"""tests/unit/test_platform_info.py — core.platform_info 單元測試（TASK-159-T3）"""
import pytest
from core.platform_info import is_synology, server_kind


def test_is_synology_true_when_env_set(monkeypatch):
    """邊界條件 1: OPENAVER_SYNOLOGY=1 時 is_synology() 回傳 True。"""
    monkeypatch.setenv("OPENAVER_SYNOLOGY", "1")
    assert is_synology() is True


def test_is_synology_false_when_env_unset(monkeypatch):
    """邊界條件 2: 環境變數未設定時 is_synology() 回傳 False。"""
    monkeypatch.delenv("OPENAVER_SYNOLOGY", raising=False)
    assert is_synology() is False


@pytest.mark.parametrize("val", ["0", "true", "", "yes", "2"])
def test_is_synology_false_when_other_values(val, monkeypatch):
    """邊界條件 3: 環境變數設為 '1' 以外的值時 is_synology() 回傳 False（嚴格 == '1'）。"""
    monkeypatch.setenv("OPENAVER_SYNOLOGY", val)
    assert is_synology() is False


@pytest.mark.parametrize(
    "synology,desktop,expected",
    [(True, "windows", "synology"), (False, None, "linux"), (False, "windows", "windows"), (False, "mac", "mac")],
)
def test_server_kind_four_values(monkeypatch, synology, desktop, expected):
    """server_kind：synology 優先於桌面種類，其餘依 desktop_kind，皆無則 linux。"""
    monkeypatch.setattr("core.platform_info.is_synology", lambda: synology)
    monkeypatch.setattr("core.platform_info.desktop_kind", lambda: desktop)
    assert server_kind() == expected
