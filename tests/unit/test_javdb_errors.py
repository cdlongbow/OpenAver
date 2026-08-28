"""
test_javdb_errors.py - javdb typed exception 與例外傳播單元測試（TASK-132a-T2）

AC-1：core/scrapers/errors.py 兩個 typed exception 與 docstring
AC-2：_get_html() 三態分類（連線層 Unreachable / 403,429,503與CF Blocked / 404,500 None）
AC-3：log 升 WARNING 且區分連不上與被擋
AC-4：search() 與 search_by_keyword() 放行新例外（三個吞點）
AC-5：查無此片回 None 不拋例外（反向鎖）
AC-6：404/500 回 None 不拋例外（反向鎖）
AC-7：CURL_CFFI_AVAILABLE=False 回 None 不拋新例外（反向鎖）
AC-8：MRO 見證例外驗證（BE-TEST-16）
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from core.scrapers import javdb

from core.scrapers.errors import SourceBlocked, SourceUnreachable


@pytest.fixture(autouse=True)
def _api_path_disabled(monkeypatch):
    """本檔測的是**網頁那條**的契約（132a 出貨的三態）。

    T3 之後 search() 會先打 App 資料介面——若不擋掉，這些測試會真的連上活站。
    一律讓資料介面那條「連不上」，search() 就會照 CD-132b-4 降級到網頁那條，
    本檔既有的斷言語意因此逐條維持不變。
    """
    from core.scrapers import javdb_api
    monkeypatch.setattr(
        javdb_api, "fetch_video",
        MagicMock(side_effect=SourceUnreachable("api disabled in this test module")),
    )


@pytest.fixture
def scraper():
    with patch("core.scrapers.javdb.rate_limit"):
        s = javdb.JavDBScraper()
        yield s


# ============================================================
# AC-2 & AC-3：_get_html() 三態分類與 log 升 WARNING
# ============================================================

class TestGetHtmlErrorHandling:
    def test_get_html_connection_error_raises_unreachable(self, scraper, monkeypatch, caplog):
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_get = MagicMock(side_effect=CurlConnectionError("Connection refused"))
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(SourceUnreachable):
                scraper._get_html("https://javdb.com/search?q=SSIS-001")

        assert any(
            record.levelno >= logging.WARNING and "JavDB request failed" in record.message
            for record in caplog.records
        )

    def test_get_html_timeout_raises_unreachable(self, scraper, monkeypatch, caplog):
        from curl_cffi.requests.exceptions import Timeout as CurlTimeout

        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_get = MagicMock(side_effect=CurlTimeout("Connection timed out"))
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(SourceUnreachable):
                scraper._get_html("https://javdb.com/search?q=SSIS-001")

    def test_get_html_403_raises_blocked(self, scraper, monkeypatch, caplog):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(SourceBlocked):
                scraper._get_html("https://javdb.com/search?q=SSIS-001")

        assert any(
            record.levelno >= logging.WARNING and "blocked" in record.message.lower()
            for record in caplog.records
        )

    def test_get_html_429_raises_blocked(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with pytest.raises(SourceBlocked):
            scraper._get_html("https://javdb.com/search?q=SSIS-001")

    def test_get_html_503_raises_blocked(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with pytest.raises(SourceBlocked):
            scraper._get_html("https://javdb.com/search?q=SSIS-001")

    @pytest.mark.parametrize(
        "challenge_snippet",
        [
            "cf-browser-verification",
            "Just a moment...",
            "challenge-platform",
        ],
    )
    def test_get_html_cf_challenge_raises_blocked(
        self, challenge_snippet, scraper, monkeypatch, caplog
    ):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = f"<html><head><title>{challenge_snippet}</title></head></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(SourceBlocked):
                scraper._get_html("https://javdb.com/search?q=SSIS-001")

        assert any(
            record.levelno >= logging.WARNING and "blocked" in record.message.lower()
            for record in caplog.records
        )

    def test_get_html_cf_challenge_ignored_if_large_body(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 大於 20000 字元且含有 challenge 關鍵字時不掃描，維持回傳 html
        mock_resp.text = "Just a moment" + ("a" * 20001)
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/search?q=SSIS-001")
        assert result == mock_resp.text

    def test_get_html_200_normal_returns_text(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Normal Page</h1></body></html>"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper._get_html("https://javdb.com/search?q=SSIS-001")
        assert result == mock_resp.text

    def test_get_html_404_returns_none_and_logs_warning(self, scraper, monkeypatch, caplog):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            result = scraper._get_html("https://javdb.com/search?q=SSIS-001")

        assert result is None
        assert any(
            record.levelno >= logging.WARNING and "non-200" in record.message.lower()
            for record in caplog.records
        )

    def test_get_html_500_returns_none_and_logs_warning(self, scraper, monkeypatch, caplog):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with caplog.at_level(logging.WARNING):
            result = scraper._get_html("https://javdb.com/search?q=SSIS-001")

        assert result is None
        assert any(
            record.levelno >= logging.WARNING and "non-200" in record.message.lower()
            for record in caplog.records
        )


# ============================================================
# AC-4：search() 與 search_by_keyword() 放行新例外（三個吞點）
# ============================================================

class TestPublicApiPropagatesErrors:
    def test_search_propagates_blocked(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with pytest.raises(SourceBlocked):
            scraper.search("SSIS-001")

    def test_search_propagates_unreachable(self, scraper, monkeypatch):
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_get = MagicMock(side_effect=CurlConnectionError("Connection refused"))
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with pytest.raises(SourceUnreachable):
            scraper.search("SSIS-001")

    def test_search_by_keyword_outer_propagates_blocked(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        with pytest.raises(SourceBlocked):
            scraper.search_by_keyword("SSIS")

    def test_search_by_keyword_inner_propagates_unreachable(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        # 關鍵字搜尋頁面成功回傳 1 筆結果
        search_list_html = (
            '<div class="movie-list">'
            '  <div class="item">'
            '    <div class="video-title"><strong>SSIS-001</strong></div>'
            '    <a href="/v/abc123">link</a>'
            '  </div>'
            '</div>'
        )

        def mock_search_impl(number):
            raise SourceUnreachable("inner detail connection failed")

        monkeypatch.setattr(scraper, "_get_html", lambda url: search_list_html)
        monkeypatch.setattr(scraper, "search_via_html", mock_search_impl)

        with pytest.raises(SourceUnreachable):
            scraper.search_by_keyword("SSIS")

    def test_search_by_keyword_inner_propagates_blocked(self, scraper, monkeypatch):
        """內層 except tuple 的**另一項**（SourceBlocked）也要走得出來。

        BE-TEST-16 的同族問題：只測 tuple 裡的一項，另一項被刪掉不會有任何測試轉紅。
        本測試就是那一項的守衛（Opus 獨立 mutation 發現的缺口，sonnet review 同時抓到）。
        """
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        search_list_html = (
            '<div class="movie-list">'
            '  <div class="item">'
            '    <div class="video-title"><strong>SSIS-001</strong></div>'
            '    <a href="/v/abc123">link</a>'
            '  </div>'
            '</div>'
        )

        def mock_search_impl(number):
            raise SourceBlocked("inner detail blocked by CF")

        monkeypatch.setattr(scraper, "_get_html", lambda url: search_list_html)
        monkeypatch.setattr(scraper, "search_via_html", mock_search_impl)

        with pytest.raises(SourceBlocked):
            scraper.search_by_keyword("SSIS")


# ============================================================
# AC-5, AC-6, AC-7：反向鎖（查無 / 404,500 / curl_cffi 不可用）
# ============================================================

class TestReverseLocks:
    def test_search_not_found_returns_none_no_exception(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<div class="movie-list"></div>'
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper.search("SSIS-001")
        assert result is None

    def test_search_404_returns_none_no_exception(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper.search("SSIS-001")
        assert result is None

    def test_search_500_returns_none_no_exception(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(javdb.curl_requests, "get", mock_get)

        result = scraper.search("SSIS-001")
        assert result is None

    def test_search_curl_cffi_unavailable_returns_none(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", False)

        result = scraper.search("SSIS-001")
        assert result is None

    def test_validate_number_invalid_raises_value_error(self, scraper):
        with pytest.raises(ValueError, match="Invalid number format"):
            scraper.search("")


# ============================================================
# AC-8：MRO 見證例外驗證（BE-TEST-16）
# ============================================================

class TestMroWitness:
    def test_witness_mro_branches(self):
        from curl_cffi.requests.exceptions import (
            ConnectTimeout,
            ConnectionError as CurlConnectionError,
            Timeout as CurlTimeout,
        )

        conn_mro = [k.__name__ for k in CurlConnectionError.__mro__]
        timeout_mro = [k.__name__ for k in CurlTimeout.__mro__]
        connect_timeout_mro = [k.__name__ for k in ConnectTimeout.__mro__]

        assert "Timeout" not in conn_mro
        assert "ConnectionError" not in timeout_mro
        # ConnectTimeout 同時繼承 ConnectionError 與 Timeout
        assert "ConnectionError" in connect_timeout_mro
        assert "Timeout" in connect_timeout_mro


# ============================================================
# AC-1：core/scrapers/errors.py 兩個 typed exception 與 docstring
# ============================================================

class TestErrorClasses:
    def test_error_classes_hierarchy_and_docstrings(self):
        from core.scrapers.errors import SourceBlocked as RealSourceBlocked
        from core.scrapers.errors import SourceUnreachable as RealSourceUnreachable

        assert issubclass(RealSourceUnreachable, RuntimeError)
        assert issubclass(RealSourceBlocked, RuntimeError)

        assert RealSourceUnreachable.__doc__ is not None
        assert "User-visible meaning:" in RealSourceUnreachable.__doc__
        assert "連不上" in RealSourceUnreachable.__doc__

        assert RealSourceBlocked.__doc__ is not None
        assert "User-visible meaning:" in RealSourceBlocked.__doc__
        assert "暫時不可用" in RealSourceBlocked.__doc__
