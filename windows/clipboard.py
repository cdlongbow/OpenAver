"""剪貼簿寫入（橋接 copy_text 用）。永不拋例外，失敗回 False。

Windows 走 ctypes（CF_UNICODETEXT）；macOS 走 pbcopy；其餘平台不支援。
"""
import subprocess
import sys

from core.logger import get_logger

logger = get_logger(__name__)

_GMEM_MOVEABLE = 0x0002
_CF_UNICODETEXT = 13
_PBCOPY_TIMEOUT = 5


def _declare_win32(ctypes, kernel32, user32):
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int


def _copy_windows(text):
    import ctypes

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    _declare_win32(ctypes, kernel32, user32)

    payload = text.encode("utf-16-le") + b"\x00\x00"
    size = len(payload)
    handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
    if not handle:
        return False
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(locked, payload, size)
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(0):
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def _copy_macos(text):
    result = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                            check=False, timeout=_PBCOPY_TIMEOUT)
    return result.returncode == 0


def copy_text(text):
    """把文字寫進系統剪貼簿；任何失敗（含非字串、不支援平台）回 False。"""
    try:
        if not isinstance(text, str):
            return False
        if sys.platform == "win32":
            return _copy_windows(text)
        if sys.platform == "darwin":
            return _copy_macos(text)
        return False
    except Exception as e:  # noqa: BLE001 — 剪貼簿失敗不得讓橋接呼叫拋出
        logger.warning(f"[clipboard] copy failed ({type(e).__name__})")
        return False
