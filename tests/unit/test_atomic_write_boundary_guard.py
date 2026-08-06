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

Global/Nonlocal 不是 rebinding，但兩者解析目標不同（review P1 二審，2026-08-06
裁決；Codex PR review 抓到第二條）：上一輪只修了「global/nonlocal 都不算重新
綁定，所以不剔除 inherited binding」這一半，把兩者用同一套「不 pop」處置合併
處理——但這是不夠的：`global name` 必須解析到 **module（root）scope** 的
binding，`nonlocal name` 才是解析到**最近 enclosing function scope** 的
binding（用 inherited map 近似成立）。「不 pop」只在 global 宣告所在的那條
scope 鏈上、每一層都恰好是同一個 binding 時才碰巧正確；一旦中間某層函式用
同名 alias 綁了不同模組，`global` 會錯拿到那個中間層的 binding 而不是 module
的。復現形狀：module `import tempfile as x`、outer `import os as x`、inner
`global x; x.mkstemp()`——inner 的 `global x` 必須回 module 拿到 `tempfile`，
判定違規（見 RED 26）；若把 module/outer 的匯入對調（module 是 `os`、outer
是 `tempfile`），同一段 `global x; x.mkstemp()` 就必須是 GREEN（見 GREEN 27，
本輪最重要的判別器：只「不 pop」的錯誤實作會在這格誤報，因為它會拿到 outer
的 `tempfile` 而不是 module 的 `os`）。

修法：`_resolve_scope` 遞迴時額外攜帶 **root（module scope）的 mod_map/
call_map**，每一層解析名字改成寫死的四條優先序（照序實作，逐條有註解）：
① 這一層自己的 import binding 最優先（`import` 勝的既有決策不變）；
② 這一層宣告 `global` 的名字 → 一律用 root maps 解析，root 沒有這個名字的
binding 就視為無 binding（從 map 移除），不可退回 inherited（見 GREEN 29：
`root_mod` 完全沒有該名字，即使某層 inherited 里還留著舊值也要清掉）；
③ 這一層宣告 `nonlocal` 的名字 → 用 inherited map 解析（＝最近 enclosing
function 的 binding，維持上一輪就有的行為，見 RED 28：nonlocal 若被誤導向
root 這格就會從 RED 變 GREEN，證明兩條路徑真的分開）；
④ 其餘名字 → inherited 扣掉 `_shadowed_names()`（一般 rebinding：參數/賦值/
for/with/except/巢狀 def 同名）。

病態交互（同一層既宣告 `global x` 又自己 `import ... as x`，例如
`global x; import os as x`——合法且會重綁 module global）：依第①條由這一層
自己的 import 勝，不追求資料流精度，這是刻意選擇（與既有「同層 import 又賦值
同名」的 fail-closed 保守取向同一家族）。實測驗證（Opus 復現，2026-08-06）：
`import os` 之後某函式 `global os; os.replace(...)` 真的會呼叫到 os.replace
（拋 `FileNotFoundError`，不是 `NameError`）；`nonlocal os` 若最近 enclosing
function 根本沒綁過 `os`，Python 在編譯期就是 `SyntaxError`，那個形狀寫不出
可運行程式碼，不必處理。見 RED 22–25（基本形，上一輪已鎖，本輪不得翻面）、
RED 26/28、GREEN 27/29（本輪新增，鎖 global→root / nonlocal→enclosing 兩條
路徑真的分岔）。

Comprehension 有隱含的獨立 scope（Codex PR review 三審抓到第三條 P1，
2026-08-06 裁決）：Python 3 的 `ListComp`/`SetComp`/`DictComp`/`GeneratorExp`
的 for-target 活在**隱含的獨立 scope**，不外洩到外層——實測驗證：
`import os as x` 之後 `def f(): values=[x for x in ()]; return x.__name__`
印出 `"os"`，證明 comprehension 的 target 完全不外洩，即使跟外層 alias
同名。上一輪只把 `Module`/`FunctionDef`/`AsyncFunctionDef`/`Lambda`/
`ClassDef` 五種節點當成 scope 邊界，comprehension 不在其中，於是
`_own_direct_nodes` 會下鑽進 comprehension 的 `for x`，把 `x` 的 `Store`
收進「這一層」的 shadow 集合，錯誤地把外層 inherited 的 `x → os` 剔除
（假綠，見 RED 30/32/33/34）。

修法必須同時處理內外兩側——只讓 comprehension 的 target「不下鑽」而不真的
把它當成一個 scope 邊界，會把漏抓換成另一個方向的誤報（`import os as x`
之後 `[x.replace('a','b') for x in items]`，這裡的 `x` 是 comprehension
自己的 target，不是 module alias，不該被判違規，見 GREEN 31）。正解：把
`ListComp`/`SetComp`/`DictComp`/`GeneratorExp` 四種節點併入 `SCOPE_TYPES`
當作真正的 scope 邊界，其 own bindings（shadow 名）＝該 comprehension 各
generator 的 target 名（含 tuple 拆包，經由既有的 `ast.Name`+`Store` 通用
邏輯自動涵蓋，不需要額外程式碼）。

一個容易漏掉的 Python 語意細節（實測驗證，見 `_comprehension_first_iter`
docstring）：comprehension 的**最外層第一個 generator 的 `iter`**是在**外層
（enclosing）scope** 求值，其餘部分（target/ifs/elt/key/value/後續
generator 的 iter）才在 comprehension 自己的隱含 scope 內求值。實測：
`import os as x` 之後 `def f(a,b): return [x for x in x.replace(a,b)]`——
這個作為 iterable 的 `x.replace(a,b)` 解析到的是外層模組層的 `os`，即使
comprehension 自己的 target 也叫 `x`（見 RED 35，本輪最重要的判別器：只把
comprehension 整體「一刀切」當成單一 scope、不特別處理第一個 iter 的錯誤
實作會在這格漏抓）。`_own_direct_nodes` 用 `skip` 排除 comprehension 自己
第一個 generator 的 `iter` 子樹（已在外層被收走，不重複計算），並在撞到
**巢狀** comprehension 時反向把它的第一個 iter 併入目前這一層繼續收集——
兩個方向都要處理，否則會漏算或重複算某個 `ast.Call`。

comprehension 內的 walrus 是 PEP 572 明文例外（Opus 於 review 三審後自查發現，
非 Codex 提出，且是**把 comprehension 升格為 scope 這一輪自己引入的**誤報）：
comprehension 雖然是 scope，但**它裡面的 assignment expression `(x := ...)`
綁在 containing scope**，不是 comprehension 的隱含 scope。實測印證：
`import os as x` + `[(x := i) for i in items]` 之後外層的 `x` 已被重綁成
`items` 的最後一個元素（型別 `str`），所以那之後的 `x.replace(...)` **不是**
違規（見 GREEN 36）。因此 `_shadowed_names` 必須破例往下鑽進巢狀
comprehension——但 `_comprehension_walrus_targets` **只收 `NamedExpr` 的
target，絕不收 generator 的 for-target**（後者才真的屬於 comprehension 自己
的 scope，收回外層就會重演三審那條 P1 的漏抓）。這個「只收一半」的邊界由
GREEN 36 與 RED 30/32/33/34 兩側夾住。

Comprehension 不可能包含 `import`/`global`/`nonlocal` 陳述式（Python 語法
本身禁止，comprehension 內只能是運算式），所以 `_own_bindings_at_level`/
`_directive_names` 不需要為 comprehension scope 特別處理，天然回傳空集合。
`async for` 沒有獨立的 `AsyncComprehension` 節點型別——`comprehension.
is_async` 只是既有 `ListComp`/`SetComp`/`DictComp`/`GeneratorExp` 節點上
`ast.comprehension` 的一個旗標，本節所有規則對 `async for` 一體適用，不需要
額外分支（實測驗證見 RED-32~34 同族案例與自我複查案例，`async for` 的行為
與 `for` 完全一致）。class body 內的 comprehension 同理不需特殊處理：實測
`class C: vals = [x for x in x.replace(1,2)]`（`x` 是模組層 alias）確實會
呼叫到 `x.replace`，與本守衛判定一致，不屬於既有「class body import 對
method 可見性」那條已知不精確的範圍。

見 RED 30（基本形，comprehension target 不得剔除外層同名 binding）、
GREEN 31（防修法只做一半——不下鑽但不真的建 scope——造成的反向誤報）、
RED 32/33/34（`SetComp`/`DictComp`/`GeneratorExp` 同族逐種各一格，不合併）、
RED 35（第一個 iter 在外層 scope 求值這條語意）。

resolver 層才是問題所在，不只是 walrus helper（Codex PR review 五審抓到第五
條 P1，2026-08-06 裁決）：`_own_direct_nodes` 把函式/lambda/class 的整個節點
都當成「子 scope 的東西」下鑽，但 Python 有一類子節點是**在外層（enclosing）
scope 求值**的——參數預設值、參數 annotation、`returns`、decorator、class
bases/keywords。當子 scope 剛好用**同名參數**遮蔽了那個名字時，這些子節點被
誤歸屬到子 scope 掃描，於是子 scope 的 shadow 把外層 binding 剔除，造成假綠。
實測驗證（Opus 復現）：`import os as x` + `def f(a,b): callback = lambda
x=x.replace(a, b): x`——lambda 的預設值 `x.replace(a, b)` 在 lambda **物件建立
時、於外層（f 的）scope** 求值（探針物件在**尚未呼叫** lambda 時就已被呼叫
到），這裡的 `x` 解析到的是外層模組層的 `os`，即使 lambda 自己的參數也叫
`x`；模組層 decorator 同理在同名 `def` 綁定**之前**求值（可執行、是真違規）。

修法：抽出唯一一份規則 `_enclosing_evaluated_children(node)`，回傳某個自帶
scope 的節點裡「在外層 scope 求值」的子運算式（照語言規格列：`FunctionDef`/
`AsyncFunctionDef` 的 decorator_list/defaults/kw_defaults/returns/各參數
annotation；`Lambda` 的 defaults/kw_defaults；`ClassDef` 的 decorator_list/
bases/keywords 的 `.value`）。`_own_direct_nodes` 撞到巢狀 scope 節點時，除了
照舊把節點本身收進來（偵測同名遮蔽），還要下鑽這些 enclosing-evaluated 子樹
併入**父** scope 的 own_nodes；子 scope 自己解析時用同一份規則算出的 `skip`
集合排除同樣這些子樹，避免同一段 `ast.Call` 被父子兩層各算一次。
`_comprehension_walrus_targets` 內原本自己另外維護一份只涵蓋
`args.defaults`/`kw_defaults` 的簡化版「什麼在外層求值」規則，改為呼叫這支
共用函式——同一規則兩份實作正是這條 P1 的溫床，本卡 spec-113 的主題就是單一
決策所有權。

見 RED 40（lambda 參數預設值 + 同名參數）、RED 41（`FunctionDef` 參數預設值 +
同名參數）、GREEN 42（lambda body 內用同名參數——防修法把 default 拉回外層時
誤把 body 也一起拉走）、RED 43（參數 annotation + 同名參數，Opus 自查發現，
Codex 未列）、RED 44（模組層 lambda 預設值 + 同名參數，證明這條與 scope 深度
無關）。

已排除、屬停損線豁免的形狀：`def f(): @os.replace(...)\n def os(): ...`（decorator
+ **函式內**同名 `def`）在執行期是 `UnboundLocalError`——同名 `def` 讓該名字
成為這層函式的 local，decorator 求值時該 local 尚未賦值，是寫不出可運行程式碼
的形狀，不需要處理（模組層版本的同一形狀不受此限，因為模組層沒有「未賦值前先
讀」的編譯期限制，見上方「Global/Nonlocal」段落已鎖的 RED/GREEN 案例族）。

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


# Python 3 comprehension（ListComp/SetComp/DictComp/GeneratorExp）有隱含的獨立
# scope，target 不外洩到外層（review P1 三審，2026-08-06 裁決；見檔頂 docstring）。
# 實測驗證：`import os as x` 後 `def f(): [x for x in ()]; return x.__name__`
# 印出 "os"——comprehension 的 for-target 完全不外洩，即使跟外層 alias 同名。
COMPREHENSION_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPE_TYPES = (
    ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
) + COMPREHENSION_TYPES


def _comprehension_first_iter(node):
    """comprehension 的**最外層第一個 generator 的 `iter` 子樹**在**外層
    （enclosing）scope** 求值，comprehension 自己的隱含 scope 只涵蓋
    target/ifs/elt（或 key/value）/後續 generator 的 iter（review P1 三審，
    實測驗證：`class Spy: def replace(self,a,b): ...` 搭配
    `[z for z in y.replace(a,b)]`，`y.replace` 確實在外層被呼叫，且外層的
    `y` 不會被 comprehension 自己的 target `z` 遮蔽——因為兩者本來就不同名；
    另一實測 `import os as x` + `[x for x in x.replace(a,b)]`，第一個 iter
    `x.replace(a,b)` 解析到的是外層模組層的 `x`（os），不是 comprehension 自己
    的 target `x`）。回傳該子樹節點；理論上 comprehension 必有至少一個
    generator，`generators` 為空是防禦性寫法，回傳 None。"""
    if not node.generators:
        return None
    return node.generators[0].iter


def _enclosing_evaluated_children(node) -> list:
    """`node`（一個自帶 scope 的節點：`FunctionDef`/`AsyncFunctionDef`/`Lambda`/
    `ClassDef`）裡「**在外層（enclosing）scope 求值**」的子運算式清單——這些子
    運算式雖然語法上長在 `node` 底下，但 Python 真正求值它們的時機/scope 是
    `node` **外面那一層**，不是 `node` 自己的 body（review 五審 P1，Codex 抓到；
    詳見檔頂 docstring「resolver 層」段）。

    照 Python 語言規格窮舉，不照「我想到的情境」列（四輪 scope P1 的教訓，見
    `_comprehension_walrus_targets` docstring 同一句）：
    - `FunctionDef`/`AsyncFunctionDef`：`decorator_list`、`args.defaults`、
      `args.kw_defaults`（跳過 `None`——只有 keyword-only 且無預設的槽位才是
      `None`）、`returns`、以及 `posonlyargs`/`args`/`kwonlyargs`/`vararg`/
      `kwarg` 各參數的 `annotation`（跳過 `None`）。
    - `Lambda`：只有 `args.defaults`/`args.kw_defaults`——lambda 語法不允許
      decorator/annotation/return type。
    - `ClassDef`：`decorator_list`、`bases`、`keywords` 的**`.value`**（不是
      `keyword` 節點本身；`keyword.arg` 只是參數名字串，不是運算式）。

    `type_params`（PEP 695 泛型語法，Python 3.12+）不處理：本庫不使用這個語法，
    且執行環境的 `ast` 模組版本不保證有這個欄位——真要支援時形狀與這裡一致
    （bound/default 也是在外層求值），列在這裡供下一個維護者參考。

    這是全檔**唯一一份**「什麼在外層求值」的規則實作——`_own_direct_nodes`（父
    scope 下鑽收集）與 `_comprehension_walrus_targets`（判斷 walrus 是否穿越
    lambda 邊界）都呼叫這支函式，不各自維護一份（單一所有權，本卡 spec-113 的
    主題；同一規則兩份實作正是第六條 P1 的溫床）。"""
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
    """`scope` 自己這一層的節點：遞迴 body，但**停在巢狀 scope 邊界**（巢狀 scope
    節點本身會被收進來一次，用來偵測「巢狀 def/class 同名遮蔽」，但不下鑽進它的
    內容——內容由遞迴呼叫 `_resolve_scope` 時單獨處理）。與 113b-T3
    `_direct_scope_nodes` 同構手法，套用在不同問題上（那支鎖委派名，這支鎖
    import binding）。

    comprehension 例外（review P1 三審）：若 `scope` 本身就是一個
    comprehension，它的第一個 generator 的 `iter` 子樹**不屬於這一層**（已在
    enclosing scope 被收走，見 `_comprehension_first_iter`），用 `skip` 排除，
    避免同一段 Call 被兩層各算一次。若在往下走的過程中撞到**巢狀**
    comprehension（`child` 是 comprehension 且 `child is not scope`），它的第
    一個 iter 子樹則要反向**併入目前這一層**（因為那個子樹是在目前這一層求值）
    繼續收集，但仍受一般巢狀 scope 邊界規則管轄。

    函式/lambda/class 例外（review 五審 P1，同構手法的推廣）：若 `scope` 本身
    就是一個 `FunctionDef`/`AsyncFunctionDef`/`Lambda`/`ClassDef`，它的
    decorator/參數預設值/annotation/`returns`/class bases/keywords（見
    `_enclosing_evaluated_children`）**不屬於這一層**（已在 enclosing scope
    被收走），同樣用 `skip` 排除。若在往下走的過程中撞到**巢狀**的
    函式/lambda/class，它們的這類子樹則要反向**併入目前這一層**繼續收集——
    與 comprehension 那條分支是同一個「skip 在自己這層排除、在父層收集巢狀
    子節點的對應子樹」手法，只是換一組節點型別，共用同一套 `skip` 機制，
    不新造第二套。"""
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


def _directive_names(own_nodes: list) -> tuple:
    """回傳 (global_names, nonlocal_names)：這一層直接宣告的 `global`/`nonlocal`
    名字，分開收集——因為兩者在 `_resolve_scope` 裡解析目標不同（`global` 回
    module/root scope；`nonlocal` 回最近 enclosing function scope），不能共用
    同一套處置（review P1 二審，2026-08-06 裁決，見檔頂 docstring）。"""
    global_names = set()
    nonlocal_names = set()
    for n in own_nodes:
        if isinstance(n, ast.Global):
            global_names.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            nonlocal_names.update(n.names)
    return global_names, nonlocal_names


def _comprehension_walrus_targets(comp) -> set:
    """巢狀 comprehension 內所有 walrus（`:=`）target 的名字集合。

    PEP 572 明文：comprehension 裡的 assignment expression **綁在 containing
    scope**（不是 comprehension 的隱含 scope）。實測印證：`import os as x` +
    `[(x := i) for i in items]` 之後，外層的 `x` 已被重綁成 `items` 的最後一個
    元素（型別 `str`），不再是 os 模組——所以那之後的 `x.replace(...)` 不是違規。

    這是唯一需要「明知 comprehension 是 scope、卻仍往裡面看一眼」的例外，因此
    刻意抽成獨立函式而不是塞進 `_shadowed_names` 的主迴圈：它只收 `NamedExpr`
    的 target，**不收 generator 的 for-target**（那個屬於 comprehension 自己的
    scope，收進外層就會重演 review 三審那條 P1 的漏抓）。

    **穿越 comprehension、不得穿越 lambda**（review 四審 P1，Codex 抓到；本函式
    初版用 `ast.walk` 一律下鑽，這是 Opus 自己寫的 bug）：PEP 572 的「綁在
    containing scope」只適用於 comprehension 自己的 walrus——**巢狀 comprehension
    的 walrus 一路往最外層那個 non-comprehension scope 綁**（`[[(x := c) for c in r]
    for r in rows]` 也算，見 GREEN 36 家族），但**巢狀 lambda 內的 walrus 綁在
    lambda 自己的 scope**、完全不外洩。實測印證：`import os as x` +
    `[lambda value: (x := value) for _ in items]`，把每個 lambda 都呼叫過之後，
    外層 `x` **仍然是 os 模組**（型別 `module`、`__name__` 為 `os`）——所以那之後
    的 `x.replace(...)` 是真違規（見 RED 37）。初版 `ast.walk` 會把 lambda 裡那個
    `NamedExpr` 誤算成外層 shadow，把 `x → os` 剔除 ⇒ 假綠。

    因此改為 scope-aware 遞迴：遇到 `COMPREHENSION_TYPES` 繼續下鑽（walrus 要往外
    綁），遇到**任何非 comprehension 的 scope 節點**（`Lambda`／`FunctionDef`／
    `AsyncFunctionDef`／`ClassDef`）**立刻停止**。實務上 comprehension 內只可能出現
    `Lambda`（comprehension 是運算式，塞不進 `def`／`class` 陳述式），但這裡照
    語言規格列 scope 節點型別、不照「我想到的情境」列——四輪 scope P1 的教訓。

    「哪些子運算式仍在外層求值」這條規則本身**不在這裡重寫**（review 五審 P1，
    2026-08-06 裁決）：直接呼叫 `_enclosing_evaluated_children`——全檔唯一一份
    「什麼在外層求值」的規則實作，`_own_direct_nodes` 也用同一份。本函式初版
    自己內嵌一份只涵蓋 `args.defaults`/`kw_defaults` 的簡化版（docstring 舊版
    甚至寫「`ClassDef` 不處理，class 是陳述式塞不進 comprehension」），與後來
    `_own_direct_nodes` 需要的完整版（decorator/annotation/returns/ClassDef
    bases）分岔成兩份——同一規則兩份實作正是第六條 P1 的溫床，改為單一所有權。
    """
    out = set()
    stop_types = tuple(t for t in SCOPE_TYPES if t not in COMPREHENSION_TYPES)

    def visit(node):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        if isinstance(node, stop_types):
            # lambda 等自帶 scope：**本體**的 walrus 綁在它自己那層、不外洩
            # （review 四審 P1）；但預設值/annotation/decorator 等在外層求值，
            # 仍要收（見 `_enclosing_evaluated_children`）。
            children = _enclosing_evaluated_children(node)
        else:
            children = ast.iter_child_nodes(node)  # comprehension 與一般運算式繼續往下
        for child in children:
            visit(child)

    visit(comp)
    return out


def _shadowed_names(scope, own_nodes: list, global_names: set, nonlocal_names: set) -> set:
    """這一層 scope 被**非 import 手段**重新綁定的名字集合：函式自己簽名上的
    參數、賦值/for-target/with-as（皆落在 `ast.Name` + `Store`/`Del`，含
    tuple 拆包、海象 `:=`）、`except E as X`、巢狀 `def`/`class` 同名。用來把
    「繼承自外層」的 binding 剔除——但這一層自己 import 的名字不剔除（見檔頂
    docstring「import 勝」決策，四條優先序的第①條）。

    `global`/`nonlocal` 宣告的名字**不**算在這個一般 shadow 集合裡：它們不是
    重新綁定，是改變名稱解析的方向，各自有專屬的解析路徑（見 `_resolve_scope`
    第②③條），不能被這裡的「直接剔除」處置。之所以仍要傳入 `global_names`/
    `nonlocal_names` 並在最後扣掉，是防「同一層某名字既被宣告 global/nonlocal、
    又被 Assign 重新賦值」的病態交互（例如 `global os; os = os`）——那個賦值
    改的是外層/module 的既有 binding，不是建立新的區域名，不該被這個一般集合
    誤收，必須讓 `_resolve_scope` 的 global/nonlocal 專屬路徑接手判斷。"""
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
            # PEP 572 例外（Opus 於 review 三審後自查發現，見檔頂「comprehension
            # 內的 walrus」段）：comprehension 是 scope，但**它裡面的 walrus
            # `(x := ...)` 綁的是「外層」scope**，不是 comprehension 自己的。
            # 所以這一層必須破例往下鑽進巢狀 comprehension——但**只收 NamedExpr
            # 的 target**，絕不收它的 for-target（那個才真的屬於 comprehension
            # 自己的 scope，收了就會重演三審那條 P1 的漏抓）。
            names.update(_comprehension_walrus_targets(n))

    names -= global_names
    names -= nonlocal_names
    return names


def _resolve_scope(scope, inherited_mod: dict, inherited_call: dict,
                    root_mod: dict = None, root_call: dict = None) -> list:
    """呼叫端比對規則（receiver + attribute 必須同時匹配，技術要點第 2 節），
    scope-aware 版本：先算這一層自己的 binding + shadow，合併出這一層「有效」
    的 mod_map/call_map，比對只屬於這一層的 ast.Call，再對每個巢狀 scope 遞迴、
    把這一層算好的 map 往下傳。回傳 (lineno, "receiver.attr" 或裸名) 清單。

    `root_mod`/`root_call` 是 Module（root）scope 自己的 import binding——第一次
    呼叫（`root_mod is None`）代表 `scope` 本身就是 Module，這一層算出的
    `own_mod`/`own_call` 直接拿來當 root；之後每一層遞迴原封不動往下傳（不重算、
    不隨 inherited 變動），讓任意深度的 `global` 宣告都能回頭查到 module 層的
    binding（review P1 二審，2026-08-06 裁決，見檔頂 docstring 四條優先序）。"""
    own_nodes = _own_direct_nodes(scope)
    own_mod, own_call = _own_bindings_at_level(own_nodes)
    global_names, nonlocal_names = _directive_names(own_nodes)
    shadowed = _shadowed_names(scope, own_nodes, global_names, nonlocal_names)

    if root_mod is None:
        root_mod, root_call = own_mod, own_call

    # 四條優先序（照順序實作，逐條交代；見檔頂 docstring 復現形狀）：
    # ① 這一層自己的 import binding 最優先 —— 用 own_mod/own_call 蓋掉 inherited。
    #    下面②③④分支都會先檢查「這個名字是不是這一層自己 import 的」，是的話
    #    一律放行不干預（病態交互 `global x; import os as x` 由這條決勝）。
    mod_map = dict(inherited_mod)
    mod_map.update(own_mod)
    call_map = dict(inherited_call)
    call_map.update(own_call)

    # ④ 其餘一般 shadow 名字（參數/賦值/for/with/except/巢狀 def 同名，已排除
    #    global/nonlocal）——直接把繼承來的 binding 剔除，除非規則①已經蓋過。
    #    （放在②③之前執行，因為②③要對 global/nonlocal 名字做更精準的處置，
    #    不能被這裡的無差別剔除搶先清空。）
    for name in shadowed:
        if name not in own_mod:
            mod_map.pop(name, None)
    for name in shadowed:
        if name not in own_call:
            call_map.pop(name, None)

    # ② global 宣告的名字 → 一律用 root（module）maps 解析；root 沒有這個名字
    #    的 binding 就視為無 binding（從 map 移除），不可退回 inherited（見
    #    GREEN 29：root 完全沒有該名字，即使 inherited 裡還留著舊值也要清掉）。
    for name in global_names:
        if name in own_mod:
            continue
        if name in root_mod:
            mod_map[name] = root_mod[name]
        else:
            mod_map.pop(name, None)
    for name in global_names:
        if name in own_call:
            continue
        if name in root_call:
            call_map[name] = root_call[name]
        else:
            call_map.pop(name, None)

    # ③ nonlocal 宣告的名字 → 解析到最近 enclosing function scope，用 inherited
    #    map 近似（維持上一輪就有的行為）。mod_map/call_map 此刻已經是 inherited
    #    疊上 own 的結果，nonlocal 名字不在 own_mod/own_call 時本來就還留著
    #    inherited 的值——這裡不需要、也不應該再動它；刻意不寫程式碼是為了讓
    #    「nonlocal 走 inherited、global 走 root」這兩條路徑在實作上真的分岔
    #    （RED 28 鎖住這件事：若誤把 nonlocal 也導向 root，該格會從 RED 變 GREEN）。

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
            violations += _resolve_scope(node, mod_map, call_map, root_mod, root_call)

    return violations


def _violations_from_tree(tree: ast.Module) -> list:
    """回傳 (lineno, "receiver.attr" 或裸名) 的違規清單。對外行為/回傳格式與
    scope-aware 改寫前完全相同，只是內部從扁平 dict 換成逐 scope 遞迴解析，
    root_mod/root_call 於首次遞迴（`scope` 即 Module）內自動算出。"""
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
    # 22: review P1 復現形狀 A——`global os` 不是重新綁定，是把這一層對 os 的
    #     讀取解析導回 module scope 既有 binding；原本被誤當成一般 shadow 剔除
    #     繼承 binding，造成這格假綠
    (22, "import os\ndef f(a, b):\n    global os\n    os.replace(a, b)\n"),
    # 23: review P1 復現形狀 B——`nonlocal os` 同理，解析導回最近 enclosing
    #     function scope 既有 binding（不是模組層），巢狀函式 + nonlocal 雙重路徑
    (23, "def outer():\n    import os\n    def inner(a, b):\n        nonlocal os\n        os.replace(a, b)\n    return inner\n"),
    # 24: review P1 復現形狀 C——alias + tempfile 配對，不只 os，確認 global 的
    #     修法不是只對 "os" 這個名字碰巧生效
    (24, "import tempfile as tf\ndef f():\n    global tf\n    return tf.mkstemp()\n"),
    # 25: Codex 特別要求——同一 scope 內 global 宣告與「另一個無關的一般 shadow
    #     手段」並存時，global 宣告的名字仍要被抓到（不能靠既有 alias 矩陣間接
    #     通過，必須是這格自己證明 global 分支真的獨立生效）
    (25, "import os\ndef f(a, b):\n    global os\n    unrelated_local = 1\n    os.replace(a, b)\n    return unrelated_local\n"),
    # 26: review P1 二審復現形狀——module 層 `x` 綁 tempfile、中間層 outer 用同名
    #     alias `x` 改綁 os，最深層 inner 的 `global x` 必須跳過 outer、直接回
    #     module 拿 tempfile，才會判定違規；只做「不 pop」的錯誤修法會在這裡漏抓
    #     （因為它會保留 outer 那層 inherited 的 os，配不上任何 PAIRS）
    (
        26,
        "import tempfile as x\n"
        "def outer():\n"
        "    import os as x\n"
        "    def inner():\n"
        "        global x\n"
        "        x.mkstemp()\n"
        "    return inner\n",
    ),
    # 28: nonlocal 必須解析到最近 enclosing function（outer 的 tempfile），不是
    #     module（json，無關配對）——本格證明 global 與 nonlocal 走的是兩條不同
    #     路徑：若實作誤把 nonlocal 也導向 root，這格會從 RED 變成 GREEN
    (
        28,
        "import json as x\n"
        "def outer():\n"
        "    import tempfile as x\n"
        "    def inner():\n"
        "        nonlocal x\n"
        "        x.mkstemp()\n"
        "    return inner\n",
    ),
    # 30: Codex PR review 三審復現形狀——外層 alias `x -> os`、comprehension 的
    #     for-target 也叫 `x`（comprehension 隱含獨立 scope，target 不外洩），
    #     comprehension 結束後外層 `x.replace(...)` 仍是真違規，不得因為守衛
    #     誤把 comprehension 的 target 當成「這一層」的 shadow 而剔除外層 binding
    (
        30,
        "import os as x\n"
        "def f(a, b):\n"
        "    values = [x for x in ()]\n"
        "    x.replace(a, b)\n"
        "    return values\n",
    ),
    # 32: 同 #30 但換 SetComp——四種 comprehension 節點型別逐種列，不合併成一格
    (
        32,
        "import tempfile as x\n"
        "def f():\n"
        "    s = {x for x in ()}\n"
        "    return x.mkstemp()\n",
    ),
    # 33: 同 #30 但換 DictComp
    (
        33,
        "import tempfile as x\n"
        "def f():\n"
        "    d = {x: 1 for x in ()}\n"
        "    return x.mkstemp()\n",
    ),
    # 34: 同 #30 但換 GeneratorExp
    (
        34,
        "import tempfile as x\n"
        "def f():\n"
        "    g = (x for x in ())\n"
        "    return x.mkstemp()\n",
    ),
    # 35: comprehension 最外層第一個 generator 的 iter 在**外層 scope**求值
    #     （實測驗證，見檔頂 docstring）——這裡的 `x.replace(a,b)` 是外層模組
    #     層的 `os`，即使 comprehension 自己的 target 也叫 `x`；只把
    #     comprehension「一刀切」當單一 scope、不特別處理第一個 iter 的錯誤
    #     實作會在這格漏抓（本輪最重要的判別器）
    (
        35,
        "import os as x\n"
        "def f(a, b):\n"
        "    return [x for x in x.replace(a, b)]\n",
    ),
    # 37: comprehension 內的 **lambda** 裡的 walrus 綁在 lambda 自己那層、不外洩
    #     （實測：把每個 lambda 都呼叫過之後外層 x 仍是 os 模組），所以最後一行
    #     仍是模組 alias 的 os.replace ⇒ 違規。`_comprehension_walrus_targets`
    #     初版用 `ast.walk` 一律下鑽，會把這個 NamedExpr 誤算成外層 shadow 而
    #     假綠（review 四審 P1）。與 GREEN-38 成對鎖住「穿越 comprehension、
    #     不得穿越 lambda」這條邊界
    (
        37,
        "import os as x\n"
        "def f(items, a, b):\n"
        "    callbacks = [lambda value: (x := value) for _ in items]\n"
        "    return x.replace(a, b)\n",
    ),
    # 40: review 五審 P1（Codex 抓到，resolver 層而非 walrus helper）——lambda 的
    #     **參數預設值**在物件建立時、於**外層**（f 的）scope 求值，即使 lambda
    #     自己的參數也叫 x（遮蔽外層同名）。錯誤實作把整個 lambda 節點都當成子
    #     scope 掃描，讓子 scope 的參數遮蔽誤剔除外層 binding，造成假綠
    (
        40,
        "import os as x\n"
        "def f(a, b):\n"
        "    callback = lambda x=x.replace(a, b): x\n"
        "    return callback\n",
    ),
    # 41: 同 #40 但換 FunctionDef（不是 lambda）的參數預設值——證明這條規則不是
    #     只對 lambda 生效，函式定義的 args.defaults 同樣在外層求值
    (
        41,
        "import os\n"
        "def f(a, b):\n"
        "    def callback(os=os.replace(a, b)):\n"
        "        return os\n"
        "    return callback\n",
    ),
    # 43: 參數 **annotation**（Opus 自查發現，Codex 五審未列）——annotation 與
    #     defaults 同樣在外層求值，同名參數 `os: os.replace(...)` 的 annotation
    #     解析到的是外層 import，不是這個參數自己
    (
        43,
        "import os\n"
        "def f(a, b):\n"
        "    def inner(os: os.replace(a, b)):\n"
        "        return os\n"
        "    return inner\n",
    ),
    # 44: 模組層 lambda 預設值——證明這條與 scope 深度無關，即使 lambda 直接掛在
    #     module 層（root scope），預設值仍在外層（module）求值
    (44, "import os as x\ncb = lambda x=x.replace('a', 'b'): x\n"),
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
    # 27: RED-26 的鏡像對調——module 層 `x` 綁 os、outer 層 `x` 改綁 tempfile，
    #     inner 的 `global x` 必須跳過 outer、回 module 拿到 os，配不上 PAIRS。
    #     本格是本輪最重要的判別器：只做「不 pop」的錯誤修法會在這裡**誤報**
    #     （因為它會保留 outer 那層 inherited 的 tempfile，誤配成違規）——這格
    #     才真正證明 global 分支「有回 module」而不只是「沒被 pop」
    (
        27,
        "import os as x\n"
        "def outer():\n"
        "    import tempfile as x\n"
        "    def inner():\n"
        "        global x\n"
        "        x.mkstemp()\n"
        "    return inner\n",
    ),
    # 29: `global` 宣告但 module 根本沒有該名字的 binding（module 層完全沒有
    #     `import ... as x`）——依優先序第②條，root 沒有就視為無 binding、直接
    #     從 map 移除，不可退回 outer 的 inherited（os），鎖住「root 沒有就清掉、
    #     不落回 inherited」這一半（review P1 二審提出的具體反例）
    (
        29,
        "def outer():\n"
        "    import os as x\n"
        "    def inner():\n"
        "        global x\n"
        "        x.replace(a, b)\n"
        "    return inner\n",
    ),
    # 31: RED-30 的鏡像對調——comprehension **內**使用 target `x`（items 的元素，
    #     字串），不是外層模組 alias，不得誤報。這格防的是修法只做一半（不下鑽
    #     但不真的把 comprehension 建成 scope）造成的反向誤報——那種半套實作會
    #     讓這格從 GREEN 變成誤報的 RED
    (
        31,
        "import os as x\n"
        "def f(items):\n"
        "    return [x.replace('a','b') for x in items]\n",
    ),
    # 36: PEP 572 例外（Opus 於 review 三審後自查發現，非 Codex 提出）——
    #     comprehension 是 scope，但**它裡面的 walrus 綁在外層**，所以
    #     `[(x := i) for i in items]` 之後外層的 `x` 已經不是模組 alias 了
    #     （實測：型別變成 str），那之後的 `x.replace(...)` 不是違規。
    #     這格鎖的是「把 comprehension 升格為 scope」時**新引入**的誤報：
    #     若 `_shadowed_names` 不破例去收巢狀 comprehension 的 NamedExpr
    #     target，這格會誤報。反向的護欄是 RED-30/32/33/34（那些證明破例
    #     只收 walrus target、沒有把 for-target 一起收回外層）
    (
        36,
        "import os as x\n"
        "def f(items):\n"
        "    vals = [(x := i) for i in items]\n"
        "    return vals and x.replace('a', 'b')\n",
    ),
    # 38: GREEN-36 的「穿越」那一半——**巢狀** comprehension 的 walrus 一樣綁在
    #     最外層那個 non-comprehension scope（PEP 572），所以外層 x 之後已不是
    #     模組 alias。與 RED-37 成對：37 鎖「不得穿越 lambda」，38 鎖「必須穿越
    #     comprehension」。少了 38，把 helper 改成「遇到任何巢狀節點都停」的過度
    #     修正會在這格誤報而沒人發現
    (
        38,
        "import os as x\n"
        "def f(rows):\n"
        "    v = [[(x := c) for c in r] for r in rows]\n"
        "    return v and x.replace('a', 'b')\n",
    ),
    # 39: RED-37 的「但預設值例外」那一半（Opus 在四審修完後自查窮舉 walrus 的
    #     所有槽位時發現，非 Codex 提出）——函式/lambda 的**參數預設值**是在
    #     「函式物件建立時、於外層 scope」求值，所以預設值裡的 walrus **仍綁外層**。
    #     實測：這段**不必呼叫任何 lambda**，外層 x 建立當下就已是 'b'（str）。
    #     RED-37（本體）與 GREEN-39（預設值）成對：只看「是不是 lambda」而不分
    #     「本體 vs 預設值」的實作，必在其中一格出錯
    (
        39,
        "import os as x\n"
        "def f(items):\n"
        "    cbs = [lambda v=(x := c): v for c in items]\n"
        "    return cbs and x.replace('a', 'b')\n",
    ),
    # 42: RED-40 的鏡像對調——lambda **body** 內使用同名參數 `x`（不是預設值），
    #     不得因為修法把預設值拉回外層求值，就連 body 也一併誤拉走。這格鎖住
    #     「只把 defaults/kw_defaults 移到外層，body 仍留在 lambda 自己的 scope」
    #     這條邊界——若實作誤把整個 Lambda 節點的求值都算進外層，這格會從 GREEN
    #     變成誤報的 RED
    (
        42,
        "import os as x\n"
        "def f(a, b):\n"
        "    return lambda x: x.replace(a, b)\n",
    ),
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
