"""windows/clipboard.py（168b-T4b）：Windows ctypes／macOS pbcopy／其餘平台形狀。"""
import ctypes as _real_ctypes
import sys
from unittest.mock import Mock

import pytest

from windows import clipboard

TEXT = "a😀中"
PAYLOAD = TEXT.encode("utf-16-le") + b"\x00\x00"


class _Api:
    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.return_value


class _Dll:
    pass


class _FakeCtypes:
    def __init__(self, **returns):
        self.c_void_p = _real_ctypes.c_void_p
        self.c_uint = _real_ctypes.c_uint
        self.c_size_t = _real_ctypes.c_size_t
        self.c_int = _real_ctypes.c_int
        self.memmove_calls = []
        k, u = _Dll(), _Dll()
        k.GlobalAlloc = _Api(returns.get("alloc", 0x1000))
        k.GlobalLock = _Api(returns.get("lock", 0x2000))
        k.GlobalUnlock = _Api(1)
        k.GlobalFree = _Api(None)
        u.OpenClipboard = _Api(returns.get("open", 1))
        u.EmptyClipboard = _Api(1)
        u.SetClipboardData = _Api(returns.get("set", 0x1000))
        u.CloseClipboard = _Api(1)
        self.windll = _Dll()
        self.windll.kernel32, self.windll.user32 = k, u

    def memmove(self, dest, src, size):
        self.memmove_calls.append((dest, src, size))


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def install(**returns):
        fake = _FakeCtypes(**returns)
        monkeypatch.setitem(sys.modules, "ctypes", fake)
        return fake
    return install


def test_win_clipboard_non_bmp_size_uses_encoded_length(win):
    fake = win()
    assert clipboard.copy_text(TEXT) is True
    k = fake.windll.kernel32
    assert k.GlobalAlloc.calls == [(0x0002, len(PAYLOAD))]
    assert len(PAYLOAD) != (len(TEXT) + 1) * 2
    assert fake.memmove_calls == [(0x2000, PAYLOAD, len(PAYLOAD))]
    assert fake.windll.user32.SetClipboardData.calls == [(13, 0x1000)]
    assert fake.windll.user32.CloseClipboard.calls == [()]
    assert k.GlobalFree.calls == []


@pytest.mark.parametrize("fail,freed", [
    ({"alloc": None}, False),
    ({"lock": None}, True),
    ({"open": 0}, True),
    ({"set": None}, True),
])
def test_win_clipboard_failures_return_false_and_free(win, fail, freed):
    fake = win(**fail)
    assert clipboard.copy_text(TEXT) is False
    assert bool(fake.windll.kernel32.GlobalFree.calls) is freed


def test_win_clipboard_exception_returns_false(win):
    fake = win()
    fake.windll.kernel32.GlobalAlloc = Mock(side_effect=OSError("boom"))
    assert clipboard.copy_text(TEXT) is False


def test_non_string_returns_false(win):
    win()
    assert clipboard.copy_text(None) is False
    assert clipboard.copy_text(123) is False


def test_macos_uses_pbcopy_with_utf8_bytes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(clipboard.subprocess, "run", run)
    assert clipboard.copy_text(TEXT) is True
    assert run.call_args.args[0] == ["pbcopy"]
    assert run.call_args.kwargs["input"] == TEXT.encode("utf-8")


def test_macos_nonzero_or_exception_is_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(clipboard.subprocess, "run", Mock(return_value=Mock(returncode=1)))
    assert clipboard.copy_text(TEXT) is False
    monkeypatch.setattr(clipboard.subprocess, "run", Mock(side_effect=OSError))
    assert clipboard.copy_text(TEXT) is False


def test_other_platform_is_false_without_subprocess(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    run = Mock()
    monkeypatch.setattr(clipboard.subprocess, "run", run)
    assert clipboard.copy_text(TEXT) is False
    run.assert_not_called()
