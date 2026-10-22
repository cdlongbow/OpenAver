"""
test_javdb_api_mapping.py - JavDB API JSON → Video 映射單元測試（TASK-132b-T2）

本檔不證明站方的欄位名是對的。餵存下來的 JSON 跑欄位斷言，在站方改版時會假綠。
欄位名的偵測器是金絲雀 A（T5）。本檔鎖的只有「我們自己的規則」。


⚠️ **圖片網址一律用 `tp.spfcas.com`（真實的資料介面圖床），不要用 `example.com` 佔位。**
TASK-132b-T4 之後 `fetch_video()` 會驗圖片 host 有沒有登記在 `core/image_host_policy.py`
（CD-132b-7：未登記 → 丟 `ValueError` → `search()` 降級 HTML）。用未登記的佔位網域
會讓本檔每一支都炸在那個閘上，而不是測到映射規則。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import core.scrapers.javdb_api as javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable


def _setup_api_mocks(
    monkeypatch,
    search_return=None,
    detail_return=None,
    search_err=None,
    detail_err=None,
):
    """Monkeypatch javdb_api.api_search 與 javdb_api.api_movie_detail；零網路。"""
    mock_search = MagicMock()
    if search_err is not None:
        mock_search.side_effect = search_err
    else:
        mock_search.return_value = search_return if search_return is not None else []
    monkeypatch.setattr(javdb_api, "api_search", mock_search)

    mock_detail = MagicMock()
    if detail_err is not None:
        mock_detail.side_effect = detail_err
    else:
        mock_detail.return_value = detail_return if detail_return is not None else {}
    monkeypatch.setattr(javdb_api, "api_movie_detail", mock_detail)

    return mock_search, mock_detail


# ============================================================
# AC-9｜例外不被吞
# ============================================================

class TestExceptionsNotSwallowed:
    def test_search_source_unreachable_is_not_swallowed(self, monkeypatch):
        """api_search 拋出 SourceUnreachable 時，fetch_video 原樣往上拋。"""
        _setup_api_mocks(monkeypatch, search_err=SourceUnreachable("timeout"))

        with pytest.raises(SourceUnreachable):
            javdb_api.fetch_video("SONE-205")

    def test_detail_source_blocked_is_not_swallowed(self, monkeypatch):
        """api_movie_detail 拋出 SourceBlocked 時，fetch_video 原樣往上拋。"""
        search_payload = [{"id": "m1", "number": "SONE-205"}]
        _setup_api_mocks(
            monkeypatch,
            search_return=search_payload,
            detail_err=SourceBlocked("blocked 429"),
        )

        with pytest.raises(SourceBlocked):
            javdb_api.fetch_video("SONE-205")


# ============================================================
# review 第 1 輪的補強（sonnet ＋ grok 雙審，2026-08-28）
# ============================================================

class TestReviewRound1Hardening:
    """三條 P3 的正向鎖 ＋ AC-9 的同一顆例外物件斷言。"""

    def test_search_exception_propagates_as_the_very_same_object(self, monkeypatch):
        """不只是同一個型別——必須是同一顆例外物件。

        「catch 起來再 raise 一個同型別的新例外」型別斷言照樣綠，但那會把
        原始訊息（哪個 host、哪個狀態碼）洗掉，debug.log 就查不出是哪一種了。
        """
        sentinel = SourceBlocked("blocked 403 for https://jdforrepam.com/api/v2/search")
        _setup_api_mocks(monkeypatch, search_err=sentinel)

        with pytest.raises(SourceBlocked) as exc:
            javdb_api.fetch_video("SONE-205")
        assert exc.value is sentinel

    def test_detail_exception_propagates_as_the_very_same_object(self, monkeypatch):
        sentinel = SourceUnreachable("non-200 500 for https://javdb.com/api/v4/movies/m1")
        _setup_api_mocks(
            monkeypatch,
            search_return=[{"id": "m1", "number": "SONE-205"}],
            detail_err=sentinel,
        )

        with pytest.raises(SourceUnreachable) as exc:
            javdb_api.fetch_video("SONE-205")
        assert exc.value is sentinel
