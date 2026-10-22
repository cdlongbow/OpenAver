"""Unit tests for WishlistRepository and wishlist schema (TASK-140-T2)."""
import sqlite3
import pytest
from pathlib import Path

from core.database import init_db
from core.database.wishlist import WishlistRepository


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """建立乾淨 schema 的臨時 DB。"""
    db_path = tmp_path / "test_wishlist.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def repo(empty_db: Path) -> WishlistRepository:
    """注入 WishlistRepository 實例。"""
    return WishlistRepository(empty_db)


def test_init_db_in_place_upgrade_preserves_videos_and_creates_wishlist(tmp_path: Path) -> None:
    """DoD-1: init_db 對已有 videos 表但無 wishlist 表的舊 DB 就地升級，兩表並存且資料不遺失。"""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    # 手動建立既有 videos 表（無 wishlist 表）
    cursor.execute("""
        CREATE TABLE videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            number TEXT,
            title TEXT,
            original_title TEXT,
            actresses TEXT,
            maker TEXT,
            director TEXT DEFAULT '',
            series TEXT,
            label TEXT DEFAULT '',
            tags TEXT,
            sample_images TEXT DEFAULT '',
            user_tags TEXT DEFAULT '[]',
            output_dir TEXT DEFAULT '',
            duration INTEGER,
            size_bytes INTEGER,
            cover_path TEXT,
            release_date TEXT,
            mtime REAL,
            nfo_mtime REAL,
            scrape_attempted_at REAL DEFAULT 0,
            auto_focal TEXT DEFAULT '',
            crop_mode TEXT NOT NULL DEFAULT 'auto',
            focal_attempted_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "INSERT INTO videos (path, number, title, maker) VALUES (?, ?, ?, ?)",
        ("/videos/ABC-001.mp4", "ABC-001", "Old Video Title", "SOD"),
    )
    conn.commit()
    conn.close()

    # 執行 init_db 升級
    init_db(db_path)

    # 驗證升級後兩表並存
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "videos" in tables
    assert "wishlist" in tables

    # 驗證 videos 表既有資料還在
    video_row = cursor.execute(
        "SELECT path, number, title FROM videos WHERE number = 'ABC-001'"
    ).fetchone()
    assert video_row is not None
    assert video_row[0] == "/videos/ABC-001.mp4"
    assert video_row[1] == "ABC-001"
    assert video_row[2] == "Old Video Title"

    # 驗證 idx_wishlist_created_at 索引存在
    indices = {
        row[1]
        for row in cursor.execute("PRAGMA index_list(wishlist)").fetchall()
    }
    assert "idx_wishlist_created_at" in indices
    conn.close()


def test_add_duplicate_returns_false_and_count_remains_one(repo: WishlistRepository) -> None:
    """DoD-4: I1 不變式——重複加入同一書籤回傳 False，且筆數維持 1。"""
    assert repo.add("ABP-123", title="First") is True
    assert repo.add("ABP-123", title="Second") is False
    assert repo.count() == 1
    items = repo.list_all()
    assert len(items) == 1
    assert items[0]["title"] == "First"


def test_all_12_fields_mapping_and_json_roundtrip_with_forward_lock(
    repo: WishlistRepository,
) -> None:
    """DoD-3 / BE-DATA-07: 12 條欄位映射完整 roundtrip ＋ 正向鎖。"""
    sample_imgs = ["https://img.com/1.jpg", "https://img.com/2.jpg"]
    preview_imgs = ["https://preview.com/1.jpg", "https://preview.com/2.jpg"]

    ok = repo.add(
        number="MIDE-001",
        title="Sample Video",
        actresses=["女優A", "女優B"],
        tags=["標籤1", "標籤2"],
        maker="S1",
        director="導演X",
        series="系列Y",
        label="廠牌Z",
        duration=120,
        release_date="2026-01-01",
        cover_path="/covers/MIDE-001.jpg",
        sample_images=sample_imgs,
        preview_sample_images=preview_imgs,
        source="dmm",
        source_url="https://dmm.co.jp/video/1",
    )
    assert ok is True

    items = repo.list_all()
    assert len(items) == 1
    item = items[0]

    assert item["number"] == "MIDE-001"
    assert item["title"] == "Sample Video"
    assert item["actresses"] == ["女優A", "女優B"]
    assert item["tags"] == ["標籤1", "標籤2"]
    assert item["maker"] == "S1"
    assert item["director"] == "導演X"
    assert item["series"] == "系列Y"
    assert item["label"] == "廠牌Z"
    assert item["duration"] == 120
    assert item["release_date"] == "2026-01-01"
    assert item["cover_path"] == "/covers/MIDE-001.jpg"
    assert item["sample_images"] == sample_imgs
    assert item["preview_sample_images"] == preview_imgs
    assert item["source"] == "dmm"
    assert item["source_url"] == "https://dmm.co.jp/video/1"
    assert isinstance(item["created_at"], str)

    # BE-DATA-07 正向鎖：preview_sample_images 與 sample_images 等長同序但不相等
    assert item["preview_sample_images"] != item["sample_images"]
    assert len(item["preview_sample_images"]) == len(item["sample_images"])


