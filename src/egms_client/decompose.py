"""Maps from L2 points: gridding, and ascending + descending into vertical and east-west.

L2A / L2B points measure motion along the satellite's line of sight (LOS).
Each point carries the LOS unit vector, from the ground to the satellite:
``los_east``, ``los_north``, ``los_up`` (descending, looking west: east
~ +0.65, up ~ +0.75; ascending, looking east: east ~ -0.69, up ~ +0.72). A
positive ``mean_velocity`` moves towards the satellite, so for a ground
motion ``(E, N, U)``::

    v_los = E * los_east + N * los_north + U * los_up

Both Sentinel-1 orbits fly almost north-south, so ``los_north`` is small
(~0.1) and north motion is left out, as EGMS does for L3. With one
ascending and one descending grid over the same cells, the two equations
give ``U`` and ``E`` cell by cell. This is what L3 does on its own 100 m
grid, here on any grid and any area.

Only numpy is needed; frames are anything indexable by column name
(a pandas DataFrame from :func:`egms_client.tables.read_csv`, for example).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from egms_client.mosaic import Mosaic

#: Points less coherent than this are left out: their series is mostly noise.
MIN_COHERENCE = 0.7


@dataclass(frozen=True, slots=True)
class LosGrid:
    """L2 points averaged per cell: LOS velocity, LOS direction, and how many points.

    ``velocity`` is a :class:`Mosaic` (mm/year, NaN where no point);
    ``east`` and ``up`` are the mean LOS unit vector components per cell;
    ``count`` the points per cell.
    """

    velocity: Mosaic
    east: Any
    up: Any
    count: Any


def grid_los(
    frame: Any,
    *,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    pixel: float = 100.0,
    min_coherence: float = MIN_COHERENCE,
) -> LosGrid:
    """Average the points of one geometry onto a grid in EPSG:3035 metres.

    The rectangle widens to the ``pixel`` grid, aligned like L3 when the
    pixel is 100 m. Points outside it, or with ``temporal_coherence`` below
    ``min_coherence``, are left out.
    """
    import numpy as np

    x0 = math.floor(minx / pixel) * pixel
    y1 = math.ceil(maxy / pixel) * pixel
    cols = round((math.ceil(maxx / pixel) * pixel - x0) / pixel)
    rows = round((y1 - math.floor(miny / pixel) * pixel) / pixel)
    x = np.asarray(frame["easting"], dtype="float64")
    y = np.asarray(frame["northing"], dtype="float64")
    keep = np.asarray(frame["temporal_coherence"], dtype="float64") >= min_coherence
    col = np.floor((x - x0) / pixel).astype("int64")
    row = np.floor((y1 - y) / pixel).astype("int64")
    keep &= (col >= 0) & (col < cols) & (row >= 0) & (row < rows)
    cell = row[keep] * cols + col[keep]
    size = rows * cols
    count = np.bincount(cell, minlength=size).astype("float64")

    def mean(column: str) -> Any:
        values = np.asarray(frame[column], dtype="float64")[keep]
        total = np.bincount(cell, weights=values, minlength=size)
        with np.errstate(invalid="ignore", divide="ignore"):
            return (total / count).reshape(rows, cols).astype("float32")

    return LosGrid(
        velocity=Mosaic(values=mean("mean_velocity"), left=x0, top=y1, pixel=pixel),
        east=mean("los_east"),
        up=mean("los_up"),
        count=count.reshape(rows, cols).astype("int32"),
    )


def decompose(ascending: LosGrid, descending: LosGrid) -> tuple[Mosaic, Mosaic]:
    """Vertical and east-west velocity (mm/year) from two LOS grids of the same cells.

    NaN where either geometry has no point. ``ValueError`` if the grids are
    not the same, or if both look the same way (two ascending grids cannot
    be separated).
    """
    import numpy as np

    va, vd = ascending.velocity, descending.velocity
    if (va.values.shape, va.left, va.top, va.pixel) != (vd.values.shape, vd.left, vd.top, vd.pixel):
        raise ValueError("the two grids must cover the same cells: grid them with the same bounds")
    ea, ua = ascending.east.astype("float64"), ascending.up.astype("float64")
    ed, ud = descending.east.astype("float64"), descending.up.astype("float64")
    if np.nanmedian(ea) * np.nanmedian(ed) > 0:
        raise ValueError("the two grids look the same way: one ascending, one descending")
    det = ea * ud - ed * ua
    a, d = va.values.astype("float64"), vd.values.astype("float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        up = (ea * d - ed * a) / det
        east = (a * ud - d * ua) / det

    def as_mosaic(values: Any) -> Mosaic:
        return Mosaic(values=values.astype("float32"), left=va.left, top=va.top, pixel=va.pixel)

    return as_mosaic(up), as_mosaic(east)
