"""Limen's per-cell aggregation, frozen for the parity test of ``egms_client.cells``.

Copied from limen ``src/limen/integrations/egms/aggregate.py`` (``per_cella``)
at commit 72ba418, with Limen's row type replaced by a dict. The package
never imports Limen (tests/test_package.py); this copy is test data.

``leggi_attributi``, ``salva_attributi`` and ``su_griglia`` are Limen's own
cache of a tile's attributes (``aggregate.py`` and ``clms.py`` at commit
89e1932, logging removed): what ``fetch_tile(keep=["attributes"])``,
``tables.read_csv`` and ``cells.on_grid`` replace.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

PASSO_M = 100.0

COLONNE_ATTRIBUTI = ("acceleration", "seasonality")


def leggi_attributi(csv: Any) -> dict[str, Any]:
    import pandas as pd

    tabella = pd.read_csv(csv, usecols=["easting", "northing", *COLONNE_ATTRIBUTI])
    return {c: tabella[c].to_numpy(dtype="float64") for c in tabella.columns}


def salva_attributi(csv: Path, path: Path) -> None:
    try:
        colonne = leggi_attributi(csv)
    except ValueError:
        colonne = {c: np.empty(0) for c in ("easting", "northing", *COLONNE_ATTRIBUTI)}
    with path.open("wb") as f:
        np.savez(f, **colonne)


def su_griglia(attributi: list[Path], colonna: str, come: Any) -> Any:
    righe, colonne = come.values.shape
    out = np.full((righe, colonne), np.nan, dtype="float32")
    for path in attributi:
        with np.load(path) as a:
            col = np.floor((a["easting"] - come.left) / come.pixel).astype(np.int64)
            riga = np.floor((come.top - a["northing"]) / come.pixel).astype(np.int64)
            dentro = (riga >= 0) & (riga < righe) & (col >= 0) & (col < colonne)
            out[riga[dentro], col[dentro]] = a[colonna][dentro]
    return out


def _p90_modulo(a: Any, b: Any) -> float | None:
    validi = ~np.isnan(a) & ~np.isnan(b)
    if not validi.any():
        return None
    return float(np.percentile(np.sqrt(a[validi] ** 2 + b[validi] ** 2), 90))


def per_cella(
    celle: list[tuple[str, float, float, float, float]],
    verticale: Any,
    est: Any,
    left: float,
    top: float,
    accelerazione_verticale: Any = None,
    accelerazione_est: Any = None,
) -> list[dict[str, Any]]:
    v, e = verticale, est
    out: list[dict[str, Any]] = []
    for cell_id, minx, miny, maxx, maxy in celle:
        c0 = max(0, math.ceil((minx - left) / PASSO_M - 0.5))
        c1 = min(v.shape[1], math.ceil((maxx - left) / PASSO_M - 0.5))
        r0 = max(0, math.ceil((top - maxy) / PASSO_M - 0.5))
        r1 = min(v.shape[0], math.ceil((top - miny) / PASSO_M - 0.5))
        vv = v[r0:r1, c0:c1]
        ee = e[r0:r1, c0:c1]
        entrambi = ~np.isnan(vv) & ~np.isnan(ee)
        n = int(entrambi.sum())
        if n == 0:
            out.append({"cell_id": cell_id, "scatterer_count": 0})
            continue
        modulo = np.sqrt(vv[entrambi] ** 2 + ee[entrambi] ** 2)
        accelerazione = None
        if accelerazione_verticale is not None and accelerazione_est is not None:
            accelerazione = _p90_modulo(
                accelerazione_verticale[r0:r1, c0:c1], accelerazione_est[r0:r1, c0:c1]
            )
        out.append(
            {
                "cell_id": cell_id,
                "insar_velocity_mmy": float(np.percentile(modulo, 90)),
                "insar_accel_mmy2": accelerazione,
                "velocita_verticale_mmy": float(np.median(vv[entrambi])),
                "velocita_est_mmy": float(np.median(ee[entrambi])),
                "scatterer_count": n,
            }
        )
    return out
