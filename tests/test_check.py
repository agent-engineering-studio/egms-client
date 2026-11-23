"""egms_client.check: numbers read back against the facts."""

from __future__ import annotations

from pathlib import Path

import pytest

from egms_client.check import (
    TEMPLATES,
    check_claims,
    check_signs,
    check_text,
    figures,
    numbers,
    words,
)

FACTS = {
    "answer": "velocity",
    "lon": 14.1205,
    "lat": 40.8225,
    "component": "U",
    "measured": True,
    "velocity_mm_per_year": 145.24,
    "reliability": {
        "score": 1.0,
        "reliable": True,
        "reliable_from": 0.5,
        "coverage": 0.762,
        "radius_m": 500.0,
    },
    "regional": {"radius_m": 5000.0, "median_mm_per_year": 26.3, "relative_mm_per_year": 118.94},
    "release": "2020-2025",
    "window": {"first": "2020-12-09", "last": "2025-11-19", "exact": True},
}


def test_numbers_in_english_and_italian() -> None:
    en = numbers("At -4.5 mm/year, 8,588 cells (39%) in E47N19, on 2020-12-09.")
    assert [(n.text, n.value, n.sign, n.percent) for n in en] == [
        ("-4.5", 4.5, -1, False),
        ("8,588", 8588.0, 0, False),
        ("39", 39.0, 0, True),
        ("2020", 2020.0, 0, False),
        ("12", 12.0, 0, False),
        ("09", 9.0, 0, False),
    ]
    it = numbers("Scende di 4,5 mm/anno; 8.588 celle, il 39 % e \u22122,0.", "it")
    assert [(n.value, n.decimals, n.sign, n.percent) for n in it] == [
        (4.5, 1, 0, False),
        (8588.0, 0, 0, False),
        (39.0, 0, 0, True),
        (2.0, 1, -1, False),
    ]


def test_figures_keep_signs_and_read_strings() -> None:
    assert sorted(figures({"a": -1.5, "b": ["2020-12-09", None, True], "p5": 3})) == [
        -1.5,
        3.0,
        5.0,
        9.0,
        12.0,
        2020.0,
    ]


def test_check_text_rounds_to_the_decimals_written() -> None:
    assert check_text("It rises 145 mm/year, 145.2 to be precise.", FACTS) == []
    assert check_text("It rises 146 mm/year.", FACTS) == ["146"]
    assert check_text("76% of the cells have a value.", FACTS) == []
    assert check_text("Within 3 km, 77% of cells.", FACTS) == ["3", "77"]
    assert check_text("Is 3 km far?", FACTS, question="within 3 km") == []


def test_check_signs() -> None:
    assert check_signs("Pozzuoli rises by 145.2 mm a year.", FACTS) == []
    (wrong,) = check_signs("Pozzuoli sinks by 145.2 mm a year.", FACTS)
    assert "sinks by 145.2" in wrong.said and wrong.fact == 145.24
    assert len(check_signs("The velocity is -145.2 mm/year.", FACTS)) == 1
    assert check_signs("Il suolo si solleva di 145,2 mm/anno.", FACTS, lang="it") == []
    assert len(check_signs("Il suolo scende di 145,2 mm/anno.", FACTS, lang="it")) == 1
    # no direction, or a threshold: not read
    assert check_signs("26.3 mm/year; cells go down faster than 145.2 mm/year.", FACTS) == []
    assert check_signs("A share of 76% goes down.", FACTS) == []


@pytest.mark.parametrize("lang", ["en", "it"])
def test_words_quote_only_the_facts_and_read_back_clean(lang: str) -> None:
    text = words(FACTS, lang)  # type: ignore[arg-type]
    assert "+145.2" in text.replace(",", ".")
    assert check_text(text, FACTS, lang=lang) == []  # type: ignore[arg-type]
    assert check_signs(text, FACTS, lang=lang) == []  # type: ignore[arg-type]
    assert check_claims(text, FACTS, lang=lang) == []  # type: ignore[arg-type]


def test_check_claims_finds_a_swap_and_a_flipped_sign() -> None:
    text = words(FACTS)
    swapped = text.replace("is +26.3 mm/year", "is +118.9 mm/year")
    (wrong,) = check_claims(swapped, FACTS)
    assert (wrong.key, wrong.fact) == ("regional.median_mm_per_year", 26.3)
    assert check_text(swapped, FACTS) == []  # a swap the loose check cannot see
    flipped = text.replace("+145.2", "-145.2")
    assert [m.key for m in check_claims(flipped, FACTS)] == ["velocity_mm_per_year"]
    late = text.replace("2025-11-19", "2025-12-31")
    assert [m.key for m in check_claims(late, FACTS)] == ["window.last"]


def test_words_for_what_is_not_measured_and_an_inexact_window() -> None:
    facts = {
        "answer": "area",
        "measured": False,
        "component": "E",
        "release": "2020-2024",
        "window": {"first": None, "last": None, "exact": False},
    }
    assert "not measured, which is not zero" in words(facts)
    assert "le date esatte della finestra non sono note" in words(facts, "it")
    assert set(TEMPLATES) == {"velocity", "area", "moving_points"}


def test_words_refuse_a_template_that_invents() -> None:
    from egms_client import check

    broken = check.Sentence("It moves 42 mm.", "Si muove di 42 mm.")
    original = check.TEMPLATES["velocity"]
    check.TEMPLATES["velocity"] = (broken,)
    try:
        with pytest.raises(ValueError, match="42"):
            words(FACTS)
    finally:
        check.TEMPLATES["velocity"] = original


def test_the_cli_checks_a_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from egms_client import cli

    folder = tmp_path
    (folder / "facts.json").write_text(json.dumps(FACTS))
    (folder / "good.md").write_text(words(FACTS, "it"))
    (folder / "bad.md").write_text("Pozzuoli scende di 145,2 mm/anno, su 900 celle.")
    assert (
        cli.main(["check", str(folder / "good.md"), str(folder / "facts.json"), "--lang", "it"])
        == 0
    )
    assert (
        cli.main(["check", str(folder / "bad.md"), str(folder / "facts.json"), "--lang", "it"]) == 1
    )
    out = capsys.readouterr().out
    assert "not in the facts: 900" in out and "wrong sign" in out
