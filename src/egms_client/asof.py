"""Ground motion as of a date: what the series said *before* a day, cell by cell.

The velocity of a release is one number over five years: the same before and
after a landslide. This module reads the series of the L3 points and gives,
for a cell and a date, two numbers kept apart:

* ``velocity_long``: the velocity from the first acquisition to the start of
  the window;
* ``velocity_before``: the velocity of the window, the last ``window_days``
  before the date.

The two do not overlap: the window is not part of the long-term velocity.

and how far apart they are (``change``, and ``change_z`` in units of the
noise of each point). A model can then ask whether the ground was speeding
up before a day, with rows built "as of" that day.

Four rules:

* **Nothing after the date is read.** Every number of a row uses only the
  acquisitions before its date: the long-term velocity and the seasonal
  cycle too. An acquisition on the day itself does not count, unless
  ``include_day=True``: a feature that sees the day of a landslide measures
  the landslide, not what came before it.
* **The caller decides the instant.** A row carries a ``date``, or an aware
  ``datetime`` read as its UTC day. This module defines no convention for
  an event with no time.
* **Not measured is ``None``, never zero**, and a row says why in
  ``reasons``. The minimums (``min_points``, ``min_acquisitions``) have no
  default: a thin cell is the caller's choice, not a hidden one.
* **Signs are kept.** The velocities are those of the component of the
  table (for the vertical one, negative is down).

How the numbers are made. For each point of the cell, a line with the annual
cycle is fitted to its series before the window: its slope is the long-term
velocity. That cycle is then taken off the window, and a line is fitted to
it: its slope is the velocity before the date. Without that step a window of
six months would read the season as a trend. The cell gets the median over
its points. ``change_z`` divides each point's change by the standard error
of its recent slope, from the scatter of its earlier series around the fit
(the uncertainty of the long-term slope is left out, so it is a little too
large); ``share_changed`` is the share of points beyond ``z``, when ``z`` is
given.

Limits. The series has one value every six days, and InSAR loses fast
motion: a slope that fails in hours shows nothing before. The season needs
a full year of series before the window (``min_history_days``). A change
that began before the window is partly in the long-term velocity and in its
cycle: a point that turned from -5 to -40 mm/year a year before the date
reads -46 over the last six months, not -40. This is a description of
the series, not an alert, and nobody has yet measured that it tells cells
with a landslide from the others.

Needs the ``tables`` extra (pandas) for the table, and numpy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from egms_client.cells import Cell
from egms_client.reliability import NOT_MEASURED
from egms_client.tables import DATE_COLUMN

#: The season is one year long: a shorter past cannot tell it from a trend.
MIN_HISTORY_DAYS = 365

#: Reasons a row has no numbers, besides ``not_measured`` (no point in the cell).
TOO_FEW_POINTS = "too_few_points"
TOO_FEW_ACQUISITIONS = "too_few_acquisitions"
TOO_SHORT_HISTORY = "too_short_history"

_YEAR_DAYS = 365.25


@dataclass(frozen=True, slots=True)
class MotionBefore:
    """What the points of one cell said before one date. ``None``: not measured.

    Velocities and ``change`` in mm/year. ``points`` are the points of the
    table in the cell; ``points_used`` those with a complete series before the
    date. ``acquisitions_long`` counts the acquisitions before the window,
    ``acquisitions_before`` those of the window, from ``window_first`` to
    ``window_last``.
    """

    id: str
    as_of: date
    points: int
    points_used: int = 0
    acquisitions_long: int = 0
    acquisitions_before: int = 0
    window_first: date | None = None
    window_last: date | None = None
    velocity_before: float | None = None
    velocity_long: float | None = None
    change: float | None = None
    change_z: float | None = None
    share_changed: float | None = None
    reasons: tuple[str, ...] = ()


class Series:
    """The series of a table, read once, for many cells and dates.

    ``frame`` is an L3 table with its dates (``tables.read_csv(path)``): the
    columns ``easting`` and ``northing`` (EPSG:3035 metres) and one column
    per acquisition. Concatenate the tables of several tiles first.
    """

    def __init__(self, frame: Any) -> None:
        import numpy as np

        columns = [c for c in frame.columns if DATE_COLUMN.fullmatch(str(c))]
        if not columns:
            raise ValueError("the table has no date columns: read it with series=True")
        missing = {"easting", "northing"} - set(frame.columns)
        if missing:
            raise ValueError(
                f"the table has no {', '.join(sorted(missing))}: an L3 table is needed"
            )
        when = sorted((date(int(c[:4]), int(c[4:6]), int(c[6:])), c) for c in map(str, columns))
        self.dates = [d for d, _ in when]
        self.days = np.array([d.toordinal() for d in self.dates], dtype="float64")
        order = np.argsort(frame["easting"].to_numpy(dtype="float64"), kind="stable")
        self.x = frame["easting"].to_numpy(dtype="float64")[order]
        self.y = frame["northing"].to_numpy(dtype="float64")[order]
        named = {str(c): c for c in frame.columns}
        # points x dates, in time order; float32 as the archive writes them
        self.values = frame[[named[c] for _, c in when]].to_numpy(dtype="float32")[order]
        angle = 2 * np.pi * np.mod((self.days - date(2000, 1, 1).toordinal()) / _YEAR_DAYS, 1.0)
        self._season = np.column_stack([np.cos(angle), np.sin(angle)])
        self._years = (self.days - self.days[0]) / _YEAR_DAYS

    def points_in(self, cell: Cell) -> Any:
        """The rows of the points whose centre is in the cell (``min <= x < max``)."""
        import numpy as np

        lo, hi = np.searchsorted(self.x, [cell.minx, cell.maxx], side="left")
        inside = (self.y[lo:hi] >= cell.miny) & (self.y[lo:hi] < cell.maxy)
        return lo + np.flatnonzero(inside)

    def before(
        self,
        cell: Cell,
        as_of: date | datetime,
        *,
        window_days: int,
        min_points: int,
        min_acquisitions: int,
        min_history_days: int = MIN_HISTORY_DAYS,
        include_day: bool = False,
        z: float | None = None,
    ) -> MotionBefore:
        """One row: see :func:`motion_before`."""
        import numpy as np

        day = _day(as_of)
        rows = self.points_in(cell)
        if len(rows) == 0:
            return MotionBefore(cell.id, day, 0, reasons=(NOT_MEASURED,))
        # The acquisitions before the date: strictly, unless the day counts.
        last = day.toordinal() + (1 if include_day else 0)
        k = int(np.searchsorted(self.days, last, side="left"))
        first = int(np.searchsorted(self.days, last - window_days, side="left"))
        counts: dict[str, Any] = {"acquisitions_long": first, "acquisitions_before": k - first}
        if k - first >= 1:
            counts |= {"window_first": self.dates[first], "window_last": self.dates[k - 1]}

        def empty(used: int, reason: str) -> MotionBefore:
            return MotionBefore(cell.id, day, len(rows), used, reasons=(reason,), **counts)

        if first < 6 or self.days[first - 1] - self.days[0] < min_history_days:
            return empty(0, TOO_SHORT_HISTORY)
        if k - first < max(min_acquisitions, 3):
            return empty(0, TOO_FEW_ACQUISITIONS)
        past = self.values[rows, :k].astype("float64")
        complete = ~np.isnan(past).any(axis=1)
        used = int(complete.sum())
        if used < max(min_points, 1):
            return empty(used, TOO_FEW_POINTS if used else NOT_MEASURED)
        y = past[complete].T  # dates x points
        t = self._years[:k]
        # The past before the window: a line and the annual cycle.
        design = np.column_stack([np.ones(first), t[:first], self._season[:first]])
        beta, *_ = np.linalg.lstsq(design, y[:first], rcond=None)
        long = beta[1]
        residual = y[:first] - design @ beta
        sigma = np.sqrt(np.sum(residual**2, axis=0) / (first - 4))
        # The window, with that cycle taken off.
        tw = t[first:] - t[first:].mean()
        spread = float(np.sum(tw**2))
        flat = y[first:] - self._season[first:k] @ beta[2:]
        recent = tw @ (flat - flat.mean(axis=0)) / spread
        change = recent - long
        error = sigma / math.sqrt(spread)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = np.where(error > 0, change / error, np.nan)
        known = score[~np.isnan(score)]
        return MotionBefore(
            cell.id,
            day,
            len(rows),
            used,
            velocity_before=float(np.median(recent)),
            velocity_long=float(np.median(long)),
            change=float(np.median(change)),
            change_z=float(np.median(known)) if len(known) else None,
            share_changed=(
                float(np.mean(np.abs(known) > z)) if z is not None and len(known) else None
            ),
            **counts,
        )


def motion_before(
    frame: Any,
    rows: Iterable[tuple[Cell, date | datetime]],
    *,
    window_days: int,
    min_points: int,
    min_acquisitions: int,
    min_history_days: int = MIN_HISTORY_DAYS,
    include_day: bool = False,
    z: float | None = None,
) -> list[MotionBefore]:
    """For each cell and date, the velocity before the date next to the long-term one.

    ``frame`` is an L3 table with its series (``tables.read_csv``), or a
    :class:`Series` already built from one. ``rows`` are pairs of a
    :class:`~egms_client.cells.Cell` (EPSG:3035 metres) and a ``date``, or an
    aware ``datetime`` read as its UTC day.

    ``window_days`` is how far back "before" goes (180, 365). A row has
    numbers only with at least ``min_points`` points and ``min_acquisitions``
    acquisitions in the window (never fewer than 3), and at least
    ``min_history_days`` of series before the window; otherwise they are
    ``None`` and ``reasons`` says why. ``include_day`` counts an acquisition on
    the day itself. ``z``
    gives ``share_changed``: the share of points whose change is beyond ``z``
    standard errors; without it the share is ``None``.

    No network and no file is read: fetching the table is a separate step.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be at least 1, got {window_days}")
    series = frame if isinstance(frame, Series) else Series(frame)
    return [
        series.before(
            cell,
            when,
            window_days=window_days,
            min_points=min_points,
            min_acquisitions=min_acquisitions,
            min_history_days=min_history_days,
            include_day=include_day,
            z=z,
        )
        for cell, when in rows
    ]


def to_frame(rows: Iterable[MotionBefore]) -> Any:
    """The rows as a ``pandas.DataFrame``: ``None`` becomes NaN, never 0."""
    import pandas as pd

    table = pd.DataFrame([asdict(r) for r in rows])
    if not table.empty:
        table["reasons"] = table["reasons"].map(",".join)
    return table


def _day(when: date | datetime) -> date:
    if isinstance(when, datetime):
        if when.tzinfo is None:
            raise ValueError("a datetime needs its time zone: pass an aware one, or a date")
        return when.astimezone(UTC).date()
    return when


__all__ = [
    "MIN_HISTORY_DAYS",
    "TOO_FEW_ACQUISITIONS",
    "TOO_FEW_POINTS",
    "TOO_SHORT_HISTORY",
    "MotionBefore",
    "Series",
    "motion_before",
    "to_frame",
]
