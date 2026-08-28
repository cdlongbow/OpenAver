"""TASK-134a-T6 — 步驟 3 回空時 debug.log 留痕（spec-134 F5 / CD-134-7）。"""
import logging

import pytest

import core.scrapers.dmm as dmm_module
from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig, Video

LOG_SNIPPET = "步驟 3 查無結果"


@pytest.fixture
def dmm_scraper(tmp_path, monkeypatch):
    monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "dmm_content_ids.json")
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "dmm_prefix_hints.json")
    monkeypatch.setattr(dmm_module, "_shipped_table_cache", {})
    monkeypatch.setattr(dmm_module, "_local_hints_cache", None)
    monkeypatch.setattr(dmm_module, "_local_hints_cache_mtime", None)
    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)
    return DMMScraper(ScraperConfig(proxy_url="http://test-proxy:8080"))


def test_step3_miss_logs_debug_with_number(dmm_scraper, caplog, monkeypatch):
    """DoD 1：discovered_cid 為 None → caplog 抓到一行 DEBUG，內容含番號。"""
    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", lambda number: "")
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: None)

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result = dmm_scraper.search("ZZZZ-999")

    assert result is None
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(
        LOG_SNIPPET in r.getMessage() and "ZZZZ-999" in r.getMessage()
        for r in debug_records
    )


def test_step3_hit_no_log(dmm_scraper, caplog, monkeypatch):
    """DoD 2 正向鎖：步驟 3 命中（discovered_cid 有值且 _fetch_by_id 成功）→ 不誤觸發。"""
    video = Video(number="ZZZZ-999", title="t", source="dmm")
    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", lambda number: "")
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: "zzzz00999")
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: video if cid == "zzzz00999" else None,
    )

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result = dmm_scraper.search("ZZZZ-999")

    assert result is not None
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)


def test_step2_hit_step3_not_reached_no_log(dmm_scraper, caplog, monkeypatch):
    """DoD 3：步驟 2 已成功 → 步驟 3 完全不執行 → 不誤導印步驟 3 失敗訊息。"""
    video = Video(number="ZZZZ-999", title="t", source="dmm")
    step3_called = {"value": False}

    def _search_content_id_spy(number):
        step3_called["value"] = True
        return None

    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", lambda number: "zzzz00999")
    monkeypatch.setattr(
        dmm_scraper,
        "_fetch_by_id",
        lambda cid: video if cid == "zzzz00999" else None,
    )
    monkeypatch.setattr(dmm_scraper, "_search_content_id", _search_content_id_spy)

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result = dmm_scraper.search("ZZZZ-999")

    assert result is not None
    assert step3_called["value"] is False
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)


def test_step3_cid_found_but_fetch_fails_no_log(dmm_scraper, caplog, monkeypatch):
    """DoD 4（A18 範圍縮小）：discovered_cid 有值但 _fetch_by_id 回 None → 不印。"""
    monkeypatch.setattr(dmm_scraper, "_convert_with_hints", lambda number: "")
    monkeypatch.setattr(dmm_scraper, "_search_content_id", lambda number: "zzzz00999")
    monkeypatch.setattr(dmm_scraper, "_fetch_by_id", lambda cid: None)

    with caplog.at_level(logging.DEBUG, logger=dmm_module.logger.name):
        result = dmm_scraper.search("ZZZZ-999")

    assert result is None
    assert not any(LOG_SNIPPET in r.getMessage() for r in caplog.records)
