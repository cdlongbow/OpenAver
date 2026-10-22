"""test_dmm_run_maker.py — DMM 片商最新作品 run_maker 的例外分類（TASK-175c-T9，plan CD-175c-8）。

站方回應（probe、片商清單、官方番號）不在單元測試裡造假：靠活站金絲雀（tests/smoke/test_dmm_search_canary.py）。
這裡只剩不碰站方回應的一案：provider 內部步驟丟出任何例外，run_maker 都要回 `maker_unreachable`（不是 `maker_not_found`）。
"""
import pytest

from core.scrapers.errors import SourceBlocked
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import EntityRef, Kind, MakerSearchResult

LABEL = "S1"
DMM_NAME = "エスワン ナンバーワンスタイル"
SPELLINGS = ["S1", DMM_NAME]
MAKER_ID = "3152"

EXCEPTIONS = [
    SourceBlocked("403"),
]


@pytest.mark.parametrize("stage", ["list"])
@pytest.mark.parametrize("exc", EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_resolve_or_list_failure_is_unreachable_not_not_found(monkeypatch, stage, exc):
    """〔使用者點片商膠囊時 DMM 暫時擋住（403）→ 本該是「連不上」且膠囊保留；碼被換成「查無」後出現片商錯誤頁並把
    膠囊收起，使用者以為 DMM 沒有這家片商，本次工作階段再也點不到〕。except 寬度是契約（BE-TEST-33）：
    resolve 階段與 list 階段各注入。"""
    def boom(*a, **kw):
        raise exc

    ref = EntityRef(Kind.MAKER, MAKER_ID, DMM_NAME)
    if stage == "resolve":
        monkeypatch.setattr(DMMProvider, "_resolve_maker", boom)
    else:
        monkeypatch.setattr(DMMProvider, "_resolve_maker", lambda self, names: ref)
        monkeypatch.setattr(DMMProvider, "list_entity", boom)
    out = DMMProvider().run_maker("s1", LABEL, SPELLINGS, 0)
    assert out == MakerSearchResult([], False, "maker_unreachable")
