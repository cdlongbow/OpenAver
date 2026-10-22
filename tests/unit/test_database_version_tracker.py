"""測試 core/database/version_tracker.py（TASK-145-T2，CD-145a-10）。"""

import pytest

from core.database import get_connection, init_db
from core.database.version_tracker import (
    get_showcase_revision,
)


def test_with_block_write_bumps_revision_and_persists(tmp_path):
    """with get_connection(...) 內 INSERT、無顯式 commit → 離開 with 後 revision +1，
    且資料真的寫進 DB（證明走的是 Python 層 commit，不是 C 層靜默 commit）。
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    start = get_showcase_revision()

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO videos (path, number) VALUES (?, ?)",
            ("/fake/with-block.mp4", "with-block"),
        )

    assert get_showcase_revision() == start + 1

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT number FROM videos WHERE number = ?",
        ("with-block",),
    ).fetchone()
    conn.close()
    assert row == ("with-block",)


def test_with_block_exception_rolls_back_and_does_not_bump(tmp_path):
    """with 區塊內拋例外 → 資料未寫入、例外傳出、revision 不變。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    start = get_showcase_revision()

    with pytest.raises(RuntimeError, match="boom"):
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO videos (path, number) VALUES (?, ?)",
                ("/fake/with-rollback.mp4", "with-rollback"),
            )
            raise RuntimeError("boom")

    assert get_showcase_revision() == start

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT number FROM videos WHERE number = ?",
        ("with-rollback",),
    ).fetchone()
    conn.close()
    assert row is None


# ============ compute_etag() (TASK-145-T3) ============

_FP = ((True, 1, 2, 3, 4), (False, 0, 0, 0, 0))
_PROJECTION = {"directories": ["/a"], "path_mappings": {}, "thumbnail_cache_enabled": False}


