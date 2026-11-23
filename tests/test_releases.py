from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from egms_client.releases import (
    KNOWN_RELEASES,
    age_days,
    covers,
    new_releases,
    window,
    window_of,
)
from egms_client.tables import read_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_the_name_is_not_the_window() -> None:
    w = window("2020-2025")
    assert w.exact
    assert w.first == date(2020, 12, 9) and w.last == date(2025, 11, 19)
    assert w.text() == "2020-12-09 to 2025-11-19"
    assert covers(w, date(2020, 6, 1)) is False  # 2020 by name, not in the data


def test_the_recorded_windows_are_those_of_the_files() -> None:
    l3 = read_csv(FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv")
    assert window_of(l3, "2020-2025", "L3") == window("2020-2025", "L3").__class__(
        "2020-2025", "L3", 2020, 2025, date(2020, 12, 9), date(2025, 11, 19)
    )
    l2 = read_csv(FIXTURES / "EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv")
    w = window_of(l2, "2020-2025", "L2B")
    assert (w.first, w.last) == (window("2020-2025", "L2B").first, window("2020-2025", "L2B").last)


def test_an_unread_window_knows_only_its_years() -> None:
    w = window("2020-2024")
    assert not w.exact and (w.first_year, w.last_year) == (2020, 2024)
    assert "not known" in w.text()
    assert covers(w, date(2022, 1, 1)) is None
    assert age_days(w, date(2026, 1, 1)) is None


def test_age_counts_from_the_last_acquisition() -> None:
    assert age_days(window("2020-2025"), date(2026, 11, 23)) == 369


def test_bad_names_and_tables_are_refused() -> None:
    with pytest.raises(ValueError, match="not a release name"):
        window("latest")
    l3 = read_csv(FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv", series=False)
    with pytest.raises(ValueError, match="no date columns"):
        window_of(l3, "2020-2025", "L3")
    l3 = read_csv(FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv")
    with pytest.raises(ValueError, match="not a release name"):
        window_of(l3, "2025", "L3")


def test_new_releases_are_those_not_seen() -> None:
    assert new_releases(list(KNOWN_RELEASES)) == []
    assert new_releases(["2020-2025", "2021-2026"]) == ["2021-2026"]
