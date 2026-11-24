from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from egms_client import cli
from egms_client.records import RecordError, problems, read, schema, validate

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "records"


def _observation(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": "opendata-record/v1",
        "kind": "observation",
        "source": {"name": "a source", "licence": "CC0-1.0"},
        "made_by": {"name": "a test"},
        "time": {"first": "2020-12-09", "last": "2025-11-19", "exact": True},
        "where": {"type": "Point", "coordinates": [14.1205, 40.8225]},
        "reliability": None,
        "property": "velocity",
        "value": 145.2,
        "unit": "mm/a",
        "meaning": "vertical; positive = up",
    }
    record.update(changes)
    return record


def _fact(**changes: Any) -> dict[str, Any]:
    record = _observation(
        kind="fact",
        question="how much rain is enough",
        values={"cumulated": {"value": 27.1, "unit": "mm"}},
    )
    for name in ("property", "value", "unit", "meaning"):
        del record[name]
    record.update(changes)
    return record


def test_the_schema_is_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(schema())
    assert schema()["title"] == "opendata-record/v1"


@pytest.mark.parametrize("path", sorted(EXAMPLES.iterdir()), ids=lambda p: p.name)
def test_every_example_is_valid(path: Path) -> None:
    assert read(path)


def test_the_examples_cover_every_kind_and_a_missing_value() -> None:
    records = [r for p in sorted(EXAMPLES.iterdir()) for r in read(p)]
    assert {r["kind"] for r in records} == {"observation", "fact", "layer"}
    assert any(r.get("value", 0) is None for r in records)


def test_a_valid_record_has_no_problems() -> None:
    assert problems(_observation()) == []
    assert problems(_fact()) == []
    assert validate(_observation()) == _observation()


def test_not_measured_is_null_not_zero() -> None:
    reasons = {"method": "a method", "reasons": ["not_measured"]}
    assert problems(_observation(value=None, reliability=reasons)) == []
    assert problems(_observation(value=0.0, reliability=reasons)) == [
        "value: the source says not_measured, so the value is null, not 0.0"
    ]
    fact = _fact(reliability=reasons)
    assert problems(fact) == [
        "values/cumulated: the source says not_measured, so the value is null, not 27.1"
    ]


def test_nan_is_not_a_value() -> None:
    assert problems(_observation(value=float("nan"))) == [
        "value: nan is not a value; write null when it is not measured"
    ]


def test_a_signed_property_says_what_its_sign_means() -> None:
    record = _observation()
    del record["meaning"]
    assert problems(record) == [
        "meaning: a velocity has a sign; say what it means, e.g. 'positive = up'"
    ]
    rain = _observation(property="rainfall", unit="mm")
    del rain["meaning"]
    assert problems(rain) == []


def test_nothing_is_an_alert_or_a_risk() -> None:
    assert problems(_observation(property="landslide_risk")) == [
        "landslide_risk: a record is a measurement, not a warning; 'risk' is not allowed"
    ]
    fact = _fact(values={"livello_allerta": {"value": 2, "unit": "1"}})
    assert problems(fact) == [
        "livello_allerta: a record is a measurement, not a warning; 'allerta' is not allowed"
    ]
    assert problems(_observation(alert=True)) == [
        "record: Additional properties are not allowed ('alert' was unexpected)"
    ]


def test_the_time_window_runs_forward() -> None:
    late = _observation(time={"first": "2025-01-01", "last": "2024-01-01", "exact": True})
    assert problems(late) == ["time: the window ends (2024-01-01) before it starts (2025-01-01)"]
    wrong = _observation(time={"first": "2025-13-01", "last": "2025-12-01", "exact": True})
    assert problems(wrong) == ["time: first and last are ISO 8601 dates"]


def test_an_instant_has_a_time_zone() -> None:
    assert problems(_observation(time={"instant": "2026-10-15T12:00:00Z"})) == []
    assert problems(_observation(time={"instant": "2026-10-15T12:00:00"})) == [
        "time/instant: give the time zone (use UTC)"
    ]
    assert problems(_observation(time={"instant": "yesterday"})) == [
        "time/instant: 'yesterday' is not an ISO 8601 date and time"
    ]


def test_a_source_may_give_no_dates() -> None:
    assert problems(_fact(time=None)) == []


def test_the_message_names_the_shape_the_record_meant() -> None:
    half = _observation(time={"first": "2020-12-09"})
    assert problems(half)[:2] == [
        "time: 'last' is a required property",
        "time: 'exact' is a required property",
    ]
    far = _observation(where={"type": "Point", "coordinates": [200, 0]})
    assert problems(far) == ["where/coordinates/0: 200 is greater than the maximum of 180"]
    assert problems(_observation(reliability={"reasons": []})) == [
        "reliability: 'method' is a required property"
    ]
    assert problems(_observation(time=5)) == ["time: 5 is not valid under any of the given schemas"]


def test_a_field_of_another_kind_is_named() -> None:
    assert problems(_observation(question="why", href="a.tif")) == [
        "question: not part of a record of kind observation",
        "href: not part of a record of kind observation",
    ]


def test_a_record_of_no_known_kind_stops_at_the_schema() -> None:
    assert problems({"kind": "x"})[-1] == (
        "kind: 'x' is not one of ['observation', 'fact', 'layer']"
    )
    assert problems([]) == ["record: a record is a JSON object"]


def test_validate_raises_with_every_problem() -> None:
    record = _observation(value=float("inf"), property="flood_risk")
    with pytest.raises(RecordError) as caught:
        validate(record)
    assert len(caught.value.problems) == 2


def test_read_takes_one_record_a_list_or_json_lines(tmp_path: Path) -> None:
    one, many, lines = tmp_path / "one.json", tmp_path / "many.json", tmp_path / "l.jsonl"
    one.write_text(json.dumps(_observation()))
    many.write_text(json.dumps([_observation(), _fact()]))
    lines.write_text(json.dumps(_observation()) + "\n\n" + json.dumps(_fact()) + "\n")
    assert [len(read(p)) for p in (one, many, lines)] == [1, 2, 2]


def test_read_says_which_record_is_wrong(tmp_path: Path) -> None:
    bad = copy.deepcopy(_observation())
    del bad["source"]
    path = tmp_path / "two.json"
    path.write_text(json.dumps([_observation(), bad]))
    with pytest.raises(RecordError, match=r"two.json #1: record: 'source' is a required"):
        read(path)


def test_the_command_checks_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = EXAMPLES / "egms-rione-terra.json"
    bad, broken = tmp_path / "bad.json", tmp_path / "broken.json"
    bad.write_text(json.dumps(_observation(value=float("nan"))))
    broken.write_text("{")
    assert cli.main(["records", str(good)]) == 0
    assert cli.main(["records", str(good), str(bad), str(broken)]) == 1
    out = capsys.readouterr().out
    assert "egms-rione-terra.json: 1 record(s), valid" in out
    assert "bad.json: bad.json #0: value: nan is not a value" in out
    assert "broken.json: Expecting property name" in out


# --- egms facts as records (egms_client.facts.to_records) -----------------------

DATA = Path(__file__).resolve().parent.parent / "benchmarks" / "data"
FLEGREI = DATA / "campi-flegrei" / "U.tif"
SEA = (14.10, 40.785, 14.12, 40.795)  # the Gulf of Pozzuoli, inside the crop: no cell has a value


def test_the_egms_examples_are_what_to_records_gives() -> None:
    from egms_client import __version__
    from scripts.example_records import OUT, made, text

    for name, records in made().items():
        assert {r["made_by"]["version"] for r in records} == {__version__}
        for r in records:
            r["made_by"]["version"] = "X"
        written = json.loads((OUT / name).read_text(encoding="utf-8"))
        for r in written if isinstance(written, list) else [written]:
            r["made_by"]["version"] = "X"
        assert json.loads(text(records)) == written, name


def test_every_record_of_every_answer_is_valid() -> None:
    from egms_client.facts import area, moving_points, to_records, velocity

    answers = [
        velocity([FLEGREI], 14.1205, 40.8225, release="2020-2025"),
        velocity([FLEGREI], 14.09, 40.785, release="2020-2025"),
        area([FLEGREI], SEA, release="2020-2025"),
        moving_points([FLEGREI], SEA, release="2020-2025"),
        area([FLEGREI], (14.10, 40.81, 14.14, 40.83), release="2020-2025"),
        moving_points([FLEGREI], (14.10, 40.81, 14.14, 40.83), release="2020-2025"),
    ]
    for facts in answers:
        for record in to_records(facts):
            assert problems(record) == [], record["id"]


def test_a_box_with_no_value_gives_null_and_the_reason() -> None:
    from egms_client.facts import area, moving_points, to_records

    for facts in (
        area([FLEGREI], SEA, release="2020-2025"),
        moving_points([FLEGREI], SEA, release="2020-2025"),
    ):
        [record] = to_records(facts)
        assert record["reliability"]["reasons"] == ["not_measured"]
        assert {q["value"] for q in record["values"].values()} == {None}


def test_a_window_known_only_by_its_years_is_not_exact() -> None:
    from egms_client.facts import to_records, velocity

    facts = velocity([FLEGREI], 14.1205, 40.8225, release="2018-2022")
    facts["window"] |= {"first": None, "last": None, "exact": False}
    [record] = to_records(facts)
    assert record["time"] == {"first": "2018-01-01", "last": "2022-12-31", "exact": False}


def test_only_the_answers_of_facts_have_records() -> None:
    from egms_client.facts import to_records

    with pytest.raises(ValueError, match="no records for an answer of kind 'releases'"):
        to_records({"answer": "releases"})
