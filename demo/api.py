"""The API behind the page of a Comune: open data side by side, as JSON and PNG.

    uvicorn --app-dir demo api:app --port 8010

Every answer is built with :mod:`egms_client.facts` and worded with
:func:`egms_client.check.words`, in Italian or English: a number on the page
is a number of the facts, with its release, its window and how far to trust
it. Nothing here is an alert service: a velocity is a measurement.

Next to EGMS, the page shows any other source that writes **records of open
data** (:mod:`egms_client.records`): a rain gauge, a threshold, the radar.
They are files in the folders of ``EGMS_UI_RECORDS`` (``.json``,
``.jsonl`` or ``.csv`` like the template; several folders separated by
``:``), read again when a file changes. A file with an invalid record is
refused whole, and the page says why. Nothing is imported from the libraries that wrote them.

Where the data come from (``EGMS_UI_SOURCE``):

* ``archive`` (the default when a key is set): the L3 tiles from the EGMS
  archive, with the CLMS key of ``EGMS_SERVICE_KEY_FILE`` or
  ``EGMS_SERVICE_KEY``, kept in ``EGMS_DATA_DIR`` after the first download
  (~60 MB a tile). The key is read here and never written anywhere.
* ``demo`` (the default with no key): the crops of the benchmark
  (``benchmarks/data``): Pozzuoli, Bologna, the Murge, the Foresta Umbra,
  Ancona. Outside them the answer is "no data loaded here", HTTP 404, which
  is not "not measured".

    /api/health                       is it up, and where the data come from
    /api/place?lon=&lat=&lang=        the velocity at a point, vertical and east-west
    /api/area?west=&south=&east=&north=&lang=&component=
    /api/moving?west=&south=&east=&north=&lang=&component=&threshold=
    /api/map.png?west=&south=&east=&north=&component=
                                      the velocity as a picture in EPSG:3857, for the map
    /api/sources                      the sources of the records, and the files refused
    /api/records?west=&south=&east=&north=
                                      the records in a box
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import warnings
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from egms_client import EgmsArchive, EgmsError, ServiceKey, tile_id, tiles_for_bounds
from egms_client.check import words
from egms_client.client import default_directory
from egms_client.facts import area, moving_points, to_records, velocity
from egms_client.mosaic import lonlat_to_laea, mosaic
from egms_client.records import RecordError, read

log = logging.getLogger("egms-client.api")

#: The crops of the benchmark: the data of the demo mode.
CROPS = Path(os.environ.get("EGMS_UI_CROPS", Path(__file__).parent.parent / "benchmarks" / "data"))
#: The folders of the records, separated by ":" (os.pathsep).
RECORDS = [
    Path(folder)
    for folder in os.environ.get(
        "EGMS_UI_RECORDS", str(Path(__file__).parent.parent / "examples" / "records")
    ).split(os.pathsep)
    if folder.strip()
]
#: Records one answer gives at most.
MAX_RECORDS = 1000
#: Tiles one answer may download at most (about 60 MB each).
MAX_TILES = int(os.environ.get("EGMS_UI_MAX_TILES") or 4)
#: A box at most this wide, in degrees, on either side.
MAX_DEGREES = 0.5
#: Colours of the map, mm/year, from down (red) to up (blue); in between, no motion.
STEPS = [-20.0, -10.0, -5.0, -2.0, 2.0, 5.0, 10.0, 20.0]
COLOURS = [
    (103, 0, 13),
    (203, 24, 29),
    (251, 106, 74),
    (252, 187, 161),
    (240, 240, 240),
    (158, 202, 225),
    (66, 146, 198),
    (8, 81, 156),
    (8, 48, 107),
]
#: Where there is no measurement: a light veil, because not measured is not still.
VEIL = (90, 96, 110, 70)


class OutsideDataError(LookupError):
    """The demo has no data loaded here: not the same as "not measured"."""


class Crops:
    """The demo source: the GeoTIFFs of the benchmark, offline."""

    name = "demo"

    def __init__(self, folder: Path) -> None:
        import rasterio

        self.places = []
        for source in sorted(folder.glob("*/source.json")):
            u = source.parent / "U.tif"
            if not u.exists():
                continue
            with rasterio.open(u) as tiff:
                bounds = tuple(tiff.bounds)
            release = json.loads(source.read_text())["release"]
            self.places.append((source.parent, bounds, release))
        if not self.places:
            raise OutsideDataError(f"no crops in {folder}")

    async def tiffs(
        self, box: tuple[float, ...], component: str
    ) -> tuple[list[Path], str, list[str]]:
        minx, miny, maxx, maxy = box
        found = [
            (folder, release)
            for folder, (left, bottom, right, top), release in self.places
            if left < maxx
            and right > minx
            and bottom < maxy
            and top > miny
            and (folder / f"{component}.tif").exists()
        ]
        if not found:
            raise OutsideDataError(
                "demo mode: no data loaded here (only Pozzuoli, Bologna, the Murge, the Foresta "
                "Umbra and Ancona). This is not 'not measured': set a CLMS key for the archive."
            )
        return [f / f"{component}.tif" for f, _ in found], found[0][1], []

    async def aclose(self) -> None:
        return None


class Archive:
    """The archive source: the L3 tiles over the box, downloaded once and kept."""

    name = "archive"

    def __init__(self, key: ServiceKey, folder: Path) -> None:
        self.archive = EgmsArchive(key=key)
        self.folder = folder
        self.release: str | None = None
        self.lock = asyncio.Lock()

    async def tiffs(
        self, box: tuple[float, ...], component: str
    ) -> tuple[list[Path], str, list[str]]:
        async with self.lock:
            if self.release is None:
                self.release = (await self.archive.releases())[-1]
        tiles = tiles_for_bounds(*box)
        if len(tiles) > MAX_TILES:
            raise ValueError(f"the box touches {len(tiles)} tiles; at most {MAX_TILES}")
        tiffs, absent = [], []
        for tile in tiles:
            tiff = await self.archive.fetch_tile(tile, component, self.release, self.folder)  # type: ignore[arg-type]
            if tiff is None:
                absent.append(tile_id(tile))
            else:
                tiffs.append(tiff)
        return tiffs, self.release, absent

    async def aclose(self) -> None:
        await self.archive.aclose()


class Shelf:
    """The records in the folders, read again when a file is added, changed or removed."""

    def __init__(self, folders: list[Path]) -> None:
        self.folders = folders
        self.seen: dict[Path, int] = {}
        self.items: list[dict[str, Any]] = []
        self.refused: list[dict[str, Any]] = []

    def files(self) -> list[Path]:
        return sorted(
            path
            for folder in self.folders
            if folder.is_dir()
            for path in folder.iterdir()
            if path.suffix in (".json", ".jsonl", ".csv") and path.is_file()
        )

    def load(self) -> None:
        files = self.files()
        stamp = {path: path.stat().st_mtime_ns for path in files}
        if stamp == self.seen:
            return
        items, refused = [], []
        for path in files:
            try:
                records = read(path)
            except RecordError as exc:
                refused.append({"file": path.name, "problems": exc.problems[:10]})
            except (OSError, ValueError) as exc:
                refused.append({"file": path.name, "problems": [f"not JSON: {exc}"]})
            else:
                items += [{"file": path.name, "record": r} for r in records]
        self.items, self.refused, self.seen = items, refused, stamp

    def sources(self) -> list[dict[str, Any]]:
        self.load()
        found: dict[str, dict[str, Any]] = {}
        for item in self.items:
            r = item["record"]
            s = found.setdefault(
                r["source"]["name"],
                {
                    **r["source"],
                    "made_by": [],
                    "records": 0,
                    "kinds": [],
                    "properties": [],
                    "methods": [],
                    "files": [],
                },
            )
            s["records"] += 1
            for key, value in (
                ("made_by", r["made_by"]["name"]),
                ("kinds", r["kind"]),
                ("properties", r.get("property") or r.get("question")),
                ("methods", (r["reliability"] or {}).get("method")),
                ("files", item["file"]),
            ):
                if value and value not in s[key]:
                    s[key].append(value)
        return sorted(found.values(), key=lambda s: str(s["name"]))

    def within(self, box: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        self.load()
        west, south, east, north = box
        out = []
        for item in self.items:
            w, s, e, n = bounds(item["record"]["where"])
            if w <= east and e >= west and s <= north and n >= south:
                out.append(item)
        return out[:MAX_RECORDS]


def bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    """West, south, east, north of a GeoJSON Point, Polygon or MultiPolygon."""
    points = list(_positions(geometry["coordinates"]))
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def _positions(coordinates: Any) -> Iterator[list[float]]:
    if isinstance(coordinates[0], (int, float)):
        yield coordinates
        return
    for part in coordinates:
        yield from _positions(part)


def source_from_env() -> Crops | Archive:
    """The source the environment asks for; the key is read, never logged."""
    wanted = os.environ.get("EGMS_UI_SOURCE", "").strip().lower()
    if wanted != "demo":
        try:
            key = ServiceKey.from_env()
        except (LookupError, FileNotFoundError):
            if wanted == "archive":
                raise
            log.info("no CLMS key: demo mode, on the crops of the benchmark")
        else:
            log.info("archive mode: L3 tiles from the EGMS archive")
            return Archive(key, default_directory())
    return Crops(CROPS)


def _number(request: Request, name: str, low: float, high: float) -> float:
    raw = request.query_params.get(name, "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not (low <= value <= high and math.isfinite(value)):
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _lang(request: Request) -> str:
    return "en" if request.query_params.get("lang") == "en" else "it"


def _component(request: Request) -> str:
    return "E" if request.query_params.get("component") == "E" else "U"


def _box(request: Request) -> tuple[float, float, float, float]:
    west = _number(request, "west", -32, 45)
    south = _number(request, "south", 27, 72)
    east = _number(request, "east", -32, 45)
    north = _number(request, "north", 27, 72)
    if not (west < east and south < north):
        raise ValueError("the box is west < east, south < north")
    if east - west > MAX_DEGREES or north - south > MAX_DEGREES:
        raise ValueError(f"the box is at most {MAX_DEGREES}° wide and tall")
    return west, south, east, north


def _around(lon: float, lat: float, metres: float = 5_100.0) -> tuple[float, float, float, float]:
    from egms_client.mosaic import lonlat_to_xy

    x, y = lonlat_to_xy(lon, lat)
    return x - metres, y - metres, x + metres, y + metres


async def health(request: Request) -> JSONResponse:
    source = request.app.state.source
    return JSONResponse({"ok": True, "source": source.name})


async def place(request: Request) -> JSONResponse:
    lon = _number(request, "lon", -32, 45)
    lat = _number(request, "lat", 27, 72)
    lang = _lang(request)
    source = request.app.state.source
    out: dict[str, Any] = {"source": source.name}
    for component, name in (("U", "vertical"), ("E", "east")):
        try:
            tiffs, release, _ = await source.tiffs(_around(lon, lat), component)
        except OutsideDataError:
            if component == "U":
                raise
            out[name] = None
            continue
        facts = await asyncio.to_thread(
            velocity, tiffs, lon, lat, component=component, release=release
        )
        out[name] = {
            "facts": facts,
            "text": words(facts, lang),  # type: ignore[arg-type]
            "records": to_records(facts),
        }
    return JSONResponse(out)


async def summary(request: Request) -> JSONResponse:
    box = _box(request)
    lang, component = _lang(request), _component(request)
    source = request.app.state.source
    tiffs, release, absent = await source.tiffs(lonlat_to_laea(*box), component)
    facts = await asyncio.to_thread(area, tiffs, box, component=component, release=release)
    facts["tiles_without_data"] = absent
    return JSONResponse({"source": source.name, "facts": facts, "text": words(facts, lang)})  # type: ignore[arg-type]


async def moving(request: Request) -> JSONResponse:
    box = _box(request)
    lang, component = _lang(request), _component(request)
    threshold = _number(request, "threshold", 1, 50) if "threshold" in request.query_params else 5.0
    source = request.app.state.source
    tiffs, release, absent = await source.tiffs(lonlat_to_laea(*box), component)
    facts = await asyncio.to_thread(
        moving_points,
        tiffs,
        box,
        component=component,
        release=release,
        threshold=threshold,
        limit=20,
    )
    facts["tiles_without_data"] = absent
    return JSONResponse({"source": source.name, "facts": facts, "text": words(facts, lang)})  # type: ignore[arg-type]


def picture(values: Any, inside: Any) -> Any:
    """RGBA of the velocities: colour by step, a veil where not measured, clear outside."""
    rgba = np.zeros((*values.shape, 4), dtype="uint8")
    have = ~np.isnan(values)
    steps = np.digitize(np.where(have, values, 0), STEPS)
    palette = np.array(COLOURS, dtype="uint8")
    rgba[..., :3] = palette[steps]
    rgba[..., 3] = np.where(have, 220, 0)
    rgba[~have & inside] = VEIL
    return rgba


def _png(box: tuple[float, float, float, float], tiffs: list[Path]) -> bytes:
    import rasterio
    import rasterio.errors
    from pyproj import Transformer
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    west, south, east, north = box
    laea = lonlat_to_laea(*box)
    m = mosaic(tiffs, minx=laea[0], miny=laea[1], maxx=laea[2], maxy=laea[3])
    to_web = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    (left, right), (bottom, top) = to_web.transform([west, east], [south, north])
    width = max(2, min(1200, round((right - left) / 75)))
    height = max(2, min(1200, round((top - bottom) / 75)))
    out = np.full((height, width), np.nan, dtype="float32")
    reproject(
        m.values,
        out,
        src_transform=rasterio.transform.from_origin(m.left, m.top, m.pixel, m.pixel),
        src_crs="EPSG:3035",
        src_nodata=np.nan,
        dst_transform=from_bounds(left, bottom, right, top, width, height),
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    rgba = picture(out, np.ones(out.shape, dtype=bool))
    with warnings.catch_warnings(), MemoryFile() as memory:
        # A PNG for a web map has no geotransform: Leaflet places it by the box.
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with memory.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as png:
            png.write(np.moveaxis(rgba, -1, 0))
        return bytes(memory.read())


async def map_png(request: Request) -> Response:
    box = _box(request)
    source = request.app.state.source
    tiffs, _, _ = await source.tiffs(lonlat_to_laea(*box), _component(request))
    body = await asyncio.to_thread(_png, box, tiffs)
    return Response(body, media_type="image/png", headers={"cache-control": "max-age=3600"})


async def sources(request: Request) -> JSONResponse:
    shelf: Shelf = request.app.state.shelf
    found = await asyncio.to_thread(shelf.sources)
    return JSONResponse(
        {
            "egms": request.app.state.source.name,
            "folders": [str(folder) for folder in shelf.folders],
            "sources": found,
            "refused": shelf.refused,
        }
    )


async def records(request: Request) -> JSONResponse:
    west = _number(request, "west", -180, 180)
    south = _number(request, "south", -90, 90)
    east = _number(request, "east", -180, 180)
    north = _number(request, "north", -90, 90)
    if not (west < east and south < north):
        raise ValueError("the box is west < east, south < north")
    shelf: Shelf = request.app.state.shelf
    found = await asyncio.to_thread(shelf.within, (west, south, east, north))
    return JSONResponse({"records": found, "limit": MAX_RECORDS})


async def _refused(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, OutsideDataError):
        return JSONResponse({"error": str(exc), "not_measured": False}, status_code=404)
    if isinstance(exc, EgmsError):
        return JSONResponse({"error": f"the EGMS archive: {exc}"}, status_code=502)
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _failed(_: Request, exc: Exception) -> JSONResponse:
    """Anything else: a short message for the page; the traceback stays in the server's log."""
    log.error("unexpected error: %s: %s", type(exc).__name__, exc)
    return JSONResponse(
        {"error": f"the server could not answer ({type(exc).__name__}); try again"},
        status_code=500,
    )


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    app.state.source = source_from_env()
    app.state.shelf = Shelf(RECORDS)
    try:
        yield
    finally:
        await app.state.source.aclose()


app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/place", place),
        Route("/api/area", summary),
        Route("/api/moving", moving),
        Route("/api/map.png", map_png),
        Route("/api/sources", sources),
        Route("/api/records", records),
    ],
    middleware=[Middleware(GZipMiddleware, minimum_size=1000)],
    exception_handlers={
        OutsideDataError: _refused,
        EgmsError: _refused,
        ValueError: _refused,
        LookupError: _refused,
        Exception: _failed,
    },
    lifespan=lifespan,
)
