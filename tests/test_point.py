"""The velocity at one point, async and sync."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import numpy as np
import pytest

from egms_client import (
    EgmsArchive,
    EgmsError,
    PointVelocity,
    Query,
    ServiceKey,
    tile_for_point,
)
from egms_client.sync import Archive

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from egms_client.mosaic import lonlat_to_xy, value_at  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE = "https://a/archive"
STEM = "EGMS_L3_E47N19_100km_U_2020_2025_1"
TO_LONLAT = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)


def _lonlat(x: float, y: float) -> tuple[float, float]:
    lon, lat = TO_LONLAT.transform(x, y)
    return float(lon), float(lat)


def _tile(directory: Path, *, crs: str = "EPSG:3035") -> Path:
    """A 10 x 10 stand-in for E47N19, top-left corner, with a nodata and a NaN cell."""
    values = np.arange(100, dtype="float32").reshape(10, 10) - 50
    values[0, 1] = -9999.0
    values[0, 2] = np.nan
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{STEM}.tiff"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(4_700_000, 2_000_000, 100, 100),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return path


class Fake:
    """Releases, and a search that finds nothing (a tile at sea)."""

    def __init__(self, *, logged_in: bool = True) -> None:
        self.paths: list[str] = []
        self.logged_in = logged_in

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if not self.logged_in:
            return httpx.Response(200, content=(FIXTURES / "not_logged_in.json").read_bytes())
        if path.endswith(("/releases", "/levels", "/bursts")):
            name = path.rsplit("/", 1)[1]
            return httpx.Response(200, content=(FIXTURES / f"{name}.json").read_bytes())
        if path.endswith("/search"):
            return httpx.Response(200, content=(FIXTURES / "search_E40N15_sea.json").read_bytes())
        raise AssertionError(path)


def _client(fake: Fake) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(fake))


def test_tile_for_point() -> None:
    assert tile_for_point(4_773_750, 1_900_050) == (47, 19)
    assert tile_for_point(4_700_000, 1_999_999.9) == (47, 19)


def test_value_at_reads_the_cell(tmp_path: Path) -> None:
    tiff = _tile(tmp_path)
    assert value_at(tiff, 4_700_350, 1_999_850) == 13 - 50  # row 1, col 3
    assert value_at(tiff, 4_700_150, 1_999_950) is None  # nodata
    assert value_at(tiff, 4_700_250, 1_999_950) is None  # NaN
    assert value_at(tiff, 4_701_050, 1_999_950) is None  # outside the raster


def test_value_at_refuses_another_projection(tmp_path: Path) -> None:
    tiff = _tile(tmp_path, crs="EPSG:4326")
    with pytest.raises(ValueError, match="not LAEA"):
        value_at(tiff, 4_700_350, 1_999_850)


def test_lonlat_to_xy_round_trips() -> None:
    lon, lat = _lonlat(4_773_750, 1_900_050)
    x, y = lonlat_to_xy(lon, lat)
    assert (round(x, 3), round(y, 3)) == (4_773_750, 1_900_050)


def test_velocity_at_a_cached_tile_asks_nothing(service_key: ServiceKey, tmp_path: Path) -> None:
    tiff = _tile(tmp_path)
    lon, lat = _lonlat(4_700_350, 1_999_850)
    fake = Fake()

    async def main() -> PointVelocity:
        async with _client(fake) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            return await archive.velocity_at(lon, lat, "U", "2020-2025", tmp_path)

    point = asyncio.run(main())
    assert fake.paths == []
    assert point.velocity == -37
    assert (point.tile, point.component, point.release, point.file) == (
        (47, 19),
        "U",
        "2020-2025",
        tiff,
    )
    assert (round(point.x), round(point.y)) == (4_700_350, 1_999_850)


def test_velocity_at_defaults_to_the_latest_release(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    _tile(tmp_path)
    lon, lat = _lonlat(4_700_350, 1_999_850)
    fake = Fake()

    async def main() -> PointVelocity:
        async with _client(fake) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            return await archive.velocity_at(lon, lat, directory=tmp_path)

    point = asyncio.run(main())
    assert point.release == "2020-2025"
    assert [p.rsplit("/", 1)[1] for p in fake.paths] == ["@@oauth2-token", "releases"]


def test_velocity_at_sea_is_none_without_a_file(service_key: ServiceKey, tmp_path: Path) -> None:
    lon, lat = _lonlat(4_050_000, 1_550_000)

    async def main() -> PointVelocity:
        async with _client(Fake()) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            return await archive.velocity_at(lon, lat, "U", "2020-2025", tmp_path)

    point = asyncio.run(main())
    assert (point.tile, point.velocity, point.file) == ((40, 15), None, None)


# The sync façade.


def test_sync_archive_blocks_and_closes(service_key: ServiceKey, tmp_path: Path) -> None:
    tiff = _tile(tmp_path)
    lon, lat = _lonlat(4_700_350, 1_999_850)
    with Archive(_client(Fake()), service_key, archive_url=ARCHIVE) as archive:
        assert archive.releases() == ["2020-2024", "2020-2025"]
        assert archive.fetch_tile((47, 19), "U", "2020-2025", tmp_path) == tiff
        assert archive.velocity_at(lon, lat, directory=tmp_path).velocity == -37
        assert archive.search((40, 15), "U", "2020-2025") is None
    archive.close()  # twice is fine
    with pytest.raises(RuntimeError, match="closed"):
        archive.releases()


def test_sync_archive_lists_and_searches(service_key: ServiceKey, tmp_path: Path) -> None:
    sea = Query(levels=("L3",), release="2020-2025", tile=(40, 15))
    with Archive(_client(Fake()), service_key, archive_url=ARCHIVE) as archive:
        assert "L2B" in archive.levels()
        assert archive.bursts()
        assert archive.find(sea) == []
        assert archive.fetch(sea, tmp_path, keep=["tiff"], on_plan=lambda hits: None) == []


def test_sync_archive_works_inside_a_running_loop(service_key: ServiceKey) -> None:
    """As in Jupyter, where asyncio.run refuses to start."""

    async def notebook_cell() -> list[str]:
        with Archive(_client(Fake()), service_key, archive_url=ARCHIVE) as archive:
            return archive.releases()

    assert asyncio.run(notebook_cell()) == ["2020-2024", "2020-2025"]


def test_sync_archive_raises_what_the_archive_refuses(service_key: ServiceKey) -> None:
    with (
        Archive(_client(Fake(logged_in=False)), service_key, archive_url=ARCHIVE) as archive,
        pytest.raises(EgmsError, match="log in"),
    ):
        archive.releases()


def test_sync_archive_with_bad_options_stops_its_thread(service_key: ServiceKey) -> None:
    with pytest.raises(TypeError):
        Archive(None, service_key, no_such_option=1)
