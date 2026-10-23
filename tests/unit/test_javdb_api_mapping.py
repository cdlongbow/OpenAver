"""
test_javdb_api_mapping.py - JavDB API JSON → Video 映射單元測試（TASK-132b-T2）

本檔不證明站方的欄位名是對的。欄位名的偵測器是金絲雀 A（T5）。
現況（spec-176）：欄位映射測試已全刪，本檔只剩 4 支例外傳遞測試。
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

