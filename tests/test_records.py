from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from contracts import ASSESSMENT, RECORD_KEYS, assessment_record, landslide_record
from jsonschema import Draft202012Validator

from egms_client import cli
from egms_client.records import SCHEMA_V2, RecordError, problems, read, schema, validate

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples" / "records"
EXAMPLES_V2 = ROOT / "examples" / "records-v2"
LANDSLIDES = json.loads((ROOT / "tests" / "fixtures" / "ispra_dated_landslides.json").read_text())


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


# --- label, headline, and the CSV template --------------------------------------

TEMPLATES = Path(__file__).resolve().parent.parent / "demo" / "web" / "public" / "templates"


def test_a_label_is_one_text_or_one_per_language() -> None:
    assert problems(_observation(label="Suolo")) == []
    assert problems(_observation(label={"it": "Suolo", "en": "Ground"})) == []
    assert problems(_observation(label={"italiano": "Suolo"})) != []
    assert problems(_observation(label={})) != []


def test_a_headline_names_one_of_the_values() -> None:
    assert problems(_fact(headline="cumulated")) == []
    assert problems(_fact(headline="median")) == [
        "headline: 'median' is not one of the values (cumulated)"
    ]
    assert problems(_observation(headline="value")) == [
        "headline: not part of a record of kind observation"
    ]


@pytest.mark.parametrize("path", sorted(TEMPLATES.iterdir()), ids=lambda p: p.name)
def test_the_templates_of_the_page_are_valid(path: Path) -> None:
    assert len(read(path)) == 3


def test_the_csv_template_reads_as_a_spreadsheet_saves_it(tmp_path: Path) -> None:
    rain = read(TEMPLATES / "record.csv")
    assert [r["value"] for r in rain] == [0.4, None, 1.2]
    assert rain[0]["where"]["coordinates"] == [14.1262, 40.8262]
    assert rain[0]["thing"] == "pluvio-01"
    assert rain[0]["label"] == "Pioggia"
    english = tmp_path / "en.csv"
    english.write_text(
        "time,lon,lat,property,value,unit,source,licence,meaning\n"
        "2025-11-19,14.12,40.82,velocity,145.2,mm/a,EGMS,CC0-1.0,positive = up\n"
    )
    [one] = read(english)
    assert one["time"] == {"first": "2025-11-19", "last": "2025-11-19", "exact": True}
    assert one["meaning"] == "positive = up"


def test_a_wrong_csv_says_which_line(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.csv"
    wrong.write_text(
        "tempo;lon;lat;grandezza;valore;unità;fonte;licenza\n"
        "2026-10-15T12:00:00;14,1;40,8;rainfall;0,4;mm;P;CC0-1.0\n"
        "2026-10-15T12:10:00Z;est;40,8;rainfall;0,4;mm;P;CC0-1.0\n"
    )
    with pytest.raises(RecordError) as caught:
        read(wrong)
    assert (
        caught.value.problems[0] == "wrong.csv line 2: time/instant: give the time zone (use UTC)"
    )
    assert caught.value.problems[1].startswith("wrong.csv line 3: where")


def test_a_csv_without_the_columns_is_refused(tmp_path: Path) -> None:
    few = tmp_path / "few.csv"
    few.write_text("tempo,valore\n2026-10-15,1\n")
    with pytest.raises(
        RecordError, match="csv: the columns lat, licence, lon, property, source, unit"
    ):
        read(few)
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(RecordError, match="csv: the columns"):
        read(empty)


# --- opendata-record/v2


def _event(**changes: Any) -> dict[str, Any]:
    record = landslide_record(LANDSLIDES[1])  # an event dated to the hour, within 100 m
    record.update(changes)
    return record


def test_v2_is_a_valid_json_schema_with_its_own_id() -> None:
    v2 = schema(SCHEMA_V2)
    Draft202012Validator.check_schema(v2)
    assert v2["title"] == "opendata-record/v2" and v2["$id"].endswith("opendata-record-v2.json")
    assert v2["$id"] != schema()["$id"]
    with pytest.raises(ValueError, match="no schema"):
        schema("opendata-record/v3")


def test_the_schemas_on_the_site_are_those_of_the_package() -> None:
    for name in ("opendata-record-v1.json", "opendata-record-v2.json"):
        packaged = ROOT / "src" / "egms_client" / "schema" / name
        assert (ROOT / "docs" / "schema" / name).read_bytes() == packaged.read_bytes()


def test_v1_is_not_edited() -> None:
    """A v1 record is checked against v1: nothing of v2 is allowed in it."""
    assert problems(_observation(where=None))[0].startswith("where: None is not")
    assert problems(_observation(where_accuracy_m=5)) != []
    assert problems(_fact(values={"flag": {"value": True}})) != []
    assert (
        "is not one of ['observation', 'fact', 'layer']" in problems(_observation(kind="event"))[-1]
    )


def test_a_record_says_which_schema_it_follows() -> None:
    assert problems(_event(schema="opendata-record/v3")) == [
        "schema: 'opendata-record/v3' is not one of opendata-record/v1, opendata-record/v2"
    ]


@pytest.mark.parametrize("path", sorted(EXAMPLES.iterdir()), ids=lambda p: p.name)
def test_every_v1_example_is_valid_as_v2_too(path: Path) -> None:
    """v2 only adds: a v1 record with its schema field changed is a v2 record."""
    for record in read(path):
        assert problems({**record, "schema": SCHEMA_V2}) == []


@pytest.mark.parametrize("path", sorted(EXAMPLES_V2.iterdir()), ids=lambda p: p.name)
def test_every_v2_example_is_valid(path: Path) -> None:
    assert all(r["schema"] == SCHEMA_V2 for r in read(path))


@pytest.mark.parametrize("row", LANDSLIDES, ids=lambda r: r["id"])
def test_every_key_of_a_dated_landslide_has_a_place(row: dict[str, Any]) -> None:
    """ispra-idrogeo's ``dated.RECORD_KEYS``, on real landslides of 28 November 2026."""
    assert tuple(row) == RECORD_KEYS
    record = landslide_record(row)  # asserts that no key is left over
    assert problems(record) == []
    assert record["time"]["days"] == row["interval_days"]
    assert record["where_accuracy_m"] == row["position_m"]
    assert record["values"]["main_event"]["value"] is row["main_event"]


def test_a_landslide_with_no_time_takes_the_end_of_its_day_and_says_so() -> None:
    day = landslide_record(LANDSLIDES[3])["time"]
    assert day["instant"] == "2010-01-01T23:00:00Z"  # the next midnight in Rome, in winter
    assert day["convention"] == "end of the day, Europe/Rome" and "local_time" not in day
    hour = landslide_record(LANDSLIDES[1])["time"]
    assert hour["instant"] == "2014-11-06T07:41:00Z" and hour["local_time"] == "08:41"
    assert "convention" not in hour
    year = landslide_record(LANDSLIDES[2])["time"]
    assert (year["first"], year["last"], year["days"]) == ("2010-01-01", "2010-12-31", 365)
    assert year["instant"] == "2010-12-31T23:00:00Z"  # the end of its last day
    summer = landslide_record({**LANDSLIDES[3], "start": "2010-07-01", "end": "2010-07-01"})
    assert summer["time"]["instant"] == "2010-07-01T22:00:00Z"
    # The day the clock goes back has 25 hours: the next midnight, not +24 h.
    autumn = landslide_record({**LANDSLIDES[3], "start": "2010-10-31", "end": "2010-10-31"})
    assert autumn["time"]["instant"] == "2010-10-31T23:00:00Z"
    # Before 1893 Rome kept its local mean time: the zone, never a fixed offset.
    assert landslide_record(LANDSLIDES[0])["time"]["instant"] == "1545-06-09T23:10:04Z"


def test_an_event_assessment_is_a_fact_with_its_yes_and_no() -> None:
    """rainfall-thresholds' ``EventAssessment`` (0.4.0): nothing is lost in v2."""
    record = assessment_record(ASSESSMENT)
    assert problems(record) == []
    values = record["values"]
    assert values["borders_unmeasured"] == {"value": True}
    assert values["rain_source"]["value"] == "rain gauge"
    assert values["ratio"]["value"] == pytest.approx(2.2109, abs=1e-4)
    # The same record cannot be written in v1: a yes/no has no unit.
    assert any(
        "borders_unmeasured" in p for p in problems({**record, "schema": "opendata-record/v1"})
    )


def test_a_place_may_be_absent_but_then_has_no_accuracy() -> None:
    assert problems(_event(where=None, where_accuracy_m=None)) == []
    assert problems(_event(where=None)) == [
        "where_accuracy_m: there is no place, so no accuracy: write null"
    ]
    assert problems(_event(where_accuracy_m=-1)) == [
        "where_accuracy_m: -1 is less than the minimum of 0"
    ]
    moved = {**_observation(), "schema": SCHEMA_V2, "where": None}
    assert problems(moved)[-1] == "where: a record of kind observation has a place"


def test_the_width_of_a_date_is_said_without_contradiction() -> None:
    time = _event()["time"]
    assert problems(_event(time={**time, "precision": "interval"})) == [
        "time/precision: an interval covers more than one day"
    ]
    assert problems(_event(time={**time, "last": "2014-11-08"})) == [
        "time/precision: a date known to the hour covers one day",
        "time/days: 1, but first to last are 3 days",
    ]
    assert problems(_event(time={**time, "local_time": "8:41"}))[0].startswith("time/local_time")
    no_clock = {k: v for k, v in time.items() if k != "local_time"}
    assert problems(_event(time={**no_clock, "convention": "end of the day"})) == [
        "time/precision: known to the hour, so the instant is not a convention"
    ]
    assert problems(_event(time={"first": "2014-11-06", "convention": "x"}))[:3] == [
        "time: 'last' is a required property",
        "time: 'exact' is a required property",
        "time: 'instant' is a dependency of 'convention'",
    ]
    assert problems(_event(time=None)) == []


def test_a_value_is_a_quantity_a_flag_or_a_category() -> None:
    def with_value(value: dict[str, Any]) -> list[str]:
        return problems(_event(values={"x": value}))

    assert with_value({"value": 3.5, "unit": "m"}) == []
    assert with_value({"value": None}) == []
    assert with_value({"value": "debris flow", "scheme": "a word of the source"}) == []
    assert with_value({"value": None, "scheme": "ISTAT region code"}) == []
    assert with_value({"value": True, "unit": "m"}) != []
    assert with_value({"value": 3.5, "scheme": "codes"}) != []
    assert with_value({"value": float("nan"), "unit": "m"}) == [
        "values/x: nan is not a value; write null when it is not measured"
    ]


def test_an_event_is_not_an_alert_either() -> None:
    assert problems(_event(event="landslide_alert")) == [
        "landslide_alert: a record is a measurement, not a warning; 'alert' is not allowed"
    ]
    assert problems(_event(question="why")) == ["question: not part of a record of kind event"]
    missing = _event()
    del missing["event"]
    assert problems(missing) == ["record: 'event' is a required property"]


def test_the_command_checks_v2_files(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["records", *(str(p) for p in sorted(EXAMPLES_V2.iterdir()))]) == 0
    assert capsys.readouterr().out.count(": 1 record(s), valid") == 4
