# egms-client

Async Python client for the archive of [EGMS](https://egms.land.copernicus.eu/),
the European Ground Motion Service (Copernicus Land Monitoring Service):
ground velocity from Sentinel-1 InSAR over all of Europe.

- **Authentication with a CLMS service key**: no browser, no copied links.
- **Search and download of Ortho L3 tiles** (100 m, vertical and east-west),
  keeping only the mean-velocity GeoTIFF, cached on disk.
- **Mosaics** of tiles over any rectangle, with no resampling (extra `raster`).

[![ci](https://github.com/agent-engineering-studio/egms-client/actions/workflows/ci.yml/badge.svg)](https://github.com/agent-engineering-studio/egms-client/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/egms-client)](https://pypi.org/project/egms-client/)

## Why a library

The EGMS Explorer is built for clicking. The archive behind it has an API,
but the parts that matter are undocumented, and each one fails quietly:

| You try | What happens |
|---|---|
| any call without a login | HTTP **200** with `{"status": false, "message": "Please log in…"}` |
| the `id` in a download link as a credential | it is the id of a **search**, and it expires: HTTP 401 |
| a tile at sea | `status: false` and `Invalid tile ID`, not an empty search |
| building the file name yourself | the trailing `_1` is a sub-release: read it from the hit |
| a malformed token assertion | HTTP **500** `DecodeError`, not 401: retries won't help |
| comparing CRS by name | four tiles of 2020-2025 say `IGNF:ETRS89LAEA`, not `EPSG:3035` |
| expecting 2021-2025 after 2020-2024 | the next release was 2020-2025: windows grow |

All checked against the live archive on 3 November 2026.

## Install

```bash
pip install egms-client           # auth, search, download
pip install "egms-client[raster]" # + mosaics (numpy, rasterio, pyproj)
```

## Credentials

Create a service key at [land.copernicus.eu](https://land.copernicus.eu/):
EU Login, profile, **API Tokens**, *Create new token*. You get a JSON file
with `client_id`, `user_id`, `private_key` and `token_uri`. It does not
expire; keep it out of your repository.

## Use

```python
import asyncio
from pathlib import Path

import httpx

from egms_client import EgmsArchive, ServiceKey, tiles_for_bounds
from egms_client.mosaic import mosaic

key = ServiceKey.from_json(Path("clms-service-key.json").read_text())


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        archive = EgmsArchive(client, key)
        print(await archive.releases())  # ['2020-2024', '2020-2025']

        # Rectangle in EPSG:3035 metres
        bounds = dict(minx=4_700_000, miny=1_900_000, maxx=4_799_999, maxy=1_999_999)
        tiffs = []
        for tile in tiles_for_bounds(*bounds.values()):
            path = await archive.fetch_tile(tile, "U", "2020-2025", Path("egms"))
            if path is not None:  # None: the tile is at sea or not covered
                tiffs.append(path)

    vertical = mosaic(tiffs, **bounds)
    print(vertical.values.shape, vertical.left, vertical.top)  # (1000, 1000) 4700000.0 2000000.0


asyncio.run(main())
```

`fetch_tile` keeps the GeoTIFF (~4 MB) and drops the ~60 MB ZIP. It
remembers both outcomes in the directory (the file, or an `…absent`
marker), so running it again for a whole country sends no request. The
token is renewed five minutes before its hour runs out.

### Bring your own HTTP

Everything `EgmsArchive` does is also exposed as pure functions, for
callers with their own HTTP and retry layer: `token_request` /
`parse_token`, `search_body` / `parse_search` / `latest_hit`,
`parse_releases`, `download_url` / `check_download` / `extract_tiff`.

## Data licence

EGMS is © European Union, Copernicus Land Monitoring Service, free and
open under the [Copernicus data policy](https://land.copernicus.eu/en/data-policy):
anything you publish from it must credit the source.

Extracted from [Limen](https://github.com/agent-engineering-studio/limen),
which uses the vertical and east-west velocities per 1 km cell as ground
motion features for landslide risk.

## Development

```bash
uv sync
make check
```

## License

Code: [Apache-2.0](./LICENSE).
