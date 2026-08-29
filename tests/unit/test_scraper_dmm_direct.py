"""
Tests for Phase 37d T3 — Proxy `direct` 模式

覆蓋 _is_dmm_enabled() / _dmm_proxy_url() helpers 和 DMMScraper 行為。
"""
import json
import os

import pytest
from unittest.mock import patch, MagicMock

from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig


# ── TestIsDmmEnabled ──────────────────────────────────────────────────────────

class TestIsDmmEnabled:
    """_is_dmm_enabled() helper 邊界條件"""

    def test_empty_string_returns_false(self):
        from core.scraper import _is_dmm_enabled
        assert _is_dmm_enabled('') is False

    def test_whitespace_only_returns_false(self):
        from core.scraper import _is_dmm_enabled
        assert _is_dmm_enabled('  ') is False

    def test_direct_lowercase_returns_true(self):
        from core.scraper import _is_dmm_enabled
        assert _is_dmm_enabled('direct') is True

    def test_direct_uppercase_returns_true(self):
        from core.scraper import _is_dmm_enabled
        assert _is_dmm_enabled('DIRECT') is True

    def test_real_proxy_url_returns_true(self):
        from core.scraper import _is_dmm_enabled
        assert _is_dmm_enabled('http://192.168.1.1:8888') is True


# ── TestDmmProxyUrl ───────────────────────────────────────────────────────────

class TestDmmProxyUrl:
    """_dmm_proxy_url() helper 邊界條件"""

    def test_direct_lowercase_returns_empty(self):
        from core.scraper import _dmm_proxy_url
        assert _dmm_proxy_url('direct') == ''

    def test_direct_uppercase_returns_empty(self):
        from core.scraper import _dmm_proxy_url
        assert _dmm_proxy_url('DIRECT') == ''

    def test_real_proxy_url_returns_original(self):
        from core.scraper import _dmm_proxy_url
        url = 'http://192.168.1.1:8888'
        assert _dmm_proxy_url(url) == url


# ── TestDmmScraperDirect ──────────────────────────────────────────────────────

class TestDmmScraperDirect:
    """DMMScraper session.proxies 行為"""

    def test_real_proxy_url_proxies_set(self):
        """proxy_url='http://...' → session.proxies 已設定"""
        from core.scrapers import DMMScraper, ScraperConfig
        proxy = 'http://192.168.1.1:8888'
        scraper = DMMScraper(ScraperConfig(proxy_url=proxy))
        assert scraper._session.proxies.get('http') == proxy
        assert scraper._session.proxies.get('https') == proxy


# ── TestSearchDirect ──────────────────────────────────────────────────────────

class TestSearchDirect:
    """search_jav() 整合測試 — 確認 direct 模式正確路由"""

    def test_search_jav_direct_includes_dmm(self):
        """proxy_url='direct' → dmm_config 非 None → DMM 進入 scrapers 列表"""
        from core.scraper import _is_dmm_enabled, _dmm_proxy_url
        proxy_url = 'direct'
        assert _is_dmm_enabled(proxy_url) is True
        assert _dmm_proxy_url(proxy_url) == ''

        # 驗證傳給 DMMScraper 的 proxy_url 是空字串（直連）
        from core.scrapers import DMMScraper, ScraperConfig
        dmm_config = ScraperConfig(proxy_url=_dmm_proxy_url(proxy_url))
        scraper = DMMScraper(dmm_config)
        assert scraper._session.trust_env is True, \
            "direct 模式下 DMMScraper 尊重系統代理（CD-134-6 反轉 4ee0baa2 的舊契約）"

    def test_search_jav_direct_dmm_config_not_none(self):
        """proxy_url='direct' → _is_dmm_enabled=True → dmm_config 建立（非 None）"""
        from core.scraper import _is_dmm_enabled, _dmm_proxy_url
        from core.scrapers import ScraperConfig
        proxy_url = 'direct'
        dmm_config = ScraperConfig(proxy_url=_dmm_proxy_url(proxy_url)) \
            if _is_dmm_enabled(proxy_url) else None
        assert dmm_config is not None, \
            "proxy_url='direct' 時 dmm_config 不應為 None"

    def test_empty_proxy_url_dmm_config_is_none(self):
        """proxy_url='' → _is_dmm_enabled=False → dmm_config 為 None

        關鍵邊界：空字串不可被誤判為 direct，DMM 不得啟用。
        """
        from core.scraper import _is_dmm_enabled, _dmm_proxy_url
        from core.scrapers import ScraperConfig
        proxy_url = ''
        # 1. _is_dmm_enabled 必須為 False
        assert _is_dmm_enabled(proxy_url) is False, \
            "proxy_url='' 時 _is_dmm_enabled 必須為 False"
        # 2. dmm_config 必須為 None
        dmm_config = ScraperConfig(proxy_url=_dmm_proxy_url(proxy_url)) \
            if _is_dmm_enabled(proxy_url) else None
        assert dmm_config is None, \
            "proxy_url='' 時 dmm_config 必須為 None（不得啟用 DMM）"


# ── TestDmmRespectsSystemProxy ───────────────────────────────────────────────

_PROXY_ENVS = (
    "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
    "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy",
)


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for name in _PROXY_ENVS:
        monkeypatch.delenv(name, raising=False)
    # urllib 的 getproxies_environment（requests 經 get_environ_proxies 走它）掃的是
    # **任何以 `_proxy` 結尾**的變數，不只上面那 8 個——開發機上若有 ftp_proxy /
    # socks_proxy 之類殘留，「無代理」那支會假紅。清乾淨這一整類。
    for name in [n for n in os.environ if n.lower().endswith("_proxy")]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _resolved_proxies(scraper, url="https://api.video.dmm.co.jp/graphql"):
    """把 requests 對環境變數的解析結果變成可斷言的具體值。"""
    return scraper._session.merge_environment_settings(url, {}, None, None, None)["proxies"]


class TestDmmRespectsSystemProxy:
    """CD-134-6／F4：direct 模式尊重系統代理（環境變數，三象限，斷言值互不相同）"""

    def test_empty_proxy_url_trust_env_true(self):
        """proxy_url='' → trust_env=True（尊重系統代理，CD-134-6／F4 反轉後的新契約）"""
        scraper = DMMScraper(ScraperConfig(proxy_url=''))
        assert scraper._session.trust_env is True, \
            "proxy_url='' 時 trust_env 必須為 True（尊重系統代理，見 spec-134 F4）"

    def test_empty_proxy_url_proxies_empty(self):
        """proxy_url='' → session.proxies 為空（交由 requests 依系統環境決定）"""
        scraper = DMMScraper(ScraperConfig(proxy_url=''))
        assert not scraper._session.proxies, \
            "proxy_url='' 時 session.proxies 必須為空"

    def test_explicit_proxy_url_proxies_set(self):
        """明確設定 proxy_url → session.proxies 包含 http/https 代理"""
        scraper = DMMScraper(ScraperConfig(proxy_url='http://x:1'))
        assert scraper._session.proxies == {
            'http': 'http://x:1',
            'https': 'http://x:1',
        }

    def test_env_https_proxy_is_respected(self, clean_proxy_env):
        """HTTPS_PROXY 有設 → 解析結果含該 proxy"""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://env-proxy:1")
        scraper = DMMScraper(ScraperConfig(proxy_url=''))
        assert _resolved_proxies(scraper)["https"] == "http://env-proxy:1"

    def test_env_no_proxy_excludes_dmm_host(self, clean_proxy_env):
        """HTTPS_PROXY 有設 + NO_PROXY 命中 DMM API host → 代理被排除"""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://env-proxy:1")
        clean_proxy_env.setenv("NO_PROXY", "api.video.dmm.co.jp")
        scraper = DMMScraper(ScraperConfig(proxy_url=''))
        assert _resolved_proxies(scraper) == {}

    def test_env_no_proxy_vars_is_clean_direct(self, clean_proxy_env):
        """無任何代理環境變數 → 解析結果無代理"""
        scraper = DMMScraper(ScraperConfig(proxy_url=''))
        assert _resolved_proxies(scraper) == {}


# ============================================================
# Mock Data (from test_new_scrapers.py)
# ============================================================

DMM_SEARCH_RESPONSE = {
    "data": {
        "legacySearchPPV": {
            "result": {
                "contents": [{"id": "sone00205"}]
            }
        }
    }
}

DMM_DETAIL_RESPONSE = {
    "data": {
        "ppvContent": {
            "id": "sone00205",
            "title": "成人への卒業",
            "description": "テスト",
            "packageImage": {"largeUrl": "https://pics.dmm.co.jp/sone205pl.jpg"},
            "makerReleasedAt": "2024-03-19T00:00:00+09:00",
            "duration": 120,
            "actresses": [{"name": "Nana Miho"}],
            "directors": [],
            "series": {"name": ""},
            "maker": {"name": "S1 NO.1 STYLE"},
            "makerContentId": "SONE-205",
        }
    }
}


def _make_mock_resp(status_code=200, json_data=None, content=None):
    """Build a MagicMock that mimics requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json = lambda: json_data
    if content is not None:
        mock_resp.content = content
    return mock_resp


# ============================================================
# Tests merged from integration/test_new_scrapers.py TestDMMScraper
# ============================================================

class TestDMMScraperIntegration:
    """DMM scraper tests (merged from test_new_scrapers.py)"""

    @pytest.fixture(autouse=True)
    def _no_rate_limit(self, monkeypatch):
        """跳過 rate_limit sleep，加速測試"""
        monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)

    @pytest.fixture
    def dmm_scraper(self, tmp_path, monkeypatch):
        """DMM scraper with isolated cache files"""
        import core.scrapers.dmm as dmm_module
        monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "dmm_content_ids.json")
        monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "dmm_prefix_hints.json")
        monkeypatch.setattr(dmm_module, "_shipped_table_cache", {})
        monkeypatch.setattr(dmm_module, "_local_hints_cache", None)
        monkeypatch.setattr(dmm_module, "_local_hints_cache_mtime", None)
        config = ScraperConfig(proxy_url="http://test-proxy:8080")
        return DMMScraper(config)

    def test_dmm_no_proxy_session_proxies_not_set(self):
        """無 proxy_url 時 session.proxies 不被設定（直連模式）"""
        scraper = DMMScraper()  # 無 proxy_url → 直連模式
        assert not scraper._session.proxies, \
            "proxy_url='' 時 session.proxies 不應被設定"

    def test_dmm_cache_hit(self, dmm_scraper, tmp_path, monkeypatch):
        """快取命中時不呼叫 search query（detail query + probe query，不超過 2 次）"""
        import core.scrapers.dmm as dmm_module
        cache_path = tmp_path / "dmm_content_ids.json"
        cache_path.write_text('{"SONE-205": "sone00205"}', encoding='utf-8')

        detail_resp = _make_mock_resp(status_code=200, json_data=DMM_DETAIL_RESPONSE)

        with patch.object(dmm_scraper._session, 'post', return_value=detail_resp) as mock_post, \
             patch.object(dmm_scraper, '_fetch_tags_from_html', return_value=[]), \
             patch('core.scrapers.dmm.rate_limit'):
            video = dmm_scraper.search("SONE-205")

        assert video is not None
        assert video.title == "成人への卒業"
        assert video.number == "SONE-205"
        for call_args in mock_post.call_args_list:
            payload = call_args[1].get('json', {}) if call_args[1] else {}
            query_str = payload.get('query', '')
            assert 'legacySearchPPV' not in query_str, "Cache hit should not trigger search query"

    def test_dmm_graphql_success(self, dmm_scraper):
        """無快取時依次呼叫 search query + detail query，成功返回 Video"""
        search_resp = _make_mock_resp(status_code=200, json_data=DMM_SEARCH_RESPONSE)
        detail_resp = _make_mock_resp(status_code=200, json_data=DMM_DETAIL_RESPONSE)

        with patch.object(dmm_scraper._session, 'post', side_effect=[
            _make_mock_resp(status_code=404),  # 補零第一試 → _fetch_by_id → 404
            _make_mock_resp(status_code=404),  # 不補零第二試 → _fetch_by_id → 404
            search_resp,                        # _search_content_id
            detail_resp,                        # _fetch_by_id(discovered_cid)
        ]), \
             patch.object(dmm_scraper, '_fetch_tags_from_html', return_value=[]), \
             patch('core.scrapers.dmm.rate_limit'):
            video = dmm_scraper.search("SONE-205")

        assert video is not None
        assert video.number == "SONE-205"
        assert video.title == "成人への卒業"
        assert video.source == "dmm"
        assert "dmm.co.jp" in video.detail_url
        assert video.date == "2024-03-19"
        assert len(video.actresses) == 1
        assert video.actresses[0].name == "Nana Miho"
        assert video.maker == "S1 NO.1 STYLE"

    def test_dmm_cache_isolation(self, dmm_scraper, tmp_path):
        """搜尋成功後 cache 寫入 tmp_path，不污染 project root"""
        detail_resp = _make_mock_resp(status_code=200, json_data=DMM_DETAIL_RESPONSE)

        with patch.object(dmm_scraper._session, 'post', return_value=detail_resp), \
             patch.object(dmm_scraper, '_fetch_tags_from_html', return_value=[]), \
             patch('core.scrapers.dmm.rate_limit'):
            video = dmm_scraper.search("SONE-205")

        # cache 應寫入 tmp_path 而非 project root
        assert (tmp_path / "dmm_content_ids.json").exists()
