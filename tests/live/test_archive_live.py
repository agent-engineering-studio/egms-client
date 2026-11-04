"""The archive as it answers today: the behaviour this library relies on.

Run only with ``EGMS_LIVE=1`` and a key in ``EGMS_SERVICE_KEY`` or
``EGMS_SERVICE_KEY_FILE`` (the weekly ``live`` workflow). A failure here
means the archive changed, not that the code did: the docstring of
:mod:`egms_client.archive` lists what was verified, and when.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

from egms_client import ARCHIVE_URL, EgmsArchive, Query, ServiceKey

pytestmark = pytest.mark.skipif(
    os.environ.get("EGMS_LIVE") != "1", reason="live archive checks: set EGMS_LIVE=1 and a key"
)

#: The smallest L2B burst seen on 2026-11-03 (~8 MB).
SMALL_BURST = Query(
    levels=("L2B",), release="2020-2025", relative_orbit=124, burst_cycle=835, swath="IW3"
)


def run(body: Callable[[EgmsArchive], Coroutine[Any, Any, Any]]) -> Any:
    async def main() -> Any:
        async with EgmsArchive(key=ServiceKey.from_env()) as archive:
            return await body(archive)

    return asyncio.run(main())


async def _raw(archive: EgmsArchive, body: dict[str, Any]) -> dict[str, Any]:
    """A search sent as is, past the library's own checks."""
    token = await archive.token()
    response = await archive._client.post(
        f"{ARCHIVE_URL}/search", headers=token.headers(), json=body
    )
    data: dict[str, Any] = response.json()
    return data


def test_the_lists_the_archive_publishes() -> None:
    async def body(a: EgmsArchive) -> tuple[list[str], list[str], list[str]]:
        return await a.releases(), await a.levels(), await a.bursts()

    releases, levels, bursts = run(body)
    assert "2020-2025" in releases
    assert levels == ["L2A", "L2B", "L3"]
    assert len(bursts) > 100 and all(len(b) == 4 for b in bursts)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"tileId": "E47N19", "releases": ["2020-2025"], "levels": ["L2a"]}, "Invalid level"),
        (
            {"relativeOrbit": "22", "releases": ["2020-2025"], "levels": ["L2B"]},
            "Invalid relative orbit",
        ),
        (
            {"bbox": [[-30, 30], [50, 72]], "releases": ["2020-2025"], "levels": ["L3"]},
            "too large",
        ),
        ({"tileId": "E40N15", "releases": ["2020-2025"], "levels": ["L3"]}, "Invalid tile ID"),
        ({"releases": ["2020-2025"], "levels": ["L3"]}, "You must provide"),
    ],
)
def test_the_traps_still_answer_the_same(body: dict[str, Any], message: str) -> None:
    answer = run(lambda a: _raw(a, body))
    assert answer["status"] is False
    assert message in answer["message"]


def test_an_l3_tile_has_both_components() -> None:
    query = Query(levels=("L3",), release="2020-2025", tile=(47, 19))
    searches = run(lambda a: a.find(query))
    types = sorted(h.product_type for s in searches for h in s.hits)
    assert types == ["ORTHO-EAST", "ORTHO-UP"]


def test_a_five_degree_box_still_passes() -> None:
    query = Query(levels=("L3",), release="2020-2025", bbox=(10.0, 42.0, 15.0, 47.0))
    searches = run(lambda a: a.find(query))
    assert len(searches) == 1 and len(searches[0].hits) > 20


def test_a_small_burst_downloads_with_the_expected_columns(tmp_path: Path) -> None:
    paths = run(lambda a: a.fetch(SMALL_BURST, tmp_path, keep=["csv", "xml"], max_bytes=50_000_000))
    csv = next(p for p in paths if p.suffix == ".csv")
    header = csv.open().readline().strip().split(",")
    for column in ("pid", "latitude", "longitude", "easting", "northing", "mean_velocity"):
        assert column in header
    assert any(c.isdigit() and len(c) == 8 for c in header)
    again = run(lambda a: a.fetch(SMALL_BURST, tmp_path, keep=["csv", "xml"]))
    assert sorted(again) == sorted(paths)


def test_pozzuoli_rises_and_the_sea_has_no_velocity(tmp_path: Path) -> None:
    """The point query on real data, through the sync façade (one L3 tile, ~60 MB)."""
    from egms_client.sync import Archive

    with Archive(key=ServiceKey.from_env()) as archive:
        pozzuoli = archive.velocity_at(14.12, 40.83, "U", "2020-2025", tmp_path)
        sea = archive.velocity_at(13.5, 40.5, "U", "2020-2025", tmp_path)
    assert pozzuoli.velocity is not None and pozzuoli.velocity > 50  # mm/year, up
    assert pozzuoli.file is not None and pozzuoli.file.name.startswith("EGMS_L3_")
    assert sea.velocity is None


def test_the_mcp_server_summarises_campi_flegrei(tmp_path: Path) -> None:
    """area_summary on real data, through an MCP client (one or two L3 tiles)."""
    pytest.importorskip("mcp")
    from mcp import Client

    from egms_client.mcp_server import create_server

    async def main() -> Any:
        box = {"west": 14.05, "south": 40.80, "east": 14.20, "north": 40.88}
        async with Client(create_server(directory=tmp_path)) as client:
            return await client.call_tool("area_summary", {**box, "release": "2020-2025"})

    result = asyncio.run(main())
    assert not result.is_error, result.content
    area = result.structured_content
    assert area is not None
    assert area["max"] > 50 and area["share_above"] > 0.1  # the caldera rises
    assert area["files"] and all(f.startswith("EGMS_L3_") for f in area["files"])


def test_fit_gives_back_the_columns_of_a_whole_burst(tmp_path: Path) -> None:
    """analysis.fit on every point of a real L2B burst (~8 MB): the archive's own model."""
    import numpy as np

    from egms_client.analysis import fit, trend_change, unwrapping_jumps
    from egms_client.tables import attributes, read_csv

    paths = run(lambda a: a.fetch(SMALL_BURST, tmp_path, keep=["csv"], max_bytes=50_000_000))
    table = read_csv(next(p for p in paths if p.suffix == ".csv"))
    ours, theirs = fit(table), attributes(table)
    complete = ours["velocity"].notna()
    assert complete.mean() > 0.95
    velocity = np.abs(ours["velocity"] - theirs["mean_velocity"])[complete]
    acceleration = np.abs(ours["acceleration"] - theirs["acceleration"])[complete]
    assert velocity.quantile(0.99) < 0.06  # the archive rounds to 0.1 mm/year
    assert acceleration.quantile(0.99) < 0.02
    assert len(trend_change(table)) == len(unwrapping_jumps(table)) == len(table)
