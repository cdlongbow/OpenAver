"""metatube 連線目標不得以原始字串進 log／例外訊息 —— AST 源碼語意守衛。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（憑證渲染單一所有權）

**為什麼需要這支**：Codex PR review 對同一個根因連開三輪——
`validate_metatube_url()` 從不檢查 userinfo，所以 `http://user:pass@host` 通得過
設定；那個值接著從三個不同出口漏出去（① `preview_cover_url` → API 回應 → 瀏覽器
② `GET /api/settings/metatube/status` 的欄位 ③ server log）。三輪的共通形狀不是
「漏想了幾個地方」，而是**每個出口各自決定要記什麼，沒有一個地方能指著說
「渲染規則寫在這裡」**——正是 spec-113 §2.5 定義的病症本身。

`core/metatube/validation.py::redact_metatube_url()` 是渲染規則的**唯一所有者**。

## 判準（T9 翻面：黑名單 → fail-closed 白名單）

前三版是**黑名單**：列舉「什麼算污染」，認不出來就放行。它被連續打穿三輪——
拼字比對 → 改名繞過（round-1）→ 別名追蹤不收斂掛死（round-2）→ 認不出
`.format()`／`str()`／container／巢狀呼叫（round-4）。失敗是**結構性**的：
Python 能把一個值送進 log 的語法形狀是開放集合，列舉違規形狀永遠落後於語言。

第四輪起翻面，與本 branch 第 4 條決策同一個動作（path 閘門從「列舉違規編碼」
改成「正向字元允許清單」）：

- **舊**：證明「這個運算式有沒有污染」→ 認不出來就**放行**（fail-open）
- **新**：證明「這個 sink 只收到已知安全的輸入」→ 認不出來就**紅**（fail-closed）

允許清單見 `_allowed()`：字面值、`redact_metatube_url(...)`、`type(x).__name__`、
`len()`、`list(x.keys())`、每個內插都安全的 f-string／`%`／`+`、provenance 證明
安全的名字、以及 `SAFE_NAME_LEDGER` 裡**逐條具名**的豁免。其餘一律紅。

**這一翻讓一條隱形殘留變成具名的**：`exc` / `err` 進 log 無法證明安全
（`requests` 的 `InvalidSchema`／`InvalidURL` 訊息內嵌原始 URL——PR body
accepted residual #5）。舊守衛對它完全無感（名字不叫 url 就放行）；新守衛逼它
進帳本並寫下理由。

**掃描範圍刻意窄**（只有實際持有 metatube 連線目標的那幾個檔）：範圍一大，帳本
成本就由每個不相干的 PR 支付——那是 CD-113c-14 撤回全庫 domain-literal 帳本時
已經走過一次的判準。59 個 sink 引數、22 種相異非字面形狀、帳本個位數，是這個
判準可行的前提。
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

LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

EXC_SUFFIX = "Error"
EXC_NAMES = frozenset({
    "MetatubeError", "MetatubeUnavailable", "MetatubeNotFound",
    "MetatubeAuthError", "MetatubeClientError", "MetatubeProtocolError",
})

# 唯一「把不安全變安全」的出口。
SAFE_RENDERER = "redact_metatube_url"

# 獨立作用域節點（別名 provenance 只往內繼承，不橫向外溢）。
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# ---------------------------------------------------------------------------
# 具名豁免帳本（binding-qualified）
# ---------------------------------------------------------------------------
# **鍵是 `函式名:綁定名`，不是裸名字**（Codex PR#128 round-5 P2）。
# 前一版用整份帳本當作用域初始安全集合，於是任何地方的 `path` 都被無條件信任——
#     def f():
#         path = self._base_url
#         logger.warning("%s", path)      # ← 假綠
# 那正好違反 T9 宣稱的「未證明一律紅」。現在豁免只在**那一個函式的那一個綁定**成立，
# 而且要綁定種類也對得上（參數 / except-as / 指派）。同名不同處＝不適用＝走 provenance。
#
# 值 = (綁定種類, 理由)。加一條要在 PR diff 上被看見。
_PARAM, _EXCEPT, _ASSIGN = "param", "except", "assign"

SAFE_BINDINGS: dict[str, tuple[str, str]] = {
    # 鍵 = `相對檔案路徑:限定作用域:綁定名`。三段缺一不可（round-5 二審 P2）：
    # 只有 `函式名:綁定名` 時，任何檔案、任何 class 的同名 method 都會通吃——
    # `class OtherClient: def get_info(self, provider)` 會命中已審核過的
    # `MetatubeHttpClient.get_info` 的豁免，而那根本是另一段程式碼。
    "core/metatube/client.py:MetatubeHttpClient._get_data:path":
        (_PARAM, "API 路徑（'/v1/movies/...'），同檔內自組、不含連線目標"),
    "core/metatube/client.py:MetatubeHttpClient.get_info:provider":
        (_PARAM, "provider 代號（型錄名）"),
    "core/metatube/client.py:MetatubeHttpClient.search:provider":
        (_PARAM, "同上"),
    "core/metatube/probe.py:probe_provider:provider":
        (_PARAM, "同上"),
    "core/metatube/state.py:MetatubeConnectionState.connect:provider_names":
        (_PARAM, "provider 代號串列"),
    "core/metatube/probe.py:probe_all:provider_names":
        (_PARAM, "同上"),
    "core/metatube/state.py:MetatubeConnectionState.is_available:source_id":
        (_PARAM, "來源代號（'metatube:FANZA'），本庫自組"),
    "core/metatube/state.py:MetatubeConnectionState.mark_available:source_id":
        (_PARAM, "同上"),
    "core/metatube/state.py:MetatubeConnectionState.mark_failed:source_id":
        (_PARAM, "同上"),
    "core/metatube/probe.py:probe_all:source_id":
        (_ASSIGN, "f'metatube:{name}'，name 來自 future.result() 的 provider 名"),
    "core/metatube/state.py:MetatubeConnectionState.set_probe_progress:total":
        (_PARAM, "計數"),
    "core/metatube/state.py:MetatubeConnectionState.set_probe_progress:done":
        (_PARAM, "計數"),
    "core/metatube/probe.py:probe_all:done":
        (_ASSIGN, "計數（`done = 0` 後遞增）"),
    "core/metatube/probe.py:probe_provider:canary":
        (_ASSIGN, "METATUBE_PROBE_CANARIES 的值——同檔字面 dict 的番號常數"),
    # ↓ 這兩條是翻面**逼出來**的：舊守衛對例外物件完全無感（名字不叫 url 就放行）。
    #   而它們分屬兩個檔／兩個作用域——名字式帳本一條通吃，完整身分才看得出是兩件事。
    "core/metatube/client.py:MetatubeHttpClient._get_data:exc":
        (_EXCEPT, "例外物件。**證不出安全**——requests 的 InvalidSchema/InvalidURL 訊息"
                  "內嵌原始 URL（PR#128 accepted residual #5）。目前該路徑不可達"
                  "（validate_metatube_url() 在任何 client 呼叫前就擋掉 scheme），"
                  "屬休眠風險，具名接受而非改碼。"),
    "core/metatube/probe.py:probe_provider:exc":
        (_EXCEPT, "同上"),
}

# 屬性層的允許（**與名字帳本分開**——否則帳本裡的 `path` 會連 `other.path` 一起放行）。
SAFE_ATTRS: frozenset[str] = frozenset({
    "__name__",      # type(x).__name__ ＝ 類別名，不是資料
    "status_code",   # HTTP 狀態碼
})

# 除了 redactor 之外，還有一個**有文件保證**的安全回傳：
#   core/metatube/validation.py:71「The returned string never contains the raw
#   hostname or IP.」——所有 return 都是模組級 _ERR_* 常數。
SAFE_CALLS: frozenset[str] = frozenset({
    "redact_metatube_url",
    "validate_metatube_url",
    "len",
})


def _callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _allowed(node: ast.AST, safe: frozenset[str] | set[str],
             safe_attrs: frozenset[str] = frozenset()) -> bool:
    """這個運算式是不是**已知安全**的形狀？認不出來一律 False（fail-closed）。"""
    if isinstance(node, ast.Constant):
        return True                                   # 字面值
    if isinstance(node, ast.JoinedStr):               # f-string：每個內插都要安全
        return all(
            _allowed(v.value, safe, safe_attrs)
            for v in node.values if isinstance(v, ast.FormattedValue)
        )
    if isinstance(node, ast.BinOp):                   # "a" + x / fmt % x：兩邊都要安全
        return _allowed(node.left, safe, safe_attrs) and _allowed(node.right, safe, safe_attrs)
    if isinstance(node, ast.Name):
        return node.id in safe
    if isinstance(node, ast.Attribute):
        # 屬性走**獨立**的允許集合，不吃名字帳本——否則帳本裡的 `path`
        # 會連 `other.path` 一起放行（round-5 P2）。
        return node.attr in SAFE_ATTRS or node.attr in safe_attrs
    if isinstance(node, ast.Call):
        fn = _callee_name(node.func)
        if fn in SAFE_CALLS:
            return True                               # 消毒出口 / 有文件保證的回傳 / len()
        if fn == "get" and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id.isupper():
            return True                               # <ALLCAPS>.get(...) ＝ 同檔字面常數表
        if fn == "list":                              # list(x.keys()) ＝ 只有鍵、沒有值
            return (
                len(node.args) == 1
                and isinstance(node.args[0], ast.Call)
                and _callee_name(node.args[0].func) == "keys"
            )
        return False                                  # 其餘任何呼叫（str()/.format()/…）→ 紅
    return False                                      # list/dict/comprehension/walrus/… → 紅


# ---------------------------------------------------------------------------
# provenance：一個名字只有在「它的每一個指派 RHS 都安全」時才算安全
# ---------------------------------------------------------------------------

def _assign_key(target: ast.AST) -> str | None:
    """只認 `name = ...`（函式作用域的區域名）。`self.attr` 由 `_safe_attributes()` 處理。"""
    return target.id if isinstance(target, ast.Name) else None


def _own_nodes(scope: ast.AST):
    """scope 自己那一層的所有節點——**不穿透**巢狀 def/class/lambda。"""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _SCOPE_NODES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _child_scopes(scope: ast.AST):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPE_NODES):
            yield node
            continue
        stack.extend(ast.iter_child_nodes(node))


def _safe_attributes(tree: ast.AST) -> frozenset[str]:
    """全檔計算哪些 `self.<attr>` 可證明安全。

    **只認 `self.<attr>`**（round-5 P2：前一版任何 `x.y = ...` 都算，於是 `other.path`
    這種也會被放行）。實例屬性跨方法存活，所以判準是「全檔每一個對 `self.X` 的指派
    都安全」——任一處寫入證不出來的值，`X` 就在所有地方都不安全。

    種子只有 `SAFE_ATTRS`，**不含名字帳本**：帳本的 `path` 不該讓 `self.path` 或
    `other.path` 自動安全。
    """
    by_attr: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if (isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
            by_attr.setdefault(tgt.attr, []).append(node.value)

    safe = set(SAFE_ATTRS)
    for _ in range(len(by_attr) + 1):
        changed = False
        for attr, values in by_attr.items():
            if attr in safe:
                continue
            if all(_allowed(v, frozenset(), frozenset(safe)) for v in values):
                safe.add(attr)
                changed = True
        if not changed:
            return frozenset(safe)
    raise AssertionError("屬性 provenance 未收斂——集合應只增不減。")


def _local_bindings(scope: ast.AST) -> dict[str, tuple[str, list[ast.AST]]]:
    """本作用域**自己**綁定了哪些名字，以及綁定種類。

    參數 / `except ... as` / 指派各自是一種綁定；for-target、with-as、walrus、
    tuple unpack 等認不出來的形式登記為 `"other"`——**它們一樣會遮蔽外層**，
    而且永遠證不出安全（fail-closed）。
    """
    out: dict[str, tuple[str, list[ast.AST]]] = {}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        args = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
        if a.vararg:
            args.append(a.vararg)
        if a.kwarg:
            args.append(a.kwarg)
        for arg in args:
            out[arg.arg] = (_PARAM, [])
    for node in _own_nodes(scope):
        if isinstance(node, ast.ExceptHandler) and node.name:
            out[node.name] = (_EXCEPT, [])
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            key = _assign_key(node.targets[0])
            if key is not None:
                kind, vals = out.get(key, (_ASSIGN, []))
                out[key] = (kind if kind == _PARAM else _ASSIGN, vals + [node.value])
            elif isinstance(node.targets[0], (ast.Tuple, ast.List)):
                for elt in node.targets[0].elts:      # tuple unpack：遮蔽 + 不可證
                    if isinstance(elt, ast.Name):
                        out.setdefault(elt.id, ("other", []))
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, ("other", []))
        elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, ("other", []))
        elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
            out.setdefault(node.optional_vars.id, ("other", []))
    return out


def _safe_names(scope, ident: str, inherited: frozenset[str],
                safe_attrs: frozenset[str]) -> frozenset[str]:
    """本作用域可證明安全的名字。

    **遮蔽**：只要本作用域自己綁定了某個名字，外層對它的判定就失效——重新證。
    這是 round-5 P2 的核心：前一版把帳本整份當初始集合，於是
    `path = self._base_url` 因為「`path` 在帳本裡」而被無條件信任。

    一個綁定安全 ⇔ ①`SAFE_BINDINGS["<函式>:<名字>"]` 命中**且綁定種類相符**，或
    ② 它是指派且**每一個** RHS 都在允許清單內。其餘一律不安全。
    """
    local = _local_bindings(scope)
    safe = {n for n in inherited if n not in local}      # 本作用域重新綁定 → 遮蔽
    for _ in range(len(local) + 1):
        changed = False
        for name, (kind, values) in local.items():
            if name in safe:
                continue
            entry = SAFE_BINDINGS.get(f"{ident}:{name}")
            if entry is not None and entry[0] == kind:
                safe.add(name)
                changed = True
                continue
            if kind == _ASSIGN and values and all(
                    _allowed(v, safe, safe_attrs) for v in values):
                safe.add(name)
                changed = True
        if not changed:
            return frozenset(safe)
    raise AssertionError("provenance 未收斂——集合應只增不減。")


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


def _child_ident(parent_ident: str, child_name: str) -> str:
    """由父作用域身分推出子作用域身分（掃描與反腐**共用同一支**，避免兩邊漂移）。

    `rel:<module>` → `rel:Klass` → `rel:Klass.method`；模組層函式 → `rel:func`。
    """
    if parent_ident.endswith(":<module>"):
        return f"{parent_ident[:-len(':<module>')]}:{child_name}"
    return f"{parent_ident}.{child_name}"


def _walk_bindings(scope, ident: str):
    """yield `(完整身分, 綁定名, 綁定種類)`，涵蓋所有巢狀作用域。"""
    for name, (kind, _vals) in _local_bindings(scope).items():
        yield f"{ident}:{name}", name, kind
    for child in _child_scopes(scope):
        child_ident = _child_ident(ident, getattr(child, "name", "<lambda>"))
        yield from _walk_bindings(child, child_ident)


def _scan_scope(scope, ident: str, inherited: frozenset[str],
                safe_attrs: frozenset[str], out: list) -> None:
    """`ident` ＝ `相對檔案路徑:限定作用域`（如
    `core/metatube/client.py:MetatubeHttpClient._get_data`）。豁免只在**那一個**
    綁定成立——換檔案、換 class、換 method 都是不同身分（round-5 二審 P2）。
    """
    safe = _safe_names(scope, ident, inherited, safe_attrs)
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        if _is_log_call(node):
            kind = "logger"
        elif _is_exception_call(node):
            kind = "exception"
        else:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if not _allowed(arg, safe, safe_attrs):
                out.append((node.lineno, kind))
                break
    for child in _child_scopes(scope):
        child_ident = _child_ident(ident, getattr(child, "name", "<lambda>"))
        _scan_scope(child, child_ident, safe, safe_attrs, out)


def _violations(path: pathlib.Path, rel: str | None = None) -> list[tuple[int, str]]:
    """`rel` ＝ 帳本身分用的相對檔案路徑。

    合成片段預設用 `<synthetic>`——**任何帳本條目都不會命中**，正是想要的：
    豁免綁在真實檔案的真實綁定上。要演示「帳本命中」的綠燈案例，必須顯式傳入
    該條目登記的那個 `rel`。
    """
    if rel is None:
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = "<synthetic>"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    _scan_scope(tree, f"{rel}:<module>", frozenset(), _safe_attributes(tree), out)
    return sorted(out)


# ---------------------------------------------------------------------------
# 受監控檔案
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", WATCHED_FILES)
def test_only_known_safe_values_reach_log_sinks(rel):
    """受監控檔案的 log／例外引數必須全部落在允許清單內。

    紅了不一定是「洩漏」，也可能是「守衛認不出這個新形狀」——**兩者都要處理**：
    前者改用 `redact_metatube_url(...)`，後者在 PR 上具名擴充允許清單或帳本。
    fail-closed 的重點就是不讓第二種情況靜靜通過。
    """
    path = REPO_ROOT / rel
    assert path.exists(), f"受監控檔案不存在（改名？搬移？）：{rel}"
    hits = _violations(path)
    assert hits == [], (
        f"{rel}: log／例外引數不在允許清單內（{len(hits)} 處，行號 {hits}）。"
        f"若是連線目標 → 改用 core.metatube.validation.redact_metatube_url()；"
        f"若是守衛認不出的安全形狀 → 在 _allowed() 或 SAFE_NAME_LEDGER 具名擴充。"
    )


def test_watched_files_actually_use_the_redactor():
    """anti-rot：受監控清單若因重構而全數失去 metatube 關聯，這支會指名。"""
    users = [
        rel for rel in WATCHED_FILES
        if SAFE_RENDERER in (REPO_ROOT / rel).read_text(encoding="utf-8")
    ]
    assert len(users) >= 3, (
        f"受監控檔案中只有 {users} 用到 redactor——清單可能已與現況脫節。"
    )


def test_ledger_has_no_dead_entries():
    """帳本反腐：豁免只准減不准增。

    binding-qualified 之後這條變得更嚴：不只檢查名字還在，還檢查
    **那個函式還在、而且那個名字仍以登記的種類綁在它裡面**。函式改名、參數改成
    區域變數、except 改成別的寫法——任一種都會讓豁免失效並被指名，而不是靜靜留著。
    """
    live: set[str] = set()
    for rel in WATCHED_FILES:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for key, _name, kind in _walk_bindings(tree, f"{rel}:<module>"):
            live.add(f"{key}|{kind}")

    dead = [
        key for key, (kind, _reason) in SAFE_BINDINGS.items()
        if f"{key}|{kind}" not in live
    ]
    assert dead == [], (
        f"SAFE_BINDINGS 有 {len(dead)} 條死條目（函式不存在／名字不再以該種類綁定）："
        f"{dead}。請刪除——豁免只准減不准增。"
    )


# ---------------------------------------------------------------------------
# 可證偽演示（合成 source，永久留檔）
# ---------------------------------------------------------------------------
# 注意：fail-closed 判準下，合成片段裡**沒有指派過的裸名一律紅**。所以綠燈演示要嘛
# 用帳本內的名字、要嘛先從安全 RHS 指派——這本身就是判準翻面的直接後果。

_RED_SNIPPETS = [
    # ---- 前三輪打出來的形狀（回歸保護）----
    ('裸名 url 進 logger', 'logger.warning("failed for %s", url)'),
    ('屬性 self._base_url 進 logger', 'logger.debug("GET %s", self._base_url)'),
    ('f-string 內插', 'logger.info(f"probing {base_url}")'),
    ('原始 url 進例外訊息', 'raise MetatubeAuthError(f"auth failed for {url}")'),
    ('字串相加', 'logger.info("at " + url)'),
    ('keyword 引數', 'logger.info("x", extra=url)'),
    ('一跳改名（round-1 的繞過）', 'target = self._base_url\nlogger.warning("%s", target)'),
    ('多跳改名鏈', 'a = self._base_url\nb = a\nc = b\nlogger.info(c)'),
    ('同名 key 先髒後 redacted（round-2 的掛死形狀）',
     'target = self._base_url\ntarget = redact_metatube_url(target)\n'
     'logger.info("%s", target)'),
    # ---- round-4 點名 + 我方實測補齊的同類（黑名單全部漏抓，白名單全紅）----
    ('.format() 插值', 'logger.warning("target={}".format(url))'),
    ('str() 包一層', 'logger.info("at %s", str(url))'),
    ('放進 list', 'logger.info("x", extra=[url])'),
    ('放進 dict', 'logger.info("x", extra={"u": url})'),
    ('f-string 內再包呼叫', 'logger.info(f"{str(self._base_url)}")'),
    # ---- DoD-4：守衛**沒見過**的語法，fail-closed 的分水嶺 ----
    ('未知方法呼叫（守衛沒見過）', 'logger.info("%s", url.upper())'),
    ('walrus（守衛沒見過）', 'logger.info("%s", (u := url))'),
    ('comprehension（守衛沒見過）', 'logger.info("%s", [x for x in url])'),
    ('subscript（守衛沒見過）', 'logger.info("%s", parts[0])'),
    ('tuple unpack 來的名字（_assign_key 不認 → 不安全）',
     'a, b = self._base_url, 1\nlogger.info("%s", a)'),
    # ---- round-5 P2：帳本必須綁 binding，不能被同名變數遮蔽 ----
    ('帳本名字被指派覆寫（Codex round-5 點名的確切形狀）',
     'def f():\n    path = self._base_url\n    logger.warning("%s", path)'),
    ('帳本名字在**未登記的函式**當參數（不得跨函式繼承豁免）',
     'def g(path):\n    logger.warning("%s", path)'),
    ('登記為參數的名字改用指派（綁定種類不符 → 豁免失效）',
     'def _get_data():\n    path = self._base_url\n    logger.warning("%s", path)'),
    ('帳本名字被拿去接屬性（other.path 不該因帳本而放行）',
     'logger.warning("%s", other.path)'),
    ('內層 def 遮蔽外層已證安全的同名變數',
     'def outer():\n    w = redact_metatube_url(base_url)\n'
     '    def inner(w):\n        logger.info("%s", w)'),
]

_GREEN_SNIPPETS = [
    ('經過 redactor', 'logger.warning("failed for %s", redact_metatube_url(url))'),
    ('只記型別名', 'logger.info("failed: %s", type(exc).__name__)'),
    ('純字面', 'logger.info("connect ok")'),
    ('len()', 'logger.info("n=%s", len(names))'),
    ('list(x.keys())', 'logger.info("keys=%s", list(data.keys()))'),
    ('非 logger 物件的同名方法', 'tracker.warning(url)'),
    ('redactor 結果改名（client.py 的 _log_target 形狀）',
     'target = redact_metatube_url(url)\nlogger.warning("%s", target)'),
    ('redactor 結果多跳改名', 'a = redact_metatube_url(base_url)\nb = a\nlogger.info(b)'),
    ('redactor 結果改名後進 f-string（client.py 的 where 形狀）',
     'tgt = redact_metatube_url(base_url)\nlogger.debug(f"GET {tgt}")'),
]


@pytest.mark.parametrize("label,src", _RED_SNIPPETS, ids=[s[0] for s in _RED_SNIPPETS])
def test_guard_flags_everything_not_provably_safe(label, src, tmp_path):
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f), f"{label}：應紅卻沒抓到（fail-closed 破功）"


@pytest.mark.parametrize("label,src", _GREEN_SNIPPETS, ids=[s[0] for s in _GREEN_SNIPPETS])
def test_guard_does_not_overreach(label, src, tmp_path):
    """負向那半沒驗，正向就只是「報得夠多」——會在合法寫法上炸開的守衛沒人留得住。"""
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f) == [], f"{label}：誤報"


def test_provenance_scope_does_not_leak_across_functions(tmp_path):
    """兩個函式用**同一個變數名**，一邊可證安全一邊不可——只能紅不可證的那一邊。

    驗的是「幾條、在第幾行」，不是「有沒有紅」：若 provenance 表做成整檔共用，
    `safe()` 裡的 `w = redact_metatube_url(...)` 會把 `leaky()` 的 `w` 一起洗白
    （或反過來誤傷），而且結果隨 AST 走訪順序飄。
    """
    src = (
        "def safe():\n"
        "    w = redact_metatube_url(base_url)\n"
        "    logger.info('%s', w)\n"          # :3 —— 不得紅
        "\n"
        "def leaky():\n"
        "    w = self._base_url\n"
        "    logger.info('%s', w)\n"          # :7 —— 必須紅
    )
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f) == [(7, "logger")], (
        "應該只紅 leaky() 那一行（:7）；連 :3 一起紅＝provenance 外溢誤傷，"
        "完全不紅＝安全那邊把不安全的洗白了"
    )


def test_partially_safe_name_is_not_safe(tmp_path):
    """同一個名字有兩個指派、只有一個可證安全 → **整體不安全**。

    這是 fail-closed 與 fail-open 的分界線本身：黑名單版會因為「找不到污染證據」
    而放行，白名單版因為「有一個指派證不出安全」而拒絕。
    """
    src = (
        "def f(flag):\n"
        "    w = redact_metatube_url(base_url)\n"
        "    if flag:\n"
        "        w = self._base_url\n"
        "    logger.info('%s', w)\n"          # :5
    )
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f) == [(5, "logger")], (
        "只要有一個指派證不出安全，這個名字就不該安全"
    )


# ---------------------------------------------------------------------------
# 帳本身分 ＝ 檔案 : 限定作用域 : 綁定名（round-5 二審 P2）
# ---------------------------------------------------------------------------
# 前一版鍵只有 `函式名:綁定名`，於是任何檔案、任何 class 的同名 method 都會通吃
# 已審核過的豁免。下面三支把「同名但不同身分必須紅」釘住。

_LEDGER_HIT_CASES = [
    ('client.py 的 MetatubeHttpClient.get_info:provider（登記命中）',
     "core/metatube/client.py",
     'class MetatubeHttpClient:\n    def get_info(self, provider):\n'
     '        logger.info("provider=%s", provider)'),
    ('probe.py 的 probe_provider:exc（登記命中）',
     "core/metatube/probe.py",
     'def probe_provider(provider):\n    try:\n        pass\n'
     '    except MetatubeError as exc:\n        logger.info("%s", exc)'),
    ('probe.py 的 probe_all:source_id（登記命中，指派型）',
     "core/metatube/probe.py",
     'def probe_all(provider_names):\n    source_id = f"metatube:{provider_names}"\n'
     '        \n    logger.info("%s", source_id)'.replace("        \n", "")),
]


@pytest.mark.parametrize("label,rel,src", _LEDGER_HIT_CASES,
                         ids=[c[0] for c in _LEDGER_HIT_CASES])
def test_ledger_hits_only_at_the_registered_identity(label, rel, src, tmp_path):
    """正向：身分完全相符時豁免生效。"""
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f, rel=rel) == [], f"{label}：誤報"


@pytest.mark.parametrize("label,rel,src", _LEDGER_HIT_CASES,
                         ids=[c[0] for c in _LEDGER_HIT_CASES])
def test_same_name_in_another_file_is_not_covered(label, rel, src, tmp_path):
    """反向 ①：**同樣的程式碼、換一個受監控檔** → 豁免不適用，必須紅。"""
    other = next(w for w in WATCHED_FILES if w != rel)
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f, rel=other), (
        f"{label}：換到 {other} 仍被放行——帳本身分沒把檔案算進去"
    )


def test_same_method_name_in_another_class_is_not_covered(tmp_path):
    """反向 ②：**同檔、同 method 名、不同 class** → 必須紅（Codex 點名的形狀）。

        class OtherClient:
            def get_info(self, provider):
                logger.warning("%s", provider)

    這不是 `MetatubeHttpClient.get_info` 那個已審核過的參數，不該共用它的豁免。
    """
    src = (
        "class OtherClient:\n"
        "    def get_info(self, provider):\n"
        '        logger.warning("%s", provider)\n'
    )
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f, rel="core/metatube/client.py") == [(3, "logger")], (
        "同名 method 位於不同 class 時不得命中豁免"
    )


def test_module_level_function_does_not_hit_class_method_ledger(tmp_path):
    """反向 ③：把 class method 攤平成模組層函式 → 身分改變，豁免失效。"""
    src = (
        "def get_info(provider):\n"
        '    logger.warning("%s", provider)\n'
    )
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    assert _violations(f, rel="core/metatube/client.py") == [(2, "logger")], (
        "模組層 get_info 不該命中 MetatubeHttpClient.get_info 的豁免"
    )
