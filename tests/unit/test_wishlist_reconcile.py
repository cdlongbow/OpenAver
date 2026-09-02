"""Unit tests for core.wishlist_reconcile (TASK-141a-T2).

走真實 WishlistRepository／VideoRepository（tmp_path 真 SQLite DB），
比照 test_wishlist_repository.py 慣例；封面路徑經 wishlist_cover_cache.get_db_path 隔離。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from core.database import WishlistRepository, VideoRepository, init_db
from core import wishlist_cover_cache as wcc


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> Path:
    """乾淨 schema 的臨時 DB，並把兩個 get_db_path landing point 導向它。"""
    path = tmp_path / "test_reconcile.db"
    init_db(path)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: path)
    monkeypatch.setattr("core.wishlist_cover_cache.get_db_path", lambda: path)
    return path


def _insert_video(db_path: Path, number: str, path: str | None = None) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO videos (path, number, title) VALUES (?, ?, ?)",
        (path or f"/lib/{number}.mp4", number, f"title-{number}"),
    )
    conn.commit()
    conn.close()


def _touch_cover(number: str) -> Path:
    dest = wcc.cover_file_for(number)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fake-webp")
    return dest


def test_reconcile_wishlist_removes_owned_keeps_unowned(db_path: Path) -> None:
    """DoD 1 + DoD 2：3 已入手全刪、2 未入手全留且逐欄位零改動。"""
    from core.wishlist_reconcile import reconcile_wishlist

    wishlist = WishlistRepository()
    owned_nums = ["OWNED-001", "OWNED-002", "OWNED-003"]
    unowned_nums = ["KEEP-001", "KEEP-002"]

    for n in owned_nums + unowned_nums:
        assert wishlist.add(n, title=f"title-{n}", maker=f"maker-{n}") is True
        _touch_cover(n)

    for n in owned_nums:
        _insert_video(db_path, n)

    # BE-TEST-10：基準值必須在對帳之前取得
    before = {item["number"]: dict(item) for item in wishlist.list_all()}
    unowned_baseline = {n: before[n] for n in unowned_nums}

    removed = reconcile_wishlist()

    assert set(removed) == set(owned_nums)
    assert len(removed) == 3

    remaining = WishlistRepository().list_all()
    remaining_numbers = [item["number"] for item in remaining]
    assert set(remaining_numbers) == set(unowned_nums)
    assert len(remaining) == 2

    # DoD 2：未入手 2 筆逐欄位完全不變
    after = {item["number"]: dict(item) for item in remaining}
    for n in unowned_nums:
        assert after[n] == unowned_baseline[n]


def test_reconcile_wishlist_survives_cover_oserror(db_path: Path, monkeypatch) -> None:
    """DoD 3：remove() 對某一筆丟 OSError → 整支不炸、回傳完整清單、其餘封面照刪。"""
    from core.wishlist_reconcile import reconcile_wishlist

    wishlist = WishlistRepository()
    owned_nums = ["OWNED-001", "OWNED-002", "OWNED-003"]
    for n in owned_nums:
        assert wishlist.add(n, title=f"t-{n}") is True
        _touch_cover(n)
        _insert_video(db_path, n)

    boom_number = "OWNED-002"
    real_remove = wcc.remove

    def _boom(number: str) -> None:
        if number == boom_number:
            raise OSError(16, "Device or resource busy")
        return real_remove(number)

    monkeypatch.setattr("core.wishlist_cover_cache.remove", _boom)

    removed = reconcile_wishlist()

    assert set(removed) == set(owned_nums)
    assert len(removed) == 3
    assert WishlistRepository().count() == 0

    # boom 那筆可能留下孤兒檔；其餘兩筆必須刪掉
    assert not wcc.cover_file_for("OWNED-001").exists()
    assert not wcc.cover_file_for("OWNED-003").exists()


def test_reconcile_wishlist_no_owned_items_skips_delete_many(
    db_path: Path, monkeypatch
) -> None:
    """DoD 4：0 筆命中 → 空清單，且 delete_many 呼叫次數為 0。"""
    from core.wishlist_reconcile import reconcile_wishlist

    wishlist = WishlistRepository()
    assert wishlist.add("KEEP-001", title="a") is True
    assert wishlist.add("KEEP-002", title="b") is True
    # 片庫空 → 0 筆命中

    spy = MagicMock(wraps=WishlistRepository.delete_many)
    monkeypatch.setattr(WishlistRepository, "delete_many", spy)

    removed = reconcile_wishlist()

    assert removed == []
    assert spy.call_count == 0
    assert WishlistRepository().count() == 2


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


def test_format_wishlist_removed_message_five_or_fewer() -> None:
    """DoD 6：5 個以內 → 沒有「及其他」尾巴；句首是總數。"""
    from core.wishlist_reconcile import format_wishlist_removed_message

    numbers = ["A-001", "A-002", "A-003"]
    assert format_wishlist_removed_message(numbers) == (
        "3 部片已入庫，已從書籤移除：A-001、A-002、A-003"
    )

    five = [f"B-{i}" for i in range(1, 6)]
    assert format_wishlist_removed_message(five) == (
        "5 部片已入庫，已從書籤移除：B-1、B-2、B-3、B-4、B-5"
    )
