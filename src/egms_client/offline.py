"""The Ortho L3 tiles of an area, downloaded once to work offline: :func:`init`.

::

    from egms_client import init

    result = await init(bbox=(15.3, 40.0, 16.9, 41.3), release="2020-2025")
    print(len(result.downloaded), "tiles,", result.bytes / 1e9, "GB")

Each tile goes through :meth:`~egms_client.client.EgmsArchive.fetch_tile`, so
what ``init`` leaves on the disk is exactly the cache that ``fetch_tile``,
``velocity_at``, the MCP server and the page read afterwards: the GeoTIFF of
each tile and component, and an ``…absent`` marker for a tile at sea. Run it
again and a tile already there costs nothing, not even a search.

A tile that fails (the archive refuses, the network gives up) is reported in
the result, not raised: the others go on, and the next run fetches only what
is missing. An error writing to the disk does raise, and stops the rest.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from egms_client.archive import (
    ARCHIVE_URL,
    COMPONENTS,
    Component,
    Hit,
    LonLatBounds,
    Tile,
    tiles_for_bounds,
)
from egms_client.auth import ServiceKey
from egms_client.client import MAX_DOWNLOADS, EgmsArchive, TileKeep, default_directory
from egms_client.errors import EgmsError

#: What happened to one tile: fetched now, already on the disk, not in the
#: archive (sea, outside coverage), or failed.
Status = Literal["downloaded", "skipped", "absent", "failed"]


@dataclass(frozen=True, slots=True)
class TileOutcome:
    """One tile and component of an :func:`init`.

    ``path`` is the GeoTIFF (``None`` when absent or failed), ``bytes`` what
    was downloaded for it now, ``error`` why it failed.
    """

    tile: Tile
    component: Component
    status: Status
    path: Path | None = None
    bytes: int = 0
    error: str = ""


@dataclass(frozen=True, slots=True)
class InitResult:
    """What :func:`init` did, tile by tile."""

    directory: Path
    release: str
    tiles: tuple[TileOutcome, ...]

    def _with(self, status: Status) -> list[TileOutcome]:
        return [t for t in self.tiles if t.status == status]

    @property
    def downloaded(self) -> list[TileOutcome]:
        """The tiles fetched by this run."""
        return self._with("downloaded")

    @property
    def skipped(self) -> list[TileOutcome]:
        """The tiles already on the disk."""
        return self._with("skipped")

    @property
    def absent(self) -> list[TileOutcome]:
        """The tiles the archive does not have (sea, outside coverage)."""
        return self._with("absent")

    @property
    def failed(self) -> list[TileOutcome]:
        """The tiles that failed: run again to fetch them."""
        return self._with("failed")

    @property
    def bytes(self) -> int:
        """The bytes downloaded by this run."""
        return sum(t.bytes for t in self.tiles)

    @property
    def complete(self) -> bool:
        """True when nothing failed: the area works offline."""
        return not self.failed


async def init(
    directory: Path | None = None,
    *,
    bbox: LonLatBounds | None = None,
    tiles: Iterable[Tile] | None = None,
    release: str | None = None,
    components: Iterable[Component] = COMPONENTS,
    keep: Iterable[TileKeep] | Mapping[Component, Iterable[TileKeep]] = ("tiff",),
    client: httpx.AsyncClient | None = None,
    key: ServiceKey | None = None,
    retries: int = 3,
    concurrency: int = MAX_DOWNLOADS,
    archive_url: str = ARCHIVE_URL,
    on_tile: Callable[[TileOutcome], None] | None = None,
) -> InitResult:
    """Download the Ortho L3 tiles of an area into ``directory``, to work offline.

    The area is ``bbox`` (west, south, east, north in degrees; needs the
    ``raster`` extra) or ``tiles``, not both. ``directory`` defaults to
    :func:`~egms_client.client.default_directory`, ``release`` to the latest
    (one request; give it to run with no network at all once the tiles are
    there), ``components`` to both.

    ``keep`` adds other files of each ZIP beside the GeoTIFF (``"csv"``, about
    250 MB a tile; ``"attributes"``, the CSV without its time series, a few
    MB; ``"xml"``), for every component or per component:
    ``{"U": ("tiff", "attributes"), "E": ("tiff",)}``.

    ``client`` and ``key`` are passed to :class:`~egms_client.client.EgmsArchive`;
    ``retries=0`` leaves every retry to the caller. At most
    :data:`~egms_client.client.MAX_DOWNLOADS` files stream at once, whatever
    ``concurrency`` says: the archive allows two per account.
    ``on_tile(outcome)`` is called as each tile is done.
    """
    if (bbox is None) == (tiles is None):
        raise ValueError("init needs an area: bbox or tiles, not both")
    if concurrency < 1:
        raise ValueError(f"concurrency must be at least 1, not {concurrency}")
    if bbox is not None:
        from egms_client.mosaic import lonlat_to_laea

        minx, miny, maxx, maxy = lonlat_to_laea(*bbox)
        area = tiles_for_bounds(minx, miny, maxx, maxy)
    else:
        area = list(dict.fromkeys(tiles or ()))
    wanted = tuple(dict.fromkeys(components))
    if isinstance(keep, Mapping):
        kept = {c: tuple(keep.get(c, ("tiff",))) for c in wanted}
    else:
        kept = dict.fromkeys(wanted, tuple(keep))
    folder = directory or default_directory()
    gate = asyncio.Semaphore(concurrency)

    async with EgmsArchive(
        client,
        key,
        archive_url=archive_url,
        retries=retries,
        max_downloads=min(concurrency, MAX_DOWNLOADS),
    ) as archive:
        chosen = release or (await archive.releases())[-1]

        async def one(tile: Tile, component: Component) -> TileOutcome:
            received = 0

            def progress(_: Hit, got: int, _total: int) -> None:
                nonlocal received
                received = got

            async with gate:
                try:
                    path = await archive.fetch_tile(
                        tile, component, chosen, folder, keep=kept[component], on_progress=progress
                    )
                except (EgmsError, httpx.HTTPError) as exc:
                    outcome = TileOutcome(
                        tile, component, "failed", bytes=received, error=str(exc)[:300]
                    )
                else:
                    status: Status = (
                        "absent" if path is None else "downloaded" if received else "skipped"
                    )
                    outcome = TileOutcome(tile, component, status, path, received)
            if on_tile is not None:
                on_tile(outcome)
            return outcome

        try:
            # A TaskGroup, so that a disk error stops the downloads still running.
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(one(t, c)) for c in wanted for t in area]
        except ExceptionGroup as errors:
            raise errors.exceptions[0] from None
    return InitResult(folder, chosen, tuple(task.result() for task in tasks))
