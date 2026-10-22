"""掃描根目錄的早退訊息要分辨缺失與權限錯誤。"""

import errno
import os

import pytest

from web.routers import scanner


def _winerr(exc, code):
    exc.winerror = code
    return exc


_MISSING = "資料夾不存在"
_UNREACHABLE = "無法存取"
_DENIED = "沒有權限讀取"


@pytest.mark.parametrize(
    ("error", "expected", "other"),
    [
        (_winerr(FileNotFoundError(errno.ENOENT, "x"), 53), _UNREACHABLE, _MISSING),
    ],
)
def test_scan_root_skip_message_for_stat_errors(monkeypatch, error, expected, other):
    def fail_stat(path):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", fail_stat)
        result = scanner._scan_root_skip_message("/root", "/normalized/root")

    assert expected in result
    assert other not in result
    if isinstance(error, PermissionError):
        assert _UNREACHABLE not in result
    else:
        assert "沒有權限" not in result


