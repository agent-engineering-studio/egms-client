from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from egms_client.mosaic import Mosaic, to_cog
from egms_client.reliability import NOT_MEASURED, coverage_map, trust

#: A 4 km square in EPSG:3035, inside tile E47N19.
LEFT, TOP = 4_750_000.0, 1_950_000.0
SIZE = 40
CENTRE = (LEFT + 2_000 + 50, TOP - 2_000 - 50)  # a cell centre
to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)


def _grid(tmp_path: Path, values: np.ndarray) -> Path:
    return to_cog(Mosaic(values=values.astype("float32"), left=LEFT, top=TOP), tmp_path / "U.tif")


def _centre() -> tuple[float, float]:
    lon, lat = to_lonlat.transform(*CENTRE)
    return float(lon), float(lat)


def test_a_full_neighbourhood_is_reliable(tmp_path: Path) -> None:
    tiff = _grid(tmp_path, np.full((SIZE, SIZE), -3.0))
    r = trust([tiff], *_centre(), regional_radius_m=1_000)
    assert r.velocity == -3.0
    assert r.coverage == 1.0
    assert r.reliable and r.score == 1.0 and r.reasons == ()
    assert r.fit is None  # no attributes: unknown, and it does not count
    assert r.regional_median == -3.0 and r.relative == 0.0


def test_no_cell_is_not_measured_not_zero(tmp_path: Path) -> None:
    values = np.full((SIZE, SIZE), 1.0)
    values[20, 20] = np.nan
    r = trust([_grid(tmp_path, values)], *_centre(), regional_radius_m=1_000)
    assert r.velocity is None and r.relative is None
    assert not r.reliable and r.score == 0.0
    assert r.reasons == (NOT_MEASURED,)


def test_a_lone_cell_has_a_value_but_is_not_reliable(tmp_path: Path) -> None:
    values = np.full((SIZE, SIZE), np.nan)
    values[20, 20] = 5.0
    r = trust([_grid(tmp_path, values)], *_centre(), regional_radius_m=1_000)
    assert r.velocity == 5.0
    assert r.coverage < 0.05
    assert not r.reliable
    assert "within 500 m" in r.reasons[0]


def test_a_loose_fit_lowers_the_score(tmp_path: Path) -> None:
    tiff = _grid(tmp_path, np.full((SIZE, SIZE), 2.0))
    cells = pd.DataFrame(
        {
            "easting": [CENTRE[0]],
            "northing": [CENTRE[1]],
            "rmse_ts": [5.4],
            "mean_velocity_std": [0.1],
        }
    )
    r = trust([tiff], *_centre(), attributes=cells, regional_radius_m=1_000)
    assert r.rmse_mm == 5.4 and r.velocity_std == 0.1
    assert r.fit == pytest.approx(0.2)
    assert r.score == pytest.approx(0.2) and not r.reliable
    assert "rmse 5.4 mm" in r.reasons[0]


def test_the_regional_median_shows_a_local_anomaly(tmp_path: Path) -> None:
    values = np.full((SIZE, SIZE), 1.5)
    values[18:23, 18:23] = 20.0
    r = trust([_grid(tmp_path, values)], *_centre(), regional_radius_m=2_000)
    assert r.regional_median == 1.5
    assert r.relative == 18.5


def test_coverage_map_counts_the_disk_and_the_edges() -> None:
    values = np.full((7, 7), 1.0)
    values[3, 3] = np.nan
    share = coverage_map(values, radius_m=100)  # the cell and its 4 neighbours
    assert share.shape == (7, 7)
    assert share[3, 3] == pytest.approx(4 / 5)
    assert share[0, 0] == pytest.approx(1.0)  # only cells inside the grid count
    assert share[2, 3] == pytest.approx(4 / 5)
