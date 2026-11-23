# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `egms_client.facts` (extra `raster`): `velocity`, `area` and
  `moving_points` give answers as data. Each number comes with its release,
  its window, the files, its reliability, the licence and notes. A place
  with no cell is `measured: false` and `null`.
- `egms_client.check`, which needs no extra. `words(facts, lang)` writes the
  answer from a template in English or Italian and checks it before it
  returns. `check_text` finds numbers the facts do not hold. `check_signs`
  finds a number said to go down that the facts hold as rising, and the
  reverse. `check_claims` finds a number said of the wrong fact in the
  template's sentences. New command `egms check text facts.json --lang it`.
- The MCP server answers with the facts. `velocity_at` now carries
  reliability, surroundings, window and licence, and it returns `files`
  instead of `file`. There are two new tools: `moving_points` and
  `check_answer`. The instructions ask the model to keep the sign, to say
  how far to trust a number, and to check its text.
- A fidelity set (`benchmarks/faithful.py`, `faithful.json`): 6 questions
  with their facts from the crops and hand answers, scored offline in CI.
  In answers with known faults, the checks without a model catch 8 of 17.
  `ask` and `label` (paid) are not run yet.
- `egms_client.cells` (extra `raster`): `per_cell(cells, up, east,
  acceleration=, seasonality=, rmse=)` gives per-cell statistics for a
  model. A cell with no pixel gives `None`, never 0.0. The medians and tails
  (`vertical_p10`, `vertical_p90`) keep their sign. The vertical
  acceleration is signed (`acceleration_median`, `acceleration_p10`) and on
  the same pixels as the velocity. `valid_pixels` counts 100 m pixels, not
  radar targets. There is also a score from coverage and fit.
  `square_cells`, `on_grid` (L3 attributes on the mosaic grid) and
  `to_frame` come with it. A test checks parity with Limen's aggregation:
  same pixels, medians and p90. Three new benchmark checks: the Rione Terra
  kilometre speeds up (+16.8 mm/year²), the Murge does not (-0.02), and 74 %
  of the Foresta Umbra kilometres are not measured. The crops now keep
  `acceleration` and `seasonality`, and the east-west attributes.
- `publiccode.yml` for the Developers Italia catalogue, checked in CI by the
  official parser, and `docs/riuso.md` for public bodies (in Italian).
- A test that the package imports neither Limen nor any of its other
  libraries: only Limen joins them.
- `egms_client.reliability` (extra `raster`): `trust(tiffs, lon, lat,
  attributes=)` says how far to trust the L3 velocity at a point, as an
  estimate declared as such (EGMS publishes no trust map): the share of
  cells with a value within 500 m, the fit of the series (`rmse_ts`) when
  the L3 CSV is given, a `score` (the smallest known part), `reliable`
  from 0.5, the `reasons`, and the `regional_median` / `relative` velocity
  within 5 km. No cell is "not measured", never zero. `coverage_map` does
  the coverage for every cell of a grid. Seven new benchmark checks: the
  blind places score below 0.5 (a lone cell in the Foresta Umbra 0.03),
  the measured ones 0.79 or more.
- A benchmark of known places (`benchmarks/`): Campi Flegrei, Bologna,
  the Murge, the Foresta Umbra and Ancona, scored offline on 9.5 MB of
  crops of the real archive, in CI with `--check` against
  `benchmarks/results.json` (`make bench`). 18 of 20 checks pass; the two
  that fail show that a still place is not at zero east-west (+1.6 mm/year
  at the Murge). `benchmarks/fetch.py` crops the cases again, in the
  `bench-data` workflow with the repository secret.
- `make help`, `make notebooks` (runs them all; needs the CLMS key) and
  `make clean`; a dependency group `examples` for the notebooks.

### Changed

- `mcp_server.summarize` moved to `egms_client.facts.summarize` (still
  importable from `mcp_server`).
- A velocity rounded to zero is `0.0`, never `-0.0`.

### Fixed

- Two calls for the same file at the same time, such as a map and a card
  asking for one tile, wrote the same `.part` and left a broken ZIP: HTTP 500
  "File is not a zip file" on the page of a Comune, on 23 November 2026.
  `EgmsArchive` now holds one lock per file in `fetch` and `fetch_tile`, and
  the second call finds the file already there.
- A download that the archive closes early, cleanly, was renamed as if it
  were whole. It is now checked as a ZIP before the rename, retried, and
  then raised as `EgmsError`. `extract` refuses a broken ZIP with
  `EgmsError` instead of `BadZipFile`.

- A valid token answered with HTTP 200 "Please log in" (seen once in 15
  calls of the live check on 23 November 2026): the client asks for a new
  token and tries once more; a second refusal raises `EgmsError`.

## [0.7.0] - 2026-11-04

### Added

- `egms_client.analysis` (extra `tables`): `fit(frame, start=, end=)` is
  the model the archive fits to each series (velocity, acceleration,
  seasonal amplitude, rmse). It gives back `mean_velocity`, `acceleration`
  and `rmse_ts` within rounding, on any window, with the day of the year
  the seasonal cycle peaks. `trend_change` gives the date a series changes
  velocity, the velocities before and after, and `delta_bic`.
  `unwrapping_jumps` finds steps of half the Sentinel-1 wavelength
  (27.7 mm). About 3 seconds each for a whole L3 tile.

## [0.6.0] - 2026-11-04

### Added

- `egms mcp`, an MCP server (extra `mcp`, on the MCP Python SDK 2.x) with
  four tools: `releases`, `find_files` (files and sizes over a box, nothing
  downloaded), `velocity_at` and `area_summary` (coverage, mean,
  percentiles, share below / above a stable band, the 5 fastest cells).
  Answers carry their release and files; `area_summary` downloads at most
  `--max-tiles` L3 tiles per box; the key is read from the server's
  environment only. `mcp_server.create_server()` builds it in Python.
- `EgmsArchive.velocity_at(lon, lat, component="U", release=None)`: the L3
  velocity of the 100 m cell at a point in degrees, as a `PointVelocity`
  that also carries its release, tile and file (`None` velocity at sea or
  without data). Only that tile is downloaded, once. Pure helpers:
  `tile_for_point(x, y)`, `mosaic.lonlat_to_xy`, `mosaic.value_at`.
- `egms_client.sync.Archive`: the client without `async`, its own event loop
  in a background thread, so it also works inside Jupyter.
- A live check: Pozzuoli rises by more than 50 mm/year, the sea has no
  velocity.
- Documentation site (MkDocs Material + mkdocstrings): the README as home
  page, the notebooks, an API reference generated from the docstrings, the
  changelog. Built with `--strict` on every pull request, published to
  GitHub Pages from `main` (`make docs` builds it locally).
- README links are absolute, so they work on GitHub, PyPI and the site.
- A roadmap page: foundations, time-series analysis and AI features.
- `llms.txt` and `llms-full.txt` on the site, built from the sources by a
  MkDocs hook (`hooks/llms.py`): the index for AI assistants, and the whole
  documentation as one text file with the API reference rendered from the
  docstrings.
- An agent skill, `skills/egms-client/SKILL.md`, also served by the site:
  how to use the library and the rules the archive enforces. A test checks
  that every import, method and constant it names exists.

## [0.5.0] - 2026-11-03

### Added

- `mosaic.to_xarray(m)`: a mosaic as an `xarray.DataArray` on `y` / `x`
  pixel centres in EPSG:3035, with the CRS CF-style in a `spatial_ref`
  coordinate (read by rioxarray, GDAL, pyproj).
- `tables.to_xarray(frame)`: the series of a CSV as a `DataArray` over
  `(pid, time)`, every attribute (`mean_velocity`, `easting`, ...) a
  coordinate along `pid`. New extra `xarray`.
- `Hit.footprint` (the outline the archive returns, `(lon, lat)` corners)
  and `Hit.covers(lon, lat)`: a burst is a tilted parallelogram, so its
  bbox claims points it does not contain.
- `notebooks/`: Campi Flegrei, a landslide in Ancona, Bologna sinking, run
  on real data, each with its figure in `docs/images/`.
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

### Fixed

- The archive allows **2 concurrent downloads per account**; a third is
  answered HTTP 429. Every download of an `EgmsArchive` (`fetch`,
  `fetch_tile`, and the caller's own parallel calls) now goes through one
  gate of `MAX_DOWNLOADS = 2`; `concurrency` defaults to 2 (it was 4, which
  failed on the third file). A 429 waits for `Retry-After`, or at least 30 s.
- A download interrupted by an error or a cancellation no longer leaves a
  `.part` file.

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
