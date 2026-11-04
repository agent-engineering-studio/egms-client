"""The archive without ``async``/``await``, for scripts and notebooks.

:class:`Archive` has the methods of :class:`~egms_client.client.EgmsArchive`,
blocking until each one is done::

    from egms_client.sync import Archive

    with Archive() as archive:
        print(archive.velocity_at(14.12, 40.83))

The async client runs on an event loop of its own, in a background thread.
That is why it also works inside Jupyter, where a loop is already running
and ``asyncio.run`` refuses to start another. The ``on_*`` callbacks of
:meth:`Archive.fetch` are called from that thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine, Iterable
from concurrent.futures import Future
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

import httpx

from egms_client.archive import Component, Hit, Query, Search, Tile
from egms_client.auth import ServiceKey
from egms_client.client import MAX_DOWNLOADS, EgmsArchive, Keep, PointVelocity, Progress

T = TypeVar("T")


class Archive:
    """:class:`~egms_client.client.EgmsArchive`, blocking.

    Takes the same arguments. Use it as a context manager, or call
    :meth:`close`: it stops the background thread.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        key: ServiceKey | None = None,
        **options: Any,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="egms-client", daemon=True
        )
        self._thread.start()
        self._closed = False
        try:
            self._archive = self._run(self._open(client, key, options))
        except BaseException:
            self._stop()
            raise

    @staticmethod
    async def _open(
        client: httpx.AsyncClient | None, key: ServiceKey | None, options: dict[str, Any]
    ) -> EgmsArchive:
        return EgmsArchive(client, key, **options)

    def __enter__(self) -> Archive:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client (if the archive opened it) and stop the thread."""
        if self._closed:
            return
        try:
            self._run(self._archive.aclose())
        finally:
            self._stop()

    def _stop(self) -> None:
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()

    def _run(self, coro: Coroutine[Any, Any, T]) -> T:
        if self._closed:
            coro.close()
            raise RuntimeError("the archive is closed")
        future: Future[T] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result()
        except BaseException:
            # Ctrl-C while waiting: stop the work in the background too.
            future.cancel()
            raise

    def releases(self) -> list[str]:
        """See :meth:`EgmsArchive.releases`."""
        return self._run(self._archive.releases())

    def levels(self) -> list[str]:
        """See :meth:`EgmsArchive.levels`."""
        return self._run(self._archive.levels())

    def bursts(self) -> list[str]:
        """See :meth:`EgmsArchive.bursts`."""
        return self._run(self._archive.bursts())

    def search(self, tile: Tile, component: Component, release: str) -> Search | None:
        """See :meth:`EgmsArchive.search`."""
        return self._run(self._archive.search(tile, component, release))

    def find(self, query: Query) -> list[Search]:
        """See :meth:`EgmsArchive.find`."""
        return self._run(self._archive.find(query))

    def fetch(
        self,
        query: Query,
        directory: Path | None = None,
        *,
        keep: Iterable[Keep] = ("zip",),
        concurrency: int = MAX_DOWNLOADS,
        max_bytes: int | None = None,
        on_file: Callable[[Hit, list[Path]], None] | None = None,
        on_progress: Progress | None = None,
        on_plan: Callable[[list[Hit]], None] | None = None,
    ) -> list[Path]:
        """See :meth:`EgmsArchive.fetch`. The callbacks run on the background thread."""
        return self._run(
            self._archive.fetch(
                query,
                directory,
                keep=keep,
                concurrency=concurrency,
                max_bytes=max_bytes,
                on_file=on_file,
                on_progress=on_progress,
                on_plan=on_plan,
            )
        )

    def fetch_tile(
        self, tile: Tile, component: Component, release: str, directory: Path | None = None
    ) -> Path | None:
        """See :meth:`EgmsArchive.fetch_tile`."""
        return self._run(self._archive.fetch_tile(tile, component, release, directory))

    def velocity_at(
        self,
        lon: float,
        lat: float,
        component: Component = "U",
        release: str | None = None,
        directory: Path | None = None,
    ) -> PointVelocity:
        """See :meth:`EgmsArchive.velocity_at`."""
        return self._run(self._archive.velocity_at(lon, lat, component, release, directory))
