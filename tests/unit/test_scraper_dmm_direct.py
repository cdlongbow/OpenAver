"""
DMMScraper 行為：未被 proxy policy 選中時尊重系統代理（CD-134-6）。

DMM 開關看膠囊、代理選擇看 core/proxy_policy.py（TASK-163a-T3a）。
"""
import os

import pytest

from core.scrapers.dmm import DMMScraper
from core.proxy_policy import ProxySettings
from core.scrapers.models import ScraperConfig

_NO_PROXY = ScraperConfig(proxy_settings=ProxySettings(url=''))  # hermetic：不讀 live config


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

    def test_no_proxy_trust_env_true(self):
        """無代理設定 → trust_env=True（尊重系統代理，CD-134-6／F4 反轉後的新契約）"""
        scraper = DMMScraper(_NO_PROXY)
        assert scraper._session.trust_env is True, \
            "無代理設定 時 trust_env 必須為 True（尊重系統代理，見 spec-134 F4）"

    def test_no_proxy_proxies_empty(self):
        """無代理設定 → session.proxies 為空（交由 requests 依系統環境決定）"""
        scraper = DMMScraper(_NO_PROXY)
        assert not scraper._session.proxies, \
            "無代理設定 時 session.proxies 必須為空"

    def test_env_https_proxy_is_respected(self, clean_proxy_env):
        """HTTPS_PROXY 有設 → 解析結果含該 proxy"""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://env-proxy:1")
        scraper = DMMScraper(_NO_PROXY)
        assert _resolved_proxies(scraper)["https"] == "http://env-proxy:1"

    def test_env_no_proxy_excludes_dmm_host(self, clean_proxy_env):
        """HTTPS_PROXY 有設 + NO_PROXY 命中 DMM API host → 代理被排除"""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://env-proxy:1")
        clean_proxy_env.setenv("NO_PROXY", "api.video.dmm.co.jp")
        scraper = DMMScraper(_NO_PROXY)
        assert _resolved_proxies(scraper) == {}

    def test_env_no_proxy_vars_is_clean_direct(self, clean_proxy_env):
        """無任何代理環境變數 → 解析結果無代理"""
        scraper = DMMScraper(_NO_PROXY)
        assert _resolved_proxies(scraper) == {}


# ============================================================
# Tests merged from integration/test_new_scrapers.py TestDMMScraper
# ============================================================

class TestDMMScraperIntegration:
    """DMM scraper tests (merged from test_new_scrapers.py)"""

    def test_dmm_no_proxy_session_proxies_not_set(self):
        """Proxy 欄空白時 session.proxies 不被設定（直連模式）"""
        scraper = DMMScraper(_NO_PROXY)
        assert not scraper._session.proxies, \
            "無代理設定 時 session.proxies 不應被設定"

