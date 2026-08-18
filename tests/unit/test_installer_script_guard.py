"""install.ps1 結束路徑守衛（TASK-120b-T3 / CD-120b-10）。

純文字讀 install.ps1，不執行 PowerShell。沿用 _Installs 兩欄位形狀：
recognized = 已辨識的合法結束語句；unparsed = 看起來相關但認不得的原文。
後者非空即 RED。

# [lint-guard: pytest-justified] PowerShell brace-depth 語意守衛
# 需追蹤 depth-0 trap／function 本體、先剔除 Exit-WithPause 再掃裸 exit、
# 以及 fail-closed 清單。static_guard_lint 是字串指紋引擎，表達不了
# 「認不得就進 unparsed」與 brace-depth 0 判定。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALL_PS1 = _REPO_ROOT / "install.ps1"

_ASSIGN_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*\s*=")
_FUNC_START_RE = re.compile(r"^function\b", re.IGNORECASE)
_TRAP_START_RE = re.compile(r"^trap\b", re.IGNORECASE)
_EXIT_WITH_PAUSE_RE = re.compile(r"Exit-WithPause", re.IGNORECASE)
_BARE_EXIT_RE = re.compile(r"(?<!::)\bexit\b", re.IGNORECASE)
_ENV_EXIT_RE = re.compile(r"\[(?:System\.)?Environment\]::Exit", re.IGNORECASE)
_SET_SHOULD_EXIT_RE = re.compile(r"\$host\.SetShouldExit", re.IGNORECASE)
_EXIT_PSSESSION_RE = re.compile(r"\bExit-PSSession\b", re.IGNORECASE)
_STOP_PROCESS_RE = re.compile(r"\bStop-Process\b", re.IGNORECASE)
_PID_RE = re.compile(r"\$PID\b", re.IGNORECASE)
_THROW_RE = re.compile(r"\bthrow\b", re.IGNORECASE)
_RETURN_RE = re.compile(r"\breturn\b", re.IGNORECASE)
_FUNC_EWP_RE = re.compile(r"function\s+Exit-WithPause\b", re.IGNORECASE)
_TRAP_KW_RE = re.compile(r"\btrap\b", re.IGNORECASE)


class _Ends(NamedTuple):
    """recognized：已辨識的合法結束語句原文。
    unparsed：看起來相關但認不得的結束寫法原文。後者非空即 RED。
    """

    recognized: list[str]
    unparsed: list[str]


class _Char(NamedTuple):
    i: int
    line: int
    ch: str
    depth: int
    in_code: bool


def _read_install_ps1() -> str:
    assert _INSTALL_PS1.is_file(), f"install.ps1 不存在：{_INSTALL_PS1}"
    return _INSTALL_PS1.read_text(encoding="utf-8")


def _annotate(text: str) -> list[_Char]:
    """逐字標 brace-depth，並標出字串／註解外的程式碼字元。

    `{`／`}` 都記外層 depth：成對大括號 depth 相同，區塊內語句 depth = 該對 + 1。
    """
    out: list[_Char] = []
    i = 0
    n = len(text)
    line = 1
    depth = 0
    mode = "code"  # code | sq | dq | comment
    while i < n:
        ch = text[i]
        rec_depth = depth
        if mode == "comment":
            in_code = False
            if ch == "\n":
                mode = "code"
                in_code = True
        elif mode == "sq":
            in_code = False
            if ch == "'" and i + 1 < n and text[i + 1] == "'":
                out.append(_Char(i=i, line=line, ch=ch, depth=depth, in_code=False))
                out.append(_Char(i=i + 1, line=line, ch="'", depth=depth, in_code=False))
                i += 2
                continue
            if ch == "'":
                mode = "code"
        elif mode == "dq":
            in_code = False
            if ch == "`" and i + 1 < n:
                nxt = text[i + 1]
                out.append(_Char(i=i, line=line, ch=ch, depth=depth, in_code=False))
                out.append(_Char(i=i + 1, line=line, ch=nxt, depth=depth, in_code=False))
                i += 2
                if nxt == "\n":
                    line += 1
                continue
            if ch == '"':
                mode = "code"
        else:
            if ch == "#":
                in_code = False
                mode = "comment"
            elif ch == "'":
                in_code = False
                mode = "sq"
            elif ch == '"':
                in_code = False
                mode = "dq"
            elif ch == "{":
                in_code = True
                rec_depth = depth
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
                rec_depth = depth
                in_code = True
            else:
                in_code = True
        out.append(_Char(i=i, line=line, ch=ch, depth=rec_depth, in_code=in_code))
        if ch == "\n":
            line += 1
        i += 1
    return out


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _line_text(text: str, line_no: int) -> str:
    rows = _lines(text)
    if 1 <= line_no <= len(rows):
        return rows[line_no - 1]
    return ""


def _code_spans(chars: list[_Char]) -> list[tuple[int, int]]:
    """in_code 連續區段 [start, end)（字元索引）。"""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for c in chars:
        if c.in_code and start is None:
            start = c.i
        elif not c.in_code and start is not None:
            spans.append((start, c.i))
            start = None
    if start is not None:
        spans.append((start, chars[-1].i + 1))
    return spans


def _find_in_code(text: str, chars: list[_Char], regex: re.Pattern[str]) -> list[re.Match[str]]:
    hits: list[re.Match[str]] = []
    for start, end in _code_spans(chars):
        for m in regex.finditer(text, start, end):
            hits.append(m)
    return hits


def _char_map(chars: list[_Char]) -> dict[int, _Char]:
    return {c.i: c for c in chars}


def _find_function_ewp_span(text: str, chars: list[_Char]) -> tuple[int, int] | None:
    """Exit-WithPause 函式本體的 [open_brace, close_brace] 字元索引；找不到回 None。"""
    cmap = _char_map(chars)
    matches = _find_in_code(text, chars, _FUNC_EWP_RE)
    if not matches:
        return None
    m = matches[0]
    ch0 = cmap.get(m.start())
    if ch0 is None or not ch0.in_code or ch0.depth != 0:
        return None
    i = m.end()
    while i < len(text):
        c = cmap.get(i)
        if c and c.in_code and c.ch == "{":
            open_i = i
            target_depth = c.depth  # depth before '{', which then increments
            j = i + 1
            while j < len(text):
                cj = cmap.get(j)
                if cj and cj.in_code and cj.ch == "}" and cj.depth == target_depth:
                    return (open_i, j)
                j += 1
            return None
        i += 1
    return None


def _find_depth0_trap_body(text: str, chars: list[_Char]) -> tuple[int, str] | None:
    """第一個 depth-0 trap 區塊：(起始行號, 區塊內文含 trap 關鍵字)。"""
    cmap = _char_map(chars)
    for m in _find_in_code(text, chars, _TRAP_KW_RE):
        c0 = cmap.get(m.start())
        if c0 is None or not c0.in_code or c0.depth != 0:
            continue
        i = m.end()
        while i < len(text):
            c = cmap.get(i)
            if c is None:
                i += 1
                continue
            if not c.in_code or c.ch.isspace():
                i += 1
                continue
            if c.ch == "{":
                target_depth = c.depth
                j = i + 1
                while j < len(text):
                    cj = cmap.get(j)
                    if cj and cj.in_code and cj.ch == "}" and cj.depth == target_depth:
                        return (c0.line, text[m.start() : j + 1])
                    j += 1
                return None
            break
    return None


def _positions(text: str) -> tuple[int | None, int | None, int | None]:
    """(i) function Exit-WithPause 行 (ii) trap 起始行 (iii) 第一個工作語句行。"""
    chars = _annotate(text)
    cmap = _char_map(chars)
    fn_line: int | None = None
    for m in _find_in_code(text, chars, _FUNC_EWP_RE):
        c0 = cmap.get(m.start())
        if c0 and c0.in_code and c0.depth == 0:
            fn_line = c0.line
            break
    trap = _find_depth0_trap_body(text, chars)
    trap_line = trap[0] if trap else None

    rows = _lines(text)
    work_line: int | None = None
    line_start_depth: dict[int, int] = {}
    for c in chars:
        if c.line not in line_start_depth:
            line_start_depth[c.line] = c.depth
    for line_no, _raw in enumerate(rows, start=1):
        if line_start_depth.get(line_no, 0) != 0:
            continue
        # Comment-only / blank
        code_on_line = [
            c for c in chars if c.line == line_no and c.in_code and not c.ch.isspace()
        ]
        if not code_on_line:
            continue
        # 重組該行 code（去掉字串／註解外的 # 註解）
        line_code = "".join(c.ch for c in chars if c.line == line_no and (c.in_code or c.ch in " \t"))
        # 更準：只取 in_code 字元
        line_code = "".join(c.ch for c in chars if c.line == line_no and c.in_code).strip()
        if not line_code or line_code in ("{", "}"):
            continue
        if _ASSIGN_RE.match(line_code):
            continue
        if _FUNC_START_RE.match(line_code) or _TRAP_START_RE.match(line_code):
            continue
        work_line = line_no
        break
    return fn_line, trap_line, work_line


def _last_depth0_executable(text: str) -> tuple[int, str] | None:
    """從檔尾往前找第一個 brace-depth 0、非空白、非註解、非單獨 {／} 的行。

    界定不出來回 None（呼叫端必須 RED，不可跳過）。
    """
    chars = _annotate(text)
    rows = _lines(text)
    if not rows:
        return None
    line_start_depth: dict[int, int] = {}
    for c in chars:
        if c.line not in line_start_depth:
            line_start_depth[c.line] = c.depth
    for line_no in range(len(rows), 0, -1):
        if line_start_depth.get(line_no, 0) != 0:
            continue
        line_code = "".join(
            c.ch for c in chars if c.line == line_no and c.in_code
        ).strip()
        if not line_code or line_code in ("{", "}"):
            continue
        return line_no, rows[line_no - 1]
    return None


def _scan_exit_paths(text: str) -> _Ends:
    """(b) 先剔除 Exit-WithPause，再在剩餘文字找裸 exit。函式外裸 exit → unparsed。"""
    chars = _annotate(text)
    body = _find_function_ewp_span(text, chars)
    masked = _EXIT_WITH_PAUSE_RE.sub(lambda m: " " * len(m.group(0)), text)
    # 遮蔽後重新標註會把原識別字當空白，depth 不變；裸 exit 掃描用原文 in_code。
    recognized: list[str] = []
    unparsed: list[str] = []
    seen_lines: set[int] = set()

    cmap = _char_map(chars)
    for m in _EXIT_WITH_PAUSE_RE.finditer(text):
        c0 = cmap.get(m.start())
        if c0 is None or not c0.in_code:
            continue
        line = _line_text(text, c0.line).rstrip()
        if c0.line not in seen_lines:
            recognized.append(line)
            seen_lines.add(c0.line)

    for m in _BARE_EXIT_RE.finditer(masked):
        c0 = cmap.get(m.start())
        if c0 is None or not c0.in_code:
            continue
        inside = body is not None and body[0] <= m.start() <= body[1]
        line = _line_text(text, c0.line).rstrip()
        if inside:
            if c0.line not in seen_lines:
                recognized.append(line)
                seen_lines.add(c0.line)
        else:
            unparsed.append(line)
    return _Ends(recognized=recognized, unparsed=unparsed)


def _statement_slice(text: str, start: int) -> str:
    """從 start 起到換行或分號（字串外簡化：取到 EOL）。"""
    end = text.find("\n", start)
    if end < 0:
        end = len(text)
    return text[start:end]


def _scan_fail_closed(text: str) -> _Ends:
    """fail-closed 清單：認不得的結束寫法進 unparsed。"""
    chars = _annotate(text)
    cmap = _char_map(chars)
    recognized: list[str] = []
    unparsed: list[str] = []

    def _add_unparsed(index: int) -> None:
        c0 = cmap.get(index)
        if c0 is None or not c0.in_code:
            return
        line = _line_text(text, c0.line).rstrip()
        if line not in unparsed:
            unparsed.append(line)

    for m in _find_in_code(text, chars, _ENV_EXIT_RE):
        _add_unparsed(m.start())
    for m in _find_in_code(text, chars, _SET_SHOULD_EXIT_RE):
        _add_unparsed(m.start())
    for m in _find_in_code(text, chars, _EXIT_PSSESSION_RE):
        _add_unparsed(m.start())
    for m in _find_in_code(text, chars, _STOP_PROCESS_RE):
        stmt = _statement_slice(text, m.start())
        if _PID_RE.search(stmt):
            _add_unparsed(m.start())
    for m in _find_in_code(text, chars, _THROW_RE):
        c0 = cmap.get(m.start())
        if c0 and c0.in_code and c0.depth == 0:
            _add_unparsed(m.start())
    for m in _find_in_code(text, chars, _RETURN_RE):
        c0 = cmap.get(m.start())
        if c0 and c0.in_code and c0.depth == 0:
            _add_unparsed(m.start())

    return _Ends(recognized=recognized, unparsed=unparsed)


@pytest.fixture(scope="module")
def source() -> str:
    return _read_install_ps1()


def test_a_trap_exists(source: str) -> None:
    """(a) depth-0 的 trap { } 存在，區塊內含 Exit-WithPause。"""
    trap = _find_depth0_trap_body(source, _annotate(source))
    assert trap is not None, "install.ps1 缺少 depth-0 的 trap { ... } 區塊"
    _line, body = trap
    assert _EXIT_WITH_PAUSE_RE.search(body), (
        f"trap 區塊內沒有 Exit-WithPause：{body}"
    )


def test_b_exit_paths_covered(source: str) -> None:
    """(b) 剔除 Exit-WithPause 後，函式本體外不得有裸 exit。"""
    ends = _scan_exit_paths(source)
    assert not ends.unparsed, (
        "install.ps1 有未覆蓋的結束路徑（函式外裸 exit）："
        f"{ends.unparsed}。fail-closed：認不得就不能宣稱結束路徑全覆蓋"
    )


def test_c_position(source: str) -> None:
    """(c) function Exit-WithPause 行 < trap 行 < 第一個工作語句行。"""
    fn_line, trap_line, work_line = _positions(source)
    assert work_line is not None, (
        "界定不出第一個 brace-depth 0 工作語句（非整檔只有賦值／函式／trap）"
    )
    assert fn_line is not None, "找不到 depth-0 的 function Exit-WithPause"
    assert trap_line is not None, "找不到 depth-0 的 trap"
    assert fn_line < trap_line < work_line, (
        f"位置不正確：Exit-WithPause@{fn_line} trap@{trap_line} 工作語句@{work_line}，"
        "必須 Exit-WithPause 定義 < trap < 第一個工作語句"
    )


def test_fail_closed_unrecognized_exit_forms(source: str) -> None:
    """fail-closed 清單任一種出現即 RED 並印原文。"""
    ends = _scan_fail_closed(source)
    assert not ends.unparsed, (
        "install.ps1 有認不得的結束寫法："
        f"{ends.unparsed}。fail-closed：無法辨識就不能宣稱結束路徑全覆蓋"
    )


def test_allows_throw_inside_expand_zip(source: str) -> None:
    """放行 Expand-ZipRobust 函式體內的 throw（:44）。"""
    assert 'throw "ZIP entry 逸出安裝目錄' in source
    ends = _scan_fail_closed(source)
    assert not any("ZIP entry" in u for u in ends.unparsed)


def test_allows_proc_kill(source: str) -> None:
    """放行 Install-WebView2 內的 $proc.Kill()（:119）。"""
    assert "$proc.Kill()" in source
    ends = _scan_fail_closed(source)
    assert not any("Kill" in u for u in ends.unparsed)


def test_allows_continue_in_zip_loop(source: str) -> None:
    """放行 Expand-ZipRobust foreach 內的 continue（:49）。"""
    assert re.search(
        r"IsNullOrEmpty\(\$entry\.Name\).*continue",
        source,
        flags=re.DOTALL,
    )
    ends = _scan_fail_closed(source)
    assert not any(re.search(r"\bcontinue\b", u, re.I) for u in ends.unparsed)


def test_allows_break_in_python_cleanup(source: str) -> None:
    """放行清除舊版 Python 迴圈內的 break（:195）。"""
    assert "Remove-Item $PythonDir" in source
    assert re.search(r"Remove-Item \$PythonDir[^\n]*\n\s*break", source)
    ends = _scan_fail_closed(source)
    assert not any(re.search(r"\bbreak\b", u, re.I) for u in ends.unparsed)


@pytest.mark.parametrize(
    "snippet",
    [
        "[Environment]::Exit(1)",
        "[System.Environment]::Exit(1)",
        "$host.SetShouldExit(1)",
        "Exit-PSSession",
        "Stop-Process -Id $PID",
        'throw "top-level"',
        "return 1",
    ],
)
def test_fail_closed_flags_synthetic(snippet: str) -> None:
    """反向：fail-closed 清單上的寫法必須進 unparsed。"""
    text = snippet + "\n"
    ends = _scan_fail_closed(text)
    assert ends.unparsed, f"應認出可疑結束寫法卻放行：{snippet!r}"
    assert any(snippet.split("\n")[0] in u or snippet in u for u in ends.unparsed)


def test_last_depth0_statement_is_exit_with_pause(source: str) -> None:
    """正常完成路徑的停留不得被移除：最後一個 depth-0 可執行語句必須是 Exit-WithPause 呼叫。"""
    last = _last_depth0_executable(source)
    assert last is not None, (
        "界定不出最後一個 brace-depth 0 可執行語句（檔案空或全是註解）"
    )
    _line_no, raw = last
    line_code = raw.strip()
    assert _EXIT_WITH_PAUSE_RE.search(line_code) and not _FUNC_START_RE.match(
        line_code
    ), (
        "最後一個 depth-0 可執行語句必須是 Exit-WithPause 呼叫，"
        f"實際找到：{raw}"
    )
