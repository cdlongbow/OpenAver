"""AST 邊界守衛：六個具名函式的 nfo_stat 委派 + 覆寫語意契約（feature/113b T3, CD-113b-3）。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（六函式 stat 委派 + 覆寫語意契約）：
# 斷言 fast_scan_directory / try_inflow_upsert / enrich_single / _sync_nfo_mtime /
# backfill_readonly_nfo_mtime / _write_movie_assets 六個函式體內「直接 .st_mtime
# 存取」與「委派 core.nfo_stat.nfo_mtime_or_none」兩個計數恰等於期望值，且各自
# 宣告的 _NFO_MTIME_POLICY 常數字面正確。static_guard_lint 只能做字面字串比對，
# 無法表達「某個具名函式體內特定 AST 節點的計數」這種語意，故留 pytest。

守什麼：
  S1 = core.gallery_scanner.fast_scan_directory
  S2 = core.db_inflow.try_inflow_upsert
  S3 = core.enricher.enrich_single
  S4 = core.enricher._sync_nfo_mtime
  S5 = core.database.migrate.backfill_readonly_nfo_mtime
  S6 = core.readonly_producer._write_movie_assets

六處各自要對帳兩個計數：「直接讀 mtime」（`.st_mtime` / `.st_mtime_ns` 屬性存取，
以及 `os.path.getmtime(...)` / 裸名 `getmtime(...)` 呼叫——Opus 審核裁決 2，三種
形狀合併進同一桶）與「委派 `core.nfo_stat.nfo_mtime_or_none`」，兩者都必須**恰等於**
期望整數（不是 `>=`）。S1 天生混著一次**正當**的非 NFO `.st_mtime`（影片檔），
所以本守衛不是「函式體有沒有違規」的黑白名單存在性判斷，是「兩個計數各自等於
某個具體整數」的逐處對帳（見 TASK-113b-T3.md 開頭説明，與 113a-T3 的關鍵差異）。

裸名 import（本卡與 113a-T3 同構的落差）：五個檔案全部是裸名呼叫
（`nfo_mtime_or_none(entry, ...)`）+ 模組最外層 `from core.nfo_stat import
nfo_mtime_or_none, NFO_MTIME_*`，不是 `nfo_stat.nfo_mtime_or_none(...)` 帶前綴
形式。本守衛因此解析 import binding：裸名呼叫/裸名常數必須真的從
`core.nfo_stat` import 進來才算合法委派/合法常數（`_nfo_stat_bare_name_bindings`），
擋掉「consumer 檔案自己定義同名 local shadow」的漏洞。

★ 巢狀 def 陷阱（本卡最重要的新發現，B 段，Opus 審核裁決 1 已獨立實測採納）：
`fast_scan_directory` 內部有兩層巢狀 `def`（`_safe_on_skip` / `scan_recursive`），
本卡要鎖的兩個目標節點全部落在最深層的 `scan_recursive` 裡。113a-T3 的
`_direct_nodes`「遞迴收集直接 body 子節點，但停在巢狀 def」若照搬到本卡，
`fast_scan_directory` 的兩個計數會**雙雙變成 0**（Opus 實測 `(0, 0)`），而不是
期望的 `(1, 1)`——整格驗收條件靜默失效，不是細節出入。113a-T3 沒踩到這個坑是
因為它的三個目標函式（`_nfo_to_meta`／`parse_nfo`／`_nfo_to_producer_meta`）
恰好都沒有巢狀 def，「停在巢狀 def」在那支守衛裡從未被真正觸發過。

**本卡定案**：收集函式改用 `_all_nodes`——直接對 `func_node` 跑 `ast.walk`，
不特殊處理巢狀 `def`/`AsyncFunctionDef`。`TestNestedDefBoundary` 用「若改回
停在巢狀 def 的收集語義」的對照實作明確鎖住這個選型（DoD 硬條件，不能只靠
六格 parametrize 剛好都過隱含證明）。

裁決 2（Opus 審核）：「直接讀取 mtime」計數桶額外收 `.st_mtime_ns` 與
`os.path.getmtime(...)`/裸名 `getmtime(...)`——只數 `.st_mtime` 會留一個現成的
繞過形狀（改寫成 `getmtime()` 語意相同但守衛全綠）。本庫兩種寫法都真的在用
（`focal/worker.py` 用 `st_mtime_ns`、`readonly_producer.py:1920` 與
`web/routers/scraper.py:641` 用 `os.path.getmtime`，皆不在本卡六個目標函式內）。
六個目標函式三種形狀合計後期望值表一格都不用改（`.st_mtime_ns`/`getmtime` 六處
皆為 0，`TASK-113b-T3.md` 附帶確認表已實測）。

★★ 本守衛的契約與**停損線**（owner 拍板，2026-08-06；下一個維護者請先讀這段）★★

  **這支守衛偵測「非蓄意的漂移」，不偵測「蓄意的規避」。**

  要防的是真實會發生的事：有人加回一次手寫 `.stat().st_mtime`、複製一個呼叫點
  卻忘了改政策常數、把委派整個拿掉。這些第一版就擋住了。

  **不在範圍內**：刻意寫出病態 Python 來騙過名字解析——例如在目標函式裡用
  `except OSError as _NFO_MTIME_POLICY` 改掉宣告、或用巢狀 scope 的同名參數遮蔽
  委派名。這類形狀已經修到 scope-aware 為止（見下方修訂史），但**手寫 AST 比對
  永遠不可能對「蓄意規避」健全**——那需要完整的型別/scope 推導，是編譯器的工作，
  不是一支測試的工作。同樣的取捨在 113a-T3 §8 Q-2 已經結案過，這裡沿用同一把尺。

  **判準**：一條 finding 要不要修，看「**不知情的維護者會不會不小心寫出來**」。
  會 → 修。要刻意才寫得出來 → 記在這裡，不修。

  這條線是被五輪 review 打出來的：第 1 輪修的是真漏洞（只取第一個 assignment），
  第 2–5 輪全部是「還能用什麼怪語法騙過它」，其中三輪紅的甚至不是程式碼、是我
  自己「已經涵蓋全部」的宣稱。**修法本身開始生出新洞（第 5 輪的不對稱正是第 4
  輪修法造成的）就是方法到極限的訊號**，不是快收工的訊號。

已知限制（承接 113a-T3 §8 Q-2 同構）：
- 把 stat 邏輯搬到六個目標函式**之外**的新 top-level helper 再從目標函式呼叫，
  會逃過本守衛的計數（跨函式呼叫鏈不追蹤）——需要刻意繞過才會發生，不在本卡
  修復範圍。
- `_all_nodes` 對巢狀 def 不設邊界，理論上若目標函式的巢狀 def 未來新增其他跟
  mtime 完全無關的 `.st_mtime` 存取也會被算進來——本卡六個函式目前無此情況
  （已用 ast.walk 逐一核對），這是「逐處對帳」相對「黑白名單違規掃描」天生的
  取捨：計數對了不保證語意對，只保證「這裡沒有意外多出/少掉一次 stat」。
- **維護成本（S1 專有）**：`fast_scan_directory` 的期望讀取數 1 綁的是影片檔那次
  正當存取。若將來在該函式內**正當地**新增另一次非 NFO 的 mtime 讀取，本守衛會
  轉紅，必須連同 `EXPECTED` 表一起更新（而不是把它當誤報繞過）——這是「恰等於」
  而非「至少」的必然代價，也正是它擋得住「偷偷多寫一次手寫 stat」的原因。

主要骨架仿 `tests/unit/test_nfo_read_boundary_guard.py`（113a-T3 產物，本卡直系
前例）：`_parse`/`_tree`（per-file cache）、`_find_func`（找不到回 None，白名單
防腐）、`_module_level_import_froms`、import binding 解析一組工具、檔頂
`[lint-guard: pytest-justified]` 標記格式、合成片段紅/綠對照 parametrize 手法，
皆原樣複用同構寫法。**不可複用**的唯一部分是 `_direct_nodes`——本卡改寫成
`_all_nodes`（上方巢狀 def 段落已說明理由）。

為何 pytest 不是 lint（CLAUDE.md「Lint 守衛規則」north-star）：本守衛驗的是
「某個 Python 函式體內特定 AST 節點的計數，以及一個賦值語句的 RHS import
binding」，CLAUDE.md 判斷原則明列此類走 pytest（C 類）；`static_guard_lint`/
eslint/stylelint 完全不處理 `.py` 檔案，機械上無法承接。
"""
import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
GALLERY_SCANNER_PY = REPO_ROOT / "core" / "gallery_scanner.py"
DB_INFLOW_PY = REPO_ROOT / "core" / "db_inflow.py"
ENRICHER_PY = REPO_ROOT / "core" / "enricher.py"
MIGRATE_PY = REPO_ROOT / "core" / "database" / "migrate.py"
READONLY_PRODUCER_PY = REPO_ROOT / "core" / "readonly_producer.py"


# ============================================================
# AST 工具（比照 test_nfo_read_boundary_guard.py 骨架；_all_nodes 是本卡改寫項）
# ============================================================

def _parse(py_file: pathlib.Path) -> ast.Module:
    return ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))


_TREE_CACHE: dict = {}


def _tree(py_file: pathlib.Path) -> ast.Module:
    key = str(py_file)
    if key not in _TREE_CACHE:
        _TREE_CACHE[key] = _parse(py_file)
    return _TREE_CACHE[key]


def _find_func(tree: ast.Module, name: str):
    """全樹遍歷找 node.name == name 的 FunctionDef/AsyncFunctionDef。找不到回
    None（白名單防腐用，呼叫端必須明確失敗並指名，不可靜默 skip）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _all_nodes(func_node) -> list:
    """收集 func_node 函式體內*所有*子節點，含巢狀 def 內部（不同於
    113a-T3 的 `_direct_nodes`：本卡必須下潛進 fast_scan_directory 的巢狀
    scan_recursive，否則其兩個目標計數會被算成 0，見本檔案開頭 docstring
    的巢狀 def 陷阱段落）。`ast.walk` 天然不在巢狀 def 停下。"""
    return list(ast.walk(func_node))


def _direct_nodes_stopping_at_nested_def(func_node) -> list:
    """113a-T3 `_direct_nodes` 的原文語義（遞迴收集直接 body 子節點，但**停在
    巢狀 def**）——本卡**不使用**這個收集方式，僅保留給 `TestNestedDefBoundary`
    做「若改回這個語義會怎樣」的對照試驗，鎖住 `_all_nodes` 的選型不被靜默
    改回去。"""
    out = []

    def _walk(nodes):
        for node in nodes:
            out.append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _walk(ast.iter_child_nodes(node))

    _walk(ast.iter_child_nodes(func_node))
    return out


SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _direct_scope_nodes(scope_node) -> list:
    """該 scope **自己**的節點（遞迴進 body，但**停在巢狀 scope**）。

    與 `_all_nodes`（全下鑽）互補：`_all_nodes` 用來數 mtime 讀取（那是純語法
    形狀，跨 scope 一樣算數），這支用來做 **scope-aware 的名字解析**（同一個
    裸名在不同 scope 可能指向不同東西）。
    """
    out = []

    def rec(node):
        for c in ast.iter_child_nodes(node):
            out.append(c)
            if isinstance(c, SCOPE_TYPES):
                continue  # 巢狀 scope 只收節點本身，內容由它自己那層處理
            rec(c)

    rec(scope_node)
    return out


def _scope_binds_name(scope_node, target_name: str) -> bool:
    """`target_name` 是否在**這一層 scope 自己**被綁定（參數或本層任何綁定形狀）。"""
    if _own_param_bindings(scope_node, target_name):
        return True
    return bool(_binding_nodes(_direct_scope_nodes(scope_node), target_name))


def _scoped_delegate_calls(scope_node, bindings: dict, shadowed: bool = False) -> list:
    """scope-aware 的委派呼叫計數（Codex 五審 P1）。

    **問題**：`_nfo_stat_delegate_calls` 只看 module 層 import binding，而計數用
    `_all_nodes` 全下鑽。於是巢狀 scope 內的呼叫會被算成合法委派，**即使那個
    scope 自己把名字重新綁定了**：

        def fast_scan_directory(...):
            def inner(nfo_mtime_or_none):        # 這個名字在 inner 裡是參數
                return nfo_mtime_or_none(path)   # 呼叫的不是 primitive，卻被計入

    上一輪我排除了「巢狀函式的參數」（正確，那是 inner 的 scope），卻沒有同時
    排除**同一個 scope 裡的呼叫**——一邊排除一邊計入，就是這條假綠。

    **為什麼不能兩邊一起排除**（Codex 給的另一個選項）：實測 S1 的唯一委派呼叫
    就住在巢狀 `scan_recursive` 裡（`fast_scan_directory > scan_recursive`），
    整層排掉會讓 S1 的委派計數變 0、期望值 1 直接崩掉。**所以只剩 scope-aware
    這一條路。**

    規則：一個裸名呼叫只有在「它所在的 scope 鏈上（目標函式以內）沒有任何一層
    重新綁定該名字」時，才算解析到 module 層的 import。
    """
    here_shadowed = shadowed or _scope_binds_name(scope_node, "nfo_mtime_or_none")
    direct = _direct_scope_nodes(scope_node)
    out = [] if here_shadowed else _nfo_stat_delegate_calls(direct, bindings)
    for n in direct:
        if isinstance(n, SCOPE_TYPES):
            out += _scoped_delegate_calls(n, bindings, here_shadowed)
    return out


def _module_level_import_froms(tree: ast.Module) -> list:
    """只收 module 最外層（非任何函式/類別內）的 `ast.ImportFrom`。"""
    return [n for n in tree.body if isinstance(n, ast.ImportFrom)]


# ============================================================
# import binding 解析（技術要點第 3 節）：裸名呼叫/裸名常數是否真的從
# core.nfo_stat import 進來，防同名 local shadow 騙過守衛
# ============================================================

NFO_STAT_SYMBOLS = {
    "nfo_mtime_or_none",
    "NFO_MTIME_REFRESH", "NFO_MTIME_ON_UPSERT", "NFO_MTIME_FILL_MISSING",
}

POLICY_CONSTANT_NAMES = ("NFO_MTIME_REFRESH", "NFO_MTIME_ON_UPSERT", "NFO_MTIME_FILL_MISSING")


def _nfo_stat_bare_name_bindings(tree: ast.Module) -> dict:
    """本檔案模組最外層 `from core.nfo_stat import X [as Y]` 的
    {本地名稱: 原始名稱}，僅收原始名稱在 NFO_STAT_SYMBOLS 內的項目。"""
    bindings = {}
    for node in _module_level_import_froms(tree):
        if node.module != "core.nfo_stat":
            continue
        for alias in node.names:
            if alias.name in NFO_STAT_SYMBOLS:
                bindings[alias.asname or alias.name] = alias.name
    return bindings


# ============================================================
# 兩個計數的判準（技術要點第 2 節 + Opus 裁決 2）
# ============================================================

def _direct_mtime_read_nodes(nodes: list) -> list:
    """回傳所有「直接讀取 mtime」節點：`.st_mtime` / `.st_mtime_ns` 屬性存取，
    以及 `os.path.getmtime(...)`（Attribute 形式）/ 裸名 `getmtime(...)`
    （Opus 審核裁決 2：三種形狀合併進同一桶，堵掉只數 `.st_mtime` 留下的
    getmtime()/st_mtime_ns 繞過縫隙）。"""
    out = []
    for n in nodes:
        if isinstance(n, ast.Attribute) and n.attr in ("st_mtime", "st_mtime_ns"):
            out.append(n)
        elif isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Attribute) and fn.attr == "getmtime":
                out.append(n)
            elif isinstance(fn, ast.Name) and fn.id == "getmtime":
                out.append(n)
    return out


def _nfo_stat_delegate_calls(nodes: list, bare_bindings: dict) -> list:
    """回傳所有真正解析到 core.nfo_stat.nfo_mtime_or_none 的 ast.Call 節點。
    bare_bindings 是本檔案模組最外層 `from core.nfo_stat import
    nfo_mtime_or_none [as Y]` 的 {本地名稱: 原始名稱}，只收原始名稱 ==
    "nfo_mtime_or_none" 的項目（同構 113a-T3 的 _resolves_to_nfo_read，防同名
    local shadow 函式騙過守衛）。"""
    return [
        n for n in nodes
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and bare_bindings.get(n.func.id) == "nfo_mtime_or_none"
    ]


POLICY_VAR = "_NFO_MTIME_POLICY"


def _own_param_bindings(func_node, target_name: str) -> list:
    """目標函式**自己簽名上**綁定 `target_name` 的參數節點（`ast.arg`）。

    Codex 四審 P1：`_binding_nodes` 刻意不數 `ast.arg`，理由是「巢狀函式的參數
    屬於它自己的 scope」——那個理由對**巢狀**函式成立，但我把它套成了全面排除，
    連**目標函式自己的參數**也一起漏掉了。而後者是**真的**在目標函式 scope 裡
    綁定該名字：

        def _sync_nfo_mtime(..., nfo_mtime_or_none):   # 遮蔽 module 層 import
            return nfo_mtime_or_none(path)             # 呼叫的已不是 primitive

    `_nfo_stat_delegate_calls` 只看 module 層 import binding，仍會把它算成合法
    委派。所以參數要數，但**只數 `func_node` 自己的 `.args`、不遞迴**（巢狀函式
    的參數維持排除，那部分的原始理由沒有錯）。

    涵蓋 `posonlyargs` / `args` / `kwonlyargs` / `vararg` / `kwarg` 五類。
    """
    a = func_node.args
    out = [
        arg for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs))
        if arg.arg == target_name
    ]
    out += [arg for arg in (a.vararg, a.kwarg) if arg is not None and arg.arg == target_name]
    return out


def _all_bindings(func_node, target_name: str) -> list:
    """函式 scope 內 `target_name` 的**全部**綁定＝自己簽名的參數 ＋ 函式體內的
    各種綁定形狀。policy 與 delegate 兩側都走這個單一入口，避免兩邊的覆蓋面漂移
    （四輪 review 的教訓：同一個漏洞會在兩個計數上各出現一次）。"""
    return _own_param_bindings(func_node, target_name) + _binding_nodes(_all_nodes(func_node), target_name)


def _binding_nodes(nodes: list, target_name: str) -> list:
    """回傳函式體內所有「會把 `target_name` 綁定到某個東西」的節點。

    掃描的欄位清單見 `_policy_assignment` docstring 的表格（Codex 三審 P1：
    `ast.Name(Store/Del)` **不是**全部，`import ... as` / `except ... as` /
    `case` 三大家族把名字存成 AST 欄位上的**字串**，不產生 `ast.Name`）。

    參數化名字（而非寫死 `_NFO_MTIME_POLICY`）是因為**同一個漏洞在委派計數那一
    側也成立**：`_nfo_stat_delegate_calls` 只靠 module 層 import binding 判斷
    `nfo_mtime_or_none(...)` 是不是真委派，若有人在函式內把這個名字重新綁定
    （用上表任何一種形狀），呼叫的其實已經是別的東西，委派計數卻照算。
    `TestDelegateNameNotRebound` 用同一支 helper 鎖住那一側。
    """
    POLICY_VAR = target_name  # noqa: N806 — 沿用下方分支的既有可讀命名
    out = []
    for n in nodes:
        # ① 賦值家族：Assign / AnnAssign / AugAssign / NamedExpr / tuple 拆包 /
        #    for-target / with-as / del —— 這些在 AST 上都是 Name + Store/Del
        if isinstance(n, ast.Name) and n.id == POLICY_VAR and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append(n)
        # ② import 別名：`import m as P` / `from m import X as P` / `from m import P`
        #    （無 asname 時綁定的是 name 的**頂層段**：`import a.b` 綁的是 `a`）
        elif isinstance(n, ast.alias) and (n.asname or n.name.split(".")[0]) == POLICY_VAR:
            out.append(n)
        # ③ except 別名：`except E as P`（.name 是 str，不是 Name 節點）
        elif isinstance(n, ast.ExceptHandler) and n.name == POLICY_VAR:
            out.append(n)
        # ④ match capture：`case P` / `case [*P]` / `case {**P}`（皆為 str 欄位）
        elif isinstance(n, ast.MatchAs) and n.name == POLICY_VAR:
            out.append(n)
        elif isinstance(n, ast.MatchStar) and n.name == POLICY_VAR:
            out.append(n)
        elif isinstance(n, ast.MatchMapping) and n.rest == POLICY_VAR:
            out.append(n)
        # ⑤ 巢狀 def/class 同名遮蔽：`def P(): ...` / `class P: ...`
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == POLICY_VAR:
            out.append(n)
        # ⑥ global/nonlocal：不新增綁定，但改變「賦值寫到哪個 scope」，會讓宣告
        #    的效力跑到函式外——同樣視為違反「唯一且就地」的宣告契約。
        elif isinstance(n, (ast.Global, ast.Nonlocal)) and POLICY_VAR in n.names:
            out.append(n)
    return out


def _policy_assignment(func_node, bindings: dict):
    """判定函式體內 `_NFO_MTIME_POLICY = ...` 賦值是否符合『恰好一個合法宣告』
    契約，回傳 `(status, node, resolved)` 三元組。

    **判準：數「這個名字被綁定了幾次」，不是數「有幾個 Assign 語句」。**

    這條規則經歷了四輪同根因的修正，每一輪都是「守衛只看得見某一部分 AST 形狀」：
      1. 初版「找到第一個合法命中即 return」——完全不驗唯一性。
      2. 補了 `ast.AnnAssign`（`P: str = X`）。
      3. Codex 二審：`ast.AugAssign`（`P += ...`）與 `ast.NamedExpr`（海象 `P := X`）。
      4. Codex 三審：**上一輪宣稱的「所有 Python 綁定都是 `ast.Name(Store/Del)`」
         這個前提本身是錯的**——`import ... as P`、`except E as P`、`case P` 這些
         形狀把名字存成 **AST 欄位上的字串**（`alias.asname` / `ExceptHandler.name`
         / `MatchAs.name`…），**根本不產生 `ast.Name` 節點**（已實測列出八種）。
         用一句漂亮的通則掩蓋沒查證的覆蓋面，正是前三輪的同一個錯誤又犯一次。
      5. Codex 四審：上一輪把 `ast.arg` 整類排除，理由「巢狀函式參數屬於不同
         scope」——那個理由只對**巢狀**函式成立，卻被套成全面排除，連**目標函式
         自己的參數**（真的在本 scope 綁定該名字）也一起漏掉。已改為
         `_own_param_bindings` 只數 `func_node` 自己的簽名、巢狀的維持排除。

    **因此本 docstring 不再宣稱任何「涵蓋全部」的通則**，改為逐項列出實際掃描的
    欄位（有增修就改這張表）：

    | 綁定形式 | AST 落點 |
    |---|---|
    | `P = X` / `P: T = X` / `P += X` / `(P := X)` / `P, q = t` / `for P in ...` / `with ... as P` / `del P` | `ast.Name` + `ctx=Store/Del` |
    | `import m as P` / `from m import X as P` / `from m import P` | `ast.alias`（`asname`，無則 `name` 的頂層段） |
    | `except E as P` | `ast.ExceptHandler.name` |
    | `case P` / `case [*P]` / `case {**P}` | `ast.MatchAs.name` / `ast.MatchStar.name` / `ast.MatchMapping.rest` |
    | `def P(): ...` / `class P: ...`（巢狀同名遮蔽） | `ast.FunctionDef` / `ast.AsyncFunctionDef` / `ast.ClassDef` 的 `.name` |
    | `global P` / `nonlocal P`（改變綁定去向） | `ast.Global.names` / `ast.Nonlocal.names` |

    | 目標函式**自己簽名**上的參數（`def f(..., P)`，含 `posonlyargs`/`args`/`kwonlyargs`/`*P`/`**P`） | `ast.arg.arg`（`_own_param_bindings`） |

    **明知未涵蓋（刻意，非疏漏）**：**巢狀**函式的參數（`def inner(P)` 裡的 `P`）
    ——那是巢狀函式自己 scope 的綁定，計入才是誤報。**注意這條的邊界**：目標函式
    **自己**的參數是要數的（見上表最後一列，Codex 四審 P1）。其餘任何形狀若日後
    被發現可以改掉這個名字，**應該修這裡，不是記成已知限制**（這支守衛的全部價值
    就是「policy 宣告唯一且說得算」）。

    回傳 `(status, node, resolved)`：
    - `("none", None, None)`：這個名字在函式體內完全沒有被綁定過。
    - `("multiple", [綁定節點...], None)`：被綁定 **>1 次**——不論個別合不合法、
      值是否相同。宣告的用途是「讀呼叫端就知道語意」，被改過第二次就不成立了
      （runtime 實際生效的是最後一次）。
    - `("ok", node, 常數原始名稱)`：恰好綁定 1 次，且那次是單純的
      `ast.Assign`（單一 Name target），RHS 是真正解析到 `core.nfo_stat` 的
      `NFO_MTIME_*` 常數。
    - `("illegal_rhs", node, None)`：恰好綁定 1 次但不合格——RHS 不是解析自
      `core.nfo_stat` 的常數（本地 shadow、字面字串），**或**那唯一一次綁定根本
      不是單純賦值（tuple 拆包、for target、AugAssign 單獨出現…）。
    """
    nodes = _all_nodes(func_node)
    # 自己簽名的參數 + 函式體內的各種綁定形狀（單一入口，見 _all_bindings）
    bind_nodes = _all_bindings(func_node, POLICY_VAR)
    if not bind_nodes:
        return ("none", None, None)
    if len(bind_nodes) > 1:
        return ("multiple", bind_nodes, None)

    # 恰好綁定一次：那一次還必須是「單純的具名賦值」才算合格宣告。
    plain_assigns = [
        n for n in nodes
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "_NFO_MTIME_POLICY"
    ]
    if len(plain_assigns) != 1:
        # 唯一那次綁定來自非賦值形式（for target / tuple 拆包 / 單獨的 AugAssign
        # 或 AnnAssign-without-value 之類）→ 不是合格宣告。
        return ("illegal_rhs", bind_nodes[0], None)
    node = plain_assigns[0]
    resolved = bindings.get(node.value.id) if isinstance(node.value, ast.Name) else None
    if resolved in POLICY_CONSTANT_NAMES:
        return ("ok", node, resolved)
    return ("illegal_rhs", node, None)


# ============================================================
# 真檔 target 清單（S1-S6）+ 期望值表（CD-113b-3 / plan-113b §3 T3 v8）
# ============================================================

# (標籤, 檔案, 函式名)
REAL_TARGETS = [
    ("S1", GALLERY_SCANNER_PY, "fast_scan_directory"),
    ("S2", DB_INFLOW_PY, "try_inflow_upsert"),
    ("S3", ENRICHER_PY, "enrich_single"),
    ("S4", ENRICHER_PY, "_sync_nfo_mtime"),
    ("S5", MIGRATE_PY, "backfill_readonly_nfo_mtime"),
    ("S6", READONLY_PRODUCER_PY, "_write_movie_assets"),
]

# (檔案, 函式名) -> (期望「直接讀 mtime」計數, 期望「委派」計數)
EXPECTED = {
    (GALLERY_SCANNER_PY, "fast_scan_directory"): (1, 1),
    (DB_INFLOW_PY, "try_inflow_upsert"): (0, 1),
    (ENRICHER_PY, "enrich_single"): (0, 1),
    (ENRICHER_PY, "_sync_nfo_mtime"): (0, 1),
    (MIGRATE_PY, "backfill_readonly_nfo_mtime"): (0, 1),
    (READONLY_PRODUCER_PY, "_write_movie_assets"): (0, 1),
}

# (檔案, 函式名) -> 期望政策常數原始名稱（CD-113b-3）
EXPECTED_POLICY = {
    (GALLERY_SCANNER_PY, "fast_scan_directory"): "NFO_MTIME_REFRESH",       # S1
    (DB_INFLOW_PY, "try_inflow_upsert"): "NFO_MTIME_ON_UPSERT",             # S2
    (ENRICHER_PY, "enrich_single"): "NFO_MTIME_REFRESH",                    # S3
    (ENRICHER_PY, "_sync_nfo_mtime"): "NFO_MTIME_FILL_MISSING",             # S4
    (MIGRATE_PY, "backfill_readonly_nfo_mtime"): "NFO_MTIME_FILL_MISSING",  # S5
    (READONLY_PRODUCER_PY, "_write_movie_assets"): "NFO_MTIME_REFRESH",     # S6
}


def _target_ctx(py_file: pathlib.Path, func_name: str):
    tree = _tree(py_file)
    func = _find_func(tree, func_name)
    if func is None:
        pytest.fail(
            f"{py_file.name}:{func_name} 定位不到（白名單防腐應先報，改名或誤刪？）"
        )
    bindings = _nfo_stat_bare_name_bindings(tree)
    return func, bindings


# ============================================================
# 白名單防腐：六個具名函式必須都能定位到（反假綠硬條件之一）
# ============================================================

class TestWhitelistAntiRot:
    """六個具名 target 必須能在對應檔 AST 定位，否則守衛指向殭屍函式、恆綠
    假通過。找不到必須明確失敗並指名。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_target_function_exists(self, label, py_file, func_name):
        tree = _tree(py_file)
        func = _find_func(tree, func_name)
        assert func is not None, (
            f"[{label}] {py_file.name}:{func_name} 指向不存在的函式（改名？）"
            f" —— 守衛失去意義，須更新清單或修復函式名"
        )

    def test_misnamed_function_fails_explicitly(self):
        """反假綠實測：函式名打錯，_target_ctx 必須用 pytest.fail 明確指名，
        不是丟出無關的 AttributeError/None 堆疊。"""
        with pytest.raises(pytest.fail.Exception, match=r"fast_scan_directoryX"):
            _target_ctx(GALLERY_SCANNER_PY, "fast_scan_directoryX")

    def test_misrouted_file_fails_explicitly(self):
        """反假綠實測：檔案路徑指到一個不存在該函式的真實檔案（不是不存在的
        路徑——五個目標檔本身都存在，錯的是「函式跟檔案對錯」這件事），
        必須明確指名，不是無關堆疊。"""
        with pytest.raises(pytest.fail.Exception, match=r"try_inflow_upsert"):
            _target_ctx(GALLERY_SCANNER_PY, "try_inflow_upsert")


# ============================================================
# (a) 逐處對帳：兩個計數恰等於期望值（反假綠硬條件，DoD 核心）
# ============================================================

class TestCountReconciliation:
    """六格用獨立 parametrize case（BE-TEST-05：表驅動守衛要逐格能單獨轉紅），
    不是塞進單一 assert all(...)。計數用 `==`，不是 `>=`。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_direct_mtime_read_count_equals_expected(self, label, py_file, func_name):
        expected_reads, _expected_delegate = EXPECTED[(py_file, func_name)]
        func, _bindings = _target_ctx(py_file, func_name)
        nodes = _all_nodes(func)
        actual = len(_direct_mtime_read_nodes(nodes))
        assert actual == expected_reads, (
            f"[{label}] {py_file.name}:{func_name}() 直接讀取 mtime 計數應恰等於"
            f" {expected_reads}，實際 {actual}"
        )

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_delegate_call_count_equals_expected(self, label, py_file, func_name):
        _expected_reads, expected_delegate = EXPECTED[(py_file, func_name)]
        func, bindings = _target_ctx(py_file, func_name)
        nodes = _all_nodes(func)
        # scope-aware：巢狀 scope 若重新綁定委派名，其內呼叫不算委派（五審 P1）
        actual = len(_scoped_delegate_calls(func, bindings))
        assert actual == expected_delegate, (
            f"expected {expected_delegate}, got {actual} calls in {func_name} ({py_file})"
        )


# ============================================================
# (b) 覆寫語意具名可見：六格常數字面逐格比對（反假綠硬條件）
# ============================================================

class TestPolicyLiteralContract:
    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_policy_literal_matches_expected(self, label, py_file, func_name):
        expected = EXPECTED_POLICY[(py_file, func_name)]
        func, bindings = _target_ctx(py_file, func_name)
        nodes = _all_nodes(func)
        status, _node, resolved = _policy_assignment(func, bindings)
        assert status == "ok", (
            f"[{label}] {py_file.name}:{func_name}() 的 `_NFO_MTIME_POLICY ="
            f" NFO_MTIME_*` 賦值應恰好 1 個合法宣告，實際狀態 status={status}"
            f"（'none'=完全沒有／'multiple'=不只一個／'illegal_rhs'=有一個但"
            f" RHS 未解析自 core.nfo_stat）"
        )
        assert resolved == expected, (
            f"[{label}] {py_file.name}:{func_name}() 的 _NFO_MTIME_POLICY 應為"
            f" {expected}，實際 {resolved}"
        )


# ============================================================
# 巢狀 def 邊界（DoD 硬條件）：鎖住 _all_nodes 的選型
# ============================================================

class TestNestedDefBoundary:
    """`fast_scan_directory` 的兩個目標節點都在巢狀 `scan_recursive` 內。若
    `_all_nodes` 被改回「停在巢狀 def」的收集語義，兩個計數會雙雙變成 0
    （Opus 審核裁決 1 已實測）。這支測試直接對照兩種收集方式的差異，明確鎖住
    `_all_nodes` 目前的選型，不能只靠六格 parametrize 剛好都過隱含證明。"""

    def test_all_nodes_descends_into_nested_def(self):
        func, bindings = _target_ctx(GALLERY_SCANNER_PY, "fast_scan_directory")
        nodes = _all_nodes(func)
        reads = len(_direct_mtime_read_nodes(nodes))
        delegates = len(_nfo_stat_delegate_calls(nodes, bindings))
        assert (reads, delegates) == (1, 1), (
            f"_all_nodes（全下鑽）對 fast_scan_directory 應得到 (1, 1)，實際"
            f" ({reads}, {delegates})——巢狀 def 選型可能被改動"
        )

    def test_stopping_at_nested_def_would_silently_zero_out(self):
        """對照試驗：若改用「停在巢狀 def」的收集語義（113a-T3 _direct_nodes
        原文），fast_scan_directory 的兩個計數會雙雙歸零——這正是本卡不能照抄
        113a-T3 骨架的存在理由，必須用測試鎖住，不能只靠文件描述。"""
        func, bindings = _target_ctx(GALLERY_SCANNER_PY, "fast_scan_directory")
        stale_nodes = _direct_nodes_stopping_at_nested_def(func)
        reads = len(_direct_mtime_read_nodes(stale_nodes))
        delegates = len(_nfo_stat_delegate_calls(stale_nodes, bindings))
        assert (reads, delegates) == (0, 0), (
            f"「停在巢狀 def」的收集語義對 fast_scan_directory 預期得到 (0, 0)"
            f"（兩個目標節點都在 scan_recursive 內、對照組看不到），實際"
            f" ({reads}, {delegates})——若這裡不再是 (0,0)，代表原始碼結構已變、"
            f"本對照測試的前提需要重新核對"
        )


# ============================================================
# 誤報檢查：S1 影片檔的 .st_mtime 不得被判違規（技術要點第 6 節）
# ============================================================

class TestFalsePositiveGuard:
    def test_fast_scan_directory_video_stat_is_counted_as_legitimate_one(self):
        """S1 的期望值表把「影片檔的 .st_mtime」算成正當的 1（不是 0）——本測試
        必須**實際跑過守衛機制**去證明那個 1 是誰貢獻的，而不是拿期望值表跟自己比。

        （T3 review 抓到的假綠：本測試原本只斷言 `EXPECTED[...] == 1`，那是測試檔
        自己的常數跟自己比，判準函式全部改壞它照樣綠——正是本 plan 在消滅的形狀。）
        """
        func, _ = _target_ctx(GALLERY_SCANNER_PY, "fast_scan_directory")
        read_nodes = _direct_mtime_read_nodes(_all_nodes(func))

        assert len(read_nodes) == 1, (
            f"S1 應恰有 1 次正當的直接 mtime 讀取（影片檔），實際 {len(read_nodes)}"
        )
        # 那 1 次必須真的是影片檔那條路徑：`stat = entry.stat()` 之後的
        # `stat.st_mtime`，receiver 是名為 `stat` 的區域變數——而不是任何
        # 對 `.nfo` 的手寫 stat（後者的 receiver 會是 nfo_path/entry 之類）。
        node = read_nodes[0]
        assert node.attr == "st_mtime"
        assert isinstance(node.value, ast.Name) and node.value.id == "stat", (
            "S1 那次正當存取應為影片檔分支的 `stat.st_mtime`（receiver 是區域變數 "
            f"`stat`），實際 receiver 形狀為 {ast.dump(node.value)[:80]}——"
            "若形狀改變，代表影片檔那段被改寫或那 1 次其實來自別處，需重新核對"
        )


# ============================================================
# 合成片段：紅/綠對照（技術要點第 6 節，裁決 1 承接）
# ============================================================

_SYNTH_IMPORTS = "from core.nfo_stat import NFO_MTIME_REFRESH, nfo_mtime_or_none\n"

_SYNTH_SHELL_MINIMAL = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return nfo_mtime_or_none(entry)
"""

# 貼近真實 fast_scan_directory 形狀：委派呼叫 + 影片檔 .st_mtime 兩者都在，
# 驗證守衛不會把正當的影片檔 stat 誤判成違規（誤報檢查）。
_SYNTH_SHELL_WITH_VIDEO_STAT = _SYNTH_IMPORTS + """
def consumer(entry, video_entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    mt = nfo_mtime_or_none(entry)
    stat = video_entry.stat()
    video_mtime = stat.st_mtime
    return mt, video_mtime
"""

# 手寫多一次 .st_mtime（違規變體）：計數應從期望值 +1。
_SYNTH_SHELL_EXTRA_ST_MTIME = _SYNTH_IMPORTS + """
def consumer(entry, some_path):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    extra_mtime = some_path.stat().st_mtime
    return nfo_mtime_or_none(entry), extra_mtime
"""

# getmtime 繞過變體（裁決 2 存在理由）：委派改寫成 os.path.getmtime(...)。
_SYNTH_SHELL_GETMTIME_BYPASS = _SYNTH_IMPORTS + """
import os


def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return os.path.getmtime(entry)
"""

# st_mtime_ns 繞過變體（裁決 2 存在理由的第二種形狀）。
_SYNTH_SHELL_ST_MTIME_NS_BYPASS = _SYNTH_IMPORTS + """
def consumer(some_path):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    stat = some_path.stat()
    return stat.st_mtime_ns
"""

# 裸名 getmtime(...) 繞過變體（不帶 os.path 前綴）。
_SYNTH_SHELL_BARE_GETMTIME_BYPASS = _SYNTH_IMPORTS + """
from os.path import getmtime


def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return getmtime(entry)
"""

# 常數字面被改掉的變體（(b) 證偽）。
_SYNTH_SHELL_WRONG_POLICY = (
    _SYNTH_IMPORTS.replace("NFO_MTIME_REFRESH", "NFO_MTIME_REFRESH, NFO_MTIME_ON_UPSERT")
    + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_ON_UPSERT
    return nfo_mtime_or_none(entry)
"""
)

# 唯一性違規變體之一（P1 修正核心，Codex branch review 抓到）：正確宣告後面
# 再新增一個「衝突但個別看起來也合法」的第二個宣告——舊版 _policy_assignment
# 找到第一個合法命中就 return，這種形狀會被靜默放行，44 格照樣全綠。新版必須
# 判定為 status="multiple" 並轉紅。
_SYNTH_SHELL_DUPLICATE_POLICY_CONFLICTING = (
    _SYNTH_IMPORTS.replace("NFO_MTIME_REFRESH", "NFO_MTIME_REFRESH, NFO_MTIME_ON_UPSERT")
    + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    x = nfo_mtime_or_none(entry)
    _NFO_MTIME_POLICY = NFO_MTIME_ON_UPSERT
    return x
"""
)

# 唯一性違規變體之二：正確宣告後面再新增一個「不合法 RHS」（字面字串）的第二
# 個宣告。舊版一樣會被第一個合法命中放行；新版必須判定為 status="multiple"
# （總賦值數 > 1 即違反唯一性，不論第二個合不合法）。
_SYNTH_SHELL_DUPLICATE_POLICY_ILLEGAL_RHS = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    x = nfo_mtime_or_none(entry)
    _NFO_MTIME_POLICY = "refresh"
    return x
"""

# AnnAssign 變體（Opus 二審補）：第二個宣告寫成帶型別標註的形式
# `_NFO_MTIME_POLICY: str = ...`，AST 上是 ast.AnnAssign 而非 ast.Assign。
# 若唯一性檢查只收 Assign，這個形狀會逃過去、status 回到 'ok' —— 與 P1 同族。
_SYNTH_SHELL_DUPLICATE_POLICY_ANNASSIGN = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    x = nfo_mtime_or_none(entry)
    _NFO_MTIME_POLICY: str = NFO_MTIME_ON_UPSERT
    return x
"""

# AugAssign 變體（Codex 二審 P1）：正確宣告後用 `+=` 就地改值。runtime 的最後
# 值已經不是宣告的那個常數，宣告失去「讀呼叫端就知道語意」的作用。
_SYNTH_SHELL_POLICY_AUGASSIGN_AFTER = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    _NFO_MTIME_POLICY += "_changed"
    return nfo_mtime_or_none(entry)
"""

# NamedExpr（海象）變體（Codex 二審 P1）：正確宣告後用 `:=` 在運算式裡重設。
_SYNTH_SHELL_POLICY_NAMEDEXPR_AFTER = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    if (_NFO_MTIME_POLICY := NFO_MTIME_ON_UPSERT):
        pass
    return nfo_mtime_or_none(entry)
"""

# 規則普適性變體（Opus 補，證明「數綁定次數」不是又一次的形狀列舉）：
# tuple 拆包與 for-target 都不在 Codex 點名的清單裡，但同樣會重新綁定該名字，
# 新判準不必為它們各寫一條分支就能一起擋掉。
_SYNTH_SHELL_POLICY_TUPLE_UNPACK_AFTER = _SYNTH_IMPORTS + """
def consumer(entry, pair):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    _NFO_MTIME_POLICY, _other = pair
    return nfo_mtime_or_none(entry)
"""

_SYNTH_SHELL_POLICY_FOR_TARGET_AFTER = _SYNTH_IMPORTS + """
def consumer(entry, seq):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    for _NFO_MTIME_POLICY in seq:
        pass
    return nfo_mtime_or_none(entry)
"""

# ── Codex 三審 P1：不產生 ast.Name 的綁定形狀（名字存成 AST 欄位上的字串）──
# 這四種在「只數 ast.Name(Store/Del)」的規則下全部隱形，卻都真的改掉 runtime 綁定。

_SYNTH_SHELL_POLICY_IMPORT_ALIAS_AFTER = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    from os import sep as _NFO_MTIME_POLICY
    return nfo_mtime_or_none(entry)
"""

_SYNTH_SHELL_POLICY_EXCEPT_ALIAS_AFTER = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    try:
        pass
    except OSError as _NFO_MTIME_POLICY:
        pass
    return nfo_mtime_or_none(entry)
"""

_SYNTH_SHELL_POLICY_MATCH_CAPTURE_AFTER = _SYNTH_IMPORTS + """
def consumer(entry, subject):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    match subject:
        case _NFO_MTIME_POLICY:
            pass
    return nfo_mtime_or_none(entry)
"""

_SYNTH_SHELL_POLICY_NESTED_DEF_SHADOW_AFTER = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH

    def _NFO_MTIME_POLICY():
        return None

    return nfo_mtime_or_none(entry)
"""

# ── Codex 四審 P1：目標函式**自己簽名**上的參數（ast.arg，不在函式體節點裡）──
# `def consumer(..., nfo_mtime_or_none)` 會在 runtime 遮蔽 module 層的 import，
# 之後的呼叫根本不是 primitive，但委派計數仍依 module import 照算。
_SYNTH_SHELL_DELEGATE_AS_PARAM = _SYNTH_IMPORTS + """
def consumer(entry, nfo_mtime_or_none):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return nfo_mtime_or_none(entry)
"""

# 同一漏洞的 policy 側：policy 名當成參數傳進來 → 那個「宣告」根本不是就地宣告。
_SYNTH_SHELL_POLICY_AS_PARAM = _SYNTH_IMPORTS + """
def consumer(entry, _NFO_MTIME_POLICY):
    return nfo_mtime_or_none(entry)
"""

_SYNTH_SHELL_POLICY_AS_PARAM_PLUS_ASSIGN = _SYNTH_IMPORTS + """
def consumer(entry, _NFO_MTIME_POLICY):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return nfo_mtime_or_none(entry)
"""

# 對照組（反誤報）：**巢狀**函式的參數同名 —— 那是巢狀 scope 自己的綁定，
# 不得被算進目標函式，否則就是誤報（`_own_param_bindings` 只看自己的簽名）。
_SYNTH_SHELL_NESTED_PARAM_SAME_NAME = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH

    def inner(nfo_mtime_or_none, _NFO_MTIME_POLICY):
        return None

    return nfo_mtime_or_none(entry)
"""

# ── Codex 五審 P1：巢狀 scope 重新綁定委派名 + 在同一個 scope 內呼叫 ──
# 上一輪排除了「巢狀函式的參數」（正確），卻仍用全下鑽計算巢狀內的呼叫——
# 一邊排除一邊計入 = 假綠。scope-aware 之後這個呼叫不得算成委派（計數 0）。
_SYNTH_SHELL_NESTED_SHADOWED_CALL = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH

    def inner(nfo_mtime_or_none):
        return nfo_mtime_or_none(entry)

    return inner
"""

# 對照組：巢狀 scope **沒有**重新綁定 → 其內呼叫仍是合法委派（S1 的真實形狀，
# 委派就住在巢狀 scan_recursive 裡）。scope-aware 不得把這種正當情形也排掉。
_SYNTH_SHELL_NESTED_UNSHADOWED_CALL = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH

    def inner():
        return nfo_mtime_or_none(entry)

    return inner
"""

# 零宣告變體：函式體內完全沒有 _NFO_MTIME_POLICY 賦值，必須判定為
# status="none"（不是跟「不合法」混在一起的扁平 None）。
_SYNTH_SHELL_NO_POLICY = _SYNTH_IMPORTS + """
def consumer(entry):
    return nfo_mtime_or_none(entry)
"""

# local shadow 變體：同名常數/函式本地定義，不是從 core.nfo_stat import
# 進來——反假綠：import binding 解析必須擋掉這種「字面值恰好對上但來源錯」。
_SYNTH_SHELL_LOCAL_SHADOW = """
NFO_MTIME_REFRESH = "refresh"


def nfo_mtime_or_none(entry):
    return None


def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    return nfo_mtime_or_none(entry)
"""


def _counts_for_source(src: str, func_name: str = "consumer"):
    tree = ast.parse(src)
    func = _find_func(tree, func_name)
    assert func is not None, f"合成片段定位不到 {func_name}"
    bindings = _nfo_stat_bare_name_bindings(tree)
    nodes = _all_nodes(func)
    reads = len(_direct_mtime_read_nodes(nodes))
    delegates = len(_scoped_delegate_calls(func, bindings))
    policy = _policy_assignment(func, bindings)
    return reads, delegates, policy


class TestSyntheticCountFingerprints:
    """(a) 計數證偽：合成殼 parametrize，永久留在測試檔——比一次性記錄輸出更強，
    每次 CI 都持續驗證同一套計數判準邏輯，完全不碰產品碼。"""

    def test_minimal_shell_counts_zero_one(self):
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_MINIMAL)
        assert (reads, delegates) == (0, 1)

    def test_video_stat_shell_counts_one_one(self):
        """誤報檢查（技術要點第 6 節）：委派 + 影片檔 .st_mtime 兩者都在的殼，
        必須得到 (1, 1)——證明守衛不會把正當的影片檔 stat 誤判成違規。"""
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_WITH_VIDEO_STAT)
        assert (reads, delegates) == (1, 1)

    def test_extra_st_mtime_flips_read_count(self):
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_EXTRA_ST_MTIME)
        assert (reads, delegates) == (1, 1)  # extra .st_mtime + 既有委派

    def test_getmtime_bypass_is_counted_as_direct_read(self):
        """裁決 2 存在理由：os.path.getmtime(...) 繞過委派，仍必須被計進
        「直接讀取 mtime」桶，不能讓委派計數維持 1 就悄悄放過。"""
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_GETMTIME_BYPASS)
        assert reads == 1, "os.path.getmtime(...) 應被計入直接讀取 mtime"
        assert delegates == 0, "改寫成 getmtime 後不應再有委派呼叫"

    def test_st_mtime_ns_bypass_is_counted_as_direct_read(self):
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_ST_MTIME_NS_BYPASS)
        assert reads == 1, ".st_mtime_ns 應被計入直接讀取 mtime"
        assert delegates == 0

    def test_bare_getmtime_bypass_is_counted_as_direct_read(self):
        reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_BARE_GETMTIME_BYPASS)
        assert reads == 1, "裸名 getmtime(...) 應被計入直接讀取 mtime"
        assert delegates == 0


class TestSyntheticPolicyFingerprints:
    """(b) 常數字面證偽：合成殼 parametrize。"""

    def test_correct_policy_resolves(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_MINIMAL)
        status, _node, resolved = policy
        assert status == "ok"
        assert resolved == "NFO_MTIME_REFRESH"

    def test_wrong_policy_resolves_to_different_constant(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_WRONG_POLICY)
        status, _node, resolved = policy
        assert status == "ok"
        assert resolved == "NFO_MTIME_ON_UPSERT"
        assert resolved != "NFO_MTIME_REFRESH", (
            "常數字面被改掉後，解析結果必須與原本的 NFO_MTIME_REFRESH 不同"
            "（(b) 證偽的核心：字面值比對要能分辨差異）"
        )


class TestSyntheticPolicyUniquenessFingerprints:
    """(b) 唯一性證偽（P1 修正核心）：`_policy_assignment` 舊版只取函式體內第一個
    合法命中就 return，從不檢查是否還有第二個賦值——下列兩個危害情境在舊版
    (改前) 實測皆為全綠（詳見本次修正的回報記錄），本類把危害坐實成永久
    parametrize 案例，連同「零宣告」一起覆蓋 `_policy_assignment` 的三種紅燈
    分支（'multiple' ×2 + 'none' ×1），對照 `TestPolicyLiteralContract` 覆蓋的
    'ok' 分支，四種 status 全部都有測試鎖住。"""

    def test_conflicting_second_assignment_is_flagged_as_multiple(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_DUPLICATE_POLICY_CONFLICTING)
        status, node, resolved = policy
        assert status == "multiple", (
            "正確宣告後面再加一個衝突但個別合法的宣告，_policy_assignment 必須"
            f" 回報 status='multiple'（唯一性違規），實際 {status}"
        )
        assert resolved is None
        assert isinstance(node, list) and len(node) == 2, (
            f"status='multiple' 時 node 應為函式體內找到的全部 2 個"
            f" `_NFO_MTIME_POLICY = ...` 賦值節點，實際 {node}"
        )

    def test_illegal_rhs_second_assignment_is_flagged_as_multiple(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_DUPLICATE_POLICY_ILLEGAL_RHS)
        status, node, resolved = policy
        assert status == "multiple", (
            "正確宣告後面再加一個不合法 RHS（字面字串）宣告，_policy_assignment"
            f" 仍必須回報 status='multiple'（總賦值數 > 1 即違反唯一性契約，不論"
            f"第二個合不合法），實際 {status}"
        )
        assert resolved is None
        assert isinstance(node, list) and len(node) == 2

    def test_annassign_second_declaration_is_flagged_as_multiple(self):
        """Opus 二審補：第二個宣告寫成 `_NFO_MTIME_POLICY: str = ...`（AnnAssign）
        時，唯一性檢查若只收 ast.Assign 就會漏掉它、status 退回 'ok'——與 P1 同
        一家族的漏洞（『只看得到一種形狀』），一併鎖住。"""
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_DUPLICATE_POLICY_ANNASSIGN)
        status, node, resolved = policy
        assert status == "multiple", (
            "第二個宣告用帶型別標註的 AnnAssign 形式，_policy_assignment 仍必須"
            f" 回報 status='multiple'，實際 {status}"
        )
        assert resolved is None
        assert isinstance(node, list) and len(node) == 2

    @pytest.mark.parametrize("label, src", [
        # Codex 二審 P1 點名的兩種
        ("AugAssign（`+=` 就地改值）", _SYNTH_SHELL_POLICY_AUGASSIGN_AFTER),
        ("NamedExpr（海象 `:=` 重設）", _SYNTH_SHELL_POLICY_NAMEDEXPR_AFTER),
        # 同屬 ast.Name(Store) 家族、不在點名清單裡的形狀
        ("tuple 拆包重新綁定", _SYNTH_SHELL_POLICY_TUPLE_UNPACK_AFTER),
        ("for-target 重新綁定", _SYNTH_SHELL_POLICY_FOR_TARGET_AFTER),
        # Codex 三審 P1：**不產生 ast.Name** 的四種（名字是 AST 欄位上的字串）
        ("import 別名（alias.asname）", _SYNTH_SHELL_POLICY_IMPORT_ALIAS_AFTER),
        ("except 別名（ExceptHandler.name）", _SYNTH_SHELL_POLICY_EXCEPT_ALIAS_AFTER),
        ("match capture（MatchAs.name）", _SYNTH_SHELL_POLICY_MATCH_CAPTURE_AFTER),
        ("巢狀 def 同名遮蔽（FunctionDef.name）", _SYNTH_SHELL_POLICY_NESTED_DEF_SHADOW_AFTER),
    ])
    def test_rebinding_after_valid_declaration_is_flagged_as_multiple(self, label, src):
        """Codex 二審 P1：正確宣告**之後**再用其他形式改掉它的值，runtime 生效
        的是最後一次，宣告卻還寫著第一個常數——守衛必須紅。

        判準已從「列舉賦值語句型別」改成「數這個名字被綁定幾次」（Store/Del 情境
        的 ast.Name），因此後兩格（tuple 拆包 / for-target，**不在 Codex 點名清單
        內**）不需要各自新增分支就一起被擋住——這正是本次不再逐一列舉節點型別的
        理由：形狀列舉是輸不完的比賽。"""
        _reads, _delegates, policy = _counts_for_source(src)
        status, node, resolved = policy
        assert status == "multiple", (
            f"『正確宣告 + {label}』必須被判為 status='multiple'（該名字被綁定 "
            f"2 次），實際 {status}——守衛又只看得見其中一種形狀了"
        )
        assert resolved is None
        assert isinstance(node, list) and len(node) == 2, (
            f"status='multiple' 時 node 應為 2 個綁定節點，實際 {node}"
        )

    def test_policy_name_as_own_parameter_alone_is_not_a_valid_declaration(self):
        """Codex 四審 P1（policy 側）：policy 名當成參數傳進來，就不是「就地宣告」
        ——只有參數、沒有賦值時必須紅（status='illegal_rhs'，恰 1 個綁定但那個
        綁定不是合格的具名賦值）。"""
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_POLICY_AS_PARAM)
        status, _node, resolved = policy
        assert status == "illegal_rhs", (
            f"policy 名只以參數形式綁定時不得算合格宣告，實際 {status}"
        )
        assert resolved is None

    def test_policy_name_as_parameter_plus_assignment_is_multiple(self):
        """參數 + 函式內再賦值 ＝ 綁定 2 次 → 唯一性違規。"""
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_POLICY_AS_PARAM_PLUS_ASSIGN)
        status, node, resolved = policy
        assert status == "multiple", (
            f"policy 名同時是參數又被賦值時必須判為 multiple，實際 {status}"
        )
        assert resolved is None
        assert isinstance(node, list) and len(node) == 2

    def test_zero_assignments_is_flagged_as_none(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_NO_POLICY)
        status, node, resolved = policy
        assert status == "none", (
            f"函式體內完全沒有 _NFO_MTIME_POLICY 賦值，_policy_assignment 必須"
            f" 回報 status='none'，實際 {status}"
        )
        assert node is None and resolved is None


class TestImportBindingAntiShadow:
    """反假綠：local shadow（本地定義同名常數/函式，未從 core.nfo_stat
    import）不得被判定為合法委派/合法常數——擋掉「字面值恰好對上但來源錯」。"""

    def test_local_shadow_is_not_recognized_as_delegate_or_policy(self):
        reads, delegates, policy = _counts_for_source(_SYNTH_SHELL_LOCAL_SHADOW)
        assert delegates == 0, (
            "本地定義的同名 nfo_mtime_or_none（非從 core.nfo_stat import）"
            "不得被計為合法委派"
        )
        status, _node, resolved = policy
        assert status == "illegal_rhs", (
            "本地定義的同名 NFO_MTIME_REFRESH（非從 core.nfo_stat import）"
            f"不得被 _policy_assignment 判定為合法常數，預期 status='illegal_rhs'"
            f"（恰有 1 個賦值但 RHS 未解析自 core.nfo_stat），實際 {status}"
        )
        assert resolved is None
        assert reads == 0


# ============================================================
# 假綠檢查（DoD 獨立項）：六處只改一處、其餘五處維持委派 → 仍紅，逐格獨立
# ============================================================

class TestDelegateNameNotRebound:
    """委派計數那一側的同款漏洞（Opus 在 Codex 三審 P1 同一輪一併收掉）。

    `_nfo_stat_delegate_calls` 只靠 **module 最外層** 的 import binding 判定
    `nfo_mtime_or_none(...)` 是不是真的委派給 `core.nfo_stat`。但函式**內部**
    只要把這個名字重新綁定（`nfo_mtime_or_none = something_else`、
    `from x import y as nfo_mtime_or_none`、`except E as nfo_mtime_or_none`…
    ——與 policy 那側完全相同的形狀清單），後續呼叫的其實已經是別的東西，
    委派計數卻照算，六格照樣全綠。

    這裡用同一支 `_binding_nodes` 反向斷言：六個目標函式內**一次都不准**重新
    綁定委派名。（policy 那側要的是「恰好綁定 1 次」，這側要的是「0 次」——
    因為它的唯一合法來源是 module 層的 import。）
    """

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS)
    def test_delegate_name_never_rebound_in_function(self, label, py_file, func_name):
        func, _bindings = _target_ctx(py_file, func_name)
        rebinds = _all_bindings(func, "nfo_mtime_or_none")
        assert rebinds == [], (
            f"[{label}] {py_file.name}:{func_name}() 內把委派名 `nfo_mtime_or_none` "
            f"重新綁定了 {len(rebinds)} 次（行 "
            f"{[getattr(n, 'lineno', '?') for n in rebinds]}）——委派計數會把之後的"
            f"呼叫誤算成合法委派，實際呼叫的已經不是 core.nfo_stat 的 primitive"
        )

    def test_delegate_name_as_own_parameter_is_detected(self):
        """Codex 四審 P1：`def consumer(..., nfo_mtime_or_none)` 會遮蔽 module 層
        import，之後的呼叫不是 primitive，但委派計數照算。參數綁定不產生
        `ast.Name`（是 `ast.arg`），必須靠 `_own_param_bindings` 抓。"""
        func = _find_func(ast.parse(_SYNTH_SHELL_DELEGATE_AS_PARAM), "consumer")
        rebinds = _all_bindings(func, "nfo_mtime_or_none")
        assert len(rebinds) == 1, (
            f"委派名被當成目標函式自己的參數時必須被偵測到，實際 {rebinds}"
        )

    def test_nested_shadowed_scope_call_is_not_counted_as_delegation(self):
        """Codex 五審 P1：巢狀 scope 把委派名綁成自己的參數，**該 scope 內的呼叫
        就不是 primitive**。上一輪排除了參數卻仍計入呼叫（一邊排除一邊計入），
        委派格因此假綠。scope-aware 之後這裡必須是 0。"""
        _reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_NESTED_SHADOWED_CALL)
        assert delegates == 0, (
            f"巢狀 scope 已把 `nfo_mtime_or_none` 綁成參數，其內呼叫不得算成"
            f" core.nfo_stat 委派，實際計為 {delegates}"
        )

    def test_nested_unshadowed_scope_call_is_still_counted(self):
        """反誤報（本條的邊界，也是 S1 的真實形狀）：巢狀 scope **沒有**重新綁定
        時，其內呼叫仍是合法委派——實測 S1 的唯一委派就住在巢狀 `scan_recursive`
        裡，若 scope-aware 把巢狀一律排掉，S1 的期望值 1 會直接崩掉。"""
        _reads, delegates, _policy = _counts_for_source(_SYNTH_SHELL_NESTED_UNSHADOWED_CALL)
        assert delegates == 1, (
            f"巢狀 scope 未重新綁定時，其內呼叫仍應計為合法委派，實際 {delegates}"
        )

    def test_nested_function_parameter_is_not_counted(self):
        """反誤報（本條的邊界）：**巢狀**函式的同名參數屬於它自己的 scope，
        不得算成目標函式的綁定——這正是 `_own_param_bindings` 只看 `func_node`
        自己的 `.args`、不遞迴的理由。"""
        func = _find_func(ast.parse(_SYNTH_SHELL_NESTED_PARAM_SAME_NAME), "consumer")
        assert _all_bindings(func, "nfo_mtime_or_none") == [], (
            "巢狀函式的參數不得被算成目標函式重新綁定了委派名（誤報）"
        )
        status, _node, resolved = _policy_assignment(func, _nfo_stat_bare_name_bindings(
            ast.parse(_SYNTH_SHELL_NESTED_PARAM_SAME_NAME)))
        assert status == "ok" and resolved == "NFO_MTIME_REFRESH", (
            f"巢狀函式的同名參數不得影響 policy 判定，實際 status={status}"
        )

    def test_rebound_delegate_name_is_detected(self):
        """證偽：合法 import + 函式內重新綁定同名 → 必須偵測到（否則本測試是空殼）。"""
        src = _SYNTH_IMPORTS + """
def consumer(entry):
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    nfo_mtime_or_none = lambda *_a, **_k: 0.0
    return nfo_mtime_or_none(entry)
"""
        func = _find_func(ast.parse(src), "consumer")
        rebinds = _all_bindings(func, "nfo_mtime_or_none")
        assert len(rebinds) == 1, (
            f"函式內重新綁定委派名必須被 _binding_nodes 偵測到，實際 {rebinds}"
        )


class TestPerFunctionIndependence:
    """六個函式的計數與常數各自獨立，改動其中一個不影響其他五個——驗證方式：
    對每個真實函式各自跑一次完整計數/常數比對，全部應與 EXPECTED/
    EXPECTED_POLICY 相符（真檔演示章節在回報中逐次記錄實測紅燈輸出，這裡驗證
    的是「當下工作樹（乾淨狀態）六格應該全綠」，是真檔演示的基線對照）。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_clean_tree_all_six_green(self, label, py_file, func_name):
        expected_reads, expected_delegate = EXPECTED[(py_file, func_name)]
        expected_policy = EXPECTED_POLICY[(py_file, func_name)]
        func, bindings = _target_ctx(py_file, func_name)
        nodes = _all_nodes(func)
        reads = len(_direct_mtime_read_nodes(nodes))
        delegates = len(_scoped_delegate_calls(func, bindings))
        status, _node, resolved = _policy_assignment(func, bindings)
        assert (reads, delegates) == (expected_reads, expected_delegate), (
            f"[{label}] 乾淨工作樹基線應為 ({expected_reads}, {expected_delegate})"
            f"，實際 ({reads}, {delegates})"
        )
        assert status == "ok" and resolved == expected_policy, (
            f"[{label}] 乾淨工作樹基線政策常數應為 {expected_policy}"
            f"（status='ok'），實際 status={status} resolved={resolved}"
        )
