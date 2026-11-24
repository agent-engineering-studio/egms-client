"""demo/api.py: the API behind the page of a Comune, on the crops of the benchmark."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

pytest.importorskip("starlette")
pytest.importorskip("rasterio")

from starlette.testclient import TestClient

from egms_client import tile_id
from egms_client.mosaic import lonlat_to_laea

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "demo"))

import api  # noqa: E402
import boundaries  # noqa: E402

PRIVATE = "-----BEGIN PRIVATE KEY-----MARKER-NEVER-LOGGED-----END PRIVATE KEY-----"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """The page of Pozzuoli: its area holds the crop of the benchmark at Rione Terra."""
    monkeypatch.setattr(api, "default_directory", lambda: tmp_path)  # no boundaries here
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    monkeypatch.delenv("EGMS_UI_RADIUS_KM", raising=False)
    with TestClient(api.app) as c:
        yield c


@pytest.fixture
def bologna(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The page of a Comune near Bologna: its area holds the crop of the benchmark."""
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "11.425")
    monkeypatch.setenv("EGMS_UI_LAT", "44.55")
    monkeypatch.setenv("EGMS_UI_RADIUS_KM", "12")
    with TestClient(api.app) as c:
        yield c


def test_health_says_where_the_data_come_from_and_the_area(client: TestClient) -> None:
    answer = client.get("/api/health").json()
    assert answer["ok"] is True and answer["source"] == "demo"
    area = answer["area"]
    assert (area["lon"], area["lat"], area["radius_km"]) == (14.1205, 40.8225, 10.0)
    assert area["west"] < 14.1205 < area["east"] and area["south"] < 40.8225 < area["north"]


def test_a_place_in_italian_with_its_facts(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225}).json()
    vertical = answer["vertical"]
    assert vertical["facts"]["velocity_mm_per_year"] == 145.2
    assert vertical["facts"]["window"]["first"] == "2020-12-09"
    assert "+145,2 mm/anno" in vertical["text"]
    assert answer["east"] is None  # no east-west crop at Pozzuoli
    english = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225, "lang": "en"})
    assert "+145.2 mm/year" in english.json()["vertical"]["text"]


def test_outside_the_area_is_not_not_measured(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 9.19, "lat": 45.46})
    assert answer.status_code == 404
    assert answer.json()["not_measured"] is False
    assert "outside the area of this page" in answer.json()["error"]
    assert "not 'not measured'" in answer.json()["error"]
    far = {"west": 11.30, "south": 44.50, "east": 11.55, "north": 44.60}
    for path in ("/api/area", "/api/moving", "/api/map.png"):
        assert client.get(path, params=far).status_code == 404


def test_outside_the_demo_data_but_inside_the_area(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "9.19")
    monkeypatch.setenv("EGMS_UI_LAT", "45.46")
    with TestClient(api.app) as c:
        answer = c.get("/api/place", params={"lon": 9.19, "lat": 45.46})
    assert answer.status_code == 404
    assert "demo mode: no data loaded here" in answer.json()["error"]


def test_the_sea_is_not_measured(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 14.10, "lat": 40.80}).json()
    assert answer["vertical"]["facts"]["measured"] is False
    assert "non misurato" in answer["vertical"]["text"]


def test_area_moving_and_the_map(bologna: TestClient) -> None:
    box = {"west": 11.30, "south": 44.50, "east": 11.55, "north": 44.60}
    summary = bologna.get("/api/area", params=box).json()
    assert summary["facts"]["median"] == -6.3
    moving = bologna.get("/api/moving", params={**box, "threshold": 10}).json()
    assert moving["facts"]["moving"] > 0 and len(moving["facts"]["cells"]) <= 20
    png = bologna.get("/api/map.png", params=box)
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")


def test_bad_boxes_are_refused(client: TestClient) -> None:
    upside = client.get("/api/area", params={"west": 12, "south": 44, "east": 11, "north": 45})
    assert upside.status_code == 400
    wide = client.get("/api/area", params={"west": 10, "south": 44, "east": 12, "north": 45})
    assert "at most" in wide.json()["error"]
    assert client.get("/api/place", params={"lon": "x", "lat": 40}).status_code == 400


def test_the_picture_veils_what_is_not_measured() -> None:
    import numpy as np

    values = np.array([[-30.0, 0.0, 30.0, np.nan]], dtype="float32")
    rgba = api.picture(values, np.ones(values.shape, dtype=bool))
    assert tuple(rgba[0, 0, :3]) == api.COLOURS[0]
    assert tuple(rgba[0, 1, :3]) == api.COLOURS[4]
    assert tuple(rgba[0, 2, :3]) == api.COLOURS[-1]
    assert tuple(rgba[0, 3]) == api.VEIL


def test_the_key_never_reaches_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    key = {
        "client_id": "c",
        "user_id": "u",
        "private_key": PRIVATE,
        "token_uri": "https://example.invalid/token",
    }
    monkeypatch.delenv("EGMS_UI_SOURCE", raising=False)
    monkeypatch.setenv("EGMS_SERVICE_KEY", json.dumps(key))
    caplog.set_level(logging.DEBUG)
    with TestClient(api.app) as c:
        assert c.get("/api/health").json()["source"] == "archive"
        assert "MARKER" not in repr(c.app.state.source.archive)  # type: ignore[attr-defined]
        assert c.get("/api/place", params={"lon": "bad", "lat": 1}).status_code == 400
    assert "MARKER" not in caplog.text


def test_docker_never_copies_the_key() -> None:
    ignored = (ROOT / ".dockerignore").read_text().split()
    for secret in (".env", "secrets", "*service-key*.json"):
        assert secret in ignored


def test_env_example_names_every_setting_and_quotes_spaces() -> None:
    import re

    example = (ROOT / ".env.example").read_text()
    names = set(re.findall(r"^([A-Z_]+)=", example, re.M))
    used = set(re.findall(r"\$\{([A-Z_]+)", (ROOT / "compose.yaml").read_text()))
    for script in ("api.py", "admin.py"):
        text = (ROOT / "demo" / script).read_text()
        used |= set(re.findall(r"environ\.get\(\"([A-Z_]+)\"", text))
    for path in (ROOT / "demo" / "web").glob("**/*.ts*"):
        if "node_modules" not in path.parts and ".next" not in path.parts:
            used |= set(re.findall(r"(?:process\.)?env\.(EGMS_[A-Z_]+)", path.read_text()))
    # Set by compose itself: the address between two containers, and paths inside them.
    used -= {"EGMS_UI_API", "EGMS_UI_INCOMING", "EGMS_UI_STATE", "EGMS_UI_RECORDS"}
    assert used - names == set()
    for line in example.splitlines():
        if re.match(r"^[A-Z_]+=", line):
            value = line.split("=", 1)[1]
            assert " " not in value or (value.startswith('"') and value.endswith('"')), line


def test_an_unexpected_error_is_json_for_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    with TestClient(api.app, raise_server_exceptions=False) as c:
        monkeypatch.setattr(c.app.state.source, "tiffs", broken)  # type: ignore[attr-defined]
        answer = c.get("/api/place", params={"lon": 14.1205, "lat": 40.8225})
    assert answer.status_code == 500
    assert answer.json() == {"error": "the server could not answer (RuntimeError); try again"}


# --- Records of open data, next to EGMS -----------------------------------------


def test_the_sources_of_the_example_records(client: TestClient) -> None:
    answer = client.get("/api/sources").json()
    assert answer["egms"] == "demo"
    assert answer["refused"] == []
    names = {s["name"]: s for s in answer["sources"]}
    gauge = names["simulated rain gauge"]
    assert gauge["records"] == 4
    assert gauge["licence"] == "CC0-1.0"
    assert gauge["properties"] == ["rainfall"]
    assert gauge["files"] == ["rain-gauge-simulated.jsonl"]
    assert "rainfall-thresholds" in {m for s in answer["sources"] for m in s["made_by"]}


def test_the_records_in_a_box(client: TestClient) -> None:
    box = {"west": 14.10, "south": 40.81, "east": 14.14, "north": 40.84}
    found = client.get("/api/records", params=box).json()["records"]
    files = {item["file"] for item in found}
    assert "rain-gauge-simulated.jsonl" in files
    assert "egms-pozzuoli-layer.json" in files  # a polygon that covers the box
    assert "egms-bologna-area.json" not in files
    bad = client.get("/api/records", params={**box, "east": 14.0})
    assert bad.status_code == 400


def test_a_place_gives_its_records_too(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225}).json()
    [record] = answer["vertical"]["records"]
    assert record["value"] == 145.2
    assert record["unit"] == "mm/a"


def test_an_invalid_file_is_refused_whole_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = json.loads((ROOT / "examples" / "records" / "egms-rione-terra.json").read_text())
    (tmp_path / "good.json").write_text(json.dumps(good))
    (tmp_path / "zero.json").write_text(json.dumps([good, good | {"value": float("nan")}]))
    (tmp_path / "broken.jsonl").write_text("{")
    (tmp_path / "notes.txt").write_text("not a record file")
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setattr(api, "RECORDS", [tmp_path, tmp_path / "missing"])
    with TestClient(api.app) as c:
        answer = c.get("/api/sources").json()
        assert [s["records"] for s in answer["sources"]] == [1]
        refused = {r["file"]: r["problems"] for r in answer["refused"]}
        assert refused["zero.json"] == [
            "zero.json #1: value: nan is not a value; write null when it is not measured"
        ]
        assert refused["broken.jsonl"][0].startswith("not JSON")
        # A new file is read at the next request.
        (tmp_path / "more.json").write_text(json.dumps(good))
        assert [s["records"] for s in c.get("/api/sources").json()["sources"]] == [2]


def test_the_bounds_of_every_shape() -> None:
    assert api.bounds({"type": "Point", "coordinates": [14.1, 40.8]}) == (14.1, 40.8, 14.1, 40.8)
    square = [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]]
    assert api.bounds({"type": "Polygon", "coordinates": square}) == (0, 0, 2, 1)
    two = [square, [[[5, 5], [6, 5], [6, 7], [5, 7], [5, 5]]]]
    assert api.bounds({"type": "MultiPolygon", "coordinates": two}) == (0, 0, 6, 7)


# --- The tiles of the place, at startup ------------------------------------------


def test_the_place_of_the_page_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    assert api._place_from_env() == (14.1205, 40.8225)
    monkeypatch.setenv("EGMS_UI_LAT", "")
    assert api._place_from_env() is None  # half a place is a mistake
    monkeypatch.setenv("EGMS_UI_LON", "")
    assert api._place_from_env() == api.DEFAULT_PLACE  # the page opens there too
    monkeypatch.setenv("EGMS_UI_LON", "14,1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40,8225")
    assert api._place_from_env() == (14.1205, 40.8225)
    monkeypatch.setenv("EGMS_UI_LAT", "10")  # outside EGMS
    assert api._place_from_env() is None


def test_prefetch_asks_both_components_and_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    import asyncio

    from egms_client import EgmsError

    asked: list[str] = []

    class Fake:
        async def tiffs(
            self, box: tuple[float, ...], component: str, wait: float | None = None
        ) -> None:
            asked.append(component)

    class Broken:
        async def tiffs(
            self, box: tuple[float, ...], component: str, wait: float | None = None
        ) -> None:
            raise EgmsError("the archive is busy")

    class Late:
        """The archive answers U, then fails E once, then answers."""

        failed = False

        async def tiffs(
            self, box: tuple[float, ...], component: str, wait: float | None = None
        ) -> None:
            asked.append(component)
            if component == "E" and not self.failed:
                self.failed = True
                raise EgmsError("ConnectTimeout")

    with caplog.at_level(logging.INFO, logger="egms-client.api"):
        area = api.Area(14.12, 40.82, 10)
        assert asyncio.run(api.prefetch(Fake(), area))  # type: ignore[arg-type]
        assert not asyncio.run(api.prefetch(Broken(), area, wait=0, tries=3))  # type: ignore[arg-type]
        assert asked == ["U", "E"]
        asked.clear()
        assert asyncio.run(api.prefetch(Late(), area, wait=0))  # type: ignore[arg-type]
    assert asked == ["U", "E", "E"]  # U is not asked again
    assert "are ready" in caplog.text and "the archive is busy" in caplog.text
    assert "(attempt 3)" in caplog.text and "trying again" in caplog.text


def test_startup_prefetches_only_in_archive_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[tuple[float, str]] = []

    async def offline(*_: object, **__: object) -> Path:
        raise httpx.ConnectError("no network in the tests")

    monkeypatch.setattr(boundaries, "fetch", offline)

    class FakeArchive(api.Archive):
        def __init__(self) -> None:
            self.name = "archive"
            self.folder = tmp_path

        async def tiffs(self, box: tuple[float, ...], component: str, wait: float | None = None):  # type: ignore[no-untyped-def]
            started.append((box[0], component))
            return [], "2020-2025", []

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(api, "source_from_env", FakeArchive)
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    with TestClient(api.app) as c:
        c.get("/api/health")
    assert [component for _, component in started] == ["U", "E"]


# --- The area of the page -----------------------------------------------------------


def test_the_area_is_a_box_of_the_radius() -> None:
    area = api.Area(14.1205, 40.8225, 10)
    west, south, east, north = area.box
    assert round((north - south) * 111.32 / 2, 2) == 10.0
    assert round((east - west) * 111.32 * math.cos(math.radians(40.8225)) / 2, 1) == 10.0
    assert area.contains(14.1205, 40.8225) and not area.contains(14.5, 40.8225)
    assert area.clip((14.0, 40.7, 15.0, 41.0)) == (west, south, east, north)
    assert area.clip((14.1, 40.8, 14.2, 40.85)) == (14.1, 40.8, 14.2, 40.85)
    with pytest.raises(api.OutsideAreaError, match=r"10 km around 14\.1205, 40\.8225"):
        area.clip((15.0, 41.0, 15.1, 41.1))


def test_the_area_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EGMS_UI_LON", raising=False)
    monkeypatch.delenv("EGMS_UI_LAT", raising=False)
    monkeypatch.delenv("EGMS_UI_RADIUS_KM", raising=False)
    assert api.area_from_env() == api.Area(14.1205, 40.8225, 10.0)  # Pozzuoli
    monkeypatch.setenv("EGMS_UI_RADIUS_KM", "5,5")
    assert api.area_from_env().radius_km == 5.5
    monkeypatch.setenv("EGMS_UI_RADIUS_KM", "50")
    with pytest.raises(ValueError, match="between 1 and 20"):
        api.area_from_env()
    monkeypatch.setenv("EGMS_UI_RADIUS_KM", "")
    monkeypatch.setenv("EGMS_UI_LON", "14.1")
    with pytest.raises(ValueError, match="both"):
        api.area_from_env()


def test_the_widest_area_fits_one_map(monkeypatch: pytest.MonkeyPatch) -> None:
    west, south, east, north = api.Area(14.1, 60.0, api.MAX_RADIUS_KM).box
    assert east - west <= api.MAX_DEGREES and north - south <= api.MAX_DEGREES


def test_a_point_near_the_edge_reads_no_tile_beyond_it() -> None:
    area = api.Area(14.1205, 40.8225, 2)
    from egms_client.mosaic import lonlat_to_laea

    inner = lonlat_to_laea(*area.box)
    cut = api._inside(api._around(14.1205, 40.8225), area)
    assert cut == inner  # 5 km around the centre is wider than the area: cut to it


# --- An archive that does not answer must not stop the page --------------------------


def _archive_with(releases: object) -> api.Archive:
    source = object.__new__(api.Archive)
    source.archive = type("A", (), {"releases": releases})()
    source.release, source.confirmed, source.retry_at = None, False, 0.0
    source.confirming = None
    return source


def test_a_silent_archive_never_holds_an_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from egms_client.releases import KNOWN_RELEASES

    monkeypatch.setattr(api, "ARCHIVE_WAIT_S", 0.05)

    async def silent(self: object) -> list[str]:
        await asyncio.sleep(10)
        return []

    async def listed(self: object) -> list[str]:
        return ["2020-2024", "2020-2026"]

    async def run() -> None:
        source = _archive_with(silent)
        # At once: the latest known release, while the archive is asked.
        assert await asyncio.wait_for(source.latest(), 0.01) == KNOWN_RELEASES[-1]
        await asyncio.sleep(0.1)
        assert not source.confirmed and source.retry_at > 0
        source.archive = type("A", (), {"releases": listed})()
        await source.latest()  # not asked again yet
        await asyncio.sleep(0.01)
        assert source.release == KNOWN_RELEASES[-1]
        source.retry_at = 0.0
        await source.latest()  # asked again, and it answers
        await asyncio.sleep(0.01)
        assert source.release == "2020-2026" and source.confirmed
        assert await source.latest() == "2020-2026"

    with caplog.at_level(logging.INFO, logger="egms-client.api"):
        asyncio.run(run())
    assert "TimeoutError" in caplog.text and "the latest known" in caplog.text
    assert "using it from now on" in caplog.text


# --- A tile not on the disk yet -------------------------------------------------------


def _archive(fetch: Any) -> api.Archive:
    """An Archive whose release is known and whose downloads are ``fetch``."""
    source = object.__new__(api.Archive)
    source.release, source.confirmed, source.retry_at = "2020-2025", True, 0.0
    source.confirming, source.downloads, source.folder = None, {}, Path("/nowhere")
    source.why, source.status = "", {}
    source.archive = type("Fake", (), {"fetch_tile": staticmethod(fetch)})()
    return source


def test_an_answer_waits_a_little_and_the_download_goes_on() -> None:
    finished: list[str] = []

    async def slow(tile: Any, component: str, release: str, folder: Path, **_: Any) -> Path:
        await asyncio.sleep(0.2)
        finished.append(tile_id(tile))
        return Path(f"/{tile_id(tile)}.tiff")

    async def run() -> None:
        source = _archive(slow)
        box = lonlat_to_laea(16.90, 40.79, 16.95, 40.81)
        with pytest.raises(api.MissingTilesError, match="downloading") as caught:
            await source.tiffs(box, "U", wait=0.01)
        assert caught.value.tiles == ["E49N19"]
        await asyncio.sleep(0.3)  # the download went on without the answer
        assert finished == ["E49N19"]
        tiffs, _, absent = await source.tiffs(box, "U", wait=0.01)
        assert [t.name for t in tiffs] == ["E49N19.tiff"] and absent == []

    asyncio.run(run())


def test_an_archive_that_does_not_answer_is_said_not_hidden() -> None:
    async def down(tile: Any, component: str, release: str, folder: Path, **_: Any) -> Path:
        raise httpx.ConnectTimeout("")

    async def run() -> None:
        source = _archive(down)
        box = lonlat_to_laea(16.90, 40.79, 16.95, 40.81)
        with pytest.raises(api.MissingTilesError, match="did not answer: ConnectTimeout"):
            await source.tiffs(box, "U", wait=1)

    asyncio.run(run())


def test_missing_tiles_are_a_503_not_not_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(*_: object, **__: object) -> None:
        raise api.MissingTilesError(["E48N20"], "downloading from the EGMS archive")

    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    with TestClient(api.app) as c:
        monkeypatch.setattr(c.app.state.source, "tiffs", missing)  # type: ignore[attr-defined]
        answer = c.get("/api/place", params={"lon": 14.1205, "lat": 40.8225})
    assert answer.status_code == 503 and answer.headers["retry-after"] == "60"
    body = answer.json()
    assert body["missing_tiles"] == ["E48N20"] and body["not_measured"] is False


@pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")
def test_the_map_draws_the_tiles_it_has_and_stripes_the_others() -> None:
    from rasterio.io import MemoryFile

    crop = sorted((ROOT / "benchmarks" / "data" / "murge").glob("U.tif"))
    box = (16.80, 40.80, 17.04, 40.89)  # Gioia del Colle: E48N19, E49N19 and, north, N20
    whole = api._png(box, crop)
    striped = api._png(box, crop, ["E48N20", "E49N20"])
    with MemoryFile(whole) as a, MemoryFile(striped) as b, a.open() as pa, b.open() as pb:
        before, after = pa.read(), pb.read()
    grey = np.all(np.moveaxis(after, 0, -1) == api.STRIPES, axis=-1)
    assert grey[:5].any() and not grey[-5:].any()  # stripes in the north only
    assert (before[:, -5:] == after[:, -5:]).all()  # the south is the same map


def test_available_lists_what_is_missing_without_raising() -> None:
    async def some(tile: Any, component: str, release: str, folder: Path, **_: Any) -> Path:
        if tile_id(tile).endswith("N20"):
            raise httpx.ConnectTimeout("")
        return Path(f"/{tile_id(tile)}.tiff")

    async def run() -> None:
        source = _archive(some)
        box = lonlat_to_laea(16.80, 40.80, 17.04, 40.89)
        tiffs, _, absent, missing = await source.available(box, "U", wait=1)
        assert sorted(t.name for t in tiffs) == ["E48N19.tiff", "E49N19.tiff"]
        assert absent == [] and sorted(missing) == ["E48N20", "E49N20"]
        with pytest.raises(api.MissingTilesError, match="ConnectTimeout"):
            await source.tiffs(box, "U", wait=1)

    asyncio.run(run())


def test_data_gaps_are_squares_with_few_measured_cells() -> None:
    crop = [ROOT / "benchmarks" / "data" / "murge" / "U.tif"]
    g = api.gaps(crop, lonlat_to_laea(16.85, 40.72, 17.0, 40.85))
    share, west, north = g.share, g.west, g.north
    assert west % api.BLOCK_M == 0 and north % api.BLOCK_M == 0
    known = share[~np.isnan(share)]
    assert known.size > 100 and 0 < (known < api.GAP_SHARE).mean() < 0.5
    # Not known is not a gap: outside the crop the squares are NaN.
    outside = api.gaps(crop, lonlat_to_laea(17.2, 40.9, 17.25, 40.95)).share
    assert np.isnan(outside).all()
    assert api._gap_at(crop, 16.9625, 40.7839) == {
        "block_m": 1000,
        "measured_share": 0.6,
        "gap": False,
    }


def test_the_gaps_of_the_area_and_of_a_point(client: TestClient) -> None:
    g = client.get(
        "/api/gaps", params={"west": 14.0, "south": 40.75, "east": 14.25, "north": 40.9}
    ).json()
    assert g["block_m"] == 1000 and g["gap_below"] == api.GAP_SHARE
    assert g["blocks"] > 0 and 0 <= g["gaps"] <= g["blocks"] and g["missing_tiles"] == []
    place = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225}).json()
    assert place["gap"]["gap"] is False and place["gap"]["measured_share"] >= api.GAP_SHARE


def test_the_startup_reports_the_progress_of_the_download() -> None:
    gate = asyncio.Event()

    async def fetch(tile: Any, component: str, release: str, folder: Path, **kw: Any) -> Path:
        kw["on_progress"](None, 30, 60)  # half of the tile
        await gate.wait()
        return Path(f"/{tile_id(tile)}-{component}.tiff")

    async def run() -> None:
        source = _archive(fetch)
        area = api.Area(14.1205, 40.8225, 10)
        startup = api.Startup(source, area)
        assert startup.as_json()["state"] == "running" and startup.as_json()["share"] == 0
        task = asyncio.create_task(api.prefetch(source, area, startup=startup))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if startup.as_json()["share"] == 0.5:
                break
        now = startup.as_json()
        assert not now["ready"] and now["share"] == 0.5
        assert {(t["tile"], t["component"], t["state"]) for t in now["tiles"]} == {
            ("E46N19", "U", "downloading"),
            ("E46N19", "E", "downloading"),
        }
        gate.set()
        assert await task
        assert startup.as_json() | {"tiles": []} == {
            "state": "ready",
            "ready": True,
            "share": 1.0,
            "attempt": 1,
            "error": None,
            "retry_in_s": None,
            "boundaries": None,
            "tiles": [],
        }

    asyncio.run(run())


def test_a_failed_startup_says_when_it_tries_again() -> None:
    async def down(tile: Any, component: str, release: str, folder: Path, **_: Any) -> Path:
        raise httpx.ConnectTimeout("")

    async def run() -> None:
        source = _archive(down)
        area = api.Area(14.1205, 40.8225, 10)
        startup = api.Startup(source, area)
        task = asyncio.create_task(api.prefetch(source, area, wait=30, startup=startup))
        for _ in range(200):  # until the attempt has failed, whatever the speed of the machine
            await asyncio.sleep(0.01)
            if startup.state == "waiting":
                break
        now = startup.as_json()
        assert now["state"] == "waiting" and 0 < now["retry_in_s"] <= 30
        assert "ConnectTimeout" in now["error"]
        assert {t["state"] for t in now["tiles"]} == {"failed"}
        task.cancel()

    asyncio.run(run())


def test_demo_mode_needs_no_loading(client: TestClient) -> None:
    startup = client.get("/api/health").json()["startup"]
    assert startup["ready"] is True and startup["share"] == 1.0


def test_a_startup_that_waits_too_long_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _archive(None)
    startup = api.Startup(source, api.Area(14.1205, 40.8225, 10))
    assert startup.as_json()["state"] == "running"
    monkeypatch.setattr(api, "STARTUP_PATIENCE_S", -1)
    now = startup.as_json()
    assert now["state"] == "slow" and "does not answer" in now["error"]


# --- The boundaries of ISTAT: gaps on land only --------------------------------------


def _comune_file(folder: Path) -> Path:
    """A shapefile like ISTAT's with one Comune: a rectangle of land near Rione Terra."""
    import shapefile
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", boundaries.CRS, always_xy=True)
    corners = [(14.08, 40.81), (14.08, 40.86), (14.16, 40.86), (14.16, 40.81), (14.08, 40.81)]
    ring = [list(to_utm.transform(lon, lat)) for lon, lat in corners]
    shp = boundaries.path(folder)
    shp.parent.mkdir(parents=True)
    with shapefile.Writer(str(shp.with_suffix("")), shapeType=shapefile.POLYGON) as w:
        w.field("PRO_COM_T", "C")
        w.field("COMUNE", "C")
        w.poly([ring])
        w.record("063060", "Pozzuoli")
    return shp


def test_the_comune_of_a_point(tmp_path: Path) -> None:
    shp = _comune_file(tmp_path)
    comuni = boundaries.comuni_in(shp, (14.0, 40.7, 14.3, 40.9))
    assert [c.name for c in comuni] == ["Pozzuoli"]
    assert boundaries.at(comuni, 14.1205, 40.8225) == comuni[0]
    assert boundaries.at(comuni, 14.10, 40.79) is None  # in the sea, south of it
    assert boundaries.comuni_in(shp, (9.0, 45.0, 9.1, 45.1)) == []
    outline = boundaries.lonlat(comuni[0].geometry)
    assert outline["type"] == "Polygon" and abs(outline["coordinates"][0][0][0] - 14.08) < 1e-4


def test_with_the_boundaries_the_sea_is_not_a_gap(tmp_path: Path) -> None:
    crop = [ROOT / "benchmarks" / "data" / "campi-flegrei" / "U.tif"]
    box = lonlat_to_laea(14.05, 40.78, 14.18, 40.87)
    comuni = boundaries.comuni_in(_comune_file(tmp_path), (14.0, 40.7, 14.3, 40.9))
    plain = api.gaps(crop, box)
    masked = api.gaps(crop, box, comuni, comuni[0])
    assert plain.land is None and masked.land is not None
    known = ~np.isnan(masked.share)
    # Fewer squares are counted: those mostly outside the Comune (the sea) are not.
    assert 0 < known.sum() < (~np.isnan(plain.share)).sum()
    assert masked.home is not None and masked.home[known].all()


def test_the_gaps_of_the_comune_and_its_outline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _comune_file(tmp_path)
    monkeypatch.setattr(api, "default_directory", lambda: tmp_path)
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    monkeypatch.setenv("EGMS_UI_LON", "14.1205")
    monkeypatch.setenv("EGMS_UI_LAT", "40.8225")
    with TestClient(api.app) as c:
        health = c.get("/api/health").json()["startup"]
        assert health["ready"] and health["boundaries"]["comune"] == "Pozzuoli"
        box = {"west": 14.05, "south": 40.78, "east": 14.18, "north": 40.87}
        g = c.get("/api/gaps", params=box).json()
        assert g["land_only"] is True and g["comune"]["name"] == "Pozzuoli"
        assert g["comune"]["blocks"] <= g["blocks"] and "ISTAT" in g["boundaries"]
        outline = c.get("/api/boundary").json()
        assert outline["properties"]["name"] == "Pozzuoli"
        assert outline["geometry"]["type"] == "Polygon"


def test_without_the_boundaries_the_page_still_counts(client: TestClient) -> None:
    g = client.get(
        "/api/gaps", params={"west": 14.05, "south": 40.78, "east": 14.18, "north": 40.87}
    )
    assert g.json()["land_only"] is False and g.json()["comune"] is None
    assert client.get("/api/boundary").status_code == 404


# --- Where the ground moves most ---------------------------------------------------


def test_the_squares_that_move_most_are_ranked() -> None:
    crop = [ROOT / "benchmarks" / "data" / "campi-flegrei" / "U.tif"]
    found = api.hotspots(crop, lonlat_to_laea(*api.Area(14.1205, 40.8225, 10).box))
    assert 0 < len(found) <= api.HOT_TOP
    assert [h["rank"] for h in found] == list(range(1, len(found) + 1))
    medians = [abs(h["median_mm_per_year"]) for h in found]
    assert medians == sorted(medians, reverse=True) and medians[-1] >= api.HOT_MIN
    top = found[0]
    # The caldera rises: the first square is near Rione Terra, going up by > 100 mm a year.
    assert top["median_mm_per_year"] > 100 and abs(top["lon"] - 14.12) < 0.03
    assert top["measured_share"] >= api.GAP_SHARE and len(top["square"]) == 5


def test_a_still_area_has_no_squares_to_follow() -> None:
    crop = [ROOT / "benchmarks" / "data" / "murge" / "U.tif"]
    assert api.hotspots(crop, lonlat_to_laea(16.85, 40.72, 17.0, 40.85)) == []


def test_the_hotspots_of_the_page(client: TestClient) -> None:
    answer = client.get("/api/hotspots").json()
    assert answer["component"] == "U" and answer["at_least_mm_per_year"] == api.HOT_MIN
    assert answer["squares"] and "not an alert" in answer["note"]
