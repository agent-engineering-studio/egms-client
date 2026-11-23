"""egms_client.cells: per-cell statistics, missing kept missing, signs kept."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from limen_reference import per_cella

from egms_client.cells import Cell, CellStats, on_grid, per_cell, square_cells, to_frame
from egms_client.mosaic import Mosaic, mosaic
from egms_client.reliability import NOT_MEASURED

DATA = Path(__file__).parent.parent / "benchmarks" / "data"


def _grid(values: list[list[float]], left: float = 0.0, top: float = 300.0) -> Mosaic:
    return Mosaic(np.array(values, dtype="float32"), left, top)


def test_square_cells_cover_the_box_on_the_origin_grid() -> None:
    cells = square_cells(1_500, 2_500, 3_200, 3_100, size_m=1_000)
    assert [c.id for c in cells] == [
        "1000m_E1000_N2000",
        "1000m_E2000_N2000",
        "1000m_E3000_N2000",
        "1000m_E1000_N3000",
        "1000m_E2000_N3000",
        "1000m_E3000_N3000",
    ]
    assert cells[0] == Cell("1000m_E1000_N2000", 1000, 2000, 2000, 3000)


def test_an_empty_cell_is_not_measured_not_zero() -> None:
    up = _grid([[math.nan] * 3] * 3)
    (s,) = per_cell([Cell("a", 0, 0, 300, 300)], up)
    assert s == CellStats("a", 9, 0, 0.0, reasons=(NOT_MEASURED,))
    assert s.vertical_median is None and s.score == 0 and not s.reliable


def test_a_cell_outside_the_grid_has_no_pixels() -> None:
    (s,) = per_cell([Cell("far", 5_000, 5_000, 6_000, 6_000)], _grid([[1.0]]))
    assert (s.pixels, s.valid_pixels, s.vertical_median) == (0, 0, None)


def test_signs_and_tails_are_kept() -> None:
    up = _grid([[-10.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 12.0]])
    (s,) = per_cell([Cell("c", 0, 0, 300, 300)], up)
    assert s.vertical_median == 1.0
    assert s.vertical_p10 is not None and s.vertical_p10 < 0
    assert s.vertical_p90 is not None and s.vertical_p90 > 1
    assert s.east_median is None and s.speed_p90 is None


def test_acceleration_is_signed_and_on_the_velocity_mask() -> None:
    nan = math.nan
    up = _grid([[1.0, 1.0, nan]])
    acc = np.array([[-2.0, -1.0, 50.0]], dtype="float32")  # the 50 has no velocity
    (s,) = per_cell([Cell("c", 0, 200, 300, 300)], up, acceleration=acc)
    assert s.acceleration_median == -1.5
    assert s.acceleration_p10 is not None and s.acceleration_p10 < -1.5
    assert (s.pixels, s.valid_pixels, s.coverage) == (3, 2, 0.667)


def test_coverage_and_fit_make_the_score() -> None:
    nan = math.nan
    sparse = _grid([[1.0, nan, nan, nan, nan, nan, nan, nan, nan, nan]], top=100)
    (s,) = per_cell([Cell("s", 0, 0, 1000, 100)], sparse)
    assert (s.coverage, s.score, s.reliable) == (0.1, 0.2, False)
    assert "10%" in s.reasons[0]

    full = _grid([[1.0, 1.0]], top=100)
    loose = np.array([[4.5, 4.5]], dtype="float32")
    (f,) = per_cell([Cell("f", 0, 0, 200, 100)], full, rmse=loose)
    assert (f.coverage, f.rmse_median, f.score, f.reliable) == (1.0, 4.5, 0.5, True)


def test_grids_must_match() -> None:
    up = _grid([[1.0, 1.0]])
    with pytest.raises(ValueError, match="same grid"):
        per_cell([], up, _grid([[1.0, 1.0]], left=100))
    with pytest.raises(ValueError, match="shape"):
        per_cell([], up, acceleration=np.zeros((2, 2)))


def test_on_grid_puts_each_row_on_its_pixel() -> None:
    import pandas as pd

    like = _grid([[0.0, 0.0], [0.0, 0.0]], left=1000, top=2200)
    frame = pd.DataFrame(
        {"easting": [1050.0, 1150.0, 9999.0], "northing": [2150.0, 2050.0, 0.0], "x": [1, 2, 3]}
    )
    grid = on_grid(frame, "x", like)
    assert grid[0, 0] == 1 and grid[1, 1] == 2
    assert np.isnan(grid[0, 1]) and np.isnan(grid[1, 0])


def test_to_frame_keeps_missing_as_nan() -> None:
    up = _grid([[1.0, math.nan]], top=100)
    stats = per_cell([Cell("a", 0, 0, 100, 100), Cell("b", 100, 0, 200, 100)], up)
    frame = to_frame(stats)
    assert list(frame.id) == ["a", "b"]
    assert frame.vertical_median.iloc[0] == 1.0 and np.isnan(frame.vertical_median.iloc[1])
    assert frame.reasons.iloc[1] == NOT_MEASURED


def _parity(up: Mosaic, east: Mosaic, cells: list[Cell]) -> int:
    ours = per_cell(cells, up, east)
    theirs = per_cella(
        [(c.id, c.minx, c.miny, c.maxx, c.maxy) for c in cells],
        up.values,
        east.values,
        up.left,
        up.top,
    )
    measured = 0
    for a, b in zip(ours, theirs, strict=True):
        assert a.valid_pixels == b["scatterer_count"]
        if a.valid_pixels == 0:
            assert a.vertical_median is None
            continue
        measured += 1
        assert a.vertical_median == pytest.approx(b["velocita_verticale_mmy"])
        assert a.east_median == pytest.approx(b["velocita_est_mmy"])
        assert a.speed_p90 == pytest.approx(b["insar_velocity_mmy"])
    return measured


def test_parity_with_limen_on_random_grids_and_unaligned_cells() -> None:
    rng = np.random.default_rng(7)
    v = rng.normal(0, 5, (40, 50)).astype("float32")
    e = rng.normal(0, 5, (40, 50)).astype("float32")
    v[rng.random(v.shape) < 0.4] = np.nan
    e[rng.random(e.shape) < 0.1] = np.nan
    v[:12, :12] = np.nan  # a blind corner
    up, east = Mosaic(v, 4_000_030.0, 2_004_000.0), Mosaic(e, 4_000_030.0, 2_004_000.0)
    cells = square_cells(4_000_030, 2_000_000, 4_005_030, 2_004_000, origin=(37.0, 11.0))
    assert _parity(up, east, cells) > 0


@pytest.mark.parametrize("case", ["ancona", "murge"])
def test_parity_with_limen_on_the_benchmark_crops(case: str) -> None:
    import rasterio

    folder = DATA / case

    with rasterio.open(folder / "U.tif") as src:
        minx, miny, maxx, maxy = src.bounds
    box = {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
    up, east = mosaic([folder / "U.tif"], **box), mosaic([folder / "E.tif"], **box)
    cells = square_cells(minx, miny, maxx, maxy)
    assert _parity(up, east, cells) >= 10
