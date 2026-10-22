"""test_dmm_entity_list.py — DMM 宣告能力（TASK-175c-T8）。

站方回應形狀、實體清單、官方番號、守衛 belongs 一律不在單元測試裡造假回應：靠活站金絲雀
（tests/smoke/test_dmm_search_canary.py）。這裡只剩不碰站方回應的宣告能力檢查。
"""
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import Kind


def test_capabilities_are_exactly_the_five_entities_plus_keyword():
    """〔使用者把 DMM 排第一打 MIDV／MIDV-01 → 若誤宣告 CODE／PARTIAL，結果混入 48midv… 重製版與別片商；
    MAKER 自 T9 起與 run_maker 同時宣告（沒有 run_maker 就宣告，片商膠囊一按就丟 TypeError）〕"""
    assert DMMProvider.capabilities == frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER, Kind.KEYWORD})
    assert not DMMProvider.capabilities & {Kind.CODE, Kind.PARTIAL}
    assert DMMProvider.supports_discovery is False and DMMProvider.fallback_streaming is True
