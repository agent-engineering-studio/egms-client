"""How far to trust an EGMS velocity at a place: an estimate, declared as such.

EGMS publishes no map of how much each cell can be trusted. This module
makes one from outside, from what the archive does give, and says which
parts it knows:

* **coverage**: the share of 100 m cells with a value within ``radius_m``.
  The radar measures where it finds stable targets (buildings, rock, bare
  ground). Under trees, on fields that change, under snow, it finds few or
  none. A lone cell in an empty neighbourhood is a weak answer, and a place
  with no cell is **not measured**: never zero.
* **fit**: how well the archive's model fits the cell's series, from
  ``rmse_ts`` (mm) in the L3 CSV. Only when its attributes are given.

``score`` is the smallest of the parts that are known, from 0 to 1, and
``reliable`` is ``score >= RELIABLE_FROM``. Each part that pulls the score
down gives its reason in words.

The thresholds are choices, not measurements: they are stated here and
checked on the benchmark of known places (``benchmarks/``), where blind
places must come out unreliable, and moving and still ones reliable.

What the estimate cannot see, and does not pretend to:

* motion too fast for InSAR (more than about a centimetre between two passes
  is lost, not measured as slow);
* motion north-south (the satellites fly almost north-south and do not see it);
* anything after the end of the release window, or smaller than a 100 m cell;
* ``mean_velocity_std``: the archive's formal error is at most 0.3 mm/year
  in 95 % of the cells of the benchmark, and at most 0.2 in a forest where
  99 % of the cells are empty. It is reported, not trusted.

``regional_median`` is the median velocity within ``regional_radius_m``:
EGMS velocities carry regional offsets (+1.6 mm/year east-west at the Murge,
a place that does not move), so a velocity reads better against its region
than against zero. ``relative`` is the velocity minus that median.

Needs the ``raster`` extra; attributes need the ``tables`` extra.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: A score from this value up is reliable.
RELIABLE_FROM = 0.5

#: The neighbourhood of a point, for coverage: about 80 cells of 100 m.
RADIUS_M = 500.0

#: Coverage from which the neighbourhood counts as fully measured.
FULL_COVERAGE = 0.5

#: The neighbourhood for the regional median.
REGIONAL_RADIUS_M = 5_000.0

#: rmse_ts (mm) up to which the fit is good, and from which it is useless.
#: 95 % of the L3 cells of the benchmark are below 3.4 mm.
GOOD_RMSE_MM = 3.0
BAD_RMSE_MM = 6.0

#: Notes every answer carries.
NOT_MEASURED = "No cell here: not measured, which is not zero."
NOT_AN_ALERT = "A ground velocity is a measurement, not an alert or a safety verdict."


@dataclass(frozen=True, slots=True)
class Reliability:
    """How far to trust the L3 velocity at a point. ``None``: not known."""

    velocity: float | None
    score: float
    reliable: bool
    coverage: float
    fit: float | None
    rmse_mm: float | None
    velocity_std: float | None
    regional_median: float | None
    relative: float | None
    reasons: tuple[str, ...]


def trust(
    tiffs: Iterable[Path],
    lon: float,
    lat: float,
    *,
    attributes: Any = None,
    radius_m: float = RADIUS_M,
    regional_radius_m: float = REGIONAL_RADIUS_M,
) -> Reliability:
    """How far to trust the L3 velocity of the cell at ``(lon, lat)``.

    ``tiffs`` are the L3 GeoTIFFs of one component around the point (the
    tiles :meth:`~egms_client.EgmsArchive.fetch_tile` returns).
    ``attributes``, optional, is the L3 CSV of the same component as a
    DataFrame (``easting``, ``northing``, ``rmse_ts``, ``mean_velocity_std``):
    without it, ``fit`` is unknown and does not count.
    """
    import numpy as np

    from egms_client.mosaic import PIXEL_M, lonlat_to_xy, mosaic

    x, y = lonlat_to_xy(lon, lat)
    reach = max(radius_m, regional_radius_m)
    m = mosaic(tiffs, minx=x - reach, miny=y - reach, maxx=x + reach, maxy=y + reach)
    rows, cols = m.values.shape
    cx = m.left + (np.arange(cols) + 0.5) * PIXEL_M
    cy = m.top - (np.arange(rows) + 0.5) * PIXEL_M
    distance = np.hypot(cx[None, :] - x, cy[:, None] - y)
    col, row = int((x - m.left) // PIXEL_M), int((m.top - y) // PIXEL_M)
    here = float(m.values[row, col])
    velocity = None if math.isnan(here) else here

    near = distance <= radius_m
    coverage = float((~np.isnan(m.values[near])).mean())
    regional = m.values[(distance <= regional_radius_m) & ~np.isnan(m.values)]
    regional_median = float(np.median(regional)) if regional.size else None

    rmse = std = fit = None
    if attributes is not None and velocity is not None:
        cell = attributes[
            ((attributes.easting - x).abs() <= PIXEL_M / 2)
            & ((attributes.northing - y).abs() <= PIXEL_M / 2)
        ]
        if len(cell):
            rmse = float(cell.rmse_ts.iloc[0])
            std = float(cell.mean_velocity_std.iloc[0])
            fit = _linear(rmse, GOOD_RMSE_MM, BAD_RMSE_MM)

    reasons: list[str] = []
    coverage_part = min(1.0, coverage / FULL_COVERAGE)
    if velocity is None:
        reasons.append(NOT_MEASURED)
        score = 0.0
    else:
        if coverage_part < 1.0:
            reasons.append(
                f"only {coverage:.0%} of the cells within {radius_m:.0f} m have a value: "
                "few stable targets (vegetation, fields, snow?)"
            )
        if fit is not None and fit < 1.0:
            reasons.append(f"the series fits the model loosely (rmse {rmse:.1f} mm)")
        score = min(p for p in (coverage_part, fit) if p is not None)
    return Reliability(
        velocity=_round(velocity),
        score=round(score, 2),
        reliable=score >= RELIABLE_FROM,
        coverage=round(coverage, 3),
        fit=None if fit is None else round(fit, 2),
        rmse_mm=_round(rmse),
        velocity_std=_round(std),
        regional_median=_round(regional_median),
        relative=(
            None
            if velocity is None or regional_median is None
            else _round(velocity - regional_median)
        ),
        reasons=tuple(reasons),
    )


def coverage_map(values: Any, *, radius_m: float = RADIUS_M, pixel: float = 100.0) -> Any:
    """For every cell of a grid, the share of cells with a value within ``radius_m``.

    ``values`` is a 2-D array (a :class:`~egms_client.mosaic.Mosaic`'s
    ``values``), NaN where there is no data. The edges count only the cells
    inside the grid. Same shape, float32.
    """
    import numpy as np

    k = int(radius_m // pixel)
    offsets = np.arange(-k, k + 1)
    disk = (offsets[:, None] ** 2 + offsets[None, :] ** 2) * pixel**2 <= radius_m**2
    have = (~np.isnan(values)).astype("float64")
    ones = np.ones_like(have)
    padded_have = np.pad(have, k)
    padded_ones = np.pad(ones, k)
    rows, cols = values.shape
    total = np.zeros_like(have)
    count = np.zeros_like(have)
    for dr, dc in zip(*np.nonzero(disk), strict=True):
        total += padded_have[dr : dr + rows, dc : dc + cols]
        count += padded_ones[dr : dr + rows, dc : dc + cols]
    return (total / count).astype("float32")


def _linear(value: float, good: float, bad: float) -> float:
    """1 at ``good`` or better, 0 at ``bad`` or worse, a straight line between."""
    return max(0.0, min(1.0, (bad - value) / (bad - good)))


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


__all__ = [
    "BAD_RMSE_MM",
    "FULL_COVERAGE",
    "GOOD_RMSE_MM",
    "NOT_AN_ALERT",
    "NOT_MEASURED",
    "RADIUS_M",
    "REGIONAL_RADIUS_M",
    "RELIABLE_FROM",
    "Reliability",
    "coverage_map",
    "trust",
]
