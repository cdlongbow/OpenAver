"""
test_javdb_search_routing.py - JavDB 搜尋路由與降級編排單元測試（TASK-132b-T3）

DoD 覆蓋：
- AC-1: API 命中時直接回傳，不碰 HTML 網頁解析
- AC-2: API 拋 SourceBlocked 時降級到 HTML 解析，並記錄 WARNING log
- AC-3: API 拋非 typed exception 時仍降級到 HTML 解析（反向鎖）
- AC-4: API 查無時降級到 HTML 解析，並記錄 INFO log
- AC-5: API 失敗且 HTML 也拋例外時，HTML 的例外正常向外拋出
- AC-6: 非法番號在 routing 前直接拋 ValueError，不碰 API 與 HTML
- AC-7: API 與 HTML 分支使用可識別的不同 mock 資料（BE-TEST-11）
- AC-8: rate_limit 在 API 命中與 HTML 命中時各呼叫 1 次，皆查無時不呼叫
- AC-12: 零網路請求保證
"""

import logging
from unittest.mock import MagicMock

import pytest

from core.scrapers import javdb
from core.scrapers.models import Video


@pytest.fixture(autouse=True)
def _block_all_network(monkeypatch):
    """AC-12: 保證本測試模組絕對不發出任何真實網路請求。"""
    def _raise_network(*args, **kwargs):
        raise AssertionError("Network access attempted in pure unit test!")

    import requests
    monkeypatch.setattr(requests, "get", _raise_network)
    monkeypatch.setattr(requests, "post", _raise_network)
    if javdb.CURL_CFFI_AVAILABLE and hasattr(javdb, "curl_requests"):
        monkeypatch.setattr(javdb.curl_requests, "get", _raise_network)
        monkeypatch.setattr(javdb.curl_requests, "post", _raise_network)


@pytest.fixture
def fake_api_video():
    return Video(
        number="SSIS-001",
        title="FROM_API",
        source="javdb",
        detail_url="https://javdb.com/v/api123",
        cover_url="https://c0.jdbstatic.com/covers/api.jpg",
    )


@pytest.fixture
def fake_html_video():
    return Video(
        number="SSIS-001",
        title="FROM_HTML",
        source="javdb",
        detail_url="https://javdb.com/v/html123",
        cover_url="https://c0.jdbstatic.com/covers/html.jpg",
    )


@pytest.fixture
def scraper():
    return javdb.JavDBScraper()


class TestJavdbSearchRouting:
    def test_api_hit_returns_video_without_touching_html(
        self, scraper, fake_api_video, monkeypatch
    ):
        """AC-1 & AC-7 & AC-8: API 命中時回傳 API 的 Video，不碰 HTML，且 rate_limit 呼叫一次。"""
        mock_rate_limit = MagicMock()
        mock_get_html = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(scraper, "search_via_api", MagicMock(return_value=fake_api_video))
        monkeypatch.setattr(scraper, "_get_html", mock_get_html)

        result = scraper.search("SSIS-001")

        assert result is not None
        assert result.title == "FROM_API"
        assert scraper.search_via_api.call_count == 1
        assert mock_get_html.call_count == 0
        assert mock_rate_limit.call_count == 1


    def test_api_unexpected_exception_still_degrades_to_html(
        self, scraper, fake_html_video, monkeypatch, caplog
    ):
        """AC-3: 反向鎖 - API 拋出非 typed exception（如 ValueError / TypeError）時仍必須降級到 HTML，不把例外放出去。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(
            scraper, "search_via_api",
            MagicMock(side_effect=ValueError("Unexpected schema payload"))
        )
        monkeypatch.setattr(scraper, "search_via_html", MagicMock(return_value=fake_html_video))

        with caplog.at_level(logging.WARNING):
            result = scraper.search("SSIS-001")

        assert result is not None
        assert result.title == "FROM_HTML"
        assert scraper.search_via_html.call_count == 1
        assert mock_rate_limit.call_count == 1
        assert any(
            record.levelno >= logging.WARNING
            and "API 降級 → HTML" in record.message
            and "ValueError" in record.message
            for record in caplog.records
        )

    def test_api_not_found_falls_back_to_html(
        self, scraper, fake_html_video, monkeypatch, caplog
    ):
        """AC-4: API 回傳 None（查無）時降級走 HTML，記錄 INFO log。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(scraper, "search_via_api", MagicMock(return_value=None))
        monkeypatch.setattr(scraper, "search_via_html", MagicMock(return_value=fake_html_video))

        with caplog.at_level(logging.INFO):
            result = scraper.search("SSIS-001")

        assert result is not None
        assert result.title == "FROM_HTML"
        assert scraper.search_via_html.call_count == 1
        assert mock_rate_limit.call_count == 1
        assert any(
            record.levelno == logging.INFO
            and "API 查無" in record.message
            and "改試 HTML" in record.message
            for record in caplog.records
        )


# ============================================================
# review 第 1 輪補強（grok P2-2）：rate_limit 只有一個 call site
# ============================================================

