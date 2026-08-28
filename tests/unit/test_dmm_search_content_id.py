"""TASK-134a-T4 — lock _search_content_id + zero-write after deleting _learn_prefix."""
import json
from unittest.mock import MagicMock, patch

import pytest

from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig, Video


def _make_mock_resp(status_code=200, json_data=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json = lambda: json_data
    return mock_resp


def _legacy_search_payload(cids: list[str]) -> dict:
    return {
        "data": {
            "legacySearchPPV": {
                "result": {
                    "contents": [{"id": cid} for cid in cids],
                }
            }
        }
    }


@pytest.fixture
def dmm_scraper(tmp_path, monkeypatch):
    import core.scrapers.dmm as dmm_module

    monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "dmm_content_ids.json")
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "dmm_prefix_hints.json")
    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)
    return DMMScraper(ScraperConfig(proxy_url="http://test-proxy:8080"))


def test_learn_prefix_and_save_prefix_hint_removed():
    assert hasattr(DMMScraper, "_learn_prefix") is False
    assert hasattr(DMMScraper, "_save_prefix_hint") is False


def test_search_step3_hit_prefix_file_unchanged_cache_gains_entry(
    tmp_path, monkeypatch
):
    """DoD 2：快取 miss → hints miss → 步驟 3 命中後，PREFIX 逐位元組不變、CACHE 有新增。"""
    import core.scrapers.dmm as dmm_module

    prefix_file = tmp_path / "dmm_prefix_hints.json"
    cache_file = tmp_path / "dmm_content_ids.json"
    prefix_file.write_text(
        json.dumps({"zzza": "h_1510"}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    cache_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(dmm_module, "PREFIX_FILE", prefix_file)
    monkeypatch.setattr(dmm_module, "CACHE_FILE", cache_file)
    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)

    # BE-TEST-10：基準值必須在被測操作之前取得
    prefix_before = prefix_file.read_bytes()

    scraper = DMMScraper(ScraperConfig(proxy_url="http://test-proxy:8080"))
    video = Video(number="ERK-116", title="test", source="dmm")

    # hints miss（步驟 2 無轉換結果）→ 步驟 3 命中 → _fetch_by_id 成功
    monkeypatch.setattr(scraper, "_convert_with_hints", lambda number: "")
    monkeypatch.setattr(scraper, "_search_content_id", lambda number: "erk00116")
    monkeypatch.setattr(
        scraper, "_fetch_by_id", lambda cid: video if cid == "erk00116" else None
    )

    result = scraper.search("ERK-116")

    assert result is not None
    assert prefix_file.read_bytes() == prefix_before
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache.get("ERK-116") == "erk00116"


def test_search_content_id_rejects_gerk116_for_erk_prefix(dmm_scraper):
    """DoD 3 反向鎖：僅有 gerk116 時不得誤配 ERK-116。"""
    resp = _make_mock_resp(
        status_code=200,
        json_data=_legacy_search_payload(["gerk116"]),
    )
    with patch.object(dmm_scraper._session, "post", return_value=resp):
        assert dmm_scraper._search_content_id("ERK-116") is None


def test_search_content_id_accepts_erk00116(dmm_scraper):
    """DoD 4 正向鎖：含 erk00116 時精確命中。"""
    resp = _make_mock_resp(
        status_code=200,
        json_data=_legacy_search_payload(["gerk116", "erk00116"]),
    )
    with patch.object(dmm_scraper._session, "post", return_value=resp):
        assert dmm_scraper._search_content_id("ERK-116") == "erk00116"
