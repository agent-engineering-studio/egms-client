from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from egms_client.decompose import LosGrid, decompose, grid_los
from egms_client.mosaic import Mosaic

#: LOS unit vectors (ground to satellite) seen near Ancona on 2026-11-03.
ASCENDING = (-0.687, 0.720)
DESCENDING = (0.648, 0.752)
BOUNDS = {"minx": 4_700_000.0, "miny": 1_900_000.0, "maxx": 4_700_300.0, "maxy": 1_900_200.0}


def _points(los: tuple[float, float], up: Any, east: Any, coherence: float = 0.9) -> dict[str, Any]:
    """Two points per cell of a 2 x 3 grid, each moving (east, up) along the given LOS."""
    xs, ys, v = [], [], []
    for r in range(2):
        for c in range(3):
            for dx in (20.0, 70.0):
                xs.append(BOUNDS["minx"] + c * 100 + dx)
                ys.append(BOUNDS["maxy"] - r * 100 - 50)
                v.append(east[r][c] * los[0] + up[r][c] * los[1])
    n = len(xs)
    return {
        "easting": np.array(xs),
        "northing": np.array(ys),
        "mean_velocity": np.array(v),
        "los_east": np.full(n, los[0]),
        "los_up": np.full(n, los[1]),
        "temporal_coherence": np.full(n, coherence),
    }


UP = [[-10.0, 0.0, 5.0], [2.0, -3.0, 160.0]]
EAST = [[1.0, -2.0, 0.0], [4.0, 0.5, -6.0]]


def test_two_geometries_give_back_vertical_and_east_west() -> None:
    a = grid_los(_points(ASCENDING, UP, EAST), **BOUNDS)
    d = grid_los(_points(DESCENDING, UP, EAST), **BOUNDS)
    up, east = decompose(a, d)
    assert np.allclose(up.values, UP, atol=1e-3)
    assert np.allclose(east.values, EAST, atol=1e-3)
    assert (up.left, up.top, up.pixel) == (4_700_000.0, 1_900_200.0, 100.0)


def test_the_grid_averages_points_and_counts_them() -> None:
    g = grid_los(_points(ASCENDING, UP, EAST), **BOUNDS)
    assert g.velocity.values.shape == (2, 3)
    assert g.count.tolist() == [[2, 2, 2], [2, 2, 2]]
    assert np.allclose(g.east, ASCENDING[0]) and np.allclose(g.up, ASCENDING[1])


def test_incoherent_and_outside_points_are_left_out() -> None:
    points = _points(ASCENDING, UP, EAST, coherence=0.5)
    g = grid_los(points, **BOUNDS)
    assert g.count.sum() == 0 and np.isnan(g.velocity.values).all()
    points = _points(ASCENDING, UP, EAST)
    points["easting"] = points["easting"] + 10_000
    assert grid_los(points, **BOUNDS).count.sum() == 0


def test_a_cell_seen_by_one_geometry_only_is_nan() -> None:
    a = grid_los(_points(ASCENDING, UP, EAST), **BOUNDS)
    points = _points(DESCENDING, UP, EAST)
    points["temporal_coherence"][:2] = 0.1  # the first cell loses its two points
    d = grid_los(points, **BOUNDS)
    up, _ = decompose(a, d)
    assert np.isnan(up.values[0, 0])
    assert np.isfinite(up.values[0, 1])


def test_different_grids_are_refused() -> None:
    a = grid_los(_points(ASCENDING, UP, EAST), **BOUNDS)
    d = grid_los(_points(DESCENDING, UP, EAST), **{**BOUNDS, "maxx": 4_700_400.0})
    with pytest.raises(ValueError, match="same cells"):
        decompose(a, d)


def test_two_grids_looking_the_same_way_are_refused() -> None:
    a = grid_los(_points(ASCENDING, UP, EAST), **BOUNDS)
    with pytest.raises(ValueError, match="one ascending, one descending"):
        decompose(a, a)


def test_a_los_grid_is_a_plain_record() -> None:
    m = Mosaic(values=np.zeros((1, 1), dtype="float32"), left=0.0, top=0.0)
    g = LosGrid(velocity=m, east=np.zeros((1, 1)), up=np.ones((1, 1)), count=np.ones((1, 1)))
    assert g.velocity is m
