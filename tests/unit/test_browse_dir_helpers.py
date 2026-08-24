import os
from web.routers.scanner import (
    _compute_parent,
    _is_windows,
    _list_windows_drives,
    _browse_start_dir,
)
from core.path_utils import to_file_uri


def test_compute_parent_posix(monkeypatch):
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
    assert _compute_parent("") is None
    assert _compute_parent("/") is None
    assert _compute_parent("/home") == "/"
    assert _compute_parent("/home/user/videos") == "/home/user"


def test_compute_parent_windows(monkeypatch):
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
    assert _compute_parent("") is None
    assert _compute_parent("C:\\") == ""
    assert _compute_parent("C:\\Users") == "C:\\"
    assert _compute_parent("C:\\Users\\videos") == "C:\\Users"
    assert _compute_parent("D:\\") == ""


def test_is_windows_default():
    assert _is_windows() == (os.name == "nt")


def test_list_windows_drives_with_listdrives(monkeypatch):
    monkeypatch.setattr(os, "listdrives", lambda: ["C:\\", "D:\\"], raising=False)
    assert _list_windows_drives() == ["C:\\", "D:\\"]


def test_list_windows_drives_fallback(monkeypatch):
    if hasattr(os, "listdrives"):
        monkeypatch.delattr(os, "listdrives")
    monkeypatch.setattr(os.path, "exists", lambda p: p in ("C:\\", "E:\\"))
    assert _list_windows_drives() == ["C:\\", "E:\\"]


def test_start_dir_restores_file_uri_source(tmp_path, monkeypatch):
    """起點決議：來源若是 file:/// URI 格式，必須透過 uri_to_local_fs_path 還原為本機路徑再取 parent。"""
    sub_dir = tmp_path / "library" / "action"
    sub_dir.mkdir(parents=True)
    uri = to_file_uri(str(sub_dir))

    config = {
        "gallery": {
            "directories": [
                {"path": uri}
            ]
        }
    }
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
    start_dir = _browse_start_dir(config)
    assert start_dir == str(tmp_path / "library")


def test_start_dir_fallback_when_source_invalid(tmp_path, monkeypatch):
    """起點決議：若設定中的來源目錄不存在，退回平台根目錄，不應拋錯或回傳無效路徑。"""
    config = {
        "gallery": {
            "directories": [
                {"path": str(tmp_path / "non_existent_folder" / "child")}
            ]
        }
    }
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
    assert _browse_start_dir(config) == "/"

    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
    assert _browse_start_dir(config) == ""


def test_start_dir_empty_config(monkeypatch):
    """起點決議：無設定來源時，POSIX 回傳 '/'，Windows 回傳 ''。"""
    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
    assert _browse_start_dir({}) == "/"

    monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
    assert _browse_start_dir({}) == ""


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
