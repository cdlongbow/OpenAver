"""test_generate_state_switch_mutex.py — 雙向互斥（PR #93 Codex P1）

switch 全窗口 vs generate 掛號的原子互斥：
- try_begin_switch(): generate 在飛 → 'generate_in_progress'；另一 switch 持窗口 →
  'switch_in_progress'（PR #93 P2 序列化）；否則佔窗口回 None
- try_mark_generate_active(): switch 進行中 → False（reverse guard）；否則登記回 True
- end_switch(): 釋放窗口

純記憶體、無 IO。每測前重置 module 全域避免跨測污染。
"""
import pytest

import core.generate_state as gs


@pytest.fixture(autouse=True)
def _reset_state():
    gs._active_tokens.clear()
    gs._switch_active = False
    yield
    gs._active_tokens.clear()
    gs._switch_active = False


class TestSwitchGenerateMutex:
    def test_switch_begins_when_idle(self):
        assert gs.try_begin_switch() is None  # None = 成功佔窗口
        assert gs._switch_active is True
        gs.end_switch()
        assert gs._switch_active is False

    def test_switch_refused_when_generate_active(self):
        assert gs.try_mark_generate_active("gen-token") is True
        # generate 在飛 → switch 不能開始（forward guard）
        assert gs.try_begin_switch() == "generate_in_progress"
        assert gs._switch_active is False

    def test_overlapping_switch_refused_and_first_window_intact(self):
        # PR #93 P2：第二個重疊 switch 必須被拒（否則第一個 end_switch 會在第二個窗口中
        # 清掉 _switch_active，讓 generate 趁隙補回卡）。
        assert gs.try_begin_switch() is None
        assert gs.try_begin_switch() == "switch_in_progress"
        assert gs._switch_active is True  # 第一個窗口仍握住、未被第二個誤設/清掉
        # 第二個被拒期間，generate 仍被第一個窗口擋住
        assert gs.try_mark_generate_active("g") is False
        gs.end_switch()
        assert gs._switch_active is False

    def test_generate_refused_while_switch_active(self):
        assert gs.try_begin_switch() is None
        # 切換窗口中 → 新 generate 掛號被拒（reverse guard，P1 核心）
        assert gs.try_mark_generate_active("gen-token") is False
        assert "gen-token" not in gs._active_tokens
        assert gs.is_generate_in_progress() is False

    def test_generate_allowed_after_switch_ends(self):
        assert gs.try_begin_switch() is None
        assert gs.try_mark_generate_active("t1") is False
        gs.end_switch()
        # 窗口釋放後 generate 可正常掛號
        assert gs.try_mark_generate_active("t1") is True
        assert gs.is_generate_in_progress() is True

    def test_switch_allowed_after_generate_done(self):
        assert gs.try_mark_generate_active("t1") is True
        assert gs.try_begin_switch() == "generate_in_progress"
        gs.mark_generate_done("t1")
        # generate 收尾後 switch 可開始
        assert gs.try_begin_switch() is None

    def test_end_switch_idempotent(self):
        gs.try_begin_switch()
        gs.end_switch()
        gs.end_switch()  # 二次釋放不炸
        assert gs._switch_active is False

    def test_two_generates_coexist_but_block_switch(self):
        assert gs.try_mark_generate_active("a") is True
        assert gs.try_mark_generate_active("b") is True
        assert gs.is_generate_in_progress() is True
        assert gs.try_begin_switch() == "generate_in_progress"
        gs.mark_generate_done("a")
        # 還有一個在飛 → 仍擋 switch
        assert gs.try_begin_switch() == "generate_in_progress"
        gs.mark_generate_done("b")
        assert gs.try_begin_switch() is None
