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
The page reads one **area**: ``EGMS_UI_RADIUS_KM`` (10 by default, 1 to 20)
around ``EGMS_UI_LON``, ``EGMS_UI_LAT`` (Rione Terra when unset). In archive
mode its tiles are downloaded at startup; outside it every answer is 404,
"outside the area", so no click starts a download elsewhere.

* ``demo`` (the default with no key): the crops of the benchmark
  (``benchmarks/data``): Pozzuoli, Bologna, the Murge, the Foresta Umbra,
  Ancona. Outside them the answer is "no data loaded here", HTTP 404, which
  is not "not measured".

    /api/health                       is it up, where the data come from, and its area
    /api/place?lon=&lat=&lang=        the velocity at a point, vertical and east-west
    /api/area?west=&south=&east=&north=&lang=&component=
    /api/moving?west=&south=&east=&north=&lang=&component=&threshold=
    /api/map.png?west=&south=&east=&north=&component=
                                      the velocity as a picture in EPSG:3857, for the map
    /api/sources                      the sources of the records, and the files refused
    /api/records?west=&south=&east=&north=
                                      the records in a box
    POST /api/ingest/{sensor}         the readings of a sensor (demo/sensors.py), with
                                      its token: SenML or records
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
import warnings
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from egms_client.releases import KNOWN_RELEASES

sys.path.insert(0, str(Path(__file__).parent))
import boundaries
import sensors

log = logging.getLogger("egms-client.api")

#: The crops of the benchmark: the data of the demo mode.
CROPS = Path(
    os.environ.get("EGMS_UI_CROPS") or Path(__file__).parent.parent / "benchmarks" / "data"
)
#: The folders of the records, separated by ":" (os.pathsep).
RECORDS = [
    Path(folder)
    for folder in os.environ.get(
        "EGMS_UI_RECORDS", str(Path(__file__).parent.parent / "examples" / "records")
    ).split(os.pathsep)
    if folder.strip()
]
#: Where the back office and the sensors write: uploads/ and sensors/ (a Docker volume).
INCOMING = Path(os.environ["EGMS_UI_INCOMING"]) if os.environ.get("EGMS_UI_INCOMING") else None
#: The registry of the sensors, written by the back office (demo/admin.py).
SENSORS = Path(os.environ.get("EGMS_UI_STATE") or "/srv/state") / "sensors.json"
#: Records one answer gives at most.
MAX_RECORDS = 1000
#: How long to wait for the archive's list of releases, and when to ask again, in seconds.
ARCHIVE_WAIT_S, RETRY_S = 15.0, 600.0
#: How long one answer waits for a tile that is not on the disk yet, in seconds.
#: The download goes on in the background; the page is told which tiles are missing.
TILE_WAIT_S = 20.0
#: Tiles one answer may download at most (about 60 MB each).
MAX_TILES = int(os.environ.get("EGMS_UI_MAX_TILES") or 4)
#: A box at most this wide, in degrees, on either side.
MAX_DEGREES = 0.8
#: The radius of the area of the page around its Comune, in km: default and limits.
RADIUS_KM, MIN_RADIUS_KM, MAX_RADIUS_KM = 10.0, 1.0, 20.0
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
#: A data gap: a square of BLOCK_M where EGMS measures less than GAP_SHARE of the
#: 100 m cells. A place where open data on the ground are missing, for the Comune
#: to think about; not a danger. Amber, not red: it is not an alert.
BLOCK_M, GAP_SHARE = 1000, 0.25
GAP = (214, 140, 0, 130)


@dataclass(frozen=True)
class Area:
    """The area of the page: its Comune and a radius around it. Nothing outside is read.

    Every new area means a download from the archive (one L3 tile is about 60 MB
    and a minute), so the page works on one area, fetched at startup, and the
    map and the API stay inside it.
    """

    lon: float
    lat: float
    radius_km: float

    @property
    def box(self) -> tuple[float, float, float, float]:
        """West, south, east, north in degrees."""
        dlat = self.radius_km / 111.32
        dlon = self.radius_km / (111.32 * math.cos(math.radians(self.lat)))
        return (
            round(self.lon - dlon, 5),
            round(self.lat - dlat, 5),
            round(self.lon + dlon, 5),
            round(self.lat + dlat, 5),
        )

    def contains(self, lon: float, lat: float) -> bool:
        west, south, east, north = self.box
        return west <= lon <= east and south <= lat <= north

    def clip(self, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """The part of a box inside the area; OutsideAreaError if there is none."""
        west, south, east, north = self.box
        out = (max(box[0], west), max(box[1], south), min(box[2], east), min(box[3], north))
        if out[0] >= out[2] or out[1] >= out[3]:
            raise OutsideAreaError(self)
        return out

    def as_json(self) -> dict[str, Any]:
        west, south, east, north = self.box
        return {
            "lon": self.lon,
            "lat": self.lat,
            "radius_km": self.radius_km,
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        }


class MissingTilesError(Exception):
    """Tiles needed for the answer are not on the disk yet. Not "not measured"."""

    def __init__(self, tiles: list[str], reason: str) -> None:
        self.tiles = tiles
        super().__init__(
            f"the tiles {', '.join(tiles)} are not on the disk yet ({reason}). "
            "The page does not answer with part of the data. This is not 'not measured'."
        )


class OutsideAreaError(LookupError):
    """Outside the area of the page: not read, so not downloaded. Not "not measured"."""

    def __init__(self, area: Area) -> None:
        super().__init__(
            f"outside the area of this page ({area.radius_km:g} km around "
            f"{area.lon:.4f}, {area.lat:.4f}): it reads its own area only. "
            "This is not 'not measured'."
        )


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
        self.confirmed = False
        self.retry_at = 0.0
        self.confirming: asyncio.Task[None] | None = None
        #: One download per tile, shared by the answers that need it, and kept
        #: going when an answer stops waiting.
        self.downloads: dict[tuple[str, str, str], asyncio.Task[Path | None]] = {}
        self.why = ""
        #: What each tile is doing: checking, downloading (bytes), ready, absent, failed.
        self.status: dict[tuple[str, str], dict[str, Any]] = {}

    def _fetch(self, tile: Any, component: str, release: str) -> asyncio.Task[Path | None]:
        key = (tile_id(tile), component, release)
        task = self.downloads.get(key)
        if task is None or (task.done() and (task.cancelled() or task.exception())):
            # A failed download is tried again; a finished one is reused.
            status = self.status.setdefault(
                (key[0], component), {"tile": key[0], "component": component}
            )
            status.update(state="checking", received=0, total=0)

            def progress(_: Any, received: int, total: int) -> None:
                status.update(state="downloading", received=received, total=total)

            def finished(done: asyncio.Task[Path | None]) -> None:
                if done.cancelled() or done.exception() is not None:
                    status["state"] = "failed"
                else:
                    status["state"] = "ready" if done.result() is not None else "absent"

            task = asyncio.create_task(
                self.archive.fetch_tile(
                    tile,
                    component,  # type: ignore[arg-type]
                    release,
                    self.folder,
                    on_progress=progress,
                )
            )
            task.add_done_callback(finished)
            self.downloads[key] = task
        return task

    async def tiffs(
        self, box: tuple[float, ...], component: str, wait: float | None = TILE_WAIT_S
    ) -> tuple[list[Path], str, list[str]]:
        """The GeoTIFFs over the box. MissingTilesError when one is not there after ``wait`` s."""
        tiffs, release, absent, missing = await self.available(box, component, wait)
        if missing:
            raise MissingTilesError(missing, self.why)
        return tiffs, release, absent

    async def available(
        self, box: tuple[float, ...], component: str, wait: float | None = TILE_WAIT_S
    ) -> tuple[list[Path], str, list[str], list[str]]:
        """The GeoTIFFs on the disk after ``wait`` s, the tiles the archive does not
        have (``absent``), and those not downloaded yet (``missing``), still going on."""
        release = await self.latest()
        tiles = tiles_for_bounds(*box)
        if len(tiles) > MAX_TILES:
            raise ValueError(f"the box touches {len(tiles)} tiles; at most {MAX_TILES}")
        tasks = {tile_id(tile): self._fetch(tile, component, release) for tile in tiles}
        _, pending = await asyncio.wait(tasks.values(), timeout=wait)
        tiffs, absent, missing = [], [], []
        self.why = "downloading from the EGMS archive"
        for name, task in tasks.items():
            if task in pending:
                missing.append(name)
            elif (exc := task.exception()) is not None:
                log.warning("tile %s %s: %s: %s", name, component, type(exc).__name__, exc)
                self.why = f"the EGMS archive did not answer: {type(exc).__name__}"
                missing.append(name)
            elif (tiff := task.result()) is None:
                absent.append(name)
            else:
                tiffs.append(tiff)
        return tiffs, release, absent, missing

    async def latest(self) -> str:
        """The latest release: the latest known at once, then the archive's own.

        The archive is asked in the background, at most ARCHIVE_WAIT_S: an
        archive that is slow or down must not stop the page, and the tiles on
        disk are enough to answer. If it does not answer it is asked again
        after RETRY_S; when it lists a newer release, the next answers use it.
        """
        if self.release is None:
            self.release = KNOWN_RELEASES[-1]
        asking = self.confirming is not None and not self.confirming.done()
        if not self.confirmed and not asking and time.monotonic() >= self.retry_at:
            self.confirming = asyncio.create_task(self._confirm())
        return self.release

    async def _confirm(self) -> None:
        try:
            newest = (await asyncio.wait_for(self.archive.releases(), ARCHIVE_WAIT_S))[-1]
        except Exception as exc:
            self.retry_at = time.monotonic() + RETRY_S
            log.warning(
                "the archive did not list its releases (%s: %s): using %s, the latest known",
                type(exc).__name__,
                exc,
                self.release,
            )
            return
        if newest != self.release:
            log.info("the archive has the release %s: using it from now on", newest)
        self.release, self.confirmed = newest, True

    async def aclose(self) -> None:
        for task in [*self.downloads.values(), self.confirming]:
            if task is not None:
                task.cancel()
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


def _inside(
    laea: tuple[float, float, float, float], area: Area
) -> tuple[float, float, float, float]:
    """A box in EPSG:3035 cut to the area: near its edge, no tile beyond it is fetched."""
    a = lonlat_to_laea(*area.box)
    return max(laea[0], a[0]), max(laea[1], a[1]), min(laea[2], a[2]), min(laea[3], a[3])


async def health(request: Request) -> JSONResponse:
    source = request.app.state.source
    return JSONResponse(
        {
            "ok": True,
            "source": source.name,
            "area": request.app.state.area.as_json(),
            "startup": request.app.state.startup.as_json(),
        }
    )


async def place(request: Request) -> JSONResponse:
    lon = _number(request, "lon", -32, 45)
    lat = _number(request, "lat", 27, 72)
    if not request.app.state.area.contains(lon, lat):
        raise OutsideAreaError(request.app.state.area)
    lang = _lang(request)
    source = request.app.state.source
    out: dict[str, Any] = {"source": source.name}
    for component, name in (("U", "vertical"), ("E", "east")):
        try:
            tiffs, release, _ = await source.tiffs(
                _inside(_around(lon, lat), request.app.state.area), component
            )
        except OutsideDataError:
            if component == "U":
                raise
            out[name] = None
            continue
        facts = await asyncio.to_thread(
            velocity, tiffs, lon, lat, component=component, release=release
        )
        if component == "U":
            out["gap"] = await asyncio.to_thread(_gap_at, tiffs, lon, lat, request.app.state.land)
        out[name] = {
            "facts": facts,
            "text": words(facts, lang),  # type: ignore[arg-type]
            "records": to_records(facts),
        }
    return JSONResponse(out)


def _gap_at(
    tiffs: list[Path], lon: float, lat: float, land: Land | None = None
) -> dict[str, Any] | None:
    """The BLOCK_M square of a point: the share of its cells EGMS measures, and if it is a gap."""
    x, y = lonlat_to_laea(lon, lat, lon, lat)[:2]
    comuni = land.comuni if land else []
    value = float(gaps(tiffs, (x, y, x + 1, y + 1), comuni).share[0, 0])
    if math.isnan(value):
        return None
    return {"block_m": BLOCK_M, "measured_share": round(value, 3), "gap": value < GAP_SHARE}


async def gap_summary(request: Request) -> JSONResponse:
    """How much of a box is data gap: squares of BLOCK_M with less than GAP_SHARE measured."""
    box = request.app.state.area.clip(_box(request))
    laea = lonlat_to_laea(*box)
    source = request.app.state.source
    missing: list[str] = []
    if isinstance(source, Archive):
        tiffs, _, _, missing = await source.available(laea, "U")
    else:
        tiffs, _, _ = await source.tiffs(laea, "U")
    land: Land = request.app.state.land
    g = await asyncio.to_thread(gaps, tiffs, laea, land.comuni, land.home)

    def count(share: Any) -> dict[str, Any]:
        known = share[~np.isnan(share)]
        found = int((known < GAP_SHARE).sum())
        return {
            "blocks": int(known.size),
            "gaps": found,
            "gap_share": round(found / known.size, 3) if known.size else None,
        }

    comune = None
    if g.home is not None and land.home is not None:
        comune = {"name": land.home.name, "code": land.home.code, **count(g.share[g.home])}
    return JSONResponse(
        {
            "block_m": BLOCK_M,
            "gap_below": GAP_SHARE,
            **count(g.share),
            "land_only": bool(land.comuni),
            "comune": comune,
            "boundaries": boundaries.CREDIT if land.comuni else None,
            "missing_tiles": missing,
        }
    )


#: The squares where the ground moves most: at most HOT_TOP, with a median of
#: at least HOT_MIN mm/year up or down. Zones to follow, not an alert.
HOT_TOP, HOT_MIN = 8, 5.0


def hotspots(
    tiffs: list[Path], laea: tuple[float, ...], comuni: Sequence[boundaries.Comune] = ()
) -> list[dict[str, Any]]:
    """The BLOCK_M squares with the largest median vertical velocity, largest first.

    Only squares where EGMS measures at least GAP_SHARE of the cells (of the
    land, with the boundaries): a median of a few cells says little.
    """
    from pyproj import Transformer

    g = gaps(tiffs, laea, comuni)
    m = mosaic(
        tiffs,
        minx=g.west,
        miny=g.north - g.share.shape[0] * BLOCK_M,
        maxx=g.west + g.share.shape[1] * BLOCK_M,
        maxy=g.north,
    )
    n = round(BLOCK_M / m.pixel)
    rows, cols = g.share.shape
    values = m.values if g.land is None else np.where(g.land, m.values, np.nan)
    blocks = values.reshape(rows, n, cols, n).transpose(0, 2, 1, 3).reshape(rows, cols, n * n)
    enough = g.share >= GAP_SHARE  # NaN compares False: not known is left out
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(np.where(enough[..., None], blocks, np.nan), axis=2)
        top = np.nanmax(np.where(enough[..., None], np.abs(blocks), np.nan), axis=2)
    order = np.argsort(-np.nan_to_num(np.abs(median), nan=-1), axis=None)
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    out: list[dict[str, Any]] = []
    for flat in order[:HOT_TOP]:
        r, c = divmod(int(flat), cols)
        value = float(median[r, c])
        if math.isnan(value) or abs(value) < HOT_MIN:
            break
        x0, y1 = g.west + c * BLOCK_M, g.north - r * BLOCK_M
        xs, ys = [x0, x0 + BLOCK_M, x0 + BLOCK_M, x0, x0], [y1, y1, y1 - BLOCK_M, y1 - BLOCK_M, y1]
        lons, lats = to_lonlat.transform(xs, ys)
        lon, lat = to_lonlat.transform(x0 + BLOCK_M / 2, y1 - BLOCK_M / 2)
        out.append(
            {
                "rank": len(out) + 1,
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "median_mm_per_year": round(value, 1),
                "largest_mm_per_year": round(float(top[r, c]), 1),
                "measured_share": round(float(g.share[r, c]), 3),
                "square": [[round(a, 5), round(b, 5)] for a, b in zip(lons, lats, strict=True)],
            }
        )
    return out


async def hot(request: Request) -> JSONResponse:
    """Where the ground of the area moves most: squares to follow, ranked. Not an alert."""
    area: Area = request.app.state.area
    laea = lonlat_to_laea(*area.box)
    source = request.app.state.source
    missing: list[str] = []
    if isinstance(source, Archive):
        tiffs, release, _, missing = await source.available(laea, "U")
    else:
        tiffs, release, _ = await source.tiffs(laea, "U")
    land: Land = request.app.state.land
    found = await asyncio.to_thread(hotspots, tiffs, laea, land.comuni)
    return JSONResponse(
        {
            "component": "U",
            "block_m": BLOCK_M,
            "at_least_mm_per_year": HOT_MIN,
            "top": HOT_TOP,
            "release": release,
            "squares": found,
            "missing_tiles": missing,
            "note": "where the ground moved most in the period: zones to follow, not an alert",
        }
    )


async def boundary(request: Request) -> JSONResponse:
    """The outline of the Comune of the page, from ISTAT, for the map."""
    land: Land = request.app.state.land
    if land.home is None:
        return JSONResponse({"error": "no boundary of the Comune here"}, status_code=404)
    geometry = await asyncio.to_thread(boundaries.lonlat, land.home.geometry)
    return JSONResponse(
        {
            "type": "Feature",
            "properties": {
                "name": land.home.name,
                "code": land.home.code,
                "source": boundaries.CREDIT,
            },
            "geometry": geometry,
        },
        headers={"cache-control": "max-age=86400"},
    )


async def summary(request: Request) -> JSONResponse:
    box = request.app.state.area.clip(_box(request))
    lang, component = _lang(request), _component(request)
    source = request.app.state.source
    tiffs, release, absent = await source.tiffs(lonlat_to_laea(*box), component)
    facts = await asyncio.to_thread(area, tiffs, box, component=component, release=release)
    facts["tiles_without_data"] = absent
    return JSONResponse({"source": source.name, "facts": facts, "text": words(facts, lang)})  # type: ignore[arg-type]


async def moving(request: Request) -> JSONResponse:
    box = request.app.state.area.clip(_box(request))
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


#: A square is counted only if at least this share of it is land (in a Comune).
MIN_LAND = 0.10


@dataclass
class Gaps:
    """The share of measured cells in each BLOCK_M square, rows from north.

    NaN where it is not known: no tile on the disk, or (with the boundaries)
    a square that is mostly sea. ``land`` is the land at 100 m (None without
    the boundaries); ``home`` the squares mostly in the Comune of the page.
    """

    share: Any
    west: float
    north: float
    pixel: float
    land: Any | None
    home: Any | None


def gaps(
    tiffs: list[Path],
    laea: tuple[float, ...],
    comuni: Sequence[boundaries.Comune] = (),
    home: boundaries.Comune | None = None,
) -> Gaps:
    """The data gaps over a box in EPSG:3035: squares on the LAEA grid.

    With the Comuni of ISTAT, only land counts: EGMS never measures the sea.
    """
    import rasterio

    x0 = math.floor(laea[0] / BLOCK_M) * BLOCK_M
    y0 = math.floor(laea[1] / BLOCK_M) * BLOCK_M
    x1 = math.ceil(laea[2] / BLOCK_M) * BLOCK_M
    y1 = math.ceil(laea[3] / BLOCK_M) * BLOCK_M
    m = mosaic(tiffs, minx=x0, miny=y0, maxx=x1, maxy=y1)
    n = round(BLOCK_M / m.pixel)
    rows, cols = m.values.shape
    loaded = np.zeros((rows, cols), dtype=bool)
    for path in tiffs:
        with rasterio.open(path) as src:
            b = src.bounds
        c0, c1 = round((b.left - x0) / m.pixel), round((b.right - x0) / m.pixel)
        r0, r1 = round((y1 - b.top) / m.pixel), round((y1 - b.bottom) / m.pixel)
        loaded[max(0, r0) : max(0, r1), max(0, c0) : max(0, c1)] = True
    shape = (rows // n, n, cols // n, n)
    measured = ~np.isnan(m.values)
    land = which = None
    if comuni:
        land, which = boundaries.land(list(comuni), x0, y1, m.pixel, rows, cols)
        on_land = land.reshape(shape).sum(axis=(1, 3))
        with np.errstate(invalid="ignore", divide="ignore"):
            share = (measured & land).reshape(shape).sum(axis=(1, 3)) / on_land
        share[on_land < MIN_LAND * n * n] = np.nan
    else:
        share = measured.reshape(shape).mean(axis=(1, 3))
    share[~loaded.reshape(shape).all(axis=(1, 3))] = np.nan
    in_home = None
    if home is not None and which is not None and land is not None:
        index = list(comuni).index(home) + 1
        mine = (which == index).reshape(shape).sum(axis=(1, 3))
        with np.errstate(invalid="ignore", divide="ignore"):
            in_home = mine / land.reshape(shape).sum(axis=(1, 3)) >= 0.5
    return Gaps(share, x0, y1, m.pixel, land, in_home)


#: Where a tile is not downloaded yet: grey stripes, not the veil of "not measured".
STRIPES = (110, 110, 110, 150)


def _png(
    box: tuple[float, float, float, float],
    tiffs: list[Path],
    missing: Sequence[str] = (),
    comuni: Sequence[boundaries.Comune] = (),
    home: boundaries.Comune | None = None,
) -> bytes:
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
    # The data gaps: their unmeasured cells on land in amber; measured ones keep their colour.
    g = gaps(tiffs, laea, comuni, home)
    share, gx0, gy1 = g.share, g.west, g.north
    n = round(BLOCK_M / m.pixel)
    gap = np.repeat(np.repeat(np.where(np.isnan(share), np.nan, share < GAP_SHARE), n, 0), n, 1)
    if g.land is not None:
        gap = np.where(g.land, gap, np.nan)
    on_web = np.full((height, width), np.nan, dtype="float32")
    reproject(
        gap.astype("float32"),
        on_web,
        src_transform=rasterio.transform.from_origin(gx0, gy1, m.pixel, m.pixel),
        src_crs="EPSG:3035",
        src_nodata=np.nan,
        dst_transform=from_bounds(left, bottom, right, top, width, height),
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    rgba[(on_web == 1) & np.isnan(out)] = GAP
    if g.land is not None:
        # Outside every Comune (the sea): no veil, since EGMS never measures there.
        land_web = np.zeros((height, width), dtype="float32")
        reproject(
            g.land.astype("float32"),
            land_web,
            src_transform=rasterio.transform.from_origin(gx0, gy1, m.pixel, m.pixel),
            src_crs="EPSG:3035",
            dst_transform=from_bounds(left, bottom, right, top, width, height),
            dst_crs="EPSG:3857",
            resampling=Resampling.nearest,
        )
        rgba[(land_web == 0) & np.isnan(out)] = 0
    if missing:
        # The pixels of the map back in LAEA: those in a missing tile get stripes.
        xs = np.linspace(left, right, width, endpoint=False) + (right - left) / width / 2
        ys = np.linspace(top, bottom, height, endpoint=False) - (top - bottom) / height / 2
        gx, gy = np.meshgrid(xs, ys)
        lon, lat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform(gx, gy)
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(lon, lat)
        names = np.char.add(
            np.char.add("E", (x // 100_000).astype(int).astype(str)),
            np.char.add("N", (y // 100_000).astype(int).astype(str)),
        )
        gone = np.isin(names, list(missing))
        rows, cols = np.indices(out.shape)
        stripe = ((rows + cols) // 4) % 2 == 0
        rgba[gone] = 0
        rgba[gone & stripe] = STRIPES
    with warnings.catch_warnings(), MemoryFile() as memory:
        # A PNG for a web map has no geotransform: Leaflet places it by the box.
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with memory.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as png:
            png.write(np.moveaxis(rgba, -1, 0))
        return bytes(memory.read())


async def map_png(request: Request) -> Response:
    box = request.app.state.area.clip(_box(request))
    source = request.app.state.source
    laea, component = lonlat_to_laea(*box), _component(request)
    missing: list[str] = []
    if isinstance(source, Archive):
        # The tiles on the disk now; the others are drawn with stripes, and come later.
        tiffs, _, _, missing = await source.available(laea, component)
    else:
        tiffs, _, _ = await source.tiffs(laea, component)
    land: Land = request.app.state.land
    body = await asyncio.to_thread(_png, box, tiffs, missing, land.comuni, land.home)
    headers = {"cache-control": "no-store" if missing else "max-age=3600"}
    if missing:
        headers["x-missing-tiles"] = ",".join(missing)
    return Response(body, media_type="image/png", headers=headers)


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


async def ingest(request: Request) -> JSONResponse:
    """The readings of a sensor: SenML or records, with the sensor's own token."""
    sensor_id = request.path_params["sensor"]
    if INCOMING is None:
        return JSONResponse({"error": "this page takes no sensors"}, status_code=404)
    host = request.client.host if request.client else "?"
    if not request.app.state.pace.allow(f"{sensor_id}|{host}"):
        return JSONResponse({"error": "too many requests: one a second at most"}, status_code=429)
    if int(request.headers.get("content-length") or 0) > sensors.MAX_BODY:
        return JSONResponse({"error": f"at most {sensors.MAX_BODY} bytes"}, status_code=413)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    sensor = request.app.state.registry.check(sensor_id, token) if scheme == "Bearer" else None
    if sensor is None:
        return JSONResponse({"error": "unknown sensor, or a wrong token"}, status_code=401)
    body = await request.body()
    if len(body) > sensors.MAX_BODY:
        return JSONResponse({"error": f"at most {sensors.MAX_BODY} bytes"}, status_code=413)
    try:
        loaded = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "the body is not JSON (SenML or records)"}, status_code=400)
    records, refused = sensors.read_body(sensor, loaded)
    folder = INCOMING / "sensors"
    await asyncio.to_thread(sensors.append, folder, sensor, records)
    await asyncio.to_thread(sensors.remember_refused, folder, sensor.id, refused)
    return JSONResponse({"accepted": len(records), "refused": refused}, status_code=202)


async def _refused(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, OutsideDataError | OutsideAreaError):
        return JSONResponse({"error": str(exc), "not_measured": False}, status_code=404)
    if isinstance(exc, EgmsError):
        return JSONResponse({"error": f"the EGMS archive: {exc}"}, status_code=502)
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _missing(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, MissingTilesError)
    return JSONResponse(
        {"error": str(exc), "not_measured": False, "missing_tiles": exc.tiles},
        status_code=503,
        headers={"Retry-After": "60"},
    )


async def _failed(_: Request, exc: Exception) -> JSONResponse:
    """Anything else: a short message for the page; the traceback stays in the server's log."""
    log.error("unexpected error: %s: %s", type(exc).__name__, exc)
    return JSONResponse(
        {"error": f"the server could not answer ({type(exc).__name__}); try again"},
        status_code=500,
    )


#: At startup, a failed download of the area is tried again after this many seconds.
STARTUP_RETRY_S = 60.0
#: An attempt where tiles still wait for the archive, with no byte, after this
#: many seconds is "slow": the page says the archive does not answer, and lets
#: the visitor in with the tiles already on the disk. The download goes on.
STARTUP_PATIENCE_S = 90.0


class Land:
    """The Comuni of the area, from ISTAT: where the land is, and the Comune of the page."""

    def __init__(self) -> None:
        self.state = "waiting"  # downloading, ready, none (not here), failed
        self.received = self.total = 0
        self.comuni: list[boundaries.Comune] = []
        self.home: boundaries.Comune | None = None
        self.error: str | None = None

    @property
    def busy(self) -> bool:
        return self.state in ("waiting", "downloading")

    def as_json(self) -> dict[str, Any]:
        share = (
            0.0
            if self.state == "waiting"
            else self.received / self.total
            if self.state == "downloading" and self.total
            else 0.0
            if self.state == "downloading"
            else 1.0
        )
        return {
            "state": self.state,
            "received": self.received,
            "total": self.total,
            "share": round(share, 3),
            "comune": self.home.name if self.home else None,
            "error": self.error,
        }


async def load_land(land: Land, area: Area, folder: Path, download: bool) -> None:
    """The Comuni of the area: from the file of ISTAT, downloaded once if allowed."""
    try:
        shp = boundaries.path(folder)
        if not shp.exists():
            if not download:
                land.state = "none"
                return
            land.state = "downloading"

            def progress(received: int, total: int) -> None:
                land.received, land.total = received, total

            shp = await boundaries.fetch(folder, progress)
        land.comuni = await asyncio.to_thread(boundaries.comuni_in, shp, area.box)
        land.home = boundaries.at(land.comuni, area.lon, area.lat)
        land.state = "ready"
        log.info(
            "boundaries: %d Comuni in the area, the page's is %s",
            len(land.comuni),
            land.home.name if land.home else "none",
        )
    except Exception as exc:
        land.state, land.error = "failed", f"{type(exc).__name__}: {exc}"
        log.warning("the boundaries of ISTAT: %s; the gaps count the sea too", land.error)


class Startup:
    """The download of the area at startup, for the loading screen of the page."""

    def __init__(self, source: Any, area: Area, land: Land | None = None) -> None:
        self.source = source
        self.land = land
        tiles = [tile_id(t) for t in tiles_for_bounds(*lonlat_to_laea(*area.box))]
        self.keys = [(name, c) for c in ("U", "E") for name in tiles]
        # Demo mode reads the crops of the benchmark: nothing to download.
        self.state = "ready" if not isinstance(source, Archive) else "running"
        self.attempt = 0
        self.error: str | None = None
        self.retry_at: float | None = None
        self.started = time.monotonic()

    def as_json(self) -> dict[str, Any]:
        status = getattr(self.source, "status", {})
        tiles = []
        for name, component in self.keys:
            s = status.get((name, component), {"state": "waiting", "received": 0, "total": 0})
            share = (
                1.0
                if s["state"] in ("ready", "absent")
                else s["received"] / s["total"]
                if s["state"] == "downloading" and s["total"]
                else 0.0
            )
            tiles.append({"tile": name, "component": component, **s, "share": round(share, 3)})
        bounds = self.land.as_json() if self.land else None
        parts = [t["share"] for t in tiles] + ([bounds["share"]] if bounds else [])
        ready = self.state == "ready" and not (self.land and self.land.busy)
        done = 1.0 if ready else sum(parts) / len(parts)
        retry = None if self.retry_at is None else max(0, round(self.retry_at - time.monotonic()))
        state, error = self.state, self.error
        stuck = [t for t in tiles if t["state"] in ("waiting", "checking")]
        if state == "running" and stuck and time.monotonic() - self.started > STARTUP_PATIENCE_S:
            state = "slow"
            error = error or "the Copernicus archive does not answer"
        if state == "ready" and not ready:
            state = "running"
        return {
            "state": state,
            "ready": ready,
            "boundaries": bounds,
            "share": round(done, 3),
            "attempt": self.attempt,
            "error": error,
            "retry_in_s": retry,
            "tiles": tiles,
        }


async def prefetch(
    source: Archive,
    area: Area,
    wait: float = STARTUP_RETRY_S,
    tries: int | None = None,
    startup: Startup | None = None,
) -> bool:
    """The tiles of the area of the page, at startup: no visitor waits for a download.

    One L3 tile is about 60 MB, and the archive takes about a minute for it.
    In the background, and only in archive mode. A failure is logged, not
    raised, and tried again after ``wait`` seconds until every tile is on the
    disk (``tries`` limits the attempts; None: until it works). True when ready.
    """
    left = ["U", "E"]
    attempt = 0
    startup = startup or Startup(source, area)
    while True:
        attempt += 1
        startup.attempt, startup.state, startup.retry_at = attempt, "running", None
        startup.started = time.monotonic()
        # Both components at once: the bar moves for all the tiles together.
        results = await asyncio.gather(
            *(source.tiffs(lonlat_to_laea(*area.box), c, wait=None) for c in left),
            return_exceptions=True,
        )
        for component, result in zip(list(left), results, strict=True):
            if not isinstance(result, BaseException):
                left.remove(component)
                continue
            exc = result
            startup.error = f"{type(exc).__name__}: {exc}"
            log.warning(
                "prefetch %s of the area (attempt %d): %s: %s; trying again in %g s",
                component,
                attempt,
                type(exc).__name__,
                exc,
                wait,
            )
        if not left:
            log.info("prefetch: the tiles of the area %s are ready", area.box)
            startup.state, startup.error = "ready", None
            return True
        if tries is not None and attempt >= tries:
            startup.state = "failed"
            return False
        startup.state, startup.retry_at = "waiting", time.monotonic() + wait
        await asyncio.sleep(wait)


#: Where the page opens when no place is set: Rione Terra, Pozzuoli (demo/web/lib/start.ts).
DEFAULT_PLACE = (14.1205, 40.8225)


def area_from_env() -> Area:
    """The area of the page: EGMS_UI_LON, EGMS_UI_LAT and EGMS_UI_RADIUS_KM (10 by default)."""
    place = _place_from_env()
    if place is None:
        raise ValueError("EGMS_UI_LON and EGMS_UI_LAT: both, as degrees inside Europe")
    raw = (os.environ.get("EGMS_UI_RADIUS_KM") or "").replace(",", ".").strip()
    radius = float(raw) if raw else RADIUS_KM
    if not MIN_RADIUS_KM <= radius <= MAX_RADIUS_KM:
        raise ValueError(f"EGMS_UI_RADIUS_KM is between {MIN_RADIUS_KM:g} and {MAX_RADIUS_KM:g}")
    return Area(*place, radius)


def _place_from_env() -> tuple[float, float] | None:
    lon_text, lat_text = os.environ.get("EGMS_UI_LON") or "", os.environ.get("EGMS_UI_LAT") or ""
    if not lon_text.strip() and not lat_text.strip():
        return DEFAULT_PLACE
    try:
        lon, lat = float(lon_text.replace(",", ".")), float(lat_text.replace(",", "."))
    except ValueError:
        return None
    return (lon, lat) if -32 <= lon <= 45 and 27 <= lat <= 72 else None


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    # uvicorn sets up its own loggers only: ours too, so the mode and the prefetch show.
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    app.state.area = area_from_env()
    log.info("the area of the page: %s", app.state.area.as_json())
    app.state.source = source_from_env()
    warm = None
    app.state.land = Land()
    archive_mode = isinstance(app.state.source, Archive)
    folder = app.state.source.folder if archive_mode else default_directory()
    app.state.startup = Startup(app.state.source, app.state.area, app.state.land)
    if archive_mode:
        # The boundaries come with the tiles; in demo mode only a file already there.
        boundaries_task = asyncio.create_task(
            load_land(app.state.land, app.state.area, folder, True)
        )
    else:
        await load_land(app.state.land, app.state.area, folder, False)
    if archive_mode:
        warm = asyncio.create_task(
            prefetch(app.state.source, app.state.area, startup=app.state.startup)
        )
    incoming = [INCOMING / "uploads", INCOMING / "sensors"] if INCOMING else []
    app.state.shelf = Shelf([*RECORDS, *incoming])
    app.state.registry = sensors.Registry(SENSORS)
    app.state.pace = sensors.Pace()
    try:
        yield
    finally:
        if warm is not None:
            warm.cancel()
        if archive_mode:
            boundaries_task.cancel()
        await app.state.source.aclose()


app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/place", place),
        Route("/api/area", summary),
        Route("/api/moving", moving),
        Route("/api/map.png", map_png),
        Route("/api/gaps", gap_summary),
        Route("/api/boundary", boundary),
        Route("/api/hotspots", hot),
        Route("/api/sources", sources),
        Route("/api/records", records),
        Route("/api/ingest/{sensor}", ingest, methods=["POST"]),
    ],
    middleware=[Middleware(GZipMiddleware, minimum_size=1000)],
    exception_handlers={
        OutsideDataError: _refused,
        OutsideAreaError: _refused,
        MissingTilesError: _missing,
        EgmsError: _refused,
        ValueError: _refused,
        LookupError: _refused,
        Exception: _failed,
    },
    lifespan=lifespan,
)
