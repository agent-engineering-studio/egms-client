"""Crop the data of every case from the EGMS archive into benchmarks/data/.

Needs the CLMS key (EGMS_SERVICE_KEY or EGMS_SERVICE_KEY_FILE) and about
1 GB of downloads, kept in EGMS_DATA_DIR. In CI it runs in the workflow
``bench-data``, which uploads the crops as an artifact to commit.

What it writes, per case, all small:

* ``U.tif`` / ``E.tif``: the Ortho L3 velocity over the case box (COG);
* ``l3.parquet`` / ``l3-E.parquet``: the L3 cell attributes in the box, of
  the vertical and (where the case has it) east-west grid; no series;
* ``ascending.parquet`` / ``descending.parquet``: the L2B points of one
  burst per direction in the box, attributes only;
* ``ascending-series.parquet`` / ...: the same points within
  ``series_radius_m`` of ``l2b_at``, with their time series (float32);
* ``source.json``: the release and the archive files each crop came from.

    uv run python -m benchmarks.fetch [case ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from egms_client import EgmsArchive, Query, tiles_for_bounds
from egms_client.mosaic import lonlat_to_laea, lonlat_to_xy, mosaic, to_cog

HERE = Path(__file__).parent
CASES = HERE / "cases.toml"
DATA = HERE / "data"

#: L3 attributes kept per cell: what reliability and cells need, not the series.
L3_COLUMNS = [
    "pid",
    "easting",
    "northing",
    "mean_velocity",
    "mean_velocity_std",
    "rmse_ts",
    "acceleration",
    "seasonality",
]

#: L2 attributes kept per point.
L2_COLUMNS = [
    "pid",
    "latitude",
    "longitude",
    "easting",
    "northing",
    "temporal_coherence",
    "rmse_ts",
    "los_east",
    "los_north",
    "los_up",
    "mean_velocity",
    "mean_velocity_std",
    "acceleration",
    "seasonality",
]


def load_cases() -> list[dict[str, Any]]:
    with CASES.open("rb") as f:
        cases: list[dict[str, Any]] = tomllib.load(f)["case"]
    return cases


async def fetch_case(archive: EgmsArchive, case: dict[str, Any], release: str, cache: Path) -> None:
    import pandas as pd

    out = DATA / case["id"]
    out.mkdir(parents=True, exist_ok=True)
    west, south, east, north = case["box"]
    minx, miny, maxx, maxy = lonlat_to_laea(west, south, east, north)
    files: dict[str, list[str]] = {}

    for component in case.get("l3", []):
        tiffs = []
        for tile in tiles_for_bounds(minx, miny, maxx, maxy):
            tiff = await archive.fetch_tile(tile, component, release, cache)
            if tiff is not None:
                tiffs.append(tiff)
        to_cog(mosaic(tiffs, minx=minx, miny=miny, maxx=maxx, maxy=maxy), out / f"{component}.tif")
        files[f"{component}.tif"] = [t.name for t in tiffs]

    if case.get("l3_attributes"):
        for component in case["l3"]:
            query = Query(
                levels=("L3",),
                release=release,
                bbox=(west, south, east, north),
                product_type="ORTHO-UP" if component == "U" else "ORTHO-EAST",
            )
            kept = await archive.fetch(query, cache, keep=["parquet"])
            mine = [path for path in kept if f"_{component}_" in path.name]
            frames = []
            for path in mine:
                p = pd.read_parquet(path, columns=L3_COLUMNS)
                inside = p.easting.between(minx, maxx) & p.northing.between(miny, maxy)
                frames.append(p[inside])
            name = "l3.parquet" if component == "U" else f"l3-{component}.parquet"
            pd.concat(frames).to_parquet(out / name, index=False, compression="zstd")
            files[name] = sorted(path.name for path in mine)

    if case.get("l2b"):
        lon, lat = case["l2b_at"]
        query = Query(levels=("L2B",), release=release, bbox=(west, south, east, north))
        hits = [h for s in await archive.find(query) for h in s.hits]
        chosen: dict[str, Any] = {}
        for hit in sorted(hits, key=lambda h: h.filesize):
            if hit.filesize > 1_000_000 and hit.covers(lon, lat):
                chosen.setdefault(hit.direction, hit)
        x0, y0 = lonlat_to_xy(lon, lat)
        for direction, hit in sorted(chosen.items()):
            burst = Query(
                levels=("L2B",),
                release=release,
                relative_orbit=hit.relative_orbit,
                burst_cycle=hit.burst_cycle,
                swath=hit.swath,
            )
            (path,) = await archive.fetch(burst, cache, keep=["parquet"])
            p = pd.read_parquet(path).drop(columns="geometry")
            inside = p.longitude.between(west, east) & p.latitude.between(south, north)
            p = p[inside]
            p[L2_COLUMNS].to_parquet(out / f"{direction}.parquet", index=False, compression="zstd")
            dates = [c for c in p.columns if str(c).isdigit() and len(str(c)) == 8]
            distance = ((p.easting - x0) ** 2 + (p.northing - y0) ** 2) ** 0.5
            near = p[distance <= case["series_radius_m"]]
            series = near[["pid", "mean_velocity", *dates]].astype(dict.fromkeys(dates, "float32"))
            series.to_parquet(out / f"{direction}-series.parquet", index=False, compression="zstd")
            files[f"{direction}.parquet"] = [path.name]

    source = {
        "case": case["id"],
        "release": release,
        "fetched": datetime.now(UTC).date().isoformat(),
        "files": files,
        "credit": "Contains modified Copernicus Land Monitoring Service information (EGMS), "
        "© European Union.",
    }
    (out / "source.json").write_text(json.dumps(source, indent=2) + "\n")
    print(f"{case['id']}: " + ", ".join(sorted(files)))


async def main(only: list[str]) -> None:
    cache = Path(os.environ.get("EGMS_DATA_DIR", "egms-data"))
    async with EgmsArchive() as archive:
        release = (await archive.releases())[-1]
        print(f"release {release}")
        for case in load_cases():
            if not only or case["id"] in only:
                await fetch_case(archive, case, release, cache)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cases", nargs="*", help="case ids (default: all)")
    asyncio.run(main(parser.parse_args().cases))
