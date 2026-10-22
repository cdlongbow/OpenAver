"""
test_javbus_scraper.py - JavBus 契約守衛（非站方 HTML 解析）

保留：
- Accept-Encoding 不得宣告 br（無 Brotli 解碼器）
- ConnectionError → TimeoutError 的 scraper↔dispatcher 例外契約
"""

import pytest
from unittest.mock import patch, MagicMock
import requests


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def scraper_zh():
    """zh-tw lang scraper with rate_limit mocked."""
    from core.scrapers.javbus import JavBusScraper
    with patch("core.scrapers.javbus.rate_limit"):
        scraper = JavBusScraper(lang="zh-tw")
        yield scraper


# ============================================================
# Accept-Encoding guard — br 不應出現（無 Brotli 解碼器）
# ============================================================

def test_accept_encoding_no_brotli():
    """JavBusScraper headers 不應宣告 br（專案無 brotli 依賴）"""
    from core.scrapers import JavBusScraper
    scraper = JavBusScraper()
    ae = scraper._session.headers.get('Accept-Encoding', '')
    assert 'br' not in ae, f"Accept-Encoding 不應含 br: {ae!r}"
    assert 'gzip' in ae, f"Accept-Encoding 應含 gzip: {ae!r}"


# ============================================================
# T60-5 / B2: ConnectionError 被 catch 並 re-raise 為 TimeoutError
# ============================================================

class TestConnectionErrorHandling:
    """B2: DNS/proxy/network failure 時不應整批崩潰，
    三個 HTTP 請求點統一 re-raise 為 TimeoutError，
    search_by_keyword 跳過繼續。"""

    def test_search_connection_error_raises_timeout(self, scraper_zh):
        """search() 撞 ConnectionError → 拋 TimeoutError（不洩漏底層 exception）"""
        scraper_zh._session.get = MagicMock(side_effect=requests.ConnectionError("DNS fail"))
        with pytest.raises(TimeoutError):
            scraper_zh.search("SNOS-143")


    def test_search_by_keyword_get_ids_failure_returns_empty(self, scraper_zh):
        """outer call：get_ids_from_search 本身撞 ConnectionError → 不讓 TimeoutError 穿透，回空 list

        Codex 2026-05-28 review P1 修正：不 mock get_ids_from_search，
        讓真實路徑跑到 _session.get 撞 ConnectionError → get_ids_from_search
        re-raise TimeoutError → search_by_keyword outer try/except 必須攔住。
        """
        scraper_zh._session.get = MagicMock(side_effect=requests.ConnectionError("dns fail"))
        result = scraper_zh.search_by_keyword("SONE")
        assert result == []
