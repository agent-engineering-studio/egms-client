from __future__ import annotations

import asyncio
import io
import json
import shutil
import struct
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from egms_client import EgmsArchive, EgmsError, Query, ServiceKey
from egms_client.cli import main
from egms_client.tables import (
    attributes,
    csv_to_geoparquet,
    dates,
    read_csv,
    series_long,
    to_geoparquet,
)

pd = pytest.importorskip("pandas")
pq = pytest.importorskip("pyarrow.parquet")

FIXTURES = Path(__file__).parent / "fixtures"
L2B = FIXTURES / "EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv"
L3 = FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv"


def test_an_l2_csv_reads_with_its_series() -> None:
    frame = read_csv(L2B)
    assert len(frame) == 3
    assert list(frame.columns[:4]) == ["pid", "mp_type", "latitude", "longitude"]
    assert str(frame["pid"].dtype) == "string"
    days = dates(frame)
    assert len(days) == 197 and days[-1] == date(2025, 11, 21)
    assert all(str(frame[c].dtype) == "float32" for c in frame.columns[-3:])
    assert "mean_velocity" in attributes(frame).columns
    assert not dates(attributes(frame))


def test_an_l3_csv_reads_without_its_series() -> None:
    frame = read_csv(L3, series=False)
    assert list(frame.columns[:3]) == ["pid", "easting", "northing"]
    assert not dates(frame)
    assert frame["easting"].iloc[0] == 4_773_750


def test_columns_narrow_the_attributes() -> None:
    frame = read_csv(L3, series=False, columns=["mean_velocity"])
    assert list(frame.columns) == ["pid", "mean_velocity"]
    with pytest.raises(ValueError, match="has no columns"):
        read_csv(L3, columns=["speed"])


def test_the_long_series_has_one_row_per_point_and_date() -> None:
    frame = read_csv(L3)
    long = series_long(frame)
    assert list(long.columns) == ["pid", "date", "displacement_mm"]
    assert len(long) == len(frame) * len(dates(frame))
    assert long["date"].min() == pd.Timestamp(dates(frame)[0])


def test_geoparquet_has_points_in_laea(tmp_path: Path) -> None:
    path = csv_to_geoparquet(Path(shutil.copy(L3, tmp_path / L3.name)), series=False)
    assert path == tmp_path / L3.with_suffix(".parquet").name
    table = pq.read_table(path)
    geo = json.loads(table.schema.metadata[b"geo"])
    column = geo["columns"]["geometry"]
    assert column["encoding"] == "WKB"
    assert column["crs"]["id"] == {"authority": "EPSG", "code": 3035}
    first = table.column("geometry")[0].as_py()
    assert struct.unpack("<bIdd", first) == (1, 1, 4_773_750.0, 1_900_050.0)
    assert "bbox" not in column  # streamed: not known before the end
    assert not list(tmp_path.glob("*.part"))


def test_a_frame_writes_with_its_bbox(tmp_path: Path) -> None:
    frame = read_csv(L3, series=False)
    table = pq.read_table(to_geoparquet(frame, tmp_path / "l3.parquet"))
    bbox = json.loads(table.schema.metadata[b"geo"])["columns"]["geometry"]["bbox"]
    assert bbox[0] == frame["easting"].min()
    assert table.num_rows == 3


def test_an_empty_table_writes_without_a_bbox(tmp_path: Path) -> None:
    frame = read_csv(L3, series=False).iloc[0:0]
    table = pq.read_table(to_geoparquet(frame, tmp_path / "empty.parquet"))
    assert "bbox" not in json.loads(table.schema.metadata[b"geo"])["columns"]["geometry"]


class Archive:
    """An archive with one L2B burst whose CSV is the real sample."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path.endswith("/search"):
            body = json.loads((FIXTURES / "search_bbox_L2B.json").read_text())
            body["hits"] = body["hits"][:1]
            return httpx.Response(200, json=body)
        stem = L2B.stem
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr(f"{stem}.csv", L2B.read_bytes())
            z.writestr(f"{stem}.xml", b"<BURST/>")
        return httpx.Response(200, content=buffer.getvalue())


def _fetch(service_key: ServiceKey, directory: Path, keep: list[Any]) -> list[Path]:
    async def run() -> list[Path]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(Archive())) as client:
            archive = EgmsArchive(client, service_key, archive_url="https://a/archive")
            query = Query(levels=("L2B",), release="2020-2025", bbox=(14.4, 40.0, 15.7, 41.0))
            return await archive.fetch(query, directory, keep=keep)

    return asyncio.run(run())


def test_fetch_can_keep_parquet_instead_of_the_csv(service_key: ServiceKey, tmp_path: Path) -> None:
    (path,) = _fetch(service_key, tmp_path, ["parquet"])
    assert path.name == f"{L2B.stem}.parquet"
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
    assert pq.read_table(path).num_rows == 3
    # Once there, it is not downloaded again.
    assert _fetch(service_key, tmp_path, ["parquet"]) == [path]


def test_fetch_can_keep_both(service_key: ServiceKey, tmp_path: Path) -> None:
    paths = _fetch(service_key, tmp_path, ["csv", "parquet"])
    assert sorted(p.suffix for p in paths) == [".csv", ".parquet"]


def test_a_failed_conversion_leaves_no_csv(service_key: ServiceKey, tmp_path: Path) -> None:
    class Broken(Archive):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if "/download/" in request.url.path:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as z:
                    z.writestr(f"{L2B.stem}.csv", b"pid,easting\n")
                return httpx.Response(200, content=buffer.getvalue())
            return super().__call__(request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(Broken())) as client:
            archive = EgmsArchive(client, service_key, archive_url="https://a/archive")
            query = Query(levels=("L2B",), release="2020-2025", bbox=(14.4, 40.0, 15.7, 41.0))
            await archive.fetch(query, tmp_path, keep=["parquet"])

    with pytest.raises(ValueError, match="easting/northing"):
        asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


def test_the_cli_converts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv = shutil.copy(L2B, tmp_path / L2B.name)
    assert main(["convert", str(csv), "--no-series"]) == 0
    assert "parquet" in capsys.readouterr().err
    assert pq.read_table(tmp_path / f"{L2B.stem}.parquet").num_rows == 3


def test_the_cli_explains_a_missing_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real = builtins.__import__

    def no_pyarrow(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("pyarrow"):
            raise ModuleNotFoundError("No module named 'pyarrow'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pyarrow)
    assert main(["convert", str(L3)]) == 1
    assert "egms-client[tables]" in capsys.readouterr().err


def test_a_busy_token_endpoint_is_retried_once_for_everyone(service_key: ServiceKey) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("oauth2-token"):
            calls.append("token")
            if len(calls) == 1:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(200, json=["2020-2025"])

    async def no_wait(_: float) -> None:
        return None

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            archive = EgmsArchive(
                client, service_key, archive_url="https://a/archive", sleep=no_wait
            )
            await asyncio.gather(*(archive.releases() for _ in range(10)))

    asyncio.run(run())
    assert calls == ["token", "token"]


def test_a_token_endpoint_that_stays_down_raises(service_key: ServiceKey) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def no_wait(_: float) -> None:
        return None

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await EgmsArchive(client, service_key, sleep=no_wait).token()

    with pytest.raises(httpx.ConnectError):
        asyncio.run(run())


def test_a_bad_assertion_is_not_retried(service_key: ServiceKey) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"message": "DecodeError"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await EgmsArchive(client, service_key).token()

    with pytest.raises(EgmsError, match="HTTP 500"):
        asyncio.run(run())
    assert calls == [1]


def test_a_conversion_that_fails_midway_leaves_nothing(tmp_path: Path) -> None:
    lines = L3.read_text().splitlines()
    lines[2] = lines[2].rsplit(",", 1)[0] + ",oops"
    csv = tmp_path / L3.name
    csv.write_text("\n".join(lines) + "\n")
    with pytest.raises(Exception, match="oops"):
        csv_to_geoparquet(csv)
    assert sorted(p.name for p in tmp_path.iterdir()) == [L3.name]
