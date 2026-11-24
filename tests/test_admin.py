"""demo/admin.py and demo/sensors.py: the back office, and the readings of sensors."""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("multipart")
pytest.importorskip("rasterio")

from starlette.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "demo"))

import admin  # noqa: E402
import api  # noqa: E402
import sensors  # noqa: E402

PASSWORD = "una password lunga per la prova"
HASH = admin.hash_password(PASSWORD)
GOOD = (ROOT / "examples" / "records" / "egms-rione-terra.json").read_bytes()


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    incoming, state = tmp_path / "incoming", tmp_path / "state"
    monkeypatch.setattr(admin, "INCOMING", incoming)
    monkeypatch.setattr(admin, "STATE", state)
    monkeypatch.setattr(admin, "RECORDS", [ROOT / "examples" / "records"])
    monkeypatch.setattr(api, "INCOMING", incoming)
    monkeypatch.setattr(api, "SENSORS", state / "sensors.json")
    monkeypatch.setenv("EGMS_ADMIN_USER", "ente")
    monkeypatch.setenv("EGMS_ADMIN_PASSWORD_HASH", HASH)
    monkeypatch.setenv("EGMS_UI_SOURCE", "demo")
    return incoming, state


@pytest.fixture
def office(folders: tuple[Path, Path]) -> Iterator[TestClient]:
    with TestClient(admin.make_app(), base_url="http://testserver") as c:
        yield c


def _sign_in(c: TestClient) -> str:
    answer = c.post("/accedi", data={"user": "ente", "password": PASSWORD}, follow_redirects=True)
    assert answer.status_code == 200
    return _csrf(answer.text)


def _csrf(text: str) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', text)
    assert found
    return found.group(1)


# --- Passwords and login ---------------------------------------------------------


def test_a_password_hash_checks_only_its_password() -> None:
    assert HASH.startswith("scrypt:") and "$" not in HASH
    assert admin.check_password(PASSWORD, HASH)
    assert not admin.check_password("un'altra", HASH)
    assert not admin.check_password(PASSWORD, "bcrypt:1:2:3:aa:bb")
    assert not admin.check_password(PASSWORD, "not a hash")
    assert admin.hash_password(PASSWORD) != HASH  # a new salt each time


def test_without_the_administrator_it_is_off(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EGMS_ADMIN_PASSWORD_HASH")
    with TestClient(admin.make_app()) as c:
        for answer in (c.get("/accedi"), c.post("/accedi", data={}), c.get("/")):
            assert answer.status_code == 503
            assert "Backoffice spento" in answer.text


def test_every_page_asks_to_sign_in(office: TestClient) -> None:
    for path in ("/", "/carica", "/sensori", "/registro"):
        answer = office.get(path, follow_redirects=False)
        assert answer.status_code == 303
        assert answer.headers["location"] == "/accedi"
    assert office.get("/health").text == "ok"


def test_signing_in_sets_a_strict_cookie(office: TestClient) -> None:
    answer = office.post(
        "/accedi", data={"user": "ente", "password": PASSWORD}, follow_redirects=False
    )
    assert answer.status_code == 303
    cookie = answer.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie  # plain HTTP on this machine
    page = office.get("/")
    assert "Fonti" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_a_cookie_behind_https_is_secure(office: TestClient) -> None:
    answer = office.post(
        "/accedi",
        data={"user": "ente", "password": PASSWORD},
        headers={"x-forwarded-proto": "https"},
        follow_redirects=False,
    )
    assert "secure" in answer.headers["set-cookie"].lower()


def test_wrong_passwords_lock_the_address(office: TestClient, folders: tuple[Path, Path]) -> None:
    for _ in range(admin.TRIES):
        assert office.post("/accedi", data={"user": "ente", "password": "no"}).status_code == 401
    assert office.post("/accedi", data={"user": "ente", "password": PASSWORD}).status_code == 429
    assert office.post("/accedi", data={"user": "altro", "password": PASSWORD}).status_code == 429
    log = (folders[1] / "log.jsonl").read_text()
    assert "accesso fallito" in log and "accesso bloccato" in log
    assert PASSWORD not in log


def test_the_lock_ends(office: TestClient) -> None:
    guard: admin.Guard = office.app.state.guard  # type: ignore[attr-defined]
    guard.failures["testclient"] = [time.time() - admin.LOCK_MINUTES * 60 - 1] * admin.TRIES
    assert not guard.locked("testclient")


def test_a_wrong_user_is_refused(office: TestClient) -> None:
    assert office.post("/accedi", data={"user": "altro", "password": PASSWORD}).status_code == 401


def test_signing_out_ends_the_session(office: TestClient) -> None:
    csrf = _sign_in(office)
    assert office.post("/esci", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert office.get("/", follow_redirects=False).status_code == 303


def test_a_form_without_its_token_is_refused(office: TestClient) -> None:
    _sign_in(office)
    answer = office.post("/esci", data={"csrf": "forged"})
    assert answer.status_code == 403
    assert office.get("/").status_code == 200  # still signed in


def test_an_expired_session_asks_again(office: TestClient) -> None:
    _sign_in(office)
    guard: admin.Guard = office.app.state.guard  # type: ignore[attr-defined]
    for s in guard.sessions.values():
        s["expires"] = 0
    assert office.get("/", follow_redirects=False).status_code == 303


# --- Files ----------------------------------------------------------------------


def test_a_valid_file_is_shown_then_saved(office: TestClient, folders: tuple[Path, Path]) -> None:
    csrf = _sign_in(office)
    shown = office.post("/carica", data={"csrf": csrf}, files={"file": ("Rione Terra.json", GOOD)})
    assert shown.status_code == 200
    assert "1 record validi" in shown.text
    assert not (folders[0] / "uploads").exists()  # nothing saved yet
    key = re.search(r'name="key" value="([^"]+)"', shown.text)
    assert key
    saved = office.post(
        "/carica/salva", data={"csrf": csrf, "key": key.group(1)}, follow_redirects=True
    )
    assert (folders[0] / "uploads" / "rione-terra.json").read_bytes() == GOOD
    assert "rione-terra.json" in saved.text and "letto" in saved.text
    # The same name again does not overwrite.
    again = office.post("/carica", data={"csrf": csrf}, files={"file": ("rione-terra.json", GOOD)})
    key = re.search(r'name="key" value="([^"]+)"', again.text)
    assert key
    office.post("/carica/salva", data={"csrf": csrf, "key": key.group(1)})
    assert (folders[0] / "uploads" / "rione-terra-2.json").exists()
    assert "file caricato" in office.get("/registro").text
    # A key is used once.
    assert office.post("/carica/salva", data={"csrf": csrf, "key": key.group(1)}).status_code == 403


def test_an_invalid_file_says_why_and_is_not_saved(
    office: TestClient, folders: tuple[Path, Path]
) -> None:
    csrf = _sign_in(office)
    bad = json.dumps(json.loads(GOOD) | {"property": "frana_rischio"}).encode()
    answer = office.post("/carica", data={"csrf": csrf}, files={"file": ("bad.json", bad)})
    assert answer.status_code == 400
    assert "rischio" in answer.text and "non è stato salvato" in answer.text
    assert not list((folders[1] / "pending").glob("*"))
    wrong = office.post("/carica", data={"csrf": csrf}, files={"file": ("a.txt", b"x")})
    assert wrong.status_code == 400
    broken = office.post("/carica", data={"csrf": csrf}, files={"file": ("a.json", b"{")})
    assert broken.status_code == 400
    assert office.post("/carica", data={"csrf": csrf}).status_code == 403


def test_a_large_file_is_refused(office: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "MAX_UPLOAD", 10)
    csrf = _sign_in(office)
    assert (
        office.post("/carica", data={"csrf": csrf}, files={"file": ("a.json", GOOD)}).status_code
        == 413
    )


def test_files_are_listed_and_only_incoming_ones_deleted(
    office: TestClient, folders: tuple[Path, Path]
) -> None:
    uploads = folders[0] / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "mine.json").write_bytes(GOOD)
    (uploads / "bad.json").write_text("{")
    (uploads / "zero.json").write_text(json.dumps(json.loads(GOOD) | {"unit": ""}))
    csrf = _sign_in(office)
    page = office.get("/").text
    assert "mine.json" in page and "rifiutato" in page and "sola lettura" in page
    assert "egms-rione-terra.json" in page  # the examples, read-only
    for folder, name in (
        ("records", "egms-rione-terra.json"),
        ("uploads", "../x.json"),
        ("uploads", ".hidden.json"),
    ):
        answer = office.post("/file/elimina", data={"csrf": csrf, "folder": folder, "name": name})
        assert answer.status_code == 403
    office.post("/file/elimina", data={"csrf": csrf, "folder": "uploads", "name": "mine.json"})
    assert not (uploads / "mine.json").exists()


def test_old_pending_files_are_cleared(office: TestClient, folders: tuple[Path, Path]) -> None:
    csrf = _sign_in(office)
    office.post("/carica", data={"csrf": csrf}, files={"file": ("a.json", GOOD)})
    guard: admin.Guard = office.app.state.guard  # type: ignore[attr-defined]
    [(key, (path, name, _))] = guard.pending.items()
    guard.pending[key] = (path, name, 0.0)
    office.post("/carica", data={"csrf": csrf}, files={"file": ("b.json", GOOD)})
    assert not path.exists() and key not in guard.pending


# --- Sensors ---------------------------------------------------------------------

SENSOR = {
    "id": "pluvio-01",
    "source": "Pluviometro del Comune",
    "licence": "CC BY 4.0",
    "property": "rainfall",
    "unit": "mm",
    "label": "Pioggia",
    "meaning": "",
    "lon": "14,1262",
    "lat": "40.8262",
    "low": "0",
    "high": "200",
}


def _create(office: TestClient, csrf: str) -> str:
    answer = office.post("/sensori", data={"csrf": csrf, **SENSOR})
    assert answer.status_code == 200
    token = re.search(r'<div class="token">([^<]+)</div>', answer.text)
    assert token
    assert "api/ingest/pluvio-01" in answer.text
    return token.group(1)


def test_a_sensor_sends_readings_with_its_token(
    office: TestClient, folders: tuple[Path, Path]
) -> None:
    csrf = _sign_in(office)
    token = _create(office, csrf)
    stored = json.loads((folders[1] / "sensors.json").read_text())
    assert stored[0]["token"] == sensors.token_hash(token)
    assert token not in (folders[1] / "sensors.json").read_text()
    assert token not in (folders[1] / "log.jsonl").read_text()
    with TestClient(api.app) as public:
        pack = [
            {"bn": "pluvio-01/", "bt": time.time() - 60, "n": "rainfall", "u": "mm", "v": 0.4},
            {"n": "rainfall", "t": 30, "v": 300},
            {"n": "seq", "v": 7},
        ]
        answer = public.post(
            "/api/ingest/pluvio-01", json=pack, headers={"Authorization": f"Bearer {token}"}
        )
        assert answer.status_code == 202
        assert answer.json()["accepted"] == 1
        assert "outside the range" in answer.json()["refused"][0]
        found = public.get("/api/sources").json()["sources"]
        assert {"Pluviometro del Comune"} <= {s["name"] for s in found}
        wrong = public.post(
            "/api/ingest/pluvio-01", json=pack, headers={"Authorization": "Bearer nope"}
        )
        assert wrong.status_code == 401
        nobody = public.post(
            "/api/ingest/nobody-01", json=pack, headers={"Authorization": f"Bearer {token}"}
        )
        assert nobody.status_code == 401
    page = office.get("/sensori").text
    assert "0.4 mm" in page and "outside the range" in page


def test_a_sensor_can_be_turned_off_given_a_new_token_and_removed(
    office: TestClient, folders: tuple[Path, Path]
) -> None:
    csrf = _sign_in(office)
    old = _create(office, csrf)
    pack = [{"bn": "pluvio-01/", "n": "rainfall", "u": "mm", "v": 1.0}]
    with TestClient(api.app) as public:
        office.post("/sensori/pluvio-01/stato", data={"csrf": csrf})
        off = public.post(
            "/api/ingest/pluvio-01", json=pack, headers={"Authorization": f"Bearer {old}"}
        )
        assert off.status_code == 401
        office.post("/sensori/pluvio-01/stato", data={"csrf": csrf})
        renewed = office.post("/sensori/pluvio-01/token", data={"csrf": csrf})
        new = re.search(r'<div class="token">([^<]+)</div>', renewed.text)
        assert new
        assert (
            public.post(
                "/api/ingest/pluvio-01", json=pack, headers={"Authorization": f"Bearer {old}"}
            ).status_code
            == 401
        )
        assert (
            public.post(
                "/api/ingest/pluvio-01",
                json=pack,
                headers={"Authorization": f"Bearer {new.group(1)}"},
            ).status_code
            == 202
        )
    assert office.post("/sensori/pluvio-01/rompi", data={"csrf": csrf}).status_code == 403
    office.post("/sensori/pluvio-01/elimina", data={"csrf": csrf})
    assert "Nessun sensore" in office.get("/sensori").text
    assert office.post("/sensori/pluvio-01/stato", data={"csrf": csrf}).status_code == 403
    log = office.get("/registro").text
    for action in (
        "sensore creato",
        "sensore spento",
        "sensore acceso",
        "nuovo token",
        "sensore eliminato",
    ):
        assert action in log


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"id": "No"}, "id non valido"),
        ({"property": "Pioggia!"}, "grandezza non valida"),
        ({"unit": ""}, "fonte, licenza e unità"),
        ({"lon": "est"}, "non è un numero"),
        ({"lat": "95"}, "fuori dai limiti"),
    ],
)
def test_a_wrong_sensor_is_refused(office: TestClient, change: dict[str, str], reason: str) -> None:
    csrf = _sign_in(office)
    answer = office.post("/sensori", data={"csrf": csrf, **SENSOR, **change})
    assert answer.status_code == 403
    assert reason in answer.text


def test_an_id_is_used_once(office: TestClient) -> None:
    csrf = _sign_in(office)
    _create(office, csrf)
    assert office.post("/sensori", data={"csrf": csrf, **SENSOR}).status_code == 403


# --- The endpoint, on its own ------------------------------------------------------


def _sensor(**changes: object) -> sensors.Sensor:
    base = sensors.Sensor(
        id="pluvio-01",
        source="P",
        licence="CC0-1.0",
        property="rainfall",
        unit="mm",
        lon=14.1,
        lat=40.8,
        token=sensors.token_hash("t"),
        label="Pioggia",
        low=0,
        high=200,
    )
    for k, v in changes.items():
        setattr(base, k, v)
    return base


def test_senml_becomes_valid_records() -> None:
    now = 1_792_065_600.0
    records, refused = sensors.read_body(
        _sensor(meaning="no sign"),
        [
            {"bn": "pluvio-01/", "bt": now - 600, "n": "rainfall", "u": "mm", "v": 0.4},
            {"n": "rainfall", "t": 300},
            {"n": "rainfall", "bt": -5, "v": 1.0},
        ],
        now=now,
    )
    assert refused == []
    assert [r["value"] for r in records] == [0.4, None, 1.0]
    assert records[0]["time"] == {"instant": "2026-10-15T11:50:00Z"}
    assert records[1]["quality"] == {"flags": ["gap"]}
    assert records[1]["reliability"]["reasons"] == ["not_measured"]
    assert records[2]["time"] == {"instant": "2026-10-15T11:59:55Z"}  # relative to now
    assert records[0]["label"] == "Pioggia" and records[0]["meaning"] == "no sign"


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        ({"bn": "altro-01/", "n": "rainfall", "v": 1}, "is not pluvio-01/rainfall"),
        ({"bn": "pluvio-01/", "n": "rainfall", "u": "m", "v": 1}, "unit 'm'"),
        (
            {"bn": "pluvio-01/", "bt": 1_792_065_600 + 3600, "n": "rainfall", "v": 1},
            "ahead of the clock",
        ),
        ({"bn": "pluvio-01/", "n": "rainfall", "v": "tanta"}, "is not a number"),
        ({"bn": "pluvio-01/", "n": "rainfall", "v": -1}, "outside the range"),
        ("x", "not an object"),
    ],
)
def test_senml_refusals_say_why(item: object, reason: str) -> None:
    records, refused = sensors.read_body(_sensor(), [item], now=1_792_065_600.0)
    assert records == []
    assert reason in refused[0]


def test_records_can_be_sent_as_they_are() -> None:
    template = json.loads(
        (ROOT / "demo" / "web" / "public" / "templates" / "record.json").read_text()
    )
    rain = [r for r in template if r.get("thing") == "pluvio-01"]
    records, refused = sensors.read_body(_sensor(), rain)
    assert len(records) == 2 and refused == []
    other, refused = sensors.read_body(
        _sensor(), [rain[0] | {"thing": "altro"}, "x", rain[0] | {"unit": ""}]
    )
    assert other == [] and len(refused) == 3
    one, _ = sensors.read_body(_sensor(), {k: v for k, v in rain[0].items() if k != "thing"})
    assert one[0]["thing"] == "pluvio-01"


def test_a_pack_that_is_not_senml() -> None:
    assert sensors.read_body(_sensor(), [])[1] == ["SenML is a non-empty JSON array"]
    assert sensors.read_body(_sensor(), 5)[1] == ["SenML is a non-empty JSON array"]


def test_the_pace_of_a_sensor() -> None:
    pace = sensors.Pace(per_minute=2)
    assert pace.allow("a", 0) and pace.allow("a", 1)
    assert not pace.allow("a", 2)
    assert pace.allow("a", 61) and pace.allow("b", 2)


def test_the_endpoint_refuses_what_it_cannot_take(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = sensors.Registry(folders[1] / "sensors.json")
    registry.save({"pluvio-01": _sensor()})
    auth = {"Authorization": "Bearer t"}
    with TestClient(api.app) as public:
        assert public.post("/api/ingest/pluvio-01", content=b"{", headers=auth).status_code == 400
        big = b"[" + b" " * sensors.MAX_BODY + b"]"
        assert public.post("/api/ingest/pluvio-01", content=big, headers=auth).status_code == 413
        assert (
            public.post(
                "/api/ingest/pluvio-01", json=[], headers={"Authorization": "Basic t"}
            ).status_code
            == 401
        )
        assert public.get("/api/ingest/pluvio-01").status_code == 405
        public.app.state.pace = sensors.Pace(per_minute=0)  # type: ignore[attr-defined]
        assert public.post("/api/ingest/pluvio-01", json=[], headers=auth).status_code == 429
    monkeypatch.setattr(api, "INCOMING", None)
    with TestClient(api.app) as public:
        assert public.post("/api/ingest/pluvio-01", json=[], headers=auth).status_code == 404


def test_a_body_larger_than_it_says_is_refused(folders: tuple[Path, Path]) -> None:
    sensors.Registry(folders[1] / "sensors.json").save({"pluvio-01": _sensor()})
    with TestClient(api.app) as public:
        big = b"[" + b" " * sensors.MAX_BODY + b"]"
        answer = public.post(
            "/api/ingest/pluvio-01",
            content=iter([big]),
            headers={"Authorization": "Bearer t", "content-type": "application/json"},
        )
        assert answer.status_code == 413


def test_the_registry_reads_again_when_the_file_changes(tmp_path: Path) -> None:
    registry = sensors.Registry(tmp_path / "s.json")
    assert registry.load() == {}
    assert registry.check("pluvio-01", "t") is None
    registry.save({"pluvio-01": _sensor()})
    assert registry.check("pluvio-01", "t") is not None
    assert registry.check("pluvio-01", "x") is None
    assert (tmp_path / "s.json").stat().st_mode & 0o777 == 0o600


def test_refusals_keep_the_last_ones(tmp_path: Path) -> None:
    sensors.remember_refused(tmp_path, "s", [])
    assert not (tmp_path / "s.refused").exists()
    sensors.remember_refused(tmp_path, "s", [str(i) for i in range(sensors.KEEP_REFUSED + 5)])
    lines = (tmp_path / "s.refused").read_text().splitlines()
    assert len(lines) == sensors.KEEP_REFUSED and json.loads(lines[-1])["reason"] == str(
        sensors.KEEP_REFUSED + 4
    )
