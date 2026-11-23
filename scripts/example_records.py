"""The egms-client records in examples/records, made from the benchmark crops.

    uv run python scripts/example_records.py

No key, no download. tests/test_records.py checks that ``to_records`` still
gives these files, so a change of shape shows up as a diff here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from egms_client.facts import area, moving_points, to_records, velocity

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "benchmarks" / "data"
OUT = ROOT / "examples" / "records"
RELEASE = "2020-2025"
BOLOGNA = (11.25, 44.45, 11.55, 44.60)


def made() -> dict[str, list[dict[str, Any]]]:
    """Each example file and the records it holds."""
    flegrei, umbra, bologna = (
        DATA / n / "U.tif" for n in ("campi-flegrei", "foresta-umbra", "bologna")
    )
    return {
        "egms-rione-terra.json": to_records(velocity([flegrei], 14.1205, 40.8225, release=RELEASE)),
        "egms-foresta-umbra-not-measured.json": to_records(
            velocity([umbra], 15.935, 41.8239, release=RELEASE)
        ),
        "egms-bologna-area.json": to_records(area([bologna], BOLOGNA, release=RELEASE)),
        "egms-bologna-moving.json": to_records(
            moving_points([bologna], BOLOGNA, release=RELEASE, limit=3)
        ),
    }


def text(records: list[dict[str, Any]]) -> str:
    body = records[0] if len(records) == 1 else records
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    for name, records in made().items():
        (OUT / name).write_text(text(records), encoding="utf-8")
        print(f"{name}: {len(records)} record(s)")
