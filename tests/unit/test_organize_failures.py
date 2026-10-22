"""
tests/unit/test_organize_failures.py — 失敗記憶資料層測試（TASK-144-T2）

覆蓋 DoD 1–11 與 mutation 點 M1–M6。
"""
import pytest

from core.database.connection import init_db, get_connection


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_failures.db"
    init_db(db_path)
    return db_path


def test_should_skip_within_24h_window(test_db):
    """DoD-2 (M1): 寫入一筆 not_found → last_failed_at + 23h 查為 True；+ 25h 為 False。"""
    from core.database.organize_failures import record_failure, should_skip

    t0 = 1_700_000_000.0
    record_failure("not_found", "ABP-123", "ABP-123", now=t0, db_path=test_db)

    # 23 小時後：在 24 小時退避窗內 → 應跳過 (True)
    assert should_skip("not_found", "ABP-123", now=t0 + 23 * 3600, db_path=test_db) is True

    # 25 小時後：已過 24 小時退避窗 → 不跳過 (False)
    assert should_skip("not_found", "ABP-123", now=t0 + 25 * 3600, db_path=test_db) is False


def test_should_skip_7d_window(test_db):
    """DoD-3 (M2): 同一鍵第二次失敗（attempt_count 變 2）→ + 6 天為 True；+ 8 天為 False。"""
    from core.database.organize_failures import record_failure, should_skip

    t0 = 1_700_000_000.0
    record_failure("not_found", "ABP-123", "ABP-123", now=t0, db_path=test_db)

    # 第二次失敗，時間戳為 t1
    t1 = t0 + 25 * 3600
    record_failure("not_found", "ABP-123", "ABP-123", now=t1, db_path=test_db)

    # 6 天後：在 7 天退避窗內 → 應跳過 (True)
    assert should_skip("not_found", "ABP-123", now=t1 + 6 * 86400, db_path=test_db) is True

    # 8 天後：已過 7 天退避窗 → 不跳過 (False)
    assert should_skip("not_found", "ABP-123", now=t1 + 8 * 86400, db_path=test_db) is False


def test_should_skip_unknown_key_returns_false(test_db):
    """DoD-4 (M3): 查一個表裡沒有的鍵 → should_skip 回 False（從未失敗過，非已過期）。"""
    from core.database.organize_failures import should_skip, record_failure

    # 空表查詢
    assert should_skip("not_found", "UNKNOWN-999", db_path=test_db) is False

    # 表裡有其他鍵時查詢不存在的鍵
    record_failure("not_found", "EXIST-001", "EXIST-001", db_path=test_db)
    assert should_skip("not_found", "UNKNOWN-999", db_path=test_db) is False
    assert should_skip("duplicate", "EXIST-001", db_path=test_db) is False


def test_case_insensitive_key(test_db):
    """DoD-7 (M6): 番號大小寫不敏感，record_failure 用小寫，should_skip 與 clear_on_success 用大寫/小寫/混合。"""
    from core.database.organize_failures import record_failure, should_skip, clear_on_success

    # 小寫寫入（SQL UPPER 存為大寫 ABC-123）
    record_failure("not_found", "abc-123", "abc-123", now=1_700_000_000.0, db_path=test_db)

    # 小寫查詢必須命中（若 WHERE 去掉 UPPER(?) 則 abc-123 != ABC-123 會回 False，M6 即被抓出）
    assert should_skip("not_found", "abc-123", now=1_700_000_000.0 + 3600, db_path=test_db) is True

    # 大寫查詢也應命中
    assert should_skip("not_found", "ABC-123", now=1_700_000_000.0 + 3600, db_path=test_db) is True

    # 混合大小寫清除
    clear_on_success("aBc-123", db_path=test_db)

    # 清除後大寫查應回 False（從未失敗過 / 已清空）
    assert should_skip("not_found", "ABC-123", now=1_700_000_000.0 + 3600, db_path=test_db) is False


def test_duplicate_key_is_case_sensitive_not_uppercased(test_db):
    """`duplicate` 的鍵是路徑 URI，**逐字原樣存**，不得比照番號做大小寫正規化。

    使用者流程（本功能的目標平台就是這一種）：片庫放在 NAS／Linux（區分大小寫），
    最愛資料夾裡同時有 `/videos/abc-123.mp4` 與 `/videos/ABC-123.mp4` 兩個**不同的**檔案
    → 其中一個因為「目標已存在」被記進失敗記憶 → 若鍵被大寫化，兩者會撞成同一列
    → **另一個檔也跟著被跳過**，最長 7 天不會被自動整理，而使用者看不出為什麼。

    這同時是 CD-144-8「以 `to_file_uri(fs_path, path_mappings)` 正規化後存」的字面要求
    ——大寫化不是正規化。
    """
    from core.database.organize_failures import record_failure, should_skip

    lower_key = "file:///videos/abc-123.mp4"
    upper_key = "file:///videos/ABC-123.mp4"
    base = 1_700_000_000.0

    record_failure("duplicate", lower_key, "ABC-123", duplicate_target="x.mp4",
                   now=base, db_path=test_db)

    assert should_skip("duplicate", lower_key, now=base + 60, db_path=test_db) is True
    assert should_skip("duplicate", upper_key, now=base + 60, db_path=test_db) is False, (
        "大小寫不同的路徑是兩個不同的檔案，不該共用同一筆失敗記憶"
    )

    # 兩者各自記一筆之後必須是兩列，不是一列
    record_failure("duplicate", upper_key, "ABC-123", duplicate_target="y.mp4",
                   now=base, db_path=test_db)
    with get_connection(test_db) as conn:
        n = conn.cursor().execute(
            "SELECT COUNT(*) FROM organize_failures WHERE reason = 'duplicate'"
        ).fetchone()[0]
    assert n == 2, "兩個大小寫不同的路徑必須各自佔一列"


