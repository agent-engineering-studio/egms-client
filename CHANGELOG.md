# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `egms_client.decompose`: `grid_los` averages L2 points (mean velocity and
  line-of-sight vector, coherent points only) on a grid in EPSG:3035, and
  `decompose` turns one ascending and one descending grid into vertical and
  east-west `Mosaic`s. Over Ancona it matches L3 with correlation 0.93
  (vertical) and 0.79 (east-west), median difference 0.6 and 0.2 mm/year.

## [0.4.0] - 2026-11-03

### Added

- `egms mosaic --bbox W,S,E,N --component U|E`: the L3 tiles a box in
  degrees touches, downloaded once, pasted and written as a Cloud-Optimized
  GeoTIFF in EPSG:3035 (extra `raster`).
- `egms_client.mosaic.to_cog` (float32, NaN nodata, deflate, overviews) and
  `lonlat_to_laea` (a box in degrees to EPSG:3035 metres, edges densified).
- Download progress: `fetch(..., on_plan=, on_progress=)`; `egms download`
  and `egms mosaic` show one updating line on a terminal, a line per file in
  a log.
- `tests/live` and a weekly `live` workflow: the archive behaviour the
  library relies on (lists, the five known refusals, a 5° box, an L3 tile, a
  small L2B download) checked against the real archive, with an issue opened
  on failure. Needs the repository secret `EGMS_SERVICE_KEY`.
- README: a real map (vertical speed around Naples, 2020-2025).

## [0.3.0] - 2026-11-03

### Added

- `egms_client.tables` (extra `tables`: pandas, pyarrow, pyproj): `read_csv`
  reads any CSV of the archive (L2A, L2B, L3) with float32 dates, optionally
  without them or with fewer attributes; `dates`, `attributes`,
  `series_long`; `to_geoparquet` and `csv_to_geoparquet` write GeoParquet
  1.1 with WKB points in EPSG:3035 from `easting` / `northing`. The CSV is
  streamed in blocks: a 250 MB L3 CSV converts in ~7 s with ~0.5 GB of
  memory, to ~60 MB.
- `fetch(..., keep=["parquet"])`: the CSV of each ZIP converted to
  GeoParquet, the CSV removed unless also kept.
- `egms convert`: CSVs already on disk to GeoParquet; `egms download --keep
  parquet`.

### Fixed

- Concurrent requests share one token request instead of each asking for
  one; a busy token endpoint (429/502/503/504, network errors) is retried.
  Its 500 (a bad assertion) is still not.
- L3 ZIPs also hold an XML: `keep="xml"` is documented for every level.

## [0.2.0] - 2026-11-03

### Added

- All the archive's levels: L2A (`BASIC`) and L2B (`CALIBRATED`) bursts
  besides Ortho L3. `Query` describes a search (levels, release, `bbox` in
  degrees, `tile`, `relative_orbit`, `burst_cycle`, `swath`, `direction`,
  `product_type`); `query_body` builds it, padding the orbit to the three
  digits the archive requires.
- `EgmsArchive.find`: the files a query matches, latest sub-release of each;
  a box larger than the archive accepts (5° a side) is split by `split_bbox`
  and the results merged.
- `EgmsArchive.fetch`: downloads streamed to disk (`.part`, then renamed),
  in parallel with a limit, retried on network errors and 429/502/503/504,
  a search searched again when its id expires, files already on disk
  skipped, `keep` choosing the ZIP or its `tiff` / `csv` / `xml`, and
  `max_bytes` refusing a download before its first byte.
- `EgmsArchive.levels`, `.bursts`; `Hit` carries level, path, bbox and the
  burst fields.
- `ServiceKey.from_env` (`EGMS_SERVICE_KEY` or `EGMS_SERVICE_KEY_FILE`) and
  `ServiceKey.from_file`; `EgmsArchive()` with no arguments opens its own
  HTTP client and reads the key from the environment.
- `default_directory`: `EGMS_DATA_DIR`, else the user cache.
- `egms` command line: `releases`, `levels`, `search`, `download`.

### Changed

- `fetch_tile` streams the ZIP to disk instead of holding it in memory, and
  its `directory` is optional.

## [0.1.1] - 2026-11-03

### Fixed

- `EgmsArchive.fetch_tile` refuses a hit whose file name does not belong to
  the requested tile or contains `/` (`EgmsError`), instead of saving it
  where the cache never finds it again.
- The cached sub-release is chosen by number (`_10` over `_9`), as
  `latest_hit` already did.

## [0.1.0] - 2026-11-03

### Added

- `ServiceKey`, `assertion`, `token_request`, `parse_token`: bearer tokens
  from a CLMS service key (RS256 JWT bearer grant).
- `search_body` / `parse_search` / `latest_hit`, `parse_releases`,
  `download_url` / `check_download` / `extract_tiff`: Ortho L3 tiles, with
  sea tiles as `None` and refusals served as HTTP 200 as `EgmsError`.
- `EgmsArchive`: async client over an injected `httpx.AsyncClient`, with
  token renewal and an on-disk cache of tiles and absent tiles.
- `egms_client.mosaic` (extra `raster`): tiles pasted on one grid, CRS
  compared by parameters (`IGNF:ETRS89LAEA` tiles accepted).
- Extracted from Limen (`src/limen/integrations/egms/` at 9b977bb) and
  relicensed under Apache-2.0 by its sole author. New: file names come from
  the search hit, so sub-releases other than `_1` work.
