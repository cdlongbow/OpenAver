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

    🔴 **第四個 patch 是 0.15.1 / TASK-132b-T3 補的，不是可有可無的**：
    T3 之後 `JavDBScraper.search()` 會**先打 App 資料介面**，只 patch `curl_requests.get`
    已經不夠——本檔會真的連上活站（實測 5 支紅、耗時 17.4 秒）。
    把資料介面那條固定成「連不上」，`search()` 就照 CD-132b-4 降級到網頁那條，
    本檔守的仍然是**網頁 shell 的執行契約**，下面每一支的斷言語意逐條不變。

    ⚠️ 這是**加嚴不是放寬**：它讓本檔回到自己 docstring 宣稱的「完全不碰網路」。
    spec-132 B8 禁止的是放寬本檔，不是禁止讓它重新 hermetic。
    """
    return (
        patch.object(javdb, "CURL_CFFI_AVAILABLE", True),
        patch.object(javdb, "_resolve_proxies", lambda url: None),
        patch.object(javdb.curl_requests, "get", get_mock),
        patch.object(javdb_api, "fetch_video", MagicMock(side_effect=_ApiDisabled())),
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
    p1, p2, p3, p4 = _patched_javdb(get_mock)
    with p1, p2, p3, p4, pytest.raises(pytest.skip.Exception) as exc:
        _run_javdb_canary()
    assert "javdb" in str(exc.value)
    # 🔴 沒有這一行，「skip」也可能是資料介面那條丟的例外造成的（grok review P2）
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"


def test_unreachable_is_skip_not_error():
    """連不上 → 金絲雀必須 **skip**（跟 TimeoutError 同一類，不是 parser 壞掉）。"""
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnErr

    get_mock = MagicMock(side_effect=CurlConnErr("refused"))
    p1, p2, p3, p4 = _patched_javdb(get_mock)
    with p1, p2, p3, p4, pytest.raises(pytest.skip.Exception) as exc:
        _run_javdb_canary()
    assert "javdb" in str(exc.value)
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"


def test_transport_exceptions_do_not_escape_the_shell():
    """反向鎖：這兩個例外**絕對不可以**從 `_run_canary` 穿出去。

    穿出去 ＝ pytest ERROR ＝ 例行跑金絲雀時每次都要人工判讀，
    正是 CD-132a-7 說要避免的「假紅」。
    """
    resp = MagicMock(status_code=403, text="blocked")
    p1, p2, p3, p4 = _patched_javdb(MagicMock(return_value=resp))
    with p1, p2, p3, p4:
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
    p1, p2, p3, p4 = _patched_javdb(get_mock)
    with p1, p2, p3, p4:
        with pytest.raises(pytest.skip.Exception) as exc:
            _run_javdb_canary()
    assert "javdb" in str(exc.value)
    assert get_mock.call_count >= 1, "HTML 那條根本沒被走到，這支測試綠得沒有意義"
