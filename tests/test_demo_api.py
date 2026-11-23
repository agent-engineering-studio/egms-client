"""demo/api.py: the API behind the page of a Comune, on the crops of the benchmark."""

from __future__ import annotations

import json
import logging
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
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    with TestClient(api.app) as c:
        yield c


def test_health_says_where_the_data_come_from(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True, "source": "demo"}


def test_a_place_in_italian_with_its_facts(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225}).json()
    vertical = answer["vertical"]
    assert vertical["facts"]["velocity_mm_per_year"] == 145.2
    assert vertical["facts"]["window"]["first"] == "2020-12-09"
    assert "+145,2 mm/anno" in vertical["text"]
    assert answer["east"] is None  # no east-west crop at Pozzuoli
    english = client.get("/api/place", params={"lon": 14.1205, "lat": 40.8225, "lang": "en"})
    assert "+145.2 mm/year" in english.json()["vertical"]["text"]


def test_outside_the_demo_data_is_not_not_measured(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 9.19, "lat": 45.46})
    assert answer.status_code == 404
    assert answer.json()["not_measured"] is False
    assert "not 'not measured'" in answer.json()["error"]


def test_the_sea_is_not_measured(client: TestClient) -> None:
    answer = client.get("/api/place", params={"lon": 14.10, "lat": 40.80}).json()
    assert answer["vertical"]["facts"]["measured"] is False
    assert "non misurato" in answer["vertical"]["text"]


def test_area_moving_and_the_map(client: TestClient) -> None:
    box = {"west": 11.30, "south": 44.50, "east": 11.55, "north": 44.60}
    summary = client.get("/api/area", params=box).json()
    assert summary["facts"]["median"] == -6.3
    moving = client.get("/api/moving", params={**box, "threshold": 10}).json()
    assert moving["facts"]["moving"] > 0 and len(moving["facts"]["cells"]) <= 20
    png = client.get("/api/map.png", params=box)
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
    used |= set(re.findall(r"environ\.get\(\"([A-Z_]+)\"", (ROOT / "demo" / "api.py").read_text()))
    for path in (ROOT / "demo" / "web").glob("**/*.ts*"):
        if "node_modules" not in path.parts and ".next" not in path.parts:
            used |= set(re.findall(r"(?:process\.)?env\.(EGMS_[A-Z_]+)", path.read_text()))
    used.discard("EGMS_UI_API")  # set by compose itself, between two containers
    assert used - names == set()
    for line in example.splitlines():
        if re.match(r"^[A-Z_]+=", line):
            value = line.split("=", 1)[1]
            assert " " not in value or (value.startswith('"') and value.endswith('"')), line
