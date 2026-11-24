"""demo/api.py: the API behind the page of a Comune, on the crops of the benchmark."""

from __future__ import annotations

import json
import logging
import math
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("rasterio")

from starlette.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "demo"))

import api  # noqa: E402

PRIVATE = "-----BEGIN PRIVATE KEY-----MARKER-NEVER-LOGGED-----END PRIVATE KEY-----"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The page of Pozzuoli: its area holds the crop of the benchmark at Rione Terra."""
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
        async def tiffs(self, box: tuple[float, ...], component: str) -> None:
            asked.append(component)

    class Broken:
        async def tiffs(self, box: tuple[float, ...], component: str) -> None:
            raise EgmsError("the archive is busy")

    with caplog.at_level(logging.INFO, logger="egms-client.api"):
        area = api.Area(14.12, 40.82, 10)
        asyncio.run(api.prefetch(Fake(), area))  # type: ignore[arg-type]
        asyncio.run(api.prefetch(Broken(), area))  # type: ignore[arg-type]
    assert asked == ["U", "E"]
    assert "are ready" in caplog.text and "the archive is busy" in caplog.text


def test_startup_prefetches_only_in_archive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[float, str]] = []

    class FakeArchive(api.Archive):
        def __init__(self) -> None:
            self.name = "archive"

        async def tiffs(self, box: tuple[float, ...], component: str):  # type: ignore[no-untyped-def]
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
    assert api.area_from_env() == api.Area(16.9233, 40.7996, 10.0)  # Gioia del Colle
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
    import asyncio

    source = object.__new__(api.Archive)
    source.archive = type("A", (), {"releases": releases})()
    source.release, source.confirmed, source.retry_at = None, False, 0.0
    source.lock = asyncio.Lock()
    return source


def test_a_silent_archive_falls_back_to_the_latest_known_release(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    from egms_client.releases import KNOWN_RELEASES

    monkeypatch.setattr(api, "ARCHIVE_WAIT_S", 0.05)

    async def silent(self: object) -> list[str]:
        await asyncio.sleep(10)
        return []

    source = _archive_with(silent)
    with caplog.at_level(logging.WARNING, logger="egms-client.api"):
        assert asyncio.run(source.latest()) == KNOWN_RELEASES[-1]
    assert "TimeoutError" in caplog.text and "the latest known" in caplog.text
    assert not source.confirmed and source.retry_at > 0

    async def listed(self: object) -> list[str]:
        return ["2020-2024", "2020-2026"]

    source.archive = type("A", (), {"releases": listed})()
    assert asyncio.run(source.latest()) == KNOWN_RELEASES[-1]  # not asked again yet
    source.retry_at = 0.0
    assert asyncio.run(source.latest()) == "2020-2026"  # asked again, and it answered
    assert source.confirmed
