"""金絲雀 A（javdb-api）分組與「會紅」故障注入守衛（零網路，跑 CI）。

金絲雀 A 必須進 GROUP_A、不得進 GROUP_B：進 GROUP_B ＝ classify_one row 6
一律 skip ＝這顆燈永遠不紅（spec-132 B8 / F5）。
"""
import ast
import inspect
import textwrap

from tests.smoke._canary_core import (
    GROUP_A,
    GROUP_B,
    _CENSORED,
    classify_one,
)


class TestGroupMembership:
    def test_api_canary_is_not_group_b(self):
        # 加進 GROUP_B ＝ 這顆燈永遠 skip、永遠不紅（mutation: api-canary-not-in-group-b）
        assert "javdb-api" not in GROUP_B

    def test_api_canary_is_group_a_and_censored(self):
        assert "javdb-api" in GROUP_A
        assert "javdb-api" in _CENSORED


class TestApiCanaryCanGoRed:
    def test_reachable_but_empty_is_fail(self):
        # F5 本體：probe 說連得到 ＋ search 回 None ⇒ 必須 fail（mutation: api-canary-actually-reds）
        assert (
            classify_one(None, True, "SONE-205", "javdb-api") == "fail"
        )

    def test_unreachable_is_skip(self):
        # 對照：連不上不算壞
        assert (
            classify_one(None, False, "SONE-205", "javdb-api") == "skip"
        )

    def test_web_javdb_none_still_skips(self):
        # 對照：網頁那條（GROUP_B）行為零回歸
        assert classify_one(None, None, "SSNI-001", "javdb") == "skip"


def _canary_method(func):
    """從函式的 **AST** 取出它呼叫 `_run_canary` 時傳的 `method=`（沒傳回 None ＝ 走 default）。

    🔴 **刻意用 AST 而不是字串比對**（review P2 實證）：
    `'method="search_via_api"' in inspect.getsource(f)` 這種寫法會被
    「**把 kwarg 刪掉、但把同一串字面留在死註解裡**」整個繞過——
    review 端在沙盒實跑過，那樣改完守衛仍然 8 passed，
    而那正是本守衛要擋的最惡性情境。反方向也會誤判：換成單引號
    `method='search_via_api'` 是功能等價的重構，字串比對卻會判紅。
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_run_canary":
            for kw in node.keywords:
                if kw.arg == "method":
                    return ast.literal_eval(kw.value)
            return None
    raise AssertionError(f"{func.__name__} 裡找不到 _run_canary(...) 呼叫")


class TestTwoCanariesCallDifferentMethods:
    """🔴 兩顆燈必須打**不同**的方法（BE-TEST-11：兩條分支不得回同一份東西）。

    Opus 補：卡片 DoD E-6 原本沒有任何機械鎖。
    `method=` 被改回預設之後，兩顆燈會一起打編排過的 `search()`——
    ⇒ A 那顆會因為 `search()` 自己會降級 HTML 而**永遠是綠的**，
    F5 想裝的偵測器等於不存在。而這件事**只有跑活站才看得出來**。
    """

    def test_web_canary_calls_search_via_html(self):
        from tests.smoke.test_source_canary import test_javdb_canary as _web
        assert _canary_method(_web) == "search_via_html", (
            "網頁金絲雀必須打 search_via_html；打編排過的 search() 會讓它跟 API 那條混在一起"
        )

    def test_api_canary_calls_search_via_api(self):
        from tests.smoke.test_source_canary import test_javdb_api_canary as _api
        assert _canary_method(_api) == "search_via_api", (
            "API 金絲雀必須打 search_via_api；打 search() 的話它會因為自動降級而永遠綠"
        )

    def test_run_canary_default_method_is_search(self):
        """其餘 7 個來源靠 default 走原路——default 被改掉它們會一起壞，而且只有活站看得出來。"""
        from tests.smoke.test_source_canary import _run_canary
        assert inspect.signature(_run_canary).parameters["method"].default == "search"
