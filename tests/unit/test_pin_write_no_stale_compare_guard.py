"""認證寫入路徑不得比對新 PIN —— AST 源碼語意守衛（TASK-114a-T6-b，Opus 裁決二重寫版）。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（語法包含關係，非字串比對）
# 斷言 set_auth / update_access_settings 的函式體內，代表「新 PIN」的名字
# 不得出現在任何 Compare 或 hmac.compare_digest(...) 節點的子樹裡。這是對
# Python 原始碼 AST 語意的檢查，static_guard_lint 的字串指紋規則做不到
# （它比對的是固定字面字串，不是「一個名字有沒有出現在某種語法結構的
# 子樹裡」），故依 CLAUDE.md「Lint 守衛規則」落在 pytest 管轄（PR#128 /
# TASK-114a-T6 Opus 裁決二，pre-merge SA-pre-6 會反查這行）。

spec §2.5 明令禁止「PIN 沒變就沿用舊票」的最佳化——寫入路徑必須無條件
validate → write DB → revoke_all → refresh cache。本守衛鎖住「以後不准
加回」這個最佳化。

## 背景：這是第二代設計，取代已被打穿三輪的 taint-tracking 版本

舊版（見 git 歷史）試著追蹤「哪些運算式代表『目前存的舊 PIN』」（taint
OLD-pin）再看它跟 NEW-pin 是否在同一個 Compare 相遇。連續三輪各自打穿
上一輪機制的認知盲區（module global 讀法沒被列入 OLD 來源、`IfExp` +
`.encode()` 包裝把 taint 追丟）——每次修法都要再改寫同一套追蹤演算法。
`pre-merge.md` 步驟 0.1 的停損條件（①本輪 finding 是上一輪新增機制造成
的 ②修正要再改同一機制）兩者皆成立 → 依規則停止 fix-forward，翻設計
（TASK-114a-T6.md「Opus 裁決二」）。

## 新設計：不追「舊值是什麼」，只問「新 PIN 有沒有出現在比較式裡」

能把一個值送進比較的語法形狀是開放集合（別名、走 global、包一層
`.encode()`／`str()`／`IfExp`／comprehension／walrus……列不完）；但「這次
呼叫傳進來的新 PIN 是誰」是**封閉**的——`set_auth` 就是參數 `pin`，
`update_access_settings` 就是 `request.pin`（`request` 是該函式的參數
名，已開檔核對，不是憑記憶假設）。判準改成純語法包含關係：

  對函式體內（不下潛巢狀 def）每一個 `ast.Compare` 節點、以及每一個
  `hmac.compare_digest(...)` 呼叫節點，`ast.walk` 它的**完整子樹**，只要
  出現代表新 PIN 的名字（裸 `Name(id="pin")` 或 `Attribute(attr="pin",
  value=Name(id="request"))`），該節點就紅。

**不做來源追蹤、不做別名分析、不列舉違規形狀**——不論新 PIN 被
`.encode()`、`str()`、`format()`、`IfExp`、tuple/list 字面值、walrus、
comprehension 包了幾層，它作為一個 `Name`/`Attribute` 節點終究得出現在
比較式的 AST 子樹裡，語法包含關係抓得到，不需要理解「這層包裝在做什
麼」。這正是關上前三輪缺口的原因：前三輪都是因為要判斷「這是不是舊
值」而漏判某種寫法；新設計完全不問「另一邊是什麼」，只問「新 PIN 在
不在這個子樹裡」。

**代價（誠實寫在這裡，不是事後才發現）**：
  1. 判準比舊版寬——`if pin == "":` 這種跟「舊值比對」完全無關的比較也
     會紅。這是刻意的（裁決二原文：「若未來真的需要在這兩支裡比較新
     PIN……那本來就該被攔下來人工看一眼 → 進具名帳本，寫理由。這是特
     性不是缺陷」）。
  2. 掃描範圍不下潛巢狀 def——巢狀 def 內對新 PIN 的比較不在掃描範圍
     （見下方 `test_nested_def_boundary_is_not_scanned` 明文釘住這個邊
     界，不讓它是「悄悄漏掉」而是「白紙黑字的已知邊界」）。
  3. 若新 PIN 先被 rebind 成另一個名字才拿去比（`masked = pin` 之後
     `if masked == x:`），因為不做別名分析，這裡看不到——同樣是換掉一
     套 taint tracking 才會有的舊病，新設計刻意不追這個以避免重蹈覆
     轍。真的出現這種寫法時，人工 review 是最後一道防線。

## 反腐（BE-TEST-05）

若 `WATCHED_FUNCTIONS` 指名的函式在目標檔案裡找不到（被改名／搬走），
一律當作違規回報（不可靜默略過，見
`test_missing_watched_function_is_flagged_not_silently_skipped`）——否則
未來一次重構就能讓這支守衛在不知不覺間永久失效。
"""
from __future__ import annotations

import ast
import pathlib
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 「新 PIN」的語法形狀 —— 每個 watched function 各自一支 matcher
# ---------------------------------------------------------------------------

def _is_new_pin_bare_name(node: ast.AST) -> bool:
    """set_auth(enabled, pin) 的新 PIN：裸名字 `pin`。"""
    return isinstance(node, ast.Name) and node.id == "pin"


def _is_new_pin_request_attr(node: ast.AST) -> bool:
    """update_access_settings(request, raw_request) 的新 PIN：
    `request.pin`（`request` 是該函式的參數名，已開檔核對非憑記憶）。"""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "pin"
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    )


WATCHED_FUNCTIONS = (
    ("core/access_auth.py", "set_auth", _is_new_pin_bare_name),
    ("web/routers/access.py", "update_access_settings", _is_new_pin_request_attr),
)

# 巢狀 def/async def 不下潛——本函式自己的 sink 才算數（見檔頭「代價」段落 2）。
_NON_DESCEND_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _own_nodes(scope: ast.AST):
    """scope 自己函式體內的所有節點——不下潛巢狀 def/async def。
    Lambda／comprehension／walrus 不是 def，照樣下潛，所以
    `any(c == pin for c in xs)` 這種包裝一樣逃不掉。"""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NON_DESCEND_SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _is_compare_digest_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr == "compare_digest"
    if isinstance(fn, ast.Name):
        return fn.id == "compare_digest"
    return False


def _find_module_function(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _scan_function(fn: ast.AST, is_new_pin) -> list[tuple[int, str]]:
    """語法包含關係掃描：每個 Compare／compare_digest 呼叫的完整子樹，
    只要出現新 PIN 的名字就紅。不分比較運算子、不做來源追蹤、不做別名
    分析（Opus 裁決二）。"""
    hits: list[tuple[int, str]] = []
    for node in _own_nodes(fn):
        if isinstance(node, ast.Compare):
            kind = "Compare"
        elif _is_compare_digest_call(node):
            kind = "hmac.compare_digest"
        else:
            continue
        for sub in ast.walk(node):
            if is_new_pin(sub):
                hits.append(
                    (node.lineno, f"新 PIN 出現在 {kind} 節點子樹內（第 {node.lineno} 行）")
                )
                break
    return sorted(hits)


def _violations_for_watched_function(
    path: pathlib.Path, func_name: str, is_new_pin
) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fn = _find_module_function(tree, func_name)
    if fn is None:
        return [
            (
                -1,
                f"anti-rot: 函式 {func_name!r} 在 {path} 找不到（被改名／搬走？）"
                "——不可靜默略過，需要人工回來更新這支守衛。",
            )
        ]
    return _scan_function(fn, is_new_pin)


def _violations_from_snippet(
    src: str, func_name: str, header: str, is_new_pin
) -> list[tuple[int, str]]:
    wrapped = header + "\n" + textwrap.indent(textwrap.dedent(src).strip() + "\n", "    ")
    tree = ast.parse(wrapped)
    fn = _find_module_function(tree, func_name)
    assert fn is not None, f"測試工具本身壞掉：包出來的原始碼找不到 {func_name}"
    return _scan_function(fn, is_new_pin)


def _violations_set_auth(src: str) -> list[tuple[int, str]]:
    return _violations_from_snippet(
        src, "set_auth", "def set_auth(enabled, pin):", _is_new_pin_bare_name
    )


def _violations_update_access_settings(src: str) -> list[tuple[int, str]]:
    return _violations_from_snippet(
        src,
        "update_access_settings",
        "def update_access_settings(request, raw_request):",
        _is_new_pin_request_attr,
    )


# ---------------------------------------------------------------------------
# 正向對照：現行真實產品碼必須零違規
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel,func_name,matcher", WATCHED_FUNCTIONS)
def test_watched_functions_have_no_new_pin_compare(rel, func_name, matcher):
    """今日乾淨的 set_auth / update_access_settings 必須零違規（回歸基準）。"""
    path = REPO_ROOT / rel
    assert path.exists(), f"受監控檔案不存在：{rel}"
    hits = _violations_for_watched_function(path, func_name, matcher)
    assert hits == [], (
        f"{rel}::{func_name} 出現新 PIN 進入比較式（{len(hits)} 處）：{hits}。"
        f"寫入路徑禁止把新 PIN 放進任何 Compare / hmac.compare_digest（spec §2.5）。"
    )


def test_attempt_pin_legitimate_compare_digest_is_out_of_scan_scope():
    """core/access_auth.py::attempt_pin 合法地用 hmac.compare_digest 比對
    候選 PIN 與目前存的 PIN（登入驗證的正常職責）——它不在
    WATCHED_FUNCTIONS 裡，本守衛只鎖 set_auth 的函式體，不掃整檔，
    所以 attempt_pin 的合法比對不會被誤殺。"""
    path = REPO_ROOT / "core/access_auth.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert _find_module_function(tree, "attempt_pin") is not None, (
        "attempt_pin 應該存在——若這個斷言失敗，代表函式被搬走，"
        "本測試存在的前提（『掃描範圍精確排除它』）也隨之失效，需要人工檢查。"
    )
    assert _violations_for_watched_function(path, "set_auth", _is_new_pin_bare_name) == []


# ---------------------------------------------------------------------------
# 反腐：掃描目標函式找不到 → 紅，不可靜默略過（BE-TEST-05）
# ---------------------------------------------------------------------------

def test_missing_watched_function_is_flagged_not_silently_skipped(tmp_path):
    """若受監控函式被改名／搬走，掃描不得悄悄回傳「零違規」——
    那會讓守衛在重構後無聲失效。"""
    stub = tmp_path / "stub_access_auth.py"
    stub.write_text(
        "def set_auth_renamed(enabled, pin):\n"
        "    return None\n",
        encoding="utf-8",
    )
    hits = _violations_for_watched_function(stub, "set_auth", _is_new_pin_bare_name)
    assert hits, "函式找不到時必須回報違規，不可回傳空清單"
    assert hits[0][0] == -1
    assert "anti-rot" in hits[0][1]
    assert "set_auth" in hits[0][1]


# ---------------------------------------------------------------------------
# RED：新 PIN 出現在比較式裡的各種包裝寫法（must go RED）
# ---------------------------------------------------------------------------

_RED_SNIPPETS_SET_AUTH = [
    (
        "1_module_global_boolop_and",
        "if _snapshot is not None and _snapshot.pin == pin:\n    return",
    ),
    (
        "2_local_alias_of_global",
        "_cur = _snapshot\nif _cur.pin == pin:\n    return",
    ),
    (
        "3_direct_snapshot_call",
        "if snapshot().pin == pin:\n    return",
    ),
    (
        "4_subscript_get_auth_settings",
        'if get_auth_settings(True)["pin"] == pin:\n    return',
    ),
    (
        "5_compare_digest_ifexp_encode",
        # 打穿上一版 taint-tracking 的那一條：OLD 值被 IfExp 包，兩邊都
        # 再包一層 .encode()——taint 追蹤失守的地方，語法包含關係不受影響。
        'if hmac.compare_digest((_snapshot.pin if _snapshot else "").encode(), '
        "pin.encode()):\n    return",
    ),
    (
        "6_walrus_wrapped",
        'if (masked := pin) == "0000":\n    return',
    ),
    (
        "7_generator_comprehension",
        'if any(c == pin for c in ("0000", "1111")):\n    return',
    ),
    (
        "8_tuple_literal_and_ne_operator",
        "if (pin,) != (stored_pin,):\n    return",
    ),
]


@pytest.mark.parametrize(
    "label,src", _RED_SNIPPETS_SET_AUTH, ids=[s[0] for s in _RED_SNIPPETS_SET_AUTH]
)
def test_guard_flags_new_pin_in_compare_set_auth(label, src):
    hits = _violations_set_auth(src)
    assert hits, f"{label}：應紅卻沒抓到（語法包含關係掃描失守）\nsrc:\n{src}"


_RED_SNIPPETS_UPDATE_ACCESS_SETTINGS = [
    (
        "9_request_pin_vs_snapshot",
        "if request.pin == snapshot().pin:\n    return",
    ),
    (
        "10_request_pin_str_wrapped_in_container",
        'if str(request.pin) in (str(get_auth_settings(True)["pin"]),):\n    return',
    ),
]


@pytest.mark.parametrize(
    "label,src",
    _RED_SNIPPETS_UPDATE_ACCESS_SETTINGS,
    ids=[s[0] for s in _RED_SNIPPETS_UPDATE_ACCESS_SETTINGS],
)
def test_guard_flags_new_pin_in_compare_update_access_settings(label, src):
    hits = _violations_update_access_settings(src)
    assert hits, f"{label}：應紅卻沒抓到\nsrc:\n{src}"


# ---------------------------------------------------------------------------
# GREEN：不得誤殺的合法寫法（must stay GREEN）
# ---------------------------------------------------------------------------

_GREEN_SNIPPETS_SET_AUTH = [
    (
        "1_format_validation_only_no_compare",
        'if not _is_valid_pin_format(pin):\n'
        '    raise ValueError("pin must be exactly 4 ASCII digits")',
    ),
    (
        "2_ifexp_no_compare_node_at_all",
        'stored_pin = pin if enabled else ""',
    ),
    (
        "3_enabled_field_not_pin",
        "if enabled != snapshot().enabled:\n    pass",
    ),
]


@pytest.mark.parametrize(
    "label,src", _GREEN_SNIPPETS_SET_AUTH, ids=[s[0] for s in _GREEN_SNIPPETS_SET_AUTH]
)
def test_guard_does_not_flag_legitimate_shapes_set_auth(label, src):
    hits = _violations_set_auth(src)
    assert hits == [], f"{label}：誤報 {hits}\nsrc:\n{src}"


def test_nested_def_boundary_is_not_scanned():
    """已知邊界（不是意外漏放）：巢狀 def 內對新 PIN 的比較不在掃描範圍
    ——本守衛只鎖 set_auth／update_access_settings『自己那一層』的函式
    體，比照 T6-a／metatube 守衛同樣『不下潛巢狀 def』的規則。這支測試
    的目的是把邊界釘成白紙黑字，不是主張這裡沒有風險——見檔頭「代價」
    段落 2，真出現這種寫法要靠 review 擋。"""
    src = (
        "def _helper():\n"
        "    return snapshot().pin == pin\n"
        "_helper()\n"
    )
    hits = _violations_set_auth(src)
    assert hits == [], (
        f"巢狀 def 內的比較不應被掃到（設計邊界）：{hits}"
    )


def test_new_pin_passed_as_plain_call_argument_is_not_a_compare():
    """新 PIN 被當一般引數往下傳（set_auth 呼叫的正常職責）不是比較，
    不該紅——例如 update_access_settings 呼叫 set_auth(request.enabled,
    request.pin) 本身不是 Compare／compare_digest 節點。"""
    src = "set_auth(request.enabled, request.pin)"
    hits = _violations_update_access_settings(src)
    assert hits == [], f"單純傳參數不應紅：{hits}"


# ---------------------------------------------------------------------------
# 掃描範圍鎖定
# ---------------------------------------------------------------------------

def test_watched_functions_cover_exactly_the_two_named_functions():
    assert {(rel, name) for rel, name, _ in WATCHED_FUNCTIONS} == {
        ("core/access_auth.py", "set_auth"),
        ("web/routers/access.py", "update_access_settings"),
    }
