"""TASK-120b-T1: check_webview2_installed() 與 pywebview 6.2.1 對帳。

表驅動偵測邏輯 + 源碼對帳守衛（常數層／語意層）+ 豁免 2 前提條款。
不得 import webview.platforms.winforms（Linux 上 import clr 會炸）。
"""
from __future__ import annotations

import re
import sys
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
