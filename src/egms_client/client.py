"""An async client over :mod:`egms_client.auth` and :mod:`egms_client.archive`.

Give it your ``httpx.AsyncClient`` and timeouts, proxies and pooling stay
yours; give it none and it opens (and closes) its own. Searches and downloads
are retried on network errors and on 429/502/503/504; other HTTP errors
propagate, and refusals the archive disguises as a 200 raise
:class:`~egms_client.errors.EgmsError`.

Downloads are streamed to a ``.part`` file and renamed when complete, so a
file that exists is whole, and memory stays flat however large the ZIP.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

import httpx

from egms_client.archive import (
    _CHUNK,
    ARCHIVE_URL,
    Component,
    Hit,
    Query,
    Search,
    Tile,
    _sub_release,
    check_download,
    download_url,
    extract,
    latest_hit,
    latest_hits,
    parse_names,
    parse_releases,
    parse_search,
    query_body,
    search_body,
    split_bbox,
    tile_prefix,
)
from egms_client.auth import ServiceKey, Token, parse_token, token_request
from egms_client.errors import EgmsError

#: Renew the token this many seconds before it expires: a national download
#: lasts longer than the token's hour.
RENEW_MARGIN_S = 300

#: What to keep of each downloaded ZIP: the ZIP itself, the files inside
#: (``tiff`` for L3 only; ``csv`` and ``xml`` for all levels), or ``parquet``:
#: the CSV as GeoParquet (needs the ``tables`` extra).
Keep = Literal["zip", "tiff", "csv", "xml", "parquet"]

_RETRY_STATUS = frozenset({429, 502, 503, 504})

#: ``(hit, bytes received so far, bytes expected)``, as a download goes.
Progress = Callable[[Hit, int, int], None]

#: The environment variable :func:`default_directory` reads.
ENV_DATA_DIR = "EGMS_DATA_DIR"


def default_directory() -> Path:
    """Where downloads go when no directory is given.

    ``EGMS_DATA_DIR`` if set, else ``egms-client`` in the user cache
    (``$XDG_CACHE_HOME``, or ``~/.cache``).
    """
    if configured := os.environ.get(ENV_DATA_DIR, "").strip():
        return Path(configured).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME", "").strip() or "~/.cache"
    return Path(cache).expanduser() / "egms-client"


class _ExpiredError(EgmsError):
    """A download refused with 401: the search id expired."""


class EgmsArchive:
    """Releases, searches and downloads, with a token renewed as needed.

    ``key`` defaults to :meth:`ServiceKey.from_env`. Use it as an async
    context manager, or call :meth:`aclose`, when it opened its own client.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        key: ServiceKey | None = None,
        *,
        archive_url: str = ARCHIVE_URL,
        clock: Callable[[], float] = time.time,
        retries: int = 3,
        backoff_s: float = 2.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._own = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, read=300), follow_redirects=True
        )
        self._key = key if key is not None else ServiceKey.from_env()
        self._archive = archive_url.rstrip("/")
        self._clock = clock
        self._retries = retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._token: Token | None = None
        self._bodies: dict[str, dict[str, Any]] = {}
        self._renewed: dict[str, str] = {}
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> EgmsArchive:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client if this archive opened it."""
        if self._own:
            await self._client.aclose()

    async def token(self) -> Token:
        """A valid bearer token, asking for a new one when the current is about to expire.

        Concurrent callers share one request. A busy endpoint (429/502/503/504,
        or a network error) is retried; its 500 is a bad assertion, not retried.
        """
        async with self._token_lock:
            now = self._clock()
            if self._token is None or now > self._token.expires_at - RENEW_MARGIN_S:
                self._token = await self._new_token(now)
            return self._token

    async def _new_token(self, now: float) -> Token:
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.post(
                    self._key.token_uri,
                    data=token_request(self._key, now=int(now)),
                    headers={"Accept": "application/json"},
                )
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
            else:
                if response.status_code not in _RETRY_STATUS or attempt == self._retries:
                    return parse_token(response.status_code, response.content, now=now)
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    async def releases(self) -> list[str]:
        """The published releases, oldest first (``["2020-2024", "2020-2025"]``)."""
        return parse_releases(await self._get("releases"))

    async def levels(self) -> list[str]:
        """The product levels (``["L2A", "L2B", "L3"]``)."""
        return parse_names(await self._get("levels"), "level list")

    async def bursts(self) -> list[str]:
        """The burst cycles, as ``Query.burst_cycle`` takes them (``"0171"``)."""
        return parse_names(await self._get("bursts"), "burst list")

    async def search(self, tile: Tile, component: Component, release: str) -> Search | None:
        """Search one Ortho L3 tile; ``None`` if the tile does not exist."""
        return await self._search(search_body(tile, component, release))

    async def find(self, query: Query) -> list[Search]:
        """Every file a query matches, the latest sub-release of each.

        A ``bbox`` larger than the archive accepts is searched in pieces; a
        file found by two pieces is listed once. Nothing is downloaded: sum
        ``hit.filesize`` to know what :meth:`fetch` would cost.
        """
        pieces = split_bbox(query.bbox) if query.bbox is not None else [None]
        seen: set[str] = set()
        searches = []
        for piece in pieces:
            part = query if piece is None else dataclasses.replace(query, bbox=piece)
            search = await self._search(query_body(part))
            if search is None:
                continue
            hits = [h for h in latest_hits(search.hits) if h.family not in seen]
            seen.update(h.family for h in hits)
            if hits:
                searches.append(Search(id=search.id, hits=hits))
        return searches

    async def fetch(
        self,
        query: Query,
        directory: Path | None = None,
        *,
        keep: Iterable[Keep] = ("zip",),
        concurrency: int = 4,
        max_bytes: int | None = None,
        on_file: Callable[[Hit, list[Path]], None] | None = None,
        on_progress: Progress | None = None,
        on_plan: Callable[[list[Hit]], None] | None = None,
    ) -> list[Path]:
        """Download what a query matches into ``directory``; the paths kept.

        ``directory`` defaults to :func:`default_directory`.

        Files already in ``directory`` are not downloaded again, so an
        interrupted run resumes where it stopped. ``keep`` picks what stays of
        each ZIP. With ``max_bytes`` set, a download larger than that raises
        :class:`EgmsError` before any byte is fetched.

        ``on_plan(hits)`` is called once with the files about to be downloaded;
        ``on_file(hit, paths)`` when each is done;
        ``on_progress(hit, received, total)`` as its bytes arrive (``received``
        starts again from 0 if a download is retried).
        """
        directory = directory or default_directory()
        kept = tuple(dict.fromkeys(keep))
        if not kept:
            raise ValueError("keep at least one of zip, tiff, csv, xml")
        done: list[Path] = []
        todo: list[tuple[str, Hit]] = []
        for search in await self.find(query):
            for hit in search.hits:
                _check_name(hit)
                outputs = _outputs(hit, kept, directory)
                if all(p.exists() for p in outputs):
                    done.extend(outputs)
                else:
                    todo.append((search.id, hit))
        size = sum(hit.filesize for _, hit in todo)
        if max_bytes is not None and size > max_bytes:
            raise EgmsError(
                f"{len(todo)} files, {size / 1e9:.1f} GB to download: more than "
                f"max_bytes ({max_bytes / 1e9:.1f} GB). Narrow the query or raise the limit."
            )
        directory.mkdir(parents=True, exist_ok=True)
        if on_plan is not None:
            on_plan([hit for _, hit in todo])
        gate = asyncio.Semaphore(concurrency)

        async def one(search_id: str, hit: Hit) -> list[Path]:
            async with gate:
                paths = await self._fetch_hit(search_id, hit, kept, directory, on_progress)
            if on_file is not None:
                on_file(hit, paths)
            return paths

        for paths in await asyncio.gather(*(one(s, h) for s, h in todo)):
            done.extend(paths)
        return done

    async def fetch_tile(
        self, tile: Tile, component: Component, release: str, directory: Path | None = None
    ) -> Path | None:
        """The tile's mean-velocity GeoTIFF in ``directory``, downloaded if missing.

        ``directory`` defaults to :func:`default_directory`.

        ``None`` when the tile does not exist. Both outcomes are remembered in
        ``directory`` (the GeoTIFF, or an ``…absent`` marker), so running it
        again for a whole country asks the archive nothing.
        """
        directory = directory or default_directory()
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
        if not hit.stem.startswith(prefix):
            # A name the glob above cannot find again would mean a ~60 MB
            # download on every run.
            raise EgmsError(f"unexpected file name for {prefix}: {hit.filename!r}")
        _check_name(hit)
        archive = await self._download(search.id, hit, directory)
        if archive is None:
            marker.touch()
            return None
        try:
            (path,) = extract(archive, ["tiff"], directory)
        finally:
            archive.unlink()
        return path

    async def _fetch_hit(
        self,
        search_id: str,
        hit: Hit,
        keep: tuple[Keep, ...],
        directory: Path,
        progress: Progress | None = None,
    ) -> list[Path]:
        search_id = self._renewed.get(search_id, search_id)
        try:
            archive = await self._download(search_id, hit, directory, progress)
        except _ExpiredError:
            # Ids expire while a long queue waits: search again, once, and
            # let the rest of the queue use the new id.
            search = await self._search(self._bodies[search_id])
            if search is None or hit.family not in {h.family for h in search.hits}:
                raise EgmsError(f"{hit.filename} is no longer in the archive") from None
            self._renewed[search_id] = search.id
            archive = await self._download(search.id, hit, directory, progress)
        if archive is None:
            return []
        members = [k for k in keep if k not in ("zip", "parquet")]
        if "parquet" in keep and "csv" not in members:
            members.append("csv")
        try:
            paths = extract(archive, members, directory)
        finally:
            if "zip" not in keep:
                archive.unlink()
        if "parquet" in keep:
            from egms_client.tables import csv_to_geoparquet

            csv = directory / f"{hit.stem}.csv"
            try:
                paths.append(await asyncio.to_thread(csv_to_geoparquet, csv))
            finally:
                if "csv" not in keep:
                    csv.unlink()
                    paths.remove(csv)
        return [archive, *paths] if "zip" in keep else paths

    async def _download(
        self, search_id: str, hit: Hit, directory: Path, progress: Progress | None = None
    ) -> Path | None:
        """The ZIP streamed into ``directory``; ``None`` on 404."""
        path = directory / hit.filename
        partial = directory / f"{hit.filename}.part"
        url = download_url(self._archive, hit)
        for attempt in range(self._retries + 1):
            try:
                async with self._client.stream("GET", url, params={"id": search_id}) as response:
                    status = response.status_code
                    if status == 404:
                        return None
                    if status == 401:
                        text = (await response.aread())[:200].decode("utf-8", "replace")
                        raise _ExpiredError(f"EGMS download refused (HTTP 401): {text}")
                    if status == 200:
                        received = 0
                        with partial.open("wb") as out:
                            async for chunk in response.aiter_bytes(_CHUNK):
                                out.write(chunk)
                                received += len(chunk)
                                if progress is not None:
                                    progress(hit, received, hit.filesize)
                        partial.rename(path)
                        return path
                    if status not in _RETRY_STATUS or attempt == self._retries:
                        check_download(status, await response.aread())
            except httpx.TransportError:
                partial.unlink(missing_ok=True)
                if attempt == self._retries:
                    raise
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _search(self, body: dict[str, Any]) -> Search | None:
        token = await self.token()
        response = await self._send(
            "POST", f"{self._archive}/search", headers=token.headers(), json=body
        )
        search = parse_search(response.content)
        if search is not None:
            self._bodies[search.id] = body
        return search

    async def _get(self, path: str) -> bytes:
        token = await self.token()
        response = await self._send("GET", f"{self._archive}/{path}", headers=token.headers())
        return response.content

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
            else:
                if response.status_code not in _RETRY_STATUS or attempt == self._retries:
                    response.raise_for_status()
                    return response
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover


def _outputs(hit: Hit, keep: tuple[Keep, ...], directory: Path) -> list[Path]:
    return [directory / (hit.filename if k == "zip" else f"{hit.stem}.{k}") for k in keep]


def _check_name(hit: Hit) -> None:
    # The name becomes a path: one with a separator would write elsewhere.
    if "/" in hit.filename or "\\" in hit.filename or hit.filename.startswith("."):
        raise EgmsError(f"unexpected file name: {hit.filename!r}")
