"""Client for the EGMS archive (European Ground Motion Service)."""

from importlib.metadata import version

from egms_client.archive import (
    ARCHIVE_URL,
    COMPONENTS,
    PRODUCT_TYPES,
    TILE_SIZE_M,
    Component,
    Hit,
    Search,
    Tile,
    api_release,
    check_download,
    download_url,
    extract_tiff,
    file_release,
    latest_hit,
    parse_releases,
    parse_search,
    search_body,
    tile_id,
    tile_prefix,
    tiles_for_bounds,
)
from egms_client.auth import ServiceKey, Token, assertion, parse_token, token_request
from egms_client.client import EgmsArchive
from egms_client.errors import EgmsError

__version__ = version("egms-client")

__all__ = [
    "ARCHIVE_URL",
    "COMPONENTS",
    "PRODUCT_TYPES",
    "TILE_SIZE_M",
    "Component",
    "EgmsArchive",
    "EgmsError",
    "Hit",
    "Search",
    "ServiceKey",
    "Tile",
    "Token",
    "__version__",
    "api_release",
    "assertion",
    "check_download",
    "download_url",
    "extract_tiff",
    "file_release",
    "latest_hit",
    "parse_releases",
    "parse_search",
    "parse_token",
    "search_body",
    "tile_id",
    "tile_prefix",
    "tiles_for_bounds",
    "token_request",
]
