"""What the time series say beyond their mean velocity. Needs the ``tables`` extra.

Every EGMS CSV comes with one model fitted to each series over the whole
release: ``mean_velocity``, ``acceleration``, ``seasonality`` (the annual
amplitude) and ``rmse_ts``. That model is::

    displacement(t) = a + v t + acceleration / 2 * t**2 + A cos(2 pi t) + B sin(2 pi t)

with ``t`` in years from the middle of the window. :func:`fit` is that same
model, and over the full window it gives back the archive's columns (the
tests check it on real CSVs). What it adds:

* any window: ``fit(frame, start=date(2024, 11, 1))`` is the velocity of the
  last year, where the archive only gives five years at once;
* the seasonal **phase**: the day of the year the seasonal cycle peaks.

Two things the archive's columns cannot show:

* :func:`trend_change`: a velocity that changes at one date, as on a slope
  that starts to creep. One acceleration over five years averages it away.
* :func:`unwrapping_jumps`: steps of half the radar wavelength (about
  27.7 mm along the line of sight) between two acquisitions. They come from
  the processing (phase unwrapping), not from the ground. Only meaningful on
  L2A / L2B, whose series are along the line of sight.

Every function takes a table of :func:`egms_client.tables.read_csv` (one
row per point, one column per date) and returns one row per point, in the
same order, with its ``pid``. Points with a missing value in the window get
NaN. Points are processed in blocks, so a whole L3 tile (~170,000 cells)
fits in memory.

Least squares treats the residuals as independent, which InSAR residuals
are not: read the statistics as rankings, not as exact probabilities.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date
from typing import Any

from egms_client.tables import DATE_COLUMN

#: Sentinel-1 C-band wavelength, in mm (5.405 GHz).
WAVELENGTH_MM = 55.465763

#: A step of the phase unwrapping: half a wavelength along the line of sight.
HALF_WAVELENGTH_MM = WAVELENGTH_MM / 2

#: Points solved at once: bounds memory to a few hundred MB.
BLOCK = 20_000

_YEAR_DAYS = 365.25


def fit(frame: Any, *, start: date | None = None, end: date | None = None) -> Any:
    """The archive's model fitted to each series, over ``start`` to ``end`` (inclusive).

    Columns: ``pid``, ``velocity`` (mm/year), ``acceleration`` (mm/year²),
    ``seasonal_amplitude`` (mm), ``seasonal_peak_doy`` (the day of the year
    the seasonal cycle peaks, 1-366), ``rmse`` (mm), ``dates`` (how many
    were used). Over the full window, ``velocity``, ``acceleration``,
    ``seasonal_amplitude`` and ``rmse`` are the archive's ``mean_velocity``,
    ``acceleration``, ``seasonality`` and ``rmse_ts``.

    The acceleration needs two years or more to mean something, and the
    season needs one full year: shorter windows raise ``ValueError``.
    """
    import numpy as np

    days, values, pids = _window(frame, start, end)
    span = (days[-1] - days[0]) / _YEAR_DAYS
    if span < 1:
        raise ValueError(f"the window is {span:.1f} years: at least one is needed")
    t = _centred(days)
    cos, sin = _season(days)
    with_acceleration = span >= 2
    columns = [np.ones_like(t), t, *([t**2] if with_acceleration else []), cos, sin]
    x = np.column_stack(columns)
    out = {
        k: np.full(len(pids), np.nan)
        for k in ("velocity", "acceleration", "seasonal_amplitude", "seasonal_peak_doy", "rmse")
    }
    for rows, y in _blocks(values):
        beta, rmse = _solve(x, y)
        a, b = beta[-2], beta[-1]
        out["velocity"][rows] = beta[1]
        if with_acceleration:
            out["acceleration"][rows] = 2 * beta[2]
        out["seasonal_amplitude"][rows] = np.hypot(a, b)
        out["seasonal_peak_doy"][rows] = _peak_doy(a, b)
        out["rmse"][rows] = rmse
    return _table(pids, {**out, "dates": np.full(len(pids), len(days))})


def trend_change(
    frame: Any,
    *,
    min_segment_days: int = 365,
    step_days: int = 30,
    start: date | None = None,
    end: date | None = None,
) -> Any:
    """The date where each series changes velocity, if it does.

    A continuous two-slope line (with the seasonal cycle) is fitted for
    every candidate date, one every ``step_days``, at least
    ``min_segment_days`` from either end. The best one is kept.

    Columns: ``pid``, ``breakpoint`` (the date), ``velocity_before`` and
    ``velocity_after`` (mm/year), ``change`` (after minus before),
    ``delta_bic`` (how much better two slopes fit than one; above 10 is
    strong evidence, and below 0 one slope is enough), ``rmse`` (mm).
    """
    import numpy as np

    days, values, pids = _window(frame, start, end)
    t = _centred(days)
    cos, sin = _season(days)
    first, last = days[0] + min_segment_days, days[-1] - min_segment_days
    if first > last:
        raise ValueError(
            f"{(days[-1] - days[0]) / _YEAR_DAYS:.1f} years is too short for two segments of "
            f"{min_segment_days} days"
        )
    candidates = np.arange(first, last + 1, step_days, dtype="float64")
    # One slope plus the season, then one hinge column per candidate date.
    # The hinge's effect, once the rest is projected out (Frisch-Waugh-Lovell),
    # is one product for all candidates and points: the same answer as a
    # full least-squares fit per candidate, ~30 times faster.
    base = np.column_stack([np.ones_like(t), t, cos, sin])
    project = np.linalg.pinv(base)
    hinges = np.maximum(0.0, (days[:, None] - candidates[None, :]) / _YEAR_DAYS)
    on_base = project @ hinges  # how each hinge reads in the base columns
    hinges_left = hinges - base @ on_base
    hinge_norm = np.sum(hinges_left**2, axis=0)
    n = len(days)
    keys = ("breakpoint", "velocity_before", "velocity_after", "change", "delta_bic", "rmse")
    out = {k: np.full(len(pids), np.nan) for k in keys}
    for rows, y in _blocks(values):
        beta0 = project @ y
        left = y - base @ beta0
        rss0 = np.sum(left**2, axis=0)
        fit_gain = hinges_left.T @ left  # candidates x points
        gain = fit_gain**2 / hinge_norm[:, None]
        best = np.argmax(gain, axis=0)
        points = np.arange(y.shape[1])
        change = fit_gain[best, points] / hinge_norm[best]
        before = beta0[1] - on_base[1, best] * change
        rss1 = np.maximum(rss0 - gain[best, points], 0.0)
        # Two parameters more than one slope: the slope change and the date.
        bic0 = n * np.log(np.maximum(rss0, 1e-12) / n) + 4 * math.log(n)
        bic1 = n * np.log(np.maximum(rss1, 1e-12) / n) + 6 * math.log(n)
        out["breakpoint"][rows] = candidates[best]
        out["velocity_before"][rows] = before
        out["velocity_after"][rows] = before + change
        out["change"][rows] = change
        out["delta_bic"][rows] = bic0 - bic1
        out["rmse"][rows] = np.sqrt(rss1 / n)
    table = _table(pids, out)
    table["breakpoint"] = _dates(out["breakpoint"])
    return table


def unwrapping_jumps(
    frame: Any,
    *,
    tolerance_mm: float = 5.0,
    window: int = 5,
    start: date | None = None,
    end: date | None = None,
) -> Any:
    """Steps of a multiple of half a wavelength between two acquisitions.

    A step counts when the difference between two consecutive dates is
    within ``tolerance_mm`` of k times 27.7 mm (k ≥ 1), and the series stays
    there: the median of the ``window`` dates after it, minus the median of
    the ``window`` dates before, is the same step. A single outlier, which
    goes up and comes back, is not a jump. Meant for L2A / L2B.

    Columns: ``pid``, ``jumps`` (how many), ``first_jump`` (its date, or
    missing), ``total_step_mm`` (their sum, signed).
    """
    import numpy as np

    days, values, pids = _window(frame, start, end)
    count = np.zeros(len(pids))
    total = np.zeros(len(pids))
    first = np.full(len(pids), np.nan)
    count[:] = np.nan
    total[:] = np.nan
    for rows, y in _blocks(values):
        y = y.T  # points x dates
        diff = np.diff(y, axis=1)
        k = np.round(np.abs(diff) / HALF_WAVELENGTH_MM)
        near = (k >= 1) & (np.abs(np.abs(diff) - k * HALF_WAVELENGTH_MM) <= tolerance_mm)
        jump = np.zeros_like(near)
        for i in np.flatnonzero(near.any(axis=0)):
            lo, hi = max(0, i + 1 - window), min(y.shape[1], i + 1 + window)
            before = np.median(y[:, lo : i + 1], axis=1)
            after = np.median(y[:, i + 1 : hi], axis=1)
            jump[:, i] = near[:, i] & (np.abs((after - before) - diff[:, i]) <= tolerance_mm)
        count[rows] = jump.sum(axis=1)
        total[rows] = np.where(jump, diff, 0.0).sum(axis=1)
        has = jump.any(axis=1)
        first_index = np.argmax(jump, axis=1)
        first[rows] = np.where(has, days[1:][first_index], np.nan)
    table = _table(pids, {"jumps": count, "total_step_mm": total})
    table["jumps"] = table["jumps"].astype("Int64")
    table.insert(2, "first_jump", _dates(first))
    return table


# Shared pieces.


def _window(frame: Any, start: date | None, end: date | None) -> tuple[Any, Any, Any]:
    """Days (as ordinals), values (dates x points, float64) and pids of a table."""
    import numpy as np

    columns = [c for c in frame.columns if DATE_COLUMN.fullmatch(str(c))]
    if not columns:
        raise ValueError("the table has no date columns: read it with series=True")
    when = [date(int(c[:4]), int(c[4:6]), int(c[6:])) for c in map(str, columns)]
    keep = [
        (c, d)
        for c, d in zip(columns, when, strict=True)
        if (start is None or d >= start) and (end is None or d <= end)
    ]
    if len(keep) < 6:
        raise ValueError(f"{len(keep)} dates between {start} and {end}: too few to fit")
    days = np.array([d.toordinal() for _, d in keep], dtype="float64")
    values = frame[[c for c, _ in keep]].to_numpy(dtype="float64").T
    pids = frame["pid"].to_numpy() if "pid" in frame.columns else frame.index.to_numpy()
    return days, values, pids


def _blocks(values: Any) -> Iterator[tuple[Any, Any]]:
    """Blocks of complete series (dates x points), with their row indices."""
    import numpy as np

    for lo in range(0, values.shape[1], BLOCK):
        y = values[:, lo : lo + BLOCK]
        complete = ~np.isnan(y).any(axis=0)
        if complete.any():
            yield lo + np.flatnonzero(complete), y[:, complete]


def _solve(x: Any, y: Any) -> tuple[Any, Any]:
    """Least squares for every column of ``y`` at once: coefficients and rmse."""
    import numpy as np

    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    return beta, np.sqrt(np.mean(residual**2, axis=0))


def _centred(days: Any) -> Any:
    return (days - (days[0] + days[-1]) / 2) / _YEAR_DAYS


def _season(days: Any) -> tuple[Any, Any]:
    """The annual cycle on the calendar: phase 0 on 1 January."""
    import numpy as np

    angle = 2 * np.pi * _year_fraction(days)
    return np.cos(angle), np.sin(angle)


def _year_fraction(days: Any) -> Any:
    import numpy as np

    origin = date(2000, 1, 1).toordinal()
    return np.mod((days - origin) / _YEAR_DAYS, 1.0)


def _peak_doy(a: Any, b: Any) -> Any:
    """Day of the year (1-366) where ``a cos + b sin`` peaks."""
    import numpy as np

    fraction = np.mod(np.arctan2(b, a) / (2 * np.pi), 1.0)
    return np.floor(fraction * _YEAR_DAYS) + 1


def _dates(ordinals: Any) -> Any:
    import pandas as pd

    return pd.Series(
        [pd.NaT if math.isnan(o) else pd.Timestamp(date.fromordinal(int(o))) for o in ordinals],
        dtype="datetime64[ns]",
    )


def _table(pids: Any, columns: dict[str, Any]) -> Any:
    import pandas as pd

    return pd.DataFrame({"pid": pids, **columns})
