"""TASK-127b-T3 —— G1 12 列判定矩陣 ＋ G2 行為 ＋ 巢狀 patch 還原自檢。

`_repo_write_guard` 是零 pytest 相依的純模組（`tests/_repo_write_guard.py`）；
這裡只做「純函式輸入 → 輸出」的忠實度驗證,不觸碰 conftest 掛的 autouse fixture
本身（那兩支的「跑起來會不會動到 sqlite3.connect / repo 根」由本檔以外的全套
跑驗證，見 REPORT-127b-T3.md）。

case id 逐字 row01...row12——`tools/mutation_gate.py` 的 `expect_fail` 靠字串
比對 pytest 輸出裡有沒有出現該 id 來判斷「只有那一列紅」，id 打錯這支卡片的
mutation 驗證就會失真。
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# `tests/` 沒有 __init__.py，pytest 收集 tests/conftest.py 時會把 tests/ 插進
# sys.path（見 _repo_write_guard.py 檔頭注解）。這裡驗證從 tests/unit/ 底下的
# 測試檔也 import 得到，不是只有 conftest 用得到。
import _repo_write_guard as rwg

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_DB = str(REPO_ROOT / "output" / "openaver.db")
SYSTEM_TMP = Path(tempfile.gettempdir())


class TestClassifyMatrix:
    """§③ 12 列白名單判定矩陣，case id 逐字 row01..row12。"""

    @pytest.mark.parametrize(
        "case_id",
        [
            "row01", "row02", "row03", "row04", "row05", "row06",
            "row07", "row08", "row09", "row10", "row11", "row12",
        ],
    )
    def test_matrix(self, case_id, tmp_path_factory):
        basetemp = tmp_path_factory.getbasetemp()

        if case_id == "row01":
            decision = rwg.evaluate_connect(
                ":memory:", False,
                repo_root=REPO_ROOT, tmp_roots=[], basetemp=None,
            )
            expect_allowed = True

        elif case_id == "row02":
            decision = rwg.evaluate_connect(
                "file::memory:?cache=shared", True,
                repo_root=REPO_ROOT, tmp_roots=[], basetemp=None,
            )
            expect_allowed = True

        elif case_id == "row03":
            # 只給 basetemp、不給 tmp_roots——只有「有沒有正確吃 basetemp 參數」
            # 這條路徑能讓它通過,不是系統 tmp 的 fallback 順便救到它。
            db_path = str(basetemp / "row03.db")
            decision = rwg.evaluate_connect(
                db_path, False,
                repo_root=REPO_ROOT, tmp_roots=[], basetemp=basetemp,
            )
            expect_allowed = True

        elif case_id == "row04":
            # 不落在 basetemp 內、只落在系統 tempfile.gettempdir() 底下——鏡射
            # tests/unit/conftest.py:29-34 的 temp_db fixture（TemporaryDirectory()）。
            db_path = os.path.join(str(SYSTEM_TMP), "openaver-guard-row04", "row04.db")
            decision = rwg.evaluate_connect(
                db_path, False,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
            )
            expect_allowed = True

        elif case_id == "row05":
            db_path = os.path.join(str(SYSTEM_TMP), "openaver-guard-row05", "row05.db")
            decision = rwg.evaluate_connect(
                f"file:{db_path}?mode=ro", True,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
            )
            expect_allowed = True

        elif case_id == "row06":
            decision = rwg.evaluate_connect(
                REAL_DB, False,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row07":
            decision = rwg.evaluate_connect(
                f"file:{REAL_DB}?mode=ro", True,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row08":
            decision = rwg.evaluate_connect(
                "openaver.db", False,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row09":
            decision = rwg.evaluate_connect(
                "http://example.com/x.db", True,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row10":
            # urlparse 對畸形 IPv6-like netloc 會真的丟 ValueError——用它驗
            # 「解析拋例外 → fail-closed 拒絕」,不是造假的路徑。
            decision = rwg.evaluate_connect(
                "file://[bad", True,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row11":
            decision = rwg.evaluate_connect(
                MagicMock(name="mock.db_path"), False,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        elif case_id == "row12":
            decision = rwg.evaluate_connect(
                "", False,
                repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=basetemp,
            )
            expect_allowed = False

        else:  # pragma: no cover — parametrize 清單本身就是 12 列,不該落到這裡
            pytest.fail(f"未知 case_id={case_id!r}")

        assert decision.allowed is expect_allowed, (
            f"{case_id}: 預期 allowed={expect_allowed}，實際 decision={decision!r}"
        )
        assert decision.case.startswith(case_id), (
            f"{case_id}: decision.case={decision.case!r} 沒有以 {case_id!r} 開頭"
        )


class TestFailClosedTypes:
    """row11 的補充：bytes 與其他非 str/PathLike 型別都要落同一個 fail-closed 桶。"""

    def test_bytes_database_rejected(self):
        decision = rwg.evaluate_connect(
            b"/tmp/should-not-be-bytes.db", False,
            repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
        )
        assert decision.allowed is False
        assert decision.case.startswith("row11")

    def test_pathlib_path_is_not_row11(self):
        """pathlib.Path 是 os.PathLike——走一般路徑判定,不是 row11。"""
        p = SYSTEM_TMP / "openaver-guard-pathlike" / "x.db"
        decision = rwg.evaluate_connect(
            p, False,
            repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
        )
        assert decision.allowed is True
        assert not decision.case.startswith("row11")


class TestReportFormatting:
    """技術要點⑥：拒絕時要能拿到「原始參數 repr」與「解析後路徑」。"""

    def test_g1_record_carries_raw_and_resolved(self):
        mock_db = MagicMock(name="mock.db_path")
        decision = rwg.evaluate_connect(
            mock_db, False,
            repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
        )
        record = rwg.format_g1_record("tests/unit/test_x.py::test_y", decision)
        assert record["nodeid"] == "tests/unit/test_x.py::test_y"
        assert record["guard"] == "G1"
        assert record["raw_arg"] == repr(mock_db)
        assert record["resolved"] is None
        assert record["reason"].startswith("row11")

    def test_g1_record_marks_allowed_by_marker(self):
        decision = rwg.evaluate_connect(
            REAL_DB, False,
            repo_root=REPO_ROOT, tmp_roots=[SYSTEM_TMP], basetemp=None,
        )
        record = rwg.format_g1_record(
            "tests/unit/test_x.py::test_y", decision, allowed_by_marker=True
        )
        assert record["reason"].endswith("_allowed_by_marker")

    def test_g2_record_shape(self):
        record = rwg.format_g2_record("tests/unit/test_x.py::test_y", {"b", "a"})
        assert record == {
            "nodeid": "tests/unit/test_x.py::test_y",
            "guard": "G2",
            "new_entries": ["a", "b"],
        }


class TestG2ScanAndIgnoreList:
    """§④ G2 行為：忽略清單、`<MagicMock*`/`<Mock*` 硬失敗、0-entry 大聲失敗。"""

    def test_scan_excludes_ignored_and_keeps_real_entries(self, tmp_path):
        """`tmp_path` 沒有自己的 `.gitignore`，所以顯式帶 patterns——這裡驗的是
        「給定忽略清單，過濾行為對不對」，.gitignore 有沒有被實讀是另一支測試
        （`test_get_g2_ignore_patterns_reads_real_gitignore`）的責任。
        """
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "foo.pyc").write_text("x")
        (tmp_path / ".pytest_cache").mkdir()
        (tmp_path / "real_file.txt").write_text("x")
        (tmp_path / "real_dir").mkdir()

        patterns = ["__pycache__/", "*.pyc", ".pytest_cache/"]
        entries = rwg.scan_repo_root_first_level(tmp_path, patterns=patterns)

        assert "real_file.txt" in entries
        assert "real_dir" in entries
        assert "__pycache__" not in entries
        assert "foo.pyc" not in entries
        assert ".pytest_cache" not in entries

    def test_magicmock_leftover_never_ignored_even_if_pattern_present(self, tmp_path):
        """即使忽略清單裡真的有 `<MagicMock*`／`<Mock*`（.gitignore 就是這樣寫的），
        G2 也不准把它們濾掉——那正是 .gitignore:94-97 想遮住、而這支守衛要攔的東西。
        """
        name = "<MagicMock name='VideoRepository().db_path' id='999'>"
        patterns_with_magicmock_rule = ["<MagicMock*", "<Mock*", "__pycache__/"]
        assert rwg.is_ignored_entry(name, False, patterns_with_magicmock_rule) is False
        assert rwg.is_ignored_entry("<Mock leftover>", False, patterns_with_magicmock_rule) is False

    def test_is_dangerous_leftover(self):
        assert rwg.is_dangerous_leftover("<MagicMock name='x' id='1'>") is True
        assert rwg.is_dangerous_leftover("<Mock id='2'>") is True
        assert rwg.is_dangerous_leftover("openaver.db") is False

    def test_require_nonzero_baseline_raises_on_empty(self):
        with pytest.raises(rwg.RepoRootScanEmptyError):
            rwg.require_nonzero_baseline(set(), "/some/path")

    def test_require_nonzero_baseline_passes_on_nonempty(self):
        rwg.require_nonzero_baseline({"a"}, "/some/path")  # 不該拋例外

    def test_get_g2_ignore_patterns_reads_real_gitignore(self):
        """實讀（不是另外手抄一份清單）——真實 .gitignore 有 `output/`，該清單裡要有它。"""
        patterns = rwg.get_g2_ignore_patterns(REPO_ROOT)
        assert "output/" in patterns
        assert "venv/" in patterns
        assert ".pytest_cache/" in patterns  # 額外補的那一條

    def test_dir_only_wildcard_pattern_is_globbed_not_compared_literally(self):
        """目錄限定（結尾 `/`）**且**含萬用字元的 pattern 必須 glob，不是字面比對。

        取代原本的「fast path vs 參考實作 parity」測試。那支測試取樣 24 個手挑
        名字，**漏掉了這一整類**，而本 repo 的 `.gitignore` 就有一條
        `*.egg-info/`——兩份實作對它答案相反（字面比對版回 False、glob 版回
        True），parity 測試卻是綠的（sonnet review 2026-08-23 實證）。

        處置不是把 parity 測試補好，是**刪掉其中一份實作**：`is_ignored_entry`
        現在只是 `_is_ignored_fast` 的薄包裝，語意只有一份。這支測試改為直接
        釘住那個語意本身。
        """
        patterns = ["*.egg-info/", "tmp_*/", "test[0-9]/", "*.log", "venv/"]

        # 目錄限定 ＋ 萬用字元 → 要 glob 得到
        assert rwg.is_ignored_entry("openaver.egg-info", True, patterns) is True
        assert rwg.is_ignored_entry("tmp_abc", True, patterns) is True
        assert rwg.is_ignored_entry("test7", True, patterns) is True

        # 目錄限定的 pattern 不准命中同名的「檔案」
        assert rwg.is_ignored_entry("openaver.egg-info", False, patterns) is False
        assert rwg.is_ignored_entry("venv", False, patterns) is False
        assert rwg.is_ignored_entry("venv", True, patterns) is True

        # 非目錄限定的 pattern 對檔案與目錄都適用
        assert rwg.is_ignored_entry("debug.log", False, patterns) is True

        # 硬失敗例外優先於一切 pattern
        assert rwg.is_ignored_entry("<MagicMock x>.egg-info", True, patterns) is False

    def test_real_gitignore_egg_info_pattern_is_actually_present(self):
        """上一支測試的前提自檢：`*.egg-info/` **真的**在本 repo 的 .gitignore 裡。

        沒有這支，上一支就退化成「測一個假想的 pattern」——哪天 .gitignore 拿掉
        那條，我們會以為自己還在守一個現存的形狀（`BE-TEST-05` 的形狀）。
        """
        patterns = rwg.get_g2_ignore_patterns(REPO_ROOT)
        dir_only_globs = [
            p for p in patterns
            if p.endswith("/") and any(ch in p[:-1] for ch in ("*", "?", "["))
        ]
        assert dir_only_globs, (
            "本 repo 的 .gitignore 已經沒有「目錄限定＋含萬用字元」的 pattern 了。"
            "上一支測試守的是一個不再存在的形狀——重新確認是否還需要它。"
            f"（現有 patterns 共 {len(patterns)} 條）"
        )

    def test_compiled_rules_cache_invalidates_when_gitignore_changes(self, tmp_path):
        """🔴 快取 key 必須含 `.gitignore` 的內容指紋，不能只用 repo_root 路徑。

        T3 初版只用路徑當 key ⇒ 同一個目錄改了 `.gitignore` 之後仍套舊規則，
        且**沒有任何錯誤訊息**（sonnet review 2026-08-23 直接重現）。

        為什麼是 P1 而不是 nit：T5 的 `pytester` 子 session 若走 in-process 模式、
        在同一個暫存 repo root 上換 `.gitignore` 跑多個情境（寫 G2 mutation 測試
        最自然的寫法），守衛會靜默給舊答案 ⇒ **T5 的 mutation 會假綠**。
        """
        (tmp_path / ".gitignore").write_text("foo/\n", encoding="utf-8")
        (tmp_path / "foo").mkdir()
        (tmp_path / "bar").mkdir()

        first = rwg.scan_repo_root_first_level(tmp_path)
        assert "foo" not in first and "bar" in first

        # mtime_ns 在某些檔案系統上解析度不足以區分「同一秒內的兩次寫入」，
        # 但 size 一起進 key ⇒ 這裡刻意讓長度也不同，兩個維度任一變了就失效。
        (tmp_path / ".gitignore").write_text("bar/\n\n", encoding="utf-8")

        second = rwg.scan_repo_root_first_level(tmp_path)
        assert "bar" not in second, (
            "換了 .gitignore 之後仍套用舊規則 —— 快取 key 沒有含內容指紋（stale）"
        )
        assert "foo" in second


class TestReportWriteIsNonFatal:
    """`report` 模式的 DoD 是「不准改變任何測試的綠紅判定」——
    那條承諾不可以建立在「報告檔一定寫得進去」這個假設上。"""

    def test_append_report_record_never_raises(self, tmp_path):
        """報告路徑指到一個「目錄」時（sonnet review 實測會 IsADirectoryError），
        `append_report_record` 必須吞掉並回報，**不得讓無關的測試變紅**。"""
        rwg.report_write_failures.clear()
        bad = tmp_path / "i_am_a_directory"
        bad.mkdir()

        rwg.append_report_record({"probe": 1}, report_path=bad)  # 不得拋

        assert len(rwg.report_write_failures) == 1
        assert "probe" in repr(rwg.report_write_failures[0]["record"])
        rwg.report_write_failures.clear()

    def test_append_report_record_happy_path_still_writes(self, tmp_path):
        """吞例外不可以吞掉正常路徑——正常情況必須真的寫出一行 JSONL。"""
        rwg.report_write_failures.clear()
        out = tmp_path / "nested" / "report.jsonl"

        rwg.append_report_record({"nodeid": "x::y", "guard": "G1"}, report_path=out)

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["nodeid"] == "x::y"
        assert rwg.report_write_failures == []


class TestEnvInjection:
    """②：兩個根一律吃環境變數，未設才落預設值。"""

    def test_repo_root_default(self, monkeypatch):
        monkeypatch.delenv(rwg.ENV_REPO_ROOT, raising=False)
        assert rwg.get_repo_root() == Path(__file__).resolve().parent.parent.parent

    def test_repo_root_injected(self, monkeypatch, tmp_path):
        monkeypatch.setenv(rwg.ENV_REPO_ROOT, str(tmp_path))
        assert rwg.get_repo_root() == tmp_path

    def test_tmp_roots_default_is_system_tempdir_only(self, monkeypatch):
        monkeypatch.delenv(rwg.ENV_TMP_ROOTS, raising=False)
        assert rwg.get_tmp_roots() == [Path(tempfile.gettempdir())]

    def test_tmp_roots_injected_replaces_not_appends(self, monkeypatch, tmp_path):
        custom = tmp_path / "a"
        monkeypatch.setenv(rwg.ENV_TMP_ROOTS, str(custom))
        roots = rwg.get_tmp_roots()
        assert roots == [custom]
        assert Path(tempfile.gettempdir()) not in roots


class TestNestedPatchRestoresWrapper:
    """技術要點⑧：既有 5 支測試自己 `with patch("sqlite3.connect", ...)`——
    離開該區塊後,`sqlite3.connect` 必須還原成**我們的 wrapper**,不是原生函式。

    本測試不改動那 5 支既有測試,而是直接驗證機制本身：conftest 的 G1 autouse
    fixture 已經對本測試生效（本檔本身就在 pytest 收集範圍內),所以進入測試時
    `sqlite3.connect` 應該已經是掛了辨識標記的 wrapper；巢狀 `unittest.mock.patch`
    進出一次之後,標記應該還在。
    """

    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_wrapper_survives_nested_patch(self):
        guard_wrapper_before = sqlite3.connect
        assert getattr(guard_wrapper_before, "__openaver_g1_wrapper__", False) is True, (
            "conftest 的 G1 autouse fixture 應該已經把 sqlite3.connect 換成我們的 wrapper"
        )

        with patch("sqlite3.connect", return_value=MagicMock()):
            assert sqlite3.connect is not guard_wrapper_before

        assert sqlite3.connect is guard_wrapper_before, (
            "巢狀 with patch(...) 離開後,sqlite3.connect 應還原回我們的 wrapper,"
            "不是原生 sqlite3.connect——這是 5 支既有測試安全共存的前提"
        )

    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_wrapper_survives_nested_patch_even_when_baseexception_propagates(self):
        """TASK-127b-T5 邊界條件「鏡像對稱」：inline 拋出的是 `BaseException`
        子類——pytest／`unittest.mock.patch` 對 `BaseException` 走的是跟一般
        `Exception` 不同的清理路徑（開工前實測前提②：teardown 仍會執行，但
        本測試釘住更貼近本專案的形狀：`with patch(...)` 這個 context manager
        本身，在區塊內有 `BaseException` 傳出去時，`__exit__` 是否仍然正確
        還原）。

        不透過真正觸發一次 G1 違規（那會撞到本檔以外的 teardown 保險層，見
        TASK-127b-T5.md 開工前實測前提③）——直接用 `RepoWriteGuardViolation`
        本人在巢狀 `with patch(...)` 區塊內拋出，驗證 context manager 的
        `__exit__` 對 `BaseException` 一樣會執行（不是只對 `Exception`）。
        """
        guard_wrapper_before = sqlite3.connect

        with pytest.raises(rwg.RepoWriteGuardViolation):
            with patch("sqlite3.connect", return_value=MagicMock()):
                assert sqlite3.connect is not guard_wrapper_before
                raise rwg.RepoWriteGuardViolation("boom")

        assert sqlite3.connect is guard_wrapper_before, (
            "BaseException 從 with patch(...) 區塊內傳出去之後,"
            "sqlite3.connect 應該還原回我們的 wrapper——`__exit__` 對"
            "BaseException 跟對 Exception 一樣會執行"
        )


class TestWrapperArgumentBinding:
    """Codex PR review 2026-08-24 P2：wrapper 的**取參**這一層在 T4 之前零覆蓋。

    `TestClassifyMatrix` 那 12 列全部直呼 `evaluate_connect()`，繞過了
    `conftest._g1_wrapper` 把 `(*args, **kwargs)` 綁成 `(database, uri)` 的那一步；
    `TestNestedPatchRestoresWrapper` 走 wrapper 層，但只驗身分還原、不驗取參。
    ⇒ 「wrapper 讀錯參數」這一整類 bug 沒有任何測試在守。

    🔴 **本類別的斷言全部走真正被 patch 的 `sqlite3.connect`**（也就是 conftest
    掛上去的 wrapper 本人），不准改成直呼 `evaluate_connect()`——那樣就退回原本
    的缺口了。

    ### 為什麼用「report 有沒有記一筆」當 oracle 而不是「有沒有拋例外」

    autouse fixture 在 setup 期就把 `mode` 讀進 closure，測試體內再
    `monkeypatch.setenv(ENV_MODE, "fail")` 對已建好的 wrapper 無效
    （會變成一支無論修法在不在都綠的假測試）。改成攔 `append_report_record`：
    `report` 與 `fail` 兩種模式下「被拒絕 → 一定會記一筆」都成立。
    """

    @pytest.fixture
    def captured_records(self, monkeypatch):
        """攔 `_rwg.append_report_record`。

        conftest 的 wrapper 是在**呼叫當下**做 `_rwg.append_report_record(...)`
        的屬性查找，所以 monkeypatch 模組屬性攔得到（不是 closure 裡的舊參照）。
        """
        records: list = []
        monkeypatch.setattr(
            rwg, "append_report_record",
            lambda record, report_path=None: records.append(record),
        )
        return records

    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_positional_uri_flag_is_bound(self, captured_records, tmp_path):
        """`uri` 用**第 8 個位置參數**傳（合法簽名）時，wrapper 必須讀得到。

        oracle 的分歧點：
          - 讀得到 `uri=True` → `evaluate_connect` 解析 URI 拿到絕對 tmp 路徑
            → `row05_uri_tmp_path` **放行**，report 零筆。
          - 讀不到（舊寫法 `kwargs.get("uri", False)`）→ 整串
            `file:/tmp/.../x.db?mode=rwc` 當一般路徑，`os.path.isabs()` 為 False
            → `row08_relative_path` **拒絕**，report 記一筆 ⇒ 本測試紅。
        """
        assert getattr(sqlite3.connect, "__openaver_g1_wrapper__", False) is True

        db = tmp_path / "positional_uri.db"
        conn = sqlite3.connect(
            f"file:{db}?mode=rwc",
            5.0, 0, "", True, sqlite3.Connection, 128,
            True,  # ← uri，第 8 個位置參數
        )
        conn.close()

        assert captured_records == [], (
            "wrapper 沒讀到位置傳入的 uri=True ⇒ 合法的 tmp URI 被誤判成 "
            f"row08 相對路徑而拒絕（假紅）。實際記到：{captured_records}"
        )

    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_keyword_uri_flag_still_bound(self, captured_records, tmp_path):
        """關鍵字形式（全庫 84 個呼叫點實際採用的唯一形狀）不得因修法而回歸。"""
        db = tmp_path / "keyword_uri.db"
        conn = sqlite3.connect(f"file:{db}?mode=rwc", uri=True)
        conn.close()
        assert captured_records == [], f"關鍵字 uri=True 被誤拒：{captured_records}"

    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_keyword_database_is_bound(self, captured_records, tmp_path):
        """`database` 也可以用關鍵字傳；綁定表不得把它漏掉。"""
        conn = sqlite3.connect(database=str(tmp_path / "kw_database.db"))
        conn.close()
        assert captured_records == [], f"關鍵字 database 被誤拒：{captured_records}"

    @pytest.mark.allow_real_db
    @pytest.mark.skipif(
        os.environ.get(rwg.ENV_MODE, rwg.DEFAULT_MODE) == rwg.MODE_OFF,
        reason="G1 在 off 模式下不掛 wrapper，此測試無意義",
    )
    def test_positional_uri_false_still_rejects_repo_relative(self, captured_records):
        """反向鎖：綁定修好之後**不能反過來變成放行機**。

        位置傳 `uri=False` ＋ repo 根相對路徑 → 仍須落 `row08` 被拒。

        🔴 TASK-127b-T5 技術要點①-c：切預設成 `fail` 之後，wrapper 會在轉發
        **之前**先拋 `RepoWriteGuardViolation`，`pytest.raises(sqlite3.
        OperationalError)` 型別對不上會讓這支測試變紅——即使 T3/T4 的
        `report` 模式下它是綠的。修法是掛 `allow_real_db` marker，讓斷言變
        成模式無關（`report`／`fail` 兩邊都是同一份斷言）：marker 讓 wrapper
        跳過拋出、仍轉發給 sqlite 自己拒絕建檔（`OperationalError`），
        record 照記（reason 帶 `_allowed_by_marker` 後綴，故用 startswith）。
        """
        rel = "__rwg_no_such_dir__/relative.db"
        assert not Path(rel).parent.exists(), (
            "這支測試靠『父目錄不存在 ⇒ sqlite 建不出檔』來保證不在 repo 根落地，"
            f"{rel} 的父目錄居然存在"
        )
        before = len(captured_records)
        with pytest.raises(sqlite3.OperationalError):
            # 有 allow_real_db marker ⇒ wrapper 只記錄、仍轉發 ⇒ 由 sqlite 自己拒絕建檔
            sqlite3.connect(rel, 5.0, 0, "", True, sqlite3.Connection, 128, False)

        new_records = captured_records[before:]
        assert len(new_records) == 1, f"相對路徑應被記一筆 row08，實際 {new_records}"
        # marker 會讓 reason 帶 `_allowed_by_marker` 後綴 ⇒ 用 startswith
        assert new_records[0]["reason"].startswith("row08_relative_path"), new_records[0]
