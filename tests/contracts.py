"""The plain contracts of two sister libraries, written as opendata-record/v2.

Test data: the package imports no sister library (tests/test_package.py), so
the keys are copied here. ``RECORD_KEYS`` is ispra-idrogeo's
``dated.RECORD_KEYS`` (0.14); the fields of the assessment are those of
rainfall-thresholds' ``EventAssessment`` and ``RainfallEvent`` (0.4.0).
Each function is one way to write that contract as a record: the libraries'
own ``as_record`` may choose other names for the values, not other shapes.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

RECORD_KEYS = (
    "source",
    "id",
    "lon",
    "lat",
    "start",
    "end",
    "time",
    "precision",
    "interval_days",
    "position_m",
    "movement",
    "region",
    "province",
    "municipality",
    "main_event",
    "citation",
)

ROME = ZoneInfo("Europe/Rome")
UTC = ZoneInfo("UTC")
END_OF_DAY = "end of the day, Europe/Rome"
CATALOGUES = {"iffi": "IdroGEO, IFFI", "eventi": "IdroGEO, eventi franosi"}


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def landslide_record(row: dict[str, Any]) -> dict[str, Any]:
    """A dated landslide (``DatedLandslide.as_dict()``) as an event record."""
    left = dict(row)
    take = left.pop
    start, end, clock = take("start"), take("end"), take("time")
    when: dict[str, Any] = {
        "first": start,
        "last": end,
        "exact": True,
        "precision": take("precision"),
        "days": take("interval_days"),
    }
    day = datetime.fromisoformat(end)
    if clock is None:
        # No time of day: the end of its (last) day, by convention. That is
        # the next local midnight (the calendar day plus one, in the zone),
        # not +24 h: the two differ when the clock changes. Never a fixed
        # offset either: before 1893 Rome kept its local mean time.
        when["instant"] = _utc(datetime.combine(day + timedelta(days=1), time(0), ROME))
        when["convention"] = END_OF_DAY
    else:
        hour, minute = (int(x) for x in clock.split(":"))
        when["instant"] = _utc(datetime.combine(day, time(hour, minute), ROME))
        when["local_time"] = clock
    lon, lat = take("lon"), take("lat")
    catalogue = take("source")
    record: dict[str, Any] = {
        "schema": "opendata-record/v2",
        "kind": "event",
        "event": "landslide",
        "id": f"{catalogue}:{take('id')}",
        "source": {
            "name": CATALOGUES[catalogue],
            "url": "https://idrogeo.isprambiente.it/",
            "licence": "CC BY-SA 4.0",
            "attribution": take("citation"),
        },
        "made_by": {"name": "ispra-idrogeo", "version": "0.14.0"},
        "time": when,
        "where": None
        if lon is None or lat is None
        else {"type": "Point", "coordinates": [lon, lat]},
        "where_accuracy_m": take("position_m"),
        "reliability": None,
        "values": {
            "movement": {"value": take("movement"), "scheme": "IFFI movement type"},
            "region": {"value": take("region"), "scheme": "ISTAT region code"},
            "province": {"value": take("province"), "scheme": "ISTAT province code"},
            "municipality": {"value": take("municipality"), "scheme": "ISTAT municipality code"},
            "main_event": {"value": take("main_event"), "meaning": "the main event of a series"},
        },
    }
    assert not left, f"keys with no place in the record: {sorted(left)}"
    return record


def assessment_record(a: dict[str, Any]) -> dict[str, Any]:
    """An ``EventAssessment`` (its fields and properties, as a dict) as a fact record."""
    start, end = a["start"], a["end"]
    return {
        "schema": "opendata-record/v2",
        "kind": "fact",
        "question": "How does this rainfall event compare with the threshold at its duration?",
        "headline": "ratio",
        "source": {"name": a["rain_source"], "licence": a["licence"]},
        "made_by": {"name": "rainfall-thresholds", "version": "0.4.0"},
        # The hours are labelled by their end: the event begins an hour before `start`.
        "time": {"first": _utc(start - timedelta(hours=1)), "last": _utc(end), "exact": True},
        "where": a["where"],
        "reliability": {
            "reliable": not a["at_least"],
            "method": "every hour of the event and of the dry break around it was measured",
            "reasons": [
                *(["hours_not_measured"] if a["unmeasured_hours"] else []),
                *(["borders_not_measured"] if a["borders_unmeasured"] else []),
            ],
        },
        "values": {
            "duration": {"value": a["duration_hours"], "unit": "h"},
            "total": {"value": a["total_mm"], "unit": "mm"},
            "intensity": {"value": a["intensity_mm_h"], "unit": "mm/h"},
            "threshold_intensity": {"value": a["threshold_mm_h"], "unit": "mm/h"},
            "threshold_total": {"value": a["threshold_mm"], "unit": "mm"},
            "threshold_alpha": {"value": a["alpha"], "unit": "mm/h"},
            "threshold_beta": {"value": a["beta"], "unit": "1"},
            "ratio": {
                "value": a["ratio"],
                "unit": "1",
                "meaning": "event intensity over threshold intensity; above 1 is above the line",
            },
            "excess_decades": {
                "value": a["excess_decades"],
                "unit": "1",
                "meaning": "log10 of ratio",
            },
            "unmeasured_hours": {"value": a["unmeasured_hours"], "unit": "h"},
            "borders_unmeasured": {"value": a["borders_unmeasured"]},
            "at_least": {
                "value": a["at_least"],
                "meaning": "true: the measured rain is a lower bound of the real one",
            },
            "rain_source": {"value": a["rain_source"], "scheme": "label given by the caller"},
        },
        "notes": [
            "A threshold exceeded is not an alert. The official alert is the criticality "
            "bulletin of the Dipartimento della Protezione Civile."
        ],
    }


#: ``event_against_threshold`` of rainfall-thresholds 0.4.0 on a fixed hourly
#: series (2.0, 5.5, 9.0, not measured, 12.5, 7.0, 3.0, 1.5 mm from 06:00 UTC of
#: 20 November 2026), against ITALICA southern (alpha 8.754, beta 0.6449), with
#: a dry break of 48 h. The series is made up; the numbers are the library's.
ASSESSMENT: dict[str, Any] = {
    "start": datetime(2026, 11, 20, 7, tzinfo=UTC),
    "end": datetime(2026, 11, 20, 14, tzinfo=UTC),
    "duration_hours": 8.0,
    "total_mm": 40.5,
    "unmeasured_hours": 1,
    "rain_source": "rain gauge",
    "intensity_mm_h": 5.0625,
    "alpha": 8.754,
    "beta": 0.6449,
    "borders_unmeasured": True,
    "threshold_mm_h": 2.2898329986183925,
    "threshold_mm": 18.31866398894714,
    "ratio": 2.210859919939376,
    "excess_decades": 0.34456122655673416,
    "at_least": True,
    "licence": "CC0-1.0",
    "where": {"type": "Point", "coordinates": [14.1205, 40.8225]},
}
