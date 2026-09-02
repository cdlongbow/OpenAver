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


def test_add_and_count(repo: WishlistRepository) -> None:
    """DoD-2: 基本 add 與 count 方法測試。"""
    assert repo.count() == 0
    assert repo.add("ABP-123", title="Test Title") is True
    assert repo.count() == 1


def test_add_duplicate_returns_false_and_count_remains_one(repo: WishlistRepository) -> None:
    """DoD-4: I1 不變式——重複加入同一書籤回傳 False，且筆數維持 1。"""
    assert repo.add("ABP-123", title="First") is True
    assert repo.add("ABP-123", title="Second") is False
    assert repo.count() == 1
    items = repo.list_all()
    assert len(items) == 1
    assert items[0]["title"] == "First"


def test_add_normalizes_number_before_insert(repo: WishlistRepository) -> None:
    """DoD-5 / Mutation 守衛: 加入書籤時做防禦性番號正規化。"""
    assert repo.add("fc2ppv-1234567", title="FC2 Sample") is True
    items = repo.list_all()
    assert len(items) == 1
    assert items[0]["number"] == "FC2-1234567"


def test_remove_normalizes_number_and_deletes(repo: WishlistRepository) -> None:
    """DoD-5: 移除書籤時鏡像正規化番號。"""
    repo.add("FC2-1234567", title="FC2 Sample")
    assert repo.count() == 1
    # 用未正規化番號呼叫 remove
    assert repo.remove("fc2ppv-1234567") is True
    assert repo.count() == 0
    # 再次刪除回傳 False
    assert repo.remove("fc2ppv-1234567") is False


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


def test_list_all_empty_table_returns_empty_list(repo: WishlistRepository) -> None:
    """空表查詢回傳空清單，不拋例外。"""
    assert repo.list_all() == []


def test_list_all_handles_corrupted_or_null_json_fields(empty_db: Path) -> None:
    """四個 list 欄位若為空字串、NULL 或損毀 JSON，回傳 [] 而非拋例外。"""
    conn = sqlite3.connect(str(empty_db))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wishlist (
            number, title, actresses, tags, sample_images, preview_sample_images
        ) VALUES (
            'CORRUPT-001', 'Corrupt Data', 'invalid json {', '', NULL, '["valid_preview"]'
        )
    """)
    conn.commit()
    conn.close()

    repo = WishlistRepository(empty_db)
    items = repo.list_all()
    assert len(items) == 1
    item = items[0]
    assert item["actresses"] == []
    assert item["tags"] == []
    assert item["sample_images"] == []
    assert item["preview_sample_images"] == ["valid_preview"]


def test_list_all_orders_newest_first(empty_db: Path) -> None:
    """list_all() 必須新→舊（F6「未入手段內部按加入時間新→舊」的資料層契約）。

    grok review（TASK-140-T2 Step 5）指出原稿只驗內容不驗順序——把 `ORDER BY
    created_at DESC` 刪掉或改成 ASC，10 支測試照樣全綠。用直接寫入的 created_at
    釘住順序（不靠 sleep 等時鐘跳秒，那會讓測試變慢且不穩）。
    """
    conn = sqlite3.connect(str(empty_db))
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO wishlist (number, title, created_at) VALUES (?, ?, ?)",
        [
            ("OLD-001", "oldest", "2026-01-01 00:00:00"),
            ("NEW-003", "newest", "2026-03-01 00:00:00"),
            ("MID-002", "middle", "2026-02-01 00:00:00"),
        ],
    )
    conn.commit()
    conn.close()

    numbers = [item["number"] for item in WishlistRepository(empty_db).list_all()]
    assert numbers == ["NEW-003", "MID-002", "OLD-001"]


def test_delete_many_empty_list(repo: WishlistRepository) -> None:
    """DoD-6: delete_many 傳入空清單回傳 0，不下 SQL。"""
    assert repo.delete_many([]) == 0


def test_delete_many_deletes_specified_and_preserves_others(
    repo: WishlistRepository,
) -> None:
    """DoD-6: delete_many 支援正規化，只刪清單內項目並保留其餘資料。"""
    repo.add("ABP-001", title="Title 1")
    repo.add("ABP-002", title="Title 2")
    repo.add("FC2-1234567", title="Title 3")
    repo.add("ABP-004", title="Title 4")

    # 包含小寫未正規化番號與不存在番號
    deleted = repo.delete_many(["abp-001", "fc2ppv-1234567", "NONEXISTENT-999"])
    assert deleted == 2
    assert repo.count() == 2

    remaining_numbers = {item["number"] for item in repo.list_all()}
    assert remaining_numbers == {"ABP-002", "ABP-004"}
