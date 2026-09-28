"""掃描根目錄的早退訊息要分辨缺失與權限錯誤。"""

import os

import pytest

from web.routers import scanner


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError("denied"), "沒有權限讀取"),
        (FileNotFoundError("missing"), "資料夾不存在"),
        (NotADirectoryError("not a directory"), "資料夾不存在"),
        (OSError("other failure"), "資料夾不存在"),
    ],
)
def test_scan_root_skip_message_for_stat_errors(monkeypatch, error, expected):
    def fail_stat(path):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", fail_stat)
        result = scanner._scan_root_skip_message("/root", "/normalized/root")

    assert expected in result
    if isinstance(error, PermissionError):
        assert "資料夾不存在" not in result
    else:
        assert "沒有權限" not in result


def test_scan_root_skip_message_allows_accessible_root(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", lambda path: object())
        result = scanner._scan_root_skip_message("/root", "/normalized/root")

    assert result is None
