"""The boundaries of the Comuni, from ISTAT: where the land is, and where the Comune is.

EGMS never measures the sea, so a square of sea would look like a data gap.
The boundaries of the Comuni follow the coast: the page counts gaps only on
land, and can count them for the Comune itself. The file is ISTAT's
generalised boundaries (about 10 MB), downloaded once and kept with the tiles.

    Confini delle unità amministrative a fini statistici, al 1 gennaio 2025.
    ISTAT, licence CC BY 4.0.

Nothing here raises if the file cannot be had: the page then counts gaps
without the mask, and says so.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

#: ISTAT's generalised boundaries of 1 January 2025, CC BY 4.0.
URL = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/2025/Limiti01012025_g.zip"
)
STEM = "Com01012025_g_WGS84"
#: Their projection: WGS 84 / UTM zone 32N.
CRS = "EPSG:32632"
CREDIT = "Confini dei Comuni: ISTAT, al 1 gennaio 2025, CC BY 4.0"
LICENCE = "CC-BY-4.0"


@dataclass(frozen=True)
class Comune:
    code: str
    name: str
    #: GeoJSON geometry in the projection of ISTAT (CRS).
    geometry: dict[str, Any]


def path(folder: Path) -> Path:
    return folder / "istat" / f"{STEM}.shp"


async def fetch(
    folder: Path, progress: Callable[[int, int], None] | None = None, timeout: float = 120.0
) -> Path:
    """The shapefile of the Comuni in ``folder/istat``, downloaded once."""
    shp = path(folder)
    if shp.exists():
        return shp
    data = bytearray()
    async with (
        httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client,
        client.stream("GET", URL) as response,
    ):
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        async for chunk in response.aiter_bytes(1 << 16):
            data.extend(chunk)
            if progress is not None:
                progress(len(data), total)
    shp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
        for name in archive.namelist():
            if Path(name).stem == STEM:
                target = shp.with_suffix(Path(name).suffix)
                partial = target.with_name(target.name + ".part")
                partial.write_bytes(archive.read(name))
                partial.replace(target)
    if not shp.exists():
        raise FileNotFoundError(f"{STEM}.shp is not in {URL}")
    return shp


def comuni_in(shp: Path, box: tuple[float, float, float, float]) -> list[Comune]:
    """The Comuni whose bounding box meets ``box`` (west, south, east, north, degrees)."""
    import shapefile
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    xs, ys = to_utm.transform([box[0], box[2], box[0], box[2]], [box[1], box[1], box[3], box[3]])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    found = []
    with shapefile.Reader(str(shp), encoding="latin-1") as reader:
        for i, record in enumerate(reader.iterRecords()):
            shape = reader.shape(i)
            bx0, by0, bx1, by1 = shape.bbox
            if bx0 > x1 or bx1 < x0 or by0 > y1 or by1 < y0:
                continue
            found.append(
                Comune(
                    code=str(record["PRO_COM_T"]),
                    name=str(record["COMUNE"]),
                    geometry=shape.__geo_interface__,
                )
            )
    return found


def at(comuni: list[Comune], lon: float, lat: float) -> Comune | None:
    """The Comune that holds a point, if any."""
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(lon, lat)
    for comune in comuni:
        if _contains(comune.geometry, x, y):
            return comune
    return None


def _contains(geometry: dict[str, Any], x: float, y: float) -> bool:
    polygons = (
        geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    )
    for rings in polygons:
        if _inside(rings[0], x, y) and not any(_inside(hole, x, y) for hole in rings[1:]):
            return True
    return False


def _inside(ring: list[Any], x: float, y: float) -> bool:
    """Ray casting: is (x, y) inside the ring?"""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def lonlat(geometry: dict[str, Any]) -> dict[str, Any]:
    """A geometry of ISTAT in degrees, for the map."""
    from rasterio.warp import transform_geom

    return dict(transform_geom(CRS, "EPSG:4326", geometry, precision=5))


def land(
    comuni: list[Comune], west: float, north: float, pixel: float, rows: int, cols: int
) -> tuple[Any, Any]:
    """Two grids in EPSG:3035: on land (in a Comune), and in each Comune (its index + 1)."""
    import numpy as np
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.warp import transform_geom

    transform = from_origin(west, north, pixel, pixel)
    shapes = [(transform_geom(CRS, "EPSG:3035", c.geometry), i + 1) for i, c in enumerate(comuni)]
    if not shapes:
        empty = np.zeros((rows, cols), dtype="int32")
        return empty.astype(bool), empty
    which = rasterize(shapes, out_shape=(rows, cols), transform=transform, fill=0, dtype="int32")
    return which > 0, which
