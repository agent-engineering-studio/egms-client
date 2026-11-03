from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from egms_client import EgmsArchive, EgmsError, Hit, Query, ServiceKey, default_directory
from egms_client.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE = "https://a/archive"
BOX = (14.4, 40.0, 15.7, 41.0)
QUERY = Query(levels=("L2B",), release="2020-2025", bbox=BOX)


def _zip(stem: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{stem}.csv", b"pid,mean_velocity\n")
        z.writestr(f"{stem}.xml", b"<BURST/>")
    return buffer.getvalue()


class Archive:
    """A fake archive for L2 searches. ``downloads`` scripts the answers per file."""

    def __init__(self, downloads: list[int | str] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.searches: list[dict[str, Any]] = []
        self.downloads = list(downloads or [])
        self.search_ids = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path.endswith(("/levels", "/bursts", "/releases")):
            name = path.rsplit("/", 1)[1]
            return httpx.Response(200, content=(FIXTURES / f"{name}.json").read_bytes())
        if path.endswith("/search"):
            body = json.loads(request.content)
            self.searches.append(body)
            self.search_ids += 1
            data = json.loads((FIXTURES / "search_bbox_L2B.json").read_text())
            data["id"] = f"id{self.search_ids}"
            return httpx.Response(200, json=data)
        if "/download/" in path:
            step = self.downloads.pop(0) if self.downloads else 200
            if step == "drop":
                raise httpx.ReadError("connection reset")
            if step != 200:
                return httpx.Response(int(step), text="Rerun your search")
            stem = path.rsplit("/", 1)[1].removesuffix(".zip")
            return httpx.Response(200, content=_zip(stem))
        raise AssertionError(path)

    def downloaded(self) -> int:
        return sum("/download/" in r.url.path for r in self.requests)


def run(
    archive: Archive,
    service_key: ServiceKey,
    body: Callable[[EgmsArchive], Coroutine[Any, Any, Any]],
) -> Any:
    async def no_wait(_: float) -> None:
        return None

    async def main() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(archive)) as client:
            return await body(EgmsArchive(client, service_key, archive_url=ARCHIVE, sleep=no_wait))

    return asyncio.run(main())


def test_levels_and_bursts(service_key: ServiceKey) -> None:
    async def body(a: EgmsArchive) -> tuple[list[str], list[str]]:
        return await a.levels(), await a.bursts()

    levels, bursts = run(Archive(), service_key, body)
    assert levels == ["L2A", "L2B", "L3"]
    assert bursts[:2] == ["0171", "0167"]


def test_a_large_box_is_searched_in_pieces_and_each_file_listed_once(
    service_key: ServiceKey,
) -> None:
    archive = Archive()
    query = Query(levels=("L2B",), release="2020-2025", bbox=(6.0, 36.0, 19.0, 47.5))
    searches = run(archive, service_key, lambda a: a.find(query))
    assert len(archive.searches) == 9
    assert all(s["bbox"][1][0] - s["bbox"][0][0] <= 5 for s in archive.searches)
    # Every piece answers the same three files: they are listed once.
    assert [len(s.hits) for s in searches] == [3]


def test_fetch_keeps_what_is_asked_and_resumes(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()
    seen: list[str] = []

    def on_file(hit: Hit, paths: list[Path]) -> None:
        seen.append(hit.filename)

    first = run(
        archive, service_key, lambda a: a.fetch(QUERY, tmp_path, keep=["csv"], on_file=on_file)
    )
    assert sorted(p.name for p in first) == sorted(f"{n.removesuffix('.zip')}.csv" for n in seen)
    assert (
        len(first) == 3 and not list(tmp_path.glob("*.zip")) and not list(tmp_path.glob("*.part"))
    )
    again = run(archive, service_key, lambda a: a.fetch(QUERY, tmp_path, keep=["csv"]))
    assert sorted(again) == sorted(first)
    assert archive.downloaded() == 3


def test_fetch_can_keep_the_zip_and_its_members(service_key: ServiceKey, tmp_path: Path) -> None:
    paths = run(
        Archive(), service_key, lambda a: a.fetch(QUERY, tmp_path, keep=["zip", "xml", "zip"])
    )
    assert sorted(p.suffix for p in paths) == [".xml"] * 3 + [".zip"] * 3


def test_fetch_refuses_more_than_max_bytes_before_downloading(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    archive = Archive()
    with pytest.raises(EgmsError, match="more than max_bytes"):
        run(archive, service_key, lambda a: a.fetch(QUERY, tmp_path, max_bytes=1_000))
    assert archive.downloaded() == 0


def test_an_expired_search_is_searched_again(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive(downloads=[401])
    paths = run(archive, service_key, lambda a: a.fetch(QUERY, tmp_path, concurrency=1))
    assert len(paths) == 3
    assert len(archive.searches) == 2
    assert archive.requests[-1].url.params["id"] == "id2"


def test_network_errors_and_busy_answers_are_retried(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    archive = Archive(downloads=["drop", 503, 200, 200])
    paths = run(archive, service_key, lambda a: a.fetch(QUERY, tmp_path, concurrency=1))
    assert len(paths) == 3
    assert archive.downloaded() == 5


def test_a_download_that_keeps_failing_raises(service_key: ServiceKey, tmp_path: Path) -> None:
    with pytest.raises(EgmsError, match="HTTP 503"):
        run(
            Archive(downloads=[503] * 4),
            service_key,
            lambda a: a.fetch(QUERY, tmp_path, concurrency=1),
        )
    with pytest.raises(httpx.ReadError):
        run(
            Archive(downloads=["drop"] * 4),
            service_key,
            lambda a: a.fetch(QUERY, tmp_path, concurrency=1),
        )
    assert not list(tmp_path.glob("*.part"))


def test_a_404_file_is_skipped(service_key: ServiceKey, tmp_path: Path) -> None:
    paths = run(
        Archive(downloads=[404]), service_key, lambda a: a.fetch(QUERY, tmp_path, concurrency=1)
    )
    assert len(paths) == 2


def test_fetch_needs_something_to_keep(service_key: ServiceKey, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep"):
        run(Archive(), service_key, lambda a: a.fetch(QUERY, tmp_path, keep=[]))


def test_the_default_directory_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGMS_DATA_DIR", "/data/egms")
    assert default_directory() == Path("/data/egms")
    monkeypatch.delenv("EGMS_DATA_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", "/cache")
    assert default_directory() == Path("/cache/egms-client")


def test_without_a_client_it_opens_and_closes_its_own(service_key: ServiceKey) -> None:
    async def body() -> bool:
        async with EgmsArchive(key=service_key) as archive:
            client = archive._client
        return client.is_closed

    assert asyncio.run(body())


def _cli(archive: Archive, argv: list[str], service_key: ServiceKey, tmp_path: Path) -> int:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({f: getattr(service_key, f) for f in service_key.__slots__}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(archive), base_url=ARCHIVE)
    return main(["--key-file", str(key), *argv], client=client)


def test_the_cli_lists_releases(
    service_key: ServiceKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(Archive(), ["releases"], service_key, tmp_path) == 0
    assert capsys.readouterr().out.split() == ["2020-2024", "2020-2025"]
    assert _cli(Archive(), ["levels"], service_key, tmp_path) == 0
    assert "L2B" in capsys.readouterr().out


def test_the_cli_searches_and_downloads(
    service_key: ServiceKey,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = Archive()
    bbox = "--bbox=14.4,40.0,15.7,41.0"
    assert _cli(archive, ["search", "--level", "L2B", bbox], service_key, tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out.count("EGMS_L2b_") == 3
    assert "3 files" in captured.err
    assert archive.searches[-1]["releases"] == ["2020-2025"]
    out = tmp_path / "out"
    argv = ["download", "--level", "L2B", bbox, "--release", "2020-2025", "--keep", "csv"]
    assert _cli(archive, [*argv, "--out", str(out)], service_key, tmp_path) == 0
    assert len(list(out.glob("*.csv"))) == 3


def test_the_cli_reports_errors_without_a_traceback(
    service_key: ServiceKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(Archive(), ["search", "--bbox", "1,2,3"], service_key, tmp_path) == 1
    assert "west,south,east,north" in capsys.readouterr().err
    assert (
        _cli(
            Archive(),
            ["download", "--tile", "E47N19", "--max-gb", "0.000001"],
            service_key,
            tmp_path,
        )
        == 1
    )
    assert "max_bytes" in capsys.readouterr().err


def test_never_more_than_two_downloads_at_once(service_key: ServiceKey, tmp_path: Path) -> None:
    """The archive answers 429 to a third concurrent download per account."""
    fake = Archive()
    flight = {"now": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if "/download/" not in request.url.path:
            return fake(request)
        flight["now"] += 1
        flight["max"] = max(flight["max"], flight["now"])
        await asyncio.sleep(0.01)
        flight["now"] -= 1
        return fake(request)

    async def main() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            # fetch with a high concurrency, and fetch_tile-like calls beside it
            await asyncio.gather(
                archive.fetch(QUERY, tmp_path / "a", keep=["csv"], concurrency=8),
                archive.fetch(QUERY, tmp_path / "b", keep=["csv"], concurrency=8),
            )

    asyncio.run(main())
    assert flight["max"] == 2
    assert fake.downloaded() == 6


def test_a_429_waits_as_long_as_the_server_says(service_key: ServiceKey, tmp_path: Path) -> None:
    waits: list[float] = []

    class Busy(Archive):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if "/download/" in request.url.path and not waits:
                return httpx.Response(429, headers={"Retry-After": "7"}, text="too many")
            return super().__call__(request)

    async def record(seconds: float) -> None:
        waits.append(seconds)

    async def main() -> list[Path]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(Busy())) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE, sleep=record)
            return await archive.fetch(QUERY, tmp_path, keep=["csv"], concurrency=1)

    assert len(asyncio.run(main())) == 3
    assert waits == [7.0]


def test_a_429_without_retry_after_waits_at_least_half_a_minute(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    async def main() -> list[Path]:
        archive_ = Archive(downloads=[429])
        async with httpx.AsyncClient(transport=httpx.MockTransport(archive_)) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE, sleep=record)
            return await archive.fetch(QUERY, tmp_path, keep=["csv"], concurrency=1)

    assert len(asyncio.run(main())) == 3
    assert waits == [30.0]


def test_a_download_stopped_midway_leaves_no_part(service_key: ServiceKey, tmp_path: Path) -> None:
    def stop(hit: Hit, received: int, total: int) -> None:
        raise KeyboardInterrupt

    async def main() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(Archive())) as client:
            archive = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            await archive.fetch(QUERY, tmp_path, concurrency=1, on_progress=stop)

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(main())
    assert not list(tmp_path.glob("*.part"))
