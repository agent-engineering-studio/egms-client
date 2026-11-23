"""Score the library on the known cases, offline, on the crops in benchmarks/data/.

    uv run python -m benchmarks.run             # the table, measured now
    uv run python -m benchmarks.run --record    # write results.json
    uv run python -m benchmarks.run --check     # CI: fail on any change from results.json
    uv run python -m benchmarks.run --markdown  # the table for the README

Every check measures one number with the library, the way a user (or the
MCP server) would get it, and compares it with the range its source gives.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
CASES = HERE / "cases.toml"
DATA = HERE / "data"
RESULTS = HERE / "results.json"

#: Measured values are compared with results.json at this precision.
DIGITS = 3


def load_cases() -> list[dict[str, Any]]:
    with CASES.open("rb") as f:
        cases: list[dict[str, Any]] = tomllib.load(f)["case"]
    return cases


def _value(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from egms_client.mosaic import lonlat_to_xy, value_at

    tiff = DATA / case["id"] / f"{check['component']}.tif"
    return value_at(tiff, *lonlat_to_xy(check["lon"], check["lat"]))


def _area(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from egms_client.mcp_server import summarize

    tiff = DATA / case["id"] / f"{check['component']}.tif"
    stats = summarize([tiff], box=tuple(check["box"]), stable_band=check.get("stable_band", 2.0))
    value = stats[check["stat"]]  # type: ignore[literal-required]
    return None if value is None else float(value)


def _points(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    import numpy as np
    import pandas as pd

    from egms_client.decompose import MIN_COHERENCE
    from egms_client.mosaic import lonlat_to_xy

    p = pd.read_parquet(DATA / case["id"] / f"{check['direction']}.parquet")
    x0, y0 = lonlat_to_xy(check["lon"], check["lat"])
    near = np.hypot(p.easting - x0, p.northing - y0) <= check["radius_m"]
    v = p.mean_velocity[near & (p.temporal_coherence >= MIN_COHERENCE)]
    if check["stat"] == "count":
        return float(len(v))
    if v.empty:
        return None
    return float(getattr(v, check["stat"])())


def _decompose(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    import numpy as np
    import pandas as pd

    from egms_client.decompose import decompose, grid_los
    from egms_client.mosaic import lonlat_to_laea, mosaic

    folder = DATA / case["id"]
    minx, miny, maxx, maxy = lonlat_to_laea(*case["box"])
    bounds = {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
    asc = grid_los(pd.read_parquet(folder / "ascending.parquet"), **bounds)
    desc = grid_los(pd.read_parquet(folder / "descending.parquet"), **bounds)
    up, east = decompose(asc, desc)
    ours = up if check["component"] == "U" else east
    l3 = mosaic([folder / f"{check['component']}.tif"], **bounds)
    both = ~np.isnan(ours.values) & ~np.isnan(l3.values)
    a, b = ours.values[both].astype("float64"), l3.values[both].astype("float64")
    if a.size < 10:
        return None
    if check["stat"] == "correlation":
        return float(np.corrcoef(a, b)[0, 1])
    return float(np.median(np.abs(a - b)))


def _fit(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    import numpy as np
    import pandas as pd

    from egms_client.analysis import fit

    p = pd.read_parquet(DATA / case["id"] / f"{check['direction']}-series.parquet")
    ours = fit(p)
    diff = np.abs(ours["velocity"].to_numpy() - p["mean_velocity"].to_numpy())
    return float(np.nanmedian(diff))


def _reliable(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    import pandas as pd

    from egms_client.reliability import trust

    folder = DATA / case["id"]
    attributes = pd.read_parquet(folder / "l3.parquet")
    tiff = folder / f"{check.get('component', 'U')}.tif"
    return trust([tiff], check["lon"], check["lat"], attributes=attributes).score


METHODS: dict[str, Callable[[dict[str, Any], dict[str, Any]], float | None]] = {
    "value": _value,
    "area": _area,
    "points": _points,
    "decompose": _decompose,
    "fit": _fit,
    "reliable": _reliable,
}


def passes(check: dict[str, Any], measured: float | None) -> bool:
    """Whether a measured number is what the case's source expects."""
    if check.get("none"):
        return measured is None
    if measured is None or math.isnan(measured):
        return False
    low: float = check.get("min", -math.inf)
    high: float = check.get("max", math.inf)
    return low <= measured <= high


def score() -> list[dict[str, Any]]:
    rows = []
    for case in load_cases():
        for check in case["check"]:
            measured = METHODS[check["kind"]](case, check)
            rows.append(
                {
                    "case": case["id"],
                    "status": case["status"],
                    "check": check["name"],
                    "kind": check["kind"],
                    "measured": None if measured is None else round(measured, DIGITS),
                    "expected": _expected(check),
                    "pass": passes(check, measured),
                }
            )
    return rows


def _expected(check: dict[str, Any]) -> str:
    if check.get("none"):
        return "not measured"
    low, high = check.get("min"), check.get("max")
    stat = check.get("stat", "score" if check["kind"] == "reliable" else "velocity")
    if low is not None and high is not None:
        return f"{low} ≤ {stat} ≤ {high}"
    return f"{stat} ≥ {low}" if low is not None else f"{stat} ≤ {high}"


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Case | Check | Expected | Measured | |", "|---|---|---|---|---|"]
    for r in rows:
        measured = "not measured" if r["measured"] is None else f"{r['measured']:g}"
        mark = "✅" if r["pass"] else "❌"
        lines.append(f"| {r['case']} | {r['check']} | {r['expected']} | {measured} | {mark} |")
    passed = sum(r["pass"] for r in rows)
    lines.append(f"\n**{passed} of {len(rows)}** checks pass.")
    return "\n".join(lines)


def check_against_record(rows: list[dict[str, Any]]) -> list[str]:
    """What changed from results.json: an outcome, a value, a check added or gone."""
    recorded = {(r["case"], r["check"]): r for r in json.loads(RESULTS.read_text())["rows"]}
    now = {(r["case"], r["check"]): r for r in rows}
    problems = [f"{k}: recorded, no longer runs" for k in recorded.keys() - now.keys()]
    problems += [f"{k}: new, not recorded (run --record)" for k in now.keys() - recorded.keys()]
    for key in recorded.keys() & now.keys():
        old, new = recorded[key], now[key]
        if old["pass"] != new["pass"] or old["measured"] != new["measured"]:
            problems.append(
                f"{key}: was {old['measured']} ({old['pass']}), "
                f"now {new['measured']} ({new['pass']})"
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="write results.json")
    mode.add_argument("--check", action="store_true", help="fail on any change from results.json")
    mode.add_argument("--markdown", action="store_true", help="print the README table")
    args = parser.parse_args(argv)
    rows = score()
    if args.record:
        sources = sorted(
            {
                json.loads((DATA / c["id"] / "source.json").read_text())["release"]
                for c in load_cases()
            }
        )
        RESULTS.write_text(
            json.dumps({"release": sources, "rows": rows}, indent=2, ensure_ascii=False) + "\n"
        )
    if args.check:
        problems = check_against_record(rows)
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{sum(r['pass'] for r in rows)} of {len(rows)} pass; {len(problems)} changes")
        return 1 if problems else 0
    print(markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
