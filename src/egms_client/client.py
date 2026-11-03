"""An async client over :mod:`egms_client.auth` and :mod:`egms_client.archive`.

It takes your ``httpx.AsyncClient``: timeouts, retries, proxies and pooling
stay yours. HTTP errors propagate; refusals the archive disguises as a 200
raise :class:`~egms_client.errors.EgmsError`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from egms_client.archive import (
    ARCHIVE_URL,
    Component,
    Search,
    Tile,
    _sub_release,
    check_download,
    download_url,
    extract_tiff,
    latest_hit,
    parse_releases,
    parse_search,
    search_body,
    tile_prefix,
)
from egms_client.auth import ServiceKey, Token, parse_token, token_request
from egms_client.errors import EgmsError

if TYPE_CHECKING:
    import httpx

#: Renew the token this many seconds before it expires: a national download
#: lasts longer than the token's hour.
RENEW_MARGIN_S = 300


class EgmsArchive:
    """Releases, searches and Ortho L3 tiles, with a token renewed as needed."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        key: ServiceKey,
        *,
        archive_url: str = ARCHIVE_URL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._key = key
        self._archive = archive_url.rstrip("/")
        self._clock = clock
        self._token: Token | None = None

    async def token(self) -> Token:
        """A valid bearer token, asking for a new one when the current is about to expire."""
        now = self._clock()
        if self._token is None or now > self._token.expires_at - RENEW_MARGIN_S:
            response = await self._client.post(
                self._key.token_uri,
                data=token_request(self._key, now=int(now)),
                headers={"Accept": "application/json"},
            )
            self._token = parse_token(response.status_code, response.content, now=now)
        return self._token

    async def releases(self) -> list[str]:
        """The published releases, oldest first (``["2020-2024", "2020-2025"]``)."""
        token = await self.token()
        response = await self._client.get(f"{self._archive}/releases", headers=token.headers())
        response.raise_for_status()
        return parse_releases(response.content)

    async def search(self, tile: Tile, component: Component, release: str) -> Search | None:
        """Search one Ortho L3 tile; ``None`` if the tile does not exist."""
        token = await self.token()
        response = await self._client.post(
            f"{self._archive}/search",
            headers=token.headers(),
            json=search_body(tile, component, release),
        )
        response.raise_for_status()
        return parse_search(response.content)

    async def fetch_tile(
        self, tile: Tile, component: Component, release: str, directory: Path
    ) -> Path | None:
        """The tile's mean-velocity GeoTIFF in ``directory``, downloaded if missing.

        ``None`` when the tile does not exist. Both outcomes are remembered in
        ``directory`` (the GeoTIFF, or an ``…absent`` marker), so running it
        again for a whole country asks the archive nothing.
        """
        prefix = tile_prefix(tile, component, release)
        cached = sorted(directory.glob(f"{prefix}*.tiff"), key=lambda p: _sub_release(p.stem))
        if cached:
            return cached[-1]
        marker = directory / f"{prefix}absent"
        if marker.exists():
            return None
        directory.mkdir(parents=True, exist_ok=True)
        search = await self.search(tile, component, release)
        hit = latest_hit(search) if search is not None else None
        if search is None or hit is None:
            marker.touch()
            return None
        if not hit.stem.startswith(prefix) or "/" in hit.filename:
            # A name the glob above cannot find again would mean a ~60 MB
            # download on every run; one with "/" would write elsewhere.
            raise EgmsError(f"unexpected file name for {prefix}: {hit.filename!r}")
        response = await self._client.get(
            download_url(self._archive, hit), params={"id": search.id}
        )
        if response.status_code == 404:
            marker.touch()
            return None
        tiff = extract_tiff(check_download(response.status_code, response.content), hit)
        path = directory / f"{hit.stem}.tiff"
        partial = path.with_suffix(".part")
        partial.write_bytes(tiff)
        partial.rename(path)
        return path
