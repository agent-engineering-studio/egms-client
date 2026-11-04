"""EGMS as tools for AI agents: an MCP server. Needs the ``mcp`` extra.

``egms mcp`` serves these tools over stdio to any MCP client (Claude
Desktop, Claude Code, IDE assistants):

* ``releases``: the published releases;
* ``find_files``: what the archive holds over a box, and its size, with
  nothing downloaded;
* ``velocity_at``: the L3 velocity of the 100 m cell at a point;
* ``area_summary``: statistics of the L3 velocity over a box, and its
  fastest cells.

Every answer names the release and the files it was computed from. The
numbers come from the data, never from the model: the tools return them,
and the client only words them. Downloads are bounded: ``area_summary``
refuses a box touching more than ``max_tiles`` L3 tiles (about 60 MB each,
kept in ``directory`` for the next call). The service key is read from the
server's environment (``EGMS_SERVICE_KEY_FILE`` or ``EGMS_SERVICE_KEY``) and
never passes through the conversation.
"""

from __future__ import annotations

import math
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
- Quote numbers only as the tools return them, with their release and file.
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


class Velocity(TypedDict):
    lon: float
    lat: float
    component: str
    meaning: str
    velocity_mm_per_year: float | None
    release: str
    tile: str
    file: str | None


class Cell(TypedDict):
    lon: float
    lat: float
    velocity_mm_per_year: float


class AreaSummary(TypedDict):
    component: str
    meaning: str
    release: str
    box: list[float]
    cells_with_data: int
    coverage: float
    mean: float | None
    median: float | None
    p5: float | None
    p95: float | None
    min: float | None
    max: float | None
    stable_band_mm_per_year: float
    share_below: float | None
    share_above: float | None
    fastest: list[Cell]
    files: list[str]
    tiles_without_data: list[str]


MEANING: dict[Component, str] = {
    "U": "vertical: positive up, negative down (subsidence)",
    "E": "east-west: positive east, negative west",
}


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
    ) -> Velocity:
        """The EGMS Ortho L3 velocity (mm/year) of the 100 m cell at a point in degrees.

        component "U" is vertical, "E" east-west. velocity_mm_per_year is null
        where EGMS has no measurement (sea, outside coverage, a cell without
        data). Downloads the point's tile once (~60 MB). release defaults to
        the latest.
        """
        point = await _guard(connect().velocity_at(lon, lat, component, release, folder))
        return Velocity(
            lon=lon,
            lat=lat,
            component=component,
            meaning=MEANING[component],
            velocity_mm_per_year=_round(point.velocity),
            release=point.release,
            tile=tile_id(point.tile),
            file=point.file.name if point.file else None,
        )

    @server.tool()
    async def area_summary(
        west: float,
        south: float,
        east: float,
        north: float,
        component: Literal["U", "E"] = "U",
        release: str | None = None,
        stable_band: float = 2.0,
    ) -> AreaSummary:
        """Statistics of the EGMS Ortho L3 velocity (mm/year) over a box in degrees.

        Returns coverage, mean, median, percentiles, the share of cells below
        -stable_band and above +stable_band mm/year (for "U": sinking and
        rising), and the 5 fastest cells. Downloads the L3 tiles the box
        touches, once; a box touching more than the server's tile limit is
        refused (narrow it). release defaults to the latest.
        """
        if not (west < east and south < north):
            raise ToolError(
                "the box is west, south, east, north, with west < east and south < north"
            )
        from egms_client.mosaic import lonlat_to_laea

        chosen = await _guard(latest(release))
        minx, miny, maxx, maxy = lonlat_to_laea(west, south, east, north)
        tiles = tiles_for_bounds(minx, miny, maxx, maxy)
        if len(tiles) > max_tiles:
            raise ToolError(
                f"the box touches {len(tiles)} L3 tiles (about {len(tiles) * 60} MB); "
                f"this server downloads at most {max_tiles}. Narrow the box."
            )
        tiffs: list[Path] = []
        absent: list[str] = []
        for tile in tiles:
            tiff = await _guard(connect().fetch_tile(tile, component, chosen, folder))
            if tiff is None:
                absent.append(tile_id(tile))
            else:
                tiffs.append(tiff)
        summary = summarize(
            tiffs,
            box=(west, south, east, north),
            stable_band=stable_band,
        )
        return AreaSummary(
            component=component,
            meaning=MEANING[component],
            release=chosen,
            box=[west, south, east, north],
            stable_band_mm_per_year=stable_band,
            files=[t.name for t in tiffs],
            tiles_without_data=absent,
            **summary,
        )

    return server


class _Stats(TypedDict):
    cells_with_data: int
    coverage: float
    mean: float | None
    median: float | None
    p5: float | None
    p95: float | None
    min: float | None
    max: float | None
    share_below: float | None
    share_above: float | None
    fastest: list[Cell]


def summarize(
    tiffs: list[Path],
    *,
    box: tuple[float, float, float, float],
    stable_band: float = 2.0,
    fastest: int = 5,
) -> _Stats:
    """The statistics ``area_summary`` returns, over the cells inside a box in degrees.

    Only cells whose centre falls inside the box count (the box is curved
    in EPSG:3035, so its bounding rectangle holds more). Pure: no network.
    """
    import numpy as np
    from pyproj import Transformer

    from egms_client.mosaic import lonlat_to_laea, mosaic

    west, south, east, north = box
    minx, miny, maxx, maxy = lonlat_to_laea(west, south, east, north)
    m = mosaic(tiffs, minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    rows, cols = m.values.shape
    x = m.left + (np.arange(cols) + 0.5) * m.pixel
    y = m.top - (np.arange(rows) + 0.5) * m.pixel
    xx, yy = np.meshgrid(x, y)
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    lon, lat = to_lonlat.transform(xx, yy)
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    values = m.values[inside]
    valid = values[~np.isnan(values)]
    n = int(valid.size)
    if n == 0:
        return _Stats(
            cells_with_data=0,
            coverage=0.0,
            mean=None,
            median=None,
            p5=None,
            p95=None,
            min=None,
            max=None,
            share_below=None,
            share_above=None,
            fastest=[],
        )
    data = np.where(inside, m.values, np.nan)
    order = np.argsort(-np.nan_to_num(np.abs(data), nan=-1.0), axis=None)[:fastest]
    top = [
        Cell(
            lon=round(float(lon.flat[i]), 5),
            lat=round(float(lat.flat[i]), 5),
            velocity_mm_per_year=round(float(data.flat[i]), 1),
        )
        for i in order
        if not math.isnan(float(data.flat[i]))
    ]
    return _Stats(
        cells_with_data=n,
        coverage=round(n / max(int(inside.sum()), 1), 3),
        mean=_round(float(valid.mean())),
        median=_round(float(np.median(valid))),
        p5=_round(float(np.percentile(valid, 5))),
        p95=_round(float(np.percentile(valid, 95))),
        min=_round(float(valid.min())),
        max=_round(float(valid.max())),
        share_below=round(float((valid < -stable_band).mean()), 3),
        share_above=round(float((valid > stable_band).mean()), 3),
        fastest=top,
    )


def run(**options: Any) -> None:
    """Serve the tools over stdio, until the client disconnects."""
    create_server(**options).run("stdio")


async def _guard[T](call: Awaitable[T]) -> T:
    """What the archive refuses, as an error the agent can read and act on."""
    try:
        return await call
    except (EgmsError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    except ImportError as exc:
        raise ToolError(f"{exc}: pip install 'egms-client[mcp]'") from exc


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


__all__ = ["MAX_TILES", "create_server", "run", "summarize"]
