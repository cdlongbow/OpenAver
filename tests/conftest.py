import pytest
import sqlite3
from pathlib import Path
import json
from core import config as core_config
import _repo_write_guard as _rwg

# TASK-127b-T5：`pytester` 子 session 的 mutation 自驗（`test_repo_write_guard_
# subsession.py`）——pytest 的硬性要求是這行必須放在 root conftest。本專案沒有
# 任何 pytester 先例，這是第一支使用它的測試。
pytest_plugins = ["pytester"]

# ── TASK-102c-T1: focal mock 座標共用常數 ──────────────────────────────
# 刻意選一個偏離中心、x/y 不對稱的值，讓「focal 平移有沒有生效」的斷言在
# mock 下依然有鑑別力——不可用 (0.5, 0.5)，否則平移後 crop 退化成置中 crop，
# 反向斷言「應與原碼輸出不同」會失真。各檔按需
# `from tests.conftest import MOCK_FOCAL_XY` 匯入。
# 註：x=0.3148 恰與 wide_offcenter_face.jpg 的真 pigo 偵測值重疊——巧合非刻意
# 逼近，且不影響判別力（patch 整段替換函式，測試期間真偵測不可能被呼叫）。
MOCK_FOCAL_XY = (0.3148, 0.2000)

# ── LAN access gate（feature/80）測試相容 ──────────────────────────────
# web.app 的 lan_access_gate middleware 用 request.client.host 判 loopback。
# Starlette TestClient 預設 client host = "testclient"（非 loopback）→ 單機模式
# （預設）會擋掉任何打路由的測試。所有測試的 TestClient 一律代表「桌面 App 自連」
# = loopback，故在**根 conftest** module-level 把預設 client 設成 127.0.0.1，使
# 「整套跑」與「單檔 isolation 跑」（CLAUDE.md 開發流程 `pytest tests/unit/test_x.py`）
# 行為一致——unit 測試在 isolation 下也不會被閘門 403。
#
# 取捨與邊界：
#   - 必須 module-level class patch（非 autouse fixture）：部分測試在 import 時即
#     `client = TestClient(app)`，早於任何 fixture；patch 須在 conftest import 即生效。
#     替代是逐檔顯式傳 loopback client（大量 churn），取捨後選集中一處。
#   - process-global：setdefault → 顯式 client=(ip,port)（如 gate 矩陣測遠端）永遠覆寫。
#   - idempotent guard：避免重複 wrap。
import starlette.testclient as _starlette_testclient

if not getattr(_starlette_testclient.TestClient, "_openaver_loopback_patched", False):
    _orig_testclient_init = _starlette_testclient.TestClient.__init__

    def _loopback_default_init(self, *args, **kwargs):
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        _orig_testclient_init(self, *args, **kwargs)

    _starlette_testclient.TestClient.__init__ = _loopback_default_init
    _starlette_testclient.TestClient._openaver_loopback_patched = True

@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    """
    Mock config path to use a temporary file.
    Avoids modifying the real config.json during tests.
    """
    # Create a temp config file
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    p = d / "test_config.json"

    # Write default config
    default_config = core_config.AppConfig().model_dump()
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(default_config, f)

    # Monkeypatch the global CONFIG_PATH variable in core.config module
    monkeypatch.setattr(core_config, "CONFIG_PATH", p)

    return p


# ============ 跨平台環境 Fixtures ============

@pytest.fixture
def mock_wsl_env(monkeypatch):
    """模擬 WSL 環境"""
    import core.path_utils as path_utils
    monkeypatch.setattr(path_utils, 'CURRENT_ENV', 'wsl')


@pytest.fixture
def mock_windows_env(monkeypatch):
    """模擬 Windows 環境"""
    import core.path_utils as path_utils
    monkeypatch.setattr(path_utils, 'CURRENT_ENV', 'windows')


@pytest.fixture
def mock_linux_env(monkeypatch):
    """模擬 Linux 環境"""
    import core.path_utils as path_utils
    monkeypatch.setattr(path_utils, 'CURRENT_ENV', 'linux')


@pytest.fixture
def mock_mac_env(monkeypatch):
    """模擬 macOS 環境"""
    import core.path_utils as path_utils
    monkeypatch.setattr(path_utils, 'CURRENT_ENV', 'mac')


# ============ Samples 目錄 Fixtures ============

@pytest.fixture
def samples_dir():
    """取得 samples 測試目錄"""
    from pathlib import Path
    return Path(__file__).parent.parent / 'samples'


# ============ Focal / crop_mode 測試 seed helper（99a-T7：retire update_crop_mode）====

@pytest.fixture
def seed_crop_mode():
    """Test-only seed helper：一條 explicit UPDATE 直接寫 crop_mode 欄位，鏡射
    VideoRepository 端已刪除的同名 mutator（那個一行方法：不碰其他欄位，鏡射
    update_user_tags）——production 已無呼叫端（plan-99a §B.3 拍板 RETIRE），只剩測試
    需要「準備一筆 crop_mode 已是非預設值的 row」這個前置狀態，不該為了測試 seed 需求
    讓已收斂的 mutator 介面再長出一個方法。放在根 conftest（跨 tests/unit 與
    tests/integration 共用），避免三處各自 copy-paste 同一條 UPDATE。

    Usage: `seed_crop_mode(repo, path, 'default')` — repo 為任一 VideoRepository 實例，
    直接用 repo.db_path 開連線寫入，回傳值鏡射原 mutator（rowcount > 0 → True）。
    """
    def _seed(repo, path: str, mode: str) -> bool:
        from core.database import get_connection
        conn = get_connection(repo.db_path)
        try:
            cursor = conn.execute(
                "UPDATE videos SET crop_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE path = ?",
                (mode, path),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    return _seed


# ============ TASK-127b-T3/T5：G1／G2 repo-write 守衛（autouse，預設 fail）====
#
# 根因（見 feature/127-gotchas-triage/TASK-127b-T3.md「現況分析」）：任何測試只要
# `patch("core.enricher.VideoRepository")` 而沒設 `mock_repo.db_path`，
# `repo.db_path` 是 MagicMock → 產品碼在 3 個檔 7 處呼叫 `sqlite3.connect(...)`
# 前一律先 `str(db_path)`／f-string 化 → 建出檔名為
# `<MagicMock name='...' id='...'>` 的空 SQLite，寫進 repo 根，`nfo_mtime` 回填
# 路徑從沒被真的執行過（被 `except Exception` 吞掉）。
#
# G1：patch 真正的 sink `sqlite3.connect`（不是 `get_connection` 定義處——見
# BE-TEST-01 §1／§3，24 個 import landing point 會漂）。判定邏輯是純函式
# （`tests/_repo_write_guard.py::evaluate_connect`），fixture 只負責轉發＋記錄。
# G2：比對 repo 根第一層（非遞迴）的檔名集合，抓 G1 萬一漏掉的雜檔。
#
# T3 把預設模式固定 `report`：只記錄不擋，`report` 模式下全套的綠紅狀態必須與
# 上線前完全相同。T4 逐筆清乾淨違規（67 筆）。**T5 把預設切成 `fail`**——見下方
# 雙層拋出的設計（TASK-127b-T5.md 技術要點①）。


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """標準 pytest 慣例：把每個階段（setup／call／teardown）的 report 存到
    `item.rep_<when>` 上。

    G1 的 teardown 保險層（見 `_g1_repo_write_guard`）要靠 `item.rep_call`
    判斷「這支測試的 call 階段本身是否已經因為這條違規而失敗」——只有
    「有累積到違規，但 call 階段沒有因此失敗」才補刀（技術要點①：兩層拋出
    缺一都不算數，但已經失敗的測試不需要教訓兩次）。這是官方文件記錄的
    "post-process test reports" pattern，`wrapper=True` 為 pluggy 1.1+／
    pytest 7.4+ 的寫法（已實測 pytest 9.0.3：teardown 讀得到 `rep_call`）。
    """
    rep = yield
    setattr(item, "rep_" + rep.when, rep)
    return rep


#: G1 的 per-test 違規累積器掛在 `request.node.stash` 上（隨 node 生滅，不是
#: 模組級全域——見 `_repo_write_guard.ViolationAccumulator` docstring）。
_G1_ACCUMULATOR_STASH_KEY = pytest.StashKey[_rwg.ViolationAccumulator]()


# `sqlite3.connect` 的位置參數順序（Argument Clinic 產生的 `__text_signature__`）：
#   (database, timeout, detect_types, isolation_level, check_same_thread,
#    factory, cached_statements, uri, *, autocommit)
# ⇒ **`uri` 是合法的第 8 個位置參數**（`autocommit` 才是 keyword-only）。
#
# 🔴 不要改用 `inspect.signature(sqlite3.connect).bind(...)`：它是 builtin，
# `inspect` 解不動 `autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL` 這個預設值，
# 實測直接 `ValueError: builtin has invalid signature` ⇒ 每一次 connect 都會炸。
# 手動維護這張表只讀不算，是安全的做法。
#
# 漏讀位置傳入的 `uri` 的後果是**假紅不是漏放**：`evaluate_connect()` 會把
# `file:/tmp/x.db?mode=rwc` 當成相對路徑（`os.path.isabs("file:/...")` 為 False）
# ⇒ 本該 row05 放行的落成 row08 拒絕。`fail` 模式下那支測試會無故變紅。
# 回歸鎖：`tests/unit/test_repo_write_guard.py::TestWrapperArgumentBinding`。
_CONNECT_POSITIONAL_PARAMS = (
    "database", "timeout", "detect_types", "isolation_level",
    "check_same_thread", "factory", "cached_statements", "uri",
)


@pytest.fixture(autouse=True)
def _g1_repo_write_guard(request, monkeypatch, tmp_path_factory):
    """patch `sqlite3.connect`，白名單制 fail-closed 判定（見 `_repo_write_guard.py`）。

    鏡像操作對稱：用 `monkeypatch.setattr` 掛上去，pytest 保證即使測試中途
    example/early-return 也會在 teardown 還原——不手動 `patcher.start()`/`stop()`。

    雙層拋出（TASK-127b-T5 技術要點①，**設計約束，不得簡化成一層**）：
      第 1 層（inline，這裡的 `_g1_wrapper` 內，真正呼叫 `original_connect`
        之前）：`mode == fail` 且沒有 `allow_real_db` marker ⇒ 立刻拋
        `RepoWriteGuardViolation`（`BaseException` 子類，穿透產品碼的
        `except Exception`），**擋得住那次連線**，同時把這筆記錄塞進本支測試的
        `ViolationAccumulator`。
      第 2 層（teardown，`yield` 之後）：若累積器有記錄、而這支測試的 call
        階段最終**沒有**因此失敗（`item.rep_call.failed` 為否——代表某處用
        `except BaseException` 把 inline 那層吞了），再拋一次
        `RepoWriteGuardViolation` 彙總告警。專守「未來有人在 DB 路徑上新增
        `except BaseException`」的情況（本專案已有 3 處這種寫法，見
        TASK-127b-T5.md「✅ 解法的實證」表）。
      掛 `allow_real_db` marker 的違規**只進 report，不進累積器**——marker
      的語意是「記錄照記、只跳過拋出」，累積器只用來驅動 teardown 補刀，
      兩者是分開的容器（見①-c，寫成同一個會讓 marker 這個逃生口失效）。
    """
    mode = _rwg.get_mode()
    if mode == _rwg.MODE_OFF:
        yield
        return

    repo_root = _rwg.get_repo_root()
    tmp_roots = _rwg.get_tmp_roots()
    basetemp = tmp_path_factory.getbasetemp()
    nodeid = request.node.nodeid
    has_marker = request.node.get_closest_marker(_rwg.ALLOW_REAL_DB_MARKER) is not None
    original_connect = sqlite3.connect
    accumulator = _rwg.ViolationAccumulator()
    request.node.stash[_G1_ACCUMULATOR_STASH_KEY] = accumulator

    def _g1_wrapper(*args, **kwargs):
        bound = dict(zip(_CONNECT_POSITIONAL_PARAMS, args))
        bound.update(kwargs)
        database = bound.get("database")
        uri = bound.get("uri", False)
        decision = _rwg.evaluate_connect(
            database, uri,
            repo_root=repo_root, tmp_roots=tmp_roots, basetemp=basetemp,
        )
        if not decision.allowed:
            record = _rwg.format_g1_record(nodeid, decision, allowed_by_marker=has_marker)
            _rwg.append_report_record(record)
            if mode == _rwg.MODE_FAIL and not has_marker:
                accumulator.add(record)
                raise _rwg.RepoWriteGuardViolation(
                    f"[repo_write_guard/G1] 拒絕的 sqlite3.connect 呼叫："
                    f"nodeid={nodeid} reason={decision.case} "
                    f"raw={decision.raw_repr} resolved={decision.resolved}\n"
                    "怎麼修（四種既有慣例，挑對得上的那個）：\n"
                    "  1. patch 使用端的 `get_db_path`（**不是定義端**——24 個 import "
                    "landing point 會漂）：`patch(\"<被測模組>.get_db_path\", "
                    "lambda: tmp_path / \"x.db\")`\n"
                    "  2. 用 mock repo 時**明確設** `mock_repo.db_path = \":memory:\"`"
                    "（漏設 ⇒ 產品碼 `str(MagicMock)` 會拿 repr 當檔名）\n"
                    "  3. module-level lazy 單例（`core.access_auth._snapshot`、"
                    "`core.similar.canonicalize._merged_alias_map`）要用 **fixture 形狀**"
                    "前後各清一次，不能只清一邊\n"
                    "  4. 這支測試**真的**需要碰真實 DB ⇒ 掛 "
                    "`@pytest.mark.allow_real_db`（會照樣記進 report，只是不擋）"
                )
        return original_connect(*args, **kwargs)

    _g1_wrapper.__openaver_g1_wrapper__ = True
    monkeypatch.setattr(sqlite3, "connect", _g1_wrapper)
    yield

    if mode == _rwg.MODE_FAIL and accumulator:
        # 🔴 setup 與 call **兩個階段都要看**（sonnet review 2026-08-24 P2）。
        # 只看 `rep_call` 的話，違規發生在「某個依賴 G1 的 fixture 自己的 setup
        # 階段」時（例如 `def other(_g1_repo_write_guard): sqlite3.connect(bad)`），
        # call 階段根本沒跑過 ⇒ `rep_call` 從未被 `pytest_runtest_makereport`
        # 設過 ⇒ `already_failed` 判 False ⇒ 保險層補刀第二次，而且訊息會說
        # 「被 except BaseException 吞掉了」——**那是假的**，違規根本沒被吞，
        # 只是發生在另一個階段。實測：一支測試吐兩份 ERROR，第二份的診斷是錯的，
        # 會把未來的除錯者導去查一個不存在的 `except BaseException`。
        rep_setup = getattr(request.node, "rep_setup", None)
        rep_call = getattr(request.node, "rep_call", None)
        already_failed = bool(
            (rep_setup is not None and rep_setup.failed)
            or (rep_call is not None and rep_call.failed)
        )
        if not already_failed:
            raise _rwg.RepoWriteGuardViolation(
                f"[repo_write_guard/G1] teardown 保險：nodeid={nodeid} 累積到 "
                f"{len(accumulator)} 筆違規，但 setup／call 兩個階段都沒有因此"
                "失敗——代表 inline 拋出的 RepoWriteGuardViolation 在某處被"
                f"`except BaseException` 吞掉了。records={accumulator.records}\n"
                "先修那個 `except BaseException`（DB 路徑上不該有），"
                "或替這支測試掛 `@pytest.mark.allow_real_db`。"
            )


@pytest.fixture(autouse=True)
def _g2_repo_root_snapshot(request):
    """比對 repo 根第一層（非遞迴）快照，抓測試期間長出來的雜檔。

    雪崩防護：`before` 在**每一支測試**的 setup 期現掃現拿（不是掛一份全 session
    共用的可變 baseline），所以某支測試留下的雜檔只會被算到那一支頭上——後面的
    測試在它自己的 setup 期掃到時，那個檔案已經是「本來就在」的一部分。

    G2 沒有「inline 攔截點」——它只在事後比對快照,所以不像 G1 需要雙層拋出;
    這裡的單一拋出點本身就已經是「事後」,直接改用 `RepoWriteGuardViolation`
    即可穿透未來任何 `except Exception`。
    """
    mode = _rwg.get_mode()
    if mode == _rwg.MODE_OFF:
        yield
        return

    repo_root = _rwg.get_repo_root()
    nodeid = request.node.nodeid

    # patterns=None（預設）→ 走 `_cached_compiled_rules` 快取，同一個 repo_root
    # 只讀＋編譯一次 .gitignore，不隨每支測試的 setup/teardown 重跑磁碟 I/O
    # ＋線性 fnmatch 掃描（DoD「耗時增幅 < 5%」量到超標的主因，見該函式註解）。
    before = _rwg.scan_repo_root_first_level(repo_root)
    _rwg.require_nonzero_baseline(before, repo_root)  # BE-TEST-05：掃到 0 筆不是「乾淨」

    yield

    after = _rwg.scan_repo_root_first_level(repo_root)
    new_entries = after - before
    if new_entries:
        record = _rwg.format_g2_record(nodeid, new_entries)
        _rwg.append_report_record(record)
        if mode == _rwg.MODE_FAIL:
            raise _rwg.RepoWriteGuardViolation(
                f"[repo_write_guard/G2] repo 根第一層長出新檔案："
                f"nodeid={nodeid} new_entries={sorted(new_entries)}\n"
                "若你同時在跑別的會寫 repo 根的 process，這可能是誤報"
                "——G2 比對的是 repo 根第一層的快照，抓不出是哪個 process 寫的。\n"
                "怎麼修：讓那個寫入落到 `tmp_path` 底下。若檔名長得像 "
                "`<MagicMock ...>`，成因是某個 mock repo 沒設 `db_path`，"
                "產品碼 `str()` 之後拿 repr 當了檔名。"
            )


