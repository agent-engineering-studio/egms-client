"""The figures of the Open Data episode on agentengineering.it, in Italian and English.

    uv run --group examples python scripts/blog_figures.py

Made from the crops of the benchmark (benchmarks/data/): no key, no download.
They go to docs/images/blog/, and the article links them from GitHub. Every
number on a figure is printed too, so the text can quote it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from egms_client.cells import on_grid, per_cell, square_cells
from egms_client.mosaic import Mosaic, lonlat_to_xy, mosaic

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "benchmarks" / "data"
OUT = ROOT / "docs" / "images" / "blog"
CREDIT = {
    "it": "Dati: EGMS 2020-2025, Copernicus Land Monitoring Service, © Unione europea.",
    "en": "Data: EGMS 2020-2025, Copernicus Land Monitoring Service, © European Union.",
}

plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})


def _crop(name: str, component: str = "U") -> Mosaic:
    tiff = DATA / name / f"{component}.tif"
    with rasterio.open(tiff) as src:
        left, bottom, right, top = src.bounds
    return mosaic([tiff], minx=left, miny=bottom, maxx=right, maxy=top)


def _save(fig: plt.Figure, name: str, lang: str) -> None:
    fig.text(0.01, 0.01, CREDIT[lang], fontsize=8, color="#5a6772")
    fig.savefig(OUT / f"{name}-{lang}.png", dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def pozzuoli() -> None:
    m = _crop("campi-flegrei")
    rows, cols = m.values.shape
    extent = (m.left, m.left + cols * m.pixel, m.top - rows * m.pixel, m.top)
    x, y = lonlat_to_xy(14.1205, 40.8225)
    text = {
        "it": (
            "Il suolo sale intorno a Pozzuoli, 2020-2025",
            "velocità verticale (mm/anno)",
            "Rione Terra\n+145,2 mm/anno",
            "grigio: nessuna misura (il mare, i boschi, i campi)",
        ),
        "en": (
            "The ground rises around Pozzuoli, 2020-2025",
            "vertical velocity (mm/year)",
            "Rione Terra\n+145.2 mm/year",
            "grey: no measurement (the sea, woods, fields)",
        ),
    }
    for lang, (title, label, point, grey) in text.items():
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.set_facecolor("#c9ccd1")
        shown = ax.imshow(m.values, extent=extent, cmap="RdBu_r", vmin=-150, vmax=150)
        ax.plot(x, y, "o", ms=9, mfc="none", mec="black", mew=2)
        ax.annotate(
            point,
            (x, y),
            xytext=(x - 6500, y - 4500),
            fontsize=10,
            arrowprops={"arrowstyle": "-", "color": "black"},
            bbox={"boxstyle": "round", "fc": "white", "ec": "none"},
        )
        ax.set_title(title, loc="left")
        ax.text(0.99, 0.02, grey, transform=ax.transAxes, ha="right", fontsize=9, color="#17324d")
        # Not set_axis_off: it hides the grey background, the colour of "no measurement".
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.colorbar(shown, ax=ax, label=label, shrink=0.8)
        _save(fig, "pozzuoli", lang)


def posatora() -> None:
    series = pd.read_parquet(DATA / "ancona" / "descending-series.parquet")
    dates = [c for c in series.columns if str(c).isdigit()]
    when = pd.to_datetime(dates, format="%Y%m%d")
    ordered = series.sort_values("mean_velocity")
    fastest, stillest = ordered.head(30), ordered.iloc[(ordered.mean_velocity.abs()).argsort()[:30]]
    fast = (fastest[dates].sub(fastest[dates[0]], axis=0)).median().to_numpy()
    still = (stillest[dates].sub(stillest[dates[0]], axis=0)).median().to_numpy()
    up = _crop("ancona")
    cell = float(
        up.values[
            int((up.top - lonlat_to_xy(13.478, 43.607)[1]) // 100),
            int((lonlat_to_xy(13.478, 43.607)[0] - up.left) // 100),
        ]
    )
    print(
        f"posatora: {len(series)} points within 1.5 km; the 30 fastest move "
        f"{fast[-1]:.1f} mm in the window (median), mean velocity "
        f"{fastest.mean_velocity.median():.1f} mm/year; the L3 cell at the slope says "
        f"{cell:+.2f} mm/year"
    )
    text = {
        "it": (
            "Il versante della Posatora, Ancona: i punti che si muovono",
            "spostamento lungo la linea di vista (mm)",
            "i 30 punti più veloci",
            "i 30 punti più fermi",
        ),
        "en": (
            "The Posatora slope, Ancona: the points that move",
            "displacement along the line of sight (mm)",
            "the 30 fastest points",
            "the 30 stillest points",
        ),
    }
    for lang, (title, label, a, b) in text.items():
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(when, fast, color="#cb181d", label=a)
        ax.plot(when, still, color="#7a8290", label=b)
        ax.axhline(0, color="black", lw=0.6)
        ax.set_title(title, loc="left")
        ax.set_ylabel(label)
        ax.legend(frameon=False)
        _save(fig, "posatora", lang)


def acceleration() -> None:
    up, east = _crop("murge"), _crop("murge", "E")
    a_u = on_grid(pd.read_parquet(DATA / "murge" / "l3.parquet"), "acceleration", up)
    a_e = on_grid(pd.read_parquet(DATA / "murge" / "l3-E.parquet"), "acceleration", east)
    rows, cols = up.values.shape
    left, top = up.left, up.top
    cells = [
        c
        for c in square_cells(left, top - rows * 100, left + cols * 100, top)
        if c.minx >= left
        and c.maxx <= left + cols * 100
        and c.miny >= top - rows * 100
        and c.maxy <= top
    ]
    signed = [s.acceleration_median for s in per_cell(cells, up, acceleration=a_u)]
    signed = np.array([s for s in signed if s is not None])
    magnitude = Mosaic(np.sqrt(a_u**2 + a_e**2), left, top)
    p90 = np.array(
        [s.vertical_p90 for s in per_cell(cells, magnitude) if s.vertical_p90 is not None]
    )
    print(
        f"murge: {len(signed)} km; signed median {np.median(signed):+.3f}, "
        f"{(signed < 0).sum()} negative, {(signed > 0).sum()} positive; "
        f"p90 of the magnitude, median {np.median(p90):.2f}"
    )
    text = {
        "it": (
            "Le Murge non si muovono: l'accelerazione, con il segno e senza",
            f"con il segno: mediana {np.median(signed):+.2f}".replace(".", ","),
            f"senza segno (modulo): mediana {np.median(p90):.2f}".replace(".", ","),
            "accelerazione verticale (mm/anno²)",
            "modulo dell'accelerazione (mm/anno²)",
            "chilometri quadrati",
        ),
        "en": (
            "The Murge do not move: the acceleration, with its sign and without",
            f"signed: median {np.median(signed):+.2f}",
            f"unsigned (magnitude): median {np.median(p90):.2f}",
            "vertical acceleration (mm/year²)",
            "magnitude of the acceleration (mm/year²)",
            "square kilometres",
        ),
    }
    for lang, (title, left_t, right_t, left_x, right_x, ylabel) in text.items():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
        axes[0].hist(signed, bins=30, color="#4292c6")
        axes[1].hist(p90, bins=30, color="#cb181d")
        for ax, sub, xl in ((axes[0], left_t, left_x), (axes[1], right_t, right_x)):
            ax.axvline(0, color="black", lw=1)
            ax.set_title(sub, fontsize=10)
            ax.set_xlabel(xl)
        axes[0].set_ylabel(ylabel)
        fig.suptitle(title, x=0.01, ha="left")
        fig.tight_layout()
        _save(fig, "accelerazione", lang)


def record_v2() -> None:
    """A real dated landslide as an opendata-record/v2 event: what each new field says."""
    import json

    record = json.loads(
        (ROOT / "examples" / "records-v2" / "ispra-idrogeo-landslide-interval.json").read_text()
    )
    lines = [
        (
            '"kind": "event",  "event": "landslide"',
            ("un fatto accaduto, non una misura", "something that happened, not a measurement"),
        ),
        (
            f'"first": "{record["time"]["first"]}",  "last": "{record["time"]["last"]}"',
            ("la fonte dice solo «2010»", 'the source says only "2010"'),
        ),
        (
            f'"precision": "interval",  "days": {record["time"]["days"]}',
            ("quanto è larga la data", "how wide the date is"),
        ),
        (
            f'"instant": "{record["time"]["instant"]}"',
            ("l'istante da usare con la pioggia", "the instant to use with the rain"),
        ),
        (
            f'"convention": "{record["time"]["convention"]}"',
            ("è una convenzione, e lo dice", "it is a convention, and says so"),
        ),
        (
            '"where_accuracy_m": null',
            (
                "la fonte non dice quanto è preciso il punto",
                "the source does not say how exact the point is",
            ),
        ),
        (
            '"movement": {"value": 0, "scheme": "IFFI movement type"}',
            ("un codice, con il suo elenco", "a code, with its list"),
        ),
        (
            '"main_event": {"value": null}',
            (
                "sì, no, o non si sa: mai falso al posto di vuoto",
                "yes, no, or not known: never false for empty",
            ),
        ),
    ]
    title = {
        "it": "Una frana dell'inventario IFFI datata «2010», scritta come record",
        "en": 'A landslide of the IFFI inventory dated "2010", written as a record',
    }
    credit = "ISPRA - Regioni e Province Autonome, IFFI, idrogeo.isprambiente.it, CC BY-SA 4.0."
    for i, lang in enumerate(("it", "en")):
        fig, ax = plt.subplots(figsize=(12.5, 4.6))
        ax.axis("off")
        ax.set_title(title[lang], loc="left", fontsize=13, fontweight="bold")
        for row, (code, note) in enumerate(lines):
            y = 0.92 - row * 0.115
            ax.text(0.0, y, code, family="monospace", fontsize=10.5, va="center")
            ax.text(0.62, y, note[i], fontsize=10.5, va="center", color="#b3541e")
        fig.text(0.01, 0.01, f"{('Dati', 'Data')[i]}: {credit}", fontsize=8, color="#5a6772")
        fig.savefig(OUT / f"record-v2-{lang}.png", dpi=110, bbox_inches="tight", facecolor="white")
        plt.close(fig)
    print("record-v2:", record["id"], record["time"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    record_v2()
    pozzuoli()
    posatora()
    acceleration()
    print(f"written: {sorted(p.name for p in OUT.glob('*.png'))}")
