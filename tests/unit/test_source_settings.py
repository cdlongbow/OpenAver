"""Unit tests for core/source_settings.py business-layer helpers (TASK-61a-1b).

Covers Runtime Auto Pool filtering (`get_enabled_source_ids`) and the
uncensored-mode single-source-of-truth (`is_uncensored_mode_effective`).
Also covers `get_all_source_ids_ordered()` (TASK-65a-1) and the
search-provider registry (`core.search_providers.registry`).
"""

from core import source_settings


# ---------------------------------------------------------------------------
# get_enabled_source_ids
# ---------------------------------------------------------------------------

def _patch_config(monkeypatch, fake_config):
    monkeypatch.setattr(
        'core.source_settings.load_config', lambda: fake_config
    )


def test_enabled_filter_excludes_disabled(monkeypatch):
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'dmm', 'type': 'builtin', 'enabled': True, 'order': 0, 'manual_only': False},
            {'id': 'javbus', 'type': 'builtin', 'enabled': False, 'order': 1, 'manual_only': False},
        ]
    })
    assert source_settings.get_enabled_source_ids() == ['dmm']


def test_order_sorting(monkeypatch):
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'c', 'type': 'builtin', 'enabled': True, 'order': 5, 'manual_only': False},
            {'id': 'a', 'type': 'builtin', 'enabled': True, 'order': 1, 'manual_only': False},
            {'id': 'b', 'type': 'builtin', 'enabled': True, 'order': 3, 'manual_only': False},
        ]
    })
    assert source_settings.get_enabled_source_ids() == ['a', 'b', 'c']


def test_manual_only_excluded_even_when_enabled(monkeypatch):
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'javlibrary', 'type': 'builtin', 'enabled': True, 'order': 0, 'manual_only': True},
            {'id': 'dmm', 'type': 'builtin', 'enabled': True, 'order': 1, 'manual_only': False},
        ]
    })
    assert source_settings.get_enabled_source_ids() == ['dmm']


def test_populated_map_excludes_unavailable_metatube_keeps_builtin(monkeypatch):
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'dmm', 'type': 'builtin', 'enabled': True, 'order': 0, 'manual_only': False},
            {'id': 'mt1', 'type': 'metatube', 'enabled': True, 'order': 1, 'manual_only': False},
        ]
    })
    # map 標記 False / 空 map → metatube 被 gate 排除；builtin 照常保留。
    assert source_settings.get_enabled_source_ids({'mt1': False}) == ['dmm']
    assert source_settings.get_enabled_source_ids({}) == ['dmm']


# ---------------------------------------------------------------------------
# is_uncensored_mode_effective
# ---------------------------------------------------------------------------

def test_uncensored_derive_all_censored_disabled_true():
    config = {
        'sources': [
            {'id': 'dmm', 'type': 'builtin', 'enabled': False},
            {'id': 'javbus', 'type': 'builtin', 'enabled': False},
            {'id': 'jav321', 'type': 'builtin', 'enabled': False},
            {'id': 'javdb', 'type': 'builtin', 'enabled': False},
            {'id': 'fc2', 'type': 'builtin', 'enabled': True},
        ]
    }
    assert source_settings.is_uncensored_mode_effective(config) is True


def test_uncensored_derive_one_censored_enabled_false():
    config = {
        'sources': [
            {'id': 'dmm', 'type': 'builtin', 'enabled': True},
            {'id': 'javbus', 'type': 'builtin', 'enabled': False},
            {'id': 'jav321', 'type': 'builtin', 'enabled': False},
            {'id': 'javdb', 'type': 'builtin', 'enabled': False},
        ]
    }
    assert source_settings.is_uncensored_mode_effective(config) is False


def test_uncensored_empty_sources_uses_legacy():
    # Empty sources list -> fallback to legacy key, NOT derive.
    config = {'sources': [], 'search': {'uncensored_mode_enabled': True}}
    assert source_settings.is_uncensored_mode_effective(config) is True
    config2 = {'sources': [], 'search': {'uncensored_mode_enabled': False}}
    assert source_settings.is_uncensored_mode_effective(config2) is False


# ---------------------------------------------------------------------------
# get_all_source_ids_ordered  (TASK-65a-1)
# ---------------------------------------------------------------------------

def test_all_sources_includes_disabled(monkeypatch):
    """Key difference vs get_enabled_source_ids: disabled entries still returned."""
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'dmm', 'enabled': True, 'order': 0},
            {'id': 'javbus', 'enabled': False, 'order': 1},
        ]
    })
    result = source_settings.get_all_source_ids_ordered()
    assert result == ['dmm', 'javbus']


# ---------------------------------------------------------------------------
# get_switchable_source_ids_ordered  (TASK-85b-D7, present-then-append per Codex P1)
# ---------------------------------------------------------------------------

def test_switchable_full_config_respects_order(monkeypatch):
    """全 8 builtin 在場 + order 打亂 → 完全依 config order（D7 修正核心，無 backfill）。"""
    from core.scrapers.utils import SOURCE_ORDER
    # 反轉 SOURCE_ORDER 當拖曳順序
    reversed_order = list(reversed(SOURCE_ORDER))
    _patch_config(monkeypatch, {
        'sources': [
            {'id': sid, 'type': 'builtin', 'enabled': True, 'order': i}
            for i, sid in enumerate(reversed_order)
        ]
    })
    assert source_settings.get_switchable_source_ids_ordered() == reversed_order


def test_switchable_partial_backfills_to_full(monkeypatch):
    """partial-builtin config（3 row）→ 前 3 依 config order，缺席者依 SOURCE_ORDER append。

    Codex P1 守衛：partial config 下不可丟失缺席 builtin（⟳ 集合不縮）。
    """
    from core.scrapers.utils import SOURCE_ORDER
    _patch_config(monkeypatch, {
        'sources': [
            {'id': 'javbus', 'type': 'builtin', 'enabled': True, 'order': 2},
            {'id': 'dmm', 'type': 'builtin', 'enabled': True, 'order': 0},
            {'id': 'javdb', 'type': 'builtin', 'enabled': True, 'order': 1},
        ]
    })
    result = source_settings.get_switchable_source_ids_ordered()
    # 前 3 = config order；尾巴 = SOURCE_ORDER 中缺席者，原序
    expected_tail = [s for s in SOURCE_ORDER if s not in {'dmm', 'javdb', 'javbus'}]
    assert result == ['dmm', 'javdb', 'javbus'] + expected_tail
    # 全 8 builtin 都在（無丟失）
    assert set(result) == set(SOURCE_ORDER)


