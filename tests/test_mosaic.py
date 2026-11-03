from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from egms_client.mosaic import is_laea, mosaic

FIXTURES = Path(__file__).parent / "fixtures"

IGNF = CRS.from_wkt((FIXTURES / "crs_ignf_etrs89laea.wkt").read_text())


def _tile(path: Path, *, left: float, top: float, values: np.ndarray, crs: CRS | str) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(left, top, 100, 100),
        nodata=-9999.0,
    ) as dst:
        dst.write(values.astype("float32"), 1)
    return path


def test_an_ignf_named_tile_is_still_laea() -> None:
    assert is_laea(IGNF)
    assert is_laea(CRS.from_epsg(3035))
    assert not is_laea(CRS.from_epsg(4326))


def test_tiles_land_in_place_and_nodata_is_nan(tmp_path: Path) -> None:
    left_values = np.full((3, 3), 1.0)
    left_values[0, 0] = -9999.0
    a = _tile(
        tmp_path / "a.tif", left=4_700_000, top=1_900_300, values=left_values, crs="EPSG:3035"
    )
    b = _tile(
        tmp_path / "b.tif", left=4_700_300, top=1_900_300, values=np.full((3, 3), 2.0), crs=IGNF
    )
    m = mosaic([a, b], minx=4_700_050, miny=1_900_000, maxx=4_700_550, maxy=1_900_400)
    assert (m.left, m.top, m.pixel) == (4_700_000, 1_900_400, 100.0)
    assert m.values.shape == (4, 6)
    assert np.isnan(m.values[0]).all()  # the row above both tiles
    assert np.isnan(m.values[1, 0])  # the tile's own nodata
    assert m.values[1, 1] == 1.0
    assert (m.values[1:, 3:] == 2.0).all()


def test_a_tile_outside_the_rectangle_is_skipped(tmp_path: Path) -> None:
    far = _tile(
        tmp_path / "far.tif", left=5_000_000, top=2_000_000, values=np.ones((2, 2)), crs="EPSG:3035"
    )
    m = mosaic([far], minx=4_700_000, miny=1_900_000, maxx=4_700_200, maxy=1_900_200)
    assert np.isnan(m.values).all()


def test_another_projection_is_refused(tmp_path: Path) -> None:
    bad = _tile(tmp_path / "bad.tif", left=10, top=45, values=np.ones((2, 2)), crs="EPSG:4326")
    with pytest.raises(ValueError, match="not LAEA Europe"):
        mosaic([bad], minx=0, miny=0, maxx=100, maxy=100)
