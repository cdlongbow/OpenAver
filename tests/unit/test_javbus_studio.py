"""
test_javbus_studio.py - JavBus 片商頁能力與單樣本分類（173-T3）

站方 HTML 那一步（有無 info 區塊、href 清單、#waterfall）以替身取代，
只測之後的純邏輯與例外契約。全部 mock _session，不連外網。
"""

import pytest
import requests
from unittest.mock import patch, MagicMock


@pytest.fixture
def scraper_zh():
    from core.scrapers.javbus import JavBusScraper
    with patch("core.scrapers.javbus.rate_limit") as rl:
        scraper = JavBusScraper(lang="zh-tw")
        scraper._rate_limit_mock = rl
        yield scraper


def _resp(status):
    r = MagicMock()
    r.status_code = status
    r.text = ""
    return r


def _sample(scraper, status=None, info=None, exc=None):
    """跑單樣本取回器；status 或 exc 擇一。"""
    info = (True, []) if info is None else info
    if exc is not None:
        scraper._session.get = MagicMock(side_effect=exc)
    else:
        scraper._session.get = MagicMock(return_value=_resp(status))
    with patch.object(scraper, "_extract_studio_info", return_value=info):
        result = scraper.fetch_studio_sample("SONE-205")
    assert scraper._session.get.call_count == 1
    return result


REQUEST_EXCS = [
    requests.Timeout("t"),
]


# ---------------- parse_studio_href ----------------


# ---------------- classify ----------------

def test_classify_only_404_is_miss():
    from core.scrapers.javbus import classify, STUDIO_MISS, STUDIO_UNREACHABLE
    assert classify(404, False, []) is STUDIO_MISS
    for status in (403, 429, 500, 503, 301, 410):
        assert classify(status, True, ["/studio/7q"]) is STUDIO_UNREACHABLE, status


@pytest.mark.parametrize("status,has_wf,expected", [
    (404, False, "LIST_END"),
    (403, True, "LIST_BLOCKED"),
])
def test_classify_list_response(status, has_wf, expected):
    import core.scrapers.javbus as jb
    assert jb.classify_list_response(status, has_wf) is getattr(jb, expected)


# ---------------- fetch_studio_sample ----------------


@pytest.mark.parametrize("exc", REQUEST_EXCS, ids=lambda e: type(e).__name__)
def test_fetch_sample_request_exceptions_are_unreachable(scraper_zh, exc):
    from core.scrapers.javbus import STUDIO_UNREACHABLE
    assert _sample(scraper_zh, exc=exc) is STUDIO_UNREACHABLE


def test_fetch_sample_rate_limits_and_uses_detail_url(scraper_zh):
    _sample(scraper_zh, 404)
    scraper_zh._rate_limit_mock.assert_called_once_with(scraper_zh.config.delay)
    url = scraper_zh._session.get.call_args[0][0]
    assert url == "https://www.javbus.com/SONE-205"


# ---------------- build_studio_url ----------------

@pytest.mark.parametrize("lang,kind,page,expected", [
    ("ja", "uncensored", 2, "https://www.javbus.com/ja/uncensored/studio/3a/2"),
])
def test_build_studio_url_matrix(lang, kind, page, expected):
    from core.scrapers.javbus import JavBusScraper
    with patch("core.scrapers.javbus.rate_limit"):
        s = JavBusScraper(lang=lang)
    sid = "3a" if kind == "uncensored" else "7q"
    assert s.build_studio_url((kind, sid), page) == expected


# ---------------- get_ids_from_studio ----------------

REF = ("censored", "7q")


def _list(scraper, status=None, waterfall=True, exc=None, ids=None):
    if exc is not None:
        scraper._session.get = MagicMock(side_effect=exc)
    else:
        scraper._session.get = MagicMock(return_value=_resp(status))
    with patch.object(scraper, "_has_waterfall", return_value=waterfall), \
         patch.object(scraper, "_parse_search_ids", return_value=ids or []):
        try:
            return scraper.get_ids_from_studio(REF, 1)
        finally:
            assert scraper._session.get.call_count == 1


@pytest.mark.parametrize("exc", REQUEST_EXCS, ids=lambda e: type(e).__name__)
def test_get_ids_from_studio_request_exceptions_unreachable(scraper_zh, exc):
    from core.scrapers.errors import SourceUnreachable
    with pytest.raises(Exception) as ei:
        _list(scraper_zh, exc=exc)
    assert type(ei.value) is SourceUnreachable


