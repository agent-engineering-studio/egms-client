"""What a release covers, how old it is, and whether the archive published a new one.

A release is named by years (``"2020-2025"``), but the name is not the
window. The 2020-2025 Ortho L3 series start on **9 December 2020** and end on
**19 November 2025**: the first eleven months of 2020 are not in it. A model
that reads the name as 1 January 2020 - 31 December 2025 puts EGMS data
before landslides it never saw.

:data:`WINDOWS` holds the windows read from real files, with the file each
came from. For a release or level not read yet, :func:`window` knows only
the years and says so (``exact=False``, no dates): not measured is not zero.

The archive publishes a new release about once a year, and the windows grow
(2020-2024, then 2020-2025). :data:`KNOWN_RELEASES` is what this version of
the library has seen; :func:`new_releases` tells what the archive lists
beyond it (``egms releases --check``, and the weekly live test).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

#: The releases this version has seen in the archive (checked 2026-11-23).
KNOWN_RELEASES: tuple[str, ...] = ("2020-2024", "2020-2025")

_NAME = re.compile(r"(?P<first>\d{4})-(?P<last>\d{4})")


@dataclass(frozen=True, slots=True)
class Window:
    """The acquisitions a release holds, for one level.

    ``first`` and ``last`` are the first and last acquisition dates when
    known (``exact``); otherwise ``None``, and only the years of the name
    are known. ``source`` is the file the dates were read from.
    """

    release: str
    level: str
    first_year: int
    last_year: int
    first: date | None = None
    last: date | None = None
    source: str = ""

    @property
    def exact(self) -> bool:
        return self.first is not None and self.last is not None

    def text(self) -> str:
        """For people and agents: ``"2020-12-09 to 2025-11-19"`` or what is not known."""
        if self.first is not None and self.last is not None:
            return f"{self.first.isoformat()} to {self.last.isoformat()}"
        return (
            f"{self.first_year} to {self.last_year} by its name; "
            "the exact acquisition dates are not known to this library"
        )


#: Windows read from the files of the archive: ``(release, level)``.
WINDOWS: dict[tuple[str, str], Window] = {
    ("2020-2025", "L3"): Window(
        "2020-2025",
        "L3",
        2020,
        2025,
        date(2020, 12, 9),
        date(2025, 11, 19),
        "EGMS_L3_E47N19_100km_U_2020_2025_1.csv",
    ),
    ("2020-2025", "L2B"): Window(
        "2020-2025",
        "L2B",
        2020,
        2025,
        date(2020, 12, 5),
        date(2025, 11, 21),
        "EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv",
    ),
}


def window(release: str, level: str = "L3") -> Window:
    """The window of a release for a level: exact if read from a file, else the years only."""
    match = _NAME.fullmatch(release)
    if match is None:
        raise ValueError(f"not a release name: {release!r} (expected like '2020-2025')")
    known = WINDOWS.get((release, level.upper()))
    if known is not None:
        return known
    return Window(release, level.upper(), int(match["first"]), int(match["last"]))


def window_of(frame: Any, release: str, level: str, source: str = "") -> Window:
    """The exact window of a table read with ``tables.read_csv``: its first and last date."""
    from egms_client.tables import dates

    found = dates(frame)
    if not found:
        raise ValueError("the table has no date columns: read it with series=True")
    match = _NAME.fullmatch(release)
    if match is None:
        raise ValueError(f"not a release name: {release!r}")
    return Window(
        release,
        level.upper(),
        int(match["first"]),
        int(match["last"]),
        min(found),
        max(found),
        source,
    )


def age_days(w: Window, today: date) -> int | None:
    """Days from the last acquisition to ``today``; ``None`` if the last date is not known."""
    return None if w.last is None else (today - w.last).days


def covers(w: Window, day: date) -> bool | None:
    """Whether a day falls inside the window; ``None`` when the window is not exact."""
    if w.first is None or w.last is None:
        return None
    return w.first <= day <= w.last


def new_releases(published: list[str]) -> list[str]:
    """The releases the archive lists that this version of the library has not seen."""
    return sorted(set(published) - set(KNOWN_RELEASES))


__all__ = [
    "KNOWN_RELEASES",
    "WINDOWS",
    "Window",
    "age_days",
    "covers",
    "new_releases",
    "window",
    "window_of",
]
