"""TASK-127b-T5 —— `pytester` 子 session：mutation 自驗 ＋ AC-3 舊/新 conftest 對照 ＋
六格 flag 矩陣 ＋ 雪崩測試。

`pytest_plugins = ["pytester"]` 已在 root `tests/conftest.py` 註冊（pytest 的硬性
要求：這行必須放在 root conftest）。本專案沒有任何 pytester 先例，本檔是第一支。

為什麼要走 `runpytest_subprocess`（技術要點③，已實測，不走 in-process）：
1. 三個 `OPENAVER_GUARD_*` 環境變數在真 subprocess 才確定生效（開工前實測：
   `runpytest_subprocess` 會繼承父 process 的環境變數，含 `monkeypatch.setenv`
   設的值）。
2. 繞開 `_repo_write_guard._cached_compiled_rules` 的 `lru_cache`——新 process
   ＝新快取，不會撞到 T3 review 抓到的 stale key 問題。
3. 父 session 自己掛的 G1／G2 autouse fixture 不會跟子 session 互相干擾。

🔴 子 session 的兩個根都要指向**假的**根（`OPENAVER_GUARD_REPO_ROOT` /
`OPENAVER_GUARD_TMP_ROOTS`），且**兩者不得互相包含**——否則子 session 的
cwd（在系統 tmp 底下）會落在預設的 tmp 白名單內，任何路徑都放行，驗出來的
是假綠（見 TASK-127b-T5.md「開工前 Opus 已實測的四個前提 ④」；本 branch
自己在 T4 二次 review 時吃過一次這個形狀的假紅假紅）。

🔴 這裡「刻意製造一筆違規再斷言」的測試全部待在子 session（不進主 session）——
若寫進主 session，本檔以外的 `_g1_repo_write_guard` teardown 保險層會對它們
補刀（開工前實測前提③：`3 passed, 2 errors`）。子 session 有自己獨立的
G1／G2 fixture 實例，不受父 session 影響。
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

import _repo_write_guard as _rwg

OPENAVER_ROOT = str(Path(__file__).resolve().parent.parent.parent)
TESTS_DIR = str(Path(__file__).resolve().parent.parent)
# `import core...`／`import web...` 要 OPENAVER_ROOT 在 PYTHONPATH；
# `import _repo_write_guard` 是 tests/ 底下的無 __init__ 頂層模組，要 TESTS_DIR。
_PYTHONPATH_FOR_SUBSESSION = os.pathsep.join([OPENAVER_ROOT, TESTS_DIR])

#: G1／G2 落地之前的 root conftest，逐字取自 `git show <SHA>:tests/conftest.py`。
#: SHA 是本 branch 的分支點（`git merge-base main HEAD` 在 branch 上的值）。
#: ⛔ **不要改成動態解析 branch**：`main` 在 CI 的 shallow checkout 裡不存在（exit 128），
#: 而且這支 branch merge 進 main 之後 `merge-base main HEAD` 會回 HEAD 本身
#: ⇒ 取到的是「新」conftest ⇒ 「舊工具 SURVIVED」這條斷言會永久紅。
#: 基準是一個**歷史事實**，不會變，所以釘成 fixture 才是對的形狀。
_PRE_G1_CONFTEST_SHA = "37247391423ca479acc4065955c5e793c220ecb0"
_PRE_G1_CONFTEST_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "conftest_pre_g1.py.txt"


def _set_guard_env(monkeypatch, pytester, *, mode: str) -> None:
    """子 session 的兩個根都指向假的根，且**互不包含**（技術要點③／開工前實測
    前提④）。

    🔴 `fake_tmp_root` 是 `fake_repo_root`（`pytester.path`）的**手足目錄**，
    不是子目錄——若寫成 `pytester.path / "xxx"`，任何合法落在 tmp 白名單內的
    寫入都會在 `fake_repo_root` 第一層生出一個新目錄（那個 tmp 根本身），
    反而被 G2 當成違規；兩者巢狀等於自己製造假陽性。
    """
    fake_repo_root = pytester.path
    fake_tmp_root = pytester.path.parent / (pytester.path.name + "__fake_tmp_root")
    fake_tmp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PYTHONPATH", _PYTHONPATH_FOR_SUBSESSION)
    monkeypatch.setenv(_rwg.ENV_REPO_ROOT, str(fake_repo_root))
    monkeypatch.setenv(_rwg.ENV_TMP_ROOTS, str(fake_tmp_root))
    monkeypatch.setenv(_rwg.ENV_MODE, mode)
    monkeypatch.delenv(_rwg.ENV_REPORT_PATH, raising=False)


def _install_live_conftest(pytester) -> None:
    """把「現行」（本 task 已修正的）root conftest 逐字複製進子 session——
    刻意讀「活的」檔案而不是重寫一份，兩邊永遠同步，不會產生第二份可能漂移
    的實作（本 branch 自己在 G2 的 `is_ignored_entry` 上吃過「兩份實作互相
    印證、其中一份是錯的」的虧，這裡不重蹈覆轍）。
    """
    live_conftest = Path(OPENAVER_ROOT, "tests", "conftest.py").read_text(encoding="utf-8")
    pytester.makeconftest(live_conftest)


def _install_old_conftest(pytester) -> None:
    """G1／G2 落地之前的 root conftest（釘死的 fixture，見 `_PRE_G1_CONFTEST_SHA`）。"""
    old_content = _PRE_G1_CONFTEST_FIXTURE.read_text(encoding="utf-8")
    # 前置自證（BE-TEST-01 §7：注入若靜默失敗就是假綠）——這份基準必須真的**沒有**守衛，
    # 否則「舊工具 SURVIVED」證明的就不是我們以為的那件事。
    assert "repo_write_guard" not in old_content, (
        f"{_PRE_G1_CONFTEST_FIXTURE} 疑似不是 pre-G1 版本（含 repo_write_guard 字樣）"
    )
    pytester.makeconftest(old_content)


def _seed_magicmock_enrich_test(pytester) -> None:
    """種一支「repo.db_path 是裸 MagicMock 的 enrich 測試」——重現 Finding A 的
    真實形狀（技術要點⑤）：不是自己拼的 bug 版，是真正呼叫
    `core.enricher._sync_nfo_mtime`（Finding A 的實際 sink），讓產品碼自己
    在 `core/database/connection.py::get_connection` 裡做的 `str(db_path)`
    產生 `<MagicMock ...>` 這個非絕對路徑字串——落 `row08`，不是 `row11`
    （因為所有 7 個 `sqlite3.connect` 呼叫點呼叫前都先 `str()`，見
    `_repo_write_guard.py` 檔頭注解）。
    """
    pytester.makepyfile(test_seed=textwrap.dedent("""
        from unittest.mock import MagicMock
        from core.enricher import _sync_nfo_mtime

        def test_seed_magicmock_db_path(tmp_path):
            video = tmp_path / "video.mp4"
            video.write_bytes(b"x")
            nfo = tmp_path / "video.nfo"
            nfo.write_text("<xml></xml>", encoding="utf-8")
            repo = MagicMock()  # repo.db_path 是裸 MagicMock，刻意不手動設
            _sync_nfo_mtime(repo, str(video), str(video), "T113A-BASE")
    """))


# ─────────────────────────────────────────────────────────────────────────────
# mutation 標的 ①：BaseException → Exception ⇒ 這支要紅
# ─────────────────────────────────────────────────────────────────────────────
def test_inline_violation_survives_broad_except(pytester, monkeypatch):
    """✅ 開工前實測前提①的證明，搬進真正的守衛：inline 拋出的
    `RepoWriteGuardViolation` 即使被測試自己包一層 `except Exception:` 也擋
    不住——因為它是 `BaseException` 的子類，不是 `Exception` 的子類。

    mutation 標的：把 `RepoWriteGuardViolation` 的基底從 `BaseException`
    改成 `Exception`——這支注入測試的 `except Exception:` 就會吞掉它，
    `test_broad_except_does_not_swallow_violation` 從 failed 變成 passed，
    本測試的 `assert_outcomes(failed=1)` 因此紅。
    """
    _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import sqlite3

        def test_broad_except_does_not_swallow_violation():
            try:
                # 相對路徑 ⇒ row08，一定被拒。
                sqlite3.connect("__no_such_dir__/relative.db")
            except Exception:
                # 產品碼真實形狀（core/enricher.py:719）：用 `except Exception`
                # 想吞掉「連線失敗」，但吞不到 RepoWriteGuardViolation
                # （BaseException 子類）——它會直接穿透這一層。
                pass
            # 如果例外被吞了，會走到這裡，測試 passed ⇒ 代表守衛沒有牙齒。
    """))

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(failed=1)
    assert "RepoWriteGuardViolation" in result.stdout.str()


# ─────────────────────────────────────────────────────────────────────────────
# mutation 標的 ②：拿掉 teardown 保險 ⇒ 這支要紅
# ─────────────────────────────────────────────────────────────────────────────
def test_teardown_catches_swallowed_violation(pytester, monkeypatch):
    """✅ 開工前實測前提③的證明：teardown 保險層要能補刀「測試自己接住
    inline 例外」的情況——這正是①-c 反向鎖選用 `allow_real_db` marker、
    而不是改成「`fail` 模式驗 `RepoWriteGuardViolation`」的原因（後者會被
    這一層保險反過來咬一口）。

    mutation 標的：拿掉 teardown 保險（`if mode == _rwg.MODE_FAIL and
    accumulator:` 那一行改成恆假）——這支注入測試就不會再被補刀，
    `test_body_catches_violation_but_teardown_should_still_fire` 從
    「1 passed, 1 error」變成「1 passed, 0 errors」，本測試的
    `assert_outcomes(passed=1, errors=1)` 因此紅。
    """
    _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import pytest
        import sqlite3
        import _repo_write_guard as _rwg

        def test_body_catches_violation_but_teardown_should_still_fire():
            with pytest.raises(_rwg.RepoWriteGuardViolation):
                # 相對路徑 ⇒ row08，inline 拋出——但這裡用 pytest.raises
                # 接住了，測試本體因此「passed」。違規已經進了本支測試的
                # per-test 累積器，call 階段沒有因此失敗。
                sqlite3.connect("__no_such_dir__/relative.db")
    """))

    result = pytester.runpytest_subprocess("-q")

    # 測試本體 passed（call 階段沒有失敗），但 teardown 保險層要補一刀
    # ⇒ errors=1（附帶結論⑤：teardown 拋出報成 ERROR 不是 FAILED，
    # DoD 判定看退出碼與 errors 計數，不能只 grep failed）。
    result.assert_outcomes(passed=1, errors=1)
    assert "teardown 保險" in result.stdout.str()


def test_setup_phase_violation_is_not_double_reported(pytester, monkeypatch):
    """sonnet review 2026-08-24 P2 的回歸鎖：違規發生在**依賴 G1 的 fixture
    自己的 setup 階段**時，teardown 保險層**不得**補刀第二次。

    為什麼會錯：保險層原本只看 `rep_call`。這個場景下 call 階段根本沒跑過
    ⇒ `rep_call` 從未被 `pytest_runtest_makereport` 設過 ⇒ `getattr(...,
    None)` 回 None ⇒ `already_failed` 判 False ⇒ 補刀，而且訊息寫
    「代表 inline 拋出的 RepoWriteGuardViolation 在某處被 `except
    BaseException` 吞掉了」——**那句是假的**。違規根本沒被吞，它正正當當地
    在 setup 階段拋出並讓測試 ERROR 了。

    後果不是假綠（兩份 ERROR 都會浮現、退出碼仍非 0），是**誤導**：未來的
    除錯者會照著那句話去找一個不存在的 `except BaseException`。

    修法：`already_failed` 同時看 `rep_setup` 與 `rep_call`。
    還原成只看 `rep_call` ⇒ `errors` 從 1 變 2 ⇒ 本測試紅。
    """
    _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import pytest
        import sqlite3

        @pytest.fixture
        def fixture_that_violates_during_setup(_g1_repo_write_guard):
            # 明示依賴 G1，確保 wrapper 已經掛上；違規發生在本 fixture 的
            # setup 期，也就是 call 階段之前。
            sqlite3.connect("__no_such_dir__/relative.db")
            yield

        def test_uses_violating_fixture(fixture_that_violates_during_setup):
            assert True
    """))

    result = pytester.runpytest_subprocess("-q")

    # setup 階段 ERROR 一份就夠了——teardown 不該再補一份。
    result.assert_outcomes(errors=1)
    assert "teardown 保險" not in result.stdout.str(), (
        "違規在 setup 階段被正當攔下，teardown 保險層不該補刀，"
        "更不該宣稱它被 `except BaseException` 吞掉了"
    )


# ─────────────────────────────────────────────────────────────────────────────
# mutation 標的 ③（row07 翻轉）留在 tests/unit/test_repo_write_guard.py，
# 該檔的 TestClassifyMatrix 已涵蓋，本檔不重複。
# ─────────────────────────────────────────────────────────────────────────────


def test_g1_baseexception_does_not_abort_pytest_session(pytester, monkeypatch):
    """DoD「BaseException 不會中斷整場 pytest session（實測確認）」——搬進真正
    的守衛驗證（開工前實測前提①用的是一支獨立的玩具 `BaseException` 子類，
    這裡改用 `_g1_repo_write_guard` 真正會拋的那個）：G1 的 inline 拋出（`fail`
    模式下不可避免地是 `RepoWriteGuardViolation`）不會中斷整場 pytest
    session——後面的測試照跑，被拋的那支報成一般 `FAILED`，不是整場 session
    崩潰或提早結束收集。
    """
    _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
    _install_live_conftest(pytester)
    pytester.makepyfile(test_probe=textwrap.dedent("""
        import sqlite3

        def test_a_triggers_violation():
            # 相對路徑 ⇒ row08，inline 拋出，不被任何東西接住。
            sqlite3.connect("__no_such_dir__/relative.db")

        def test_b_runs_after_a():
            assert True

        def test_c_runs_after_b():
            assert True
    """))

    result = pytester.runpytest_subprocess("-v")

    # test_a 因為未接住的 BaseException 而 FAILED，但 session 沒有中止——
    # test_b／test_c 都照跑且綠（3 個測試都被收集、都執行到）。
    result.assert_outcomes(passed=2, failed=1)
    stdout = result.stdout.str()
    assert "test_a_triggers_violation FAILED" in stdout
    assert "test_b_runs_after_a PASSED" in stdout
    assert "test_c_runs_after_b PASSED" in stdout


class TestAC3OldNewConftestComparison:
    """AC-3：舊工具（分支點的 conftest，沒有 G1／G2）SURVIVED；新工具（本 task 修好的）PASS。

    ⚠️ CD-127b-4：舊 conftest 抽出後要先自證「它真的跑起來了」——不是自己拼一支
    恆綠的假測試。這裡的自證是：舊 harness 真的在 pytester 的 cwd 建出
    `<MagicMock ...>` 那個離譜檔名（那正是 1425 個空 SQLite 的成因）。
    """

    def test_old_conftest_survived_the_bug(self, pytester, monkeypatch):
        _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
        _install_old_conftest(pytester)
        _seed_magicmock_enrich_test(pytester)

        result = pytester.runpytest_subprocess("-q")

        # CD-127b-4 自證：baseline 綠 ＋ 有輸出，且真的走到了 sqlite3.connect
        # (str(裸 MagicMock)) 這條路徑——不是自己拼一支恆綠的假測試。
        result.assert_outcomes(passed=1)
        leftover = list(pytester.path.rglob("<MagicMock*"))
        assert leftover, (
            "舊 conftest 沒有留下 <MagicMock ...> 檔——代表這支測試根本沒有"
            "真的走到 sqlite3.connect(str(裸 MagicMock)) 這條路徑，"
            "SURVIVED 的證據不成立"
        )
        # SURVIVED：舊 harness 沒有任何守衛，這支「該被擋下」的測試照樣綠。

    def test_new_conftest_catches_the_bug(self, pytester, monkeypatch):
        _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
        _install_live_conftest(pytester)
        _seed_magicmock_enrich_test(pytester)

        result = pytester.runpytest_subprocess("-q")

        # PASS：本 task 的 G1 擋下同一支測試——RepoWriteGuardViolation 穿透
        # `_sync_nfo_mtime` 的 `except Exception`，測試轉紅。
        result.assert_outcomes(failed=1)
        assert "RepoWriteGuardViolation" in result.stdout.str()


class TestAvalancheProtection:
    """雪崩防護：G2 的 baseline 在**每支測試**的 setup 期現掃現拿，所以某支測試
    留下的雜檔只會被算到那一支頭上——連續兩支、只有第一支污染 ⇒ 只有第一支紅。
    """

    def test_only_first_test_is_blamed_for_leftover_file(self, pytester, monkeypatch):
        _set_guard_env(monkeypatch, pytester, mode=_rwg.MODE_FAIL)
        _install_live_conftest(pytester)
        pytester.makepyfile(test_avalanche=textwrap.dedent("""
            from pathlib import Path
            import _repo_write_guard as _rwg

            def test_a_leaves_junk_in_repo_root():
                # 直接在 G2 監控的 repo 根第一層留下一個雜檔——純粹測 G2 的
                # 雪崩防護，不依賴 sqlite3／G1。
                repo_root = Path(_rwg.get_repo_root())
                (repo_root / "avalanche_junk.txt").write_text("x", encoding="utf-8")

            def test_b_is_clean():
                assert True
        """))

        result = pytester.runpytest_subprocess("-v")

        # G2 沒有 inline 攔截點——它只在 teardown 事後比對快照，所以「被 G2
        # 攔到」的測試組合是 call 階段 passed（本體沒做錯事）＋ teardown
        # errors（附帶結論⑤：teardown 拋出報成 ERROR 不是 FAILED）。
        # test_a 一支貢獻 1 個 passed（call）＋ 1 個 error（teardown）；
        # test_b 貢獻 1 個 passed——合計 passed=2, errors=1。
        result.assert_outcomes(passed=2, errors=1)
        stdout = result.stdout.str()
        assert "test_a_leaves_junk_in_repo_root ERROR" in stdout
        assert "test_b_is_clean PASSED" in stdout
        assert "test_b_is_clean ERROR" not in stdout, (
            "雪崩：test_b 不該因為 test_a 留下的雜檔被連坐——"
            "G2 的 baseline 必須是每支測試 setup 期現掃現拿"
        )


class TestSixCellFlagMatrix:
    """邊界條件「flag 正交組合」：off／report／fail × 有無 `allow_real_db`
    marker ＝ 6 格，六格都要有測試。特別是 `fail` ＋ 有 marker ⇒ 放行且記錄
    （這格若壞掉，`allow_real_db` 這個逃生口就形同虛設）。

    探測手法：連到一個「父目錄不存在」的相對路徑。
      - 被 G1 擋下 ⇒ inline 拋 `RepoWriteGuardViolation`（不是
        `sqlite3.OperationalError`）⇒ `pytest.raises(OperationalError)`
        型別對不上 ⇒ 測試紅。
      - 沒被擋下（`off`／`report`／有 marker）⇒ 轉發給 sqlite，由它自己
        因為父目錄不存在而拒絕（`OperationalError`）⇒ `pytest.raises`
        接得住 ⇒ 測試綠。
    """

    @pytest.mark.parametrize(
        "mode,use_marker,expect_blocked",
        [
            (_rwg.MODE_OFF, False, False),
            (_rwg.MODE_OFF, True, False),
            (_rwg.MODE_REPORT, False, False),
            (_rwg.MODE_REPORT, True, False),
            (_rwg.MODE_FAIL, False, True),
            (_rwg.MODE_FAIL, True, False),  # ← DoD 特別點名的那一格
        ],
        ids=[
            "off_no_marker", "off_marker",
            "report_no_marker", "report_marker",
            "fail_no_marker_blocked", "fail_marker_allowed",
        ],
    )
    def test_flag_marker_combination(
        self, pytester, monkeypatch, mode, use_marker, expect_blocked
    ):
        _set_guard_env(monkeypatch, pytester, mode=mode)
        _install_live_conftest(pytester)
        # 用逐行組字串而不是把 marker 塞進 dedent 區塊中間——後者會讓 marker
        # 那行帶自己的縮排、緊跟其後的 `def` 卻沒有，dedent() 抓公因縮排時
        # 會被那個 0 縮排的 `def` 拉成完全不縮排，其餘行反而變成語法錯誤縮排
        # （已實測：`IndentationError: unexpected indent`）。
        lines = ["import sqlite3", "import pytest", ""]
        if use_marker:
            lines.append("@pytest.mark.allow_real_db")
        lines.extend([
            "def test_probe():",
            "    with pytest.raises(sqlite3.OperationalError):",
            '        sqlite3.connect("__no_such_dir__/relative.db")',
        ])
        pytester.makepyfile(test_probe="\n".join(lines) + "\n")

        result = pytester.runpytest_subprocess("-q")

        if expect_blocked:
            result.assert_outcomes(failed=1)
            assert "RepoWriteGuardViolation" in result.stdout.str()
        else:
            result.assert_outcomes(passed=1)
