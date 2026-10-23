import os
from web.routers.scanner import (
    _compute_parent,
    _browse_start_dir,
)


def test_compute_parent_windows(monkeypatch):
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
    assert _compute_parent("") is None
    assert _compute_parent("C:\\") == ""
    assert _compute_parent("C:\\Users") == "C:\\"
    assert _compute_parent("C:\\Users\\videos") == "C:\\Users"
    assert _compute_parent("D:\\") == ""


def test_start_dir_falls_back_when_parent_unlistable(tmp_path, monkeypatch):
    """起點決議：來源上一層存在但列不出來（traverse-only / NAS 權限壞掉）時退回平台根。

    sonnet review 2026-08-24 MAJOR#1：只查 os.path.isdir 不足 —— 目錄存在但 scandir 拋
    OSError 時，第一次開彈窗（不帶 path）會直接吃 403，使用者沒有任何畫面可以導去別處。
    """
    sub_dir = tmp_path / "library" / "action"
    sub_dir.mkdir(parents=True)
    config = {"gallery": {"directories": [{"path": str(sub_dir)}]}}

    original_scandir = os.scandir

    def mock_scandir(p):
        if str(p) == str(tmp_path / "library"):
            raise PermissionError("Permission denied")
        return original_scandir(p)

    monkeypatch.setattr("web.routers.scanner.os.scandir", mock_scandir)
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
    assert _browse_start_dir(config) == "/"

    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
    assert _browse_start_dir(config) == ""
