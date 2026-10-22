"""唯讀/非唯讀第②層「寫後記帳+回報」收斂終態的跨檔 AST 結構守衛（feature/105 T7，
v0.13 TASK-109-T6 翻面）。

[pytest-justified: cross-file Python AST contract, feature/91/66 先例]

把「一份實作」最終狀態用機械閘鎖死，防止未來一長新欄位就再手抄一份拷貝
（PR#113 八輪 churn 的根因）。TASK-109（T2/T3）把單片／batch 唯讀分支的第②層
邏輯收斂進 `core.readonly_producer.enrich_one_readonly` 公開入口後，本檔的鎖
跟著翻面——鎖的是「呼叫方走公開入口」而非「兩份拷貝各自手抄同一組 helper」：

  1. **正向鎖**（`POSITIVE_LOCKS`）：對明列的 production target 函式
     （P1–P6、P8），斷言其 named FunctionDef body 內含對應 helper / 公開入口
     的 `ast.Call`。P4（`enrich_single_endpoint`）/P6（`_do_readonly`）鎖的是
     單一入口 `enrich_one_readonly`；P8 鎖該入口自身必須呼叫五支收斂後的
     共用 helper（原 P4/P6/P7 的目的搬家至此，不是消失）。
  2. **負向鎖**：
     a. `TestNegativeMirrorLocks`：對 `NEGATIVE_SCAN_TARGETS`（與
        `POSITIVE_LOCKS` 解耦的自有清單，CD-109-9）逐一斷言四類舊 mirror
        手抄指紋不復生。
     b. `TestNegativeForbiddenPrimitiveCalls`：`enrich_single_endpoint` /
        `_do_readonly` 的 body 不得直接呼叫已收斂進 `enrich_one_readonly`
        的私有 primitive——先解析 import alias binding（module-level ∪
        target 函式自身含巢狀 scope 的 `ast.ImportFrom`）再掃 `ast.Call`，
        防止 function-local `import … as x` 繞過（CD-109-4/10）。
  3. **白名單防腐**：每個 named target 必須能 AST 定位，避免改名後恆綠假通過。

掃描粒度＝named `FunctionDef`/`AsyncFunctionDef` 的「直接 body」（遞迴但**停在
巢狀 def**，比照先例 `test_async_offload_guard.py::_collect_direct_calls`）：
`event_generator` 收集 Call 時停在 nested `_do_readonly`，兩者的直接呼叫集合
互不污染。

為何 pytest 不是 lint（CLAUDE.md「Lint 守衛規則」north-star）：本守衛驗的是
「某個 Python 函式的源碼語意（AST 節點形狀 / import binding）」——CLAUDE.md
判斷原則明列此類走 pytest（C 類）。它 walk named FunctionDef 的
`ast.Call`/`ast.Assign`/`ast.BoolOp`/`ast.ImportFrom` 節點形狀，非
`"name" in source` 字面掃描，故 eslint/static_guard 無法表達、亦不觸
SA-pre-6 的 html/js/css content-based 偵測。
"""
import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
ENRICHER_PY = REPO_ROOT / "core" / "enricher.py"
SCRAPER_PY = REPO_ROOT / "web" / "routers" / "scraper.py"
READONLY_PRODUCER_PY = REPO_ROOT / "core" / "readonly_producer.py"


# ============================================================
# AST 工具（比照 test_async_offload_guard.py 骨架）
# ============================================================

def _parse(py_file: pathlib.Path) -> ast.Module:
    return ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))


def _find_func(tree: ast.Module, name: str):
    """全樹遍歷找 node.name == name 的 FunctionDef/AsyncFunctionDef（名稱檔內唯一）。

    涵蓋雙層巢狀（`event_generator` in `batch_enrich_endpoint`；`_do_readonly` in
    `event_generator`）——`ast.walk` 遞迴命中即可。找不到回 None（白名單防腐用）。
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _direct_nodes(func_node) -> list:
    """收集 func_node「直接 body」的所有子節點（遞迴，但**停在巢狀 def**）。

    停在 nested `FunctionDef`/`AsyncFunctionDef`：故 `event_generator` 的收集不會
    下潛到 `_do_readonly`，兩者各自獨立掃描、集合互不污染（比照先例
    `_collect_direct_calls`「遇 nested def 就 continue 不下潛」）。
    """
    out = []

    def _walk(nodes):
        for node in nodes:
            out.append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _walk(ast.iter_child_nodes(node))

    _walk(ast.iter_child_nodes(func_node))
    return out


def _call_name(call: ast.Call):
    """取 Call 的函式名：ast.Name → .id（裸名，如 enrich_success()）；
    ast.Attribute → .attr（如 mod.enrich_success()）。

    HEAD 實測六支 helper + schedule_focal_after_cover_write 全以裸名呼叫（各模組
    `from … import`），故 `.id` 即命中；仍涵蓋 `.attr` 防未來改 import 風格
    （比照先例 `test_async_offload_guard.py::_call_name`）。
    """
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _direct_call_names(func_node) -> set:
    return {
        _call_name(n)
        for n in _direct_nodes(func_node)
        if isinstance(n, ast.Call) and _call_name(n) is not None
    }


def _collect_import_aliases(import_nodes, forbidden: set) -> dict:
    """從一批 `ast.ImportFrom` 節點收集「指向 forbidden 原始名稱」的本地名稱綁定。

    回傳 {本地名稱（asname 或 name）: 原始名稱}。用於先解析 import alias binding
    再去掃 `ast.Call`——`from mod import x as y` 之後 body 內 `y(...)` 呼叫的
    `_call_name` 只會是 `y`，不解 alias 就掃不到真正指向 `x` 的呼叫。
    """
    aliases = {}
    for node in import_nodes:
        for alias in node.names:
            if alias.name in forbidden:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def _module_level_import_froms(tree: ast.Module) -> list:
    """只收 module 最外層（非任何函式/類別內）的 `ast.ImportFrom`。"""
    return [n for n in tree.body if isinstance(n, ast.ImportFrom)]


def _all_import_froms_in_func(func_node) -> list:
    """target 函式自身（含其巢狀 scope，`ast.walk` 全下潛）內所有 `ast.ImportFrom`。

    刻意不比照 `_direct_nodes` 停在巢狀 def——function-local alias import 可能
    寫在任何深度，收集階段要抓全，掃 Call 階段才用 `_direct_nodes` 的 body 粒度
    （見 TASK-109-T6 §3「必須先解析 import alias binding 再掃呼叫」）。
    """
    return [n for n in ast.walk(func_node) if isinstance(n, ast.ImportFrom)]


# ============================================================
# 正向鎖清單（HEAD 7a8289d9 實測，v0.13 TASK-109-T6 翻面，權威見 TASK-105-T7
# 現況分析表 + TASK-109-T6 現況分析表）
# ============================================================
# (檔案, 函式名, {必含 helper Call})
POSITIVE_LOCKS = [
    # P6 — v0.13 翻面（TASK-109-T3）：同 P4，_do_readonly closure 改呼叫公開
    # 入口，四支阻塞 helper 的呼叫搬進 enrich_one_readonly（P8）。**不得改回**
    # 鎖 helper 名單，理由同 P4。
    (SCRAPER_PY, "_do_readonly", {"enrich_one_readonly"}),
    # P7 移除（TASK-109-T3）：event_generator 的 batch 唯讀成功分支不再手抄
    # enrich_success(...)，改為 asdict(payload)（payload 即 enrich_one_readonly
    # 已回傳好的 EnrichResult）。**不得加回這條正向鎖**——已無共用 helper 可鎖。
    # event_generator 本身仍留在 NEGATIVE_SCAN_TARGETS（CD-109-9①，見下）。
    # P8 — 新增（TASK-109-T6）：五支 helper 呼叫搬家後的新家。P4/P6 移除的目的
    # 在此重新鎖住——enrich_one_readonly 必須親自呼叫這五支，不得再手抄。
    (READONLY_PRODUCER_PY, "enrich_one_readonly", {
        "cover_uri_is_servable",
        "apply_cover_preserve",
        "compute_has_servable_cover",
        "enrich_success",
        "schedule_focal_after_cover_write",
    }),
]

# CD-109-9（硬要求）：與 POSITIVE_LOCKS 解耦的自有明列清單，不由 POSITIVE_LOCKS
# 推導——避免「從 POSITIVE_LOCKS 拿掉一個 target」同時讓它悄悄掉出負向指紋／
# 白名單防腐的掃描集合（覆蓋靜默收縮的 fail-open）。
NEGATIVE_SCAN_TARGETS = [
    (ENRICHER_PY, "enrich_single"),
    (ENRICHER_PY, "_write_cover"),
    (ENRICHER_PY, "fetch_samples_only"),
    (SCRAPER_PY, "enrich_single_endpoint"),
    (SCRAPER_PY, "fetch_samples_endpoint"),
    (SCRAPER_PY, "_do_readonly"),
    (SCRAPER_PY, "event_generator"),                # 失去正向鎖（P7 移除），但仍須留在負向掃描集合
    (READONLY_PRODUCER_PY, "enrich_one_readonly"),  # 新家：邏輯搬家了，鎖也要跟著搬
]

# 白名單防腐 / 負向指紋：所有 named target（去重）
ALL_TARGETS = NEGATIVE_SCAN_TARGETS


_TREE_CACHE: dict = {}


def _tree(py_file: pathlib.Path) -> ast.Module:
    key = str(py_file)
    if key not in _TREE_CACHE:
        _TREE_CACHE[key] = _parse(py_file)
    return _TREE_CACHE[key]


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / detector 函式在 parsed Python 片段上的行為，非 html/js/css 靜態
# 字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6 例外清單「Python-AST
# 源碼語意守衛」）。v0.13 TASK-109-T6：P4/P6 改鎖公開入口 enrich_one_readonly、
# P7 移除、新增 P8 鎖該入口自身的五支 helper（POSITIVE_LOCKS 翻面，理由見各條目
# inline 註解）。
class TestPositiveContractLocks:
    """正向鎖：每個 target body 必含指定共用 helper 的 Call（消除手抄第②層）。"""

    @pytest.mark.parametrize("py_file, func_name, required", POSITIVE_LOCKS,
                             ids=[n for _, n, _ in POSITIVE_LOCKS])
    def test_target_calls_required_helpers(self, py_file, func_name, required):
        func = _find_func(_tree(py_file), func_name)
        assert func is not None, f"{py_file.name}:{func_name} 定位不到（白名單防腐應先報）"
        present = _direct_call_names(func)
        missing = required - present
        assert not missing, (
            f"{py_file.name}:{func_name}() 的 body 未呼叫共用 helper {sorted(missing)}"
            f" —— 疑似手抄第②層邏輯而繞過 core.enrich_contract/core.focal_trigger。"
            f" 現有直接呼叫: {sorted(present)}"
        )


# ============================================================
# 負向鎖：四類舊 mirror 手抄指紋（AST 節點形狀，非字串 regex）
# ============================================================

def _is_mirror_cover_assign(node) -> bool:
    """指紋1：`has_servable_cover = cover_written or had_cover`。

    要求：(a) 單一 bare Name target（id=='has_servable_cover'）——**排除** 961 的
    Tuple/List 解包；(b) value 為 BoolOp(Or) 且**兩 operand 皆 ast.Name**——961 的
    `payload or ({}, {}, False)` 右 operand 是 Tuple 非 Name，天然排除；正確碼
    `has_servable_cover = compute_has_servable_cover(...)` value 是 Call 非 BoolOp，
    亦排除。
    """
    if not isinstance(node, ast.Assign):
        return False
    if len(node.targets) != 1:
        return False
    tgt = node.targets[0]
    if not (isinstance(tgt, ast.Name) and tgt.id == "has_servable_cover"):
        return False
    val = node.value
    if not (isinstance(val, ast.BoolOp) and isinstance(val.op, ast.Or)):
        return False
    return all(isinstance(v, ast.Name) for v in val.values)


def _is_inline_reason_ifexp(node) -> bool:
    """指紋2：inline `reason = 'hit' if … else 'no_cover'`（reason 派生已入
    enrich_success builder，不得散落 target body）。IfExp body/orelse 為
    Constant('hit')/Constant('no_cover')。
    """
    if not isinstance(node, ast.IfExp):
        return False
    body, orelse = node.body, node.orelse
    if not (isinstance(body, ast.Constant) and isinstance(orelse, ast.Constant)):
        return False
    return {body.value, orelse.value} == {"hit", "no_cover"}


def _is_fill_missing_had_cover_boolop(node) -> bool:
    """指紋3：`mode == 'fill_missing' and not … and had_cover`（已被
    apply_cover_preserve 取代、fill_missing 顯式閘移除）。BoolOp(And) 之子樹含
    Compare(== Constant('fill_missing')) 且含 Name('had_cover')。
    """
    if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And)):
        return False
    subtree = list(ast.walk(node))
    has_fill = any(
        isinstance(c, ast.Compare)
        and any(isinstance(cmp, ast.Constant) and cmp.value == "fill_missing"
                for cmp in ([c.left] + list(c.comparators)))
        for c in subtree
    )
    has_had_cover = any(isinstance(c, ast.Name) and c.id == "had_cover" for c in subtree)
    return has_fill and has_had_cover


def _is_second_original_title_preserve(node) -> bool:
    """指紋4：第二套手寫 original_title preserve `… or <row>.original_title`
    （唯一 preserve 只在 effective_original_title helper）。BoolOp(Or) 之子樹含
    `Attribute(attr='original_title', value=Name(<任意>))`。

    **錨定 attr shape、不錨定 receiver 變數名**（F1 修正）：主 target `enrich_single`
    的 DB row 變數是 `existing_record`（非 `existing`），若硬編 `existing.` 會漏掉最
    可能發生複製回退的那個站（AST 指紋硬編 receiver 名的經典假綠）。任意 `Name`
    receiver 的 `.original_title` 屬性存取都算——因 `meta` 是 dict、走 `meta.get(...)`
    不會有 `.original_title` 屬性存取，只有 DB row 物件（不論命名）才有此屬性；
    全庫唯一的合法 `<x>.original_title`（`enricher.py:80` `video.original_title`）在
    所有 named target 之外、且非 BoolOp，粒度天然不掃。

    不誤傷 plain `meta.get("original_title","")`（那是純 Call、非 Attribute，且在
    _write_nfo/_db_upsert/_write_movie_assets 等非-target 函式，粒度天然不掃）。
    """
    if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
        return False
    for c in ast.walk(node):
        if (isinstance(c, ast.Attribute) and c.attr == "original_title"
                and isinstance(c.value, ast.Name)):
            return True
    return False


NEGATIVE_FINGERPRINTS = [
    ("has_servable_cover = cover_written or had_cover", _is_mirror_cover_assign),
    ("reason = 'hit' if … else 'no_cover'", _is_inline_reason_ifexp),
    ("mode == 'fill_missing' and … and had_cover", _is_fill_missing_had_cover_boolop),
    ("… or existing.original_title (2nd preserve)", _is_second_original_title_preserve),
]


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / detector 函式在 parsed Python 片段上的行為，非 html/js/css 靜態
# 字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6 例外清單「Python-AST
# 源碼語意守衛」）。v0.13 TASK-109-T6：掃描集合改讀 NEGATIVE_SCAN_TARGETS——與
# POSITIVE_LOCKS 解耦的自有清單（CD-109-9），不再由 POSITIVE_LOCKS 推導，避免
# 正向鎖被拿掉時覆蓋跟著靜默收縮。


# 負向鎖 body 粒度掃描的禁用私有 primitive 名單（TASK-109-T6 §3）：這些已收斂進
# enrich_one_readonly（P8）的呼叫，不得再被 enrich_single_endpoint / _do_readonly
# 這兩個公開入口 caller 直接呼叫（呼叫方必須走 enrich_one_readonly，不得繞過）。
# **刻意不含** should_preserve_cover —— TASK-109-T5 讓 enrich_single_endpoint 合法
# 呼叫它（refresh_full + overwrite_existing=false 的分裂防呆封面政策，:490），列入
# 會誤殺。
FORBIDDEN_PRIVATE_PRIMITIVES = frozenset({
    "_produce_one",
    "resolve_ingest_plan",
    "_readonly_stub_not_found",
    "cover_uri_is_servable",
    "apply_cover_preserve",
    "compute_has_servable_cover",
    "schedule_focal_after_cover_write",
})

FORBIDDEN_PRIMITIVE_TARGETS = [
    (SCRAPER_PY, "enrich_single_endpoint"),
    (SCRAPER_PY, "_do_readonly"),
]


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / import alias binding 在 parsed Python 原始碼上的行為，非
# html/js/css 靜態字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6
# 例外清單「Python-AST 源碼語意守衛」）。新增於 v0.13 TASK-109-T6：先解析 import
# alias binding（module-level ∪ target 函式自身含巢狀 scope 的 ast.ImportFrom）
# 聯集成本地名稱集合，再掃 target body 的 ast.Call——防止 function-local
# `import … as x` 繞過只讀 module-level 的掃描。


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / detector 函式在 parsed Python 片段上的行為，非 html/js/css 靜態
# 字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6 例外清單「Python-AST
# 源碼語意守衛」）。v0.13 TASK-109-T6：刪除 test_961_tuple_target_not_flagged
# （其錨定的 production 碼已被 T3 合法移除）；覆蓋同一 detector 行為的合成孿生
# 測試移至 TestNegativeDetectorSensitivity::test_fp1_passes_961_tuple_and_correct_call，
# 不隨 production 重構腐爛。


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / detector 函式在 parsed Python 片段上的行為，非 html/js/css 靜態
# 字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6 例外清單「Python-AST
# 源碼語意守衛」）。
class TestNegativeDetectorSensitivity:
    """負向鎖 detector 敏感度（防近空殼假綠）：直接餵 AST 片段，斷言四個 detector
    對 canonical mirror 形狀**命中**、對正確碼**放行**。這把「守衛真的鎖得住」的
    mutation 直覺固化成回歸測試（F1：指紋4 曾硬編 `existing` 漏掉主 target 的
    `existing_record`）。"""

    @staticmethod
    def _first(src: str, node_type):
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, node_type):
                return n
        raise AssertionError(f"片段內找不到 {node_type.__name__}")


# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（cross-file enrich_contract 契約）：
# 斷言 AST 節點形狀 / detector 函式在 parsed Python 片段上的行為，非 html/js/css 靜態
# 字串存在檢查，eslint/static_guard 無法表達（pre-merge SA-pre-6 例外清單「Python-AST
# 源碼語意守衛」）。v0.13 TASK-109-T6：ALL_TARGETS = NEGATIVE_SCAN_TARGETS（已與
# POSITIVE_LOCKS 解耦的自有清單），本 class 因此掃描 8 個 target（含新家
# enrich_one_readonly 與失去正向鎖但仍受掃描的 event_generator）。
