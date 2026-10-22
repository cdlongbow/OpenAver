"""TASK-120b-T1: check_webview2_installed() 與 pywebview 6.2.1 對帳。

表驅動偵測邏輯 + 源碼對帳守衛（常數層／語意層）+ 豁免 2 前提條款。
不得 import webview.platforms.winforms（Linux 上 import clr 會炸）。
"""
from __future__ import annotations

import ctypes as _real_ctypes
import logging
import re
import sys
import types
from pathlib import Path

import pytest
import webview

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = REPO_ROOT / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

import standalone  # noqa: E402  — sibling import path, same as launcher runtime

# ---------------------------------------------------------------------------
# 具名豁免清單（CD-120b-2 / 豁免 2）— 不是靜默跳過某項比對
# ---------------------------------------------------------------------------
EXEMPTION_1_CD120B2_DOTNET_NAMEERROR = (
    "豁免 1（CD-120b-2）：.NET Release 讀不到時，pywebview 因 finally: "
    "winreg.CloseKey(net_key) 對未賦值名稱取值而拋 NameError 穿出；"
    "我們的讀值注入點契約是回 None，決策邏輯把 None 轉成 False。"
    "理由：那台機器上 pywebview 必定啟動失敗，使用者可見結論相同（起不來），"
    "差別只在我們給看得懂的提示、它給未攔截例外。"
)

EXEMPTION_2_WEBVIEW2_RUNTIME_PATH_SHORTCIRCUIT = (
    "豁免 2（WEBVIEW2_RUNTIME_PATH 短路不移植）：_is_chromium() 開頭 "
    "if settings['WEBVIEW2_RUNTIME_PATH']: return True 不搬。"
    "理由：全庫 core/web/windows/build.py/build_macos.py 沒有該 setting 的賦值，"
    "恆為 falsy，等價性不受影響。前提由本檔賦值掃描守衛鎖住。"
)

# pywebview 6.2.1 winforms.py 已知良好原文（語意層守衛；正規化空白後比對）
_KNOWN_GOOD_IS_NEW_VERSION = """
def _is_new_version(current_version: str, new_version: str) -> bool:
    new_range = new_version.split('.')
    cur_range = current_version.split('.')
    for index, _ in enumerate(new_range):
        if len(cur_range) > index:
            return int(new_range[index]) >= int(cur_range[index])

    return False
"""

_KNOWN_GOOD_EDGE_BUILD = r"""
    def edge_build(key_type, key, description=''):
        try:
            if machine() == 'x86' or key_type == 'HKEY_CURRENT_USER':
                path = rf'Microsoft\EdgeUpdate\Clients\{key}'
            else:
                path = rf'WOW6432Node\Microsoft\EdgeUpdate\Clients\{key}'

            with winreg.OpenKey(getattr(winreg, key_type), rf'SOFTWARE\{path}') as windows_key:
                build, _ = winreg.QueryValueEx(windows_key, 'pv')
                return str(build)

        except Exception:
            pass

        return '0'
"""

_GUID_RE = re.compile(r"'(\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\})'")
_ASSIGN_RE = re.compile(
    r"""(?x)
    (?:
        \bWEBVIEW2_RUNTIME_PATH\b
        |
        \w+(?:\.\w+)*\s*\[\s*['"]WEBVIEW2_RUNTIME_PATH['"]\s*\]
    )
    \s*=
    """
)

_THIS_FILE = Path(__file__).resolve()
_SCAN_ROOTS = (
    REPO_ROOT / "core",
    REPO_ROOT / "web",
    REPO_ROOT / "windows",
    REPO_ROOT / "tests",
)
_SCAN_FILES = (
    REPO_ROOT / "build.py",
    REPO_ROOT / "build_macos.py",
)


class _CallRecorder:
    """Records positional-arg tuples and returns a mapped value.

    BE-TEST-01: do not use a bare MagicMock — its repr can be written as a
    filename at the repo root during mutation self-checks.
    """

    def __init__(self, mapping, default="0"):
        self.calls: list[tuple] = []
        self._mapping = mapping
        self._default = default

    def __call__(self, *args):
        self.calls.append(args)
        if args in self._mapping:
            return self._mapping[args]
        if len(args) == 1 and args[0] in self._mapping:
            return self._mapping[args[0]]
        return self._default

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _winforms_path() -> Path:
    return Path(webview.__file__).resolve().parent / "platforms" / "winforms.py"


def _extract_def(src: str, def_name: str) -> str:
    match = re.search(rf"^([ \t]*)def {re.escape(def_name)}\b.*$", src, re.M)
    if not match:
        return ""
    indent = match.group(1)
    start = match.start()
    lines = src[start:].splitlines(keepends=True)
    collected = [lines[0]]
    for line in lines[1:]:
        if not line.strip():
            collected.append(line)
            continue
        line_indent_len = len(line) - len(line.lstrip(" \t"))
        if line_indent_len <= len(indent):
            break
        collected.append(line)
    return "".join(collected)


def _extract_winforms_constants(src: str) -> tuple[dict, list[str]]:
    """Fail-closed: identified fields + unrecognized-but-relevant snippets."""
    identified: dict = {}
    unrecognized: list[str] = []
    chromium = _extract_def(src, "_is_chromium")
    if not chromium:
        unrecognized.append(src[:400])
        return identified, unrecognized

    guids = _GUID_RE.findall(chromium)
    if len(guids) == 4:
        identified["guids"] = guids
    else:
        unrecognized.append(f"guids={guids!r} snippet={chromium[:400]!r}")

    builds = re.findall(r"'(\d+\.\d+\.\d+\.\d+)'", chromium)
    if len(builds) == 1:
        identified["min_build"] = builds[0]
    else:
        unrecognized.append(f"min_build={builds!r} snippet={chromium[:400]!r}")

    rels = re.findall(r"if version < (\d+)", chromium)
    if len(rels) == 1:
        identified["dotnet_release_min"] = int(rels[0])
    else:
        unrecognized.append(f"dotnet={rels!r} snippet={chromium[:400]!r}")

    hive_m = re.search(
        r"for key_type in \(((?:\s*'HKEY_[A-Z_]+'\s*,?){2})\)",
        chromium,
    )
    if hive_m:
        identified["hives"] = tuple(re.findall(r"'([^']+)'", hive_m.group(1)))
    else:
        unrecognized.append(f"hives snippet={chromium[:400]!r}")

    return identified, unrecognized


def _strip_python_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        in_s = None
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if in_s:
                out.append(ch)
                if ch == "\\" and i + 1 < len(line):
                    out.append(line[i + 1])
                    i += 2
                    continue
                if ch == in_s:
                    in_s = None
                i += 1
                continue
            if ch in ("'", '"'):
                in_s = ch
                out.append(ch)
                i += 1
                continue
            if ch == "#":
                break
            out.append(ch)
            i += 1
        lines.append("".join(out))
    return "\n".join(lines)


def _ok_release():
    return standalone.DOTNET_RELEASE_MIN


def _guid(name: str) -> str:
    return getattr(standalone, name)


def _pv_map(pairs):
    return {(hive, guid): pv for hive, guid, pv in pairs}


# 12-cell table. pv='' is included so it is one of the parametrized cells;
# it additionally asserts the walk aborted (via expect_pv_calls).
_CASES = [
    (
        "hklm_only",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_LOCAL_MACHINE",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    standalone.WEBVIEW2_MIN_BUILD,
                )
            ]
        ),
        True,
        None,
    ),
    (
        "dotnet_too_old",
        lambda: standalone.DOTNET_RELEASE_MIN - 1,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    "87.0.0.0",
                )
            ]
        ),
        False,
        None,
    ),
    (
        "none_found",
        _ok_release,
        lambda: {},
        False,
        None,
    ),
    (
        "pv_86_0_0_0_true",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    "86.0.0.0",
                )
            ]
        ),
        True,
        None,
    ),
    (
        "pv_85_0_999_0_false",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    "85.0.999.0",
                )
            ]
        ),
        False,
        None,
    ),
]


@pytest.mark.parametrize(
    "case_id,release_fn,pv_fn,expected,expect_pv_calls_fn",
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_check_webview2_installed_table(
    monkeypatch, case_id, release_fn, pv_fn, expected, expect_pv_calls_fn
):
    """12 格表驅動：hive／GUID／版本地板／.NET／空字串中止語意。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    pv_reader = _CallRecorder(pv_fn())
    net_reader = _CallRecorder({(): release_fn()})
    monkeypatch.setattr(standalone, "read_webview2_pv", pv_reader)
    monkeypatch.setattr(standalone, "read_dotnet_release", net_reader)

    result = standalone.check_webview2_installed()

    assert result is expected, f"{case_id}: expected {expected!r}, got {result!r}"
    if expect_pv_calls_fn is not None:
        assert pv_reader.calls == expect_pv_calls_fn(), (
            f"{case_id}: walk must abort after empty pv; "
            f"calls={pv_reader.calls!r}"
        )


class _FakeDotnetWinreg:
    """Lets read_dotnet_release() run on Linux; QueryValueEx returns a planted value."""

    HKEY_LOCAL_MACHINE = object()

    def __init__(self, release_value):
        self._release_value = release_value

    def OpenKey(self, hive, path):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def QueryValueEx(self, key, name):
        return (self._release_value, 4)


@pytest.mark.parametrize(
    "case_id,hive_name,machine_name,expected",
    [
        (
            "hkcu_x64",
            "HKEY_CURRENT_USER",
            "AMD64",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ),
        (
            "hklm_x64",
            "HKEY_LOCAL_MACHINE",
            "AMD64",
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ),
    ],
    ids=["hkcu_x64", "hklm_x64", ],
)
def test_webview2_registry_subpath_matches_edge_build(
    case_id, hive_name, machine_name, expected
):
    """x86／WOW6432Node 路徑與 pywebview edge_build() 組法逐字相同（零 mock）。"""
    guid = standalone.WEBVIEW2_RUNTIME_GUID
    got = standalone.webview2_registry_subpath(hive_name, guid, machine_name)
    assert got == expected, f"{case_id}: {got!r} != {expected!r}"


def test_winforms_constants_match_module_constants():
    """E8(a) 常數層：四 GUID／版本地板／.NET 門檻／hive 名與順序對帳。"""
    path = _winforms_path()
    src = path.read_text(encoding="utf-8")
    identified, unrecognized = _extract_winforms_constants(src)
    assert unrecognized == [], (
        f"winforms constants unrecognized (fail-closed): {unrecognized!r}"
    )
    expected_guids = [
        standalone.WEBVIEW2_RUNTIME_GUID,
        standalone.WEBVIEW2_BETA_GUID,
        standalone.WEBVIEW2_DEV_GUID,
        standalone.WEBVIEW2_CANARY_GUID,
    ]
    assert identified["guids"] == expected_guids
    assert identified["min_build"] == standalone.WEBVIEW2_MIN_BUILD
    assert identified["dotnet_release_min"] == standalone.DOTNET_RELEASE_MIN
    assert identified["hives"] == standalone.WEBVIEW2_REGISTRY_HIVES

    impl = (WINDOWS_DIR / "standalone.py").read_text(encoding="utf-8")
    assert "豁免 1" in impl and "CD-120b-2" in impl, EXEMPTION_1_CD120B2_DOTNET_NAMEERROR
    assert "豁免 2" in impl and "WEBVIEW2_RUNTIME_PATH" in impl, (
        EXEMPTION_2_WEBVIEW2_RUNTIME_PATH_SHORTCIRCUIT
    )


# ---------------------------------------------------------------------------
# TASK-120b-T2: MessageBoxW 契約／兩段 try／三態 log
# ---------------------------------------------------------------------------

_WEBVIEW2_DOWNLOAD_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_FLAGS_YES_NO = 0x50034
_FLAGS_OK = 0x50010
_PROMPT_DISPLAY_FAIL_MARK = "提示視窗無法顯示"
_BROWSER_OPEN_FAIL_MARK = "開啟瀏覽器失敗"
_LOG_USER_ACCEPTED = "請安裝 WebView2 後重新啟動"
_LOG_USER_DECLINED = "用戶取消安裝，程式結束"


class _FakeWinApi:
    """One Win32 API: records calls and exposes writable argtypes/restype."""

    def __init__(self, return_value=1):
        self.return_value = return_value
        self.calls: list[tuple] = []
        self.argtypes = None
        self.restype = None
        self.side_effect = None

    def __call__(self, *args):
        self.calls.append(args)
        if self.side_effect is not None:
            raise self.side_effect
        value = self.return_value
        if self.restype is _real_ctypes.c_void_p and value in (0, None):
            return None
        return value


class _FakeDll:
    """Independent kernel32 / user32 stand-in (must not share one object)."""


class _FakeCtypes:
    """Lets _win_message_box() / copy_to_clipboard() run on Linux.

    Injection shape matches _FakeDotnetWinreg: plant via
    monkeypatch.setitem(sys.modules, "ctypes", ...).

    ``fake.calls`` remains MessageBoxW's (hwnd, text, caption, flags) list so
    existing ``_install_fake_ctypes(monkeypatch, return_value=N)`` callers
    keep working. Clipboard APIs live on ``fake.windll.kernel32.*`` /
    ``fake.windll.user32.*`` and keep their own ``.calls``.
    ``memmove`` is fake (never forwards to the real libc memmove).
    """

    def __init__(self, return_value, *, last_error=0):
        self._return_value = return_value
        self._last_error = last_error
        self.calls: list[tuple] = []
        self.memmove_calls: list[tuple] = []

        self.c_void_p = _real_ctypes.c_void_p
        self.c_uint = _real_ctypes.c_uint
        self.c_size_t = _real_ctypes.c_size_t
        self.c_int = _real_ctypes.c_int

        kernel32 = _FakeDll()
        user32 = _FakeDll()
        kernel32.GlobalAlloc = _FakeWinApi(0x1000)
        kernel32.GlobalLock = _FakeWinApi(0x2000)
        kernel32.GlobalUnlock = _FakeWinApi(1)
        kernel32.GlobalFree = _FakeWinApi(None)
        user32.OpenClipboard = _FakeWinApi(1)
        user32.EmptyClipboard = _FakeWinApi(1)
        user32.SetClipboardData = _FakeWinApi(0x1000)
        user32.CloseClipboard = _FakeWinApi(1)

        message_box = _FakeWinApi(return_value)

        def message_box_w(hwnd, text, caption, flags):
            rec = (hwnd, text, caption, flags)
            self.calls.append(rec)
            return message_box(hwnd, text, caption, flags)

        message_box_w.argtypes = None
        message_box_w.restype = None
        message_box_w.calls = message_box.calls
        user32.MessageBoxW = message_box_w

        windll = _FakeDll()
        windll.kernel32 = kernel32
        windll.user32 = user32
        self.windll = windll

    def GetLastError(self):
        return self._last_error

    def memmove(self, dest, src, size):
        self.memmove_calls.append((dest, src, size))
        return dest


def _install_fake_ctypes(monkeypatch, return_value, *, last_error=0):
    fake = _FakeCtypes(return_value, last_error=last_error)
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    return fake


def _install_prompt_spies(monkeypatch):
    """Record _win_message_box / show_error; first box always accepts."""
    box_calls: list[tuple] = []
    error_calls: list[tuple] = []

    def _box(text, caption, *, yes_no):
        box_calls.append((text, caption, yes_no))
        return True

    def _err(*args, **kwargs):
        error_calls.append((args, kwargs))

    monkeypatch.setattr(standalone, "_win_message_box", _box)
    monkeypatch.setattr(standalone, "show_error", _err)
    return box_calls, error_calls


def _second_window_calls(box_calls):
    return [c for c in box_calls if c[2] is False]


class _FakeTk:
    def withdraw(self):
        return None

    def destroy(self):
        return None


def _install_fake_tkinter(monkeypatch, *, askyesno_result=False):
    """Plant tkinter so the non-Windows branch can run headless."""
    calls = {"askyesno": [], "showerror": []}

    msg_mod = types.ModuleType("tkinter.messagebox")

    def askyesno(title, message):
        calls["askyesno"].append((title, message))
        return askyesno_result

    def showerror(title, message):
        calls["showerror"].append((title, message))

    msg_mod.askyesno = askyesno
    msg_mod.showerror = showerror

    tk_mod = types.ModuleType("tkinter")
    tk_mod.Tk = _FakeTk
    tk_mod.messagebox = msg_mod

    monkeypatch.setitem(sys.modules, "tkinter", tk_mod)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", msg_mod)
    return calls


def _standalone_logger():
    return logging.getLogger("OpenAver.standalone")


def test_win_message_box_idyes_returns_true(monkeypatch):
    """MessageBoxW 回傳 IDYES(6) → True（使用者按是）。"""
    _install_fake_ctypes(monkeypatch, return_value=6)
    assert standalone._win_message_box("t", "c", yes_no=True) is True


def test_win_message_box_idno_returns_false(monkeypatch):
    """MessageBoxW 回傳 IDNO(7) → False（使用者拒絕，不是呼叫失敗）。"""
    _install_fake_ctypes(monkeypatch, return_value=7)
    assert standalone._win_message_box("t", "c", yes_no=True) is False


def test_show_webview2_prompt_windows_message_contains_download_url(monkeypatch):
    """AC-2.3：Windows 分支提示文字含完整下載網址字面。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    fake = _install_fake_ctypes(monkeypatch, return_value=7)
    result = standalone.show_webview2_prompt()
    assert result is False
    assert fake.calls, "MessageBoxW must be called on win32"
    _hwnd, text, caption, flags = fake.calls[0]
    assert _WEBVIEW2_DOWNLOAD_URL in text
    assert standalone.WEBVIEW2_DOWNLOAD_URL in text
    assert caption == "需要 WebView2 Runtime"
    assert flags == _FLAGS_YES_NO


def test_show_webview2_prompt_browser_open_false_still_returns_true(
    monkeypatch, caplog
):
    """使用者按是 + webbrowser.open 回 False → 仍回 True，第二視窗直呼 _win_message_box。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    _install_fake_ctypes(monkeypatch, return_value=6)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    box_calls, error_calls = _install_prompt_spies(monkeypatch)
    with caplog.at_level(logging.WARNING):
        result = standalone.show_webview2_prompt()
    assert result is True
    assert error_calls == []
    second = _second_window_calls(box_calls)
    assert len(second) == 1
    text, caption, yes_no = second[0]
    assert yes_no is False
    assert caption == "需要 WebView2 Runtime"
    assert _WEBVIEW2_DOWNLOAD_URL in text
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text
    # 回 False 這種失敗形式也要留痕（拋例外那條有自己的 log，兩者都不得靜默）
    assert "瀏覽器未開啟" in caplog.text


def test_ensure_webview2_runtime_user_accepted_log(monkeypatch, caplog):
    """使用者按是 → 現行字串「請安裝 WebView2 後重新啟動」＋ exit(0)。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "check_webview2_installed", lambda: False)
    monkeypatch.setattr(standalone, "show_webview2_prompt", lambda: True)
    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as ei:
            standalone._ensure_webview2_runtime(_standalone_logger())
    assert ei.value.code == 0
    assert _LOG_USER_ACCEPTED in caplog.text
    assert _LOG_USER_DECLINED not in caplog.text
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text


# ---------------------------------------------------------------------------
# TASK-120d-T1: show_error 還原 / 第二視窗 / 剪貼簿 / 偵測 log / GetLastError
# ---------------------------------------------------------------------------

_CLIP_COPIED_MARK = "網址已複製到剪貼簿"
_CLIP_FAIL_MARK = "無法寫入剪貼簿，請按 Ctrl+C 複製此視窗文字"
_OPENED_TRUE_INFO_MARK = "已請系統開啟下載頁"


def _drive_second_window(monkeypatch, *, clipboard_ok):
    """User clicks Yes, browser open fails; control clipboard via fake ctypes."""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    fake = _install_fake_ctypes(monkeypatch, return_value=6)
    if not clipboard_ok:
        fake.windll.kernel32.GlobalAlloc.return_value = 0
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    box_calls, error_calls = _install_prompt_spies(monkeypatch)
    result = standalone.show_webview2_prompt()
    return result, box_calls, error_calls, fake


def _assert_second_window_common(text, caption, yes_no):
    assert yes_no is False
    assert caption == "需要 WebView2 Runtime"
    assert "？" not in text
    assert "是否" not in text
    assert _WEBVIEW2_DOWNLOAD_URL in text.splitlines()


# ---------------------------------------------------------------------------
# TASK-153b-T4: bootstrap 呼叫順序與失敗可見出口
# ---------------------------------------------------------------------------


def test_main_bootstrap_failure_shows_dialog_and_exits_without_server(monkeypatch):
    """DataLayoutError → show_error(details=None) + sys.exit(1)；port／thread／window 零呼叫。"""
    import threading
    from core.data_layout import DataLayoutError

    calls = {"show_error": [], "port": 0, "server": 0, "window": 0}

    def boom():
        raise DataLayoutError("fixture bootstrap failure")

    def fake_show_error(title, message, details=None, logger=None):
        calls["show_error"].append(
            {"title": title, "message": message, "details": details}
        )

    def fake_find_free_port(*_a, **_k):
        calls["port"] += 1
        return 49152

    def tracking_start(self):
        calls["server"] += 1

    def fake_create_window(*_a, **_k):
        calls["window"] += 1
        return None

    monkeypatch.setattr(standalone, "bootstrap_data_layout", boom)
    monkeypatch.setattr(standalone, "show_error", fake_show_error)
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone, "find_free_port", fake_find_free_port)
    monkeypatch.setattr(standalone, "setup_logging", lambda **k: None)
    # keep real get_logger so logger is assigned before the gate
    monkeypatch.setattr(threading.Thread, "start", tracking_start)
    monkeypatch.setattr(standalone.webview, "create_window", fake_create_window)

    with pytest.raises(SystemExit) as ei:
        standalone.main()

    assert ei.value.code == 1
    assert len(calls["show_error"]) == 1
    err = calls["show_error"][0]
    assert "OpenAver" in err["title"]
    assert "啟動失敗" in err["title"]
    assert "OpenAver" in err["message"]
    assert "啟動失敗" in err["message"]
    assert err["details"] is None
    assert calls["port"] == 0
    assert calls["server"] == 0
    assert calls["window"] == 0


def test_main_bootstrap_failure_win32_uses_native_message_box_not_show_error(monkeypatch):
    """153b CodeRabbit #5：win32＋資料根失敗 → 走 _win_message_box，show_error 零呼叫。

    D1（0.14.0）撤回的是 show_error() 自己的平台分派；這裡是
    _bootstrap_data_layout_or_exit 專屬例外（見 windows/standalone.py 該函式
    docstring），理由是此呼叫點在 find_free_port() 之前、從未佔 port，且資料根
    壞掉是每次啟動都重現的持續性失敗，不跳窗使用者永遠不知道為什麼打不開。
    """
    import threading
    from core.data_layout import DataLayoutError

    calls = {"box": [], "show_error": [], "port": 0, "server": 0, "window": 0}

    def boom():
        raise DataLayoutError("fixture bootstrap failure")

    def fake_win_message_box(text, caption, *, yes_no):
        calls["box"].append({"text": text, "caption": caption, "yes_no": yes_no})
        return True

    def fake_show_error(title, message, details=None, logger=None):
        calls["show_error"].append(
            {"title": title, "message": message, "details": details}
        )

    def fake_find_free_port(*_a, **_k):
        calls["port"] += 1
        return 49152

    def tracking_start(self):
        calls["server"] += 1

    def fake_create_window(*_a, **_k):
        calls["window"] += 1
        return None

    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "bootstrap_data_layout", boom)
    monkeypatch.setattr(standalone, "_win_message_box", fake_win_message_box)
    monkeypatch.setattr(standalone, "show_error", fake_show_error)
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone, "find_free_port", fake_find_free_port)
    monkeypatch.setattr(standalone, "setup_logging", lambda **k: None)
    monkeypatch.setattr(threading.Thread, "start", tracking_start)
    monkeypatch.setattr(standalone.webview, "create_window", fake_create_window)

    with pytest.raises(SystemExit) as ei:
        standalone.main()

    assert ei.value.code == 1
    assert len(calls["box"]) == 1
    assert calls["box"][0]["yes_no"] is False
    assert "OpenAver" in calls["box"][0]["caption"]
    assert "啟動失敗" in calls["box"][0]["caption"]
    assert "OpenAver" in calls["box"][0]["text"]
    assert calls["show_error"] == []
    assert calls["port"] == 0
    assert calls["server"] == 0
    assert calls["window"] == 0


