"""175b-T7：DMM 女優只留主名（去結尾全形括號舊名）。合成資料，不連外。"""
from unittest.mock import MagicMock, patch

import pytest

from core.proxy_policy import ProxySettings
from core.scrapers.dmm import DMMScraper, _actress_main_name
from core.scrapers.models import ScraperConfig


@pytest.mark.parametrize("raw, expected", [
    ("あかね麗（二階堂麗）", "あかね麗"),
    ("あかね麗 （二階堂麗）", "あかね麗"),
    ("A（B、C）", "A"),
    ("三上悠亜", "三上悠亜"),
    ("Name(Old)", "Name(Old)"),
    ("A（B）C", "A（B）C"),
    ("（二階堂麗）", "（二階堂麗）"),
    ("A（B）（C）", "A（B）"),  # D1：只去最後一段
    ("", ""),
    (None, None),
])
def test_actress_main_name_table(raw, expected):
    assert _actress_main_name(raw) == expected


def _resp(data):
    m = MagicMock()
    m.status_code = 200
    m.json = lambda: data
    return m


_ACTRESSES = [{"name": "あかね麗（二階堂麗）"}, {"name": "三上悠亜"}]


@pytest.fixture
def scraper(monkeypatch):
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)
    return DMMScraper(ScraperConfig(proxy_settings=ProxySettings(url="")))


def _search_resp():
    return _resp({"data": {"legacySearchPPV": {"result": {"contents": [
        {"id": "sone00205", "title": "T", "actresses": _ACTRESSES}]}}}})


def test_fetch_by_id_actress_main_name(scraper):
    detail = _resp({"data": {"ppvContent": {
        "id": "sone00205", "title": "T", "description": "", "packageImage": {},
        "makerReleasedAt": "2024-03-19T00:00:00+09:00", "duration": 1,
        "actresses": _ACTRESSES, "directors": [], "series": {"name": ""},
        "maker": {"name": "M"}, "makerContentId": "SONE-205"}}})
    with patch.object(scraper._session, "post", return_value=detail), \
         patch.object(scraper, "_fetch_tags_from_html", return_value=[]):
        video = scraper._fetch_by_id("sone00205")
    assert [a.name for a in video.actresses] == ["あかね麗", "三上悠亜"]


def test_keyword_with_ids_actress_main_name(scraper):
    with patch.object(scraper._session, "post", return_value=_search_resp()):
        pairs = scraper.search_by_keyword_with_ids("あかね麗")
    assert [a.name for a in pairs[0][1].actresses] == ["あかね麗", "三上悠亜"]


def test_keyword_fallback_actress_main_name(scraper):
    with patch.object(scraper._session, "post", return_value=_search_resp()), \
         patch.object(scraper, "_fetch_by_id", return_value=None):
        videos = scraper.search_by_keyword("あかね麗")
    assert [a.name for a in videos[0].actresses] == ["あかね麗", "三上悠亜"]
