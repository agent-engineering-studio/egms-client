"""egms_client.facts: answers as data, on the benchmark crops."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from egms_client import facts
from egms_client.check import check_claims, check_signs, check_text, words

DATA = Path(__file__).parent.parent / "benchmarks" / "data"


def test_velocity_at_rione_terra() -> None:
    f = facts.velocity(
        [DATA / "campi-flegrei" / "U.tif"],
        14.1205,
        40.8225,
        release="2020-2025",
        attributes=pd.read_parquet(DATA / "campi-flegrei" / "l3.parquet"),
    )
    assert f["velocity_mm_per_year"] == 145.2 and f["measured"]
    assert f["reliability"]["score"] == 1.0 and f["reliability"]["rmse_mm"] == 2.7
    assert f["regional"]["relative_mm_per_year"] == 118.9
    assert f["window"] == {
        "release": "2020-2025",
        "level": "L3",
        "first": "2020-12-09",
        "last": "2025-11-19",
        "exact": True,
        "text": "2020-12-09 to 2025-11-19",
        "source": "EGMS_L3_E47N19_100km_U_2020_2025_1.csv",
    }
    assert f["files"] == ["U.tif"] and "European Union" in f["licence"]
    json.dumps(f)  # plain data


def test_the_sea_is_not_measured() -> None:
    f = facts.velocity([DATA / "campi-flegrei" / "U.tif"], 14.10, 40.80, release="2020-2025")
    assert (f["measured"], f["velocity_mm_per_year"], f["reliability"]["score"]) == (False, None, 0)
    assert f["notes"][0].startswith("No cell here")


def test_area_and_moving_points_at_bologna() -> None:
    box = (11.30, 44.50, 11.55, 44.60)
    a = facts.area([DATA / "bologna" / "U.tif"], box, release="2020-2025")
    assert a["median"] == -6.3 and a["share_below"] == 0.966
    assert a["notes"][0].startswith("Only 39%")
    m = facts.moving_points([DATA / "bologna" / "U.tif"], box, release="2020-2025", limit=3)
    assert m["reference_median_mm_per_year"] == a["median"]
    assert len(m["cells"]) == 3
    speeds = [abs(c["relative_mm_per_year"]) for c in m["cells"]]
    assert speeds == sorted(speeds, reverse=True) and speeds[-1] >= 5
    assert m["moving_reliable"] <= m["moving"]


def test_moving_points_where_nothing_is_measured() -> None:
    m = facts.moving_points([], (14.0, 40.0, 14.01, 40.01), release="2020-2024")
    assert (m["measured"], m["moving"], m["cells"]) == (False, 0, [])
    assert m["window"]["exact"] is False


def test_every_answer_reads_back_clean_in_both_languages() -> None:
    box = (11.30, 44.50, 11.55, 44.60)
    tiff = [DATA / "bologna" / "U.tif"]
    for f in (
        facts.velocity(tiff, 11.40, 44.55, release="2020-2025"),
        facts.area(tiff, box, release="2020-2025"),
        facts.moving_points(tiff, box, release="2020-2025"),
    ):
        for lang in ("en", "it"):
            text = words(f, lang)
            assert check_text(text, f, lang=lang) == []
            assert check_signs(text, f, lang=lang) == []
            assert check_claims(text, f, lang=lang) == []
