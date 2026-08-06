"""AST 邊界守衛：三個具名函式的 NFO 讀取委派契約（feature/113a T3，CD-113a-5）。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（跨三檔函式體委派契約）：
# 斷言 _nfo_to_meta / VideoScanner.parse_nfo / _nfo_to_producer_meta 三個函式體內
# 的八類 NFO 讀取必須委派 core.nfo_read，唯一例外是 B 的 findall('user_tag')。
# static_guard_lint 只能做字面字串比對，無法表達「某個具名函式體內的呼叫目標」
# 這種 AST 語意，故留 pytest。

守什麼：
  A = core.enricher._nfo_to_meta
  B = core.gallery_scanner.VideoScanner.parse_nfo（class method）
  C = core.readonly_producer._nfo_to_producer_meta

八類 NFO 讀取（actor / maker / release-date / tag-genre / series / runtime /
番號 / 簡單欄位）在 A/B/C 三個函式體內必須委派 `core.nfo_read` 的六支共用函式
（`nfo_text` / `nfo_first_text` / `nfo_actor_names` / `nfo_merged_tags` /
`nfo_series_name` / `nfo_runtime_minutes`），唯一允許的直接 ElementTree 讀取
是 B 的 `root.findall('user_tag')`（E3，引數必須逐字等於 `'user_tag'`）。

裸名 import 落差（本卡與 plan 原文的核心差異，見 TASK-113a-T3.md 技術要點第 1
節）：T2 落地後三個檔案全部是裸名呼叫（`nfo_text(root, ...)`）+ 模組最外層
`from core.nfo_read import nfo_text, ...`，不是 plan 初稿設想的
`nfo_read.nfo_text(...)` 帶前綴形式。本守衛因此不比對「呼叫語法長什麼樣
子」，而是解析 import binding：裸名呼叫必須真的從 `core.nfo_read` import
進來才算合法委派（`_resolves_to_nfo_read`）——這同時擋掉「consumer 檔案自己
定義一個同名 local shadow 函式騙過守衛」的漏洞：若 import 被拿掉、換成本地
定義，委派判定回傳 None，正向斷言會判定「委派缺失」而失敗，不會被同名字面
呼叫騙過。也一併支援 `nfo_read.nfo_text(...)` 帶前綴寫法（面向未來，現況三
檔皆未使用）。**這道防護有一個窄縫**（T3 review 實測）：若 import **仍在**、
但檔案後段又 `def` 一個同名函式覆蓋它（Python last-wins），AST 層看到 import
binding 就會判定為合法委派。該形狀由 `ruff` 的 `F811`（redefinition of unused）
獨立擋住且已全庫在 CI 執行，故此處不重複實作。

已知限制：把讀取搬到三個函式**之外**的新 helper（例如 `enricher.py` 新增一個
`_read_actors_v2()` 再從 `_nfo_to_meta` 呼叫它）會逃過本守衛——`_direct_nodes`
只掃三個具名函式的直接函式體，不追蹤跨函式呼叫鏈。這是刻意接受的缺口
（plan CD-113a-5 / §8 Q-2 已結案：需要一個刻意繞過的動作才會發生，不是無意
間寫出來的形狀），不在本卡修復範圍。

主要骨架仿 `tests/integration/test_enrich_contract_structure.py`
（`_parse`/`_tree`/`_find_func`/`_direct_nodes`/`_call_name`/import alias 解析
一組工具）；違規指紋 detector 風格（一個小 predicate 函式對應一種節點形狀）
亦仿同檔案的 `NEGATIVE_FINGERPRINTS` 段落。

為何 pytest 不是 lint（CLAUDE.md「Lint 守衛規則」north-star）：本守衛驗的是
「某個 Python 函式的源碼語意（AST 節點形狀 / import binding）」，CLAUDE.md
判斷原則明列此類走 pytest（C 類）；`static_guard_lint`/eslint/stylelint 完全
不處理 `.py` 檔案，機械上無法承接。
"""
import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
ENRICHER_PY = REPO_ROOT / "core" / "enricher.py"
GALLERY_SCANNER_PY = REPO_ROOT / "core" / "gallery_scanner.py"
READONLY_PRODUCER_PY = REPO_ROOT / "core" / "readonly_producer.py"
NFO_UPDATER_PY = REPO_ROOT / "core" / "nfo_updater.py"


# ============================================================
# AST 工具（比照 test_enrich_contract_structure.py 骨架）
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
    """全樹遍歷找 node.name == name 的 FunctionDef/AsyncFunctionDef。

    `ast.walk` 會下潛進 `ClassDef.body`，天然涵蓋 class method（B 是
    `VideoScanner.parse_nfo`），不需要為此寫特殊邏輯。找不到回 None（白名單
    防腐用，呼叫端必須明確失敗並指名，不可靜默 skip）。
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _direct_nodes(func_node) -> list:
    """收集 func_node「直接 body」的所有子節點（遞迴，但**停在巢狀 def**）。"""
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
# import binding 解析（技術要點第 1 節）：裸名呼叫是否真的從
# core.nfo_read import 進來，防同名 local shadow 函式騙過守衛
# ============================================================

NFO_READ_FUNCS = {
    "nfo_text", "nfo_first_text", "nfo_actor_names",
    "nfo_merged_tags", "nfo_series_name", "nfo_runtime_minutes",
}


def _nfo_read_bare_name_bindings(tree: ast.Module) -> dict:
    """本檔案模組最外層 `from core.nfo_read import X [as Y]` 的
    {本地名稱: 原始名稱}，僅收原始名稱在 NFO_READ_FUNCS 內的項目。"""
    bindings = {}
    for node in _module_level_import_froms(tree):
        if node.module != "core.nfo_read":
            continue
        for alias in node.names:
            if alias.name in NFO_READ_FUNCS:
                bindings[alias.asname or alias.name] = alias.name
    return bindings


def _nfo_read_module_aliases(tree: ast.Module) -> set:
    """本檔案模組最外層 `import core.nfo_read [as Y]` 的模組別名集合
    （面向未來：支援 `nfo_read.nfo_text(...)` 這種帶前綴寫法）。"""
    aliases = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "core.nfo_read":
                    aliases.add(alias.asname or "core")
    return aliases


def _resolves_to_nfo_read(call: ast.Call, bare_bindings: dict, module_aliases: set):
    """回傳這個 Call 真正對應的 nfo_read 原始函式名，或 None（不是合法委派）。"""
    fn = call.func
    if isinstance(fn, ast.Name):
        return bare_bindings.get(fn.id)
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        if fn.value.id in module_aliases and fn.attr in NFO_READ_FUNCS:
            return fn.attr
    return None


def _find_calls(func_node, bare_bindings: dict, module_aliases: set, target_name: str) -> list:
    """回傳函式體內所有真正解析到 target_name（nfo_read 原始函式名）的 Call 節點。"""
    return [
        n for n in _direct_nodes(func_node)
        if isinstance(n, ast.Call)
        and _resolves_to_nfo_read(n, bare_bindings, module_aliases) == target_name
    ]


def _all_nfo_read_calls(func_node, bare_bindings: dict, module_aliases: set) -> list:
    return [
        n for n in _direct_nodes(func_node)
        if isinstance(n, ast.Call)
        and _resolves_to_nfo_read(n, bare_bindings, module_aliases) is not None
    ]


def _literal_str_args(call: ast.Call) -> list:
    """call 的位置引數裡，凡是 ast.Constant(str) 就取值；tuple/list 引數展開
    內層字面。"""
    out = []
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            out.append(a.value)
        elif isinstance(a, (ast.Tuple, ast.List)):
            out.extend(e.value for e in a.elts if isinstance(e, ast.Constant))
    return out


# ============================================================
# 違規判準（負向掃描）：函式體內任何直接 ET 讀取原語
# ============================================================

FORBIDDEN_ET_ATTRS = {"find", "findall", "iterfind", "iter"}


def _is_direct_et_read(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in FORBIDDEN_ET_ATTRS
    )


def _is_e3(node: ast.AST, func_name: str) -> bool:
    """唯一例外：B `parse_nfo` 的 `root.findall('user_tag')`。引數必須逐字
    等於字串 'user_tag'，函式必須是 parse_nfo，方法必須是 findall。"""
    if func_name != "parse_nfo":
        return False
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "findall"):
        return False
    if len(node.args) != 1:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Constant) and arg.value == "user_tag"


def _all_et_primitive_calls(func_node) -> list:
    """所有直接 ET 讀取原語呼叫（**不排除** E3），供「盤點對帳」用。"""
    return [n for n in _direct_nodes(func_node) if _is_direct_et_read(n)]


def _violations(func_node, func_name: str) -> list:
    """排除 E3 之後的違規清單——判準不依賴 _resolves_to_nfo_read，
    find/findall/iterfind/iter 這四個 attr 名稱本來就不在 NFO_READ_FUNCS 裡，
    白名單結構因此天然 fail-closed（CD-113a-5）。"""
    return [n for n in _all_et_primitive_calls(func_node) if not _is_e3(n, func_name)]


def _violation_report(source_text: str, violations: list) -> str:
    lines = []
    for n in violations:
        seg = ast.get_source_segment(source_text, n) or "<no source segment>"
        lines.append(f"  line {n.lineno}: {seg}")
    return "\n".join(lines)


# ============================================================
# 真檔 target 清單（A/B/C）
# ============================================================

# (標籤, 檔案, 函式名)
REAL_TARGETS = [
    ("A", ENRICHER_PY, "_nfo_to_meta"),
    ("B", GALLERY_SCANNER_PY, "parse_nfo"),
    ("C", READONLY_PRODUCER_PY, "_nfo_to_producer_meta"),
]

# 反假綠斷言（裁決 2，硬條件）：每個函式體內 nfo_read 委派呼叫數量下限
# ——HEAD 現況實測（見 TASK-113a-T3.md「現況分析」表逐行核對）：
#   A `_nfo_to_meta`：11 筆（nfo_text x5, nfo_first_text x2, nfo_actor_names x1,
#     nfo_series_name x1, nfo_merged_tags x1, nfo_runtime_minutes x1）
#   B `parse_nfo`：12 筆（nfo_text x5, nfo_first_text x3, nfo_actor_names x1,
#     nfo_merged_tags x1, nfo_series_name x1, nfo_runtime_minutes x1）
#   C `_nfo_to_producer_meta`：14 筆（nfo_text x7, nfo_first_text x3,
#     nfo_actor_names x1, nfo_merged_tags x1, nfo_series_name x1,
#     nfo_runtime_minutes x1）
MIN_NFO_READ_DELEGATIONS = {
    "A": 11,
    "B": 12,
    "C": 14,
}

# 八類正向斷言表（技術要點第 3 節）
SINGLE_CALL_CATEGORIES = {
    # 類別: nfo_read 原始函式名
    "actor": "nfo_actor_names",
    "tag_genre": "nfo_merged_tags",
    "series": "nfo_series_name",
    "runtime": "nfo_runtime_minutes",
}

TUPLE_CATEGORIES = {
    "maker": ("nfo_first_text", ("maker", "studio")),
    "release_date": ("nfo_first_text", ("release", "premiered", "year")),
}

# 番號類：nfo_first_text，A 不提取（N/A）
NUM_EXPECTED = {
    "A": None,
    "B": ("num", "id"),
    "C": ("num", "id", "uniqueid"),
}

# 簡單欄位類：nfo_text，字面 tag 集合（== 整個集合，不是子集比對）
SIMPLE_FIELDS_EXPECTED = {
    "A": {"title", "originaltitle", "director", "label", "website"},
    "B": {"title", "originaltitle", "director", "label", "thumb"},
    "C": {"title", "originaltitle", "director", "label", "website", "plot", "rating"},
}


def _target_ctx(py_file: pathlib.Path, func_name: str):
    tree = _tree(py_file)
    func = _find_func(tree, func_name)
    assert func is not None, (
        f"{py_file.name}:{func_name} 定位不到（白名單防腐應先報，改名或誤刪？）"
    )
    bare = _nfo_read_bare_name_bindings(tree)
    aliases = _nfo_read_module_aliases(tree)
    return func, bare, aliases


# ============================================================
# 白名單防腐：三個具名函式必須都能定位到（裁決 2 硬條件之一）
# ============================================================

class TestWhitelistAntiRot:
    """三個具名 target 必須能在對應檔 AST 定位，否則守衛指向殭屍函式、
    恆綠假通過。找不到必須明確失敗並指名是哪一個。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_target_function_exists(self, label, py_file, func_name):
        tree = _tree(py_file)
        func = _find_func(tree, func_name)
        assert func is not None, (
            f"[{label}] {py_file.name}:{func_name} 指向不存在的函式（改名？）"
            f" —— 守衛失去意義，須更新清單或修復函式名"
        )


# ============================================================
# 反假綠斷言（裁決 2，硬條件）：委派呼叫數量下限 + E3 恰好等於 1
# ============================================================

class TestAntiFalseGreenFloor:
    """守衛必須先斷言「我真的找到了東西」，再斷言「找到的東西沒有違規」。
    什麼都沒掃到也算通過，是掃描型守衛的假綠同構失效模式（spec AC6 實作
    提醒 / PR#125 round-3 P2 同一形狀）。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_delegation_count_meets_named_floor(self, label, py_file, func_name):
        func, bare, aliases = _target_ctx(py_file, func_name)
        count = len(_all_nfo_read_calls(func, bare, aliases))
        floor = MIN_NFO_READ_DELEGATIONS[label]
        assert count >= floor, (
            f"[{label}] {py_file.name}:{func_name}() 只掃到 {count} 筆 nfo_read"
            f" 委派呼叫，低於具名下限 {floor}——疑似 import binding 解析失效或"
            f" 委派被大量拔除，守衛本身可能正在假綠"
        )

    def test_e3_count_is_exactly_one(self):
        """E3（B 的 root.findall('user_tag')）必須恰好等於 1，不是 ≥1——
        多一處 user_tag 直接讀取也要紅。"""
        func, _bare, _aliases = _target_ctx(GALLERY_SCANNER_PY, "parse_nfo")
        e3_hits = [n for n in _all_et_primitive_calls(func) if _is_e3(n, "parse_nfo")]
        assert len(e3_hits) == 1, (
            f"E3（root.findall('user_tag')）計數應恰好等於 1，實際 {len(e3_hits)}"
            f" —— 行號: {[n.lineno for n in e3_hits]}"
        )


# ============================================================
# 盤點對帳（DoD）：三個函式體內直接 ET 讀取合計恰好一處（E3）
# ============================================================

class TestInventoryReconciliation:
    def test_total_direct_et_reads_is_exactly_e3(self):
        total = []
        for label, py_file, func_name in REAL_TARGETS:
            func, _bare, _aliases = _target_ctx(py_file, func_name)
            total.extend((label, n) for n in _all_et_primitive_calls(func))
        assert len(total) == 1, (
            f"A/B/C 三函式體內直接 ET 讀取（find/findall/iterfind/iter）合計應"
            f" 恰好 1 處（E3），實際 {len(total)}: "
            f"{[(label, n.lineno) for label, n in total]}"
        )
        label, node = total[0]
        assert label == "B" and _is_e3(node, "parse_nfo"), (
            f"唯一的直接 ET 讀取應是 B 的 E3（root.findall('user_tag')），"
            f"實際落在 [{label}] line {node.lineno}"
        )

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_no_violations_after_e3_exclusion(self, label, py_file, func_name):
        source_text = py_file.read_text(encoding="utf-8")
        func, _bare, _aliases = _target_ctx(py_file, func_name)
        violations = _violations(func, func_name)
        assert not violations, (
            f"[{label}] {py_file.name}:{func_name}() 殘留直接 ET 讀取:\n"
            f"{_violation_report(source_text, violations)}"
        )


# ============================================================
# 八類正向斷言（引數字面內容，裁決 3）
# ============================================================

class TestPositiveDelegationContract:
    """逐類比對呼叫目標與引數字面內容——只驗「有沒有呼叫」抓不到
    「換成別支 nfo_read 函式」或「tag 鏈內容被偷改」這種 mutation。"""

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    @pytest.mark.parametrize("category, target_func", SINGLE_CALL_CATEGORIES.items(),
                             ids=list(SINGLE_CALL_CATEGORIES.keys()))
    def test_single_call_categories(self, category, target_func, label, py_file, func_name):
        func, bare, aliases = _target_ctx(py_file, func_name)
        calls = _find_calls(func, bare, aliases, target_func)
        assert len(calls) == 1, (
            f"[{label}/{category}] {py_file.name}:{func_name}() 應恰有一筆對"
            f" {target_func} 的委派呼叫，實際 {len(calls)} 筆"
        )

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    @pytest.mark.parametrize("category, spec", TUPLE_CATEGORIES.items(),
                             ids=list(TUPLE_CATEGORIES.keys()))
    def test_tuple_literal_categories(self, category, spec, label, py_file, func_name):
        target_func, expected = spec
        func, bare, aliases = _target_ctx(py_file, func_name)
        calls = _find_calls(func, bare, aliases, target_func)
        matches = [c for c in calls if _literal_str_args(c) == list(expected)]
        assert len(matches) == 1, (
            f"[{label}/{category}] {py_file.name}:{func_name}() 應恰有一筆"
            f" {target_func}{expected} 委派呼叫，實際命中 {len(matches)} 筆"
            f"（候選呼叫引數: {[_literal_str_args(c) for c in calls]}）"
        )

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_num_category(self, label, py_file, func_name):
        expected = NUM_EXPECTED[label]
        func, bare, aliases = _target_ctx(py_file, func_name)
        calls = _find_calls(func, bare, aliases, "nfo_first_text")
        if expected is None:
            # A 不提取番號（N/A，非缺口）——不斷言存在，但不得意外命中
            return
        matches = [c for c in calls if _literal_str_args(c) == list(expected)]
        assert len(matches) == 1, (
            f"[{label}/num] {py_file.name}:{func_name}() 應恰有一筆"
            f" nfo_first_text{expected} 委派呼叫，實際命中 {len(matches)} 筆"
            f"（候選呼叫引數: {[_literal_str_args(c) for c in calls]}）"
        )

    @pytest.mark.parametrize("label, py_file, func_name", REAL_TARGETS,
                             ids=[t[0] for t in REAL_TARGETS])
    def test_simple_fields_category(self, label, py_file, func_name):
        expected = SIMPLE_FIELDS_EXPECTED[label]
        func, bare, aliases = _target_ctx(py_file, func_name)
        calls = _find_calls(func, bare, aliases, "nfo_text")
        fields = set()
        for c in calls:
            args = _literal_str_args(c)
            assert len(args) == 1, (
                f"[{label}/簡單欄位] {py_file.name}:{func_name}() 的 nfo_text"
                f" 呼叫 line {c.lineno} 應恰有一個字面字串引數，實際 {args}"
            )
            fields.add(args[0])
        assert fields == expected, (
            f"[{label}/簡單欄位] {py_file.name}:{func_name}() 的 nfo_text 字面"
            f" tag 集合應等於 {sorted(expected)}，實際 {sorted(fields)}"
            f"（差集 missing={sorted(expected - fields)} extra={sorted(fields - expected)}）"
        )


# ============================================================
# 誤報檢查（技術要點第 6 節）
# ============================================================

class TestFalsePositiveGuards:
    def test_nfo_updater_helpers_exist_but_not_scanned(self):
        """nfo_updater.py::add_actor / add_tags_and_genres 存在，但本檔案掃描
        範圍白名單只有 A/B/C 三個具名 target，結構上不可能觸及它們。"""
        tree = _tree(NFO_UPDATER_PY)
        add_actor = _find_func(tree, "add_actor")
        add_tags = _find_func(tree, "add_tags_and_genres")
        assert add_actor is not None, "core.nfo_updater.add_actor 應存在"
        assert add_tags is not None, "core.nfo_updater.add_tags_and_genres 應存在"
        scanned_names = {func_name for _label, _py_file, func_name in REAL_TARGETS}
        assert "add_actor" not in scanned_names
        assert "add_tags_and_genres" not in scanned_names

    def test_readonly_producer_out_of_scope_function_not_in_targets(self):
        """resolve_ingest_plan 存在於 readonly_producer.py，但不在本檔案的
        掃描清單常數（REAL_TARGETS）裡。"""
        tree = _tree(READONLY_PRODUCER_PY)
        func = _find_func(tree, "resolve_ingest_plan")
        assert func is not None, "core.readonly_producer.resolve_ingest_plan 應存在"
        scanned_names = {func_name for _label, py_file, func_name in REAL_TARGETS
                          if py_file == READONLY_PRODUCER_PY}
        assert "resolve_ingest_plan" not in scanned_names

    def test_nfo_updater_parse_nfo_does_not_collide_with_gallery_scanner(self):
        """core.nfo_updater.parse_nfo 與 core.gallery_scanner.VideoScanner.parse_nfo
        同名但不同檔案——各自 parse 各自的 AST tree，B 的定位不會誤中此函式。"""
        updater_func = _find_func(_tree(NFO_UPDATER_PY), "parse_nfo")
        assert updater_func is not None
        assert updater_func.lineno == 162  # nfo_updater.py 的簽名純位置參數版本
        scanner_func = _find_func(_tree(GALLERY_SCANNER_PY), "parse_nfo")
        assert scanner_func is not None
        assert scanner_func.lineno != updater_func.lineno


# ============================================================
# 合成 source 片段：八類 parametrize 紅/綠對照（技術要點第 5 節，裁決 1）
# ============================================================

_SYNTH_IMPORTS = """
from core.nfo_read import (
    nfo_actor_names,
    nfo_first_text,
    nfo_merged_tags,
    nfo_runtime_minutes,
    nfo_series_name,
    nfo_text,
)
"""

# 八類各一組（代表函式在 A/B/C 間輪替，確保三個檔名都至少被驗過一次，
# 也確保 class-method 定位方式在合成測試裡也被走過一次——round 1）
SYNTHETIC_ROUNDS = [
    (
        "actor", "parse_nfo",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.actor = ','.join(nfo_actor_names(root))
        return info
""",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.actor = ','.join(n.text.strip() for n in root.findall('.//actor/name') if n.text)
        return info
""",
    ),
    (
        "maker", "_nfo_to_meta",
        _SYNTH_IMPORTS + """
def _nfo_to_meta(root):
    return {
        "maker": nfo_first_text(root, ("maker", "studio")),
    }
""",
        _SYNTH_IMPORTS + """
def _nfo_to_meta(root):
    return {
        "maker": (root.find("maker").text or "").strip() if root.find("maker") is not None else "",
    }
""",
    ),
    (
        "release_date", "_nfo_to_producer_meta",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'date': nfo_first_text(root, ('release', 'premiered', 'year')),
    }
""",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'date': (root.find('release').text or "").strip() if root.find('release') is not None else "",
    }
""",
    ),
    (
        "tag_genre", "parse_nfo",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.genre = ','.join(nfo_merged_tags(root))
        return info
""",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.genre = ','.join(g.text.strip() for g in root.findall('genre') if g.text)
        return info
""",
    ),
    (
        "series", "_nfo_to_meta",
        _SYNTH_IMPORTS + """
def _nfo_to_meta(root):
    return {
        "series": nfo_series_name(root),
    }
""",
        _SYNTH_IMPORTS + """
def _nfo_to_meta(root):
    return {
        "series": (root.find('set/name').text or "").strip() if root.find('set/name') is not None else "",
    }
""",
    ),
    (
        "runtime", "_nfo_to_producer_meta",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'duration': nfo_runtime_minutes(root),
    }
""",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'duration': int(root.find('runtime').text) if root.find('runtime') is not None else None,
    }
""",
    ),
    (
        "num", "parse_nfo",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.num = nfo_first_text(root, ('num', 'id'))
        return info
""",
        _SYNTH_IMPORTS + """
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
        info.num = (root.find('num').text or "").strip() if root.find('num') is not None else ""
        return info
""",
    ),
    (
        "simple_fields", "_nfo_to_producer_meta",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'title': nfo_text(root, 'title'),
    }
""",
        _SYNTH_IMPORTS + """
def _nfo_to_producer_meta(root):
    return {
        'title': (root.find('title').text or "").strip() if root.find('title') is not None else "",
    }
""",
    ),
]


class TestSyntheticRedGreenPairs:
    """八類各一組合成片段（紅／綠對照），永久留在測試檔的 parametrize case
    ——比「跑一次記錄輸出後只剩文字紀錄」更強：每次 CI 都持續驗證同一段違規
    判準邏輯，且完全不碰產品碼。"""

    @pytest.mark.parametrize("category, func_name, green_src, red_src", SYNTHETIC_ROUNDS,
                             ids=[r[0] for r in SYNTHETIC_ROUNDS])
    def test_green_has_zero_violations(self, category, func_name, green_src, red_src):
        tree = ast.parse(green_src)
        func = _find_func(tree, func_name)
        assert func is not None, f"[{category}] 綠版合成片段定位不到 {func_name}"
        violations = _violations(func, func_name)
        assert not violations, (
            f"[{category}] 綠版合成片段（委派寫法）不應有違規:\n"
            f"{_violation_report(green_src, violations)}"
        )

    @pytest.mark.parametrize("category, func_name, green_src, red_src", SYNTHETIC_ROUNDS,
                             ids=[r[0] for r in SYNTHETIC_ROUNDS])
    def test_red_has_violations(self, category, func_name, green_src, red_src):
        tree = ast.parse(red_src)
        func = _find_func(tree, func_name)
        assert func is not None, f"[{category}] 紅版合成片段定位不到 {func_name}"
        violations = _violations(func, func_name)
        assert violations, (
            f"[{category}] 紅版合成片段（手寫 ET 讀取）應被判為違規，實際 0 筆"
            f" —— 守衛假綠"
        )
        # 違規報告必須含行號與內容，可直接定位問題行
        report = _violation_report(red_src, violations)
        assert violations[0].lineno > 0
        assert report.strip()


# ============================================================
# 假綠檢查（DoD 獨立項，PR#125 round-3 教訓）：同函式只換回一類，
# 其餘七類維持委派 → 守衛仍紅，且恰指向那一類
# ============================================================

# B 天生涵蓋八類（含 E3），用它的殼做「全綠 + 單類轉紅」組合。
# 紅版刻意寫成「先 root.find(...) 存一個變數，再判斷/取值」的單一 find-call
# 形狀（而非 SYNTHETIC_ROUNDS 表列的三元運算式兩次呼叫 root.find 寫法）——
# 這裡需要「恰好一筆違規」的精確計數，兩次呼叫會讓同一類自己就衝到 2 筆，
# 掩蓋「只換一類、其餘七類仍委派」這個假綠檢查真正要驗的東西。
_FULL_PARSE_NFO_LINES = {
    "actor": (
        ["info.actor = ','.join(nfo_actor_names(root))"],
        ["info.actor = ','.join(n.text.strip() for n in root.findall('.//actor/name') if n.text)"],
    ),
    "maker": (
        ["info.maker = nfo_first_text(root, ('maker', 'studio'))"],
        ["_maker_el = root.find('maker')",
         "info.maker = (_maker_el.text or '').strip() if _maker_el is not None else ''"],
    ),
    "release_date": (
        ["info.date = nfo_first_text(root, ('release', 'premiered', 'year'))"],
        ["_release_el = root.find('release')",
         "info.date = (_release_el.text or '').strip() if _release_el is not None else ''"],
    ),
    "tag_genre": (
        ["info.genre = ','.join(nfo_merged_tags(root))"],
        ["info.genre = ','.join(g.text.strip() for g in root.findall('genre') if g.text)"],
    ),
    "series": (
        ["info.series = nfo_series_name(root)"],
        ["_series_el = root.find('set/name')",
         "info.series = (_series_el.text or '').strip() if _series_el is not None else ''"],
    ),
    "runtime": (
        ["info.duration = nfo_runtime_minutes(root)"],
        ["_runtime_el = root.find('runtime')",
         "info.duration = int(_runtime_el.text) if _runtime_el is not None else None"],
    ),
    "num": (
        ["info.num = nfo_first_text(root, ('num', 'id'))"],
        ["_num_el = root.find('num')",
         "info.num = (_num_el.text or '').strip() if _num_el is not None else ''"],
    ),
    "simple_fields": (
        ["info.title = nfo_text(root, 'title')"],
        ["_title_el = root.find('title')",
         "info.title = (_title_el.text or '').strip() if _title_el is not None else ''"],
    ),
}


def _build_full_parse_nfo(red_category: str = None, e3_tag: str = "user_tag") -> str:
    """組出涵蓋全部八類 + E3 的合成 `parse_nfo` 殼。`red_category` 給定時，
    該類換成手寫紅版，其餘七類維持委派版；`e3_tag` 覆蓋 E3 的字面引數，
    用於白名單精確度 mutation。"""
    lines = []
    for category, (green_lines, red_lines) in _FULL_PARSE_NFO_LINES.items():
        lines.extend(red_lines if category == red_category else green_lines)
    e3_line = f"info.user_tags = [t.text.strip() for t in root.findall('{e3_tag}') if t.text]"
    lines.append(e3_line)
    body = "\n".join(f"        {line}" for line in lines)
    return _SYNTH_IMPORTS + f"""
class _Info:
    pass


class VideoScanner:
    def parse_nfo(self, root):
        info = _Info()
{body}
        return info
"""


class TestFalseGreenCheck:
    """全綠殼先確認 0 違規，再逐類單獨轉紅，確認每次都恰有一筆違規且指向
    正確的那一行——證明守衛不是「這個函式有沒有委派過任何東西」的存在性
    檢查。"""

    def test_full_delegation_shell_is_zero_violations(self):
        tree = ast.parse(_build_full_parse_nfo())
        func = _find_func(tree, "parse_nfo")
        assert func is not None
        violations = _violations(func, "parse_nfo")
        assert not violations, (
            f"全委派殼（八類 + E3 皆合法）不應有違規:\n"
            f"{_violation_report(_build_full_parse_nfo(), violations)}"
        )

    @pytest.mark.parametrize("category", list(_FULL_PARSE_NFO_LINES.keys()))
    def test_single_category_flip_is_exactly_one_violation(self, category):
        src = _build_full_parse_nfo(red_category=category)
        tree = ast.parse(src)
        func = _find_func(tree, "parse_nfo")
        assert func is not None
        violations = _violations(func, "parse_nfo")
        assert len(violations) == 1, (
            f"[{category}] 只換回一類、其餘七類維持委派，應恰有一筆違規，"
            f"實際 {len(violations)}:\n{_violation_report(src, violations)}"
        )
        red_text = "\n".join(_FULL_PARSE_NFO_LINES[category][1])
        seg = ast.get_source_segment(src, violations[0])
        assert seg and seg in red_text, (
            f"[{category}] 違規應指向該類手寫紅版的呼叫，實際指向: {seg!r}"
            f"（紅版原文: {red_text!r}）"
        )


# ============================================================
# 白名單精確度 mutation（DoD 獨立項）：E3 的 'user_tag' 換成其他字面
# ============================================================

class TestWhitelistPrecisionMutation:
    def test_e3_wrong_literal_is_flagged(self):
        src = _build_full_parse_nfo(e3_tag="genre")
        tree = ast.parse(src)
        func = _find_func(tree, "parse_nfo")
        assert func is not None
        violations = _violations(func, "parse_nfo")
        assert len(violations) == 1, (
            f"E3 的 'user_tag' 換成 'genre' 後應恰有一筆違規，實際 "
            f"{len(violations)}:\n{_violation_report(src, violations)}"
        )
        seg = ast.get_source_segment(src, violations[0])
        assert "findall('genre')" in (seg or ""), (
            f"違規應指向 root.findall('genre') 那一行，實際: {seg}"
        )

    def test_e3_correct_literal_is_not_flagged(self):
        src = _build_full_parse_nfo(e3_tag="user_tag")
        tree = ast.parse(src)
        func = _find_func(tree, "parse_nfo")
        assert func is not None
        violations = _violations(func, "parse_nfo")
        assert not violations, (
            f"E3 引數為正確字面 'user_tag' 時不應有違規:\n"
            f"{_violation_report(src, violations)}"
        )
