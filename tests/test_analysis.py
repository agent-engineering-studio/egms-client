"""Time-series analysis: on series with known answers, and against the archive's own columns."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from egms_client import analysis  # noqa: E402
from egms_client.analysis import (  # noqa: E402
    HALF_WAVELENGTH_MM,
    fit,
    trend_change,
    unwrapping_jumps,
)
from egms_client.tables import attributes, read_csv  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
START = date(2020, 12, 5)
DATES = [START + timedelta(days=6 * i) for i in range(301)]  # five years, every 6 days
DAYS = np.array([d.toordinal() for d in DATES], dtype="float64")
T = (DAYS - (DAYS[0] + DAYS[-1]) / 2) / 365.25


def _season(amplitude: float, peak_doy: float) -> Any:
    fraction = np.mod((DAYS - date(2000, 1, 1).toordinal()) / 365.25, 1.0)
    return amplitude * np.cos(2 * np.pi * (fraction - (peak_doy - 0.5) / 365.25))


def _frame(*series: Any, pids: list[str] | None = None) -> Any:
    columns = {d.strftime("%Y%m%d"): [s[i] for s in series] for i, d in enumerate(DATES)}
    return pd.DataFrame({"pid": pids or [f"p{i}" for i in range(len(series))], **columns})


def _noise(seed: int, sigma: float = 0.5) -> Any:
    return np.random.default_rng(seed).normal(0, sigma, len(DATES))


# fit


def test_fit_recovers_a_known_series() -> None:
    y = 3 - 4.0 * T + 0.5 * 0.8 * T**2 + _season(2.5, 200)
    (row,) = fit(_frame(y)).to_dict("records")
    assert row["velocity"] == pytest.approx(-4.0, abs=1e-6)
    assert row["acceleration"] == pytest.approx(0.8, abs=1e-6)
    assert row["seasonal_amplitude"] == pytest.approx(2.5, abs=1e-6)
    assert row["seasonal_peak_doy"] == 200
    assert row["rmse"] == pytest.approx(0, abs=1e-6)
    assert row["dates"] == len(DATES)


@pytest.mark.parametrize(
    ("name", "seasonality_tolerance"),
    [
        ("EGMS_L3_E47N19_100km_U_2020_2025_1.csv", 0.06),
        # L2B seasonality is 1.5 for every point of the burst: the archive
        # seems to estimate it per burst, not per point.
        ("EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv", 0.2),
    ],
)
def test_fit_gives_back_the_archive_columns(name: str, seasonality_tolerance: float) -> None:
    table = read_csv(FIXTURES / name)
    ours = fit(table)
    theirs = attributes(table)
    # The archive rounds to 0.1 mm/year, 0.01 mm/year² and 0.1 mm.
    np.testing.assert_allclose(ours["velocity"], theirs["mean_velocity"], atol=0.051)
    np.testing.assert_allclose(ours["acceleration"], theirs["acceleration"], atol=0.011)
    np.testing.assert_allclose(ours["rmse"], theirs["rmse_ts"], atol=0.06)
    np.testing.assert_allclose(
        ours["seasonal_amplitude"], theirs["seasonality"], atol=seasonality_tolerance
    )
    assert list(ours["pid"]) == list(table["pid"])


def test_fit_on_a_window() -> None:
    late = T > 1.0  # the last ~1.5 years move faster
    y = -1.0 * T + np.where(late, -5.0 * (T - 1.0), 0.0)
    row = fit(_frame(y), start=date(2024, 6, 1)).iloc[0]
    assert row["velocity"] == pytest.approx(-6.0, abs=0.01)
    assert row["dates"] == sum(d >= date(2024, 6, 1) for d in DATES)
    assert np.isnan(row["acceleration"])  # under two years: no acceleration


def test_fit_refuses_less_than_a_year() -> None:
    with pytest.raises(ValueError, match="at least one is needed"):
        fit(_frame(T), start=date(2025, 3, 1))


def test_a_series_with_a_gap_is_nan_and_the_others_are_not() -> None:
    gap = T.copy()
    gap[10] = np.nan
    table = fit(_frame(gap, 2 * T))
    assert table["velocity"].isna().tolist() == [True, False]
    assert table["velocity"][1] == pytest.approx(2.0)


def test_blocks_give_the_same_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _frame(*(v * T + _noise(i) for i, v in enumerate([-3.0, -1.0, 0.0, 2.0, 5.0])))
    whole = fit(table)
    monkeypatch.setattr(analysis, "BLOCK", 2)
    np.testing.assert_allclose(fit(table)["velocity"], whole["velocity"])


def test_without_a_pid_column_the_index_is_the_pid() -> None:
    table = _frame(T).drop(columns="pid")
    table.index = ["cell-a"]
    assert fit(table)["pid"].tolist() == ["cell-a"]


def test_a_table_without_dates_is_refused() -> None:
    with pytest.raises(ValueError, match="no date columns"):
        fit(pd.DataFrame({"pid": ["a"], "mean_velocity": [1.0]}))
    with pytest.raises(ValueError, match="too few"):
        fit(_frame(T), start=date(2025, 11, 1))


# trend_change


def test_trend_change_finds_the_date_a_slope_starts_to_move() -> None:
    onset = date(2023, 6, 1)
    years_after = np.maximum(0.0, (DAYS - onset.toordinal()) / 365.25)
    moving = -0.5 * T - 12.0 * years_after + _season(1.5, 30) + _noise(1)
    still = -0.5 * T + _season(1.5, 30) + _noise(2)
    a, b = trend_change(_frame(moving, still)).to_dict("records")
    assert abs((a["breakpoint"].date() - onset).days) <= 30
    assert a["velocity_before"] == pytest.approx(-0.5, abs=0.3)
    assert a["velocity_after"] == pytest.approx(-12.5, abs=0.3)
    assert a["change"] == pytest.approx(-12.0, abs=0.4)
    assert a["delta_bic"] > 100
    assert b["delta_bic"] < 10  # one slope is enough
    assert a["rmse"] == pytest.approx(0.5, abs=0.1)


def test_trend_change_is_the_best_full_fit_over_the_candidates() -> None:
    """The projected solve equals a least-squares fit per candidate date, done the long way."""
    series = [
        v * T + 4 * np.maximum(0, T - s) + _noise(i)
        for i, (v, s) in enumerate([(-1.0, -0.5), (2.0, 0.3), (0.0, 1.0)])
    ]
    ours = trend_change(_frame(*series), step_days=60)
    fraction = np.mod((DAYS - date(2000, 1, 1).toordinal()) / 365.25, 1.0)
    cos, sin = np.cos(2 * np.pi * fraction), np.sin(2 * np.pi * fraction)
    candidates = np.arange(DAYS[0] + 365, DAYS[-1] - 365 + 1, 60)
    for row, y in zip(ours.to_dict("records"), series, strict=True):
        fits = []
        for day in candidates:
            hinge = np.maximum(0.0, (DAYS - day) / 365.25)
            x = np.column_stack([np.ones_like(T), T, hinge, cos, sin])
            beta, *_ = np.linalg.lstsq(x, y, rcond=None)
            fits.append((float(np.sum((y - x @ beta) ** 2)), day, beta))
        rss, day, beta = min(fits, key=lambda f: f[0])
        assert row["breakpoint"].date() == date.fromordinal(int(day))
        assert row["velocity_before"] == pytest.approx(beta[1], abs=1e-9)
        assert row["change"] == pytest.approx(beta[2], abs=1e-9)
        assert row["rmse"] == pytest.approx(np.sqrt(rss / len(DATES)), abs=1e-9)


def test_trend_change_on_the_archive_l3_cells() -> None:
    """The three E47N19 cells: still until 2023, then sinking."""
    table = trend_change(read_csv(FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv"))
    assert (table["delta_bic"] > 10).all()
    assert (table["change"] < -1).all()
    assert (table["breakpoint"].dt.year == 2023).all()


def test_trend_change_needs_room_for_two_segments() -> None:
    with pytest.raises(ValueError, match="too short"):
        trend_change(_frame(T), min_segment_days=1000)


# unwrapping_jumps


def test_a_half_wavelength_step_is_a_jump() -> None:
    step = np.where(np.arange(len(DATES)) > 150, HALF_WAVELENGTH_MM, 0.0)
    double = np.where(np.arange(len(DATES)) > 80, -2 * HALF_WAVELENGTH_MM, 0.0)
    noise = _noise(3, 0.8)
    table = unwrapping_jumps(_frame(-1.0 * T + step + noise, double + noise))
    one, two = table.to_dict("records")
    assert one["jumps"] == 1
    assert one["first_jump"].date() == DATES[151]
    assert one["total_step_mm"] == pytest.approx(HALF_WAVELENGTH_MM, abs=3)
    assert two["jumps"] == 1
    assert two["total_step_mm"] == pytest.approx(-2 * HALF_WAVELENGTH_MM, abs=3)


def test_an_outlier_or_real_motion_is_not_a_jump() -> None:
    spike = _noise(4, 0.8)
    spike[100] += HALF_WAVELENGTH_MM  # one bad date: up and back
    fast = -30.0 * T + _noise(5, 0.8)  # steady motion, 0.5 mm per date
    gap = _noise(6).copy()
    gap[3] = np.nan
    table = unwrapping_jumps(_frame(spike, fast, gap))
    assert table["jumps"].tolist()[:2] == [0, 0]
    assert table["first_jump"].isna().all()
    assert table["jumps"].isna().tolist() == [False, False, True]


def test_analysis_on_the_archive_l2b_points() -> None:
    table = unwrapping_jumps(read_csv(FIXTURES / "EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv"))
    assert table["jumps"].tolist() == [0, 0, 0]
