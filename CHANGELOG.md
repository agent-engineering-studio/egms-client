# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
