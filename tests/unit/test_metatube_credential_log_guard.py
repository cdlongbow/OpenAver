"""metatube 連線目標不得以原始字串進 log／例外訊息 —— AST 源碼語意守衛。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（憑證渲染單一所有權）

**為什麼需要這支**：Codex PR review 對同一個根因連開三輪——
`validate_metatube_url()` 從不檢查 userinfo，所以 `http://user:pass@host` 通得過
設定；那個值接著從三個不同出口漏出去（① `preview_cover_url` → API 回應 → 瀏覽器
② `GET /api/settings/metatube/status` 的欄位 ③ server log）。三輪的共通形狀不是
「漏想了幾個地方」，而是**每個出口各自決定要記什麼，沒有一個地方能指著說
「渲染規則寫在這裡」**——正是 spec-113 §2.5 定義的病症本身。

第三輪逐點修了 11 處。但「逐點修」不會阻止第 12 處被加回來，所以把它機械化：
`core/metatube/validation.py::redact_metatube_url()` 是渲染規則的**唯一所有者**，
本守衛禁止受監控的檔案把原始 URL 變數餵進 `logger.*()` 或例外建構子。

**掃描範圍刻意窄**（只有實際持有 metatube 連線目標的那幾個檔）：泛掃全庫的
「變數叫 url 就不准進 log」會在無數不相干的地方誤報——那是 CD-113c-14 撤回全庫
domain-literal 帳本時已經走過一次的判準（帳本的代價由每個不相干的 PR 支付）。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# 持有 metatube 連線目標的檔案。新增第三個 consumer 時要一併登記進來——
# 那是 PR 架構審核的責任，本守衛不假裝能自動發現（同 CD-113c-15 第 ④ 條）。
WATCHED_FILES = (
    "core/metatube/client.py",
    "core/metatube/state.py",
    "core/metatube/probe.py",
    "web/routers/settings_metatube.py",
)

# 這些名字承載「可能含 userinfo／query 的原始 URL」。
TAINTED_NAMES = frozenset({"url", "base_url", "_base_url"})

LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

# 例外類別名：訊息會被下游 `logger.exception` / `%s` 印出來，等同 log 表面。
EXC_SUFFIX = "Error"
EXC_NAMES = frozenset({
    "MetatubeError", "MetatubeUnavailable", "MetatubeNotFound",
    "MetatubeAuthError", "MetatubeClientError", "MetatubeProtocolError",
})


def _is_tainted_expr(node: ast.AST) -> bool:
    """這個運算式會不會把原始 URL 的內容帶出來？

    涵蓋三種寫法：裸名 `url`、屬性 `self._base_url`、以及 f-string 內插
    （`f"{self._base_url}{path}"` 這種——第三輪的根因正是這一形狀）。
    **不涵蓋**經過 `redact_metatube_url(...)` 的呼叫結果，那正是允許的出口。
    """
    if isinstance(node, ast.Name):
        return node.id in TAINTED_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in TAINTED_NAMES
    if isinstance(node, ast.JoinedStr):  # f-string
        return any(
            _is_tainted_expr(v.value)
            for v in node.values
            if isinstance(v, ast.FormattedValue)
        )
    if isinstance(node, ast.BinOp):  # "a" + url
        return _is_tainted_expr(node.left) or _is_tainted_expr(node.right)
    return False


def _is_log_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in LOG_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    )


def _is_exception_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Name):
        return False
    return node.func.id in EXC_NAMES or node.func.id.endswith(EXC_SUFFIX)


def _violations(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_log_call(node):
            kind = "logger"
        elif _is_exception_call(node):
            kind = "exception"
        else:
            continue
        args = list(node.args) + [kw.value for kw in node.keywords]
        for arg in args:
            if _is_tainted_expr(arg):
                out.append((node.lineno, kind))
                break
    return out


@pytest.mark.parametrize("rel", WATCHED_FILES)
def test_no_raw_metatube_url_in_logs_or_exception_messages(rel):
    """受監控檔案不得把原始 URL 餵進 `logger.*()` 或例外建構子。

    修法一律是 `redact_metatube_url(...)`（`core/metatube/validation.py`），
    它保留 host[:port]（診斷「打的是哪一台」必要）、丟掉 scheme／userinfo／
    path／query／fragment。
    """
    path = REPO_ROOT / rel
    assert path.exists(), f"受監控檔案不存在（改名？搬移？）：{rel}"
    hits = _violations(path)
    assert hits == [], (
        f"{rel}: 原始 URL 進了 log／例外訊息（{len(hits)} 處，行號 {hits}）。"
        f"改用 core.metatube.validation.redact_metatube_url()。"
    )


def test_watched_files_actually_use_the_redactor():
    """anti-rot：受監控清單若因重構而全數失去 metatube 關聯，這支會指名。

    沒有這一條，上面那組「全部零違規」在檔案被清空或改名後仍然會綠——
    這正是 BE-TEST-05 說的「認不出來的東西被跳過＝假綠」的鏡像形狀。
    """
    users = [
        rel for rel in WATCHED_FILES
        if "redact_metatube_url" in (REPO_ROOT / rel).read_text(encoding="utf-8")
    ]
    assert len(users) >= 3, (
        f"受監控檔案中只有 {users} 用到 redactor——清單可能已與現況脫節，"
        f"請重新確認哪些檔案持有 metatube 連線目標。"
    )


# ---- 可證偽演示（合成 source，永久留檔）----

_RED_SNIPPETS = [
    ('裸名 url 進 logger', 'logger.warning("failed for %s", url)'),
    ('屬性 self._base_url 進 logger', 'logger.debug("GET %s", self._base_url)'),
    ('f-string 內插（第三輪的根因形狀）', 'logger.info(f"probing {base_url}")'),
    ('原始 url 進例外訊息', 'raise MetatubeAuthError(f"auth failed for {url}")'),
    ('字串相加', 'logger.info("at " + url)'),
    ('keyword 引數', 'logger.info("x", extra=url)'),
]

_GREEN_SNIPPETS = [
    ('經過 redactor', 'logger.warning("failed for %s", redact_metatube_url(url))'),
    ('只記型別名', 'logger.info("failed: %s", type(exc).__name__)'),
    ('不相干的變數', 'logger.info("count=%s", total)'),
    ('redacted 變數', 'logger.debug("GET %s", where)'),
    ('非 logger 物件的同名方法', 'tracker.warning(url)'),
]


@pytest.mark.parametrize("label,src", _RED_SNIPPETS, ids=[s[0] for s in _RED_SNIPPETS])
def test_guard_flags_violating_shapes(label, src, tmp_path):
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f), f"{label}：應紅卻沒抓到"


@pytest.mark.parametrize("label,src", _GREEN_SNIPPETS, ids=[s[0] for s in _GREEN_SNIPPETS])
def test_guard_does_not_overreach(label, src, tmp_path):
    """負向那半沒驗，正向就只是「報得夠多」——會在合法寫法上炸開的守衛沒人留得住。"""
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f) == [], f"{label}：誤報"
