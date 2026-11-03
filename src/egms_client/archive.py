"""Searching and downloading Ortho L3 tiles from the EGMS archive.

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
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

from egms_client.errors import EgmsError

ARCHIVE_URL = "https://egms.land.copernicus.eu/insar-api/archive"

Component = Literal["U", "E"]
COMPONENTS: tuple[Component, ...] = ("U", "E")
PRODUCT_TYPES: dict[Component, str] = {"U": "ORTHO-UP", "E": "ORTHO-EAST"}

#: Side of an Ortho L3 tile, in EPSG:3035 metres.
TILE_SIZE_M = 100_000

#: (E, N): the lower-left corner in hundreds of kilometres.
Tile = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Hit:
    """One downloadable file of a search."""

    filename: str
    filesize: int
    tile_id: str
    release: str
    version: str
    product_type: str

    @property
    def stem(self) -> str:
        """The file name without ``.zip``: also the name of the GeoTIFF inside."""
        return self.filename.removesuffix(".zip")


@dataclass(frozen=True, slots=True)
class Search:
    """A search id and its hits. The id is what the download URL needs."""

    id: str
    hits: list[Hit]


def tile_id(tile: Tile) -> str:
    """``(47, 19)`` → ``"E47N19"``."""
    e, n = tile
    return f"E{e}N{n}"


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


def parse_releases(body: bytes | str) -> list[str]:
    """The release names, oldest first. :class:`EgmsError` when not logged in."""
    data = _json(body)
    if not isinstance(data, list):
        raise EgmsError(f"EGMS archive refused the release list: {_message(data)}")
    return sorted(str(r) for r in data)


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
    hits = [
        Hit(
            filename=str(h["filename"]),
            filesize=int(h.get("filesize") or 0),
            tile_id=str(h.get("tileId") or ""),
            release=str(h.get("release") or ""),
            version=str(h.get("version") or ""),
            product_type=str(h.get("productType") or ""),
        )
        for h in data.get("hits") or []
    ]
    return Search(id=str(data["id"]), hits=hits)


def latest_hit(search: Search) -> Hit | None:
    """The hit with the highest sub-release, or ``None`` if there is none."""
    return max(search.hits, key=lambda h: _sub_release(h.version), default=None)


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
