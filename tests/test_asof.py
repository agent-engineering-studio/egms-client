"""egms_client.asof: ground motion before a date, with nothing read after it."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from egms_client.asof import (  # noqa: E402
    TOO_FEW_ACQUISITIONS,
    TOO_FEW_POINTS,
    TOO_SHORT_HISTORY,
    MotionBefore,
    Series,
    motion_before,
    to_frame,
)
from egms_client.cells import Cell  # noqa: E402
from egms_client.reliability import NOT_MEASURED  # noqa: E402
from egms_client.tables import read_csv  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
START = date(2020, 12, 9)
DATES = [START + timedelta(days=6 * i) for i in range(300)]  # to 8 November 2025
CELL = Cell("a", 0, 0, 1000, 1000)
KEEP: dict[str, Any] = {"window_days": 180, "min_points": 1, "min_acquisitions": 10}


def _years(day: date) -> float:
    return (day - START).days / 365.25


def _frame(series: list[list[float]], xy: list[tuple[float, float]] | None = None) -> Any:
    """A table shaped like an L3 one: a point per row, a column per date."""
    xy = xy or [(50.0 + 100 * i, 50.0) for i in range(len(series))]
    head = pd.DataFrame(
        {
            "pid": [f"p{i}" for i in range(len(series))],
            "easting": [x for x, _ in xy],
            "northing": [y for _, y in xy],
        }
    )
    columns = [day.strftime("%Y%m%d") for day in DATES]
    values = pd.DataFrame(np.array(series, dtype="float32"), columns=columns)
    return pd.concat([head, values], axis=1)


def _line(slope: float, *, turn: date | None = None, after: float = 0.0) -> list[float]:
    """mm at each date: ``slope`` mm/year, then ``after`` mm/year from ``turn``."""
    out = []
    for day in DATES:
        value = slope * _years(day)
        if turn is not None and day > turn:
            value = slope * _years(turn) + after * (_years(day) - _years(turn))
        out.append(value)
    return out


def _one(frame: Any, when: Any, **options: Any) -> MotionBefore:
    (row,) = motion_before(frame, [(CELL, when)], **{**KEEP, **options})
    return row


def test_a_steady_point_has_the_same_velocity_before_and_long() -> None:
    row = _one(_frame([_line(-8.0), _line(-12.0), _line(-10.0)]), date(2024, 6, 1))
    assert row.velocity_long == pytest.approx(-10.0, abs=1e-3)
    assert row.velocity_before == pytest.approx(-10.0, abs=1e-3)
    assert row.change == pytest.approx(0.0, abs=1e-3)
    assert (row.points, row.points_used, row.reasons) == (3, 3, ())
    assert row.acquisitions_before == 30  # 180 days, one every six


def test_a_point_that_speeds_up_shows_it_before_the_date() -> None:
    turn = date(2024, 1, 1)
    frame = _frame([_line(-5.0, turn=turn, after=-40.0)] * 4)
    row = _one(frame, date(2024, 7, 1))
    assert row.velocity_before == pytest.approx(-40.0, abs=1e-3)
    assert row.velocity_long == pytest.approx(-5.0, abs=1e-3)  # the window is not in it
    assert row.change == pytest.approx(-35.0, abs=1e-3)
    # The same cell a year earlier: nothing yet.
    assert _one(frame, date(2023, 7, 1)).change == pytest.approx(0.0, abs=1e-3)


def test_nothing_after_the_date_is_read() -> None:
    """Changing the series from the date on changes no number of the row."""
    when = date(2023, 9, 1)
    calm = _frame([_line(-5.0)] * 3)
    slid = _frame([_line(-5.0, turn=when - timedelta(days=1), after=-500.0)] * 3)
    assert _one(calm, when) == _one(slid, when)


def test_an_acquisition_on_the_day_does_not_count_unless_asked() -> None:
    when = DATES[150]  # a day with an acquisition
    series = _line(-5.0)
    series[150] += 80.0  # the ground drops on the day
    frame = _frame([series] * 3)
    before = _one(frame, when)
    assert before.window_last == DATES[149]
    assert before.velocity_before == pytest.approx(-5.0, abs=1e-3)
    with_day = _one(frame, when, include_day=True)
    assert with_day.window_last == when
    assert with_day.velocity_before is not None and with_day.velocity_before > 0
    # The window moves with the day: still 180 days, one acquisition later.
    assert before.window_first is not None
    assert with_day.window_first == before.window_first + timedelta(days=6)


def test_an_aware_datetime_is_read_as_its_utc_day() -> None:
    frame = _frame([_line(-5.0)] * 2)
    # The next local midnight in Rome after 3 October 2023: still the 3rd in UTC.
    instant = datetime(2023, 10, 3, 22, 0, tzinfo=UTC)
    assert _one(frame, instant) == _one(frame, date(2023, 10, 3))
    with pytest.raises(ValueError, match="time zone"):
        _one(frame, datetime(2023, 10, 3, 22, 0))


def test_the_season_is_not_read_as_a_trend() -> None:
    """A still point with an annual cycle of 5 mm: a window of six months is flat."""
    wave = [5.0 * math.sin(2 * math.pi * _years(d)) for d in DATES]
    row = _one(_frame([wave] * 3), date(2024, 3, 1))
    assert row.velocity_long == pytest.approx(0.0, abs=0.05)
    assert row.velocity_before == pytest.approx(0.0, abs=0.05)
    # The same window with no season taken off would read tens of mm/year.
    half = [d for d in DATES if date(2023, 9, 3) <= d < date(2024, 3, 1)]
    naive = np.polyfit([_years(d) for d in half], [wave[DATES.index(d)] for d in half], 1)[0]
    assert abs(naive) > 10


def test_a_cell_with_no_point_is_not_measured() -> None:
    frame = _frame([_line(-5.0)], xy=[(5000.0, 5000.0)])
    row = _one(frame, date(2024, 6, 1))
    assert row == MotionBefore("a", date(2024, 6, 1), 0, reasons=(NOT_MEASURED,))
    assert row.velocity_before is None and row.velocity_long is None


def test_a_point_on_the_upper_edge_belongs_to_the_next_cell() -> None:
    frame = _frame([_line(-5.0), _line(-5.0)], xy=[(0.0, 0.0), (1000.0, 500.0)])
    assert _one(frame, date(2024, 6, 1)).points == 1


def test_too_few_points_or_acquisitions_give_none_and_say_why() -> None:
    frame = _frame([_line(-5.0)] * 2)
    thin = _one(frame, date(2024, 6, 1), min_points=3)
    assert thin.reasons == (TOO_FEW_POINTS,) and thin.velocity_before is None
    assert (thin.points, thin.points_used, thin.acquisitions_before) == (2, 2, 30)
    few = _one(frame, date(2024, 6, 1), min_acquisitions=31)
    assert few.reasons == (TOO_FEW_ACQUISITIONS,) and few.change is None
    # Long after the last acquisition the window is empty.
    late = _one(frame, date(2026, 11, 28))
    assert late.reasons == (TOO_FEW_ACQUISITIONS,)
    assert (late.acquisitions_before, late.window_last) == (0, None)
    assert late.acquisitions_long == 300  # all of them are before the window


def test_the_first_year_is_too_short_for_the_season() -> None:
    frame = _frame([_line(-5.0)] * 2)
    early = _one(frame, date(2021, 9, 1))
    assert early.reasons == (TOO_SHORT_HISTORY,) and early.velocity_long is None
    assert _one(frame, date(2021, 9, 1), min_history_days=80).reasons == ()
    assert _one(frame, date(2019, 1, 1)).acquisitions_long == 0


def test_a_series_with_a_gap_before_the_date_is_left_out() -> None:
    holed = _line(-5.0)
    holed[100] = math.nan
    row = _one(_frame([holed, _line(-7.0)]), date(2024, 6, 1))
    assert (row.points, row.points_used) == (2, 1)
    assert row.velocity_long == pytest.approx(-7.0, abs=1e-3)
    # A gap after the date does not matter.
    late = _line(-5.0)
    late[290] = math.nan
    assert _one(_frame([late]), date(2024, 6, 1)).points_used == 1


def test_the_change_is_weighed_against_the_noise_of_each_point() -> None:
    rng = np.random.default_rng(7)
    turn = date(2024, 1, 1)
    noise = rng.normal(0, 1.0, size=(20, len(DATES)))
    steady = _frame((np.array([_line(-5.0)] * 20) + noise).tolist())
    faster = _frame((np.array([_line(-5.0, turn=turn, after=-40.0)] * 20) + noise).tolist())
    calm = _one(steady, date(2024, 7, 1), z=3.0)
    moved = _one(faster, date(2024, 7, 1), z=3.0)
    assert calm.change_z is not None and abs(calm.change_z) < 1.5
    assert calm.share_changed is not None and calm.share_changed <= 0.1
    assert moved.change_z is not None and moved.change_z < -5
    assert moved.share_changed == 1.0
    # Without z the share is not computed: no threshold is assumed.
    assert _one(faster, date(2024, 7, 1)).share_changed is None


def test_many_rows_share_one_reading_of_the_table() -> None:
    frame = _frame([_line(-5.0), _line(3.0)], xy=[(50.0, 50.0), (1050.0, 50.0)])
    cells = [CELL, Cell("b", 1000, 0, 2000, 1000)]
    series = Series(frame)
    rows = motion_before(
        series, [(c, d) for c in cells for d in (date(2023, 1, 1), date(2025, 1, 1))], **KEEP
    )
    assert [(r.id, r.as_of.year) for r in rows] == [
        ("a", 2023),
        ("a", 2025),
        ("b", 2023),
        ("b", 2025),
    ]
    assert [round(r.velocity_long or 0) for r in rows] == [-5, -5, 3, 3]
    table = to_frame([*rows, _one(frame, date(2019, 1, 1))])
    assert list(table.reasons) == ["", "", "", "", TOO_SHORT_HISTORY]
    assert np.isnan(table.velocity_before.iloc[-1])
    with pytest.raises(ValueError, match="window_days"):
        motion_before(series, [], **{**KEEP, "window_days": 0})


def test_a_table_without_series_or_position_is_refused() -> None:
    frame = _frame([_line(-5.0)])
    with pytest.raises(ValueError, match="no date columns"):
        Series(frame[["pid", "easting", "northing"]])
    with pytest.raises(ValueError, match="easting"):
        Series(frame.drop(columns=["easting"]))


def test_on_a_real_tile_the_full_window_gives_the_archive_velocity() -> None:
    """Three real points of E47N19: over the whole release, the long-term velocity
    is the archive's ``mean_velocity``, to its one decimal."""
    frame = read_csv(FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv")
    for _, point in frame.iterrows():
        cell = Cell(
            "p", point.easting - 50, point.northing - 50, point.easting + 50, point.northing + 50
        )
        (row,) = motion_before(frame, [(cell, date(2025, 11, 20))], **KEEP)
        assert row.acquisitions_long + row.acquisitions_before == 302 and row.points == 1
        assert row.velocity_long == pytest.approx(point.mean_velocity, abs=0.5)
