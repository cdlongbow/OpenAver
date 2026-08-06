"""AST 邊界守衛：裸 os.replace / tempfile.mkstemp 只准出現在 core/atomic_write.py
（feature/113d T3, CD-113d-5）。

# [lint-guard: pytest-justified] Python-AST 源碼語意守衛（os.replace/mkstemp 邊界式契約）：
# 斷言裸 os.replace(...) / tempfile.mkstemp(...)（含任意 import alias/dotted binding
# 形式）只准出現在 core/atomic_write.py，其餘 core/+web/+windows/ 檔案違規數恰為 0。
# static_guard_lint 只能做字面字串比對，無法表達「解析 import binding 後判斷呼叫端
# receiver+attribute 是否同時對應到 os.replace/tempfile.mkstemp」這種語意，故留 pytest。

守什麼：T1（10b5c605）/T2（d6c34917）已把四處手寫的「同目錄 mkstemp → 開 fh → 關 fd
→ os.replace → 例外時清 temp」骨架收斂進 core/atomic_write.py 的 atomic_write()
primitive。本守衛掃描 core/ + web/ + windows/ 全部 .py（排除 scripts/、build*.py、
tests/），對每個檔案做完整 import binding 解析（ast.Import 的 alias/dotted 語意 +
ast.ImportFrom 的 asname），確認裸 os.replace(...) / tempfile.mkstemp(...) 呼叫
（不論寫成 os.replace(...)／platform_os.replace(...)／from os import replace as X;
X(...) 等任何 binding 形式）恰好只出現在 core/atomic_write.py，其餘所有檔案違規數
必須為 0——防止未來有人重構時繞過 primitive、在別處手寫一次原子寫（連同 primitive
內建的 Windows 容錯語意 BE-ENV-01 一起被繞過）。

核心關鍵一行：呼叫端比對時 `isinstance(node.func.value, ast.Name)` 這道判斷，讓
`"abc".replace(x, y)`（receiver 是 ast.Constant）與 `s.upper().replace(...)`
（receiver 是 ast.Call，鏈式呼叫）都在進入 module_bindings 查找之前就被排除——這是
本守衛能對 core/+web/ 現存 67 處 `.replace(` 呼叫全部歸零誤報的關鍵，不是加分項。

Scope-aware binding 解析（review P1，2026-08-06 裁決）：初版 `_binding_maps` 把
全檔各 scope 的 import binding 併成單一扁平 dict，會在多函式各自用同一個 alias
（例如兩個函式各自 `import os as tmp` / `import tempfile as tmp`）時發生兩種假象
之一——後定義的函式覆蓋前面的 binding，造成漏抓；或參數/區域變數恰好同名於某處
的 import alias，被外層 binding 誤接上，造成誤報。改為 `_resolve_scope` 遞迴：
每個 scope（`Module`/`FunctionDef`/`AsyncFunctionDef`/`Lambda`/`ClassDef`）先算
「這一層自己直接擁有」的 import binding（遞迴 body 但停在巢狀 scope 邊界），
再算這一層被非 import 手段重新綁定的名字集合（參數、賦值、for/with target、
except/global/nonlocal、巢狀 def/class 同名），從**繼承來的** binding 裡把這些
名字剔除——但**這一層自己 import 的名字不剔除**（同一層既 import 又賦值同名，
import 勝：`import os as tmp; tmp = 5; tmp.replace(...)` 仍判定為違規，這是刻意
的保守選擇，換取規則簡單、可讀，而非追求完整的資料流精度）。呼叫端比對只看
「屬於這一層自己」的 `ast.Call`，逐層遞迴時把算好的 binding 往下傳。

已知的殘留不精確（記錄不修，理由見下方停損線判準）：`class C: import os as tmp`
放在類別本體、再由某個 method 使用裸名 `tmp.replace(...)`——本演算法會把類別層
的 import 視為可繼承給巢狀 method，但 Python 實際的名字解析規則是 method 不會
看見 class body 的區域名字（那段程式碼在真實執行時會是 `NameError`，是寫不出
可運行程式碼的形狀）。往「誤報」方向偏，不是往「漏抓」方向偏，本卡判斷不需要
特別排除。

`from os import *` 星號匯入不在本守衛的靜態 binding 解析範圍內（無法枚舉星號
匯入實際綁定了哪些名字）——但這是正交閘：`pyproject.toml` 的 `ruff` `select`
已含 `"F"`（涵蓋 F403 `import *` 用法禁止、F405 可能來自 star import 的名字未定義
警告），全庫早已機械禁止 star import，這支守衛不需要重複防這一類。

★★ 本守衛的契約與停損線（owner 拍板，2026-08-06；下一個維護者請先讀這段）★★

本守衛偵測「非蓄意的漂移」（有人重構時把 os.replace/mkstemp 換了 import 寫法、
或在 core/atomic_write.py 之外的檔案手寫一次原子寫），不偵測「蓄意的規避」
（例如刻意用 getattr(os, "repl" + "ace") 動態取屬性、或用 importlib 動態載入
os 模組來繞過靜態 import binding 解析）。判準＝「不知情的維護者會不會不小心
寫出來」。21 格證偽矩陣已窮舉常見的 alias/dotted/asname 組合形狀 + 多 scope
binding 交錯形狀，屬於「會不小心寫出來」的範圍；動態屬性存取、字串拼接呼叫名、
利用 class-body 名字解析規則等需要刻意繞過的手法不在本守衛修復範圍。這條判準
與 113b-T3（tests/unit/test_nfo_stat_boundary_guard.py）的停損線完全同構，不另
立新標準。

為何 pytest 不是 lint（CLAUDE.md「Lint 守衛規則」north-star，CD-113d-5 定案）：
本守衛驗的是「解析 import binding 後判斷某個 ast.Call 節點的 receiver+attribute
是否同時對應到 os.replace/tempfile.mkstemp」這種 Python 源碼語意（AST），CLAUDE.md
判斷原則列為 C 類（某個 Python 函式的行為/源碼語意）；`scripts/*.mjs`
（eslint/stylelint 家族的 static_guard_lint / i18n_lint）完全不處理 .py 檔案，
機械上無法承接這種語意判斷。
"""
import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ATOMIC_WRITE_PY = REPO_ROOT / "core" / "atomic_write.py"
SCAN_ROOTS = ["core", "web", "windows"]  # scripts/、build*.py、tests/ 一律不納入

PAIRS = {("os", "replace"), ("tempfile", "mkstemp")}


# ============================================================
# Scope-aware import binding 解析（review P1 裁決，2026-08-06）
#
# 初版把全檔 import binding 併成一個扁平 dict（ast.walk 全域掃描），在多 scope
# 各自宣告同名 alias 時會漏抓或誤報（見檔頂 docstring「Scope-aware binding 解析」
# 段落）。改為對每個 scope 遞迴解析、只把「這一層自己看得到」的 binding 往下傳。
# ============================================================

SCOPE_TYPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_direct_nodes(scope) -> list:
    """`scope` 自己這一層的節點：遞迴 body，但**停在巢狀 scope 邊界**（巢狀 scope
    節點本身會被收進來一次，用來偵測「巢狀 def/class 同名遮蔽」，但不下鑽進它的
    內容——內容由遞迴呼叫 `_resolve_scope` 時單獨處理）。與 113b-T3
    `_direct_scope_nodes` 同構手法，套用在不同問題上（那支鎖委派名，這支鎖
    import binding）。"""
    out = []

    def rec(node):
        for child in ast.iter_child_nodes(node):
            out.append(child)
            if child is not scope and isinstance(child, SCOPE_TYPES):
                continue
            rec(child)

    rec(scope)
    return out


def _own_bindings_at_level(own_nodes: list) -> tuple:
    """技術要點第 1 節兩條 import binding 規則，套用在「這一層自己的節點」而非
    全檔（原規則本身不變，只是輸入從 `ast.walk(tree)` 換成 `own_nodes`）。"""
    module_bindings = {}     # 本地名稱 -> 目標模組（"os"/"tempfile"/dotted）
    callable_bindings = {}   # 本地名稱 -> (module, attr)

    for node in own_nodes:
        if isinstance(node, ast.Import):
            # ① ast.Import —— 照 Python 真實 binding 語意分兩種
            for a in node.names:
                if a.asname:
                    # import os.path as p  → p 指向完整 dotted module os.path
                    bound, target = a.asname, a.name
                else:
                    # import os.path      → 頂層 os 指向 os（split 取第一段）
                    bound = target = a.name.split(".", 1)[0]
                if target in {"os", "tempfile"}:
                    module_bindings[bound] = target

        elif isinstance(node, ast.ImportFrom):
            # ② ast.ImportFrom —— module ∈ {"os","tempfile"} 時
            if node.module in {"os", "tempfile"}:
                for a in node.names:
                    if (node.module, a.name) in PAIRS:
                        callable_bindings[a.asname or a.name] = (node.module, a.name)

    return module_bindings, callable_bindings


def _shadowed_names(scope, own_nodes: list) -> set:
    """這一層 scope 被**非 import 手段**重新綁定的名字集合：函式自己簽名上的
    參數、賦值/for-target/with-as（皆落在 `ast.Name` + `Store`/`Del`，含
    tuple 拆包、海象 `:=`）、`except E as X`、巢狀 `def`/`class` 同名、
    `global`/`nonlocal` 宣告。用來把「繼承自外層」的 binding 剔除——但這一層
    自己 import 的名字不剔除（見檔頂 docstring「import 勝」決策）。"""
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
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
    return names


def _resolve_scope(scope, inherited_mod: dict, inherited_call: dict) -> list:
    """呼叫端比對規則（receiver + attribute 必須同時匹配，技術要點第 2 節），
    scope-aware 版本：先算這一層自己的 binding + shadow，合併出這一層「有效」
    的 mod_map/call_map，比對只屬於這一層的 ast.Call，再對每個巢狀 scope 遞迴、
    把這一層算好的 map 往下傳。回傳 (lineno, "receiver.attr" 或裸名) 清單。"""
    own_nodes = _own_direct_nodes(scope)
    own_mod, own_call = _own_bindings_at_level(own_nodes)
    shadowed = _shadowed_names(scope, own_nodes)

    mod_map = dict(inherited_mod)
    mod_map.update(own_mod)
    for name in shadowed:
        if name not in own_mod:  # 同一層既 import 又賦值同名 → import 勝，不剔除
            mod_map.pop(name, None)

    call_map = dict(inherited_call)
    call_map.update(own_call)
    for name in shadowed:
        if name not in own_call:
            call_map.pop(name, None)

    violations = []
    for node in own_nodes:
        if not isinstance(node, ast.Call):
            continue

        # Call(func=Attribute(value=Name(n), attr=a))
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            receiver = node.func.value.id
            attr = node.func.attr
            mod = mod_map.get(receiver)
            if mod is not None and (mod, attr) in PAIRS:
                violations.append((node.lineno, f"{receiver}.{attr}"))

        # Call(func=Name(n))
        elif isinstance(node.func, ast.Name):
            n = node.func.id
            pair = call_map.get(n)
            if pair in PAIRS:
                violations.append((node.lineno, n))

    for node in own_nodes:
        if isinstance(node, SCOPE_TYPES):
            violations += _resolve_scope(node, mod_map, call_map)

    return violations


def _violations_from_tree(tree: ast.Module) -> list:
    """回傳 (lineno, "receiver.attr" 或裸名) 的違規清單。對外行為/回傳格式與
    scope-aware 改寫前完全相同，只是內部從扁平 dict 換成逐 scope 遞迴解析。"""
    return _resolve_scope(tree, {}, {})


def _find_violations(py_file: pathlib.Path) -> list:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    return _violations_from_tree(tree)


def _violations_in_source(source: str) -> list:
    """同 _find_violations，但吃字串（合成片段用，不碰檔案系統）。"""
    tree = ast.parse(source)
    return _violations_from_tree(tree)


# ============================================================
# 掃描目標清單（技術要點第 3 節）
# ============================================================

def _scan_targets() -> list:
    files = []
    for root_name in SCAN_ROOTS:
        for py_file in sorted((REPO_ROOT / root_name).rglob("*.py")):
            if py_file.resolve() == ATOMIC_WRITE_PY.resolve():
                continue  # atomic_write.py 是允許出現真呼叫的邊界本體，另外用反假綠測試單獨驗證
            files.append(py_file)
    return files


SCAN_TARGETS = _scan_targets()  # 本卡實測 110 支


def test_scan_targets_is_nonempty_and_each_root_contributes():
    """反假綠第三條路：SCAN_ROOTS 打錯字、或 rglob 因故回傳空清單，會讓所有
    parametrize case 消失、pytest 顯示「0 個 case 卻整體 PASS」，看起來像是
    通過但其實什麼都沒掃到。這裡直接鎖住 core/web/windows 三個根目錄都至少
    貢獻 1 支檔案，且總數量在合理量級（本卡實測 110 支，抓寬鬆下限防止未來
    刪檔導致的漂移誤判成 bug）。"""
    assert len(SCAN_TARGETS) >= 50, (
        f"SCAN_TARGETS 數量異常低（{len(SCAN_TARGETS)}），SCAN_ROOTS 或 rglob 可能出錯"
    )
    contributed_roots = {p.relative_to(REPO_ROOT).parts[0] for p in SCAN_TARGETS}
    for root_name in SCAN_ROOTS:
        assert root_name in contributed_roots, (
            f"SCAN_TARGETS 裡沒有任何來自 {root_name}/ 的檔案——SCAN_ROOTS 打錯字"
            f"或該目錄的 rglob 結果異常"
        )


# ============================================================
# (a) 主斷言：每檔獨立 parametrize，逐格可單獨轉紅（技術要點第 4 節）
# ============================================================

@pytest.mark.parametrize(
    "py_file", SCAN_TARGETS, ids=[str(p.relative_to(REPO_ROOT)) for p in SCAN_TARGETS]
)
def test_no_bare_replace_or_mkstemp_outside_primitive(py_file):
    violations = _find_violations(py_file)
    assert violations == [], (
        f"{py_file}: 裸 os.replace/mkstemp 呼叫（{violations}）必須改走 "
        f"core.atomic_write.atomic_write()，不得繞過 primitive"
    )


# ============================================================
# (b) 反假綠測試（技術要點第 5 節 / E 段）
# ============================================================

def test_atomic_write_py_is_the_only_boundary_and_actually_uses_primitives():
    """條件 1：core/atomic_write.py 找不到 → 失敗並指名。
    條件 2：檔案存在但找不到其中可解析的 os.replace / mkstemp 呼叫 → 失敗並指名
    （防守衛在空檔案/被清空的 primitive 上永遠全綠）。"""
    if not ATOMIC_WRITE_PY.exists():
        pytest.fail(
            f"boundary guard cannot operate: {ATOMIC_WRITE_PY} not found "
            f"(guard would trivially pass on an empty/missing boundary)"
        )
    violations = _find_violations(ATOMIC_WRITE_PY)
    kinds = {name.rsplit(".", 1)[-1] for _, name in violations}
    if "replace" not in kinds:
        pytest.fail(
            f"{ATOMIC_WRITE_PY} contains no resolvable os.replace call — "
            f"guard's positive boundary reference is missing (silent-empty-file false green)"
        )
    if "mkstemp" not in kinds:
        pytest.fail(
            f"{ATOMIC_WRITE_PY} contains no resolvable tempfile.mkstemp call — "
            f"guard's positive boundary reference is missing (silent-empty-file false green)"
        )


# ============================================================
# (c) 15 格證偽矩陣（技術要點第 6 節，parametrize，永久留測試檔）
# ============================================================

# RED（10 格，防假綠）—— 每格附「這格在防什麼」，逐字承接 TASK-113d-T3.md D 段矩陣
RED_CASES = [
    # 1: 最基本形狀，ast.Import 無 as、無 dotted
    (1, "import os\nos.replace(a, b)\n"),
    # 2: ast.Import 有 as、無 dotted —— bound=asname, target=name 分支
    (2, "import os as platform_os\nplatform_os.replace(a, b)\n"),
    # 3: 同 #1 但換 tempfile/mkstemp 配對
    (3, "import tempfile\ntempfile.mkstemp()\n"),
    # 4: 同 #2 但換配對；v2 漏掉，且 v2 還拿同一個 tmp 當 green case（見 #10）
    (4, "import tempfile as tmp\ntmp.mkstemp()\n"),
    # 5: ast.ImportFrom 無 as，裸名呼叫（callable_bindings）
    (5, "from os import replace\nreplace(a, b)\n"),
    # 6: ast.ImportFrom 有 as；v2 漏掉
    (6, "from os import replace as atomic_replace\natomic_replace(a, b)\n"),
    # 7: 同 #5 換配對
    (7, "from tempfile import mkstemp\nmkstemp()\n"),
    # 8: 同 #6 換配對；v2 漏掉
    (8, "from tempfile import mkstemp as create_temp\ncreate_temp()\n"),
    # 13: Python 把頂層 os 綁進 scope（a.name.split(".",1)[0] 分支）；v3 漏掉——
    #     v3 曾用 alias.name ∈ {"os","tempfile"} 過濾掉 "os.path"，導致 .split() 那半從未生效
    (13, "import os.path\nos.replace(a, b)\n"),
    # 14: dotted import 不得干擾同檔其他 binding——兩條 ast.Import 各自獨立累積進
    #     module_bindings，不互相覆蓋
    (14, "import tempfile\nimport os.path\ntempfile.mkstemp()\n"),
    # 20: scope-aware 化之後，最基本的「模組層 import、函式內呼叫」繼承路徑必須
    #     還能用——防「修過頭把繼承鏈也一起殺了」（review P1 修法本身的回歸線）
    (20, "import os\ndef f(a,b): os.replace(a,b)\n"),
    # 21: 巢狀函式必須能繼承外層函式（不是只繼承模組層）宣告的 import——
    #     scope 鏈遞迴要一路往下傳，不能只做一層
    (21, "def outer():\n    import os\n    def inner():\n        os.replace(a, b)\n    return inner\n"),
]

# GREEN（5 格，防誤報）
GREEN_CASES = [
    # 9: attribute 對、receiver 不是 ast.Name（是 ast.Constant）——
    #    isinstance(node.func.value, ast.Name) 直接排除，代表現存 core/+web/ 67 處裡
    #    的多數（尤其是字面字串起手的鏈式呼叫）
    (9, '"abc".replace(x, y)\n'),
    # 10: receiver 對（tmp -> tempfile）、attribute 不對（TemporaryDirectory 不在
    #     PAIRS）——(mod, attr) in PAIRS 判斷擋下
    (10, "import tempfile as tmp\ntmp.TemporaryDirectory()\n"),
    # 11: 配對交叉——receiver 解析出來是 os、attribute 是 mkstemp，兩者各自都在各自
    #     的清單裡，但 ("os","mkstemp") 不在 PAIRS（只有 ("os","replace") 與
    #     ("tempfile","mkstemp")）——receiver 與 attribute 必須同時匹配同一組 pair
    (11, "import os as tmp\ntmp.mkstemp()\n"),
    # 12: 區域變數 receiver，dest 從未出現在任何 import 語句 →
    #     module_bindings.get("dest") 是 None。合成案例，非本庫既有用法（TASK-113d-T3.md
    #     B 段已驗證全庫無 Path.replace(other_path) 改名語意呼叫），仍是必要的反誤報覆蓋
    (12, "from pathlib import Path\ndest = Path('x')\ndest.replace(other)\n"),
    # 15: p 綁的是完整 dotted module os.path（有 as 分支：bound, target = asname, name），
    #     target="os.path" 不在 {"os","tempfile"} 過濾清單裡，module_bindings 裡不會有
    #     "p" 這個 key —— 若照「一律綁頂層」的簡化寫法會誤判成 RED（v4 與 Codex 建議的差異）
    (15, "import os.path as p\np.replace(a, b)\n"),
    # 17: 參數名撞到模組層 import alias（`import os as tmp` 後某個無關函式恰好
    #     用 tmp 當參數名）——函式自己的參數要能剔除繼承來的 binding，不是「只要
    #     module 層看過這個名字就永遠算數」（review P1 復現形狀③）
    (17, "import os as tmp\ndef unrelated(tmp): return tmp.replace('a','b')\n"),
    # 18: 參數直接叫 os，遮蔽模組層 `import os`——同上，換成完全撞名（P1 形狀④）
    (18, "import os\ndef f(os): return os.replace('a','b')\n"),
    # 19: 區域變數（非參數）叫 os，遮蔽模組層 `import os`——賦值 target 也要能
    #     剔除繼承來的 binding，不是只有參數才算 shadow（P1 形狀⑤）
    (19, "import os\ndef f(s):\n    os = s.strip()\n    return os.replace('a','b')\n"),
]


@pytest.mark.parametrize(
    "case_id,source", RED_CASES, ids=[f"RED-{c[0]}" for c in RED_CASES]
)
def test_matrix_red_cases(case_id, source):
    assert _violations_in_source(source) != [], (
        f"case #{case_id} 應偵測為違規，但守衛判為合法：{source!r}"
    )


@pytest.mark.parametrize(
    "case_id,source", GREEN_CASES, ids=[f"GREEN-{c[0]}" for c in GREEN_CASES]
)
def test_matrix_green_cases(case_id, source):
    assert _violations_in_source(source) == [], (
        f"case #{case_id} 應為合法，但守衛誤報為違規：{source!r}"
    )


# 16: 兩個不相關的函式各自用同一個 alias 名（tmp）匯入不同模組——初版扁平 dict
#     版本會讓後定義的函式（helper）的 binding 覆蓋掉前一個（bad）的，導致 bad
#     裡的違規被靜默吃掉、只剩 helper 那筆（review P1 復現形狀②，本卡最重要的
#     回歸鎖）。這格不能只用「非空」判斷（那樣即使漏抓一筆也會誤判為通過），
#     必須明確斷言兩筆都在。
_CASE_16_SOURCE = (
    "def bad(a,b):\n"
    "    import os as tmp\n"
    "    tmp.replace(a,b)\n"
    "\n\n"
    "def helper():\n"
    "    import tempfile as tmp\n"
    "    tmp.mkstemp()\n"
)


def test_matrix_case_16_two_scopes_same_alias_both_detected():
    violations = _violations_in_source(_CASE_16_SOURCE)
    kinds = {name for _, name in violations}
    assert len(violations) == 2, (
        f"case #16 兩個 scope 各自的違規都應被獨立偵測到，實際只有 {violations}"
        f"（若只剩 1 筆，代表後一個 scope 的 binding 覆蓋掉了前一個——P1 復發）"
    )
    assert kinds == {"tmp.replace", "tmp.mkstemp"}, (
        f"case #16 應同時報出 bad() 內的 tmp.replace 與 helper() 內的 tmp.mkstemp，"
        f"實際 {kinds}"
    )


def test_import_wins_over_same_level_reassignment():
    """設計決策鎖定測試（檔頂 docstring「同一層既 import 又賦值同名」段落）：
    `import os as tmp` 之後同一層又把 tmp 重新賦值，本守衛選擇讓 import 贏
    （仍判定為違規），不追蹤「這一層內時間順序上最後一次賦值才是真正生效值」
    的完整資料流——這是刻意的簡化取捨，必須有測試鎖住，不能只留在文件裡。"""
    source = "import os as tmp\ntmp = 5\ntmp.replace(a,b)\n"
    assert _violations_in_source(source) != [], (
        "同層 import 之後又賦值同名，預期仍判定為違規（import 勝），"
        "若變成 GREEN 代表這條設計決策被靜默改掉了"
    )


# ============================================================
# 附加誤報防線：鏈式呼叫 receiver（func.value 是 ast.Call 而非 ast.Name）
# ============================================================

def test_chained_call_receiver_is_not_misjudged():
    """`s.upper().replace(...)` 的 node.func.value 是 ast.Call（鏈式呼叫的中間
    結果），不是 ast.Name——isinstance(node.func.value, ast.Name) 這道判斷必須
    在進入 module_bindings 查找之前就把它擋下（core/scrapers/avsox.py:166 的
    真實形狀：`s.upper().replace("-PPV", "")`）。"""
    source = "import os\ns = os.environ.get('X', '')\nresult = s.upper().replace('-PPV', '')\n"
    assert _violations_in_source(source) == [], (
        "鏈式呼叫（func.value 是 ast.Call）被誤判為違規"
    )


# ============================================================
# 附加邊界：同一行匯入多個模組 / relative import 不得誤判或拋非預期例外
# ============================================================

def test_multi_name_single_import_line_detects_both():
    """`import os, tempfile` 同一行匯入多個模組（ast.Import 的 node.names 是
    清單），_binding_maps 的 for a in node.names 已天然涵蓋，這裡驗證兩個違規
    都被偵測到。"""
    source = "import os, tempfile\nos.replace(a, b)\ntempfile.mkstemp()\n"
    violations = _violations_in_source(source)
    assert len(violations) == 2, f"應偵測到兩個違規，實際 {violations}"


def test_relative_import_does_not_raise_or_misjudge():
    """`from . import replace` 是相對 import，node.module 為 None——
    `if node.module in {"os","tempfile"}` 對 None 天然是 False，不拋例外、
    也不誤判（這裡的 replace 不是 os.replace）。"""
    source = "from . import replace\nreplace(a, b)\n"
    assert _violations_in_source(source) == [], (
        "相對 import 的裸名呼叫不應被誤判為 os.replace/tempfile.mkstemp"
    )


# ============================================================
# 誤報檢查清單（Task 誤報檢查清單第 2 項）：現存 core/+web/ 全部 67 處
# `.replace(` 呼叫中，除 core/atomic_write.py 內 2 處真呼叫外，其餘一律不誤判——
# 由上方主斷言（test_no_bare_replace_or_mkstemp_outside_primitive）對 110 支
# SCAN_TARGETS 全綠即為此條的完整證明，此處另外挑幾個代表性檔案做具名回歸釘點，
# 讓失敗訊息能直接點出「哪個代表性檔案破了規則」而不必等全量 parametrize 掃過。
# ============================================================

REPRESENTATIVE_REPLACE_FILES = [
    REPO_ROOT / "core" / "gallery_scanner.py",   # pattern.replace(...) 區域變數
    REPO_ROOT / "core" / "path_utils.py",        # path.replace(...) 區域變數（合法路徑處理實作本體）
    REPO_ROOT / "core" / "scrapers" / "avsox.py",  # s.upper().replace(...) 鏈式呼叫
]


@pytest.mark.parametrize(
    "py_file", REPRESENTATIVE_REPLACE_FILES,
    ids=[str(p.relative_to(REPO_ROOT)) for p in REPRESENTATIVE_REPLACE_FILES],
)
def test_representative_replace_heavy_files_have_zero_violations(py_file):
    assert py_file.exists(), f"代表性檔案不存在，需更新清單：{py_file}"
    violations = _find_violations(py_file)
    assert violations == [], (
        f"{py_file} 現存 .replace( 呼叫應全數為合法用法（區域變數/鏈式呼叫），"
        f"實際被守衛誤判為違規：{violations}"
    )
