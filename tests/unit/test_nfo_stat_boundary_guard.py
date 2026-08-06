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


def _policy_assignment(nodes: list, bindings: dict):
    """回傳函式體內唯一一個 `_NFO_MTIME_POLICY = NFO_MTIME_*` 賦值節點，以及它
    解析到的原始常數名稱（"NFO_MTIME_REFRESH" 等）。找不到、或找到但 RHS 不是
    真正綁定到 core.nfo_stat 的名稱 → 回 None。"""
    for n in nodes:
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "_NFO_MTIME_POLICY"
            and isinstance(n.value, ast.Name)
        ):
            resolved = bindings.get(n.value.id)
            if resolved in POLICY_CONSTANT_NAMES:
                return n, resolved
    return None


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
        actual = len(_nfo_stat_delegate_calls(nodes, bindings))
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
        result = _policy_assignment(nodes, bindings)
        assert result is not None, (
            f"[{label}] {py_file.name}:{func_name}() 找不到合法的"
            f" `_NFO_MTIME_POLICY = NFO_MTIME_*` 賦值（解析自 core.nfo_stat）"
        )
        _node, resolved = result
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
    delegates = len(_nfo_stat_delegate_calls(nodes, bindings))
    policy = _policy_assignment(nodes, bindings)
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
        assert policy is not None
        _node, resolved = policy
        assert resolved == "NFO_MTIME_REFRESH"

    def test_wrong_policy_resolves_to_different_constant(self):
        _reads, _delegates, policy = _counts_for_source(_SYNTH_SHELL_WRONG_POLICY)
        assert policy is not None
        _node, resolved = policy
        assert resolved == "NFO_MTIME_ON_UPSERT"
        assert resolved != "NFO_MTIME_REFRESH", (
            "常數字面被改掉後，解析結果必須與原本的 NFO_MTIME_REFRESH 不同"
            "（(b) 證偽的核心：字面值比對要能分辨差異）"
        )


class TestImportBindingAntiShadow:
    """反假綠：local shadow（本地定義同名常數/函式，未從 core.nfo_stat
    import）不得被判定為合法委派/合法常數——擋掉「字面值恰好對上但來源錯」。"""

    def test_local_shadow_is_not_recognized_as_delegate_or_policy(self):
        reads, delegates, policy = _counts_for_source(_SYNTH_SHELL_LOCAL_SHADOW)
        assert delegates == 0, (
            "本地定義的同名 nfo_mtime_or_none（非從 core.nfo_stat import）"
            "不得被計為合法委派"
        )
        assert policy is None, (
            "本地定義的同名 NFO_MTIME_REFRESH（非從 core.nfo_stat import）"
            "不得被 _policy_assignment 判定為合法常數"
        )
        assert reads == 0


# ============================================================
# 假綠檢查（DoD 獨立項）：六處只改一處、其餘五處維持委派 → 仍紅，逐格獨立
# ============================================================

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
        delegates = len(_nfo_stat_delegate_calls(nodes, bindings))
        policy = _policy_assignment(nodes, bindings)
        assert (reads, delegates) == (expected_reads, expected_delegate), (
            f"[{label}] 乾淨工作樹基線應為 ({expected_reads}, {expected_delegate})"
            f"，實際 ({reads}, {delegates})"
        )
        assert policy is not None and policy[1] == expected_policy, (
            f"[{label}] 乾淨工作樹基線政策常數應為 {expected_policy}"
        )
