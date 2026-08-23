import pytest
import sqlite3
from pathlib import Path
import json
from core import config as core_config
import _repo_write_guard as _rwg

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


# ============ TASK-127b-T3：G1／G2 repo-write 守衛（autouse，骨架，預設 report）====
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
# 本 task（T3）預設模式固定 `report`：只記錄不擋，`report` 模式下全套的綠紅
# 狀態必須與上線前完全相同——這是 DoD 硬性要求，不是這裡順手做到的。
# T5 才會把 `OPENAVER_REPO_WRITE_GUARD` 預設切成 `fail`。


@pytest.fixture(autouse=True)
def _g1_repo_write_guard(request, monkeypatch, tmp_path_factory):
    """patch `sqlite3.connect`，白名單制 fail-closed 判定（見 `_repo_write_guard.py`）。

    鏡像操作對稱：用 `monkeypatch.setattr` 掛上去，pytest 保證即使測試中途
    example/early-return 也會在 teardown 還原——不手動 `patcher.start()`/`stop()`。
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

    def _g1_wrapper(*args, **kwargs):
        database = args[0] if args else kwargs.get("database")
        uri = kwargs.get("uri", False)
        decision = _rwg.evaluate_connect(
            database, uri,
            repo_root=repo_root, tmp_roots=tmp_roots, basetemp=basetemp,
        )
        if not decision.allowed:
            record = _rwg.format_g1_record(nodeid, decision, allowed_by_marker=has_marker)
            _rwg.append_report_record(record)
            if mode == _rwg.MODE_FAIL and not has_marker:
                raise AssertionError(
                    f"[repo_write_guard/G1] 拒絕的 sqlite3.connect 呼叫："
                    f"nodeid={nodeid} reason={decision.case} "
                    f"raw={decision.raw_repr} resolved={decision.resolved}"
                )
        return original_connect(*args, **kwargs)

    _g1_wrapper.__openaver_g1_wrapper__ = True
    monkeypatch.setattr(sqlite3, "connect", _g1_wrapper)
    yield


@pytest.fixture(autouse=True)
def _g2_repo_root_snapshot(request):
    """比對 repo 根第一層（非遞迴）快照，抓測試期間長出來的雜檔。

    雪崩防護：`before` 在**每一支測試**的 setup 期現掃現拿（不是掛一份全 session
    共用的可變 baseline），所以某支測試留下的雜檔只會被算到那一支頭上——後面的
    測試在它自己的 setup 期掃到時，那個檔案已經是「本來就在」的一部分。
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
            raise AssertionError(
                f"[repo_write_guard/G2] repo 根第一層長出新檔案："
                f"nodeid={nodeid} new_entries={sorted(new_entries)}"
            )


