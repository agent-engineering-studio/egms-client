"""The MCP server, through a real MCP client connected in-process."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from egms_client import EgmsArchive, ServiceKey

pytest.importorskip("mcp")
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

from mcp import Client  # noqa: E402
from mcp.types import CallToolResult  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from egms_client import cli  # noqa: E402
from egms_client.mcp_server import create_server, summarize  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE = "https://a/archive"
STEM = "EGMS_L3_E47N19_100km_U_2020_2025_1"
TO_LONLAT = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)


def _lonlat(x: float, y: float) -> tuple[float, float]:
    lon, lat = TO_LONLAT.transform(x, y)
    return float(lon), float(lat)


def _box(minx: float, miny: float, maxx: float, maxy: float) -> dict[str, float]:
    """The box in degrees around a rectangle in EPSG:3035."""
    corners = [_lonlat(x, y) for x in (minx, maxx) for y in (miny, maxy)]
    lons, lats = zip(*corners, strict=True)
    return {"west": min(lons), "south": min(lats), "east": max(lons), "north": max(lats)}


#: Rows 3-6, columns 3-6 of the stand-in tile: 16 cells, -17 to +16 mm/year.
INNER = _box(4_700_300, 1_999_300, 4_700_700, 1_999_700)


def _tile(directory: Path) -> Path:
    """A 10 x 10 stand-in for E47N19 at its top-left corner: value = 10 * row + col - 50."""
    values = np.arange(100, dtype="float32").reshape(10, 10) - 50
    path = directory / f"{STEM}.tiff"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:3035",
        transform=from_origin(4_700_000, 2_000_000, 100, 100),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return path


class Fake:
    """Releases; an L2B search for a box; every tile but E47N19 at sea."""

    def __init__(self, *, logged_in: bool = True) -> None:
        self.logged_in = logged_in

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if not self.logged_in:
            return httpx.Response(200, content=(FIXTURES / "not_logged_in.json").read_bytes())
        if path.endswith("/releases"):
            return httpx.Response(200, content=(FIXTURES / "releases.json").read_bytes())
        if path.endswith("/search"):
            body = json.loads(request.content)
            name = "search_bbox_L2B.json" if "bbox" in body else "search_E40N15_sea.json"
            return httpx.Response(200, content=(FIXTURES / name).read_bytes())
        raise AssertionError(path)


def _call(
    service_key: ServiceKey,
    directory: Path,
    tool: str,
    arguments: dict[str, Any],
    *,
    fake: Fake | None = None,
    factory: Callable[[], EgmsArchive] | None = None,
    max_tiles: int = 9,
) -> CallToolResult:
    async def main() -> CallToolResult:
        transport = httpx.MockTransport(fake or Fake())

        def archive() -> EgmsArchive:
            client = httpx.AsyncClient(transport=transport)
            return EgmsArchive(client, service_key, archive_url=ARCHIVE)

        server = create_server(factory or archive, directory=directory, max_tiles=max_tiles)
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(main())


def _data(result: CallToolResult) -> Any:
    assert not result.is_error, result.content
    return result.structured_content


def _error(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(c, "text", "") for c in result.content)


def test_the_tools_and_their_instructions() -> None:
    async def main() -> tuple[list[str], dict[str, Any], str]:
        async with Client(create_server(lambda: pytest.fail("no archive needed"))) as client:
            tools = (await client.list_tools()).tools
            velocity = next(t for t in tools if t.name == "velocity_at")
            return sorted(t.name for t in tools), velocity.input_schema, client.instructions or ""

    names, schema, instructions = asyncio.run(main())
    assert names == ["area_summary", "find_files", "releases", "velocity_at"]
    assert schema["required"] == ["lon", "lat"]
    assert schema["properties"]["component"]["enum"] == ["U", "E"]
    assert "not a safety verdict" in instructions


def test_releases(service_key: ServiceKey, tmp_path: Path) -> None:
    result = _data(_call(service_key, tmp_path, "releases", {}))
    assert result == {"result": ["2020-2024", "2020-2025"]}


def test_find_files_lists_sizes_and_downloads_nothing(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    box = {"west": 14.4, "south": 40.0, "east": 15.7, "north": 41.0}
    found = _data(_call(service_key, tmp_path, "find_files", {**box, "level": "L2B"}))
    assert found["release"] == "2020-2025"
    assert found["count"] == len(found["files"]) > 0
    total_mb = sum(f["size_mb"] for f in found["files"])
    assert found["total_gb"] == pytest.approx(total_mb / 1000, abs=0.01)
    assert found["truncated"] is False
    assert list(tmp_path.iterdir()) == []


def test_velocity_at_names_its_source(service_key: ServiceKey, tmp_path: Path) -> None:
    _tile(tmp_path)
    lon, lat = _lonlat(4_700_350, 1_999_850)
    point = _data(_call(service_key, tmp_path, "velocity_at", {"lon": lon, "lat": lat}))
    assert point["velocity_mm_per_year"] == -37
    assert point["release"] == "2020-2025"
    assert (point["tile"], point["file"]) == ("E47N19", f"{STEM}.tiff")
    assert "positive up" in point["meaning"]


def test_velocity_at_sea_is_null(service_key: ServiceKey, tmp_path: Path) -> None:
    lon, lat = _lonlat(4_050_000, 1_550_000)
    point = _data(_call(service_key, tmp_path, "velocity_at", {"lon": lon, "lat": lat}))
    assert (point["velocity_mm_per_year"], point["file"]) == (None, None)


def test_area_summary(service_key: ServiceKey, tmp_path: Path) -> None:
    _tile(tmp_path)
    area = _data(_call(service_key, tmp_path, "area_summary", INNER))
    assert area["cells_with_data"] == 16
    assert area["coverage"] == 1.0
    assert (area["min"], area["max"], area["mean"], area["median"]) == (-17, 16, -0.5, -0.5)
    assert (area["share_below"], area["share_above"]) == (0.5, 0.5)
    assert area["fastest"][0]["velocity_mm_per_year"] == -17
    assert [abs(c["velocity_mm_per_year"]) for c in area["fastest"]] == [17, 16, 16, 15, 15]
    assert area["files"] == [f"{STEM}.tiff"]
    assert area["release"] == "2020-2025"


def test_area_summary_with_no_data_at_all(tmp_path: Path) -> None:
    box = _box(4_050_000, 1_550_000, 4_050_500, 1_550_500)
    stats = summarize([], box=(box["west"], box["south"], box["east"], box["north"]))
    assert stats["cells_with_data"] == 0
    assert stats["mean"] is None and stats["fastest"] == []


def test_area_summary_refuses_a_large_box(service_key: ServiceKey, tmp_path: Path) -> None:
    box = {"west": 10.0, "south": 44.0, "east": 12.0, "north": 45.0}
    message = _error(_call(service_key, tmp_path, "area_summary", box, max_tiles=2))
    assert "Narrow the box" in message
    assert list(tmp_path.iterdir()) == []


def test_area_summary_refuses_a_box_upside_down(service_key: ServiceKey, tmp_path: Path) -> None:
    box = {"west": 12.0, "south": 44.0, "east": 10.0, "north": 45.0}
    assert "west < east" in _error(_call(service_key, tmp_path, "area_summary", box))


def test_what_the_archive_refuses_reaches_the_agent(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    message = _error(_call(service_key, tmp_path, "releases", {}, fake=Fake(logged_in=False)))
    assert "log in" in message


def test_a_missing_key_says_what_to_set(service_key: ServiceKey, tmp_path: Path) -> None:
    def no_key() -> EgmsArchive:
        raise LookupError("EGMS_SERVICE_KEY is not set")

    message = _error(_call(service_key, tmp_path, "releases", {}, factory=no_key))
    assert message.endswith("EGMS_SERVICE_KEY is not set (in the environment of the MCP server)")


def test_the_default_archive_reads_the_key_file(
    service_key: ServiceKey, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.json"

    async def main() -> CallToolResult:
        async with Client(create_server(key_file=missing)) as client:
            return await client.call_tool("releases", {})

    assert "missing.json" in _error(asyncio.run(main()))


def test_egms_mcp_starts_the_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr("egms_client.mcp_server.run", lambda **options: seen.update(options))
    key = tmp_path / "key.json"
    status = cli.main(
        ["--key-file", str(key), "mcp", "--data-dir", str(tmp_path), "--max-tiles", "4"]
    )
    assert status == 0
    assert seen == {"directory": tmp_path, "max_tiles": 4, "key_file": key}
