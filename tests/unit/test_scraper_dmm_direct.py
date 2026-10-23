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


    def test_env_https_proxy_is_respected(self, clean_proxy_env):
        """HTTPS_PROXY 有設 → 解析結果含該 proxy"""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://env-proxy:1")
        scraper = DMMScraper(_NO_PROXY)
        assert _resolved_proxies(scraper)["https"] == "http://env-proxy:1"


# ============================================================
# Tests merged from integration/test_new_scrapers.py TestDMMScraper
# ============================================================


