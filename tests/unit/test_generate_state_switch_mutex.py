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
    gs._config_save_tokens.clear()
    yield
    gs._active_tokens.clear()
    gs._switch_active = False
    gs._config_save_tokens.clear()


class TestSwitchGenerateMutex:

    def test_switch_refused_when_generate_active(self):
        assert gs.try_mark_generate_active("gen-token") is True
        # generate 在飛 → switch 不能開始（forward guard）
        assert gs.try_begin_switch() == "generate_in_progress"
        assert gs._switch_active is False


    def test_generate_refused_while_switch_active(self):
        assert gs.try_begin_switch() is None
        # 切換窗口中 → 新 generate 掛號被拒（reverse guard，P1 核心）
        assert gs.try_mark_generate_active("gen-token") is False
        assert "gen-token" not in gs._active_tokens
        assert gs.is_generate_in_progress() is False


class TestSwitchConfigSaveMutex:
    """PR #93 P2-e / 五審：整份設定儲存 ↔ switch 真互斥，儲存端用 token-set（非 bool）。"""


    def test_switch_refused_while_config_save_active(self):
        # 儲存持窗口中 → switch 不能開始（否則 purge 與存檔 mutate 交錯 → 舊快照寫回）
        tok = object()
        assert gs.try_begin_config_save(tok) is None
        assert gs.try_begin_switch() == "config_save_in_progress"
        assert gs._switch_active is False  # switch 未佔窗口
        assert tok in gs._config_save_tokens  # 儲存窗口仍握住

    def test_config_save_refused_while_switch_active(self):
        # switch purge 窗口中 → 新整份儲存被拒（反向 guard，P2-e 核心）
        assert gs.try_begin_switch() is None
        tok = object()
        assert gs.try_begin_config_save(tok) == "switch_in_progress"
        assert tok not in gs._config_save_tokens


    # --- PR #93 五審 Codex：重疊存檔下第一個結束不得清掉第二個的窗口 ---


