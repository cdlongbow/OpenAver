"""TASK-163a-T5 — 重刮預覽／指定來源搜尋回報 access_error。

假回應只驗接線；2026-10-09 實測台灣直連活站回 200，沒有可重現的真封鎖回應。
"""
import pytest

import core.scraper as scraper_mod
from core.scrapers.errors import SourceBlocked
from core.scrapers.models import Video


@pytest.fixture(autouse=True)
def _isolated(temp_config_path, monkeypatch):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    import core.scrapers.dmm as dmm_module

    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)


def test_auto_search_dmm_refused_other_sources_still_return(monkeypatch):
    class _Blocked:
        def search(self, number):
            raise SourceBlocked("DMM: HTTP 403")

    class _Bus:
        def search(self, number):
            return Video(number="SONE-205", title="t", source="javbus")

    monkeypatch.setattr(scraper_mod, "get_enabled_source_ids", lambda availability_map=None: ["dmm", "javbus"])
    monkeypatch.setattr(scraper_mod, "DMMScraper", lambda *a, **k: _Blocked())
    monkeypatch.setattr(scraper_mod, "JavBusScraper", lambda *a, **k: _Bus())
    result = scraper_mod.search_jav("SONE-205", source="auto")
    assert result is not None and result["_source"] == "javbus"
