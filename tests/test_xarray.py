from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from egms_client.mosaic import Mosaic, to_xarray
from egms_client.tables import dates, read_csv
from egms_client.tables import to_xarray as series_to_xarray

xr = pytest.importorskip("xarray")
pytest.importorskip("pyproj")

FIXTURES = Path(__file__).parent / "fixtures"
L3 = FIXTURES / "EGMS_L3_E47N19_100km_U_2020_2025_1.csv"


def test_a_mosaic_becomes_a_dataarray_on_pixel_centres() -> None:
    values = np.array([[1.0, np.nan, 3.0], [4.0, 5.0, 6.0]], dtype="float32")
    da = to_xarray(Mosaic(values=values, left=4_700_000.0, top=2_000_000.0))
    assert da.dims == ("y", "x")
    assert da.x.values.tolist() == [4_700_050.0, 4_700_150.0, 4_700_250.0]
    assert da.y.values.tolist() == [1_999_950.0, 1_999_850.0]
    assert da.attrs["units"] == "mm/year"
    assert da.attrs["grid_mapping"] == "spatial_ref"
    assert "Lambert" in da.spatial_ref.attrs["spatial_ref"]
    assert da.sel(x=4_700_250.0, y=1_999_850.0).item() == 6.0
    assert np.isnan(da.values[0, 1])


def test_the_crs_is_read_back_by_pyproj() -> None:
    from pyproj import CRS

    da = to_xarray(Mosaic(values=np.zeros((1, 1), dtype="float32"), left=0.0, top=100.0))
    assert CRS.from_cf(da.spatial_ref.attrs).to_epsg() == 3035


def test_series_become_a_dataarray_over_pid_and_time() -> None:
    frame = read_csv(L3)
    da = series_to_xarray(frame)
    assert da.dims == ("pid", "time")
    assert da.shape == (3, len(dates(frame)))
    assert da.time.values[0] == np.datetime64(dates(frame)[0], "ns")
    assert da.attrs["units"] == "mm"
    first = str(frame["pid"].iloc[0])
    assert float(da.sel(pid=first).mean_velocity) == pytest.approx(frame["mean_velocity"].iloc[0])
    assert da.easting.dims == ("pid",)
    fast = da.where(da.mean_velocity < 0, drop=True)
    assert set(fast.pid.values) == set(frame.loc[frame.mean_velocity < 0, "pid"].astype(str))


def test_a_table_without_series_is_refused() -> None:
    with pytest.raises(ValueError, match="no date columns"):
        series_to_xarray(read_csv(L3, series=False))
