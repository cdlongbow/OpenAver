from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from core.scrapers.actress.xcity import (
    _find_exact_match,
    _parse_xcity_detail_html,
    scrape_xcity,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "scrapers"


def _fixture(filename):
    return (FIXTURES / filename).open(encoding="utf-8").read()


def _detail(*rows):
    return (
        '<div id="avidolDetails"><h1>試験女優</h1><dl class="profile">'
        + "".join(f'<dd><span class="koumoku">{label}</span>{value}</dd>' for label, value in rows)
        + "</dl></div>"
    )


def test_parse_xcity_detail_real_fixture_fields():
    result = _parse_xcity_detail_html(_fixture("xcity_辰巳ゆい.html"), "辰巳ゆい")
    assert result is not None
    assert {key: result.get(key) for key in (
        "birth", "blood", "hometown", "height", "bust", "cup", "waist", "hip",
        "hobby", "photo_url",
    )} == {
        "birth": "1984-06-08",
        "blood": "B型",
        "hometown": "岐阜県",
        "height": "168cm",
        "bust": "88cm",
        "cup": "F",
        "waist": "60cm",
        "hip": "89cm",
        "hobby": "ショッピング、車庫入れ",
        "photo_url": "https://faws.xcity.jp/actress/large/image/person/501.jpg",
    }
    assert "favorite" not in result


@pytest.mark.parametrize("html", [
    _fixture("xcity_delisted.html"),
    '<div id="avidolDetails"><h1>  </h1></div>',
], ids=["missing_details", "empty_heading"])
def test_parse_xcity_detail_returns_none_when_delisted(html):
    assert _parse_xcity_detail_html(html, "試験女優") is None


@pytest.mark.parametrize("name,expected", [
    ("つぼみ", "1419"),
    ("望月つぼみ", "21862"),
    ("鮎川つぼみ", "11788"),
    ("存在しない女優", None),
])
def test_find_exact_match_returns_exact_candidate_only(name, expected):
    assert _find_exact_match(_fixture("xcity_search_つぼみ.html"), name) == expected


def test_find_exact_match_no_candidates():
    assert _find_exact_match("<html><body></body></html>", "つぼみ") is None


def test_parse_xcity_detail_parser_error_returns_none():
    with patch("core.scrapers.actress.xcity.BeautifulSoup", side_effect=ValueError("bad html")):
        assert _parse_xcity_detail_html("<html>", "試験女優") is None


@pytest.mark.parametrize("value,expected", [
    ("-型", None),
    ("-", None),
    ("AB型", "AB型"),
])
def test_parse_xcity_blood(value, expected):
    result = _parse_xcity_detail_html(_detail(("血液型", value)), "試験女優")
    assert result is not None
    assert result.get("blood") == expected
    assert ("blood" in result) == (expected is not None)


@pytest.mark.parametrize("value,expected", [
    ("B83 W58 H85", {"bust": "83cm", "waist": "58cm", "hip": "85cm"}),
    ("B83 W58", {"bust": "83cm", "waist": "58cm"}),
    ("W58 H85", {"waist": "58cm", "hip": "85cm"}),
])
def test_parse_xcity_size_without_cup_or_missing_measurement(value, expected):
    result = _parse_xcity_detail_html(_detail(("サイズ", value)), "試験女優")
    assert result is not None
    assert {key: result[key] for key in ("bust", "waist", "hip") if key in result} == expected
    assert "cup" not in result


@pytest.mark.parametrize("rows,expected", [
    ([("趣味", "ショッピング"), ("特技", "")], "ショッピング"),
    ([("趣味", ""), ("特技", "車庫入れ")], "車庫入れ"),
    ([("趣味", ""), ("特技", "")], None),
])
def test_parse_xcity_hobby_ignores_empty_parts_and_other(rows, expected):
    result = _parse_xcity_detail_html(_detail(*rows, ("その他", "長い自由記述")), "試験女優")
    assert result is not None
    assert result.get("hobby") == expected
    assert "長い自由記述" not in str(result)


@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), requests.RequestException("network")])
def test_scrape_xcity_search_request_failure_returns_none(failure):
    with patch("core.scrapers.actress.xcity.requests.get", side_effect=failure):
        assert scrape_xcity("つぼみ") is None


@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), requests.RequestException("network")])
def test_scrape_xcity_detail_request_failure_returns_none(failure):
    search = Mock(status_code=200, text=_fixture("xcity_search_つぼみ.html"))
    with patch("core.scrapers.actress.xcity.requests.get", side_effect=[search, failure]):
        assert scrape_xcity("つぼみ") is None


def test_scrape_xcity_search_miss_skips_detail_request():
    search = Mock(status_code=200, text="<html></html>")
    with patch("core.scrapers.actress.xcity.requests.get", return_value=search) as get:
        assert scrape_xcity("つぼみ") is None
        get.assert_called_once()


def test_scrape_xcity_fetches_exact_candidate_detail():
    search = Mock(status_code=200, text=_fixture("xcity_search_つぼみ.html"))
    detail = Mock(status_code=200, text=_detail(("身長", "160cm")))
    with patch("core.scrapers.actress.xcity.requests.get", side_effect=[search, detail]) as get:
        assert scrape_xcity("つぼみ")["height"] == "160cm"
        assert get.call_args_list[0].args[0] == "https://xcity.jp/idol/?genre=%2Fidol%2F&q=%E3%81%A4%E3%81%BC%E3%81%BF&sg=idol"
        assert get.call_args_list[1].args[0] == "https://xcity.jp/idol/detail/1419/"
