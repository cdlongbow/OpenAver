"""63c-4: _get_uncensored_sources staged promotion（US4 / CD-63c-8）。

驗 metatube 無碼 provider 依番號類型 prepend 到 builtin 前；無 metatube → 純 builtin（B1 一致）。
patch get_enabled_source_ids（使用端 core.scraper）模擬「enabled + available」的來源集，
隔離 staging 過濾邏輯（availability gate 本身由 get_enabled_source_ids 自己的測試覆蓋）。
"""
import pytest

from core import scraper


def _patch_enabled(monkeypatch, sids):
    """模擬 get_enabled_source_ids 回傳（已含 enabled + available + order gate）。"""
    monkeypatch.setattr(
        scraper, "get_enabled_source_ids",
        lambda availability_map=None: list(sids),
    )
    monkeypatch.setattr(scraper.metatube_state, "availability_map", lambda: {})
    monkeypatch.setattr(scraper.metatube_state, "routing_availability_map", lambda: {})


# ─── HEYZO 分支 ───

def test_heyzo_metatube_available_prepended(monkeypatch):
    _patch_enabled(monkeypatch, ["metatube:HEYZO"])
    assert scraper._get_uncensored_sources("HEYZO-3333") == ["metatube:HEYZO", "heyzo", "avsox"]


def test_heyzo_metatube_unavailable_builtin_only(monkeypatch):
    # unavailable → get_enabled_source_ids 已 gate 排除 → 模擬回空 metatube
    _patch_enabled(monkeypatch, [])
    assert scraper._get_uncensored_sources("HEYZO-3333") == ["heyzo", "avsox"]


def test_heyzo_no_metatube_enabled_b1_behavior(monkeypatch):
    _patch_enabled(monkeypatch, ["javbus", "heyzo"])  # builtin enabled，無 metatube
    assert scraper._get_uncensored_sources("HEYZO-3333") == ["heyzo", "avsox"]


# ─── FC2 分支 ───

def test_fc2_metatube_three_providers_order_preserved(monkeypatch):
    _patch_enabled(monkeypatch, ["metatube:FC2", "metatube:fc2hub"])
    assert scraper._get_uncensored_sources("FC2-PPV-3333") == [
        "metatube:FC2", "metatube:fc2hub", "fc2", "avsox",
    ]


def test_fc2_only_fc2_capable_metatube_picked(monkeypatch):
    # HEYZO enabled 但非 FC2 系 → FC2 番號不該選它
    _patch_enabled(monkeypatch, ["metatube:HEYZO"])
    assert scraper._get_uncensored_sources("FC2-PPV-3333") == ["fc2", "avsox"]


def test_fc2ppvdb_picked(monkeypatch):
    _patch_enabled(monkeypatch, ["metatube:FC2PPVDB"])
    assert scraper._get_uncensored_sources("fc2-123") == ["metatube:FC2PPVDB", "fc2", "avsox"]


# ─── 日期型分支 ───

def test_date_type_caribbeancom_prepended(monkeypatch):
    _patch_enabled(monkeypatch, ["metatube:Caribbeancom"])
    result = scraper._get_uncensored_sources("020125-001")
    assert result == ["metatube:Caribbeancom", "d2pass", "heyzo", "fc2", "avsox"]


def test_date_type_excludes_fc2_and_heyzo_metatube(monkeypatch):
    # HEYZO / FC2 系 metatube 不屬日期型 → 日期番號不選它們，只選 Caribbeancom
    _patch_enabled(monkeypatch, ["metatube:HEYZO", "metatube:FC2", "metatube:Caribbeancom"])
    result = scraper._get_uncensored_sources("020125-001")
    assert result == ["metatube:Caribbeancom", "d2pass", "heyzo", "fc2", "avsox"]


def test_date_type_no_metatube_b1_behavior(monkeypatch):
    _patch_enabled(monkeypatch, [])
    assert scraper._get_uncensored_sources("020125-001") == ["d2pass", "heyzo", "fc2", "avsox"]


def test_date_type_multiple_date_providers_order(monkeypatch):
    _patch_enabled(monkeypatch, ["metatube:1Pondo", "metatube:10musume"])
    result = scraper._get_uncensored_sources("020125_001")
    assert result == ["metatube:1Pondo", "metatube:10musume", "d2pass", "heyzo", "fc2", "avsox"]


# ─── 常數正確性 ───

def test_date_uncensored_constant_excludes_branch_providers():
    from core.scrapers.utils import METATUBE_DATE_UNCENSORED, METATUBE_UNCENSORED
    # 日期型 = 全無碼 去掉 fc2/heyzo 分支各自處理的 4 個
    assert METATUBE_DATE_UNCENSORED == METATUBE_UNCENSORED - {"HEYZO", "FC2", "FC2PPVDB", "fc2hub"}
    assert len(METATUBE_DATE_UNCENSORED) == 11


# ─── TASK-130b-T3：_get_uncensored_sources 吃的是 routing map（行為測試） ───
#
# 上面所有測試都把 get_enabled_source_ids 整支換掉，因此 availability gate
# 完全沒有跑——把 _get_uncensored_sources 裡的 routing_availability_map()
# 改回 availability_map()，那些測試會全部照樣綠。以下兩支不 patch
# get_enabled_source_ids，改餵真 config 讓真 gate 跑起來，是這個呼叫點
# 唯一的行為級守衛。

def _patch_real_gate(monkeypatch, display_map, routing_map):
    """餵真 config + 兩張語意不同的 map，讓真的 availability gate 跑起來。"""
    from core import source_settings
    fake_config = {
        'sources': [
            {'id': 'metatube:HEYZO', 'type': 'metatube', 'enabled': True,
             'order': 0, 'manual_only': False},
        ]
    }
    monkeypatch.setattr(source_settings, "load_config", lambda: fake_config)
    monkeypatch.setattr(scraper.metatube_state, "availability_map", lambda: dict(display_map))
    monkeypatch.setattr(scraper.metatube_state, "routing_availability_map", lambda: dict(routing_map))


def test_uncensored_sources_uses_routing_map_expired_source_retried(monkeypatch):
    """冷卻已過期（display=False、routing=True）→ 該無碼來源仍排進候選。

    使用者流程：接的無碼 provider 抖過一次網路 → 冷卻窗口過後搜一部 HEYZO
    番號 → 那家要重新回到候選清單裡，而不是永遠消失。
    """
    _patch_real_gate(monkeypatch,
                     display_map={'metatube:HEYZO': False},
                     routing_map={'metatube:HEYZO': True})
    assert scraper._get_uncensored_sources("HEYZO-3333") == [
        "metatube:HEYZO", "heyzo", "avsox",
    ]


def test_uncensored_sources_cooling_source_excluded(monkeypatch):
    """冷卻中（兩張 map 都 False）→ 該無碼來源被 gate 排除，只剩 builtin。"""
    _patch_real_gate(monkeypatch,
                     display_map={'metatube:HEYZO': False},
                     routing_map={'metatube:HEYZO': False})
    assert scraper._get_uncensored_sources("HEYZO-3333") == ["heyzo", "avsox"]
