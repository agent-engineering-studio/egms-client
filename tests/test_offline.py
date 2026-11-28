from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from egms_client import InitResult, ServiceKey, TileOutcome, init
from egms_client.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE = "https://a/archive"
#: E47N19 and E48N19 are on land, E40N15 is at sea.
LAND = {"E47N19", "E48N19"}


def _zip(stem: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{stem}.tiff", b"TIFF")
        z.writestr(f"{stem}.csv", b"series")
    return buffer.getvalue()


class Archive:
    """A fake L3 archive: every tile in ``LAND`` exists, for both components."""

    def __init__(self, *, refuse: str = "") -> None:
        self.requests: list[httpx.Request] = []
        #: A file name whose download answers 500.
        self.refuse = refuse
        self.flight = 0
        self.max_flight = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("oauth2-token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path.endswith("/releases"):
            return httpx.Response(200, content=(FIXTURES / "releases.json").read_bytes())
        if path.endswith("/search"):
            body = json.loads(request.content)
            tile, component = body["tileId"], body["productType"].removeprefix("ORTHO-")[0]
            if tile not in LAND:
                return httpx.Response(
                    200, content=(FIXTURES / "search_E40N15_sea.json").read_bytes()
                )
            name = f"EGMS_L3_{tile}_100km_{component}_2020_2025_1.zip"
            hit = {"filename": name, "filesize": 1000, "tileId": tile, "version": "2020_2025_1"}
            return httpx.Response(200, json={"status": True, "id": "s", "hits": [hit]})
        if "/download/" in path:
            name = path.rsplit("/", 1)[1]
            if name == self.refuse:
                return httpx.Response(500, text="no")
            self.flight += 1
            self.max_flight = max(self.max_flight, self.flight)
            await asyncio.sleep(0.01)
            self.flight -= 1
            return httpx.Response(200, content=_zip(name.removesuffix(".zip")))
        raise AssertionError(path)

    def downloaded(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[1] for r in self.requests if "/download/" in r.url.path]


def run(archive: Archive, service_key: ServiceKey, **kwargs: Any) -> InitResult:
    async def body() -> InitResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(archive)) as client:
            return await init(client=client, key=service_key, archive_url=ARCHIVE, **kwargs)

    return asyncio.run(body())


TILES = [(47, 19), (48, 19), (40, 15)]


def test_init_downloads_an_area_once(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()
    seen: list[TileOutcome] = []
    first = run(
        archive,
        service_key,
        directory=tmp_path,
        tiles=TILES,
        release="2020-2025",
        on_tile=seen.append,
    )
    assert first.complete and first.release == "2020-2025" and first.directory == tmp_path
    assert len(first.downloaded) == 4 and len(first.absent) == 2 and not first.skipped
    assert first.bytes > 0 and len(seen) == 6
    assert sorted(p.name for p in tmp_path.glob("*.tiff")) == [
        f"EGMS_L3_E{e}N19_100km_{c}_2020_2025_1.tiff" for e in (47, 48) for c in "EU"
    ]
    assert not list(tmp_path.glob("*.zip")) and not list(tmp_path.glob("*.part"))

    archive.requests.clear()
    again = run(archive, service_key, directory=tmp_path, tiles=TILES, release="2020-2025")
    assert len(again.skipped) == 4 and len(again.absent) == 2 and again.bytes == 0
    # Offline: the second run asks the archive nothing, not even a token.
    assert archive.requests == []


def test_never_more_than_two_downloads_at_once(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()
    run(archive, service_key, directory=tmp_path, tiles=TILES, release="2020-2025", concurrency=8)
    assert archive.max_flight == 2


def test_keep_per_component(service_key: ServiceKey, tmp_path: Path) -> None:
    result = run(
        Archive(),
        service_key,
        directory=tmp_path,
        tiles=[(47, 19)],
        release="2020-2025",
        keep={"U": ("tiff", "csv")},
    )
    assert len(result.downloaded) == 2
    assert [p.name for p in tmp_path.glob("*.csv")] == ["EGMS_L3_E47N19_100km_U_2020_2025_1.csv"]


def test_a_failed_tile_is_reported_and_the_rest_goes_on(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    archive = Archive(refuse="EGMS_L3_E47N19_100km_U_2020_2025_1.zip")
    result = run(
        archive,
        service_key,
        directory=tmp_path,
        tiles=TILES,
        components=["U"],
        release="2020-2025",
        retries=0,
    )
    assert not result.complete
    [failed] = result.failed
    assert failed.tile == (47, 19) and failed.path is None and "500" in failed.error
    assert [t.tile for t in result.downloaded] == [(48, 19)]
    # The next run fetches only what failed.
    archive.refuse = ""
    archive.requests.clear()
    again = run(
        archive, service_key, directory=tmp_path, tiles=TILES, components=["U"], release="2020-2025"
    )
    assert archive.downloaded() == ["EGMS_L3_E47N19_100km_U_2020_2025_1.zip"]
    assert again.complete


def test_a_disk_error_raises(
    service_key: ServiceKey, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(*_: Any, **__: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("egms_client.client.extract", full)
    with pytest.raises(OSError, match="No space"):
        run(Archive(), service_key, directory=tmp_path, tiles=TILES, release="2020-2025")


def test_the_release_defaults_to_the_latest(service_key: ServiceKey, tmp_path: Path) -> None:
    result = run(Archive(), service_key, directory=tmp_path, tiles=[(47, 19)], components=["U"])
    assert result.release == "2020-2025"


def test_a_bbox_is_turned_into_tiles(service_key: ServiceKey, tmp_path: Path) -> None:
    # Around Naples: inside E47N19 only.
    result = run(
        Archive(),
        service_key,
        directory=tmp_path,
        bbox=(14.5, 40.3, 15.0, 40.6),
        components=["U"],
        release="2020-2025",
    )
    assert [t.tile for t in result.tiles] == [(47, 19)]


def test_the_default_directory_is_under_data_root(
    service_key: ServiceKey, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EGMS_DATA_DIR", raising=False)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    result = run(Archive(), service_key, tiles=[(47, 19)], components=["U"], release="2020-2025")
    assert result.directory == tmp_path / "egms-client"
    assert len(list((tmp_path / "egms-client").glob("*.tiff"))) == 1


def test_init_needs_one_area(service_key: ServiceKey) -> None:
    with pytest.raises(ValueError, match="bbox or tiles"):
        run(Archive(), service_key)
    with pytest.raises(ValueError, match="bbox or tiles"):
        run(Archive(), service_key, bbox=(14.0, 40.0, 15.0, 41.0), tiles=[(47, 19)])
    with pytest.raises(ValueError, match="concurrency"):
        run(Archive(), service_key, tiles=[(47, 19)], concurrency=0)


def _cli(archive: Archive, argv: list[str], service_key: ServiceKey, tmp_path: Path) -> int:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({f: getattr(service_key, f) for f in service_key.__slots__}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(archive))
    return main(["--key-file", str(key), *argv], client=client)


def test_the_cli_init(
    service_key: ServiceKey, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "data"
    argv = ["init", "--tile", "E47N19", "--tile", "E40N15", "--release", "2020-2025"]
    assert _cli(Archive(), [*argv, "--out", str(out)], service_key, tmp_path) == 0
    err = capsys.readouterr().err
    assert "E47N19 U: downloaded" in err and "E40N15 E: absent" in err
    assert "2 downloaded" in err and "0 failed" in err
    assert len(list(out.glob("*.tiff"))) == 2

    refusing = Archive(refuse="EGMS_L3_E48N19_100km_U_2020_2025_1.zip")
    argv = ["init", "--tile", "E48N19", "--component", "U", "--out", str(out)]
    assert _cli(refusing, argv, service_key, tmp_path) == 1
    assert "E48N19 U: failed" in capsys.readouterr().err

    assert _cli(Archive(), ["init"], service_key, tmp_path) == 1
    assert "needs an area" in capsys.readouterr().err


def test_egms_error_is_a_failure_too(service_key: ServiceKey, tmp_path: Path) -> None:
    class Odd(Archive):
        async def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"status": False, "message": "Server busy"})
            return await super().__call__(request)

    result = run(Odd(), service_key, directory=tmp_path, tiles=[(47, 19)], release="2020-2025")
    assert len(result.failed) == 2
    assert all("Server busy" in t.error for t in result.failed)


def test_a_failure_with_no_message_says_what_it_was(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    """httpx.ConnectTimeout has an empty message: the outcome names the exception."""

    class Unreachable(Archive):
        async def __call__(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("")

    result = run(
        Unreachable(),
        service_key,
        directory=tmp_path,
        tiles=[(47, 19)],
        components=["U"],
        release="2020-2025",
        retries=0,
    )
    [failed] = result.failed
    assert failed.error == "ConnectTimeout"
