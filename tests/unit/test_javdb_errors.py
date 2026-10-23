"""
test_javdb_errors.py - javdb typed exception 與例外傳播單元測試（TASK-132a-T2）

AC-1：core/scrapers/errors.py 兩個 typed exception 與 docstring
AC-2：_get_html() 三態分類（連線層 Unreachable / 403,429,503與CF Blocked / 404,500 None）
AC-3：log 升 WARNING 且區分連不上與被擋
AC-4：search() 放行新例外
AC-5：查無此片回 None 不拋例外（反向鎖）
AC-6：404/500 回 None 不拋例外（反向鎖）
AC-7：CURL_CFFI_AVAILABLE=False 回 None 不拋新例外（反向鎖）
AC-8：MRO 見證例外驗證（BE-TEST-16）
"""

from unittest.mock import MagicMock, patch

import pytest

from core.scrapers import javdb

from core.scrapers.errors import SourceUnreachable


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


# ============================================================
# AC-4：search() 放行新例外
# ============================================================


# ============================================================
# AC-5, AC-6, AC-7：反向鎖（查無 / 404,500 / curl_cffi 不可用）
# ============================================================

class TestReverseLocks:

    def test_search_curl_cffi_unavailable_returns_none(self, scraper, monkeypatch):
        monkeypatch.setattr(javdb, "CURL_CFFI_AVAILABLE", False)

        result = scraper.search("SSIS-001")
        assert result is None


# ============================================================
# AC-8：MRO 見證例外驗證（BE-TEST-16）
# ============================================================


# ============================================================
# AC-1：core/scrapers/errors.py 兩個 typed exception 與 docstring
# ============================================================

