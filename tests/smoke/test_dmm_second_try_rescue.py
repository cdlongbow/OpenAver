"""DoD 6：步驟 2 第二試／步驟 3 真連線救回（TASK-134b-T10）.

三筆各鎖不同路徑（見 TASK-134b-T10 佐證表 C）：
  MIDD-357 / KAWD-067 → 不補零第二試
  NWF-237             → 步驟 3（queryWord "NWF 237" → 3nwf237）

需日本線路。外部不可達時 skip；HTTP 通了但回空 → fail（與 D8 同形）。
CI 排除（--ignore=tests/smoke / -m "not smoke"）。
"""
import pytest

from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig

pytestmark = pytest.mark.smoke

# (番號, 期望 makerContentId) — 期望值由主 session 2026-08-29 實測，不得自行更動
RESCUE_CASES = (
    ("MIDD-357", "MIDD-357"),
    ("KAWD-067", "KAWD-067"),
    ("NWF-237", "NWF-237"),
)


@pytest.mark.smoke
@pytest.mark.parametrize("number,expected_number", RESCUE_CASES)
def test_dmm_rescues_second_try_or_step3_number(
    number, expected_number, tmp_path, monkeypatch
):
    """對補零算不出、但 DMM 確實收錄的番號，真實 search() 應救回正確片。"""
    from core.config import load_config
    from core.scraper import _dmm_proxy_url, _is_dmm_enabled
    import core.scrapers.dmm as dmm_module

    raw = (load_config().get("search") or {}).get("proxy_url") or ""
    if not _is_dmm_enabled(raw):
        pytest.skip("dmm proxy 未設定（無日本線路）")

    monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "dmm_content_ids.json")
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "dmm_prefix_hints.json")

    scraper = DMMScraper(ScraperConfig(proxy_url=_dmm_proxy_url(raw)))

    try:
        result = scraper.search(number)
    except Exception as e:
        pytest.skip(f"DMM 連線失敗（{type(e).__name__}: {e}）")

    if result is None:
        pytest.fail(
            f"DMM 救回失敗或回空（番號={number}；"
            "HTTP 已通但查無結果——不是環境未就緒）"
        )

    assert result.number == expected_number
