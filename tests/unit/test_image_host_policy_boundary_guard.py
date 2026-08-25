"""AST 邊界守衛：圖片 host 放行政策單一所有權 ＋ metatube_state 原子讀取（113c-T4）。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（放行政策單一所有權）
# 斷言 (1) core/actress_photo.py 與 web/routers/search.py 不得再出現 domain-shaped
# 字面容器（module-level ＋ 函式體；允許清單僅 REFERER_MAP）；(2) 全庫 core/＋web/
# 讀取 metatube_state 的 .base_url／.is_connected 必須經 connected_base_url()，
# 例外帳本六欄精確對帳。static_guard_lint 只能做字面字串比對，無法表達
# 「domain-shaped 內容判準」或「import binding 解析後的 Attribute Load」語意，故留 pytest。

本守衛只掃**容器字面**。以裸字面比較寫成的 host 政策（`if "x.com" in url:`）
掃不到——`proxy_image()` 現有三個 Referer 判斷就是這個形狀，它們依 CD-113c-10
屬於另一個決策所有權。這是 CD-113c-15 第 ④ 條「第三個 consumer 是 PR 架構審核
問題」的具體實例。

骨架：抄 tests/unit/test_atomic_write_boundary_guard.py（113d）的 module-level 掃描
＋ scope-aware import binding 解析；不抄 113a/113b（只掃具名函式體）。

Tier 1（CD-113c-14）：固定兩檔 TIER1_TARGETS；domain-shaped 形式定義見
_DOMAIN_SHAPED_RE；允許清單唯一一筆 REFERER_MAP（CD-113c-10：不同決策所有權，
不是暫時放行）。_HEADERS／CONTENT_TYPE_MAP 依判準本來不命中，不進清單。

Tier 2（CD-113c-6c）：SCAN_ROOTS=core/web；僅當 receiver 可靜態解析為
core.metatube.state.metatube_state 時禁 .base_url／.is_connected。例外帳本
手寫死五列（每列六欄），不得由掃描結果反推。scraper 一筆 known-debt
（`is_connected`；`base_url` 那筆已於 TASK-130b-T6 還清，改走 probe_snapshot()
單鎖快照，並加了負向鎖防止再被登錄回來）；settings_metatube 兩筆
known-debt(dedup-only)（Opus 裁決 3：命中 race 只會多做一次重連）。

DoD-3 fail-closed（Opus 裁決 1）：module-level 賦值 RHS 為 comprehension／
BinOp∈{Add,Sub,BitOr,BitAnd}／內建集合建構子 Call 時轉紅——不是任何 Call 都紅。
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections import Counter

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Tier 1 constants
# ---------------------------------------------------------------------------

TIER1_TARGETS = [
    REPO_ROOT / "core" / "actress_photo.py",
    REPO_ROOT / "web" / "routers" / "search.py",
]

# plan/card 形式定義：可選 scheme + ≥2 個以點分隔的 label + 可選結尾 /
_DOMAIN_SHAPED_RE = re.compile(
    r"^(?:https?://)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/?$"
)

# 允許清單唯一一筆。note 寫死為不同決策所有權（CD-113c-10），不是暫時放行。
TIER1_ALLOWLIST: dict[str, str] = {
    "REFERER_MAP": (
        "不同決策所有權：它是『這個 source 送哪個 Referer』的唯一所有者，"
        "不是 host 白名單的第二份拷貝（CD-113c-10）"
    ),
}

# ---------------------------------------------------------------------------
# Tier 2 constants
# ---------------------------------------------------------------------------

SCAN_ROOTS = ["core", "web"]
TARGET_MODULE = "core.metatube.state"
TARGET_NAME = "metatube_state"
FORBIDDEN_ATTRS = frozenset({"base_url", "is_connected"})

# 例外帳本六欄（檔案, 函式, receiver binding, attribute, 預期次數, note）。
# 手寫死；不鎖行號（T3a 後 scraper 行號已漂）。不得由掃描結果反推擴增。
# image_host_policy.py 不得列入（它呼叫 connected_base_url()，是 Call 不是屬性讀）。
TIER2_EXEMPTIONS: list[tuple[str, str, str, str, int, str]] = [
    (
        "core/scraper.py",
        "search_jav",
        "metatube_state",
        "is_connected",
        1,
        # TASK-130b-T6：base_url 那一筆 known-debt 已還（search_jav 改用
        # probe_snapshot() 單鎖快照），本列只剩 is_connected 的兩段式讀取。
        "known-debt",  # residual-8/9：兩段式讀取 pre-existing，113c 不修
    ),
    (
        "web/app.py",
        "lifespan",
        "_mt_startup_state",
        "base_url",
        1,
        "",
    ),
    (
        "web/app.py",
        "get_common_context",
        "_mt_state",
        "is_connected",
        1,
        "",
    ),
    (
        "web/routers/settings_metatube.py",
        "connect",
        "state",
        "is_connected",
        1,
        # Opus 裁決 3：與 scraper 同形兩段式讀；race 命中只會多做一次重連，非錯誤結果
        "known-debt(dedup-only)",
    ),
    (
        "web/routers/settings_metatube.py",
        "connect",
        "state",
        "base_url",
        1,
        "known-debt(dedup-only)",
    ),
]

# ---------------------------------------------------------------------------
# Scope types（113d 同構；comprehension 有隱含獨立 scope）
# ---------------------------------------------------------------------------

COMPREHENSION_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPE_TYPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
) + COMPREHENSION_TYPES


# ============================================================
# Tier 1：domain-shaped 字面容器
# ============================================================


def _is_domain_shaped(value: object) -> bool:
    """形式定義：ast.Constant 字串 ① 無空白 ② 匹配 regex ③ **不是純數字 label**。

    第 ③ 條解決 plan 內部的一處衝突：形式定義的 regex 會 match `127.0.0.1`
    （`[A-Za-z0-9-]` 含數字），但同一段的窮舉範例把它列在「不應紅」並註明
    「純數字 label——**刻意排除**，IP 字面另有 `core/metatube/validation.py`
    的 `ipaddress` 判定負責，不屬本政策」。

    衝突時以窮舉範例為準——plan 對那份範例的前言逐字寫著「實作時逐一寫成
    測試，**不得只憑上面的 regex 自行詮釋**」，那句話存在的唯一理由就是
    「regex 不精確、範例才是消歧義的那一方」。

    實務後果：若有人在 Tier 1 兩檔放 `{"127.0.0.1", "::1"}` 這種 loopback 集合
    （`web/app.py:_LOOPBACK_HOSTS` 就是這個形狀，只是不在掃描範圍內），照 regex
    會誤報成 host 白名單復發。
    """
    if not isinstance(value, str):
        return False
    if any(ch.isspace() for ch in value):
        return False
    if _DOMAIN_SHAPED_RE.match(value) is None:
        return False
    # ③ 剝掉 scheme 與結尾斜線後，若每一個 label 都是純數字 → 視為 IP 字面，排除
    bare = value.split("://", 1)[-1].rstrip("/")
    return not all(label.isdigit() for label in bare.split("."))


def _container_elts(node: ast.AST) -> list:
    """回傳容器字面可檢查的元素節點清單（Dict 取 key 與 value 兩側）。"""
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return list(node.elts)
    if isinstance(node, ast.Dict):
        out = []
        for k, v in zip(node.keys, node.values, strict=True):
            if k is not None:  # **spread 的 key 是 None
                out.append(k)
            out.append(v)
        return out
    return []


def _is_container_literal(node: ast.AST) -> bool:
    return isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict))


def _container_has_domain_shaped(node: ast.AST) -> bool:
    """至少一個元素為 domain-shaped Constant 字串即命中。"""
    for elt in _container_elts(node):
        if isinstance(elt, ast.Constant) and _is_domain_shaped(elt.value):
            return True
    return False


def _module_level_container_names(tree: ast.Module) -> dict[int, str]:
    """module-level Assign/AnnAssign 的容器字面 → 賦值目標名字。"""
    names: dict[int, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and _is_container_literal(stmt.value):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    names[id(stmt.value)] = t.id
                    break
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if _is_container_literal(stmt.value) and isinstance(stmt.target, ast.Name):
                names[id(stmt.value)] = stmt.target.id
    return names


def _tier1_hits_from_tree(tree: ast.Module) -> list[dict]:
    """回傳 domain-shaped 容器命中清單（含允許清單過濾前的全部命中）。

    每筆：{lineno, name|None, allowed: bool}。name 僅 module-level 賦值有值。
    """
    name_by_container = _module_level_container_names(tree)
    hits = []
    for node in ast.walk(tree):
        if not _is_container_literal(node):
            continue
        if not _container_has_domain_shaped(node):
            continue
        name = name_by_container.get(id(node))
        allowed = name is not None and name in TIER1_ALLOWLIST
        hits.append(
            {
                "lineno": getattr(node, "lineno", 0),
                "name": name,
                "allowed": allowed,
            }
        )
    return hits


def _tier1_violations(tree: ast.Module) -> list[dict]:
    return [h for h in _tier1_hits_from_tree(tree) if not h["allowed"]]


def _tier1_violations_in_source(source: str) -> list[dict]:
    return _tier1_violations(ast.parse(source))


def _tier1_hits_in_source(source: str) -> list[dict]:
    return _tier1_hits_from_tree(ast.parse(source))


# ============================================================
# DoD-3 fail-closed：module-level 動態建構
# ============================================================

_COLLECTION_CTORS = frozenset({"set", "frozenset", "list", "tuple", "dict"})
_BINOP_TRIGGERS = (ast.Add, ast.Sub, ast.BitOr, ast.BitAnd)


def _is_dynamic_module_level_rhs(rhs: ast.AST) -> bool:
    """無法靜態判定內容形狀的 module-level RHS（Opus 裁決 1 精確邊界）。

    觸發：comprehension／BinOp∈{Add,Sub,BitOr,BitAnd}／內建集合建構子 Call。
    刻意不紅：Div（Path /）、非集合建構子 Call（get_logger／APIRouter／re.compile）。
    """
    if isinstance(rhs, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return True
    if isinstance(rhs, ast.BinOp) and isinstance(rhs.op, _BINOP_TRIGGERS):
        return True
    if isinstance(rhs, ast.Call) and isinstance(rhs.func, ast.Name):
        if rhs.func.id in _COLLECTION_CTORS:
            return True
    # 容器字面**內部**有非 Constant 元素 → 內容靜態判定不出來 → 紅。
    # 這一條補的是 review P2：`_X = {load_host(), "a.com"}` 這種形狀，Tier 1 只看
    # `ast.Constant` 元素、DoD-3 原本只看 RHS 最外層節點型別，**兩層都看不到**
    # 那個 Call 元素——於是一個「有一半內容是動態產生的 host 集合」可以完全靜默
    # 通過。容器字面是本守衛唯一在意的形狀，它的元素判定不出來就必須紅。
    # `*spread` 與 `**spread` 同理（`ast.Starred` / Dict 的 key 為 None）。
    if isinstance(rhs, (ast.Set, ast.List, ast.Tuple)):
        return any(not isinstance(e, ast.Constant) for e in rhs.elts)
    if isinstance(rhs, ast.Dict):
        if any(k is None for k in rhs.keys):  # **spread
            return True
        return any(
            not isinstance(n, ast.Constant)
            for n in list(rhs.keys) + list(rhs.values)
        )
    return False


def _module_level_dynamic_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """回傳 (lineno, name) 清單。"""
    out = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if _is_dynamic_module_level_rhs(stmt.value):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        out.append((stmt.lineno, t.id))
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if _is_dynamic_module_level_rhs(stmt.value) and isinstance(
                stmt.target, ast.Name
            ):
                out.append((stmt.lineno, stmt.target.id))
    return out


def _dynamic_violations_in_source(source: str) -> list[tuple[int, str]]:
    return _module_level_dynamic_violations(ast.parse(source))


# ============================================================
# Tier 2：scope-aware metatube_state binding ＋ Attribute Load 禁令
# （113d _resolve_scope 同構，目標從 Call(os.replace) 換成 Attribute Load）
# ============================================================


def _comprehension_first_iter(node):
    if not node.generators:
        return None
    return node.generators[0].iter


def _enclosing_evaluated_children(node) -> list:
    out = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        out += list(node.decorator_list)
        a = node.args
        out += list(a.defaults)
        out += [d for d in a.kw_defaults if d is not None]
        if node.returns is not None:
            out.append(node.returns)
        for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            if arg.annotation is not None:
                out.append(arg.annotation)
        if a.vararg is not None and a.vararg.annotation is not None:
            out.append(a.vararg.annotation)
        if a.kwarg is not None and a.kwarg.annotation is not None:
            out.append(a.kwarg.annotation)
    elif isinstance(node, ast.Lambda):
        a = node.args
        out += list(a.defaults)
        out += [d for d in a.kw_defaults if d is not None]
    elif isinstance(node, ast.ClassDef):
        out += list(node.decorator_list)
        out += list(node.bases)
        out += [kw.value for kw in node.keywords]
    return out


def _own_direct_nodes(scope) -> list:
    out = []
    if isinstance(scope, COMPREHENSION_TYPES):
        first_iter = _comprehension_first_iter(scope)
        skip = {first_iter} if first_iter is not None else set()
    else:
        skip = set(_enclosing_evaluated_children(scope))

    def rec(node):
        for child in ast.iter_child_nodes(node):
            if child in skip:
                continue
            out.append(child)
            if child is not scope and isinstance(child, SCOPE_TYPES):
                if isinstance(child, COMPREHENSION_TYPES):
                    nested_first_iter = _comprehension_first_iter(child)
                    if nested_first_iter is not None:
                        out.append(nested_first_iter)
                        if not isinstance(nested_first_iter, SCOPE_TYPES):
                            rec(nested_first_iter)
                else:
                    for sub in _enclosing_evaluated_children(child):
                        out.append(sub)
                        if not isinstance(sub, SCOPE_TYPES):
                            rec(sub)
                continue
            rec(child)

    rec(scope)
    return out


def _own_singleton_bindings(own_nodes: list) -> dict:
    """這一層直接 import 的 metatube_state singleton 綁定：local_name → True。

    支援（card 技術要點「設計問題」段落逐條）：
    - `from core.metatube.state import metatube_state`
    - `from core.metatube.state import metatube_state as X`
    - **`import core.metatube.state as X`** → `X.metatube_state.<attr>`（dotted，
      本庫現況未使用，但 card 明文要求支援，同 113d 對 `import os.path` 的處理）
    - **`import core.metatube.state`** → `core.metatube.state.metatube_state.<attr>`

    後兩種的 receiver 是 `ast.Attribute` 而非 `ast.Name`，由 `_module_bindings()`
    ＋ `_receiver_is_singleton()` 兩支處理；本函式只負責前兩種（receiver 是裸名）。
    """
    bindings = {}
    for node in own_nodes:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != TARGET_MODULE:
            continue
        for a in node.names:
            if a.name == TARGET_NAME:
                bindings[a.asname or a.name] = True
    return bindings


def _module_bindings(own_nodes: list) -> dict:
    """`ast.Import` 產生的 module binding：local_name → dotted module path。

    照 Python 真實 binding 語意分兩種（同 113d `_binding_maps` 的 Import 分支）：
    - `import core.metatube.state as X` → `X` 指向完整 dotted module
    - `import core.metatube.state`      → **頂層** `core` 指向 `core`
    """
    out = {}
    for node in own_nodes:
        if not isinstance(node, ast.Import):
            continue
        for a in node.names:
            if a.asname:
                out[a.asname] = a.name
            else:
                top = a.name.split(".", 1)[0]
                out[top] = top
    return out


def _dotted_name(node) -> str | None:
    """把 `a.b.c` 攤平成 `"a.b.c"`；鏈上出現非 Name/Attribute 即回 None。"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _receiver_is_singleton(receiver, name_bind: dict, mod_bind: dict) -> str | None:
    """receiver 是否解析為 `core.metatube.state.metatube_state`；是則回顯示名。

    fail-closed 的方向在這裡是「解析不出來就不報」——因為 Tier 2 的語意是
    「**僅當**可靜態解析為目標 singleton 時才禁」（CD-113c-6c／card DoD-2），
    對不確定的 receiver 泛報會誤傷其他物件的同名屬性，那正是 card 明文禁止的
    「按單獨 attribute 名稱或變數拼字泛掃」。未解析到的形狀由帳本的**次數對帳**
    兜底（少報＝某一格次數不符＝紅）。
    """
    if isinstance(receiver, ast.Name):
        return receiver.id if receiver.id in name_bind else None
    dotted = _dotted_name(receiver)
    if dotted is None:
        return None
    # 形狀必須是 `<module-binding>.metatube_state`
    head, _, last = dotted.rpartition(".")
    if last != TARGET_NAME or not head:
        return None
    if mod_bind.get(head) == TARGET_MODULE:
        return dotted  # `import core.metatube.state as X` → X.metatube_state
    # `import core.metatube.state`（無 as）只綁頂層 `core`，之後整條路徑是
    # `core.metatube.state.metatube_state`——取 head 的最長已綁前綴再接回剩餘段。
    parts = head.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in mod_bind:
            resolved = ".".join([mod_bind[prefix]] + parts[i:])
            return dotted if resolved == TARGET_MODULE else None
    return None


def _directive_names(own_nodes: list) -> tuple:
    global_names = set()
    nonlocal_names = set()
    for n in own_nodes:
        if isinstance(n, ast.Global):
            global_names.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            nonlocal_names.update(n.names)
    return global_names, nonlocal_names


def _comprehension_walrus_targets(comp) -> set:
    out = set()
    stop_types = tuple(t for t in SCOPE_TYPES if t not in COMPREHENSION_TYPES)

    def visit(node):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        if isinstance(node, stop_types):
            children = _enclosing_evaluated_children(node)
        else:
            children = ast.iter_child_nodes(node)
        for child in children:
            visit(child)

    visit(comp)
    return out


def _shadowed_names(scope, own_nodes: list, global_names: set, nonlocal_names: set) -> set:
    names = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            names.add(arg.arg)
        if a.vararg:
            names.add(a.vararg.arg)
        if a.kwarg:
            names.add(a.kwarg.arg)
    for n in own_nodes:
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, COMPREHENSION_TYPES):
            names.update(_comprehension_walrus_targets(n))
    names -= global_names
    names -= nonlocal_names
    return names


def _scope_func_name(scope, enclosing_func: str) -> str:
    """回傳這一層 scope 對應的函式名（供例外帳本對帳；不鎖行號）。"""
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return scope.name
    return enclosing_func


def _resolve_tier2_scope(
    scope,
    inherited: dict,
    root_bind: dict | None = None,
    enclosing_func: str = "<module>",
    inherited_mod: dict | None = None,
) -> list:
    """回傳 (lineno, func_name, receiver, attr) 違規清單。"""
    own_nodes = _own_direct_nodes(scope)
    own_bind = _own_singleton_bindings(own_nodes)
    own_mod = _module_bindings(own_nodes)
    global_names, nonlocal_names = _directive_names(own_nodes)
    shadowed = _shadowed_names(scope, own_nodes, global_names, nonlocal_names)

    if root_bind is None:
        root_bind = own_bind

    bind = dict(inherited)
    bind.update(own_bind)
    # module binding（`import core.metatube.state as X`）同樣沿 scope 繼承——
    # module-level 的 import 在函式體內看得見，這是 Python 語意不是選擇。
    mod_bind = dict(inherited_mod or {})
    mod_bind.update(own_mod)

    for name in shadowed:
        if name not in own_bind:
            bind.pop(name, None)
        if name not in own_mod:
            mod_bind.pop(name, None)

    for name in global_names:
        if name in own_bind:
            continue
        if name in root_bind:
            bind[name] = root_bind[name]
        else:
            bind.pop(name, None)

    # nonlocal：保留 inherited（不另動）

    func_name = _scope_func_name(scope, enclosing_func)
    violations = []
    for node in own_nodes:
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        if node.attr not in FORBIDDEN_ATTRS:
            continue
        receiver = _receiver_is_singleton(node.value, bind, mod_bind)
        if receiver is None:
            continue
        violations.append((node.lineno, func_name, receiver, node.attr))

    for node in own_nodes:
        if isinstance(node, SCOPE_TYPES):
            child_func = _scope_func_name(node, func_name)
            violations += _resolve_tier2_scope(
                node, bind, root_bind, child_func, mod_bind
            )

    return violations


def _tier2_violations_from_tree(tree: ast.Module) -> list:
    return _resolve_tier2_scope(tree, {})


def _tier2_violations_in_source(source: str) -> list:
    return _tier2_violations_from_tree(ast.parse(source))


def _tier2_find_violations(py_file: pathlib.Path) -> list:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    return _tier2_violations_from_tree(tree)


# ============================================================
# 掃描目標
# ============================================================


def _tier2_scan_targets() -> list:
    files = []
    for root_name in SCAN_ROOTS:
        for py_file in sorted((REPO_ROOT / root_name).rglob("*.py")):
            files.append(py_file)
    return files


TIER2_SCAN_TARGETS = _tier2_scan_targets()


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


# ============================================================
# 反假綠：掃描目標非空
# ============================================================


def test_tier1_targets_exist():
    """Tier 1 固定兩檔都必須存在——清單打錯字不得靜默全綠。"""
    for path in TIER1_TARGETS:
        assert path.is_file(), f"Tier 1 目標不存在: {path}"


def test_tier2_scan_targets_is_nonempty_and_each_root_contributes():
    assert len(TIER2_SCAN_TARGETS) >= 50, (
        f"TIER2_SCAN_TARGETS 數量異常低（{len(TIER2_SCAN_TARGETS)}），"
        f"SCAN_ROOTS 或 rglob 可能出錯"
    )
    contributed = {p.relative_to(REPO_ROOT).parts[0] for p in TIER2_SCAN_TARGETS}
    for root_name in SCAN_ROOTS:
        assert root_name in contributed, (
            f"TIER2_SCAN_TARGETS 裡沒有任何來自 {root_name}/ 的檔案"
        )


# ============================================================
# DoD-1：Tier 1 主斷言（parametrize 兩檔）
# ============================================================


@pytest.mark.parametrize(
    "py_file",
    TIER1_TARGETS,
    ids=[_rel(p) for p in TIER1_TARGETS],
)
def test_no_domain_shaped_literal_container_outside_allowlist(py_file):
    """Tier 1：兩檔 module-level ＋ 函式體不得有未允許的 domain-shaped 字面容器。

    逐處對帳次數（violations 清單必須為空），不是存在性檢查。
    """
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    violations = _tier1_violations(tree)
    assert violations == [], (
        f"{_rel(py_file)}: domain-shaped 字面容器違規 "
        f"（{len(violations)} 處）: {violations}；"
        f"host 政策必須走 core.image_host_policy，不得第二份字面清單"
    )


class TestTier1WhitelistAntiRot:
    """允許清單裡的名字若已不存在 → 失敗並指名（不得靜默通過）。"""

    def test_referer_map_exists_as_module_level_domain_shaped_container(self):
        path = REPO_ROOT / "core" / "actress_photo.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _tier1_hits_from_tree(tree)
        allowed_names = {h["name"] for h in hits if h["allowed"]}
        for name in TIER1_ALLOWLIST:
            assert name in allowed_names, (
                f"允許清單名字 {name!r} 在 core/actress_photo.py 找不到"
                f"對應的 domain-shaped 字面容器（改名？刪除？）——"
                f"anti-rot 失敗：{TIER1_ALLOWLIST[name]}"
            )

    def test_allowlist_is_exactly_referer_map(self):
        """清單不得膨脹：唯一一筆 REFERER_MAP；_HEADERS／CONTENT_TYPE_MAP 不進清單。"""
        assert set(TIER1_ALLOWLIST) == {"REFERER_MAP"}
        assert "不同決策所有權" in TIER1_ALLOWLIST["REFERER_MAP"]
        assert "CD-113c-10" in TIER1_ALLOWLIST["REFERER_MAP"]


# ============================================================
# DoD-2：Tier 2 主斷言 ＋ 例外帳本對帳
# ============================================================


def _collect_all_tier2_hits() -> list[tuple[str, str, str, str]]:
    """全庫 (rel_path, func, receiver, attr) 清單（逐次出現，可重複）。"""
    hits = []
    for py_file in TIER2_SCAN_TARGETS:
        rel = _rel(py_file)
        for _lineno, func, receiver, attr in _tier2_find_violations(py_file):
            hits.append((rel, func, receiver, attr))
    return hits


def test_no_bare_base_url_or_is_connected_outside_exemption_table():
    """Tier 2：所有 metatube_state .base_url／.is_connected Load 必須在例外帳本內，
    且次數恰好等於表定值。未登錄存取／次數改變 → RED。"""
    hits = _collect_all_tier2_hits()
    actual = Counter(hits)
    expected = Counter()
    for path, func, receiver, attr, count, _note in TIER2_EXEMPTIONS:
        expected[(path, func, receiver, attr)] += count

    # 未登錄的存取
    unregistered = {k: v for k, v in actual.items() if k not in expected}
    assert not unregistered, (
        f"未登錄的 metatube_state .base_url／.is_connected 存取: {unregistered}；"
        f"必須改走 connected_base_url()，或（僅 known-debt）更新例外帳本"
    )

    # 次數不符（含表有碼無、碼多於表）
    mismatches = []
    for key, exp_count in expected.items():
        act_count = actual.get(key, 0)
        if act_count != exp_count:
            mismatches.append((key, exp_count, act_count))
    assert not mismatches, (
        f"例外帳本次數不符 (key, expected, actual): {mismatches}"
    )


class TestTier2ExemptionAntiRot:
    """例外表每一列的錨點必須仍找得到；消失 → 紅並指名。"""

    @pytest.mark.parametrize(
        "path,func,receiver,attr,count,note",
        TIER2_EXEMPTIONS,
        ids=[
            f"{p}:{f}.{r}.{a}"
            for p, f, r, a, _c, _n in TIER2_EXEMPTIONS
        ],
    )
    def test_exemption_anchor_present(self, path, func, receiver, attr, count, note):
        py_file = REPO_ROOT / path
        assert py_file.is_file(), f"例外帳本檔案不存在: {path}"
        hits = [
            h
            for h in _tier2_find_violations(py_file)
            if h[1] == func and h[2] == receiver and h[3] == attr
        ]
        assert len(hits) == count, (
            f"例外錨點 {path}:{func} {receiver}.{attr} "
            f"預期 {count} 次，實際 {len(hits)}"
            f"{f' [{note}]' if note else ''}——"
            f"函式改名／讀取被移除或次數改變時必須更新帳本"
        )

    def test_exemption_table_has_exactly_five_rows(self):
        """TASK-130b-T6：原本 6 列，`core/scraper.py:search_jav` 的 base_url
        那一筆 known-debt 已還（改走 probe_snapshot() 單鎖快照）→ 5 列。
        **這是收緊，不是放寬**：少一個被豁免的 bare access。"""
        assert len(TIER2_EXEMPTIONS) == 5

    def test_image_host_policy_not_in_exemptions(self):
        """registry 不得列入例外（它呼叫 connected_base_url()，本來就不該命中）。"""
        for path, *_ in TIER2_EXEMPTIONS:
            assert path != "core/image_host_policy.py"

    def test_known_debt_notes(self):
        notes = {
            (p, f, r, a): n for p, f, r, a, _c, n in TIER2_EXEMPTIONS
        }
        assert notes[("core/scraper.py", "search_jav", "metatube_state", "is_connected")] == (
            "known-debt"
        )
        # base_url 那一筆已於 TASK-130b-T6 還清，不再登錄
        assert ("core/scraper.py", "search_jav", "metatube_state", "base_url") not in notes
        assert notes[
            ("web/routers/settings_metatube.py", "connect", "state", "is_connected")
        ] == "known-debt(dedup-only)"
        assert notes[
            ("web/routers/settings_metatube.py", "connect", "state", "base_url")
        ] == "known-debt(dedup-only)"
        assert notes[("web/app.py", "lifespan", "_mt_startup_state", "base_url")] == ""
        assert notes[
            ("web/app.py", "get_common_context", "_mt_state", "is_connected")
        ] == ""


def test_exemption_table_count_mismatch_is_rejected():
    """DoD-5：模擬有人誤收緊帳本（預期次數改小）→ 必須轉紅。

    不改產品碼；直接對 actual counter 與收緊後 expected 比對。
    """
    hits = _collect_all_tier2_hits()
    actual = Counter(hits)
    # 把 scraper.is_connected 的預期從 1 收成 0
    tightened = Counter()
    for path, func, receiver, attr, count, _note in TIER2_EXEMPTIONS:
        if (
            path == "core/scraper.py"
            and func == "search_jav"
            and receiver == "metatube_state"
            and attr == "is_connected"
        ):
            count = 0
        tightened[(path, func, receiver, attr)] += count

    key = ("core/scraper.py", "search_jav", "metatube_state", "is_connected")
    assert actual[key] == 1
    assert tightened[key] == 0
    assert actual[key] != tightened[key], "收緊後應與實際次數不符"


# ============================================================
# DoD-3：fail-closed 主斷言（兩檔現況零命中）
# ============================================================


@pytest.mark.parametrize(
    "py_file",
    TIER1_TARGETS,
    ids=[_rel(p) for p in TIER1_TARGETS],
)
def test_dynamic_construction_assigned_to_module_level_name_is_rejected(py_file):
    """DoD-3：無法靜態判定的 module-level 賦值現況必須為 0（上線即綠）。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    violations = _module_level_dynamic_violations(tree)
    assert violations == [], (
        f"{_rel(py_file)}: module-level 動態建構違規: {violations}"
    )


# ============================================================
# domain-shaped 判準邊界（plan 窮舉，寫成測試）
# ============================================================

_SHOULD_MATCH = [
    "javbus.com",
    "pics.dmm.co.jp",
    "https://www.graphis.ne.jp/",
    "1pondo.tv",
    "cf.javfree.me",
]

_SHOULD_NOT_MATCH = [
    "image/jpeg",  # 無點分 label（/ 不是 .）
    ".jpg",  # 首字元為點，無左 label
    "Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit/537.36",  # 含空白
    "依優先順序自動選擇",  # 無點
    "metatube:FANZA",  # 無點
    "127.0.0.1",  # 純數字 label：plan 窮舉範例明列「刻意排除」（見 _is_domain_shaped ③）
    "192.168.1.1",
    "https://10.0.0.1/",
]


@pytest.mark.parametrize("s", _SHOULD_MATCH, ids=_SHOULD_MATCH)
def test_domain_shaped_positive(s):
    assert _is_domain_shaped(s) is True


@pytest.mark.parametrize("s", _SHOULD_NOT_MATCH, ids=[repr(x) for x in _SHOULD_NOT_MATCH])
def test_domain_shaped_negative(s):
    assert _is_domain_shaped(s) is False


def test_domain_shaped_excludes_ip_literals_but_not_numeric_prefixed_domains():
    """IP 字面排除**不得**擴大成「開頭是數字就放過」。

    `1pondo.tv` 與 `10musume.com` 都以數字開頭、且是真的 host（registry 裡就有
    這兩筆）。排除條件必須是「**每一個** label 都是純數字」，不是「第一個 label
    是數字」——後者會讓這兩筆從此掃不到，等於在守衛上開一個以數字命名的後門。
    """
    assert _is_domain_shaped("127.0.0.1") is False
    assert _is_domain_shaped("1pondo.tv") is True
    assert _is_domain_shaped("10musume.com") is True


# ============================================================
# 可證偽矩陣（合成 source，永久留檔；DoD-4）
# ============================================================

# Tier 1 RED
TIER1_RED_CASES = [
    # ① module-level 新增 domain-shaped set——擴大到 module-level 的直接證明
    (
        1,
        "_ALLOWED_X = {'evil.example'}\n",
        "module-level domain-shaped set 必須紅（只掃函式體會全綠）",
    ),
    # ② 同一函式體內兩個違規容器
    (
        2,
        "def f():\n    a = {'evil.example'}\n    b = {'other.evil'}\n    return a, b\n",
        "函式體內兩個違規容器都要抓到",
    ),
    # list / tuple / dict value / dict key
    (3, "X = ['javbus.com']\n", "list 字面"),
    (4, "X = ('javbus.com',)\n", "tuple 字面"),
    (5, "X = {'h': 'pics.dmm.co.jp'}\n", "dict value"),
    (6, "X = {'cf.javfree.me': True}\n", "dict key"),
    (7, "X = {'https://www.graphis.ne.jp/'}\n", "scheme+host+/"),
    (8, "X = {'1pondo.tv'}\n", "root domain"),
]

TIER1_GREEN_CASES = [
    # REFERER_MAP 形狀允許
    (
        10,
        "REFERER_MAP = {'graphis': 'https://www.graphis.ne.jp/'}\n",
        "允許清單 REFERER_MAP",
    ),
    # 非 domain-shaped
    (11, "CONTENT_TYPE_MAP = {'image/jpeg': '.jpg'}\n", "MIME／副檔名不命中"),
    (
        12,
        "_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64)'}\n",
        "含空白 UA 不命中",
    ),
    # 裸字面比較——結構上不掃 Compare（Opus 裁決 2）
    (
        13,
        'def proxy_image(url):\n    if "javbus.com" in url:\n        return 1\n',
        "裸字面比較不進容器掃描",
    ),
    # 非容器
    (14, 'HOST = "javbus.com"\n', "單一 Constant 賦值不是容器"),
    (15, "SAFE = re.compile(r'^[A-Za-z0-9._~-]+$')\n", "re.compile 引數不是容器"),
]

# Tier 2 RED
TIER2_RED_CASES = [
    # ③ registry 兩段式讀取形狀
    (
        20,
        "from core.metatube.state import metatube_state\n"
        "def proxy_dynamic_hosts():\n"
        "    if metatube_state.is_connected:\n"
        "        return metatube_state.base_url\n"
        "    return None\n",
        "兩段式 is_connected + base_url 必須紅",
    ),
    # 四種 alias 寫法
    (
        21,
        "from core.metatube.state import metatube_state as state\n"
        "def f():\n    return state.base_url\n",
        "as state alias",
    ),
    (
        22,
        "from core.metatube.state import metatube_state as _mt_state\n"
        "def f():\n    return _mt_state.is_connected\n",
        "as _mt_state alias",
    ),
    (
        23,
        "from core.metatube.state import metatube_state as _mt_startup_state\n"
        "def f():\n    return _mt_startup_state.base_url\n",
        "as _mt_startup_state alias",
    ),
    # 函式內 import
    (
        24,
        "def f():\n"
        "    from core.metatube.state import metatube_state as _mt_state\n"
        "    return _mt_state.is_connected\n",
        "函式內 import binding",
    ),
]

TIER2_GREEN_CASES = [
    # connected_base_url() 是 Call，不是屬性讀
    (
        30,
        "from core.metatube.state import metatube_state\n"
        "def proxy_dynamic_hosts():\n"
        "    return metatube_state.connected_base_url()\n",
        "connected_base_url() Call 不命中",
    ),
    # 其他物件的同名屬性
    (
        31,
        "def f(request):\n    return request.base_url\n",
        "request.base_url 不得誤傷",
    ),
    # self._base_url（T3b shim）——receiver 非 import binding；attr 名也不同
    (
        32,
        "class _MetatubeShim:\n"
        "    def __init__(self, base_url):\n"
        "        self._base_url = base_url\n"
        "    def map(self, info):\n"
        "        return self._base_url\n",
        "self._base_url 不命中",
    ),
    # Store 寫入不掃
    (
        33,
        "from core.metatube.state import metatube_state\n"
        "def f(v):\n"
        "    metatube_state.base_url = v\n",
        "Store 不掃（僅 Load）",
    ),
    # 參數遮蔽
    (
        34,
        "from core.metatube.state import metatube_state\n"
        "def f(metatube_state):\n"
        "    return metatube_state.base_url\n",
        "參數遮蔽 import binding",
    ),
    # 其他屬性
    (
        35,
        "from core.metatube.state import metatube_state\n"
        "def f():\n"
        "    return metatube_state.token\n",
        "token 不在禁令",
    ),
]

# DoD-3 RED / GREEN
DOD3_RED_CASES = [
    (40, "_X = set(_load_hosts())\n", "集合建構子 set(...)"),
    (41, "_X = list(hosts)\n", "list(...)"),
    (42, "_X = frozenset(hosts)\n", "frozenset(...)"),
    (43, "_X = dict(pairs)\n", "dict(...)"),
    (44, "_X = tuple(hosts)\n", "tuple(...)"),
    (45, "_X = A | B\n", "BitOr 聯集"),
    (46, "_X = A & B\n", "BitAnd 交集"),
    (47, "_X = A + B\n", "Add 串接"),
    (48, "_X = A - B\n", "Sub 差集"),
    (49, "_X = {h for h in hosts}\n", "SetComp"),
    (50, "_X = [h for h in hosts]\n", "ListComp"),
    (51, "_X = {k: v for k, v in pairs}\n", "DictComp"),
]

DOD3_GREEN_CASES = [
    # 裁決 1 反向：非集合建構子 Call 必須仍綠
    (60, "_Y = SomeClass(hosts)\n", "非集合建構子 Call 不紅"),
    (61, "logger = get_logger(__name__)\n", "get_logger"),
    (62, "router = APIRouter()\n", "APIRouter"),
    (63, "SAFE = re.compile(r'x')\n", "re.compile"),
    # Div 不在觸發集合（Path / "output"）
    (64, 'GFRIENDS_DIR = Path(__file__).parent / "output"\n', "Path Div 不紅"),
    # 字面容器本身不是「動態建構」——由 Tier 1 管
    (65, "X = {'a': 1}\n", "字面 dict 不是動態建構"),
]


class TestFalsifiabilityDemonstration:
    """DoD-4 可證偽演示矩陣（合成 source，不碰產品碼）。

    每格附「這格在防什麼」——比照 113d RED_CASES 排版。
    """

    @pytest.mark.parametrize(
        "case_id,source,reason",
        TIER1_RED_CASES,
        ids=[f"T1-RED-{c[0]}" for c in TIER1_RED_CASES],
    )
    def test_tier1_red(self, case_id, source, reason):
        violations = _tier1_violations_in_source(source)
        assert violations, (
            f"T1-RED-{case_id} 應轉紅（{reason}），但守衛判綠: {source!r}"
        )

    @pytest.mark.parametrize(
        "case_id,source,reason",
        TIER1_GREEN_CASES,
        ids=[f"T1-GREEN-{c[0]}" for c in TIER1_GREEN_CASES],
    )
    def test_tier1_green(self, case_id, source, reason):
        violations = _tier1_violations_in_source(source)
        assert not violations, (
            f"T1-GREEN-{case_id} 應綠（{reason}），但違規: {violations}"
        )

    def test_two_containers_count_is_two(self):
        """② 強化：同一函式兩個違規容器 → 命中次數恰為 2；只拿掉一處仍須紅。"""
        both = (
            "def f():\n"
            "    a = {'evil.example'}\n"
            "    b = {'other.evil'}\n"
            "    return a, b\n"
        )
        one = (
            "def f():\n"
            "    a = {'evil.example'}\n"
            "    return a\n"
        )
        assert len(_tier1_violations_in_source(both)) == 2
        assert len(_tier1_violations_in_source(one)) == 1

    @pytest.mark.parametrize(
        "case_id,source,reason",
        TIER2_RED_CASES,
        ids=[f"T2-RED-{c[0]}" for c in TIER2_RED_CASES],
    )
    def test_tier2_red(self, case_id, source, reason):
        violations = _tier2_violations_in_source(source)
        assert violations, (
            f"T2-RED-{case_id} 應轉紅（{reason}），但守衛判綠: {source!r}"
        )

    @pytest.mark.parametrize(
        "case_id,source,reason",
        TIER2_GREEN_CASES,
        ids=[f"T2-GREEN-{c[0]}" for c in TIER2_GREEN_CASES],
    )
    def test_tier2_green(self, case_id, source, reason):
        violations = _tier2_violations_in_source(source)
        assert not violations, (
            f"T2-GREEN-{case_id} 應綠（{reason}），但違規: {violations}"
        )

    def test_registry_two_step_read_counts_two(self):
        """③：兩次屬性讀 → 兩筆違規（is_connected + base_url）。"""
        src = (
            "from core.metatube.state import metatube_state\n"
            "def proxy_dynamic_hosts():\n"
            "    if metatube_state.is_connected:\n"
            "        return metatube_state.base_url\n"
            "    return None\n"
        )
        v = _tier2_violations_in_source(src)
        attrs = sorted(x[3] for x in v)
        assert attrs == ["base_url", "is_connected"]

    @pytest.mark.parametrize(
        "case_id,source,reason",
        DOD3_RED_CASES,
        ids=[f"DOD3-RED-{c[0]}" for c in DOD3_RED_CASES],
    )
    def test_dod3_red(self, case_id, source, reason):
        violations = _dynamic_violations_in_source(source)
        assert violations, (
            f"DOD3-RED-{case_id} 應轉紅（{reason}），但守衛判綠: {source!r}"
        )

    @pytest.mark.parametrize(
        "case_id,source,reason",
        DOD3_GREEN_CASES,
        ids=[f"DOD3-GREEN-{c[0]}" for c in DOD3_GREEN_CASES],
    )
    def test_dod3_green(self, case_id, source, reason):
        violations = _dynamic_violations_in_source(source)
        assert not violations, (
            f"DOD3-GREEN-{case_id} 應綠（{reason}），但違規: {violations}"
        )

    def test_anti_rot_allowlist_rename_shape(self):
        """④ 合成形：允許清單名字對不到命中容器 → anti-rot 語意（命中變違規）。

        把 REFERER_MAP 改名成 OTHER 後，同內容容器不再允許。
        """
        allowed = "REFERER_MAP = {'g': 'https://www.graphis.ne.jp/'}\n"
        renamed = "OTHER_MAP = {'g': 'https://www.graphis.ne.jp/'}\n"
        assert not _tier1_violations_in_source(allowed)
        assert _tier1_violations_in_source(renamed), (
            "改名後同內容容器必須變違規（允許清單按名字，不按內容）"
        )


# ============================================================
# review 修補（2026-08-07）：dotted ast.Import ＋ 容器內非 Constant 元素
# ============================================================

# 兩條都是 review 抓到的**守衛自己的洞**——守衛沒守到的東西，測試也證不出來，
# 所以修補一律連同「能證明它壞掉」的合成案例一起進來。

_TIER2_DOTTED_RED = [
    # card 技術要點明文要求支援（「本庫實際上未使用這個寫法，但要支援，
    # 同 113d 對 `import os.path` 的處理方式」）。initial 實作只認 ImportFrom。
    ("import-as, module scope",
     "import core.metatube.state as X\nu = X.metatube_state.base_url\n"),
    ("import-as, 函式內使用（binding 沿 scope 繼承）",
     "import core.metatube.state as X\ndef f():\n    return X.metatube_state.is_connected\n"),
    ("plain dotted import（只綁頂層 core，靠最長前綴解析）",
     "import core.metatube.state\nu = core.metatube.state.metatube_state.base_url\n"),
]

_TIER2_DOTTED_GREEN = [
    # 別誤傷：這四種都**不是** metatube_state 的讀取
    ("alias 被區域變數遮蔽",
     "import core.metatube.state as X\ndef f():\n    X = object()\n    return X.metatube_state.base_url\n"),
    ("其他物件的同名屬性",
     "import requests\nu = requests.base_url\n"),
    ("self 的私有屬性（T3b 的 _MetatubeShim._base_url 形狀）",
     "class C:\n    def f(self):\n        return self.base_url\n"),
    ("長得像但模組不對",
     "import core.other.state as X\nu = X.metatube_state.base_url\n"),
]


@pytest.mark.parametrize("label,src", _TIER2_DOTTED_RED, ids=[c[0] for c in _TIER2_DOTTED_RED])
def test_tier2_detects_dotted_import_bindings(label, src):
    """dotted `ast.Import` 的三種形狀都必須被解析到 metatube_state。"""
    assert _tier2_violations_in_source(src), f"{label}：dotted import 漏抓"


@pytest.mark.parametrize("label,src", _TIER2_DOTTED_GREEN, ids=[c[0] for c in _TIER2_DOTTED_GREEN])
def test_tier2_dotted_support_does_not_overreach(label, src):
    """加了 dotted 支援之後不得誤傷——負向那半沒驗，正向就只是「報得夠多」。"""
    assert _tier2_violations_in_source(src) == [], f"{label}：誤報"


_DOD3_NON_CONSTANT_RED = [
    ("Set 內含 Call", '_X = {load_host(), "a.com"}\n'),
    ("List 內含 Name", '_X = ["a.com", EXTRA_HOST]\n'),
    ("Tuple 內含 BinOp", '_X = ("a.com", "b" + ".com")\n'),
    ("Dict value 為 Call", '_X = {"k": load_host()}\n'),
    ("Dict key 為 Name", '_X = {HOST_KEY: "a.com"}\n'),
    ("Dict **spread", '_X = {**OTHER, "k": "a.com"}\n'),
    ("Set *spread", '_X = {*OTHER, "a.com"}\n'),
]


@pytest.mark.parametrize("label,src", _DOD3_NON_CONSTANT_RED, ids=[c[0] for c in _DOD3_NON_CONSTANT_RED])
def test_dod3_flags_container_with_non_constant_elements(label, src):
    """容器**內部**有非 Constant 元素 → 內容判定不出來 → 紅（review P2）。

    修補前這一類是兩層都看不到的死角：Tier 1 只檢查 `ast.Constant` 元素（非
    Constant 元素直接 skip），DoD-3 只看 RHS 最外層節點型別（`{...}` 是 Set
    字面、不是 Call/BinOp/comprehension）。於是
    `_ALLOWED = {load_host(), "a.com"}` 這種「一半內容動態產生的 host 集合」
    可以完全靜默通過——正是 BE-TEST-05 說的「認不出來的東西被跳過＝假綠」。
    """
    assert _dynamic_violations_in_source(src), f"{label}：非 Constant 元素被靜默跳過"


_DOD3_ALL_CONSTANT_GREEN = [
    ("全 Constant Dict（REFERER_MAP 形狀）", '_X = {"graphis": "https://www.graphis.ne.jp/"}\n'),
    ("全 Constant Tuple", '_X = ("a", "b")\n'),
    ("空容器", '_X = {}\n'),
]


@pytest.mark.parametrize("label,src", _DOD3_ALL_CONSTANT_GREEN, ids=[c[0] for c in _DOD3_ALL_CONSTANT_GREEN])
def test_dod3_does_not_flag_all_constant_containers(label, src):
    """全 Constant 的容器內容判定得出來——交給 Tier 1 判 domain-shaped，DoD-3 不插手。

    沒有這一組，上面那組「全部轉紅」用 `return True` 就能造假。
    """
    assert _dynamic_violations_in_source(src) == [], f"{label}：誤報"
