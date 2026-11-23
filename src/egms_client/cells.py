"""Per-cell statistics of the L3 grids, for a model or a map: missing stays missing.

A model works on cells (1 km squares, say), not on 100 m pixels. This module
takes the L3 grids of a place and gives, for every cell, what its pixels say,
with three rules a model needs and easily breaks:

* **Not measured is not zero.** A cell with no pixel gets ``None`` for every
  statistic and ``valid_pixels == 0``. Writing 0.0 there tells a model "the
  ground is still" where the satellite saw nothing (a forest, radar shadow).
* **Signs are kept.** ``vertical_median`` and the tails ``vertical_p10`` (the
  pixels sinking most) and ``vertical_p90`` keep up and down apart. The
  acceleration is vertical and signed: ``acceleration_p10 < 0`` means some
  pixels sink faster and faster. A magnitude (``sqrt(E² + U²)``) mixes a
  slope speeding up with one slowing down. ``speed_p90`` is the one unsigned
  number, kept because a landslide fills few pixels of a cell.
* **One mask.** Every statistic, the acceleration and the seasonality too,
  uses the same pixels: those with a velocity (both components when ``east``
  is given). ``valid_pixels`` counts them; ``pixels`` counts the grid pixels
  whose centre falls in the cell. Both are 100 m pixels, not radar targets.

A cell takes the pixels whose **centre** lies in it (``minx <= x < maxx``), so
cells need not align with the 100 m grid. The rule is the one of Limen's
aggregation, and a test checks that the medians, the p90 and the counts are
the same on the same input.

``score`` is the coverage part of :mod:`egms_client.reliability`
(``coverage / FULL_COVERAGE``, at most 1), lowered by the fit of the series
when ``rmse`` is given; ``reliable`` is ``score >= RELIABLE_FROM``.

Needs the ``raster`` extra for the grids; :func:`to_frame` needs ``tables``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from egms_client.mosaic import Mosaic
from egms_client.reliability import (
    BAD_RMSE_MM,
    FULL_COVERAGE,
    GOOD_RMSE_MM,
    NOT_MEASURED,
    RELIABLE_FROM,
    _linear,
)


@dataclass(frozen=True, slots=True)
class Cell:
    """A rectangle in EPSG:3035 metres, with its id."""

    id: str
    minx: float
    miny: float
    maxx: float
    maxy: float


@dataclass(frozen=True, slots=True)
class CellStats:
    """What the pixels of one cell say. ``None``: not measured, never zero.

    Velocities in mm/year, accelerations in mm/year², seasonality in mm.
    """

    id: str
    pixels: int
    valid_pixels: int
    coverage: float
    vertical_median: float | None = None
    vertical_p10: float | None = None
    vertical_p90: float | None = None
    east_median: float | None = None
    speed_p90: float | None = None
    acceleration_median: float | None = None
    acceleration_p10: float | None = None
    seasonality_median: float | None = None
    rmse_median: float | None = None
    score: float = 0.0
    reliable: bool = False
    reasons: tuple[str, ...] = ()


def square_cells(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    *,
    size_m: float = 1_000.0,
    origin: tuple[float, float] = (0.0, 0.0),
) -> list[Cell]:
    """The squares of side ``size_m`` that touch a rectangle, on a grid from ``origin``.

    The id is the size and the lower-left corner: ``"1000m_E4400000_N2000000"``.
    """
    x0, y0 = origin
    first_col = math.floor((minx - x0) / size_m)
    last_col = math.ceil((maxx - x0) / size_m)
    first_row = math.floor((miny - y0) / size_m)
    last_row = math.ceil((maxy - y0) / size_m)
    out = []
    for row in range(first_row, last_row):
        for col in range(first_col, last_col):
            left, bottom = x0 + col * size_m, y0 + row * size_m
            out.append(
                Cell(
                    f"{size_m:g}m_E{left:.0f}_N{bottom:.0f}",
                    left,
                    bottom,
                    left + size_m,
                    bottom + size_m,
                )
            )
    return out


def on_grid(frame: Any, column: str, like: Mosaic) -> Any:
    """A column of the L3 attributes on the grid of a mosaic, pixel by pixel.

    ``frame`` has ``easting`` and ``northing`` (the pixel centre, EPSG:3035)
    and ``column`` (``acceleration``, ``seasonality``, ``rmse_ts``): the
    attributes of the same component as ``like``. NaN where a pixel has no row.
    """
    import numpy as np

    rows, cols = like.values.shape
    out = np.full((rows, cols), np.nan, dtype="float32")
    col = np.floor((frame["easting"].to_numpy() - like.left) / like.pixel).astype(np.int64)
    row = np.floor((like.top - frame["northing"].to_numpy()) / like.pixel).astype(np.int64)
    inside = (row >= 0) & (row < rows) & (col >= 0) & (col < cols)
    out[row[inside], col[inside]] = frame[column].to_numpy()[inside]
    return out


def per_cell(
    cells: Iterable[Cell],
    up: Mosaic,
    east: Mosaic | None = None,
    *,
    acceleration: Any = None,
    seasonality: Any = None,
    rmse: Any = None,
) -> list[CellStats]:
    """One :class:`CellStats` per cell. Pure: no I/O.

    ``up`` (and ``east``, on the same grid) are mosaics of the L3 velocity.
    ``acceleration``, ``seasonality`` and ``rmse`` are arrays on the same
    grid (:func:`on_grid` of the vertical attributes); each is optional.
    """
    import numpy as np

    v = up.values
    e = None
    if east is not None:
        if east.values.shape != v.shape or (east.left, east.top) != (up.left, up.top):
            raise ValueError("up and east must be on the same grid (mosaic them on the same box)")
        e = east.values
    for name, grid in (
        ("acceleration", acceleration),
        ("seasonality", seasonality),
        ("rmse", rmse),
    ):
        if grid is not None and grid.shape != v.shape:
            raise ValueError(f"{name} must have the shape of up: {grid.shape} != {v.shape}")

    out = []
    for c in cells:
        # The centre of pixel j is at left + (j + 0.5) * pixel: in the cell
        # when minx <= centre < maxx.
        c0 = max(0, math.ceil((c.minx - up.left) / up.pixel - 0.5))
        c1 = min(v.shape[1], math.ceil((c.maxx - up.left) / up.pixel - 0.5))
        r0 = max(0, math.ceil((up.top - c.maxy) / up.pixel - 0.5))
        r1 = min(v.shape[0], math.ceil((up.top - c.miny) / up.pixel - 0.5))
        pixels = max(0, r1 - r0) * max(0, c1 - c0)
        if pixels == 0:
            out.append(CellStats(c.id, 0, 0, 0.0, reasons=(NOT_MEASURED,)))
            continue
        vv = v[r0:r1, c0:c1]
        mask = ~np.isnan(vv)
        if e is not None:
            ee = e[r0:r1, c0:c1]
            mask &= ~np.isnan(ee)
        n = int(mask.sum())
        coverage = n / pixels
        if n == 0:
            out.append(CellStats(c.id, pixels, 0, 0.0, reasons=(NOT_MEASURED,)))
            continue
        vertical = vv[mask].astype("float64")
        horizontal = ee[mask].astype("float64") if e is not None else None
        acc = _masked(acceleration, mask, r0, r1, c0, c1)
        rmse_median = _quantile(_masked(rmse, mask, r0, r1, c0, c1), 50)

        reasons = []
        coverage_part = min(1.0, coverage / FULL_COVERAGE)
        if coverage_part < 1.0:
            reasons.append(f"only {coverage:.0%} of the cell's pixels have a value")
        fit = None if rmse_median is None else _linear(rmse_median, GOOD_RMSE_MM, BAD_RMSE_MM)
        if fit is not None and fit < 1.0:
            reasons.append(f"the series fit the model loosely (median rmse {rmse_median:.1f} mm)")
        score = min(p for p in (coverage_part, fit) if p is not None)

        out.append(
            CellStats(
                id=c.id,
                pixels=pixels,
                valid_pixels=n,
                coverage=round(coverage, 3),
                vertical_median=_quantile(vertical, 50),
                vertical_p10=_quantile(vertical, 10),
                vertical_p90=_quantile(vertical, 90),
                east_median=_quantile(horizontal, 50),
                speed_p90=(
                    None
                    if horizontal is None
                    else _quantile(np.sqrt(vertical**2 + horizontal**2), 90)
                ),
                acceleration_median=_quantile(acc, 50),
                acceleration_p10=_quantile(acc, 10),
                seasonality_median=_quantile(_masked(seasonality, mask, r0, r1, c0, c1), 50),
                rmse_median=rmse_median,
                score=round(score, 2),
                reliable=score >= RELIABLE_FROM,
                reasons=tuple(reasons),
            )
        )
    return out


def to_frame(stats: Iterable[CellStats]) -> Any:
    """The statistics as a DataFrame, one row per cell; missing stays NaN, not 0."""
    import pandas as pd

    rows = [asdict(s) | {"reasons": "; ".join(s.reasons)} for s in stats]
    return pd.DataFrame(rows, columns=list(CellStats.__dataclass_fields__))


def _masked(grid: Any, mask: Any, r0: int, r1: int, c0: int, c1: int) -> Any:
    """The values of ``grid`` under the velocity mask, without NaN; None if no grid."""
    import numpy as np

    if grid is None:
        return None
    values = grid[r0:r1, c0:c1][mask].astype("float64")
    return values[~np.isnan(values)]


def _quantile(values: Any, q: float) -> float | None:
    import numpy as np

    if values is None or values.size == 0:
        return None
    return float(np.percentile(values, q))


__all__ = ["Cell", "CellStats", "on_grid", "per_cell", "square_cells", "to_frame"]
