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

from egms_client import EgmsArchive, EgmsError, ServiceKey

FIXTURES = Path(__file__).parent / "fixtures"

ARCHIVE = "https://a/archive"
STEM = "EGMS_L3_E47N19_100km_U_2020_2025_1"


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{STEM}.tiff", b"TIFF")
        z.writestr(f"{STEM}.csv", b"series")
    return buffer.getvalue()


class Archive:
    """A fake archive that records every request."""

    def __init__(self, *, download_status: int = 200, expired: int = 0) -> None:
        self.requests: list[httpx.Request] = []
        self.tokens = 0
        self.download_status = download_status
        #: How many downloads answer 401 before one goes through.
        self.expired = expired

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("oauth2-token"):
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"t{self.tokens}", "expires_in": 3600})
        assert request.headers.get("Authorization", "").startswith("Bearer") or "download" in path
        if path.endswith("/releases"):
            return httpx.Response(200, content=(FIXTURES / "releases.json").read_bytes())
        if path.endswith("/search"):
            tile = json.loads(request.content)["tileId"]
            name = "search_E47N19_U.json" if tile == "E47N19" else "search_E40N15_sea.json"
            return httpx.Response(200, content=(FIXTURES / name).read_bytes())
        if "/download/" in path:
            assert request.url.params["id"] == "0123456789abcdef0123456789abcdef"
            if self.expired:
                self.expired -= 1
                return httpx.Response(401, text="gone")
            if self.download_status != 200:
                return httpx.Response(self.download_status, text="gone")
            return httpx.Response(200, content=_zip())
        raise AssertionError(path)


def run(
    archive: Archive,
    service_key: ServiceKey,
    body: Callable[[EgmsArchive], Coroutine[Any, Any, Any]],
    clock: Callable[[], float] = lambda: 1_000.0,
) -> Any:
    async def main() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(archive)) as client:
            return await body(EgmsArchive(client, service_key, archive_url=ARCHIVE, clock=clock))

    return asyncio.run(main())


def test_releases_need_a_token(service_key: ServiceKey) -> None:
    archive = Archive()
    assert run(archive, service_key, lambda a: a.releases()) == ["2020-2024", "2020-2025"]
    assert archive.requests[0].url.path.endswith("oauth2-token")
    assert archive.requests[1].headers["Authorization"] == "Bearer t1"


def test_the_token_is_reused_and_renewed_before_it_expires(service_key: ServiceKey) -> None:
    archive = Archive()
    now = [1_000.0]

    async def body(a: EgmsArchive) -> None:
        await a.releases()
        await a.releases()
        assert archive.tokens == 1
        now[0] += 3600 - 299
        await a.releases()

    run(archive, service_key, body, clock=lambda: now[0])
    assert archive.tokens == 2


def test_a_tile_is_downloaded_once(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()

    async def body(a: EgmsArchive) -> tuple[Path | None, Path | None]:
        first = await a.fetch_tile((47, 19), "U", "2020_2025", tmp_path / "tiles")
        second = await a.fetch_tile((47, 19), "U", "2020-2025", tmp_path / "tiles")
        return first, second

    first, second = run(archive, service_key, body)
    assert first == second == tmp_path / "tiles" / f"{STEM}.tiff"
    assert first is not None and first.read_bytes() == b"TIFF"
    assert sum("/download/" in r.url.path for r in archive.requests) == 1
    assert not list((tmp_path / "tiles").glob("*.part"))


def test_the_same_tile_asked_twice_at_once_is_downloaded_once(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    """A map and a card ask for the same tile together (seen in the page of a Comune)."""
    archive = Archive()

    async def slow(request: httpx.Request) -> httpx.Response:
        # A download takes time: the second call arrives while the first streams.
        if "/download/" in request.url.path:
            await asyncio.sleep(0.05)
        return archive(request)

    async def main() -> list[Path | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            a = EgmsArchive(client, service_key, archive_url=ARCHIVE)
            return list(
                await asyncio.gather(
                    a.fetch_tile((47, 19), "U", "2020_2025", tmp_path),
                    a.fetch_tile((47, 19), "U", "2020_2025", tmp_path),
                )
            )

    first, second = asyncio.run(main())
    assert first == second == tmp_path / f"{STEM}.tiff"
    assert first is not None and first.read_bytes() == b"TIFF"
    assert sum("/download/" in r.url.path for r in archive.requests) == 1
    assert not list(tmp_path.glob("*.part"))


def test_a_tile_at_sea_is_remembered_as_absent(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()

    async def body(a: EgmsArchive) -> None:
        assert await a.fetch_tile((40, 15), "U", "2020_2025", tmp_path) is None
        assert await a.fetch_tile((40, 15), "U", "2020_2025", tmp_path) is None

    run(archive, service_key, body)
    assert sum(r.url.path.endswith("/search") for r in archive.requests) == 1
    assert (tmp_path / "EGMS_L3_E40N15_100km_U_2020_2025_absent").exists()


def test_a_404_download_is_absent_too(service_key: ServiceKey, tmp_path: Path) -> None:
    result = run(
        Archive(download_status=404),
        service_key,
        lambda a: a.fetch_tile((47, 19), "U", "2020_2025", tmp_path),
    )
    assert result is None
    assert (tmp_path / "EGMS_L3_E47N19_100km_U_2020_2025_absent").exists()


def test_an_expired_search_is_searched_again_once(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive(expired=1)
    path = run(archive, service_key, lambda a: a.fetch_tile((47, 19), "U", "2020_2025", tmp_path))
    assert path == tmp_path / f"{STEM}.tiff"
    paths = [r.url.path.rsplit("/", 1)[-1] for r in archive.requests]
    assert paths.count("search") == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{STEM}.tiff"]


def test_a_tile_keeps_other_files_of_its_zip(service_key: ServiceKey, tmp_path: Path) -> None:
    archive = Archive()

    async def body(a: EgmsArchive) -> tuple[Path | None, Path | None, Path | None]:
        only_tiff = await a.fetch_tile((47, 19), "U", "2020_2025", tmp_path)
        with_csv = await a.fetch_tile((47, 19), "U", "2020_2025", tmp_path, keep=("tiff", "csv"))
        again = await a.fetch_tile((47, 19), "U", "2020_2025", tmp_path, keep=["csv"])
        return only_tiff, with_csv, again

    only_tiff, with_csv, again = run(archive, service_key, body)
    assert only_tiff == with_csv == again == tmp_path / f"{STEM}.tiff"
    assert (tmp_path / f"{STEM}.csv").read_bytes() == b"series"
    # The GeoTIFF alone was not enough for the second call; the third asks nothing.
    assert sum("/download/" in r.url.path for r in archive.requests) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{STEM}.csv", f"{STEM}.tiff"]


def test_without_retries_a_busy_archive_says_its_status(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    async def body(client: httpx.AsyncClient) -> None:
        a = EgmsArchive(client, service_key, archive_url=ARCHIVE, retries=0)
        await a.fetch_tile((47, 19), "U", "2020_2025", tmp_path)

    async def main() -> None:
        transport = httpx.MockTransport(Archive(download_status=429))
        async with httpx.AsyncClient(transport=transport) as client:
            await body(client)

    with pytest.raises(EgmsError, match="HTTP 429") as refused:
        asyncio.run(main())
    assert refused.value.status_code == 429
    assert list(tmp_path.iterdir()) == []


def test_an_expired_search_raises_and_leaves_nothing(
    service_key: ServiceKey, tmp_path: Path
) -> None:
    with pytest.raises(EgmsError, match="HTTP 401"):
        run(
            Archive(download_status=401),
            service_key,
            lambda a: a.fetch_tile((47, 19), "U", "2020_2025", tmp_path),
        )
    assert list(tmp_path.iterdir()) == []


def test_a_search_without_hits_is_absent(service_key: ServiceKey, tmp_path: Path) -> None:
    class Empty(Archive):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"status": True, "hits": [], "id": "x"})
            return super().__call__(request)

    assert (
        run(Empty(), service_key, lambda a: a.fetch_tile((48, 19), "E", "2020_2025", tmp_path))
        is None
    )


def test_a_hit_for_another_tile_is_refused(service_key: ServiceKey, tmp_path: Path) -> None:
    class Wrong(Archive):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                body = json.loads((FIXTURES / "search_E47N19_U.json").read_text())
                body["hits"][0]["filename"] = "../EGMS_L3_E47N19_100km_U_2020_2025_1.zip"
                return httpx.Response(200, json=body)
            return super().__call__(request)

    with pytest.raises(EgmsError, match="unexpected file name"):
        run(Wrong(), service_key, lambda a: a.fetch_tile((47, 19), "U", "2020_2025", tmp_path))


def test_the_highest_cached_sub_release_wins(service_key: ServiceKey, tmp_path: Path) -> None:
    for sub in (9, 10):
        (tmp_path / f"EGMS_L3_E47N19_100km_U_2020_2025_{sub}.tiff").write_bytes(b"x")
    found = run(
        Archive(), service_key, lambda a: a.fetch_tile((47, 19), "U", "2020_2025", tmp_path)
    )
    assert found == tmp_path / "EGMS_L3_E47N19_100km_U_2020_2025_10.tiff"


class Forgetful(Archive):
    """An archive that answers "Please log in" to the first ``refusals`` calls."""

    def __init__(self, refusals: int) -> None:
        super().__init__()
        self.refusals = refusals

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("oauth2-token") and self.refusals:
            self.refusals -= 1
            self.requests.append(request)
            return httpx.Response(200, content=(FIXTURES / "not_logged_in.json").read_bytes())
        return super().__call__(request)


def test_a_valid_token_refused_once_is_renewed(service_key: ServiceKey) -> None:
    archive = Forgetful(refusals=1)
    assert run(archive, service_key, lambda a: a.releases()) == ["2020-2024", "2020-2025"]
    assert archive.tokens == 2
    assert archive.requests[-1].headers["Authorization"] == "Bearer t2"


def test_a_search_refused_once_is_sent_again(service_key: ServiceKey) -> None:
    archive = Forgetful(refusals=1)
    search = run(archive, service_key, lambda a: a.search((47, 19), "U", "2020-2025"))
    assert search is not None and archive.tokens == 2


def test_a_second_refusal_is_a_real_one(service_key: ServiceKey) -> None:
    archive = Forgetful(refusals=2)
    with pytest.raises(EgmsError, match="log in"):
        run(archive, service_key, lambda a: a.releases())
    assert archive.tokens == 2


def test_only_the_archive_refusal_counts_as_log_in() -> None:
    from egms_client.client import _asks_to_log_in

    assert _asks_to_log_in((FIXTURES / "not_logged_in.json").read_bytes())
    assert not _asks_to_log_in(b"<html>please log in</html>")
    assert not _asks_to_log_in(b'["log in"]')
    assert not _asks_to_log_in((FIXTURES / "releases.json").read_bytes())
