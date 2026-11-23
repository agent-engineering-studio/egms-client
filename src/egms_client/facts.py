"""Answers as data: every number with where it comes from and how far to trust it.

A language model words an answer; it never makes one. The functions here
compute the answer from local files and return it as a plain dict (JSON
ready) that carries, next to each number:

* ``release`` and ``window``: when the satellites measured. The data stop at
  the end of the window and do not describe the ground of today;
* ``files``: the archive files the number was read from;
* ``reliability``: how far to trust it (:mod:`egms_client.reliability`),
  with its reasons;
* ``licence`` and ``notes``: the credit EGMS asks for, and what a number is
  not (not measured is not zero; a velocity is not an alert).

The MCP server returns these dicts; :mod:`egms_client.check` checks a text
written from them. Pure: no network, only the GeoTIFFs (and, for the fit of
the series, the L3 attributes) given. Needs the ``raster`` extra.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypedDict

from egms_client.releases import window
from egms_client.reliability import (
    FULL_COVERAGE,
    NOT_AN_ALERT,
    NOT_MEASURED,
    RADIUS_M,
    REGIONAL_RADIUS_M,
    RELIABLE_FROM,
    trust,
)

#: The credit EGMS asks for, on every answer.
LICENCE = (
    "Contains modified Copernicus Land Monitoring Service information (EGMS), "
    "© European Union. Licence: Copernicus data policy, free and open."
)

#: What every answer reminds.
NOT_TODAY = "The data stop at the end of the window: they do not describe the ground of today."

MEANING = {
    "U": "vertical: positive up, negative down (subsidence)",
    "E": "east-west: positive east, negative west",
}


class Cell(TypedDict):
    lon: float
    lat: float
    velocity_mm_per_year: float


class _Stats(TypedDict):
    cells_with_data: int
    coverage: float
    mean: float | None
    median: float | None
    p5: float | None
    p95: float | None
    min: float | None
    max: float | None
    share_below: float | None
    share_above: float | None
    fastest: list[Cell]


def summarize(
    tiffs: list[Path],
    *,
    box: tuple[float, float, float, float],
    stable_band: float = 2.0,
    fastest: int = 5,
) -> _Stats:
    """The statistics ``area_summary`` returns, over the cells inside a box in degrees.

    Only cells whose centre falls inside the box count (the box is curved
    in EPSG:3035, so its bounding rectangle holds more). Pure: no network.
    """
    import numpy as np
    from pyproj import Transformer

    from egms_client.mosaic import lonlat_to_laea, mosaic

    west, south, east, north = box
    minx, miny, maxx, maxy = lonlat_to_laea(west, south, east, north)
    m = mosaic(tiffs, minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    rows, cols = m.values.shape
    x = m.left + (np.arange(cols) + 0.5) * m.pixel
    y = m.top - (np.arange(rows) + 0.5) * m.pixel
    xx, yy = np.meshgrid(x, y)
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    lon, lat = to_lonlat.transform(xx, yy)
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    values = m.values[inside]
    valid = values[~np.isnan(values)]
    n = int(valid.size)
    if n == 0:
        return _Stats(
            cells_with_data=0,
            coverage=0.0,
            mean=None,
            median=None,
            p5=None,
            p95=None,
            min=None,
            max=None,
            share_below=None,
            share_above=None,
            fastest=[],
        )
    data = np.where(inside, m.values, np.nan)
    order = np.argsort(-np.nan_to_num(np.abs(data), nan=-1.0), axis=None)[:fastest]
    top = [
        Cell(
            lon=round(float(lon.flat[i]), 5),
            lat=round(float(lat.flat[i]), 5),
            velocity_mm_per_year=round(float(data.flat[i]), 1),
        )
        for i in order
        if not math.isnan(float(data.flat[i]))
    ]
    return _Stats(
        cells_with_data=n,
        coverage=round(n / max(int(inside.sum()), 1), 3),
        mean=_round(float(valid.mean())),
        median=_round(float(np.median(valid))),
        p5=_round(float(np.percentile(valid, 5))),
        p95=_round(float(np.percentile(valid, 95))),
        min=_round(float(valid.min())),
        max=_round(float(valid.max())),
        share_below=round(float((valid < -stable_band).mean()), 3),
        share_above=round(float((valid > stable_band).mean()), 3),
        fastest=top,
    )


def _round(value: float | None) -> float | None:
    """Two decimals, and never -0.0: a velocity of zero has no direction."""
    return None if value is None else round(value, 2) + 0.0


def window_facts(release: str, level: str = "L3") -> dict[str, Any]:
    """The window of a release as data: exact dates when known, else the years only."""
    w = window(release, level)
    return {
        "release": release,
        "level": w.level,
        "first": None if w.first is None else w.first.isoformat(),
        "last": None if w.last is None else w.last.isoformat(),
        "exact": w.exact,
        "text": w.text(),
        "source": w.source or None,
    }


def velocity(
    tiffs: Iterable[Path],
    lon: float,
    lat: float,
    *,
    component: str = "U",
    release: str,
    attributes: Any = None,
) -> dict[str, Any]:
    """The L3 velocity of the 100 m cell at a point, with its reliability and window.

    ``tiffs`` are the L3 tiles of ``component`` around the point;
    ``attributes``, optional, the L3 attributes of the same component (for
    the fit of the series).
    """
    tiffs = list(tiffs)
    r = trust(tiffs, lon, lat, attributes=attributes)
    measured = r.velocity is not None
    notes = [NOT_TODAY, NOT_AN_ALERT]
    if not measured:
        notes.insert(0, NOT_MEASURED)
    return {
        "answer": "velocity",
        "lon": lon,
        "lat": lat,
        "component": component,
        "meaning": MEANING[component],
        "unit": "mm/year",
        "cell_m": 100.0,
        "measured": measured,
        "velocity_mm_per_year": r.velocity,
        "reliability": {
            "score": r.score,
            "reliable": r.reliable,
            "reliable_from": RELIABLE_FROM,
            "coverage": r.coverage,
            "radius_m": RADIUS_M,
            "fit": r.fit,
            "rmse_mm": r.rmse_mm,
            "reasons": list(r.reasons),
        },
        "regional": {
            "radius_m": REGIONAL_RADIUS_M,
            "median_mm_per_year": r.regional_median,
            "relative_mm_per_year": r.relative,
        },
        "release": release,
        "window": window_facts(release),
        "files": sorted(p.name for p in tiffs),
        "licence": LICENCE,
        "notes": notes,
    }


def area(
    tiffs: Iterable[Path],
    box: tuple[float, float, float, float],
    *,
    component: str = "U",
    release: str,
    stable_band: float = 2.0,
) -> dict[str, Any]:
    """Statistics of the L3 velocity over a box in degrees (``mcp_server.summarize``)."""
    tiffs = list(tiffs)
    stats = summarize(tiffs, box=box, stable_band=stable_band)
    measured = stats["cells_with_data"] > 0
    notes = [NOT_TODAY, NOT_AN_ALERT]
    if not measured:
        notes.insert(0, NOT_MEASURED)
    elif stats["coverage"] < FULL_COVERAGE:
        notes.insert(
            0,
            f"Only {stats['coverage']:.0%} of the cells have a value: the statistics "
            "describe the measured cells, not the whole box.",
        )
    return {
        "answer": "area",
        "box": list(box),
        "component": component,
        "meaning": MEANING[component],
        "unit": "mm/year",
        "measured": measured,
        **stats,
        "stable_band_mm_per_year": stable_band,
        "release": release,
        "window": window_facts(release),
        "files": sorted(p.name for p in tiffs),
        "licence": LICENCE,
        "notes": notes,
    }


def moving_points(
    tiffs: Iterable[Path],
    box: tuple[float, float, float, float],
    *,
    component: str = "U",
    release: str,
    threshold: float = 5.0,
    limit: int = 10,
) -> dict[str, Any]:
    """The cells of a box that move against their region, the fastest first.

    A cell moves when its velocity differs from the median of the box by
    ``threshold`` mm/year or more: EGMS velocities carry regional offsets,
    so the median of the box is the reference, not zero. Each cell has its
    coverage within ``RADIUS_M`` and whether it is reliable (coverage at
    least ``FULL_COVERAGE * RELIABLE_FROM``): a lone fast cell is weak
    evidence. Only cells whose centre is inside the box count.
    """
    import numpy as np
    from pyproj import Transformer

    from egms_client.mosaic import lonlat_to_laea, mosaic
    from egms_client.reliability import coverage_map

    tiffs = list(tiffs)
    west, south, east, north = box
    minx, miny, maxx, maxy = lonlat_to_laea(west, south, east, north)
    m = mosaic(tiffs, minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    rows, cols = m.values.shape
    x = m.left + (np.arange(cols) + 0.5) * m.pixel
    y = m.top - (np.arange(rows) + 0.5) * m.pixel
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True).transform(xx, yy)
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    values = np.where(inside, m.values, np.nan)
    have = ~np.isnan(values)
    n = int(have.sum())
    base: dict[str, Any] = {
        "answer": "moving_points",
        "box": list(box),
        "component": component,
        "meaning": MEANING[component],
        "unit": "mm/year",
        "threshold_mm_per_year": threshold,
        "cells_with_data": n,
        "coverage": round(n / max(int(inside.sum()), 1), 3),
        "release": release,
        "window": window_facts(release),
        "files": sorted(p.name for p in tiffs),
        "licence": LICENCE,
    }
    if n == 0:
        return base | {
            "measured": False,
            "reference_median_mm_per_year": None,
            "moving": 0,
            "moving_reliable": 0,
            "cells": [],
            "notes": [NOT_MEASURED, NOT_TODAY, NOT_AN_ALERT],
        }
    reference = float(np.median(values[have]))
    relative = values - reference
    coverage = coverage_map(m.values, radius_m=RADIUS_M, pixel=m.pixel)
    reliable = coverage >= FULL_COVERAGE * RELIABLE_FROM
    moving = have & (np.abs(relative) >= threshold)
    order = np.argsort(-np.nan_to_num(np.abs(np.where(moving, relative, np.nan)), nan=-1.0), None)
    cells = [
        {
            "lon": round(float(lon.flat[i]), 5),
            "lat": round(float(lat.flat[i]), 5),
            "velocity_mm_per_year": round(float(values.flat[i]), 1),
            "relative_mm_per_year": round(float(relative.flat[i]), 1),
            "coverage": round(float(coverage.flat[i]), 2),
            "reliable": bool(reliable.flat[i]),
        }
        for i in order[: min(limit, int(moving.sum()))]
    ]
    return base | {
        "measured": True,
        "reference_median_mm_per_year": round(reference, 1),
        "moving": int(moving.sum()),
        "moving_reliable": int((moving & reliable).sum()),
        "cells": cells,
        "notes": [
            "A cell moves when it differs from the median of the box by the threshold.",
            NOT_TODAY,
            NOT_AN_ALERT,
        ],
    }


__all__ = [
    "LICENCE",
    "MEANING",
    "NOT_TODAY",
    "area",
    "moving_points",
    "summarize",
    "velocity",
    "window_facts",
]
