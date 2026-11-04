---
name: egms-client
description: Download and read Copernicus EGMS (European Ground Motion Service) InSAR data in Python with the egms-client library - Ortho L3 velocity tiles, L2A/L2B measurement points and their time series, mosaics, GeoParquet, vertical/east-west decomposition. Use when code needs ground motion, subsidence, uplift or landslide data over Europe, or mentions EGMS, egms-client or the EGMS archive.
---

# egms-client

`egms-client` is a typed, async Python client for the EGMS archive
(`https://egms.land.copernicus.eu/insar-api/archive`). Use it rather than
raw HTTP: the archive's API is undocumented, and it fails **quietly**
(HTTP 200 with `status: false`, expiring ids, a 429 on the third download).
The library already handles all of that.

Full documentation: https://agentengineering.it/egms-client/ ·
everything as plain text: https://agentengineering.it/egms-client/llms-full.txt

## Setup

```bash
pip install egms-client                            # search, download
pip install "egms-client[raster,tables,xarray]"    # + mosaics, pandas/GeoParquet, xarray
export EGMS_SERVICE_KEY_FILE=~/clms-service-key.json  # or EGMS_SERVICE_KEY='<the JSON>'
```

The service key is a CLMS JSON key (land.copernicus.eu → profile → API
Tokens). It is a secret. Never write its contents or its path into code,
logs or notebooks: let `EgmsArchive()` read it from the environment.

## The data, in one paragraph

- **Ortho L3** (`"L3"`): mean velocity on a 100 m grid in **EPSG:3035**, in
  100 km tiles named by their lower-left corner in hundreds of km
  (`(47, 19)` ↔ `"E47N19"`). One file per component: `"U"` vertical,
  `"E"` east-west. Each ZIP is about 60 MB and holds a GeoTIFF (about 4 MB)
  and a CSV of time series (about 245 MB).
- **L2A / L2B** (`"L2A"` basic, `"L2B"` calibrated on GNSS): measurement
  points per Sentinel-1 burst. Their velocity is along the satellite's
  **line of sight** (LOS), not vertical. The CSV has one column per
  acquisition date (displacement in mm).
- Velocities are in **mm/year**. `U < 0` means the ground goes down. A
  positive LOS `mean_velocity` moves towards the satellite.
- Releases are windows of years (`"2020-2024"`, `"2020-2025"`). Get them
  from `await archive.releases()` (oldest first) and never guess the next
  one.

## Recipes

```python
import asyncio
from pathlib import Path

from egms_client import EgmsArchive, Query, tiles_for_bounds


async def main() -> None:
    async with EgmsArchive() as archive:
        release = (await archive.releases())[-1]

        # The vertical velocity at a point (lon, lat): one tile downloaded, once.
        point = await archive.velocity_at(14.12, 40.83, "U", release, Path("egms"))
        print(point.velocity, point.file)  # mm/year (None at sea / no data), its source

        # One L3 tile: path to the GeoTIFF (cached), or None if the tile does not exist.
        tiff = await archive.fetch_tile((47, 19), "U", release, Path("egms"))

        # L2B points over a box in degrees (west, south, east, north).
        query = Query(levels=("L2B",), release=release, bbox=(14.4, 40.0, 15.7, 41.0))
        found = await archive.find(query)  # nothing downloaded
        gb = sum(h.filesize for s in found for h in s.hits) / 1e9  # tell the user first
        paths = await archive.fetch(query, Path("egms"), keep=["parquet"], max_bytes=10**10)


asyncio.run(main())
```

- Without `async` (scripts, Jupyter): `from egms_client.sync import Archive`.
  It has the same methods, which block, and works as `with Archive() as archive:`.
  Prefer it in notebooks over `asyncio.run`, which fails when a loop is already running.
- A map over a box in degrees: `from egms_client.mosaic import mosaic, lonlat_to_laea, to_cog`.
  Convert the box with `lonlat_to_laea(w, s, e, n)`, pick tiles with
  `tiles_for_bounds(minx, miny, maxx, maxy)`, fetch each with `fetch_tile`, then
  call `mosaic(tiffs, minx=..., miny=..., maxx=..., maxy=...)`. NaN marks no data.
  From a shell: `egms mosaic --bbox W,S,E,N --component U --out map.tif`.
- Tables: `from egms_client.tables import read_csv, attributes, dates, series_long`.
  `read_csv(path, series=False)` reads the attributes only and is much lighter.
- Vertical and east-west from L2: `from egms_client.decompose import grid_los, decompose`.
  Use one **ascending** and one **descending** grid over the same bounds.
- xarray: `egms_client.mosaic.to_xarray(m)` gives dims `(y, x)`, and
  `egms_client.tables.to_xarray(df)` gives dims `(pid, time)`.
- A file's real outline: `hit.covers(lon, lat)`. A burst is a tilted
  parallelogram, so its `bbox` claims points it does not contain.

## Rules (each one is a real failure of the archive)

1. **Never build file names or download URLs by hand.** The trailing `_1`
   is a sub-release that changes. The `id` in a download link is a *search*
   id that expires (HTTP 401). Use `find` / `fetch` / `fetch_tile`.
2. **Level names are upper case:** `"L2A"`, `"L2B"`, `"L3"`. `"L2a"` (as
   in file names) is `Invalid level`.
3. **Relative orbits are three-digit strings** (`"022"`). The library pads
   integers for you, so passing `22` to `Query` is fine. Raw API calls with
   `22` fail.
4. **Boxes are at most 5° × 5° per search.** `find` / `fetch` split larger
   ones. Do not split them yourself.
5. **At most 2 downloads at once per account.** A third is HTTP 429. One
   `EgmsArchive` enforces this across all its calls, so share one instance
   and do not create several to "go faster".
6. **A tile at sea is not an error:** `fetch_tile` returns `None` and
   remembers it.
7. **Compare CRS by parameters, not by name.** Some tiles say
   `IGNF:ETRS89LAEA` instead of `EPSG:3035`. `mosaic` already handles this.
8. **Downloads are big.** One relative orbit is about 400 bursts and about
   90 GB per level. Always `find` first, report the size, and pass
   `max_bytes` (CLI: `--max-gb`, 10 by default).
9. **Errors:** `EgmsError` means the server answered but refused. Its
   message is the archive's message, so show it rather than retrying
   blindly.

## Without writing code

If the user only needs answers (not code), the MCP server may already be
connected: tools `releases`, `find_files`, `velocity_at`, `area_summary`
from `egms mcp` (extra `mcp`). Prefer them to downloading data by hand.

## When reporting results

State the release, the level, the component and the file(s) a number came
from. Ground motion data is evidence, not a hazard assessment: do not
present a velocity as a safety verdict on a building or slope.

Data: EGMS, © European Union, Copernicus Land Monitoring Service.
