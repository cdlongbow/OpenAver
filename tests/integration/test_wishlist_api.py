"""
test_wishlist_api.py — /api/wishlist 端點整合測試（TASK-140-T4）。

使用 FastAPI TestClient + tmp_path 真實 SQLite DB 與三個 get_db_path landing points 隔離。
"""
import sqlite3
import pytest
from fastapi.testclient import TestClient

from core.database import init_db
from core import wishlist_cover_cache


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """建立臨時測試資料庫"""
    db_path = tmp_path / "test_wishlist.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(tmp_db, monkeypatch):
    """TestClient，同時 patch 三個獨立的 get_db_path landing points"""
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)
    monkeypatch.setattr("core.wishlist_cover_cache.get_db_path", lambda: tmp_db)
    # 第三個 landing point 刻意**不包** try/except：`web/routers/wishlist.py` 對
    # `get_db_path` 的別名匯入（比照 search.py:33）是為了讓測試 patch 得到使用端
    # binding。哪天有人把那行匯入刪了，這裡要**立刻紅**——包成 try/except 會讓
    # 「隔離點消失」變成靜默通過，那正是 v0.15.5 清掉的形狀。
    monkeypatch.setattr("web.routers.wishlist.get_db_path", lambda: tmp_db)

    from web.app import app
    return TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_add_wishlist_happy_path(client, tmp_db, monkeypatch):
    """POST /api/wishlist 正常新增書籤，下載成功回 cover_available: True"""
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda number, primary, fallback: True)

    payload = {
        "number": "SONE-205",
        "title": "測試標題 1",
        "actors": ["明日花キララ"],
        "tags": ["巨乳", "單體作品"],
        "maker": "S1 NO.1 STYLE",
        "director": "監督A",
        "series": "系列A",
        "label": "廠牌A",
        "duration": 120,
        "date": "2025-01-01",
        "cover": "https://example.com/cover.jpg",
        "preview_cover_url": "https://example.com/preview.jpg",
        "sample_images": ["https://example.com/sample1.jpg"],
        "preview_sample_images": ["https://example.com/preview_sample1.jpg"],
        "source": "dmm",
        "url": "https://example.com/item/sone205",
    }
    resp = client.post("/api/wishlist", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["cover_available"] is True

    # 驗證 DB
    conn = sqlite3.connect(str(tmp_db))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wishlist WHERE number = ?", ("SONE-205",))
    row = cursor.fetchone()
    conn.close()
    assert row is not None


def test_add_wishlist_dto_field_mapping(client, tmp_db, monkeypatch):
    """DoD-3: 前端欄位名映射到 DB 正確欄位（actors->actresses, date->release_date, url->source_url）"""
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda number, primary, fallback: True)

    payload = {
        "number": "ABW-001",
        "title": "DTO Mapping Title",
        "actors": ["葵つかさ", "橋本ありな"],
        "tags": ["女教師"],
        "maker": "ABC",
        "director": "監督B",
        "series": "系列B",
        "label": "廠牌B",
        "duration": 150,
        "date": "2024-05-20",
        "cover": "https://example.com/cov.jpg",
        "preview_cover_url": "https://example.com/pcov.jpg",
        "sample_images": ["https://example.com/sample_full.jpg"],
        "preview_sample_images": ["https://example.com/sample_thumb.jpg"],
        "source": "mgstage",
        "url": "https://example.com/item/abw001",
    }
    resp = client.post("/api/wishlist", json=payload)
    assert resp.status_code == 200

    # 查 GET /api/wishlist
    list_resp = client.get("/api/wishlist")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["number"] == "ABW-001"
    assert item["actresses"] == ["葵つかさ", "橋本ありな"]
    assert item["release_date"] == "2024-05-20"
    assert item["source_url"] == "https://example.com/item/abw001"
    # cover 與 preview_cover_url 不進 DB / 不在傳回欄位中
    assert "cover" not in item
    assert "preview_cover_url" not in item
    # sample_images 與 preview_sample_images 不得塌縮
    assert item["sample_images"] == ["https://example.com/sample_full.jpg"]
    assert item["preview_sample_images"] == ["https://example.com/sample_thumb.jpg"]
    assert item["sample_images"] != item["preview_sample_images"]


def test_add_wishlist_cover_download_failure_still_succeeds(client, tmp_db, monkeypatch):
    """DoD-4: download_and_save 回 False 時，加入書籤仍成功（cover_available: False）"""
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda number, primary, fallback: False)

    resp = client.post("/api/wishlist", json={
        "number": "FAIL-001",
        "title": "Cover Fail Title",
        "cover": "https://example.com/notfound.jpg",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["cover_available"] is False

    # DB 中確實有該列
    count_resp = client.get("/api/wishlist/count")
    assert count_resp.json()["count"] == 1


def test_add_wishlist_cover_write_oserror_still_succeeds(client, tmp_db, monkeypatch):
    """DoD-4 & M2: download_and_save 丟 OSError 時，加入書籤仍成功且回 cover_available: False"""
    def _raise_oserror(number, primary, fallback):
        raise OSError("disk full or permission denied")

    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", _raise_oserror)

    resp = client.post("/api/wishlist", json={
        "number": "OSERR-001",
        "title": "OSError Title",
        "cover": "https://example.com/disk_full.jpg",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["cover_available"] is False

    # DB 中確實有該列
    count_resp = client.get("/api/wishlist/count")
    assert count_resp.json()["count"] == 1


def test_add_wishlist_duplicate_number(client, tmp_db, monkeypatch):
    """POST /api/wishlist 重複加入已存在番號，回 success: True 不拋錯且不重複網路下載"""
    called = []
    def _mock_download(number, primary, fallback):
        called.append(number)
        return True

    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", _mock_download)

    payload = {"number": "DUP-001", "title": "First", "cover": "http://cov"}
    resp1 = client.post("/api/wishlist", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["success"] is True
    assert len(called) == 1

    # 第二次加入
    resp2 = client.post("/api/wishlist", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True
    # 第一次加成功後第二次不重新觸發 download_and_save
    assert len(called) == 1


def test_list_wishlist_empty(client):
    """GET /api/wishlist 空清單回 []"""
    resp = client.get("/api/wishlist")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_wishlist_sorting_unowned_first_then_owned(client, tmp_db):
    """DoD-5: GET /api/wishlist 排序：未入手（新到舊）在前，已入手（新到舊）在後"""
    conn = sqlite3.connect(str(tmp_db))
    # 插入 3 筆書籤，created_at 由舊到新：AAA-001, BBB-002, CCC-003
    conn.execute("""
        INSERT INTO wishlist (number, title, created_at)
        VALUES
        ('AAA-001', 'Oldest Unowned', '2026-01-01 10:00:00'),
        ('BBB-002', 'Middle Owned', '2026-01-02 10:00:00'),
        ('CCC-003', 'Newest Unowned', '2026-01-03 10:00:00')
    """)
    # 在 videos 表中插入 BBB-002（已入手）
    conn.execute("""
        INSERT INTO videos (path, number, title)
        VALUES ('file:///test/BBB-002.mp4', 'BBB-002', 'Owned Video')
    """)
    conn.commit()
    conn.close()

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3

    # 順序應為：CCC-003 (未入手，最新), AAA-001 (未入手，較舊), BBB-002 (已入手)
    assert items[0]["number"] == "CCC-003"
    assert items[0]["_owned"] is False

    assert items[1]["number"] == "AAA-001"
    assert items[1]["_owned"] is False

    assert items[2]["number"] == "BBB-002"
    assert items[2]["_owned"] is True


def test_fc2_legacy_number_format_stays_unowned_by_design(client, tmp_db):
    """DoD-6: FC2 格式舊列殘留（書籤 FC2-1234567 vs videos FC2PPV-1234567）依設計維持 _owned: False。"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO wishlist (number, title, created_at)
        VALUES ('FC2-1234567', 'FC2 Wishlist Item', '2026-01-01 10:00:00')
    """)
    conn.execute("""
        INSERT INTO videos (path, number, title)
        VALUES ('file:///test/FC2PPV-1234567.mp4', 'FC2PPV-1234567', 'Legacy FC2 Video')
    """)
    conn.commit()
    conn.close()

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["number"] == "FC2-1234567"
    assert items[0]["_owned"] is False


def test_delete_wishlist_existing(client, tmp_db):
    """DELETE /api/wishlist/{number} 存在番號回 success: True 並刪除封面"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO wishlist (number, title) VALUES ('IPX-123', 'Delete Target')")
    conn.commit()
    conn.close()

    # 建立封面檔案
    cover_file = wishlist_cover_cache.cover_file_for("IPX-123")
    cover_file.parent.mkdir(parents=True, exist_ok=True)
    cover_file.write_bytes(b"RIFF....WEBPVP8 ...fake...")
    assert cover_file.exists()

    resp = client.delete("/api/wishlist/IPX-123")
    assert resp.status_code == 200
    assert resp.json() == {"success": True}

    # 驗證 DB 已刪除
    conn = sqlite3.connect(str(tmp_db))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM wishlist WHERE number = 'IPX-123'")
    assert cursor.fetchone()[0] == 0
    conn.close()

    # 驗證封面檔案已刪除
    assert not cover_file.exists()


def test_delete_wishlist_nonexistent(client, tmp_db):
    """DELETE /api/wishlist/{number} 不存在番號回 success: False (200 OK，非 404)"""
    resp = client.delete("/api/wishlist/NONEXISTENT-999")
    assert resp.status_code == 200
    assert resp.json() == {"success": False}


def test_wishlist_count(client, tmp_db):
    """GET /api/wishlist/count 回傳總書籤數"""
    resp0 = client.get("/api/wishlist/count")
    assert resp0.status_code == 200
    assert resp0.json() == {"count": 0}

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO wishlist (number, title) VALUES ('C-001', 'T1'), ('C-002', 'T2')")
    conn.commit()
    conn.close()

    resp1 = client.get("/api/wishlist/count")
    assert resp1.status_code == 200
    assert resp1.json() == {"count": 2}


def test_wishlist_membership_mixed_and_casing(client, tmp_db):
    """POST /api/wishlist/membership 混合命中/未命中，key 使用原始輸入字串"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO wishlist (number, title) VALUES ('IPX-123', 'T1'), ('SSIS-456', 'T2')")
    conn.commit()
    conn.close()

    resp = client.post("/api/wishlist/membership", json={
        "numbers": ["ipx-123", "SSIS-456", "UNKNOWN-001"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "ipx-123": True,
        "SSIS-456": True,
        "UNKNOWN-001": False,
    }


def test_wishlist_membership_empty(client, tmp_db):
    """POST /api/wishlist/membership 空陣列回 {}"""
    resp = client.post("/api/wishlist/membership", json={"numbers": []})
    assert resp.status_code == 200
    assert resp.json() == {}


def test_cleanup_deletes_only_owned_and_leaves_others(client, tmp_db):
    """DoD-7 & M1: POST /api/wishlist/cleanup 只刪已入手的書籤與封面，保留未入手的"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO wishlist (number, title)
        VALUES
        ('OWNED-001', 'Owned Title'),
        ('UNOWNED-002', 'Unowned Title 2'),
        ('UNOWNED-003', 'Unowned Title 3')
    """)
    conn.execute("""
        INSERT INTO videos (path, number, title)
        VALUES ('file:///test/OWNED-001.mp4', 'OWNED-001', 'Owned Video')
    """)
    conn.commit()
    conn.close()

    # 建立三者的封面檔案
    f1 = wishlist_cover_cache.cover_file_for("OWNED-001")
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_bytes(b"cover1")

    f2 = wishlist_cover_cache.cover_file_for("UNOWNED-002")
    f2.parent.mkdir(parents=True, exist_ok=True)
    f2.write_bytes(b"cover2")

    f3 = wishlist_cover_cache.cover_file_for("UNOWNED-003")
    f3.parent.mkdir(parents=True, exist_ok=True)
    f3.write_bytes(b"cover3")

    resp = client.post("/api/wishlist/cleanup")
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 1}

    # 已入手的封面被刪
    assert not f1.exists()
    # 未入手的封面保留
    assert f2.exists()
    assert f3.exists()

    # DB 中剩下 2 筆
    count_resp = client.get("/api/wishlist/count")
    assert count_resp.json()["count"] == 2


def test_cleanup_all_unowned_noop(client, tmp_db):
    """POST /api/wishlist/cleanup 全部未入手時回 deleted_count: 0"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO wishlist (number, title) VALUES ('UN-1', 'T1'), ('UN-2', 'T2')")
    conn.commit()
    conn.close()

    resp = client.post("/api/wishlist/cleanup")
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 0}

    count_resp = client.get("/api/wishlist/count")
    assert count_resp.json()["count"] == 2


def test_get_wishlist_cover_hit(client, tmp_db):
    """DoD-8: GET /api/wishlist/cover 命中回 200 image/webp 與正確 bytes 且 Cache-Control: no-cache"""
    fake_webp = b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00"
    cover_file = wishlist_cover_cache.cover_file_for("SONE-205")
    cover_file.parent.mkdir(parents=True, exist_ok=True)
    cover_file.write_bytes(fake_webp)

    resp = client.get("/api/wishlist/cover?number=sone-205")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/webp"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.content == fake_webp


def test_get_wishlist_cover_miss(client, tmp_db):
    """DoD-8: GET /api/wishlist/cover 未命中回 404"""
    resp = client.get("/api/wishlist/cover?number=NONEXISTENT-999")
    assert resp.status_code == 404
