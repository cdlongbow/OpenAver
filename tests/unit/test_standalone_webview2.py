"""TASK-120b-T1: check_webview2_installed() 與 pywebview 6.2.1 對帳。

表驅動偵測邏輯 + 源碼對帳守衛（常數層／語意層）+ 豁免 2 前提條款。
不得 import webview.platforms.winforms（Linux 上 import clr 會炸）。
"""
from __future__ import annotations

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
        "hkcu_only",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    standalone.WEBVIEW2_MIN_BUILD,
                )
            ]
        ),
        True,
        None,
    ),
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
        "beta_only",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_BETA_GUID"),
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
        "dotnet_unreadable",
        lambda: None,
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
        "pv_86_0_1_0_true",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    "86.0.1.0",
                )
            ]
        ),
        True,
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
    (
        "pv_87_0_0_0_true",
        _ok_release,
        lambda: _pv_map(
            [
                (
                    "HKEY_CURRENT_USER",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    "87.0.0.0",
                )
            ]
        ),
        True,
        None,
    ),
    (
        "key_missing_zero",
        _ok_release,
        lambda: {
            (hive, guid): "0"
            for guid in (
                _guid("WEBVIEW2_RUNTIME_GUID"),
                _guid("WEBVIEW2_BETA_GUID"),
                _guid("WEBVIEW2_DEV_GUID"),
                _guid("WEBVIEW2_CANARY_GUID"),
            )
            for hive in standalone.WEBVIEW2_REGISTRY_HIVES
        },
        False,
        None,
    ),
    (
        "empty_pv_aborts",
        _ok_release,
        lambda: _pv_map(
            [
                ("HKEY_CURRENT_USER", _guid("WEBVIEW2_RUNTIME_GUID"), ""),
                (
                    "HKEY_LOCAL_MACHINE",
                    _guid("WEBVIEW2_RUNTIME_GUID"),
                    standalone.WEBVIEW2_MIN_BUILD,
                ),
            ]
        ),
        False,
        lambda: [("HKEY_CURRENT_USER", _guid("WEBVIEW2_RUNTIME_GUID"))],
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


def test_check_webview2_installed_non_win32_zero_registry_access(monkeypatch):
    """AC-1.5：非 win32 早退，注入點呼叫次數必須為 0。"""
    monkeypatch.setattr(standalone.sys, "platform", "linux")
    pv_reader = _CallRecorder({})
    net_reader = _CallRecorder({(): standalone.DOTNET_RELEASE_MIN})
    monkeypatch.setattr(standalone, "read_webview2_pv", pv_reader)
    monkeypatch.setattr(standalone, "read_dotnet_release", net_reader)

    result = standalone.check_webview2_installed()

    assert result is False
    assert pv_reader.call_count == 0
    assert net_reader.call_count == 0


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
    "case_id,release_value",
    [
        ("dotnet_release_string", "394802"),
        ("dotnet_release_bool", True),
    ],
    ids=["dotnet_release_string", "dotnet_release_bool"],
)
def test_dotnet_release_non_int_means_not_installed(monkeypatch, case_id, release_value):
    """非 int（含 REG_SZ 字串、bool）必須與 pywebview 一樣判未安裝，不得 int() 放寬。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _FakeDotnetWinreg(release_value))
    monkeypatch.setattr(
        standalone, "read_webview2_pv", lambda *_a: standalone.WEBVIEW2_MIN_BUILD
    )

    result = standalone.check_webview2_installed()

    assert result is False, f"{case_id}: non-int Release must be False, got {result!r}"


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
        (
            "hkcu_x86",
            "HKEY_CURRENT_USER",
            "x86",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ),
        (
            "hklm_x86",
            "HKEY_LOCAL_MACHINE",
            "x86",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ),
    ],
    ids=["hkcu_x64", "hklm_x64", "hkcu_x86", "hklm_x86"],
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


def test_winforms_semantics_match_known_good():
    """E8(b) 語意層：_is_new_version / edge_build 原文鎖定 6.2.1。"""
    path = _winforms_path()
    src = path.read_text(encoding="utf-8")
    is_new = _extract_def(src, "_is_new_version")
    edge = _extract_def(src, "edge_build")
    assert is_new, f"_is_new_version not found in {path}:\n{src[:400]}"
    assert edge, f"edge_build not found in {path}:\n{src[:400]}"
    assert _norm(is_new) == _norm(_KNOWN_GOOD_IS_NEW_VERSION), (
        f"_is_new_version drifted:\n--- winforms ---\n{is_new}\n"
        f"--- known-good ---\n{_KNOWN_GOOD_IS_NEW_VERSION}"
    )
    assert _norm(edge) == _norm(_KNOWN_GOOD_EDGE_BUILD), (
        f"edge_build drifted:\n--- winforms ---\n{edge}\n"
        f"--- known-good ---\n{_KNOWN_GOOD_EDGE_BUILD}"
    )
    assert "return '0'" in edge


def test_exemption2_no_webview2_runtime_path_assignment():
    """E8(c) 豁免 2 前提：全庫不得出現 WEBVIEW2_RUNTIME_PATH 賦值（不含本守衛檔）。"""
    hits: list[str] = []
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    files.extend(_SCAN_FILES)
    for path in files:
        if path.resolve() == _THIS_FILE:
            continue
        text = _strip_python_comments(path.read_text(encoding="utf-8", errors="replace"))
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _ASSIGN_RE.search(line):
                rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
                hits.append(f"{rel}:{lineno}:{line.strip()}")
    assert hits == [], (
        "WEBVIEW2_RUNTIME_PATH assignment found; re-check exemption 2:\n"
        + "\n".join(hits)
    )
    # 豁免清單必須以具名常數存在（不是靜默跳過）
    assert "CD-120b-2" in EXEMPTION_1_CD120B2_DOTNET_NAMEERROR
    assert "WEBVIEW2_RUNTIME_PATH" in EXEMPTION_2_WEBVIEW2_RUNTIME_PATH_SHORTCIRCUIT


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


class _FakeCtypes:
    """Lets _win_message_box() run on Linux; MessageBoxW records args.

    Injection shape matches _FakeDotnetWinreg: plant via
    monkeypatch.setitem(sys.modules, "ctypes", ...).
    """

    def __init__(self, return_value):
        self._return_value = return_value
        self.calls: list[tuple] = []
        self.windll = self
        self.user32 = self

    def MessageBoxW(self, hwnd, text, caption, flags):
        self.calls.append((hwnd, text, caption, flags))
        return self._return_value


def _install_fake_ctypes(monkeypatch, return_value):
    fake = _FakeCtypes(return_value)
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    return fake


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


def test_win_message_box_yes_no_flags(monkeypatch):
    """yes_no=True → flags = MB_YESNO|MB_ICONWARNING|MB_SETFOREGROUND|MB_TOPMOST。"""
    fake = _install_fake_ctypes(monkeypatch, return_value=standalone.IDYES)
    result = standalone._win_message_box("text", "caption", yes_no=True)
    assert result is True
    assert fake.calls == [(0, "text", "caption", _FLAGS_YES_NO)]
    flags = fake.calls[0][3]
    assert flags & standalone.MB_YESNO
    assert flags & standalone.MB_ICONWARNING
    assert flags & standalone.MB_SETFOREGROUND
    assert flags & standalone.MB_TOPMOST
    assert flags == (
        standalone.MB_YESNO
        | standalone.MB_ICONWARNING
        | standalone.MB_SETFOREGROUND
        | standalone.MB_TOPMOST
    )


def test_win_message_box_ok_flags(monkeypatch):
    """yes_no=False → flags = MB_OK|MB_ICONERROR|MB_SETFOREGROUND|MB_TOPMOST。"""
    fake = _install_fake_ctypes(monkeypatch, return_value=1)
    result = standalone._win_message_box("text", "caption", yes_no=False)
    assert result is True
    assert fake.calls == [(0, "text", "caption", _FLAGS_OK)]
    flags = fake.calls[0][3]
    assert flags & standalone.MB_ICONERROR
    assert flags & standalone.MB_SETFOREGROUND
    assert flags & standalone.MB_TOPMOST
    assert flags == (
        standalone.MB_OK
        | standalone.MB_ICONERROR
        | standalone.MB_SETFOREGROUND
        | standalone.MB_TOPMOST
    )


def test_win_message_box_idyes_returns_true(monkeypatch):
    """MessageBoxW 回傳 IDYES(6) → True（使用者按是）。"""
    _install_fake_ctypes(monkeypatch, return_value=6)
    assert standalone._win_message_box("t", "c", yes_no=True) is True


def test_win_message_box_idno_returns_false(monkeypatch):
    """MessageBoxW 回傳 IDNO(7) → False（使用者拒絕，不是呼叫失敗）。"""
    _install_fake_ctypes(monkeypatch, return_value=7)
    assert standalone._win_message_box("t", "c", yes_no=True) is False


@pytest.mark.parametrize("yes_no", [True, False], ids=["yes_no", "ok"])
def test_win_message_box_zero_raises(monkeypatch, yes_no):
    """回傳 0＝Win32 呼叫失敗 → 拋例外，不得回 False（Bug C）。"""
    _install_fake_ctypes(monkeypatch, return_value=0)
    with pytest.raises(RuntimeError):
        standalone._win_message_box("t", "c", yes_no=yes_no)


def test_win_message_box_ok_nonzero_returns_true(monkeypatch):
    """yes_no=False 時任何非 0 回傳皆視為成功關閉 → True。"""
    _install_fake_ctypes(monkeypatch, return_value=1)
    assert standalone._win_message_box("t", "c", yes_no=False) is True


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


def test_show_webview2_prompt_display_failure_propagates(monkeypatch):
    """顯示失敗（MessageBoxW=0）必須穿出 show_webview2_prompt()，不得吞成 False。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    _install_fake_ctypes(monkeypatch, return_value=0)
    with pytest.raises(RuntimeError):
        standalone.show_webview2_prompt()


def test_show_webview2_prompt_browser_open_false_still_returns_true(
    monkeypatch, caplog
):
    """使用者按是 + webbrowser.open 回 False → 仍回 True，並另開含網址的 show_error。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    _install_fake_ctypes(monkeypatch, return_value=6)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    error_calls: list[tuple] = []
    monkeypatch.setattr(
        standalone, "show_error", lambda *a, **k: error_calls.append((a, k))
    )
    with caplog.at_level(logging.WARNING):
        result = standalone.show_webview2_prompt()
    assert result is True
    assert len(error_calls) == 1
    assert _WEBVIEW2_DOWNLOAD_URL in error_calls[0][0][1]
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text
    # 回 False 這種失敗形式也要留痕（拋例外那條有自己的 log，兩者都不得靜默）
    assert "瀏覽器未開啟" in caplog.text


def test_show_webview2_prompt_browser_open_exception_still_returns_true(
    monkeypatch, caplog
):
    """使用者按是 + webbrowser.open 拋例外 → 仍回 True；log 與「提示無法顯示」不同字串。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    _install_fake_ctypes(monkeypatch, return_value=6)
    import webbrowser

    def _boom(_url):
        raise OSError("no browser")

    monkeypatch.setattr(webbrowser, "open", _boom)
    error_calls: list[tuple] = []
    monkeypatch.setattr(
        standalone, "show_error", lambda *a, **k: error_calls.append((a, k))
    )
    with caplog.at_level(logging.WARNING):
        result = standalone.show_webview2_prompt()
    assert result is True
    assert len(error_calls) == 1
    assert _WEBVIEW2_DOWNLOAD_URL in error_calls[0][0][1]
    assert _BROWSER_OPEN_FAIL_MARK in caplog.text
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text


@pytest.mark.parametrize(
    "browser_fail",
    ["return_false", "raise"],
    ids=["open_false", "open_raises"],
)
def test_browser_open_failure_not_treated_as_display_failure(
    monkeypatch, caplog, browser_fail
):
    """反向鎖：開瀏覽器失敗不得被判成沒問成；_ensure 走「請安裝後重新啟動」。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "check_webview2_installed", lambda: False)
    _install_fake_ctypes(monkeypatch, return_value=6)
    import webbrowser

    if browser_fail == "return_false":
        monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    else:

        def _boom(_url):
            raise OSError("no browser")

        monkeypatch.setattr(webbrowser, "open", _boom)
    monkeypatch.setattr(standalone, "show_error", lambda *_a, **_k: None)

    prompt_result = standalone.show_webview2_prompt()
    assert prompt_result is True

    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as ei:
            standalone._ensure_webview2_runtime(_standalone_logger())
    assert ei.value.code == 0
    assert _LOG_USER_ACCEPTED in caplog.text
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text
    assert _LOG_USER_DECLINED not in caplog.text


def test_show_webview2_prompt_non_windows_skips_win_message_box(monkeypatch):
    """AC-2.4：非 win32 走 tkinter，_win_message_box／MessageBoxW 呼叫次數為 0；訊息不加網址。"""
    monkeypatch.setattr(standalone.sys, "platform", "linux")
    fake = _install_fake_ctypes(monkeypatch, return_value=6)
    tk_calls = _install_fake_tkinter(monkeypatch, askyesno_result=False)
    box_calls: list = []

    def _unexpected(*_a, **_k):
        box_calls.append(1)
        return False

    monkeypatch.setattr(standalone, "_win_message_box", _unexpected)
    result = standalone.show_webview2_prompt()
    assert result is False
    assert box_calls == []
    assert fake.calls == []
    assert tk_calls["askyesno"], "tkinter messagebox.askyesno must be used"
    _title, message = tk_calls["askyesno"][0]
    assert _WEBVIEW2_DOWNLOAD_URL not in message


def test_show_error_windows_uses_ok_message_box(monkeypatch):
    """AC-2.5：Windows 分支 show_error 走 MessageBoxW(yes_no=False)，呼叫點簽章不變。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    fake = _install_fake_ctypes(monkeypatch, return_value=1)
    standalone.show_error("啟動失敗", "伺服器啟動逾時。", None, None)
    assert fake.calls
    hwnd, text, caption, flags = fake.calls[0]
    assert hwnd == 0
    assert caption == "啟動失敗"
    assert text == "伺服器啟動逾時。"
    assert flags == _FLAGS_OK


def test_show_error_windows_display_failure_is_swallowed(monkeypatch, caplog):
    """show_error Windows 顯示失敗不得往外拋，退回寫 log。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    _install_fake_ctypes(monkeypatch, return_value=0)
    logger = _standalone_logger()
    with caplog.at_level(logging.ERROR, logger="OpenAver.standalone"):
        standalone.show_error("啟動失敗", "伺服器啟動逾時。", None, logger)
    assert "啟動失敗" in caplog.text
    assert "伺服器啟動逾時。" in caplog.text


def test_show_error_non_windows_skips_win_message_box(monkeypatch):
    """非 Windows 的 show_error 逐字走 tkinter，不呼叫 MessageBoxW。"""
    monkeypatch.setattr(standalone.sys, "platform", "linux")
    fake = _install_fake_ctypes(monkeypatch, return_value=1)
    tk_calls = _install_fake_tkinter(monkeypatch)
    standalone.show_error("啟動失敗", "伺服器啟動逾時。")
    assert fake.calls == []
    assert tk_calls["showerror"]


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


def test_ensure_webview2_runtime_user_declined_log(monkeypatch, caplog):
    """使用者按否 → 現行字串「用戶取消安裝，程式結束」＋ exit(0)。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "check_webview2_installed", lambda: False)
    monkeypatch.setattr(standalone, "show_webview2_prompt", lambda: False)
    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as ei:
            standalone._ensure_webview2_runtime(_standalone_logger())
    assert ei.value.code == 0
    assert _LOG_USER_DECLINED in caplog.text
    assert _LOG_USER_ACCEPTED not in caplog.text
    assert _PROMPT_DISPLAY_FAIL_MARK not in caplog.text


def test_ensure_webview2_runtime_display_failure_log_has_no_cancel(
    monkeypatch, caplog
):
    """顯示失敗 → 新 log 不含「取消」；exit(0)；不得走取消／已接受字串。"""
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "check_webview2_installed", lambda: False)
    _install_fake_ctypes(monkeypatch, return_value=0)
    with caplog.at_level(logging.INFO):
        with pytest.raises(SystemExit) as ei:
            standalone._ensure_webview2_runtime(_standalone_logger())
    assert ei.value.code == 0
    fail_msgs = [
        rec.getMessage()
        for rec in caplog.records
        if _PROMPT_DISPLAY_FAIL_MARK in rec.getMessage()
    ]
    assert fail_msgs, caplog.text
    assert all("取消" not in msg for msg in fail_msgs)
    assert _LOG_USER_DECLINED not in caplog.text
    assert _LOG_USER_ACCEPTED not in caplog.text
