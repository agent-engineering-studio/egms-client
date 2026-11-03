"""The CSVs of the archive as tables. Needs the ``tables`` extra.

Every ZIP holds a CSV with one row per measurement point (L2A, L2B) or per
100 m cell (L3): its attributes, then one column per acquisition date
(``20251119``) with the displacement in millimetres since the first date.

* L2 columns start ``pid, mp_type, latitude, longitude, easting, northing,
  height_ortho, ...``; ``mean_velocity`` is along the satellite's line of
  sight (``los_east``, ``los_north``, ``los_up`` give its direction);
* L3 columns start ``pid, easting, northing, height_ortho, ...``;
  ``mean_velocity`` is vertical (``U``) or east-west (``E``).

``easting`` / ``northing`` are EPSG:3035 metres in both, so
:func:`to_geoparquet` writes one geometry for every level. Values are mm and
mm/year. An L3 CSV is ~250 MB for ~170,000 cells and ~300 dates.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

#: A date column: ``YYYYMMDD``.
DATE_COLUMN = re.compile(r"\d{8}")


def read_csv(path: Path, *, series: bool = True, columns: Sequence[str] | None = None) -> Any:
    """A CSV of the archive as a ``pandas.DataFrame``.

    ``series=False`` skips the date columns (much less memory); ``columns``
    keeps only those attributes (``pid`` is always kept). Dates are float32.
    """
    import pandas as pd

    with path.open() as f:
        header = f.readline().strip().split(",")
    names = [c for c in header if not DATE_COLUMN.fullmatch(c)]
    if columns is not None:
        unknown = sorted(set(columns) - set(names))
        if unknown:
            raise ValueError(f"{path.name} has no columns {unknown}: {names}")
        names = [c for c in names if c == "pid" or c in columns]
    dates = [c for c in header if DATE_COLUMN.fullmatch(c)] if series else []
    dtypes = dict.fromkeys(dates, "float32")
    dtypes |= {c: "string" for c in ("pid", "mp_type") if c in names}
    return pd.read_csv(path, usecols=[*names, *dates], dtype=dtypes, engine="pyarrow")


def dates(frame: Any) -> list[date]:
    """The acquisition dates of a table, in its column order."""
    return [_date(c) for c in frame.columns if DATE_COLUMN.fullmatch(str(c))]


def attributes(frame: Any) -> Any:
    """The table without its date columns."""
    return frame[[c for c in frame.columns if not DATE_COLUMN.fullmatch(str(c))]]


def series_long(frame: Any) -> Any:
    """One row per point and date: ``pid``, ``date``, ``displacement_mm``."""
    import pandas as pd

    columns = [c for c in frame.columns if DATE_COLUMN.fullmatch(str(c))]
    long = frame.melt(
        id_vars=["pid"], value_vars=columns, var_name="date", value_name="displacement_mm"
    )
    long["date"] = pd.to_datetime(long["date"], format="%Y%m%d")
    return long


def to_xarray(frame: Any) -> Any:
    """The series of a table as an ``xarray.DataArray`` over ``(pid, time)``.

    Values are the displacement in mm (float32). Every attribute column
    (``easting``, ``mean_velocity``, ...) becomes a coordinate along ``pid``,
    so points can be selected by them. Needs ``xarray``.
    """
    import numpy as np
    import xarray as xr

    columns = [c for c in frame.columns if DATE_COLUMN.fullmatch(str(c))]
    if not columns:
        raise ValueError("the table has no date columns: read it with series=True")
    others = [c for c in frame.columns if c not in columns and c != "pid"]
    return xr.DataArray(
        frame[columns].to_numpy(dtype="float32"),
        dims=("pid", "time"),
        coords={
            "pid": frame["pid"].astype(str).to_numpy(),
            "time": np.array(dates(frame), dtype="datetime64[ns]"),
            **{c: ("pid", frame[c].to_numpy()) for c in others},
        },
        name="displacement",
        attrs={"units": "mm", "source": "Copernicus EGMS"},
    )


def to_geoparquet(frame: Any, path: Path) -> Path:
    """Write a table as GeoParquet: points in EPSG:3035 from ``easting`` / ``northing``.

    Plain Parquet readers see the columns; GIS tools (GeoPandas, QGIS,
    DuckDB spatial) also see the ``geometry``. Written to ``.part`` first.
    """
    import pyarrow as pa

    return _write_geoparquet(pa.Table.from_pandas(frame, preserve_index=False), path)


def csv_to_geoparquet(csv: Path, parquet: Path | None = None, *, series: bool = True) -> Path:
    """A CSV of the archive straight to GeoParquet, next to it by default.

    Streamed in blocks with pyarrow alone, so memory stays flat however large
    the CSV: an L3 CSV of 250 MB becomes ~60 MB of Parquet. The file carries
    no bbox (optional in GeoParquet), as it is not known before the end.
    """
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq

    with csv.open() as f:
        header = f.readline().strip().split(",")
    if not {"easting", "northing"} <= set(header):
        raise ValueError(f"{csv.name} has no easting/northing: not a CSV of the archive")
    names = [c for c in header if series or not DATE_COLUMN.fullmatch(c)]
    types = {c: pa.float32() for c in header if DATE_COLUMN.fullmatch(c)}
    types |= {c: pa.string() for c in ("pid", "mp_type") if c in header}
    reader = pacsv.open_csv(
        csv,
        read_options=pacsv.ReadOptions(block_size=16 << 20),
        convert_options=pacsv.ConvertOptions(column_types=types, include_columns=names),
    )
    path = parquet or csv.with_suffix(".parquet")
    partial = path.with_name(f"{path.name}.part")
    schema = reader.schema.append(pa.field("geometry", pa.binary()))
    schema = schema.with_metadata({b"geo": json.dumps(_geo_metadata(None)).encode()})
    try:
        with pq.ParquetWriter(partial, schema, compression="zstd") as writer:
            for batch in reader:
                x, y = _xy(batch)
                writer.write_batch(batch.append_column("geometry", _wkb(x, y)))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(path)
    return path


def _write_geoparquet(table: Any, path: Path) -> Path:
    import pyarrow.parquet as pq

    x, y = _xy(table)
    bbox = [float(x.min()), float(y.min()), float(x.max()), float(y.max())] if len(x) else None
    table = table.append_column("geometry", _wkb(x, y))
    metadata = {**(table.schema.metadata or {}), b"geo": json.dumps(_geo_metadata(bbox)).encode()}
    partial = path.with_name(f"{path.name}.part")
    pq.write_table(table.replace_schema_metadata(metadata), partial, compression="zstd")
    partial.rename(path)
    return path


def _xy(table: Any) -> tuple[Any, Any]:
    import pyarrow as pa
    import pyarrow.compute as pc

    x = pc.cast(table.column("easting"), pa.float64()).to_numpy()
    y = pc.cast(table.column("northing"), pa.float64()).to_numpy()
    return x, y


def _wkb(x: Any, y: Any) -> Any:
    """Points as WKB: byte order (1 = little endian), type (1 = point), x, y."""
    import numpy as np
    import pyarrow as pa

    n = len(x)
    wkb = np.zeros(n, dtype=[("order", "u1"), ("kind", "<u4"), ("x", "<f8"), ("y", "<f8")])
    wkb["order"], wkb["kind"], wkb["x"], wkb["y"] = 1, 1, x, y
    offsets = np.arange(n + 1, dtype="int32") * wkb.dtype.itemsize
    return pa.Array.from_buffers(
        pa.binary(), n, [None, pa.py_buffer(offsets), pa.py_buffer(wkb.tobytes())]
    )


def _geo_metadata(bbox: list[float] | None) -> dict[str, Any]:
    from pyproj import CRS

    column: dict[str, Any] = {
        "encoding": "WKB",
        "geometry_types": ["Point"],
        "crs": CRS.from_epsg(3035).to_json_dict(),
    }
    if bbox is not None:
        column["bbox"] = bbox
    return {"version": "1.1.0", "primary_column": "geometry", "columns": {"geometry": column}}


def _date(text: str) -> date:
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))
