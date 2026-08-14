"""
tests/unit/test_javlibrary_scraper.py
──────────────────────────────────────
CF 不可用／視窗未建立時必須拋特定例外的契約守衛。

不是站方 HTML 解析測試——這些例外是 0.13.13 出貨的
「灰化並說明原因」使用者可見行為的後端契約。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.scrapers.javlibrary import JavLibraryScraper

# ──────────────────────────────────────
# 共用 fixture HTML（僅供 CF challenge 形狀辨識）
# ──────────────────────────────────────

CF_CHALLENGE_HTML = """\
<html><head><title>Just a moment...</title></head><body>
  <form id="challenge-form"></form>
</body></html>"""

# 多版本列表頁（模擬 MIDV-010 風格）— 供 detail-fetch CF 路徑用
MULTI_VERSION_LIST_HTML = """\
<html><head><title>品番検索結果</title></head><body>
  <div class="video">
    <a href="./javlidaori.html" title="MIDV-010 Angel Kiss ビアンたちの愛情物語">MIDV-010 Angel Kiss</a>
    <a href="">これが欲しい</a><a href="">見た</a><a href="">持ってる</a>
  </div>
  <div class="video">
    <a href="./javme3bu7e.html" title="MIDV-010 連続中出しオーガズムSP">MIDV-010 連続...</a>
    <a href="">これが欲しい</a><a href="">見た</a><a href="">持ってる</a>
  </div>
  <div class="video">
    <a href="./javmidv100.html" title="MIDV-100 隣のお姉さん">MIDV-100 隣の...</a>
    <a href="">これが欲しい</a><a href="">見た</a><a href="">持ってる</a>
  </div>
</body></html>"""

PATCH_TARGET = "core.scrapers.javlibrary.get_cf_transport"


def _make_transport(*html_responses: str) -> MagicMock:
    """建立回傳依序 HTML 的 mock transport"""
    transport = MagicMock()
    transport.fetch.side_effect = list(html_responses)
    return transport


# ──────────────────────────────────────
# (e) transport None → CfTransportUnavailable
# ──────────────────────────────────────

def test_search_no_transport_raises_unavailable():
    """get_cf_transport() 回傳 None 應拋 CfTransportUnavailable"""
    with patch(PATCH_TARGET, return_value=None):
        scraper = JavLibraryScraper()
        with pytest.raises(CfTransportUnavailable):
            scraper.search("TCD-332")


# ──────────────────────────────────────
# (f) fetch 回 CF challenge HTML → CfChallengeRequired
# ──────────────────────────────────────

def test_search_cf_challenge_raises_required():
    """fetch 回 CF challenge page 應拋 CfChallengeRequired"""
    transport = _make_transport(CF_CHALLENGE_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        scraper = JavLibraryScraper()
        with pytest.raises(CfChallengeRequired):
            scraper.search("TCD-332")


# ── CF 案例 ──

def test_search_all_versions_list_cf_challenge_raises():
    """search_all_versions：列表頁遇 CF challenge → CfChallengeRequired。"""
    transport = _make_transport(CF_CHALLENGE_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        with pytest.raises(CfChallengeRequired):
            JavLibraryScraper().search_all_versions("MIDV-010")


def test_search_all_versions_detail_cf_challenge_raises():
    """search_all_versions：detail fetch 遇 CF challenge → CfChallengeRequired。"""
    transport = _make_transport(MULTI_VERSION_LIST_HTML, CF_CHALLENGE_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        with pytest.raises(CfChallengeRequired):
            JavLibraryScraper().search_all_versions("MIDV-010")


def test_search_all_versions_transport_none_raises():
    """get_cf_transport() None → CfTransportUnavailable。"""
    with patch(PATCH_TARGET, return_value=None):
        with pytest.raises(CfTransportUnavailable):
            JavLibraryScraper().search_all_versions("MIDV-010")


def test_fetch_by_detail_url_cf_challenge_raises():
    """fetch_by_detail_url：detail fetch 遇 CF challenge → CfChallengeRequired。"""
    transport = _make_transport(CF_CHALLENGE_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        with pytest.raises(CfChallengeRequired):
            JavLibraryScraper().fetch_by_detail_url(
                "https://www.javlibrary.com/ja/javtest.html", "TCD-332"
            )


def test_fetch_by_detail_url_transport_none_raises():
    """fetch_by_detail_url：transport None → CfTransportUnavailable。"""
    with patch(PATCH_TARGET, return_value=None):
        with pytest.raises(CfTransportUnavailable):
            JavLibraryScraper().fetch_by_detail_url(
                "https://www.javlibrary.com/ja/javtest.html", "TCD-332"
            )
