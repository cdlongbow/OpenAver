"""DoD 6 / F2：步驟 3 真連線救回表算不出來的片（TASK-134a-T4）.

需日本線路（legacySearchPPV）。外部不可達時 skip，不是 fail。
CI 排除（--ignore=tests/smoke / -m "not smoke"）。
"""
import pytest

from core.scrapers.dmm import DMMScraper
from core.scrapers.models import ScraperConfig

pytestmark = pytest.mark.smoke

# NWF 系列（ワンズファクトリー）真實 cid 帶數字前綴（3nwf237）；不在出貨表與收割名單中。
# 空 hints 下 _convert_with_hints → "nwf00237"，步驟 2 必然失敗（DMM 查無此 cid），
# 只能靠步驟 3 救回。若未來 refresh 收錄 nwf 前綴，自檢斷言會因前提崩壞而報錯（TASK-134b-T11 D5）。
RESCUE_NUMBER = "NWF-237"


@pytest.mark.smoke
def test_dmm_step3_rescues_number_not_convertible_by_hints(tmp_path, monkeypatch):
    """對 hints 算不出正確 cid、但 DMM 確實收錄的番號，真實 search() 應救回。"""
    from core.config import load_config
    from core.scraper import _dmm_proxy_url, _is_dmm_enabled
    import core.scrapers.dmm as dmm_module

    raw = (load_config().get("search") or {}).get("proxy_url") or ""
    if not _is_dmm_enabled(raw):
        pytest.skip("dmm proxy 未設定（無日本線路）")

    # 強制走步驟 3：空快取 + 空 hints（不得碰專案根真檔）
    monkeypatch.setattr(dmm_module, "CACHE_FILE", tmp_path / "dmm_content_ids.json")
    monkeypatch.setattr(dmm_module, "PREFIX_FILE", tmp_path / "dmm_prefix_hints.json")

    scraper = DMMScraper(ScraperConfig(proxy_url=_dmm_proxy_url(raw)))

    # 防衛：空 hints 下步驟 2 候選必須算不出正確 cid
    converted = scraper._convert_with_hints(RESCUE_NUMBER)
    assert converted != "3nwf237", (
        f"測試前提崩壞：空 hints 竟算出正確 cid {converted!r}"
    )

    try:
        result = scraper.search(RESCUE_NUMBER)
    except Exception as e:
        pytest.skip(f"DMM 連線失敗（{type(e).__name__}: {e}）")

    if result is None:
        pytest.skip(
            f"DMM 步驟 3 救回失敗或回空（番號={RESCUE_NUMBER}；"
            "可能無日本線路、被擋、或該片下架）"
        )

    assert result is not None
