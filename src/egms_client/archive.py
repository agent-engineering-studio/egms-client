"""Searching and downloading from the EGMS archive: Ortho L3 tiles and L2 bursts.

The Ortho L3 product is the ground velocity resampled on a 100 m grid in
EPSG:3035 (LAEA Europe), in 100 km tiles, one per component: ``U``
(vertical) and ``E`` (east-west). A tile is named by its lower-left corner
in hundreds of kilometres: E47N19 covers 4,700,000-4,800,000 m east and
1,900,000-2,000,000 m north. Each ZIP (~60 MB) holds a CSV of time series
(~245 MB once unpacked) and a GeoTIFF of the mean velocity (~4 MB).

Downloading needs the ``id`` of a **search**, not the bearer token: the
download URL carries ``?id=<search id>``, and that id expires. An expired or
unknown id is answered with HTTP 401 and a plain-text message.

Verified against the live archive on 2026-11-03:

* releases are named ``2020-2025`` in the API and ``2020_2025`` in file
  names; a release is a window of years, and a new one may extend the window
  rather than slide it (2020-2024 was followed by 2020-2025, not 2021-2025);
* a tile at sea or outside coverage is answered with ``status: false`` and
  ``Invalid tile ID: 'E40N15'``, not with an empty search;
* each hit carries its own ``filename`` and ``version`` (``2020_2025_1``):
  the trailing number is a sub-release, so read the name from the hit
  instead of building it.

Beyond Ortho L3 the archive serves two levels of measurement points, one
ZIP per Sentinel-1 burst (a CSV of points with their time series and an XML
of metadata): L2A (``BASIC``) and L2B (``CALIBRATED``, tied to GNSS).
Verified on 2026-11-03:

* ``GET /levels`` names them ``L2A``, ``L2B``, ``L3``; the lower-case
  ``L2a`` of the file names is refused as ``Invalid level``;
* a search needs a place: ``bbox``, ``tileId``, ``swath``, ``burstCycle``
  or ``relativeOrbit``, else ``You must provide either bbox, ...``;
* ``bbox`` is ``[[west, south], [east, north]]`` in degrees, for every level;
  any other shape is answered ``An error occurred processing the search``,
  and an area of 7° x 7° is ``Requested area is too large`` (5° x 5° passes);
* ``relativeOrbit`` is a string of three digits: ``"022"`` works, ``22`` and
  ``"22"`` are ``Invalid relative orbit``;
* one relative orbit is ~400 bursts and ~90 GB per level.
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from egms_client.errors import EgmsError

ARCHIVE_URL = "https://egms.land.copernicus.eu/insar-api/archive"

_CHUNK = 1 << 20

Component = Literal["U", "E"]
COMPONENTS: tuple[Component, ...] = ("U", "E")
PRODUCT_TYPES: dict[Component, str] = {"U": "ORTHO-UP", "E": "ORTHO-EAST"}

#: Side of an Ortho L3 tile, in EPSG:3035 metres.
TILE_SIZE_M = 100_000

#: (E, N): the lower-left corner in hundreds of kilometres.
Tile = tuple[int, int]

Level = Literal["L2A", "L2B", "L3"]
LEVELS: tuple[Level, ...] = ("L2A", "L2B", "L3")

Direction = Literal["ascending", "descending"]

#: (west, south, east, north) in degrees.
LonLatBounds = tuple[float, float, float, float]

#: Side of the largest box searched at once, in degrees: 5° x 5° passes,
#: 7° x 7° is "Requested area is too large".
MAX_BBOX_DEG = 5.0


@dataclass(frozen=True, slots=True)
class Query:
    """What to look for: levels, a release and at least one place.

    ``bbox`` works for every level; ``tile`` is for L3; ``relative_orbit``,
    ``burst_cycle`` and ``swath`` are for L2A and L2B. ``product_type``
    narrows L3 to ``ORTHO-UP`` or ``ORTHO-EAST``.
    """

    levels: tuple[Level, ...]
    release: str
    bbox: LonLatBounds | None = None
    tile: Tile | None = None
    relative_orbit: int | str | None = None
    burst_cycle: int | str | None = None
    swath: str | None = None
    direction: Direction | None = None
    product_type: str | None = None


@dataclass(frozen=True, slots=True)
class Hit:
    """One downloadable file of a search. The L2 fields are empty for L3."""

    filename: str
    filesize: int
    tile_id: str
    release: str
    version: str
    product_type: str
    level: str = ""
    path: str = ""
    bbox: LonLatBounds | None = None
    burst_id: str = ""
    relative_orbit: str = ""
    burst_cycle: str = ""
    swath: str = ""
    direction: str = ""
    polarization: str = ""
    #: The file's outline, ``(lon, lat)`` corners: a burst is a tilted
    #: parallelogram, so its ``bbox`` covers more than the burst does.
    footprint: tuple[tuple[float, float], ...] = ()

    def covers(self, lon: float, lat: float) -> bool:
        """True if the point is inside the footprint (inside the bbox if there is none)."""
        if not self.footprint:
            if self.bbox is None:
                return False
            west, south, east, north = self.bbox
            return west <= lon <= east and south <= lat <= north
        inside = False
        corners = self.footprint
        for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1], strict=True):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
        return inside

    @property
    def stem(self) -> str:
        """The file name without ``.zip``: also the name of every file inside."""
        return self.filename.removesuffix(".zip")

    @property
    def family(self) -> str:
        """The name up to the sub-release: hits of one family are versions of one file."""
        return self.stem.rsplit("_", 1)[0]


@dataclass(frozen=True, slots=True)
class Search:
    """A search id and its hits. The id is what the download URL needs."""

    id: str
    hits: list[Hit]


def tile_id(tile: Tile) -> str:
    """``(47, 19)`` → ``"E47N19"``."""
    e, n = tile
    return f"E{e}N{n}"


def parse_tile_id(text: str) -> Tile:
    """``"E47N19"`` → ``(47, 19)``; ``ValueError`` for anything else."""
    match = re.fullmatch(r"E(\d+)N(\d+)", text.strip().upper())
    if match is None:
        raise ValueError(f"not a tile id: {text!r} (expected like E47N19)")
    return int(match[1]), int(match[2])


def tiles_for_bounds(minx: float, miny: float, maxx: float, maxy: float) -> list[Tile]:
    """The tiles covering a rectangle in EPSG:3035 metres."""
    e0, e1 = math.floor(minx / TILE_SIZE_M), math.floor(maxx / TILE_SIZE_M)
    n0, n1 = math.floor(miny / TILE_SIZE_M), math.floor(maxy / TILE_SIZE_M)
    return [(e, n) for e in range(e0, e1 + 1) for n in range(n0, n1 + 1)]


def api_release(release: str) -> str:
    """``2020_2025`` (file names) or ``2020-2025`` → ``2020-2025`` (the API's form)."""
    return release.replace("_", "-")


def file_release(release: str) -> str:
    """``2020-2025`` or ``2020_2025`` → ``2020_2025`` (the file names' form)."""
    return release.replace("-", "_")


def tile_prefix(tile: Tile, component: Component, release: str) -> str:
    """The file name up to the sub-release: ``EGMS_L3_E47N19_100km_U_2020_2025_``."""
    return f"EGMS_L3_{tile_id(tile)}_100km_{component}_{file_release(release)}_"


def search_body(tile: Tile, component: Component, release: str) -> dict[str, Any]:
    """The JSON body of ``POST {archive}/search`` for one Ortho L3 tile."""
    return {
        "tileId": tile_id(tile),
        "releases": [api_release(release)],
        "levels": ["L3"],
        "productType": PRODUCT_TYPES[component],
    }


def query_body(query: Query) -> dict[str, Any]:
    """The JSON body of ``POST {archive}/search`` for a :class:`Query`.

    ``ValueError`` when the query has no place, which the archive would refuse.
    """
    if not query.levels:
        raise ValueError("a query needs at least one level")
    body: dict[str, Any] = {
        "releases": [api_release(query.release)],
        "levels": list(query.levels),
    }
    if query.bbox is not None:
        west, south, east, north = query.bbox
        if not (west < east and south < north):
            raise ValueError(f"bbox is (west, south, east, north): {query.bbox}")
        body["bbox"] = [[west, south], [east, north]]
    if query.tile is not None:
        body["tileId"] = tile_id(query.tile)
    if query.relative_orbit is not None:
        body["relativeOrbit"] = f"{int(query.relative_orbit):03d}"
    if query.burst_cycle is not None:
        body["burstCycle"] = f"{int(query.burst_cycle):04d}"
    if query.swath is not None:
        body["swath"] = query.swath.upper()
    if query.direction is not None:
        body["direction"] = query.direction
    if query.product_type is not None:
        body["productType"] = query.product_type
    if body.keys() <= {"releases", "levels", "direction", "productType"}:
        raise ValueError("a query needs a place: bbox, tile, relative_orbit, burst_cycle or swath")
    return body


def split_bbox(bbox: LonLatBounds, step: float = MAX_BBOX_DEG) -> list[LonLatBounds]:
    """A box cut into pieces no larger than ``step`` degrees a side, west to east."""
    west, south, east, north = bbox
    nx, ny = math.ceil((east - west) / step), math.ceil((north - south) / step)
    dx, dy = (east - west) / nx, (north - south) / ny
    return [
        (west + i * dx, south + j * dy, west + (i + 1) * dx, south + (j + 1) * dy)
        for i in range(nx)
        for j in range(ny)
    ]


def parse_releases(body: bytes | str) -> list[str]:
    """The release names, oldest first. :class:`EgmsError` when not logged in."""
    return sorted(parse_names(body, "release list"))


def parse_names(body: bytes | str, what: str) -> list[str]:
    """A JSON list of names (``/levels``, ``/bursts``), in the archive's order."""
    data = _json(body)
    if not isinstance(data, list):
        raise EgmsError(f"EGMS archive refused the {what}: {_message(data)}")
    return [str(r) for r in data]


def parse_search(body: bytes | str) -> Search | None:
    """The search, or ``None`` when the tile does not exist (sea, no coverage).

    Raises :class:`EgmsError` for any other refusal, such as a missing login.
    """
    data = _json(body)
    if not isinstance(data, dict):
        raise EgmsError(f"EGMS archive returned an unexpected search: {str(body)[:200]}")
    if not data.get("status"):
        if str(data.get("message") or "").startswith("Invalid tile ID"):
            return None
        raise EgmsError(f"EGMS archive refused the search: {_message(data)}")
    hits = [_hit(h) for h in data.get("hits") or []]
    return Search(id=str(data["id"]), hits=hits)


def latest_hit(search: Search) -> Hit | None:
    """The hit with the highest sub-release, or ``None`` if there is none."""
    return max(search.hits, key=lambda h: _sub_release(h.version), default=None)


def latest_hits(hits: Iterable[Hit]) -> list[Hit]:
    """One hit per file, the highest sub-release of each, in their first order."""
    best: dict[str, Hit] = {}
    for hit in hits:
        known = best.get(hit.family)
        if known is None or _sub_release(hit.version) > _sub_release(known.version):
            best[hit.family] = hit
    return list(best.values())


def download_url(archive_url: str, hit: Hit) -> str:
    """The URL to GET with ``params={"id": search.id}``."""
    return f"{archive_url.rstrip('/')}/download/{hit.filename}"


def check_download(status_code: int, body: bytes) -> bytes:
    """The ZIP, or :class:`EgmsError` (401 means the search id expired: search again)."""
    if status_code != 200:
        text = body[:200].decode("utf-8", "replace")
        raise EgmsError(f"EGMS download refused (HTTP {status_code}): {text}")
    return body


def extract_tiff(archive: bytes, hit: Hit) -> bytes:
    """The mean-velocity GeoTIFF from a tile's ZIP; the CSV is left inside."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        try:
            return z.read(f"{hit.stem}.tiff")
        except KeyError as exc:
            raise EgmsError(f"{hit.filename} has no {hit.stem}.tiff: {z.namelist()}") from exc


def extract(archive: Path, suffixes: Iterable[str], directory: Path) -> list[Path]:
    """The files ``<stem>.<suffix>`` of a downloaded ZIP, written to ``directory``.

    Each is streamed to a ``.part`` file and renamed, so a file that exists is
    whole. :class:`EgmsError` if the ZIP lacks one of them.
    """
    stem = archive.name.removesuffix(".zip")
    paths = []
    with zipfile.ZipFile(archive) as z:
        for suffix in suffixes:
            name = f"{stem}.{suffix}"
            try:
                info = z.getinfo(name)
            except KeyError as exc:
                raise EgmsError(f"{archive.name} has no {name}: {z.namelist()}") from exc
            path = directory / name
            partial = path.with_name(f"{name}.part")
            with z.open(info) as src, partial.open("wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
            partial.rename(path)
            paths.append(path)
    return paths


def _hit(h: dict[str, Any]) -> Hit:
    def text(key: str) -> str:
        return str(h.get(key) or "")

    try:
        (west, south), (east, north) = h["bbox"]
        bbox: LonLatBounds | None = (float(west), float(south), float(east), float(north))
    except (KeyError, TypeError, ValueError):
        bbox = None
    try:
        footprint = tuple((float(x), float(y)) for x, y in h.get("poly") or ())
    except (TypeError, ValueError):
        footprint = ()
    return Hit(
        filename=str(h["filename"]),
        filesize=int(h.get("filesize") or 0),
        tile_id=text("tileId"),
        release=text("release"),
        version=text("version"),
        product_type=text("productType"),
        level=text("productLevel"),
        path=text("path"),
        bbox=bbox,
        burst_id=text("burstId"),
        relative_orbit=text("relativeOrbit"),
        burst_cycle=text("burstCycle"),
        swath=text("swath"),
        direction=text("direction"),
        polarization=text("polarization"),
        footprint=footprint,
    )


def _sub_release(version: str) -> int:
    tail = version.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _json(body: bytes | str) -> Any:
    try:
        return json.loads(body)
    except ValueError as exc:
        raise EgmsError(f"EGMS archive did not return JSON: {str(body)[:200]!r}") from exc


def _message(data: Any) -> str:
    return str(data.get("message")) if isinstance(data, dict) else str(data)[:200]
