"""EGMS as tools for AI agents: an MCP server. Needs the ``mcp`` extra.

``egms mcp`` serves these tools over stdio to any MCP client (Claude
Desktop, Claude Code, IDE assistants):

* ``releases``: the published releases;
* ``find_files``: what the archive holds over a box, and its size, with
  nothing downloaded;
* ``velocity_at``: the L3 velocity of the 100 m cell at a point;
* ``area_summary``: statistics of the L3 velocity over a box, and its
  fastest cells;
* ``moving_points``: the cells of a box that move against the median of the
  box, each with how far to trust it;
* ``check_answer``: the numbers of a text that the facts do not hold, the
  ones with the wrong sign, and the ones said of the wrong fact.

The answers are facts (:mod:`egms_client.facts`): every number with its
release, its window, the files it was read from, how far to trust it, the
licence and notes. The numbers come from the data, never from the model:
the tools return them, the client only words them, and ``check_answer``
reads the words back. Downloads are bounded: ``area_summary``
refuses a box touching more than ``max_tiles`` L3 tiles (about 60 MB each,
kept in ``directory`` for the next call). The service key is read from the
server's environment (``EGMS_SERVICE_KEY_FILE`` or ``EGMS_SERVICE_KEY``) and
never passes through the conversation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from egms_client.archive import Component, Query, tile_id, tiles_for_bounds
from egms_client.auth import ServiceKey
from egms_client.client import EgmsArchive, default_directory
from egms_client.errors import EgmsError
from egms_client.facts import summarize

#: L3 tiles ``area_summary`` downloads at most for one box (~60 MB each).
MAX_TILES = 9

#: Files listed by ``find_files``; the totals always count them all.
MAX_LISTED = 50

INSTRUCTIONS = """\
Tools over the Copernicus European Ground Motion Service (EGMS): how fast the
ground moves across Europe, measured by Sentinel-1 radar (InSAR), in mm/year.

- Component "U" is vertical (negative: the ground goes down), "E" east-west
  (negative: west). Ortho L3 is a 100 m grid; L2A/L2B are measurement points
  along the satellite's line of sight.
- Quote numbers only as the tools return them, with their release, window
  and file. The window is when the satellites measured: say that the data
  stops there, and do not describe the ground of today with it.
- Say how far to trust a number (reliability: score, coverage, reasons).
  null is "not measured", never zero. Keep the sign: negative "U" is down.
- Before answering, pass your text and the facts to check_answer, and fix
  what it finds.
  A velocity is evidence, not a safety verdict: do not tell anyone that a
  building, slope or area is safe or dangerous.
- Boxes are west, south, east, north in degrees. Use find_files to check
  sizes before suggesting downloads.
- Data: EGMS, (c) European Union, Copernicus Land Monitoring Service."""

ArchiveFactory = Callable[[], EgmsArchive]


class FileInfo(TypedDict):
    filename: str
    size_mb: float
    level: str
    tile_id: str
    direction: str
    relative_orbit: str


class FilesFound(TypedDict):
    release: str
    levels: list[str]
    count: int
    total_gb: float
    files: list[FileInfo]
    truncated: bool


class Checked(TypedDict):
    ok: bool
    numbers_not_in_facts: list[str]
    wrong_sign: list[str]
    wrong_fact: list[str]


def create_server(
    archive: ArchiveFactory | None = None,
    *,
    directory: Path | None = None,
    max_tiles: int = MAX_TILES,
    key_file: Path | None = None,
) -> MCPServer[Any]:
    """The MCP server, its tools bound to one :class:`EgmsArchive`.

    ``archive`` builds that client on the first call (default: one reading
    ``key_file``, else the environment), so the server starts even without
    a key and says what is missing when a tool is used. ``directory`` is
    where tiles are kept (default :func:`default_directory`).
    """
    from egms_client import __version__

    state: dict[str, EgmsArchive] = {}
    folder = directory or default_directory()

    def default_archive() -> EgmsArchive:
        key = ServiceKey.from_file(key_file) if key_file else ServiceKey.from_env()
        return EgmsArchive(key=key)

    def connect() -> EgmsArchive:
        if "archive" not in state:
            try:
                state["archive"] = (archive or default_archive)()
            except (LookupError, ValueError, OSError) as exc:
                raise ToolError(f"{exc} (in the environment of the MCP server)") from exc
        return state["archive"]

    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if "archive" in state:
                await state.pop("archive").aclose()

    server: MCPServer[Any] = MCPServer(
        name="egms",
        title="EGMS ground motion",
        instructions=INSTRUCTIONS,
        website_url="https://agentengineering.it/egms-client/",
        version=__version__,
        lifespan=lifespan,
    )

    async def latest(release: str | None) -> str:
        return release or (await connect().releases())[-1]

    @server.tool()
    async def releases() -> list[str]:
        """The EGMS releases, oldest first. Each is a window of years, e.g. "2020-2025"."""
        return await _guard(connect().releases())

    @server.tool()
    async def find_files(
        west: float,
        south: float,
        east: float,
        north: float,
        level: Literal["L2A", "L2B", "L3"] = "L3",
        release: str | None = None,
    ) -> FilesFound:
        """The files the EGMS archive holds over a box in degrees, and their size.

        Nothing is downloaded. L3 is the 100 m velocity grid (one file per
        100 km tile and component); L2A and L2B are measurement points, one
        file per Sentinel-1 burst, often several GB per box. release defaults
        to the latest.
        """
        chosen = await _guard(latest(release))
        query = Query(levels=(level,), release=chosen, bbox=(west, south, east, north))
        hits = [h for s in await _guard(connect().find(query)) for h in s.hits]
        return FilesFound(
            release=chosen,
            levels=[level],
            count=len(hits),
            total_gb=round(sum(h.filesize for h in hits) / 1e9, 3),
            files=[
                FileInfo(
                    filename=h.filename,
                    size_mb=round(h.filesize / 1e6, 1),
                    level=h.level or "L3",
                    tile_id=h.tile_id,
                    direction=h.direction,
                    relative_orbit=h.relative_orbit,
                )
                for h in hits[:MAX_LISTED]
            ],
            truncated=len(hits) > MAX_LISTED,
        )

    @server.tool()
    async def velocity_at(
        lon: float,
        lat: float,
        component: Literal["U", "E"] = "U",
        release: str | None = None,
    ) -> dict[str, Any]:
        """The EGMS Ortho L3 velocity (mm/year) of the 100 m cell at a point in degrees.

        component "U" is vertical, "E" east-west. velocity_mm_per_year is null
        where EGMS has no measurement (sea, outside coverage, a cell without
        data): not measured, not zero. With it: how far to trust it
        (reliability), the median of its surroundings within the tile, the
        release window, the file, the licence. Downloads the point's tile once
        (~60 MB). release defaults to the latest.
        """
        from egms_client import facts

        point = await _guard(connect().velocity_at(lon, lat, component, release, folder))
        answer = facts.velocity(
            [point.file] if point.file else [],
            lon,
            lat,
            component=component,
            release=point.release,
        )
        return answer | {"tile": tile_id(point.tile)}

    async def tiles_over(
        box: tuple[float, float, float, float], component: Component, release: str
    ) -> tuple[list[Path], list[str]]:
        west, south, east, north = box
        if not (west < east and south < north):
            raise ToolError(
                "the box is west, south, east, north, with west < east and south < north"
            )
        from egms_client.mosaic import lonlat_to_laea

        tiles = tiles_for_bounds(*lonlat_to_laea(west, south, east, north))
        if len(tiles) > max_tiles:
            raise ToolError(
                f"the box touches {len(tiles)} L3 tiles (about {len(tiles) * 60} MB); "
                f"this server downloads at most {max_tiles}. Narrow the box."
            )
        tiffs: list[Path] = []
        absent: list[str] = []
        for tile in tiles:
            tiff = await _guard(connect().fetch_tile(tile, component, release, folder))
            if tiff is None:
                absent.append(tile_id(tile))
            else:
                tiffs.append(tiff)
        return tiffs, absent

    @server.tool()
    async def area_summary(
        west: float,
        south: float,
        east: float,
        north: float,
        component: Literal["U", "E"] = "U",
        release: str | None = None,
        stable_band: float = 2.0,
    ) -> dict[str, Any]:
        """Statistics of the EGMS Ortho L3 velocity (mm/year) over a box in degrees.

        Returns coverage, mean, median, percentiles, the share of cells below
        -stable_band and above +stable_band mm/year (for "U": sinking and
        rising), and the 5 fastest cells, with the release window, files,
        licence and notes. Downloads the L3 tiles the box touches, once; a
        box touching more than the server's tile limit is refused (narrow
        it). release defaults to the latest.
        """
        from egms_client import facts

        box = (west, south, east, north)
        chosen = await _guard(latest(release))
        tiffs, absent = await tiles_over(box, component, chosen)
        answer = facts.area(
            tiffs, box, component=component, release=chosen, stable_band=stable_band
        )
        return answer | {"tiles_without_data": absent}

    @server.tool()
    async def moving_points(
        west: float,
        south: float,
        east: float,
        north: float,
        component: Literal["U", "E"] = "U",
        release: str | None = None,
        threshold: float = 5.0,
        limit: int = 10,
    ) -> dict[str, Any]:
        """The cells of a box that move against the box's median, fastest first.

        A cell moves when its velocity differs from the median of the box by
        threshold mm/year or more (EGMS velocities carry regional offsets, so
        the median, not zero, is the reference). Each cell says whether its
        neighbourhood is well measured (reliable). Same downloads and limits
        as area_summary. release defaults to the latest.
        """
        from egms_client import facts

        box = (west, south, east, north)
        chosen = await _guard(latest(release))
        tiffs, absent = await tiles_over(box, component, chosen)
        answer = facts.moving_points(
            tiffs,
            box,
            component=component,
            release=chosen,
            threshold=threshold,
            limit=max(1, min(limit, 50)),
        )
        return answer | {"tiles_without_data": absent}

    @server.tool()
    async def check_answer(
        text: str, facts: dict[str, Any], lang: Literal["en", "it"] = "en"
    ) -> Checked:
        """Check a text against the facts a tool returned, before giving it to a person.

        Lists the numbers of the text that the facts do not hold, the ones
        with the wrong sign ("sinks by 4" where the facts give +4), and the
        ones said of the wrong fact. ok is true when all three are empty.
        No download.
        """
        from egms_client.check import check_claims, check_signs, check_text

        strangers = check_text(text, facts, lang=lang)
        signs = [str(m) for m in check_signs(text, facts, lang=lang)]
        claims = [str(m) for m in check_claims(text, facts, lang=lang)]
        return Checked(
            ok=not (strangers or signs or claims),
            numbers_not_in_facts=strangers,
            wrong_sign=signs,
            wrong_fact=claims,
        )

    return server


def run(*, http_port: int | None = None, http_host: str = "127.0.0.1", **options: Any) -> None:
    """Serve the tools over stdio, or over HTTP at ``http://host:port/mcp``.

    HTTP is for a container (``egms mcp --http 8768 --host 0.0.0.0``); the
    key stays in the server's environment either way.
    """
    server = create_server(**options)
    if http_port is None:
        server.run("stdio")
    else:
        server.run("streamable-http", host=http_host, port=http_port)


async def _guard[T](call: Awaitable[T]) -> T:
    """What the archive refuses, as an error the agent can read and act on."""
    try:
        return await call
    except (EgmsError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    except ImportError as exc:
        raise ToolError(f"{exc}: pip install 'egms-client[mcp]'") from exc


__all__ = ["MAX_TILES", "create_server", "run", "summarize"]
