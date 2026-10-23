"""Unit tests for core.wishlist_reconcile (TASK-141a-T2).

走真實 WishlistRepository／VideoRepository（tmp_path 真 SQLite DB），
比照 test_wishlist_repository.py 慣例；封面路徑經 wishlist_cover_cache.get_db_path 隔離。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from core.database import WishlistRepository, init_db


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> Path:
    """乾淨 schema 的臨時 DB，並把兩個 get_db_path landing point 導向它。"""
    path = tmp_path / "test_reconcile.db"
    init_db(path)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: path)
    monkeypatch.setattr("core.wishlist_cover_cache.get_db_path", lambda: path)
    return path


def test_reconcile_wishlist_videos_table_zero_writes(
    db_path: Path, monkeypatch
) -> None:
    """DoD 5：VideoRepository 除 get_by_numbers 外零方法呼叫。"""
    from core.wishlist_reconcile import reconcile_wishlist

    wishlist = WishlistRepository()
    assert wishlist.add("OWNED-001", title="a") is True
    assert wishlist.add("KEEP-001", title="b") is True

    video_repo = MagicMock()
    video_repo.get_by_numbers.return_value = {
        "OWNED-001": [MagicMock()],
        "KEEP-001": [],
    }
    monkeypatch.setattr(
        "core.wishlist_reconcile.VideoRepository",
        lambda *a, **k: video_repo,
    )

    removed = reconcile_wishlist()

    # list_all 依 created_at 降序：後加的 KEEP-001 在前
    assert removed == ["OWNED-001"]
    assert video_repo.method_calls == [
        call.get_by_numbers(["KEEP-001", "OWNED-001"])
    ]


def test_format_wishlist_removed_message_eight_numbers() -> None:
    """DoD 6：8 筆 → 前 5 個 ＋「及其他 3 部」；逐字比對完整字串。"""
    from core.wishlist_reconcile import format_wishlist_removed_message

    numbers = [f"NUM-{i:03d}" for i in range(1, 9)]
    assert format_wishlist_removed_message(numbers) == (
        "8 部片已入庫，已從書籤移除：NUM-001、NUM-002、NUM-003、NUM-004、NUM-005，及其他 3 部"
    )


