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

## 別名追蹤（Codex PR#128 P2）

第一版只比對**拼字**（名字是不是 `url`／`base_url`／`_base_url`），於是
`target = self._base_url` 後面 `logger.warning("%s", target)` 就通得過——
一次 routine rename 就繞過了守衛想擋的那件事本身。現在會追指派：

- 追 `name = ...` 與 `self.attr = ...`；跑到不動點，所以 `a = X; b = a; c = b` 整條鏈都算髒
- **RHS 是 `redact_metatube_url(...)` → LHS 乾淨**。沒有這一條，`client.py` 真正在用的
  `_log_target` / `where` 會整批誤報——那才是會讓人把守衛刪掉的那種紅
- 別名表**逐作用域**計算、只往內繼承，不橫向外溢（見
  `test_alias_scope_does_not_leak_across_functions`）
- flow-insensitive：log 呼叫寫在污染指派之前照樣抓（過近似往安全的那邊）

**明示殘留**（認不出來就不動，不猜）：tuple unpack、subscript、walrus、`AugAssign`
的指派目標不追蹤；decorator／參數預設值等「在外層作用域求值」的子節點按所在
`_SCOPE_NODES` 歸屬，未做 `_enclosing_evaluated_children()` 那套精算（本 4 檔無此形狀）。
拼字命中 `TAINTED_NAMES` 是洗不掉的下限——`url = redact_metatube_url(url)` 之後
`url` 仍算髒，fail-closed，修法是換名字。
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

# 唯一能把污染洗掉的出口。指派的 RHS 是它的呼叫 → LHS 乾淨。
_REDACTOR_NAME = "redact_metatube_url"

# Python 的獨立作用域節點。別名只在自己那層 + 往內繼承，不橫向外溢——
# 否則 A 函式裡的 `where = redact_metatube_url(...)` 會把 B 函式裡
# 同名的 `where = self._base_url` 洗白，而且結果隨 AST 走訪順序飄。
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# 例外類別名：訊息會被下游 `logger.exception` / `%s` 印出來，等同 log 表面。
EXC_SUFFIX = "Error"
EXC_NAMES = frozenset({
    "MetatubeError", "MetatubeUnavailable", "MetatubeNotFound",
    "MetatubeAuthError", "MetatubeClientError", "MetatubeProtocolError",
})


def _is_tainted_expr(node: ast.AST, aliases: frozenset[str] | set[str] | None = None) -> bool:
    """這個運算式會不會把原始 URL 的內容帶出來？

    涵蓋四種寫法：裸名 `url`、屬性 `self._base_url`、f-string 內插
    （`f"{self._base_url}{path}"` 這種——第三輪的根因正是這一形狀），以及
    **改名後的暫存變數**（`target = self._base_url` 之後的 `target`，由
    `aliases` 提供，見 `_resolve_aliases`）。
    **不涵蓋**經過 `redact_metatube_url(...)` 的呼叫結果，那正是允許的出口。

    拼字命中 `TAINTED_NAMES` 是**洗不掉的下限**：即使有人寫
    `url = redact_metatube_url(url)`，`url` 這個名字仍然算髒。fail-closed，
    且與加入別名追蹤前的行為完全一致（零既有綠燈回歸）。修法是換個名字。
    """
    aliases = aliases or frozenset()
    if isinstance(node, ast.Name):
        return node.id in TAINTED_NAMES or node.id in aliases
    if isinstance(node, ast.Attribute):
        return node.attr in TAINTED_NAMES or node.attr in aliases
    if isinstance(node, ast.JoinedStr):  # f-string
        return any(
            _is_tainted_expr(v.value, aliases)
            for v in node.values
            if isinstance(v, ast.FormattedValue)
        )
    if isinstance(node, ast.BinOp):  # "a" + url
        return _is_tainted_expr(node.left, aliases) or _is_tainted_expr(node.right, aliases)
    return False


def _is_redactor_call(node: ast.AST) -> bool:
    """RHS 是 `redact_metatube_url(...)`（或 `mod.redact_metatube_url(...)`）？"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == _REDACTOR_NAME
    if isinstance(func, ast.Attribute):
        return func.attr == _REDACTOR_NAME
    return False


def _assign_key(target: ast.AST) -> str | None:
    """只認 `name = ...` 與 `self.attr = ...`。

    tuple unpack／subscript／walrus／AugAssign 一律回 None ＝ 不追蹤。
    「認不出來就不動」而不是猜——猜錯的方向是誤報，誤報會讓人把守衛刪掉
    （同 CD-113c-14 撤回全庫帳本的判準）。這些形狀是明示的殘留，不是遺漏：
    真的有人用 tuple unpack 搬 URL 時，本守衛看不到。
    """
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


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
    """scope 內最近一層的巢狀作用域節點。"""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPE_NODES):
            yield node
            continue
        stack.extend(ast.iter_child_nodes(node))


def _resolve_aliases(scope: ast.AST, inherited: frozenset[str]) -> frozenset[str]:
    """算出本作用域內哪些名字被污染（繼承外層結果）。回傳的是**受污染名字的集合**。

    **flow-insensitive**：先把整個作用域的指派收齊再定案，不管文字順序。
    因此「log 呼叫寫在污染指派之前」也照樣抓得到——過近似的方向是安全的那一邊。

    **單調（monotone）**：這是本函式的核心不變式，也是 Codex PR#128 round-2 P2 的
    修正重點。第一版把每個名字算成一個可正可反的 `bool`，於是

        target = self._base_url            # → True
        target = redact_metatube_url(target)   # → False

    兩條指派會讓同一個 key 在 True/False 之間**永遠來回**，`changed` 兩邊都被拉起，
    `while changed:` 不收斂＝**掛死整個 pytest run**（比答錯更糟：沒有結果可看）。

    改成單調 lattice 後結構上不可能震盪：狀態只有「不在集合」→「在集合」單向一次，
    redactor 的結果**不貢獻污染，但也洗不掉已有的污染**。因此上面那組被判成
    tainted（fail-closed）——同一個名字既承接過原始 URL 又承接過 redacted 值時，
    我們不去猜哪一次先發生，一律當髒；修法是換個名字。這與既有的
    「拼字命中 `TAINTED_NAMES` 是洗不掉的下限」是同一條原則。

    迴圈另加**上界** `len(assigns) + 1`：單調性已經保證收斂，這個上界只是讓
    「未來有人把 lattice 改回可雙向」從**掛死**變成**一條指名的紅**。
    """
    tainted = set(inherited)
    assigns = [
        n for n in _own_nodes(scope)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
    ]
    for _ in range(len(assigns) + 1):
        changed = False
        for node in assigns:
            key = _assign_key(node.targets[0])
            if key is None or key in tainted:
                continue                       # 已髒就不再看＝單調的實作面保證
            if _is_redactor_call(node.value):
                continue                       # redactor 結果不貢獻污染
            if _is_tainted_expr(node.value, tainted):
                tainted.add(key)
                changed = True
        if not changed:
            return frozenset(tainted)
    raise AssertionError(                      # 單調時不可達；可達＝有人破壞了不變式
        f"別名解析在 {len(assigns) + 1} 輪內未收斂——lattice 不再是單調的。"
        f"見 _resolve_aliases docstring：狀態只准單向 False→True。"
    )


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


def _scan_scope(scope: ast.AST, inherited: frozenset[str], out: list) -> None:
    aliases = _resolve_aliases(scope, inherited)
    for node in _own_nodes(scope):
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
            if _is_tainted_expr(arg, aliases):
                out.append((node.lineno, kind))
                break
    for child in _child_scopes(scope):
        _scan_scope(child, aliases, out)


def _violations(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    _scan_scope(tree, frozenset(), out)
    return sorted(out)   # _own_nodes 是 LIFO 走訪，排序讓行號可讀且結果穩定


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
    # ---- Codex PR#128 P2：改名暫存變數（一次 routine refactor 就能繞過拼字比對）----
    ('一跳改名', 'target = self._base_url\nlogger.warning("%s", target)'),
    ('多跳改名鏈', 'a = self._base_url\nb = a\nc = b\nlogger.info(c)'),
    ('改名後才進 f-string', 'tgt = self._base_url\nlogger.debug(f"GET {tgt}{path}")'),
    ('屬性改名（self.x = self._base_url 鏡像形狀）',
     'class C:\n    def m(self):\n        self._cached = self._base_url\n'
     '        logger.debug("GET %s", self._cached)'),
    ('log 呼叫寫在污染指派之前（flow-insensitive 要照抓）',
     'def f():\n    logger.info("%s", t)\n    t = self._base_url'),
    ('改名後進例外訊息', 'tgt = url\nraise MetatubeError(f"failed {tgt}")'),
    # Codex PR#128 round-2 P2：同名 key 同時承接髒值與 redacted 值。
    # 第一版在這裡**無窮迴圈掛死**；單調化後判 tainted（fail-closed）。
    ('同名 key 先髒後 redacted（震盪形狀）',
     'target = self._base_url\ntarget = redact_metatube_url(target)\n'
     'logger.info("%s", target)'),
    ('同名 key 先 redacted 後髒（震盪形狀的反序）',
     'target = redact_metatube_url(url)\ntarget = self._base_url\n'
     'logger.info("%s", target)'),
]

_GREEN_SNIPPETS = [
    ('經過 redactor', 'logger.warning("failed for %s", redact_metatube_url(url))'),
    ('只記型別名', 'logger.info("failed: %s", type(exc).__name__)'),
    ('不相干的變數', 'logger.info("count=%s", total)'),
    ('redacted 變數', 'logger.debug("GET %s", where)'),
    ('非 logger 物件的同名方法', 'tracker.warning(url)'),
    # ---- 別名追蹤**不得**誤傷的形狀（負向那半；client.py 現況就是前兩條）----
    ('redactor 結果改名（client.py 的 _log_target 形狀）',
     'target = redact_metatube_url(url)\nlogger.warning("%s", target)'),
    ('redactor 結果多跳改名', 'a = redact_metatube_url(base_url)\nb = a\nlogger.info(b)'),
    ('redactor 結果改名後進 f-string（client.py 的 where 形狀）',
     'tgt = redact_metatube_url(base_url)\nlogger.debug(f"GET {tgt}{path}")'),
    ('不相干變數改名（不能因為存在別的指派就誤傷）',
     'count = total\nlogger.info("n=%s", count)'),
    ('同名變數在不同函式：一邊乾淨不得洗白另一邊的髒（此處驗乾淨那邊）',
     'def a():\n    w = redact_metatube_url(url)\n    logger.info("%s", w)'),
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


def test_alias_resolution_terminates_on_conflicting_assignments(tmp_path):
    """同一個 key 同時被指派髒值與 redacted 值 → 必須**收斂**，且判 tainted。

    這條鎖的是 Codex PR#128 round-2 P2：第一版的 lattice 允許 True↔False 雙向
    轉移，這個形狀會讓 `while changed:` 永遠跑下去——**掛死整個 pytest run**。
    掛死比答錯更難診斷（沒有 traceback、沒有失敗清單，只有一個不會結束的 job），
    所以這裡驗的不只是「答案對不對」，而是「它會不會回來」。

    `_resolve_aliases` 現在有 `len(assigns) + 1` 的上界，任何未來把單調性弄壞的
    修改都會撞上 AssertionError 而不是靜靜地轉圈。
    """
    src = (
        "target = self._base_url\n"
        "target = redact_metatube_url(target)\n"
        "logger.info('%s', target)\n"          # :3
    )
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    # 若單調性被破壞，這一行不會回來（而不是斷言失敗）——這正是本測試的重點
    assert _violations(f) == [(3, "logger")], (
        "同名 key 兩種來源時必須 fail-closed 判髒：不去猜哪一次指派先發生"
    )


def test_alias_scope_does_not_leak_across_functions(tmp_path):
    """兩個函式用**同一個變數名**，一邊乾淨一邊髒——只能紅髒的那一邊。

    這條鎖的是別名追蹤最容易寫錯的地方：若別名表做成整檔共用一份，
    `safe()` 裡的 `w = redact_metatube_url(...)` 會把 `leaky()` 裡的
    `w = self._base_url` 洗白（或反過來誤傷），而且結果隨 AST 走訪順序飄——
    「有紅」不等於「紅對地方」，所以這裡驗的是**幾條、在第幾行**。
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
        "應該只紅 leaky() 那一行（:7）；若連 :3 一起紅＝別名表外溢誤傷，"
        "若完全不紅＝乾淨那邊把髒的洗白了"
    )
