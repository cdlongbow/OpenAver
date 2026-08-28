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

from core.scrapers import javdb, javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
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

    def test_api_blocked_falls_back_to_html(
        self, scraper, fake_html_video, monkeypatch, caplog
    ):
        """AC-2 & AC-7 & AC-8: API 被擋（SourceBlocked）時降級走 HTML，記錄 WARNING，rate_limit 呼叫一次。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(
            scraper, "search_via_api",
            MagicMock(side_effect=SourceBlocked("API blocked by CF"))
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
            and "SourceBlocked" in record.message
            for record in caplog.records
        )

    def test_api_unreachable_falls_back_to_html(
        self, scraper, fake_html_video, monkeypatch, caplog
    ):
        """AC-2: API 連不上（SourceUnreachable）時降級走 HTML，記錄 WARNING。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(
            scraper, "search_via_api",
            MagicMock(side_effect=SourceUnreachable("Connection timeout"))
        )
        monkeypatch.setattr(scraper, "search_via_html", MagicMock(return_value=fake_html_video))

        with caplog.at_level(logging.WARNING):
            result = scraper.search("SSIS-001")

        assert result is not None
        assert result.title == "FROM_HTML"
        assert scraper.search_via_html.call_count == 1
        assert any(
            record.levelno >= logging.WARNING
            and "API 降級 → HTML" in record.message
            and "SourceUnreachable" in record.message
            for record in caplog.records
        )

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

    def test_api_fails_and_html_blocked_raises_blocked(
        self, scraper, monkeypatch
    ):
        """AC-5: API 失敗（SourceUnreachable）且 HTML 也被擋（SourceBlocked）時，search() 拋出 SourceBlocked。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(
            scraper, "search_via_api",
            MagicMock(side_effect=SourceUnreachable("API down"))
        )
        monkeypatch.setattr(
            scraper, "search_via_html",
            MagicMock(side_effect=SourceBlocked("HTML CF block"))
        )

        with pytest.raises(SourceBlocked):
            scraper.search("SSIS-001")

        assert mock_rate_limit.call_count == 0

    def test_api_fails_and_html_unreachable_raises_unreachable(
        self, scraper, monkeypatch
    ):
        """AC-5: API 失敗且 HTML 連線失敗時，search() 拋出 SourceUnreachable。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(
            scraper, "search_via_api",
            MagicMock(side_effect=SourceBlocked("API blocked"))
        )
        monkeypatch.setattr(
            scraper, "search_via_html",
            MagicMock(side_effect=SourceUnreachable("HTML conn fail"))
        )

        with pytest.raises(SourceUnreachable):
            scraper.search("SSIS-001")

        assert mock_rate_limit.call_count == 0

    def test_both_api_and_html_not_found_returns_none(
        self, scraper, monkeypatch
    ):
        """AC-8: API 查無且 HTML 查無時，回傳 None 且 rate_limit 不呼叫。"""
        mock_rate_limit = MagicMock()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", mock_rate_limit)
        monkeypatch.setattr(scraper, "search_via_api", MagicMock(return_value=None))
        monkeypatch.setattr(scraper, "search_via_html", MagicMock(return_value=None))

        result = scraper.search("SSIS-001")

        assert result is None
        assert mock_rate_limit.call_count == 0

    def test_invalid_number_raises_value_error_without_calling_api_or_html(
        self, scraper, monkeypatch
    ):
        """AC-6: 非法番號直接拋 ValueError，不呼叫 search_via_api 與 search_via_html。"""
        mock_api = MagicMock()
        mock_html = MagicMock()
        monkeypatch.setattr(scraper, "search_via_api", mock_api)
        monkeypatch.setattr(scraper, "search_via_html", mock_html)

        with pytest.raises(ValueError, match="Invalid number format"):
            scraper.search("")

        assert mock_api.call_count == 0
        assert mock_html.call_count == 0


class TestSearchViaApiAndHtmlContracts:
    def test_search_via_api_calls_javdb_api_fetch_video(
        self, scraper, fake_api_video, monkeypatch
    ):
        """search_via_api 薄封裝契約：直接轉發已正規化番號給 javdb_api.fetch_video，不攔截例外。"""
        mock_fetch = MagicMock(return_value=fake_api_video)
        monkeypatch.setattr(javdb_api, "fetch_video", mock_fetch)

        result = scraper.search_via_api("SSIS-001")

        assert result is fake_api_video
        mock_fetch.assert_called_once_with("SSIS-001")

    def test_search_via_api_propagates_exceptions(
        self, scraper, monkeypatch
    ):
        """search_via_api 契約：例外不自行攔截，直接向外拋出供 search() 處理。"""
        mock_fetch = MagicMock(side_effect=SourceBlocked("API blocked"))
        monkeypatch.setattr(javdb_api, "fetch_video", mock_fetch)

        with pytest.raises(SourceBlocked):
            scraper.search_via_api("SSIS-001")


# ============================================================
# review 第 1 輪補強（grok P2-2）：rate_limit 只有一個 call site
# ============================================================

def test_rate_limit_lives_only_in_search_not_in_search_via_html():
    """`rate_limit` 必須只由 `search()` 呼叫，`search_via_html()` 裡不得再留一份。

    為什麼需要這一支（grok review P2）：上面所有降級測試都把 `search_via_html`
    **整支換成 MagicMock**，所以「HTML 本體裡又留／又加回一次 `rate_limit`」
    這個回歸**觀測不到**——`search()` 那一次仍然讓 `call_count == 1`。

    使用者流程：兩次節流疊起來，每搜一個番號多等一個 delay。單看沒感覺，
    但批次整理一百部片就是多等一百次。

    這是源碼語意檢查，不是字串存在檢查 ⇒ 依 CLAUDE.md「Lint 守衛規則」屬 pytest 這一格。
    """
    import inspect

    from core.scrapers.javdb import JavDBScraper

    html_src = inspect.getsource(JavDBScraper.search_via_html)
    api_src = inspect.getsource(JavDBScraper.search_via_api)
    # 節流已隨 review round-2 的 `allow_api` 拆分搬進 `_search_number()`
    # （`search()` 現在只是它的 `allow_api=True` 入口）。
    search_src = inspect.getsource(JavDBScraper._search_number)

    assert "rate_limit" not in html_src, (
        "search_via_html() 裡不得有 rate_limit——它已經搬到 search()，"
        "留兩份會讓每次搜尋節流兩次"
    )
    assert "rate_limit" not in api_src, "search_via_api() 是薄封裝，不該節流"
    assert search_src.count("rate_limit(") == 3, (
        "_search_number() 應該剛好有三個 rate_limit 呼叫點（API 命中、html-only、"
        "HTML 備援），三者互斥所以每次搜尋最多只會執行到一個"
    )
