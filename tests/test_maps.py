from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from egms_client import EgmsArchive, Hit, Query, ServiceKey
from egms_client.cli import _Meter, main
from egms_client.mosaic import Mosaic, lonlat_to_laea, mosaic, to_cog

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
STEM = "EGMS_L3_E47N19_100km_U_2020_2025_1"
#: A small box in degrees, and the same in EPSG:3035 metres.
BOX = (14.5, 40.5, 14.52, 40.52)


def _tiff(left: float, top: float, values: np.ndarray[Any, Any]) -> bytes:
    with rasterio.MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float32",
            crs="EPSG:3035",
            transform=from_origin(left, top, 100.0, 100.0),
            nodata=-9999.0,
        ) as dst:
            dst.write(values.astype("float32"), 1)
        return bytes(memory.read())


def _grid() -> tuple[float, float, np.ndarray[Any, Any]]:
    """A tiff covering BOX on the 100 m grid, values 0, 1, 2, ..."""
    minx, miny, maxx, maxy = lonlat_to_laea(*BOX)
    left, top = np.floor(minx / 100) * 100, np.ceil(maxy / 100) * 100
    cols = int(np.ceil((maxx - left) / 100))
    rows = int(np.ceil((top - miny) / 100))
    return left, top, np.arange(rows * cols, dtype="float32").reshape(rows, cols)


class Archive:
    """An archive with one L3 tile; ``chunks`` bytes per download chunk."""

    def __init__(self) -> None:
        self.searches: list[dict[str, Any]] = []
        left, top, values = _grid()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr(f"{STEM}.tiff", _tiff(left, top, values))
            z.writestr(f"{STEM}.csv", b"pid,easting,northing\n")
        self.zip = buffer.getvalue()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path.endswith("/releases"):
            return httpx.Response(200, json=["2020-2024", "2020-2025"])
        if path.endswith("/search"):
            self.searches.append(json.loads(request.content))
            body = json.loads((FIXTURES / "search_E47N19_U.json").read_text())
            body["hits"][0]["filesize"] = len(self.zip)
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=self.zip)


def _key_file(service_key: ServiceKey, tmp_path: Path) -> Path:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({f: getattr(service_key, f) for f in service_key.__slots__}))
    return key


def test_a_box_in_degrees_becomes_laea_metres() -> None:
    # 10°E 52°N is the origin of EPSG:3035, at false easting/northing.
    minx, miny, maxx, maxy = lonlat_to_laea(9.99, 51.99, 10.01, 52.01)
    assert minx < 4_321_000 < maxx
    assert miny < 3_210_000 < maxy


def test_a_mosaic_writes_as_a_cloud_optimized_geotiff(tmp_path: Path) -> None:
    values = np.array([[1.0, np.nan], [3.0, 4.0]], dtype="float32")
    path = to_cog(Mosaic(values=values, left=4_700_000.0, top=2_000_000.0), tmp_path / "m.tif")
    with rasterio.open(path) as src:
        assert src.crs.to_epsg() == 3035
        assert src.transform.c == 4_700_000.0 and src.transform.f == 2_000_000.0
        assert np.isnan(src.nodata)
        assert src.tags()["units"] == "mm/year"
        read = src.read(1)
    assert read[0, 0] == 1.0 and np.isnan(read[0, 1])
    assert not list(tmp_path.glob("*.part"))


def test_progress_reports_bytes_and_the_plan(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()
    plans: list[list[str]] = []
    seen: list[tuple[str, int, int]] = []

    async def run() -> list[Path]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(archive)) as client:
            a = EgmsArchive(client, service_key, archive_url="https://a/archive")
            query = Query(levels=("L3",), release="2020-2025", tile=(47, 19))
            return await a.fetch(
                query,
                tmp_path,
                keep=["tiff"],
                on_plan=lambda hits: plans.append([h.filename for h in hits]),
                on_progress=lambda h, got, total: seen.append((h.filename, got, total)),
            )

    (tiff,) = asyncio.run(run())
    assert plans == [[f"{STEM}.zip"]]
    assert seen[-1] == (f"{STEM}.zip", len(archive.zip), len(archive.zip))
    assert tiff.name == f"{STEM}.tiff"


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def _hit(name: str, size: int) -> Hit:
    return Hit(name, size, "", "", "", "")


def test_the_meter_prints_a_line_per_file_off_a_terminal() -> None:
    stream = _Stream(tty=False)
    meter = _Meter(stream)
    a, b = _hit("a.zip", 2_000_000_000), _hit("b.zip", 1_000_000_000)
    meter.plan([a, b])
    meter.progress(a, 10, a.filesize)
    meter.file(a, [Path("a.tiff")])
    meter.file(b, [])
    meter.close()
    assert stream.getvalue().splitlines() == [
        "2 files, 3.00 GB to download",
        "[1/2] a.zip: a.tiff",
        "[2/2] b.zip: absent",
    ]


def test_the_meter_updates_one_line_on_a_terminal() -> None:
    stream = _Stream(tty=True)
    now = [0.0]
    meter = _Meter(stream, clock=lambda: now[0])
    a = _hit("a.zip", 1_000_000_000)
    meter.plan([a])
    now[0] = 1.0
    meter.progress(a, 500_000_000, a.filesize)
    meter.progress(a, 600_000_000, a.filesize)  # within 0.5 s: not shown
    meter.file(a, [Path("a.tiff")])
    meter.close()
    out = stream.getvalue()
    assert "\r0/1 files, 0.50/1.00 GB (50%)" in out
    assert "0.60/1.00" not in out
    assert out.endswith("\r1/1 files, 1.00/1.00 GB (100%)\n")


def test_nothing_to_download_prints_nothing() -> None:
    stream = _Stream(tty=True)
    meter = _Meter(stream)
    meter.plan([])
    meter.close()
    assert stream.getvalue() == ""


def test_the_cli_makes_a_map_from_a_box_in_degrees(
    service_key: ServiceKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = Archive()
    client = httpx.AsyncClient(transport=httpx.MockTransport(archive))
    out = tmp_path / "map.tif"
    argv = [
        "--key-file",
        str(_key_file(service_key, tmp_path)),
        "mosaic",
        "--bbox",
        ",".join(map(str, BOX)),
        "--data-dir",
        str(tmp_path / "tiles"),
        "--out",
        str(out),
    ]
    assert main(argv, client=client) == 0
    assert archive.searches[0]["productType"] == "ORTHO-UP"
    assert archive.searches[0]["levels"] == ["L3"]
    left, top, values = _grid()
    with rasterio.open(out) as src:
        got = src.read(1)
        assert (src.transform.c, src.transform.f) == (left, top)
    assert np.array_equal(got, values)
    assert "pixels of 100 m from 1 tiles" in capsys.readouterr().err
    # Same box again: the tile is on disk, nothing is downloaded.
    assert main(argv, client=httpx.AsyncClient(transport=httpx.MockTransport(archive))) == 0


def test_the_cli_mosaic_needs_a_box(
    service_key: ServiceKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(Archive()))
    argv = ["--key-file", str(_key_file(service_key, tmp_path)), "mosaic", "--tile", "E47N19"]
    assert main(argv, client=client) == 1
    assert "needs --bbox" in capsys.readouterr().err


def test_the_cli_names_the_raster_extra(
    service_key: ServiceKey,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real = builtins.__import__

    def no_mosaic(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "egms_client.mosaic":
            raise ModuleNotFoundError("No module named 'rasterio'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mosaic)
    client = httpx.AsyncClient(transport=httpx.MockTransport(Archive()))
    argv = ["--key-file", str(_key_file(service_key, tmp_path)), "mosaic", "--bbox", "1,2,3,4"]
    assert main(argv, client=client) == 1
    assert "egms-client[raster]" in capsys.readouterr().err


def test_mosaic_of_the_downloaded_tile_matches(tmp_path: Path) -> None:
    left, top, values = _grid()
    path = tmp_path / f"{STEM}.tiff"
    path.write_bytes(_tiff(left, top, values))
    minx, miny, maxx, maxy = lonlat_to_laea(*BOX)
    m = mosaic([path], minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    assert np.array_equal(m.values, values)
