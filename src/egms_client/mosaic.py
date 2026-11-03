"""Ortho L3 tiles pasted onto one grid. Needs the ``raster`` extra.

The tiles sit on a common 100 m grid in EPSG:3035, so a mosaic is a copy of
each tile into its place, with no resampling.

Some tiles declare their CRS as ``IGNF:ETRS89LAEA`` instead of
``EPSG:3035``: the same projection under the French IGN's name. In the
2020-2025 release that is E43N26, E44N26, E45N26 and E46N26 (in 2020-2024,
E42N26 and E43N26). Comparing CRS by name rejects them; :func:`is_laea`
compares the parameters.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Pixel size of the Ortho L3 product, in metres.
PIXEL_M = 100.0


@dataclass(frozen=True, slots=True)
class Mosaic:
    """A float32 array (NaN where there is no data) and its upper-left corner."""

    values: Any
    left: float
    top: float
    pixel: float = PIXEL_M


def is_laea(crs: Any) -> bool:
    """True if a rasterio CRS is LAEA Europe (EPSG:3035) by its parameters."""
    from pyproj import CRS

    with warnings.catch_warnings():
        # pyproj warns that a PROJ string drops information: only the
        # parameters are wanted here.
        warnings.simplefilter("ignore", UserWarning)
        return bool(CRS.from_wkt(crs.to_wkt()).to_proj4() == CRS.from_epsg(3035).to_proj4())


def mosaic(tiffs: Iterable[Path], *, minx: float, miny: float, maxx: float, maxy: float) -> Mosaic:
    """Paste the tiles of one component over a rectangle in EPSG:3035 metres.

    The rectangle widens to the 100 m grid. Pixels no tile covers, and the
    tiles' own nodata, are NaN. A tile in another projection raises
    ``ValueError``.
    """
    import numpy as np
    import rasterio

    x0 = math.floor(minx / PIXEL_M) * PIXEL_M
    y0 = math.floor(miny / PIXEL_M) * PIXEL_M
    x1 = math.ceil(maxx / PIXEL_M) * PIXEL_M
    y1 = math.ceil(maxy / PIXEL_M) * PIXEL_M
    rows = round((y1 - y0) / PIXEL_M)
    cols = round((x1 - x0) / PIXEL_M)
    out = np.full((rows, cols), np.nan, dtype="float32")
    for path in tiffs:
        with rasterio.open(path) as src:
            if not is_laea(src.crs):
                raise ValueError(f"{path.name}: not LAEA Europe ({src.crs})")
            band = src.read(1).astype("float32")
            if src.nodata is not None:
                band[band == src.nodata] = np.nan
            col = round((src.bounds.left - x0) / PIXEL_M)
            row = round((y1 - src.bounds.top) / PIXEL_M)
        sr, sc = max(0, -row), max(0, -col)
        dr, dc = max(0, row), max(0, col)
        h = min(band.shape[0] - sr, rows - dr)
        w = min(band.shape[1] - sc, cols - dc)
        if h <= 0 or w <= 0:
            continue
        piece = band[sr : sr + h, sc : sc + w]
        target = out[dr : dr + h, dc : dc + w]
        valid = ~np.isnan(piece)
        target[valid] = piece[valid]
    return Mosaic(values=out, left=x0, top=y1)
