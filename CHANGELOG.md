# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.10.0] - 2026-11-28

Next: a minor release (0.10.0).

### Added

- `fetch_tile(..., keep=("tiff", "attributes"))`, `init(keep=...)` and `egms init --keep attributes`: the attributes of a tile (position, velocity, acceleration, seasonality, RMSE) without its time series, in `<stem>.attributes.csv` beside the GeoTIFF: a few MB instead of the 250 MB of the CSV, which is not left on the disk. A tile whose GeoTIFF is there and whose attributes are not is downloaded again, once. Read it with `tables.read_csv(path, series=False)` and put a column on a mosaic with `cells.on_grid`.
- `tables.csv_attributes(csv, out=None)`: a CSV of the archive without its date columns. Standard library only, streamed.

### Changed

- The package may not import `limen_core` either (`tests/test_package.py`).

## [0.9.0] - 2026-11-25

Next: a minor release (0.9.0).

### Added

- `init()` and `egms init`: the Ortho L3 tiles of an area (`bbox` in degrees, or `tiles`), both components or those chosen, downloaded once into the data folder to work offline. Every tile goes through `fetch_tile`, so the result is the cache the rest of the library reads; a second run asks the archive nothing. At most two downloads at once (the archive's limit per account). A tile that fails is reported in the result (`InitResult`: downloaded, already there, absent, failed, bytes), not raised; a disk error raises. It takes your `httpx.AsyncClient` and `retries=0`, to leave every retry to the caller, and `keep` per component (`{"U": ("tiff", "csv")}`). `egms init` exits 1 if a tile failed.
- The card of a point opens over the map, slightly see-through: an arrow for the motion, a chart of the point against the median 5 km around, a meter for reliability, the period measured, and a line for the series of other sources nearby.
- Where the ground moves most: the eight 1 km squares with the largest median vertical velocity (at least 5 mm/year, where EGMS measures at least a quarter of the cells), numbered on the map and ranked in the panel (`/api/hotspots`). Zones to follow, not an alert.
- The boundaries of the Comuni from ISTAT (generalised, 1 January 2025, CC BY 4.0), downloaded once at startup: data gaps count land only, the Comune of the page gets its own count, and its outline is on the map (`/api/boundary`). The sea is no longer a gap.
- A loading screen at the first start: a progress bar and the state of each EGMS tile of the area, from `/api/health` (`startup`); the map opens when they are on the disk. If the archive does not answer for 90 s, the visitor can enter with the tiles already there.
- `EgmsArchive.fetch_tile(..., on_progress=)`: the bytes of a download as they arrive.
- Data gaps: the page marks in amber the 1 km squares where EGMS measures less than a quarter of the cells, counts them for the area (`/api/gaps`), and says on the card of a point if its square is one. They are where a Comune can publish more open data; not a danger. The page now says what it is for.
- The page works on one area: the Comune (`EGMS_UI_LON`, `EGMS_UI_LAT`) and
  a radius around it (`EGMS_UI_RADIUS_KM`, 1 to 20, 10 by default). At
  startup the API downloads all the tiles of the area, both components; the
  map is locked on it (it cannot be dragged out, nor zoomed out beyond it),
  veils what is outside and draws its edge; the ground map is one picture of
  the whole area, asked once. Outside the area the API answers 404,
  "outside the area of this page", so no click starts a download elsewhere.
  `/api/health` gives the area.
- An archive that does not list its releases within 15 seconds no longer
  stops the page: the API uses the latest known release with the tiles on
  disk, logs it, and asks again after 10 minutes.
- The first click in an area no longer looks broken. Its EGMS tile (about
  60 MB) takes about a minute to come from the archive: after 2 seconds the
  panel says so, and a badge on the map says the ground map is loading,
  downloading, or not available. At startup, in archive mode, the API
  downloads in the background the tiles around `EGMS_UI_LAT`/`EGMS_UI_LON`
  (Rione Terra when unset), so the first visitor does not wait. The API now
  logs its mode and the prefetch.
- A back office (`demo/admin.py`, container `egms-client-admin`, on
  127.0.0.1:3004 only), off until `.env` names the administrator:
  `EGMS_ADMIN_USER` and `EGMS_ADMIN_PASSWORD_HASH` (scrypt, made by
  `make admin-password`). Upload a JSON, JSON Lines or CSV file, checked and
  shown before it is saved; register sensors, each with its own token
  (shown once, kept as a SHA-256 hash), turn them off, renew or remove
  them; list every file the page reads with the reasons of a refusal; a log
  of logins and changes, never a password or a token. Sessions in memory
  for 8 hours, cookie `HttpOnly` and `SameSite=Strict` (`Secure` behind
  HTTPS), a token on every form, 15 minutes of wait after 5 wrong
  passwords.
- Sensors (`demo/sensors.py`): `POST /api/ingest/{id}` on the public page,
  with `Authorization: Bearer TOKEN`, takes SenML (RFC 8428, as Limen's v2
  sensors) or records; at most one request a second and 64 KB. A reading
  with another name or unit, ahead of the clock, not a number or outside
  the range of the sensor is refused with its reason. The readings become
  records, one JSON Lines file per sensor and day, in the volume
  `egms-incoming`; the registry is in `egms-state`.
- A simpler page. The map fills the screen and zooms with the mouse wheel.
  The panel has one row per source: its name, its number in words, and a
  dot for how far to trust it; a row opens on its source, dates, licence
  and notes. On a phone the panel is a sheet that slides up. A «Layers»
  box turns the ground map, the moving cells and each source on and off.
  The technical side moves to its own page, `/dati`: the sources and how
  they are made, the code, the CSV columns and the templates to download
  (`/templates/record.json`, `/templates/record.csv`). The old `?tab=`
  links lead there.
- Records: `label` (one text, or one per language) and, in a fact,
  `headline`, the value to show first. `to_records` gives both.
- Records from CSV: `records.read` and `egms records` take a `.csv` with the
  columns of the template (Italian or English headers, comma or semicolon,
  decimal comma), and the page reads `.csv` files too.
- The page of a Comune shows open data side by side. Next to EGMS, it reads
  records from folders (`EGMS_UI_RECORDS`; in Docker the examples and
  `records/`, set by `EGMS_RECORDS_DIR`, read-only) and shows the sources
  near the point clicked, each with its source, time, reliability, licence
  and «how it is made». Tabs «Sources» (with the files refused and why) and
  «Add a source»; `?tab=fonti|aggiungi` opens on them. New API routes
  `/api/sources` and `/api/records`; `/api/place` also gives the records.
  The examples now sit at Pozzuoli: the dpc-radar reliability recomputed
  there (0.81) and the simulated rain gauge.

### Changed

- The default data folder follows `DATA_ROOT`, the root shared with Limen and the other libraries: `$DATA_ROOT/egms-client`. `EGMS_DATA_DIR` still wins when set, for compatibility, but leaves `.env.example`; without either, the user cache as before. `compose.yaml` keeps the tiles in `${DATA_ROOT:-./data}/egms-client` on the host instead of the volume `egms-data` (copy them over, or let them download again).
- The page still opens on Pozzuoli when no Comune is set (Gioia del Colle was tried, and left: EGMS measures much more of Pozzuoli).
- The API never waits for the archive's list of releases: it uses the latest known one at once and asks the archive in the background.

### Fixed

- A zone of the ranking points at its measured cell nearest the middle: its card shows a value, not the "not measured" of a gap between cells. Choosing it flies the map there, low enough for the card.
- The card of a point has a fixed width, its data gap first, no empty chart for a point not measured, and the page's font.
- The ground map draws the tiles on the disk and stripes those still downloading, instead of failing; the page asks again every 2 minutes until it is whole.
- A point whose cell is not measured says how many cells are measured within 500 m, and the median within 5 km.
- A tile not on the disk yet no longer holds an answer for minutes: the API waits 20 s, then answers 503 with the missing tiles, and the download goes on in the background. The page says so (it is not «not measured»).

## [0.8.0] - 2026-11-24

How far to trust the data, and an AI layer that cannot invent numbers.
The work of #22 (phases 0-6): a benchmark of known places (21 of 23),
reliability, release windows, cells for a model, facts and checks,
Docker and a page for a Comune.

### Added

- `EgmsArchive.fetch_tile(..., keep=("tiff", "csv"))`: other files of the
  tile's ZIP beside the GeoTIFF. A search id that expired before the download
  (HTTP 401) is searched again, once, as `fetch` already did.
- `EgmsError.status_code`: the HTTP status of a refused download or token. A
  caller with its own retry (`EgmsArchive(retries=0)`) reads it to tell a
  busy archive from a refusal.
- Records of open data (`egms_client.records`, extra `records`): one JSON
  Schema, `opendata-record/v1`, for observations, facts and map layers from
  any source, with checks a schema cannot make (not measured is null, a
  signed value says what its sign means, no alerts). `egms records FILE...`
  checks files. Real examples in `examples/records`. The design is in
  `docs/design/open-data-schema.md`.
- `facts.to_records`: the answers of `velocity`, `area` and `moving_points`
  as records. `scripts/example_records.py` writes the egms examples from the
  benchmark crops; a test checks they do not drift.
- Docker: `compose.yaml` (`name: egms-client`) with `egms-client-api`,
  `egms-client-ui` (127.0.0.1:3003), `egms-client-notebook` (8889, profile
  `notebook`) and `egms-client-mcp` (8768, profile `mcp`). The key is mounted
  read-only from `./secrets` and never copied into an image
  (`.dockerignore`). A complete `.env.example` comes with it. New targets
  `make up`, `demo`, `down` and `logs`.
- A page for a Comune (`demo/web`): Next.js, Bootstrap Italia and Leaflet
  from npm, no CDN. It is in Italian and English, set from `.env` or the
  address, and embeddable (`EGMS_UI_FRAME_ANCESTORS`, `embed=1`). Behind it
  is `demo/api.py`, which serves place, area, moving cells and a map PNG,
  built with `facts` and `words`. Without a key it runs in demo mode on the
  benchmark crops.
- `words` says more of an empty cell with measured neighbours: the share of
  measured cells within 500 m and the median within 5 km. "Not measured"
  alone, on a green spot at Pianura where 47 % of the cells around have a
  value, told too little.
- `egms mcp --http PORT --host ADDR`: the MCP server over streamable HTTP.
- Notebooks `04_how_much_to_trust` and `05_cells_for_a_model`, on the
  crops: no key; `make notebooks-offline` and in CI.
- CI jobs `notebooks` and `docker`: the images build, and the page answers in
  demo mode, with no key in the image and no root.
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
