"""tests/unit/test_platform_info.py — core.platform_info 單元測試（TASK-159-T3）"""
from core.platform_info import is_synology


def test_is_synology_true_when_env_set(monkeypatch):
    """邊界條件 1: OPENAVER_SYNOLOGY=1 時 is_synology() 回傳 True。"""
    monkeypatch.setenv("OPENAVER_SYNOLOGY", "1")
    assert is_synology() is True


