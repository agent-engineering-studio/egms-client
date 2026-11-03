<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/egms-client/main/docs/images/banner.svg" alt="egms-client: ground motion of Europe from space, in a few lines of Python" width="100%">
</p>

<p align="center">
  <a href="https://github.com/agent-engineering-studio/egms-client/actions/workflows/ci.yml"><img src="https://github.com/agent-engineering-studio/egms-client/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://pypi.org/project/egms-client/"><img src="https://img.shields.io/pypi/v/egms-client" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-blue" alt="Python 3.12 | 3.13">
  <img src="https://img.shields.io/badge/typing-mypy%20strict-informational" alt="mypy strict">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

**egms-client** is a small, typed, async Python library for the archive of
[EGMS](https://egms.land.copernicus.eu/), the **European Ground Motion
Service**. EGMS measures how much the ground moves, millimetre by millimetre,
across all of Europe, using radar satellites. This library lets you download
that data from a script, with no browser and no copy-pasted links.

```python
path = await archive.fetch_tile((47, 19), "U", "2020-2025", Path("egms"))
# egms/EGMS_L3_E47N19_100km_U_2020_2025_1.tiff  (vertical speed, mm/year)
```

---

## Contents

- [What is EGMS, in 30 seconds](#what-is-egms-in-30-seconds)
- [What this library does](#what-this-library-does)
- [Who is it for](#who-is-it-for)
- [Quick start](#quick-start)
- [Where downloads are saved](#where-downloads-are-saved)
- [Time series as tables](#time-series-as-tables)
- [How it works](#how-it-works)
- [Recipes](#recipes)
- [The traps we already fell into](#the-traps-we-already-fell-into)
- [API at a glance](#api-at-a-glance)
- [Contributing](#contributing) · [Ideas to work on](#ideas-to-work-on)
- [Data licence and credits](#data-licence-and-credits)

---

## What is EGMS, in 30 seconds

The Sentinel-1 satellites fly over Europe every few days and send down radar
pulses. Comparing the echoes from one pass to the next (a technique called
**InSAR**) shows whether a point on the ground moved closer or farther, down
to a few millimetres. Copernicus turns years of these measurements into
**maps of speed**: how fast the ground goes up or down, east or west, in
**millimetres per year**.

```mermaid
flowchart LR
    S["🛰️ Sentinel-1<br/>radar, every few days"] --> I["InSAR processing<br/>(Copernicus)"]
    I --> A["EGMS archive<br/>Ortho L3 tiles"]
    A -->|egms-client| Y["📁 GeoTIFF on your disk<br/>speed in mm/year"]
    Y --> U["Your analysis<br/>maps · models · alerts"]
```

What you can see with it, for example:

- a **town that is sinking** because groundwater is pumped out (subsidence);
- a **slope that creeps** downhill before a landslide;
- a **bridge, dam or railway** that settles more than it should;
- the ground **rising** above a volcano or a gas storage site.

> Negative vertical speed (`U < 0`) means the ground goes **down**;
> positive means it goes **up**.

Here is real data, made with one command of this library. Around Pozzuoli
the Campi Flegrei caldera is **rising by up to 16 cm a year**, while Naples
and Vesuvius barely move:

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/egms-client/main/docs/images/naples-vertical.png" alt="EGMS vertical ground speed around Naples, 2020-2025: the Campi Flegrei caldera at Pozzuoli rises by up to 160 mm a year" width="100%">
</p>

```bash
egms mosaic --bbox 13.95,40.75,14.55,41.0 --component U --out naples-U.tif
```

## What this library does

| | Feature | In plain words |
|---|---|---|
| 🔑 | **Login with a CLMS service key** | Your key file is all it needs, from a path or an environment variable. Tokens are created and renewed for you. |
| 🔎 | **Every product of the archive** | **L3** speed maps (vertical `U`, east-west `E`, 100 m grid) and **L2A / L2B** measurement points with their full time series. |
| 🗺️ | **Search by area in degrees** | Give a box in longitude/latitude; areas larger than the archive accepts are split for you. |
| 💾 | **Never download twice** | Files already on disk are skipped, interrupted runs resume, and you choose what to keep of each ZIP (`tiff`, `csv`, `xml`, `parquet` or the ZIP). |
| 📈 | **Time series as tables** | The CSVs in pandas, or straight to **GeoParquet** (a 250 MB CSV becomes ~60 MB) for GeoPandas, QGIS, DuckDB. |
| 🛡️ | **Safe by default** | Parallel downloads with a limit, automatic retries, a size check before the first byte. |
| 🖥️ | **Command line** | `egms search` and `egms download`, no Python needed. |
| 🧩 | **Mosaics** | Glue tiles into one array over any rectangle, with no resampling. |
| 🧪 | **Pure functions too** | Every step is also a plain function, if you have your own HTTP stack. |

## Who is it for

- **Researchers and students** in geology, geophysics and remote sensing who
  want EGMS data in a notebook or pipeline.
- **GIS and data engineers** who need to download a region or a whole
  country, repeatably.
- **Risk and infrastructure teams** (landslides, subsidence, monitoring of
  roads, railways, dams) who use ground motion as one input among many.

It started inside [Limen](https://github.com/agent-engineering-studio/limen),
where the vertical and east-west speeds of each 1 km cell are features of a
landslide-risk model, and was extracted so that anyone can use it.

---

## Quick start

### 1. Install

```bash
pip install egms-client           # login, search, download
pip install "egms-client[raster]" # + mosaics (numpy, rasterio, pyproj)
pip install "egms-client[tables]" # + CSVs as pandas / GeoParquet (pandas, pyarrow, pyproj)
pip install "egms-client[xarray]" # + maps and series as xarray DataArray
```

Python 3.12 or newer.

### 2. Get a service key (once, 2 minutes)

1. Go to [land.copernicus.eu](https://land.copernicus.eu/) and sign in with **EU Login**.
2. Open your profile → **API Tokens** → *Create new token*.
3. Save the JSON file you get, e.g. as `clms-service-key.json`.

It contains `client_id`, `user_id`, `private_key` and `token_uri`, and it
**does not expire**. Treat it like a password: keep it out of git.

> The key is shown **only once**, right after *Create new token*: copy the
> whole JSON then. The token list shows only its `key_id`, which is not
> enough to log in.

Then tell egms-client where it is, with **one** of these environment
variables, so no code ever contains a path or a secret:

```bash
export EGMS_SERVICE_KEY_FILE=~/clms-service-key.json   # a file on disk
export EGMS_SERVICE_KEY="$(cat ~/clms-service-key.json)"  # or the JSON itself (CI, Docker secrets)
```

### 3. Download your first tile

```python
import asyncio
from pathlib import Path

from egms_client import EgmsArchive


async def main() -> None:
    async with EgmsArchive() as archive:  # key from the environment
        print(await archive.releases())  # ['2020-2024', '2020-2025']

        path = await archive.fetch_tile((47, 19), "U", "2020-2025", Path("egms"))
        print(path)  # egms/EGMS_L3_E47N19_100km_U_2020_2025_1.tiff


asyncio.run(main())
```

That's it: `path` is a GeoTIFF of 1,000 × 1,000 pixels, each one the mean
vertical speed of a 100 m square, in mm/year.

### 3b. Or from the command line

```bash
egms releases
egms search   --level L2B --bbox 14.4,40.0,15.7,41.0     # what is there, and how many GB
egms download --tile E47N19 --component U --keep tiff --out egms
egms download --level L2B --bbox 14.4,40.0,15.7,41.0 --keep parquet --max-gb 10
egms convert  egms/EGMS_L3_E47N19_100km_U_2020_2025_1.csv   # a CSV you already have
egms mosaic   --bbox 13.95,40.75,14.55,41.0 --component U --out naples-U.tif   # a map, extra raster
```

`--bbox` is *west,south,east,north* in degrees. `download` and `mosaic` stop
before the first byte if the total is above `--max-gb` (10 by default), and
show their progress: one updating line in a terminal, a line per file in a
log.

`egms mosaic` downloads the L3 tiles a box touches (once: they stay in
`--data-dir`), pastes them, and writes a **Cloud-Optimized GeoTIFF** in
EPSG:3035 (float32, NaN as nodata, with overviews): drag it into QGIS, or
serve it over HTTP as is.

### 4. Make a mosaic and look at it

```python
from egms_client import tiles_for_bounds
from egms_client.mosaic import mosaic

# A rectangle in EPSG:3035 metres (here: exactly tile E47N19)
bounds = dict(minx=4_700_000, miny=1_900_000, maxx=4_799_999, maxy=1_999_999)


async def download(archive: EgmsArchive) -> list[Path]:
    tiffs = []
    for tile in tiles_for_bounds(*bounds.values()):
        path = await archive.fetch_tile(tile, "U", "2020-2025", Path("egms"))
        if path is not None:  # None: the tile is at sea or not covered
            tiffs.append(path)
    return tiffs


# ... after downloading:
vertical = mosaic(tiffs, **bounds)
print(vertical.values.shape, vertical.left, vertical.top)
# (1000, 1000) 4700000.0 2000000.0
```

Want a picture? With `pip install matplotlib`:

```python
import matplotlib.pyplot as plt

rows, cols = vertical.values.shape
extent = (
    vertical.left,
    vertical.left + cols * vertical.pixel,
    vertical.top - rows * vertical.pixel,
    vertical.top,
)
plt.imshow(vertical.values, cmap="RdBu_r", vmin=-10, vmax=10, extent=extent)
plt.colorbar(label="vertical speed (mm/year)")  # blue: sinking, red: rising
plt.title("EGMS Ortho L3 · E47N19 · 2020-2025")
plt.show()
```

---

## Where downloads are saved

In the directory you pass (`directory` in Python, `--out` on the command
line). If you pass none:

1. `EGMS_DATA_DIR`, if set;
2. otherwise `~/.cache/egms-client` (or `$XDG_CACHE_HOME/egms-client`).

The directory is also the cache: whatever is already there is **not
downloaded again**, so the next run with the same request only asks the
archive for the list of files (a few KB) and returns.

In **Docker**, point it at a volume so the data survives the container:

```yaml
services:
  app:
    environment:
      EGMS_DATA_DIR: /data/egms
      EGMS_SERVICE_KEY_FILE: /run/secrets/clms_service_key
    volumes:
      - egms-data:/data/egms
    secrets:
      - clms_service_key
volumes:
  egms-data:
secrets:
  clms_service_key:
    file: ./clms-service-key.json
```

---

## How it works

### Tiles: how Europe is cut into squares

The Ortho L3 product lives on a single grid in **EPSG:3035** (the standard
equal-area projection for Europe). The grid is cut into 100 km squares, and
each square is named after its **lower-left corner, in hundreds of
kilometres**.

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/egms-client/main/docs/images/tiles.svg" alt="Tile grid: E47N19 starts at 4,700 km east and 1,900 km north; a rectangle spanning four tiles returns those four tiles" width="100%">
</p>

You never have to compute tile names by hand: give `tiles_for_bounds` a
rectangle and it returns every tile it touches.

```python
>>> tiles_for_bounds(4_530_000, 1_740_000, 4_670_000, 1_870_000)
[(45, 17), (45, 18), (46, 17), (46, 18)]
>>> tile_id((47, 19))
'E47N19'
```

### Logging in: the service key never leaves your machine

Your key signs a short-lived request (a JWT); the Copernicus server answers
with a token valid for one hour. `EgmsArchive` asks for a new one **five
minutes before it expires**, so a download of a whole country, which takes
longer than an hour, never stops halfway.

```mermaid
sequenceDiagram
    autonumber
    participant You as Your script
    participant C as EgmsArchive
    participant T as CLMS token endpoint
    participant A as EGMS archive

    You->>C: fetch_tile((47, 19), "U", "2020-2025")
    C->>C: sign a JWT with the private key (RS256)
    C->>T: POST token_uri (JWT bearer grant)
    T-->>C: access_token, valid 1 hour
    C->>A: POST /search  (Bearer token)
    A-->>C: search id + files
    C->>A: GET /download/<file>?id=<search id>
    A-->>C: ZIP (~60 MB)
    C-->>You: Path to the GeoTIFF (~4 MB)
```

### Downloading: what `fetch_tile` decides

```mermaid
flowchart TD
    start(["fetch_tile(tile, component, release, dir)"]) --> c1{"GeoTIFF already<br/>in dir?"}
    c1 -- yes --> r1(["return its path<br/>no network"])
    c1 -- no --> c2{"'…absent' marker<br/>in dir?"}
    c2 -- yes --> r0(["return None<br/>no network"])
    c2 -- no --> s["search the archive"]
    s --> c3{"tile exists?"}
    c3 -- "no (sea, no coverage)" --> m["write '…absent' marker"] --> r0b(["return None"])
    c3 -- yes --> d["download ZIP<br/>of the latest sub-release"]
    d --> x["extract only the GeoTIFF<br/>write it atomically (.part → .tiff)"]
    x --> r2(["return its path"])
```

Because **both** outcomes are written to disk, running the same script again
over a whole country sends **zero requests**. And because the file is first
written as `.part` and then renamed, an interrupted run never leaves a
half-written GeoTIFF behind.

### Why it keeps only the GeoTIFF

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/egms-client/main/docs/images/sizes.svg" alt="Per tile: ZIP about 60 MB, CSV about 245 MB unpacked, GeoTIFF kept about 4 MB" width="100%">
</p>

Each ZIP also holds a CSV with the full time series of every pixel. It is
large and most uses only need the mean speed, so `fetch_tile` leaves it out.
Need the time series? `fetch(..., keep=["parquet"])` keeps it as GeoParquet,
about a quarter of the CSV: see [Time series as tables](#time-series-as-tables).

### The building blocks

The library has two layers. You can use the high-level client, or call the
pure functions with any HTTP library you like.

```mermaid
flowchart LR
    subgraph yours["Your code"]
        H["httpx.AsyncClient<br/>(timeouts, retries, proxy)"]
    end
    subgraph lib["egms_client"]
        direction TB
        CL["client.py<br/>EgmsArchive"]
        AU["auth.py<br/>ServiceKey · token_request · parse_token"]
        AR["archive.py<br/>search_body · parse_search · extract_tiff …"]
        MO["mosaic.py<br/>mosaic · to_cog<br/>(extra: raster)"]
        ER["errors.py<br/>EgmsError"]
    end
    H --> CL
    CL --> AU
    CL --> AR
    AR -. GeoTIFFs .-> MO
```

- **`auth.py`, `archive.py`**: pure functions, no network. They build
  requests and read answers. Easy to test, easy to reuse.
- **`client.py`**: `EgmsArchive` wires them to **your** `httpx.AsyncClient`.
  Timeouts, retries and proxies stay under your control.
- **`mosaic.py`**: optional, only needs `numpy`, `rasterio`, `pyproj`.

---

## Recipes

### Download a whole region, both components

```python
for component in ("U", "E"):  # vertical, east-west
    for tile in tiles_for_bounds(4_300_000, 1_500_000, 5_200_000, 2_700_000):
        await archive.fetch_tile(tile, component, "2020-2025", Path("egms"))
```

Stop it and start it again whenever you like: finished tiles are skipped.

### Measurement points (L2A, L2B) over an area

```python
from egms_client import EgmsArchive, Query

query = Query(levels=("L2B",), release="2020-2025", bbox=(14.4, 40.0, 15.7, 41.0))

async with EgmsArchive() as archive:
    found = await archive.find(query)  # nothing downloaded yet
    gb = sum(h.filesize for s in found for h in s.hits) / 1e9
    print(f"{gb:.1f} GB")  # 8.5 GB: 41 bursts

    paths = await archive.fetch(query, Path("egms"), keep=["csv"], max_bytes=10**10)
```

Each CSV holds one row per measurement point: position (`latitude`,
`longitude`, `easting`, `northing`), quality (`temporal_coherence`,
`rmse_ts`), speed (`mean_velocity`, in mm/year along the satellite's line of
sight) and one column per acquisition date with the displacement in mm.

Other filters: `relative_orbit=124`, `burst_cycle=835`, `swath="IW3"`,
`direction="descending"`. L2A is the same with `levels=("L2A",)`.

### Time series as tables

With the `tables` extra, every CSV of the archive (L2A, L2B and L3) reads
the same way: attributes first, then one column per acquisition date with
the displacement in mm.

```python
from egms_client.tables import attributes, dates, read_csv, series_long

points = read_csv(Path("egms/EGMS_L3_E47N19_100km_U_2020_2025_1.csv"))
print(len(points), len(dates(points)))  # 169917 cells, 302 dates
fast = attributes(points).query("mean_velocity < -10")  # sinking > 1 cm/year
long = series_long(points[points.pid.isin(fast.pid)])  # pid, date, displacement_mm
```

`read_csv(path, series=False)` skips the dates and uses far less memory.

Or skip pandas and go straight to **GeoParquet**, points in EPSG:3035,
streamed in blocks so memory stays flat (~0.5 GB for a 250 MB CSV):

```python
paths = await archive.fetch(query, Path("egms"), keep=["parquet"])  # no CSV left on disk
```

```python
import geopandas as gpd

cells = gpd.read_parquet("egms/EGMS_L3_E47N19_100km_U_2020_2025_1.parquet")
cells.plot(column="mean_velocity", cmap="RdBu_r", vmin=-10, vmax=10, markersize=0.1)
```

DuckDB reads it too: `SELECT avg(mean_velocity) FROM 'egms/*.parquet'`.

### As xarray

With the `xarray` extra (`pip install "egms-client[raster,tables,xarray]"`),
maps and series become labelled arrays for the scientific Python stack:

```python
from egms_client.mosaic import to_xarray
from egms_client.tables import to_xarray as series_to_xarray

grid = to_xarray(vertical)  # dims (y, x), EPSG:3035 in `spatial_ref`
grid.sel(x=4_773_750, y=1_900_050, method="nearest")

series = series_to_xarray(points)  # dims (pid, time), displacement in mm
rising = series.where(series.mean_velocity > 10, drop=True)
rising.mean("pid").plot()  # the average curve of the fastest-rising cells
```

### Always use the newest release

```python
release = (await archive.releases())[-1]  # sorted oldest first
```

### Handle errors

```python
from egms_client import EgmsError

try:
    path = await archive.fetch_tile((47, 19), "U", "2020-2025", Path("egms"))
except EgmsError as exc:
    # The archive or the token endpoint answered, but refused:
    # bad key, expired search, missing GeoTIFF in the ZIP...
    print("EGMS said no:", exc)
except httpx.HTTPError as exc:
    # Network problems still failing after 3 retries.
    print("network:", exc)
```

### Bring your own HTTP (sync example)

No `asyncio`? Every step is a plain function:

```python
import time
from pathlib import Path

import httpx

from egms_client import (
    ARCHIVE_URL,
    ServiceKey,
    check_download,
    download_url,
    extract_tiff,
    latest_hit,
    parse_search,
    parse_token,
    search_body,
    token_request,
)

key = ServiceKey.from_json(Path("clms-service-key.json").read_text())

with httpx.Client(timeout=120) as http:
    now = time.time()
    r = http.post(
        key.token_uri, data=token_request(key, now=int(now)), headers={"Accept": "application/json"}
    )
    token = parse_token(r.status_code, r.content, now=now)

    r = http.post(
        f"{ARCHIVE_URL}/search",
        headers=token.headers(),
        json=search_body((47, 19), "U", "2020-2025"),
    )
    search = parse_search(r.content)  # None: tile at sea
    hit = latest_hit(search) if search else None

    if search and hit:
        r = http.get(download_url(ARCHIVE_URL, hit), params={"id": search.id})
        tiff = extract_tiff(check_download(r.status_code, r.content), hit)
        Path(f"{hit.stem}.tiff").write_bytes(tiff)
```

---

## The traps we already fell into

The EGMS Explorer is built for clicking. The API behind it works, but the
parts that matter are undocumented, and each one fails **quietly**. This
library handles all of these for you:

| You try | What actually happens | What egms-client does |
|---|---|---|
| any call without a login | HTTP **200** with `{"status": false, "message": "Please log in…"}` | raises `EgmsError` |
| the `id` in a download link as a credential | it is the id of a **search**, and it expires: HTTP 401 | searches, then downloads right away |
| a tile at sea | `status: false` and `Invalid tile ID`, not an empty result | returns `None`, remembers it |
| building the file name yourself | the trailing `_1` is a sub-release that can change | reads the name from the search hit |
| a malformed token request | HTTP **500** `DecodeError`, not 401: retrying won't help | raises `EgmsError` with the message |
| comparing CRS by name | four 2020-2025 tiles say `IGNF:ETRS89LAEA`, not `EPSG:3035` | compares projection parameters |
| expecting 2021-2025 after 2020-2024 | the next release was 2020-2025: windows grow | lists releases from the API |
| asking for level `L2a` as in the file names | `Invalid level`: the API wants `L2A` | uses the API's names |
| relative orbit `22` | `Invalid relative orbit`: it must be the string `"022"` | pads it for you |
| a bbox in any other shape than `[[w, s], [e, n]]` | `An error occurred processing the search` | builds the right shape |
| a box of 7° × 7° | `Requested area is too large` (5° × 5° passes) | splits it and merges the results |
| a third download at the same time | HTTP **429** `At most 2 downloads may be performed simultaneously` (per account) | never more than 2 at once, whatever you ask |

All checked against the live archive on 3 November 2026.

---

## API at a glance

| Name | What it does |
|---|---|
| `ServiceKey.from_env()` | The key from `EGMS_SERVICE_KEY` or `EGMS_SERVICE_KEY_FILE`. |
| `ServiceKey.from_file(path)` / `.from_json(text)` | The key from a file or a string. |
| `EgmsArchive(client=None, key=None)` | The async client; opens its own HTTP client and reads the key from the environment if not given. |
| `.releases()` / `.levels()` / `.bursts()` | What the archive publishes. |
| `Query(levels, release, bbox=, tile=, relative_orbit=, ...)` | What to look for. |
| `.find(query)` | The matching files, latest version of each; nothing downloaded. |
| `.fetch(query, dir, keep=, concurrency=, max_bytes=, on_progress=)` | Download them, skipping what is on disk; `on_plan`, `on_progress`, `on_file` report as it goes. |
| `.search(tile, component, release)` | One search; `None` if the tile does not exist. |
| `.fetch_tile(tile, component, release, dir)` | GeoTIFF path (cached), or `None`. |
| `tiles_for_bounds(minx, miny, maxx, maxy)` | Tiles covering a rectangle (EPSG:3035 m). |
| `tile_id((e, n))` / `parse_tile_id(text)` | `(47, 19)` ↔ `"E47N19"`. |
| `default_directory()` | Where downloads go when no directory is given. |
| `mosaic(tiffs, minx=, miny=, maxx=, maxy=)` | One float32 array, NaN where no data. |
| `to_cog(mosaic, path)` / `lonlat_to_laea(w, s, e, n)` | A mosaic as Cloud-Optimized GeoTIFF; a box in degrees as EPSG:3035 metres. |
| `tables.read_csv(path, series=, columns=)` | A CSV as a pandas DataFrame (extra `tables`). |
| `tables.dates(df)` / `.attributes(df)` / `.series_long(df)` | Its dates, its attributes, its series one row per date. |
| `tables.csv_to_geoparquet(csv)` / `.to_geoparquet(df, path)` | GeoParquet, points in EPSG:3035. |
| `mosaic.to_xarray(m)` / `tables.to_xarray(df)` | A map over `(y, x)`, series over `(pid, time)`, as `xarray.DataArray` (extra `xarray`). |
| `EgmsError` | The server answered, but refused. |

Lower level, for your own HTTP layer: `token_request` / `parse_token`,
`search_body` / `parse_search` / `latest_hit`, `parse_releases`,
`download_url` / `check_download` / `extract_tiff`.

---

## Contributing

Contributions of every size are welcome, from a typo to a new feature. You
don't need to be an InSAR expert: most of the code is plain Python, HTTP and
files.

```bash
git clone https://github.com/agent-engineering-studio/egms-client
cd egms-client
uv sync          # install everything, dev tools included
make check       # ruff + mypy --strict + pytest, the same gate as CI
```

The tests **do not need a service key or network**: they run against
recorded answers of the real archive in [`tests/fixtures/`](tests/fixtures/).

```text
egms-client/
├── src/egms_client/
│   ├── auth.py      # service key → JWT → bearer token
│   ├── archive.py   # tiles, search, download: pure functions
│   ├── client.py    # EgmsArchive: async client, cache, token renewal
│   ├── mosaic.py    # tiles → one array, Cloud-Optimized GeoTIFF (extra: raster)
│   ├── tables.py    # CSVs → pandas, GeoParquet (extra: tables)
│   ├── cli.py       # the `egms` command
│   └── errors.py    # EgmsError
└── tests/
    ├── fixtures/    # real archive answers, for offline tests
    └── live/        # the same behaviour, checked weekly on the real archive
```

The archive's API is undocumented, so a **weekly workflow**
(`.github/workflows/live.yml`) runs `tests/live` against the real archive
and opens an issue if something changed. To run it yourself:
`EGMS_LIVE=1 EGMS_SERVICE_KEY_FILE=~/clms-service-key.json uv run pytest tests/live`.

How to propose a change:

```mermaid
flowchart LR
    A["Open an issue<br/>or pick one"] --> B["Fork + branch"]
    B --> C["Code + tests"]
    C --> D["make check ✅"]
    D --> E["Pull request<br/>Conventional Commits"]
    E --> F["Review & merge 🎉"]
```

Rules are short: see [CONTRIBUTING.md](./CONTRIBUTING.md). Commits follow
[Conventional Commits](https://www.conventionalcommits.org/), coverage stays
above 90%, and contributions are accepted under Apache-2.0.

### Ideas to work on

Not promises, just directions where help would make a difference. Open an
issue to discuss one before starting.

| Idea | Why it matters | Good for |
|---|---|---|
| 📓 **Example notebooks** (a city, a landslide, a coastline) | Show what the data can do | first contribution, GIS users |
| 🧭 **Mosaics from L2 points** (gridding, line-of-sight decomposition) | Your own maps from the raw measurements | advanced, InSAR users |
| 📚 **Documentation site** | Search, API reference, tutorials | anyone |

Found something odd in the archive? That is a contribution too: open an issue
with what you sent and what came back.

---

## Data licence and credits

EGMS data is © European Union, Copernicus Land Monitoring Service, free and
open under the [Copernicus data policy](https://land.copernicus.eu/en/data-policy).
Anything you publish from it **must credit the source**, for example:

> Contains modified Copernicus Land Monitoring Service information (EGMS), © European Union.

The images in this README are illustrations, not EGMS data.

Code: [Apache-2.0](./LICENSE). Extracted from
[Limen](https://github.com/agent-engineering-studio/limen).

If this project is useful to you, a ⭐ on GitHub helps others find it.
