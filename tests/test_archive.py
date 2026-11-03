from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from egms_client import (
    EgmsError,
    Hit,
    Search,
    api_release,
    check_download,
    download_url,
    extract_tiff,
    file_release,
    latest_hit,
    parse_releases,
    parse_search,
    search_body,
    tile_id,
    tile_prefix,
    tiles_for_bounds,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_tile_names_are_the_lower_left_corner_in_hundreds_of_km() -> None:
    assert tile_id((47, 19)) == "E47N19"
    assert tiles_for_bounds(4_750_000, 1_950_000, 4_850_000, 1_999_999) == [(47, 19), (48, 19)]
    assert tiles_for_bounds(4_700_000, 1_900_000, 4_700_000, 1_900_000) == [(47, 19)]


def test_releases_have_two_spellings() -> None:
    assert api_release("2020_2025") == api_release("2020-2025") == "2020-2025"
    assert file_release("2020-2025") == file_release("2020_2025") == "2020_2025"
    assert tile_prefix((47, 19), "U", "2020-2025") == "EGMS_L3_E47N19_100km_U_2020_2025_"


def test_the_search_body_asks_for_one_ortho_tile() -> None:
    assert search_body((47, 19), "E", "2020_2025") == {
        "tileId": "E47N19",
        "releases": ["2020-2025"],
        "levels": ["L3"],
        "productType": "ORTHO-EAST",
    }


def test_releases_parse_and_sort() -> None:
    assert parse_releases((FIXTURES / "releases.json").read_bytes()) == ["2020-2024", "2020-2025"]
    assert parse_releases(b'["2020-2025", "2019-2023"]') == ["2019-2023", "2020-2025"]


def test_without_a_login_the_archive_refuses_with_a_200() -> None:
    body = (FIXTURES / "not_logged_in.json").read_bytes()
    with pytest.raises(EgmsError, match="Please log in"):
        parse_releases(body)
    with pytest.raises(EgmsError, match="Please log in"):
        parse_search(body)


def test_a_search_hit_carries_its_own_file_name() -> None:
    search = parse_search((FIXTURES / "search_E47N19_U.json").read_bytes())
    assert search is not None
    assert search.id == "0123456789abcdef0123456789abcdef"
    (hit,) = search.hits
    assert hit.filename == "EGMS_L3_E47N19_100km_U_2020_2025_1.zip"
    assert hit.stem == "EGMS_L3_E47N19_100km_U_2020_2025_1"
    assert (hit.filesize, hit.tile_id, hit.release) == (64361037, "E47N19", "2020-2025")
    assert (hit.version, hit.product_type) == ("2020_2025_1", "ORTHO-UP")


def test_a_tile_at_sea_is_none_not_an_error() -> None:
    assert parse_search((FIXTURES / "search_E40N15_sea.json").read_bytes()) is None


@pytest.mark.parametrize("body", [b"[]", b"<html/>"])
def test_a_search_that_is_not_an_object_raises(body: bytes) -> None:
    with pytest.raises(EgmsError):
        parse_search(body)


def _hit(version: str) -> Hit:
    return Hit(
        filename=f"EGMS_L3_E47N19_100km_U_{version}.zip",
        filesize=1,
        tile_id="E47N19",
        release="2020-2025",
        version=version,
        product_type="ORTHO-UP",
    )


def test_the_latest_sub_release_wins() -> None:
    search = Search(id="x", hits=[_hit("2020_2025_1"), _hit("2020_2025_2"), _hit("odd")])
    assert latest_hit(search) == _hit("2020_2025_2")
    assert latest_hit(Search(id="x", hits=[])) is None


def test_download_url_uses_the_hit_name() -> None:
    assert (
        download_url("https://a/archive/", _hit("2020_2025_1"))
        == "https://a/archive/download/EGMS_L3_E47N19_100km_U_2020_2025_1.zip"
    )


def test_an_expired_search_id_is_a_401() -> None:
    body = (FIXTURES / "download_expired_401.txt").read_bytes()
    with pytest.raises(EgmsError, match=r"HTTP 401.*Rerun your search"):
        check_download(401, body)
    assert check_download(200, b"zip") == b"zip"


def _zip(**files: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


def test_only_the_geotiff_comes_out_of_the_zip() -> None:
    hit = _hit("2020_2025_1")
    archive = _zip(**{f"{hit.stem}.tiff": b"TIFF", f"{hit.stem}.csv": b"big"})
    assert extract_tiff(archive, hit) == b"TIFF"
    with pytest.raises(EgmsError, match="has no"):
        extract_tiff(_zip(other=b""), hit)
