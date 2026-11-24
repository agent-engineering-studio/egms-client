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


# --- Records of open data (egms_client.records) -------------------------------

#: The source of every EGMS record.
SOURCE = {
    "url": "https://egms.land.copernicus.eu/",
    "licence": "Copernicus data policy, free and open",
    "attribution": (
        "Contains modified Copernicus Land Monitoring Service information (EGMS), © European Union"
    ),
}

#: How the reliability of a point is made, in one line.
POINT_METHOD = (
    "egms-client: share of measured 100 m cells within 500 m, and fit of the series; "
    "an estimate made from outside EGMS"
)

#: How the reliability of a box is made, in one line.
BOX_METHOD = "egms-client: the share of the 100 m cells in the box that have a value"

_COMPONENT = {"U": "vertical", "E": "east-west"}

#: The names of the records for people, by answer and component.
_LABELS = {
    "velocity": {
        "U": {"it": "Movimento del suolo, verticale", "en": "Ground motion, vertical"},
        "E": {"it": "Movimento del suolo, est-ovest", "en": "Ground motion, east-west"},
    },
    "area": {
        "U": {
            "it": "Movimento verticale del suolo nel riquadro",
            "en": "Vertical ground motion in the box",
        },
        "E": {
            "it": "Movimento est-ovest del suolo nel riquadro",
            "en": "East-west ground motion in the box",
        },
    },
    "moving_points": {
        "U": {
            "it": "Celle che si muovono più dei dintorni",
            "en": "Cells that move more than their surroundings",
        },
        "E": {
            "it": "Celle che si muovono più dei dintorni",
            "en": "Cells that move more than their surroundings",
        },
    },
}
#: The value a fact shows first.
_HEADLINES = {"area": "median", "moving_points": "moving"}


def to_records(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The facts of :func:`velocity`, :func:`area` or :func:`moving_points` as records.

    Records follow opendata-record/v1 (:mod:`egms_client.records`), the
    shape the application reads from every source. A velocity is one
    ``observation``. An area and the moving cells are one ``fact`` with the
    statistics, then one ``observation`` per cell listed. A missing value
    stays ``null`` and carries the reason ``not_measured``.
    """
    answer = facts.get("answer")
    if answer == "velocity":
        records = [_point_record(facts)]
    elif answer == "area":
        records = [_box_record(facts, "How fast does the ground move in this box?")]
        records += _cells(facts, "fastest")
    elif answer == "moving_points":
        records = [_box_record(facts, "Which cells move against the rest of this box?")]
        records += _cells(facts, "cells")
    else:
        raise ValueError(f"no records for an answer of kind {answer!r}")
    # The id first, after the schema and the kind: it is what a reader looks for.
    head = ("schema", "kind", "id")
    return [
        {k: r[k] for k in head} | {k: v for k, v in r.items() if k not in head} for r in records
    ]


def _envelope(facts: dict[str, Any], kind: str, where: dict[str, Any]) -> dict[str, Any]:
    from egms_client import __version__

    component = facts["component"]
    return {
        "schema": "opendata-record/v1",
        "kind": kind,
        "source": {"name": f"EGMS Ortho L3 {facts['release']}, {_COMPONENT[component]}", **SOURCE},
        "made_by": {"name": "egms-client", "version": __version__},
        "label": _LABELS["velocity" if kind == "observation" else facts["answer"]][component],
        "time": _record_time(facts["window"]),
        "where": where,
    }


def _record_time(w: dict[str, Any]) -> dict[str, Any]:
    if w["first"] and w["last"]:
        return {"first": w["first"], "last": w["last"], "exact": bool(w["exact"])}
    # Only the years of the release name: say they are not the dates.
    first, last = str(w["release"]).split("-")
    return {"first": f"{first}-01-01", "last": f"{last}-12-31", "exact": False}


def _point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def _reasons(reasons: list[str]) -> list[str]:
    return ["not_measured" if r == NOT_MEASURED else r for r in reasons]


def _point_record(facts: dict[str, Any]) -> dict[str, Any]:
    r, regional = facts["reliability"], facts["regional"]
    notes = [n for n in facts["notes"] if n != NOT_MEASURED]
    if r["coverage"] is not None:
        notes.insert(
            0, f"{r['coverage']:.0%} of the cells within {r['radius_m']:.0f} m have a value."
        )
    if regional["median_mm_per_year"] is not None:
        notes.insert(
            0,
            f"The median within {regional['radius_m'] / 1000:.0f} km is "
            f"{regional['median_mm_per_year']:+.1f} mm/a.",
        )
    if not facts["measured"]:
        notes.insert(0, NOT_MEASURED)
    c = facts["component"]
    return {
        **_envelope(facts, "observation", _point(facts["lon"], facts["lat"])),
        "id": f"egms-l3-{c.lower()}-{facts['release']}-{facts['lon']}-{facts['lat']}",
        "property": "velocity",
        "value": facts["velocity_mm_per_year"],
        "unit": "mm/a",
        "meaning": facts["meaning"],
        "reliability": {
            "score": r["score"],
            "reliable": r["reliable"],
            "method": POINT_METHOD,
            "reasons": _reasons(r["reasons"]),
        },
        "notes": notes,
    }


def _box_record(facts: dict[str, Any], question: str) -> dict[str, Any]:
    west, south, east, north = facts["box"]
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    meaning = facts["meaning"]
    measured = facts["measured"]
    if facts["answer"] == "area":
        names = {"median": "median", "p5": "p5", "p95": "p95", "min": "min", "max": "max"}
        values: dict[str, Any] = {
            name: {"value": facts[key], "unit": "mm/a", "meaning": meaning}
            for name, key in names.items()
        }
        if measured:
            band = facts["stable_band_mm_per_year"]
            values |= {
                "share_down": {
                    "value": facts["share_below"],
                    "unit": "1",
                    "meaning": f"share of the measured cells below -{band} mm/a",
                },
                "share_up": {
                    "value": facts["share_above"],
                    "unit": "1",
                    "meaning": f"share of the measured cells above +{band} mm/a",
                },
            }
    else:
        values = {
            "reference": {
                "value": facts["reference_median_mm_per_year"],
                "unit": "mm/a",
                "meaning": f"median of the box, the reference; {meaning}",
            }
        }
        if measured:
            values |= {
                "moving": {
                    "value": facts["moving"],
                    "unit": "1",
                    "meaning": (
                        f"cells {facts['threshold_mm_per_year']} mm/a or more from the reference"
                    ),
                },
                "moving_reliable": {
                    "value": facts["moving_reliable"],
                    "unit": "1",
                    "meaning": "of them, cells with enough measured cells around",
                },
            }
    if measured:
        values |= {
            "coverage": {
                "value": facts["coverage"],
                "unit": "1",
                "meaning": "share of the cells in the box that have a value",
            },
            "cells_with_data": {"value": facts["cells_with_data"], "unit": "1"},
        }
    box = "-".join(str(v) for v in facts["box"])
    return {
        **_envelope(facts, "fact", {"type": "Polygon", "coordinates": [ring]}),
        "id": f"egms-l3-{facts['component'].lower()}-{facts['release']}-{facts['answer']}-{box}",
        "question": question,
        "headline": _HEADLINES[facts["answer"]] if facts["measured"] else next(iter(values)),
        "values": values,
        "reliability": {
            "method": BOX_METHOD,
            "reasons": [] if measured else ["not_measured"],
        },
        "notes": list(facts["notes"]),
    }


def _cells(facts: dict[str, Any], key: str) -> list[dict[str, Any]]:
    c = facts["component"]
    out = []
    for cell in facts[key]:
        lon, lat = cell["lon"], cell["lat"]
        record: dict[str, Any] = {
            **_envelope(facts, "observation", _point(lon, lat)),
            "id": f"egms-l3-{c.lower()}-{facts['release']}-{lon}-{lat}",
            "property": "velocity",
            "value": cell["velocity_mm_per_year"],
            "unit": "mm/a",
            "meaning": facts["meaning"],
            "reliability": None,
            "notes": [NOT_TODAY, NOT_AN_ALERT],
        }
        if "relative_mm_per_year" in cell:
            record["reliability"] = {
                "score": None,
                "reliable": cell["reliable"],
                "method": f"egms-client: share of measured cells within {RADIUS_M:.0f} m",
                "reasons": [],
            }
            record["notes"].insert(
                0,
                f"{cell['relative_mm_per_year']:+.1f} mm/a against the median of the box; "
                f"{cell['coverage']:.0%} of the cells within {RADIUS_M:.0f} m have a value.",
            )
        out.append(record)
    return out


__all__ = [
    "LICENCE",
    "MEANING",
    "NOT_TODAY",
    "area",
    "moving_points",
    "summarize",
    "to_records",
    "velocity",
    "window_facts",
]
