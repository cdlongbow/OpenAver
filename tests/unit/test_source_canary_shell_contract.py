"""金絲雀 live shell 的**執行契約**守衛（零網路，跑在 CI）。

為什麼存在（0.15.1 / TASK-132a-T2 的自引回歸）：
javdb 被 Cloudflare 擋下來是**預期中的 skip**（`_canary_core.GROUP_B` ＋
`test_source_canary.py` docstring 都明文寫了「javdb CF-ban」是 expected skip）。
在 0.15.1 之前，403 會在 `javdb._get_html()` 裡被吞成 `None`，`search()` 回 `None`，
金絲雀走 `classify_one` row 6 → skip。

TASK-132a-T2 把 403 改成拋 `SourceBlocked`，而 `_run_canary` 當時**只接 `TimeoutError`**
⇒ 例外直接穿出去，整支金絲雀變成 **ERROR**，而不是 skip。
那是「我們自己的改動打破了自己的測試執行契約」，而且**只有在真的被 CF 擋的時候才會現形**
——owner 本機當時連得上，例行跑全綠，看不到它。

本檔用假的 403 / 連線失敗把那個情境固定下來。
`tests/unit/test_source_canary_logic.py` 守的是**純判斷邏輯**；本檔守的是**live shell 的接線**。
"""
from unittest.mock import MagicMock, patch

import pytest

from core.scrapers import javdb, javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
# 用 `as _` 改名匯入：直接 `import test_javdb_canary` 會讓 pytest **把它當成本檔的測試收集起來**，
# 於是這支 CI unit test 會真的連上 javdb 打網路（實測 2.86s）。改名後就只是個被呼叫的函式。
from tests.smoke.test_source_canary import test_javdb_canary as _run_javdb_canary


def _patched_javdb(get_mock):
    """把 javdb 的**兩條**網路層都換掉，讓 canary 完全不碰網路。

    javdb 屬 Group B，`_run_canary` 不會跑 probe，所以整條路徑是 hermetic 的。

    **曾經有第四個 patch**（把 `javdb_api.fetch_video` 固定成連不上），因為 T3 之後
    `JavDBScraper.search()` 會先打 App 資料介面，只 patch `curl_requests.get` 會真的連上活站。
    **T5 之後它是死碼**：`test_javdb_canary` 已改成 `method="search_via_html"`，
    整條路根本不經過 `search()`（pre-merge branch review 抓到）。

    那個不變式**沒有消失，只是換人守**：
    `tests/unit/test_source_canary_api_group.py` 用 AST 讀 `_run_canary(...)` 的 `method=`，
    把 `test_javdb_canary` 鎖在 `search_via_html`。哪天有人改回 `method="search"`，
    那支會紅——而不是本檔靜靜地開始連活站。
    """
    return (
        patch.object(javdb, "CURL_CFFI_AVAILABLE", True),
        patch.object(javdb, "_resolve_proxies", lambda url: None),
        patch.object(javdb.curl_requests, "get", get_mock),
    )


class _ApiDisabled(RuntimeError):
    """本檔專用：把資料介面那條關掉時丟的例外。

    🔴 **刻意不是 `SourceUnreachable` / `SourceBlocked`**（grok review P2 指出的覆蓋損失）：
    那兩個型別 `_run_canary` 自己會接住並收成 skip
    ⇒ 萬一哪天 `search()` 不再攔資料介面那條的例外，例外會直接被 `_run_canary` 收掉，
    **下面四支測試仍然全綠，但 `curl_requests.get` 的 403 mock 一次都沒被打到**
    ——守衛從此驗不到它宣稱在驗的那條 HTML 路徑。

    用一個 `_run_canary` **不認識**的型別，那個回歸就會讓本檔變成 ERROR（＝紅），
    這正是本檔存在的理由。
    """


@pytest.mark.parametrize("status_code", [403, 429, 503])
def test_cf_ban_is_skip_not_error(status_code):
    """被擋（403/429/503）→ 金絲雀必須 **skip**，不得 ERROR 也不得 fail。"""
    resp = MagicMock(status_code=status_code, text="blocked")
    get_mock = MagicMock(return_value=resp)
    p1, p2, p3 = _patched_javdb(get_mock)
    with p1, p2, p3, pytest.raises(pytest.skip.Exception) as exc:
        _run_javdb_canary()
    assert "javdb" in str(exc.value)
    # 🔴 沒有這一行，「skip」也可能是資料介面那條丟的例外造成的（grok review P2）
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"


def test_unreachable_is_skip_not_error():
    """連不上 → 金絲雀必須 **skip**（跟 TimeoutError 同一類，不是 parser 壞掉）。"""
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

    get_mock = MagicMock(side_effect=CurlConnErr("refused"))
    p1, p2, p3 = _patched_javdb(get_mock)
    with p1, p2, p3, pytest.raises(pytest.skip.Exception) as exc:
        _run_javdb_canary()
    assert "javdb" in str(exc.value)
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"


def test_transport_exceptions_do_not_escape_the_shell():
    """反向鎖：這兩個例外**絕對不可以**從 `_run_canary` 穿出去。

    穿出去 ＝ pytest ERROR ＝ 例行跑金絲雀時每次都要人工判讀，
    正是 CD-132a-7 說要避免的「假紅」。
    """
    resp = MagicMock(status_code=403, text="blocked")
    p1, p2, p3 = _patched_javdb(MagicMock(return_value=resp))
    with p1, p2, p3:
        try:
            _run_javdb_canary()
        except pytest.skip.Exception:
            pass  # 正確
        except (SourceUnreachable, SourceBlocked) as e:  # pragma: no cover
            pytest.fail(f"transport 例外穿出了 canary shell：{type(e).__name__}")


def test_http_200_empty_parse_still_reaches_a_verdict():
    """200 ＋ 空解析**不得**被新的 transport `except` 攔走——它必須走完 `classify_one`。

    ⚠️ **這一條驗不到「紅」，而且驗不到是對的**：javdb 屬 `GROUP_B`，沒有 probe 可以分辨
    「站方掛了」與「站方改版把我們的 selector 打壞了」，所以 `classify_one` row 6 對它
    **本來就一律判 skip**（`_canary_core.py` 的 6-state 表）。
    「200-but-empty → red」是 **Group A** 才有的判定（row 4，靠 probe 撐起來），
    而本檔測的 javdb 不在那一組。

    ⇒ 這條鎖住的是**它有走到判決**：不是未捕捉的例外、也不是被上面那個
    `except (SourceUnreachable, SourceBlocked)` 提早吞掉。Group A 的 row-4 判定
    由 `tests/unit/test_source_canary_logic.py` 直接對 `classify_one` 驗，不在本檔。
    """
    resp = MagicMock(status_code=200, text="<html><body>nothing</body></html>")
    get_mock = MagicMock(return_value=resp)
    p1, p2, p3 = _patched_javdb(get_mock)
    with p1, p2, p3:
        with pytest.raises(pytest.skip.Exception) as exc:
            _run_javdb_canary()
    assert "javdb" in str(exc.value)
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"


# ============================================================
# 映射／解析失敗的執行契約（Codex PR review round-2 P2 / P3）
# ============================================================

class _Stub:
    """假 scraper：照 `plan` 逐個番號回東西或丟東西。"""

    def __init__(self, plan):
        self._plan = list(plan)
        self.calls = 0

    def search_via_api(self, number):
        self.calls += 1
        item = self._plan.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _video(number, cover="https://tp.spfcas.com/c.jpg"):
    from core.scrapers.models import Video

    return Video(number=number, title="T", source="javdb",
                 detail_url="https://javdb.com/v/x", cover_url=cover)


def _numbers(source, n):
    """把 CANARY_NUMBERS[source] 暫時換成 n 個真番號（形狀要能通過 numbers_match）。"""
    from tests.smoke import test_source_canary as shell

    return patch.dict(shell.CANARY_NUMBERS, {source: [f"SONE-{200 + i}" for i in range(n)]})


def test_mapping_error_is_a_fail_not_a_pytest_error():
    """欄位型別變了 → 必須走 classify/quorum 判紅，不可以變成 pytest ERROR。

    為什麼要這一支：ERROR 會**繞過判決本體**，而且當場中止迴圈——
    後面幾個番號一個都沒驗到。這顆燈存在的理由正是偵測這種形狀改變。
    """
    from tests.smoke import test_source_canary as shell

    stub = _Stub([AttributeError("'int' object has no attribute 'strip'")] * 3)
    with _numbers("javdb-api", 3), \
         patch.object(shell, "_probe_reachable", lambda *a, **k: True), \
         pytest.raises(pytest.fail.Exception) as exc:
        shell._run_canary("javdb-api", stub, method="search_via_api")

    assert "javdb-api" in str(exc.value)
    assert stub.calls == 3, "迴圈被例外中止了——後面的番號沒被驗到"


def test_mapping_error_on_group_b_must_not_become_skip():
    """🔴 反向鎖：Group B 的映射失敗**不可以**被記成 skip。

    Group B（javdb 網頁）享有「全 skip 視為正常」的 CF-ban 豁免。
    如果映射失敗被塞成 `video = None`，它會走 classify_one row 6 → skip → 被豁免吃掉
    ⇒ **真正的 parser 回歸變成靜靜的綠燈**。spec-132 B8 禁止的正是這種放寬。
    """
    from tests.smoke import test_source_canary as shell

    stub = _Stub([TypeError("bad shape")] * 2)
    stub.search_via_html = stub.search_via_api

    # 🔴 **不能用 `pytest.raises(pytest.fail.Exception)`**：`pytest.skip()` 丟的
    # `Skipped` 繼承 `BaseException`，`raises` 收不到，它會直接穿出本函式 ⇒
    # 這一支會被報成 **skipped**，而摘要行的 `N passed, 1 skipped` 讀起來像綠的。
    # 也就是說那樣寫的話，本守衛在陷阱真的出現時「看起來是過的」——
    # 正是它要防的那個形狀。三個出口全部明寫。
    with _numbers("javdb", 2):
        try:
            shell._run_canary("javdb", stub, method="search_via_html")
        except pytest.fail.Exception as e:
            assert "0 healthy" in str(e), f"紅了但理由不對: {e}"
        except pytest.skip.Exception as e:
            raise AssertionError(
                f"Group B 的映射失敗被降級成 skip，會被 CF-ban 豁免吃掉: {e}"
            ) from None
        else:
            raise AssertionError("既沒紅也沒 skip —— 判決根本沒發生")


def test_a_typo_in_method_name_still_errors():
    """反向鎖：`method` 打錯字是**測試自己壞了**，必須 ERROR，不可以被當成「來源紅了」。

    上面那個 broad except 如果罩住了 `getattr`，打錯字會靜靜變成紅燈，
    而我們會去查 javdb 而不是去查自己的測試。
    """
    from tests.smoke import test_source_canary as shell

    with _numbers("javdb-api", 1), pytest.raises(AttributeError):
        shell._run_canary("javdb-api", _Stub([]), method="search_via_typo")


def test_run_canary_returns_the_video_that_passed_not_the_first_number():
    """判綠時要交回**真的通過的那一部**，而不是讓呼叫端自己重抓 `[0]`。

    第一個番號被下架、後面某個過了 → quorum 綠（pass-wins），
    重抓 `[0]` 卻是 None ⇒ 封面解碼驗證被靜默跳過，而那時明明有可用的封面。
    """
    from tests.smoke import test_source_canary as shell

    stub = _Stub([None, _video("SONE-201")])
    with _numbers("javdb-api", 2), \
         patch.object(shell, "_probe_reachable", lambda *a, **k: False):
        got = shell._run_canary("javdb-api", stub, method="search_via_api")

    assert got is not None and got.number == "SONE-201", (
        "回傳的不是通過 quorum 的那一部——呼叫端會拿不到封面"
    )
