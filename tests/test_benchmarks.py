from __future__ import annotations

import math

from benchmarks.run import load_cases, markdown, passes


def test_a_range_passes_inside_and_fails_outside() -> None:
    check = {"min": 1.0, "max": 2.0}
    assert passes(check, 1.5)
    assert not passes(check, 2.5)
    assert not passes(check, None)
    assert not passes(check, math.nan)


def test_not_measured_passes_only_as_none() -> None:
    assert passes({"none": True}, None)
    assert not passes({"none": True}, 0.0)


def test_every_case_names_its_source_and_has_checks() -> None:
    for case in load_cases():
        assert case["source"].strip(), case["id"]
        assert case["status"] in {"moving", "still", "blind"}, case["id"]
        assert case["check"], case["id"]


def test_the_table_counts_what_passes() -> None:
    row = {"case": "c", "check": "x", "expected": "v ≥ 1", "measured": None, "pass": False}
    assert "not measured" in markdown([row])
    assert "**0 of 1**" in markdown([row])


def test_the_fidelity_set_scores_as_written() -> None:
    from benchmarks.faithful import load, table

    text, faults = table(load())
    assert faults == []
    assert "| hand | 6 | 57 | 57 |" in text


def test_a_number_for_what_is_not_measured_is_a_fault() -> None:
    from benchmarks.faithful import kind
    from egms_client.check import numbers

    facts = {"velocity_mm_per_year": None, "reliability": {"coverage": 0.0}}
    (zero,) = numbers("0.0")
    assert kind(zero, 0, "velocity_mm_per_year", facts, "", "en") == "unmeasured"
    (rising,) = numbers("+4.5")
    assert kind(rising, 1, "v", {"v": -4.5}, "", "en") == "sign"
    (rough,) = numbers("8,600")
    assert kind(rough, 0, "n", {"n": 8588}, "", "en") == "approximate"
