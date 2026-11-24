"""Sensors that send their readings to the page, and the files they fill.

The back office (demo/admin.py) registers a sensor: its id, what it measures,
where it is, the source and licence to credit, and a token. The token is
shown once and kept only as a SHA-256 hash. The API (demo/api.py) takes the
readings at ``POST /api/ingest/{id}``, with ``Authorization: Bearer TOKEN``,
as SenML (RFC 8428, the shape of Limen's v2 sensors) or as records, and
appends them, as records, to one JSON Lines file per sensor and day.

    [{"bn": "pluvio-01/", "bt": 1792065600, "n": "rainfall", "u": "mm", "v": 0.4}]

A reading is refused, with its reason, when its name is not
``{id}/{property}``, its unit is not the sensor's, its time is more than ten
minutes ahead, or its value is outside the range of the sensor. The last
refusals of each sensor are kept for the back office. Nothing here raises an
alert: a reading is a measurement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from egms_client.records import SCHEMA, problems

#: The id of a sensor: lowercase letters, digits and dashes, as in Limen.
SENSOR_ID = re.compile(r"\A[a-z0-9][a-z0-9-]{2,62}\Z")
#: A body larger than this is refused.
MAX_BODY = 64 * 1024
#: Requests one sensor may make in a minute.
PER_MINUTE = 60
#: A reading this far ahead of the clock is refused, in seconds.
AHEAD = 600
#: Refusals kept per sensor, for the back office.
KEEP_REFUSED = 50
#: RFC 8428 4.5.3: a time under 2**28 seconds is relative to now.
RELATIVE = 2**28


@dataclass
class Sensor:
    """A sensor the back office registered. ``token`` is the SHA-256 of the token."""

    id: str
    source: str
    licence: str
    property: str
    unit: str
    lon: float
    lat: float
    token: str
    label: str = ""
    meaning: str = ""
    low: float | None = None
    high: float | None = None
    active: bool = True
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


class Registry:
    """The sensors, in one JSON file written by the back office and read by the API."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.seen: int | None = None
        self.sensors: dict[str, Sensor] = {}

    def load(self) -> dict[str, Sensor]:
        try:
            stamp = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self.sensors, self.seen = {}, None
            return self.sensors
        if stamp != self.seen:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.sensors = {s["id"]: Sensor(**s) for s in raw}
            self.seen = stamp
        return self.sensors

    def save(self, sensors: dict[str, Sensor]) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix(".partial")
            partial.write_text(
                json.dumps([asdict(s) for s in sensors.values()], indent=2), encoding="utf-8"
            )
            partial.chmod(0o600)
            partial.replace(self.path)
        self.seen = None

    def check(self, sensor_id: str, token: str) -> Sensor | None:
        """The sensor if the token is its own and it is active; None otherwise."""
        sensor = self.load().get(sensor_id)
        if sensor is None or not sensor.active:
            # Compare anyway: the time does not tell which ids exist.
            hmac.compare_digest(token_hash(token), "0" * 64)
            return None
        return sensor if hmac.compare_digest(token_hash(token), sensor.token) else None


class Pace:
    """At most ``PER_MINUTE`` requests a minute for each sensor."""

    def __init__(self, per_minute: int = PER_MINUTE) -> None:
        self.per_minute = per_minute
        self.calls: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        recent = [t for t in self.calls.get(key, []) if now - t < 60]
        if len(recent) >= self.per_minute:
            self.calls[key] = recent
            return False
        self.calls[key] = [*recent, now]
        return True


def record(sensor: Sensor, when: datetime, value: float | None, flags: list[str]) -> dict[str, Any]:
    """One reading of a sensor as an observation of opendata-record/v1."""
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "observation",
        "id": f"{sensor.id}-{when.strftime('%Y%m%dT%H%M%SZ')}",
        "source": {"name": sensor.source, "licence": sensor.licence},
        "made_by": {"name": sensor.id},
        "thing": sensor.id,
        "time": {"instant": when.isoformat(timespec="seconds").replace("+00:00", "Z")},
        "where": {"type": "Point", "coordinates": [sensor.lon, sensor.lat]},
        "property": sensor.property,
        "value": value,
        "unit": sensor.unit,
        "quality": {"flags": flags},
        "reliability": None
        if value is not None
        else {"method": "the sensor sent no value", "reasons": ["not_measured"]},
    }
    if sensor.label:
        out["label"] = sensor.label
    if sensor.meaning:
        out["meaning"] = sensor.meaning
    return out


def from_senml(
    sensor: Sensor, pack: Any, now: float | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """The records of a SenML pack, and the reasons for the readings refused.

    Only the subset Limen uses: ``bn``, ``bt``, ``n``, ``u``, ``v``, ``t``.
    A name other than the sensor's property (such as ``seq``) is skipped.
    """
    now = time.time() if now is None else now
    if not isinstance(pack, list) or not pack:
        return [], ["SenML is a non-empty JSON array"]
    out, refused = [], []
    base_name, base_time = "", 0.0
    for i, item in enumerate(pack):
        if not isinstance(item, dict):
            refused.append(f"#{i}: not an object")
            continue
        base_name = item.get("bn", base_name)
        base_time = float(item.get("bt", base_time))
        name = f"{base_name}{item.get('n', '')}"
        sensor_name, _, prop = name.rpartition("/")
        if not prop or prop != sensor.property:
            continue
        if sensor_name != sensor.id:
            refused.append(f"#{i}: the name {name!r} is not {sensor.id}/{sensor.property}")
            continue
        unit = item.get("u", sensor.unit)
        if unit != sensor.unit:
            refused.append(f"#{i}: unit {unit!r}, the sensor sends {sensor.unit!r}")
            continue
        moment = base_time + float(item.get("t", 0))
        if moment < RELATIVE:
            moment += now
        if moment > now + AHEAD:
            refused.append(f"#{i}: the time is ahead of the clock")
            continue
        value = item.get("v")
        if value is not None and (not isinstance(value, int | float) or not math.isfinite(value)):
            refused.append(f"#{i}: the value {value!r} is not a number")
            continue
        flags = ["ok"]
        if value is not None and (
            (sensor.low is not None and value < sensor.low)
            or (sensor.high is not None and value > sensor.high)
        ):
            refused.append(f"#{i}: {value} is outside the range of the sensor")
            continue
        if value is None:
            flags = ["gap"]
        out.append(record(sensor, datetime.fromtimestamp(moment, UTC), value, flags))
    return out, refused


def from_records(sensor: Sensor, body: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Records sent as they are: valid, and of this sensor (``thing``) only."""
    items = body if isinstance(body, list) else [body]
    out, refused = [], []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            refused.append(f"#{i}: not an object")
            continue
        item = {**item, "thing": item.get("thing", sensor.id)}
        if item["thing"] != sensor.id:
            refused.append(f"#{i}: thing {item['thing']!r} is not this sensor")
            continue
        found = problems(item)
        if found:
            refused.append(f"#{i}: {found[0]}")
            continue
        out.append(item)
    return out, refused


def read_body(
    sensor: Sensor, body: Any, now: float | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """SenML, or records (objects with ``schema``)."""
    looks_like_records = isinstance(body, dict) or (
        isinstance(body, list) and body and isinstance(body[0], dict) and "schema" in body[0]
    )
    if looks_like_records:
        return from_records(sensor, body)
    records, refused = from_senml(sensor, body, now)
    # Every record leaves here valid: the same check as any file.
    valid = []
    for r in records:
        found = problems(r)
        if found:
            refused.append(f"{r['id']}: {found[0]}")
        else:
            valid.append(r)
    return valid, refused


def append(folder: Path, sensor: Sensor, records: list[dict[str, Any]]) -> None:
    """One JSON Lines file per sensor and day, appended."""
    folder.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[str]] = {}
    for r in records:
        day = r["time"]["instant"][:10] if "instant" in r["time"] else "undated"
        by_day.setdefault(day, []).append(json.dumps(r, ensure_ascii=False))
    for day, lines in by_day.items():
        with (folder / f"{sensor.id}-{day}.jsonl").open("a", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")


def remember_refused(folder: Path, sensor_id: str, reasons: list[str]) -> None:
    """The last refusals of a sensor, for the back office (not read as records)."""
    if not reasons:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sensor_id}.refused"
    old = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    new = [json.dumps({"time": stamp, "reason": r}) for r in reasons]
    path.write_text("\n".join([*old, *new][-KEEP_REFUSED:]) + "\n", encoding="utf-8")
