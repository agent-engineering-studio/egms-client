"""Records of open data: one shape for every source the application reads.

A record is a JSON object valid against ``schema/opendata-record-v1.json``.
It is an ``observation`` (one value at one place and time), a ``fact`` (an
answer already computed) or a ``layer`` (a map). Every record says its
source, licence, time window, place and how far to trust it.

The schema is the contract between sources. A library, an IoT gateway or a
CSV from a municipality writes records; the application reads records. No
source imports another.

Some rules a JSON Schema cannot say. :func:`problems` checks them too:

* not measured is ``null``, never 0 or NaN;
* a signed property (a velocity, a displacement) says what its sign means;
* the time window does not end before it starts;
* nothing is an alert or a risk.

Validation needs the extra ``records`` (``jsonschema``).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

SCHEMA = "opendata-record/v1"

#: The reason a source gives when a place has no measurement.
NOT_MEASURED = "not_measured"

#: Properties whose sign carries meaning: they need ``meaning``.
SIGNED = frozenset({"velocity", "displacement", "acceleration", "tilt", "water_level_change"})

#: Words a record may not use as a name: a record is a measurement, not a warning.
NOT_A_RECORD = ("alert", "alarm", "warning", "risk", "allerta", "allarme", "rischio")


#: The fields that belong to one kind only (the schema says the same).
ONLY = {
    "observation": frozenset({"value", "quality"}),
    "fact": frozenset({"question", "values"}),
    "layer": frozenset({"href", "media_type", "no_data"}),
}


class RecordError(ValueError):
    """A record is not valid against opendata-record/v1. ``problems`` says why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@cache
def schema() -> dict[str, Any]:
    """The JSON Schema of opendata-record/v1."""
    text = files("egms_client").joinpath("schema/opendata-record-v1.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


@cache
def _validator() -> Any:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ImportError(
            "checking records needs jsonschema: pip install 'egms-client[records]'"
        ) from exc
    return Draft202012Validator(schema())


def problems(record: Any) -> list[str]:
    """Everything wrong with one record, as short sentences; empty if it is valid."""
    if not isinstance(record, dict):
        return ["record: a record is a JSON object"]
    found = _schema_errors(record)
    if found and any(f.startswith(("schema:", "kind:")) for f in found):
        return found
    found += _fields(record)
    found += _numbers(record)
    found += _sign(record)
    found += _not_measured(record)
    found += _time(record)
    found += _names(record)
    return found


def validate(record: Any) -> dict[str, Any]:
    """Return the record if it is valid; raise :class:`RecordError` if not."""
    found = problems(record)
    if found:
        raise RecordError(found)
    return dict(record)


def read(path: str | Path) -> list[dict[str, Any]]:
    """The records in a file: one object, a list of objects, or JSON Lines (``.jsonl``).

    Every record is validated; the first file with an invalid one raises
    :class:`RecordError`, with the position of the record in the file.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        loaded: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
    items = loaded if isinstance(loaded, list) else [loaded]
    out = []
    for i, item in enumerate(items):
        found = problems(item)
        if found:
            raise RecordError([f"{path.name} #{i}: {p}" for p in found])
        out.append(item)
    return out


def _schema_errors(record: Any) -> list[str]:
    found = []
    for error in _validator().iter_errors(record):
        for e in _closest(error):
            place = "/".join(str(p) for p in e.absolute_path) or "record"
            # A field of another kind: jsonschema loses its name, so _fields says it.
            if not e.message.startswith("False schema"):
                found.append(f"{place}: {e.message}")
    return found


def _fields(record: dict[str, Any]) -> list[str]:
    kind = record.get("kind")
    return [
        f"{name}: not part of a record of kind {kind}"
        for other, names in ONLY.items()
        if other != kind
        for name in sorted(names - ONLY.get(str(kind), frozenset()))
        if name in record
    ]


def _closest(error: Any) -> list[Any]:
    """The errors of the branch the record meant, when a oneOf (time, where) fails."""
    if not error.context:
        return [error]
    branches: dict[Any, list[Any]] = {}
    for e in error.context:
        branches.setdefault(e.schema_path[0], []).append(e)

    def other_shape(errors: list[Any]) -> bool:
        return any(
            (e.validator == "type" and not e.relative_path)
            or (e.validator == "const" and list(e.relative_path) == ["type"])
            or (e.validator == "additionalProperties" and not e.relative_path)
            for e in errors
        )

    meant = [errs for errs in branches.values() if not other_shape(errs)]
    return min(meant, key=len) if meant else [error]


def _quantities(record: dict[str, Any]) -> list[tuple[str, Any]]:
    if record.get("kind") == "fact" and isinstance(record.get("values"), dict):
        return [
            (f"values/{name}", q.get("value"))
            for name, q in record["values"].items()
            if isinstance(q, dict)
        ]
    return [("value", record["value"])] if "value" in record else []


def _numbers(record: dict[str, Any]) -> list[str]:
    return [
        f"{name}: {value} is not a value; write null when it is not measured"
        for name, value in _quantities(record)
        if isinstance(value, float) and not math.isfinite(value)
    ]


def _sign(record: dict[str, Any]) -> list[str]:
    prop = record.get("property")
    if prop in SIGNED and not record.get("meaning"):
        return [f"meaning: a {prop} has a sign; say what it means, e.g. 'positive = up'"]
    return []


def _not_measured(record: dict[str, Any]) -> list[str]:
    reliability = record.get("reliability")
    reasons = reliability.get("reasons", []) if isinstance(reliability, dict) else []
    if NOT_MEASURED not in reasons:
        return []
    return [
        f"{name}: the source says {NOT_MEASURED}, so the value is null, not {value}"
        for name, value in _quantities(record)
        if value is not None
    ]


def _time(record: dict[str, Any]) -> list[str]:
    time = record.get("time")
    if not isinstance(time, dict):
        return []
    if "instant" in time:
        try:
            moment = datetime.fromisoformat(str(time["instant"]))
        except ValueError:
            return [f"time/instant: {time['instant']!r} is not an ISO 8601 date and time"]
        return [] if moment.tzinfo else ["time/instant: give the time zone (use UTC)"]
    try:
        first = date.fromisoformat(str(time.get("first"))[:10])
        last = date.fromisoformat(str(time.get("last"))[:10])
    except ValueError:
        return ["time: first and last are ISO 8601 dates"]
    return [f"time: the window ends ({last}) before it starts ({first})"] if last < first else []


def _names(record: dict[str, Any]) -> list[str]:
    names = [str(record.get("property", ""))]
    if isinstance(record.get("values"), dict):
        names += list(record["values"])
    return [
        f"{name}: a record is a measurement, not a warning; '{word}' is not allowed"
        for name in names
        for word in NOT_A_RECORD
        if word in name.lower()
    ]
