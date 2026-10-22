"""
tests/unit/test_javlibrary_scraper.py
──────────────────────────────────────
CF 不可用／視窗未建立時必須拋特定例外的契約守衛。

不是站方 HTML 解析測試——這些例外是 0.13.13 出貨的
「灰化並說明原因」使用者可見行為的後端契約。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.cf_transport import CfTransportUnavailable
from core.scrapers.javlibrary import JavLibraryScraper

PATCH_TARGET = "core.scrapers.javlibrary.get_cf_transport"


# ──────────────────────────────────────
# (e) transport None → CfTransportUnavailable
# ──────────────────────────────────────

def test_search_no_transport_raises_unavailable():
    """get_cf_transport() 回傳 None 應拋 CfTransportUnavailable"""
    with patch(PATCH_TARGET, return_value=None):
        scraper = JavLibraryScraper()
        with pytest.raises(CfTransportUnavailable):
            scraper.search("TCD-332")


def test_search_all_versions_transport_none_raises():
    """get_cf_transport() None → CfTransportUnavailable。"""
    with patch(PATCH_TARGET, return_value=None):
        with pytest.raises(CfTransportUnavailable):
            JavLibraryScraper().search_all_versions("MIDV-010")


def test_fetch_by_detail_url_transport_none_raises():
    """fetch_by_detail_url：transport None → CfTransportUnavailable。"""
    with patch(PATCH_TARGET, return_value=None):
        with pytest.raises(CfTransportUnavailable):
            JavLibraryScraper().fetch_by_detail_url(
                "https://www.javlibrary.com/ja/javtest.html", "TCD-332"
            )
