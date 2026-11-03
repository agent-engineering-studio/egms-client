from __future__ import annotations

import dataclasses
import io
import json
import zipfile
from pathlib import Path

import pytest

from egms_client import (
    EgmsError,
    Query,
    ServiceKey,
    extract,
    latest_hits,
    parse_names,
    parse_search,
    parse_tile_id,
    query_body,
    split_bbox,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_bbox_query_asks_for_west_south_then_east_north() -> None:
    query = Query(levels=("L2B",), release="2020_2025", bbox=(14.4, 40.0, 15.7, 41.0))
    assert query_body(query) == {
        "releases": ["2020-2025"],
        "levels": ["L2B"],
        "bbox": [[14.4, 40.0], [15.7, 41.0]],
    }


def test_orbit_and_burst_are_zero_padded_strings() -> None:
    # The archive refuses relativeOrbit 22 and "22": only "022" is found.
    body = query_body(
        Query(
            levels=("L2A", "L2B"),
            release="2020-2025",
            relative_orbit=22,
            burst_cycle="834",
            swath="iw1",
            direction="ascending",
        )
    )
    assert body["relativeOrbit"] == "022"
    assert body["burstCycle"] == "0834"
    assert (body["swath"], body["direction"]) == ("IW1", "ascending")


def test_an_l3_query_by_tile_and_component() -> None:
    body = query_body(
        Query(levels=("L3",), release="2020-2025", tile=(47, 19), product_type="ORTHO-UP")
    )
    assert body["tileId"] == "E47N19"
    assert body["productType"] == "ORTHO-UP"


@pytest.mark.parametrize(
    "query",
    [
        Query(levels=("L3",), release="2020-2025"),
        Query(levels=("L3",), release="2020-2025", direction="ascending"),
        Query(levels=(), release="2020-2025", tile=(47, 19)),
        Query(levels=("L3",), release="2020-2025", bbox=(15.0, 40.0, 14.0, 41.0)),
    ],
)
def test_a_query_without_a_place_or_level_is_refused_before_asking(query: Query) -> None:
    with pytest.raises(ValueError):
        query_body(query)


def test_a_large_box_is_cut_into_pieces_the_archive_accepts() -> None:
    assert split_bbox((10, 40, 12, 42)) == [(10, 40, 12, 42)]
    pieces = split_bbox((6.0, 36.0, 19.0, 47.5))
    assert len(pieces) == 3 * 3
    assert all(e - w <= 5 and n - s <= 5 for w, s, e, n in pieces)
    assert (pieces[0][0], pieces[0][1], pieces[-1][2], pieces[-1][3]) == (6.0, 36.0, 19.0, 47.5)


def test_tile_ids_parse_back() -> None:
    assert parse_tile_id(" e47n19 ") == (47, 19)
    with pytest.raises(ValueError, match="not a tile id"):
        parse_tile_id("47-19")


def test_an_l2_hit_carries_its_burst() -> None:
    search = parse_search((FIXTURES / "search_bbox_L2B.json").read_bytes())
    assert search is not None
    hit = search.hits[0]
    assert hit.filename == "EGMS_L2b_124_0835_IW3_VV_2020_2025_1.zip"
    assert (hit.level, hit.product_type, hit.tile_id) == ("L2B", "CALIBRATED", "")
    assert (hit.relative_orbit, hit.burst_cycle, hit.swath) == ("124", "0835", "IW3")
    assert (hit.direction, hit.polarization, hit.burst_id) == (
        "descending",
        "VV",
        "124-0835-IW3-VV",
    )
    assert hit.bbox is not None and hit.bbox[0] < hit.bbox[2]
    assert hit.family == "EGMS_L2b_124_0835_IW3_VV_2020_2025"
    assert hit.path.startswith("2020-2025/L2B/")


def test_a_hit_without_a_usable_bbox_has_none() -> None:
    body = json.loads((FIXTURES / "search_bbox_L2A.json").read_text())
    body["hits"][0]["bbox"] = "odd"
    search = parse_search(json.dumps(body))
    assert search is not None and search.hits[0].bbox is None


def test_latest_hits_keeps_one_version_per_file() -> None:
    search = parse_search((FIXTURES / "search_bbox_L2A.json").read_bytes())
    assert search is not None
    first = search.hits[0]
    newer = dataclasses.replace(
        first, filename=first.filename.replace("_1.zip", "_2.zip"), version="2020_2025_2"
    )
    picked = latest_hits([first, *search.hits[1:], newer])
    assert len(picked) == len(search.hits)
    assert picked[0] is newer


def test_names_lists_and_their_refusals() -> None:
    assert parse_names((FIXTURES / "levels.json").read_bytes(), "levels") == ["L2A", "L2B", "L3"]
    assert parse_names((FIXTURES / "bursts.json").read_bytes(), "bursts")[0] == "0171"
    with pytest.raises(EgmsError, match="too large"):
        parse_search((FIXTURES / "area_too_large.json").read_bytes())
    with pytest.raises(EgmsError, match="refused the bursts"):
        parse_names((FIXTURES / "not_logged_in.json").read_bytes(), "bursts")


def test_extract_writes_the_asked_members(tmp_path: Path) -> None:
    stem = "EGMS_L2b_124_0835_IW3_VV_2020_2025_1"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{stem}.csv", b"pid,mean_velocity\n")
        z.writestr(f"{stem}.xml", b"<BURST/>")
    archive = tmp_path / f"{stem}.zip"
    archive.write_bytes(buffer.getvalue())
    (csv,) = extract(archive, ["csv"], tmp_path)
    assert csv.read_bytes() == b"pid,mean_velocity\n"
    with pytest.raises(EgmsError, match="has no"):
        extract(archive, ["tiff"], tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_the_key_comes_from_the_environment(service_key: ServiceKey, tmp_path: Path) -> None:
    text = json.dumps(
        {
            "client_id": service_key.client_id,
            "user_id": service_key.user_id,
            "private_key": service_key.private_key,
            "token_uri": service_key.token_uri,
        }
    )
    assert ServiceKey.from_env({"EGMS_SERVICE_KEY": text}) == service_key
    path = tmp_path / "key.json"
    path.write_text(text)
    assert ServiceKey.from_env({"EGMS_SERVICE_KEY_FILE": str(path)}) == service_key
    assert ServiceKey.from_env({"EGMS_SERVICE_KEY": " ", "EGMS_SERVICE_KEY_FILE": str(path)})
    with pytest.raises(LookupError, match="EGMS_SERVICE_KEY"):
        ServiceKey.from_env({})
