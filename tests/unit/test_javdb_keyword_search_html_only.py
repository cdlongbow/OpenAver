"""spec-132 Non-Goals：關鍵字搜尋維持 HTML，不得碰資料介面。

plan 的 CD-132b-12 寫的是「`search_by_keyword()` 一個字都不動」，而那支是逐筆呼叫
`search()` 取詳情的——`search()` 在 T3 改成 API 優先之後，**沒改到那支也一樣會走 API**
（Codex review round-2 P2）。

使用者流程：使用者用關鍵字（片名片段、女優名）搜尋 → 每筆結果各打一次資料介面，
一次搜尋最多 20 次 → 我們想省著用的那條路被高頻打；它被擋的話，**精準番號搜尋
也一起壞**（那條路只有它，HTML 備援還要過 Cloudflare）。

測試不得發出任何真實網路請求。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.scrapers import javdb
from core.scrapers.models import Video

_LIST_HTML = (
    '<div class="movie-list">'
    '  <div class="item">'
    '    <div class="video-title"><strong>SSIS-001</strong></div>'
    '    <a href="/v/aaa">link</a>'
    '  </div>'
    '  <div class="item">'
    '    <div class="video-title"><strong>SSIS-002</strong></div>'
    '    <a href="/v/bbb">link</a>'
    '  </div>'
    '</div>'
)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _raise(*_a, **_k):
        raise AssertionError("Network access attempted in pure unit test!")

    import requests

    monkeypatch.setattr(requests, "get", _raise)
    monkeypatch.setattr(requests, "post", _raise)
    if javdb.CURL_CFFI_AVAILABLE and hasattr(javdb, "curl_requests"):
        monkeypatch.setattr(javdb.curl_requests, "get", _raise)
    monkeypatch.setattr(javdb, "rate_limit", MagicMock())


def _video(number: str) -> Video:
    return Video(
        number=number,
        title=f"FROM_HTML {number}",
        source="javdb",
        detail_url=f"https://javdb.com/v/{number}",
    )


@pytest.fixture
def scraper():
    return javdb.JavDBScraper()


def test_keyword_search_never_calls_the_api(scraper, monkeypatch):
    """mutation keyword-html-only：把迴圈改回 `self.search(...)` → 本支必須紅。"""
    api = MagicMock(side_effect=AssertionError("關鍵字搜尋不得呼叫資料介面"))
    html = MagicMock(side_effect=lambda number: _video(number))
    monkeypatch.setattr(scraper, "_get_html", lambda _url: _LIST_HTML)
    monkeypatch.setattr(scraper, "search_via_api", api)
    monkeypatch.setattr(scraper, "search_via_html", html)

    results = scraper.search_by_keyword("三上")

    assert [v.number for v in results] == ["SSIS-001", "SSIS-002"]
    assert api.call_count == 0
    assert html.call_count == 2


def test_precise_search_still_prefers_the_api(scraper, monkeypatch):
    """反向鎖：上一支不可以靠「把 API 整條停掉」通過。

    精準番號搜尋**必須**仍是 API 優先，否則 132b 整支 branch 等於沒做。
    """
    api = MagicMock(return_value=_video("SSIS-001"))
    html = MagicMock(side_effect=AssertionError("API 命中時不該再走 HTML"))
    monkeypatch.setattr(scraper, "search_via_api", api)
    monkeypatch.setattr(scraper, "search_via_html", html)

    assert scraper.search("SSIS-001") is not None
    assert api.call_count == 1
    assert html.call_count == 0


def test_keyword_search_now_returns_amateur_numbers(scraper, monkeypatch):
    """素人番號過閘後送出 HTML 詳情請求並回結果。

    這條鎖的仍是 `_search_number()` 沒有在拆分時把正規化／格式檢查漏掉
    （CD-132b-13：兩條路徑之前只做一次）——D 委派 `is_strict_number` 後，
    素人番號（如 259LUXU-1234）會通過閘門，期望從「零詳情請求」翻面為
    「送出詳情並回結果」。
    """
    list_html = (
        '<div class="movie-list">'
        '  <div class="item">'
        '    <div class="video-title"><strong>259LUXU-1234</strong></div>'
        '    <a href="/v/ccc">link</a>'
        '  </div>'
        '</div>'
    )
    html = MagicMock(side_effect=lambda number: _video(number))
    monkeypatch.setattr(scraper, "_get_html", lambda _url: list_html)
    monkeypatch.setattr(scraper, "search_via_html", html)

    results = scraper.search_by_keyword("LUXU")
    assert [v.number for v in results] == ["259LUXU-1234"]
    assert html.call_count == 1
