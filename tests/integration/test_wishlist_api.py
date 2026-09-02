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

@pytest.fixture(autouse=True)
def reset_buffer():
    """通知 buffer 是模組層級全域 deque，測試間必須清空，否則「恰好一筆」會閃爍。"""
    import web.routers.notifications as notif_mod
    notif_mod._notifications.clear()
    notif_mod._read_ids.clear()
    yield
    notif_mod._notifications.clear()
    notif_mod._read_ids.clear()


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


def test_list_wishlist_auto_removes_owned_items_on_load(client, tmp_db):
    """TASK-141a-T4 DoD 1: GET /api/wishlist 對帳後已入手項目直接消失（DB 真刪、無 _owned）。"""
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
    assert len(items) == 2
    assert [item["number"] for item in items] == ["CCC-003", "AAA-001"]
    for item in items:
        assert "_owned" not in item

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT COUNT(*) FROM wishlist WHERE number = ?",
        ("BBB-002",),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_fc2_legacy_number_format_survives_auto_removal(client, tmp_db):
    """TASK-141a-T4：FC2 舊列漏判（FC2- vs FC2PPV-）不會被自動移除。"""
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

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT COUNT(*) FROM wishlist WHERE number = ?",
        ("FC2-1234567",),
    ).fetchone()
    conn.close()
    assert row[0] == 1


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


def test_list_wishlist_reconcile_deletes_only_owned_and_leaves_others(client, tmp_db):
    """TASK-141a-T4：GET /api/wishlist 對帳只刪已入手的書籤與封面，保留未入手的"""
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

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200

    # 已入手的封面被刪
    assert not f1.exists()
    # 未入手的封面保留
    assert f2.exists()
    assert f3.exists()

    # DB 中剩下 2 筆
    count_resp = client.get("/api/wishlist/count")
    assert count_resp.json()["count"] == 2


def test_list_wishlist_reconcile_noop_when_all_unowned(client, tmp_db):
    """TASK-141a-T4：GET /api/wishlist 全部未入手時對帳為 no-op，清單與 count 不變"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO wishlist (number, title) VALUES ('UN-1', 'T1'), ('UN-2', 'T2')")
    conn.commit()
    conn.close()

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

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


def test_add_wishlist_reports_added_false_on_duplicate(client, tmp_db, monkeypatch):
    """branch review P2-1：重複加入回 added:false（success 仍 True，冪等語意不變）。

    沒有這個欄位，前端的樂觀 +1 補不回來——切換版本會把整顆結果物件換掉、連帶清掉
    `_wishlisted`，卡片變回「加入書籤」，再按一次計數就永久多一。
    """
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda *a, **k: True)
    payload = {"number": "ADDFLAG-001", "title": "x", "cover": "http://cov"}

    first = client.post("/api/wishlist", json=payload).json()
    assert first["success"] is True
    assert first["added"] is True, "第一次加入必須回 added:True"

    second = client.post("/api/wishlist", json=payload).json()
    assert second["success"] is True, "重複加入不是錯誤（冪等），success 維持 True"
    assert second["added"] is False, "重複加入必須回 added:False，否則前端計數補不回來"


def test_delete_wishlist_survives_cover_unlink_failure(client, tmp_db, monkeypatch):
    """Codex PR#175 P2：封面刪不掉（Windows 檔案鎖／防毒）不得讓已 commit 的刪除回 500。

    回 500 的話前端會把樂觀移除整個回滾 ⇒ 畫面跳出一張 DB 裡已經不存在的幽靈卡、
    計數還加一，要重新整理才會消失。
    """
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda *a, **k: True)
    client.post("/api/wishlist", json={"number": "LOCKED-001", "title": "x", "cover": "http://c"})

    def _boom(number):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr("core.wishlist_cover_cache.remove", _boom)

    resp = client.delete("/api/wishlist/LOCKED-001")
    assert resp.status_code == 200, "封面刪不掉不得變成 500"
    assert resp.json() == {"success": True}, "回應必須反映 DB 的權威狀態（那一列真的刪掉了）"
    assert client.get("/api/wishlist/count").json()["count"] == 0


def test_list_wishlist_reconcile_survives_cover_unlink_failure(client, tmp_db, monkeypatch):
    """TASK-141a-T4：GET 對帳路徑——第 k 筆封面刪檔失敗不得中斷、也不得回 500。"""
    monkeypatch.setattr("core.wishlist_cover_cache.download_and_save", lambda *a, **k: True)
    numbers = ("BATCHLOCK-001", "BATCHLOCK-002")
    for n in numbers:
        client.post("/api/wishlist", json={"number": n, "title": "x", "cover": "http://c"})
    conn = sqlite3.connect(str(tmp_db))
    conn.executemany(
        "INSERT INTO videos (path, number, title) VALUES (?, ?, ?)",
        [(f"/lib/{n}.mp4", n, "x") for n in numbers],
    )
    conn.commit()
    conn.close()

    def _boom(number):
        raise OSError(16, "Device or resource busy")

    monkeypatch.setattr("core.wishlist_cover_cache.remove", _boom)

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200, "封面刪不掉不得變成 500"
    assert resp.json() == []
    assert client.get("/api/wishlist/count").json()["count"] == 0


def test_list_wishlist_emits_single_reconcile_notification(client, tmp_db):
    """TASK-141a-T4 DoD 2: 一次 GET 恰好一筆 notif.wishlist_auto_removed，message 逐字比對。"""
    from core.wishlist_reconcile import format_wishlist_removed_message

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO wishlist (number, title, created_at)
        VALUES
        ('NOTIF-001', 'Owned One', '2026-01-01 10:00:00'),
        ('NOTIF-002', 'Owned Two', '2026-01-02 10:00:00')
    """)
    conn.executemany(
        "INSERT INTO videos (path, number, title) VALUES (?, ?, ?)",
        [
            ("/lib/NOTIF-001.mp4", "NOTIF-001", "v1"),
            ("/lib/NOTIF-002.mp4", "NOTIF-002", "v2"),
        ],
    )
    conn.commit()
    conn.close()

    # list_all 依 created_at DESC → 對帳回傳順序為 NOTIF-002, NOTIF-001
    expected_message = format_wishlist_removed_message(["NOTIF-002", "NOTIF-001"])

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200

    notif_resp = client.get("/api/notifications")
    assert notif_resp.status_code == 200
    items = notif_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title_key"] == "notif.wishlist_auto_removed"
    assert items[0]["level"] == "info"
    assert items[0]["message"] == expected_message
    assert items[0]["task_type"] == "wishlist_reconcile"


def test_list_wishlist_survives_reconcile_failure(client, tmp_db, monkeypatch):
    """branch review P2（2026-09-02）：對帳掛掉不得吃掉整份清單。

    三個對帳觸發點裡只有這一個是**使用者正盯著看的畫面**，卻是唯一沒做失敗隔離的。
    真實死法：掃描正在跑（upsert_batch 整個目錄一個交易）→ 使用者點開書籤分頁 →
    delete_many 撞寫鎖 → 5 秒後 database is locked → 這支回 500 → 前端 !resp.ok
    只 console.error、空狀態又要 wishlistLoaded 才顯示 ⇒ 整片空白零提示。
    """
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO wishlist (number, title, created_at) "
        "VALUES ('LOCK-001', 'Still Here', '2026-01-01 10:00:00')"
    )
    conn.commit()
    conn.close()

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("web.routers.wishlist.reconcile_wishlist", _boom)

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200, "對帳失敗不得讓清單回 500"
    numbers = [item["number"] for item in resp.json()]
    assert numbers == ["LOCK-001"], "清單必須照回，沒對到帳只是這次沒收斂"

    items = client.get("/api/notifications").json()["items"]
    assert len(items) == 1
    assert items[0]["title_key"] == "notif.wishlist_reconcile_failed"
    assert items[0]["level"] == "warn"
    assert items[0]["task_type"] == "wishlist_reconcile"


def test_list_wishlist_second_load_no_duplicate_notification(client, tmp_db, monkeypatch):
    """TASK-141a-T4 DoD 3: 連續兩次 GET → 第二次零通知、delete_many 不被呼叫。"""
    from core.database import WishlistRepository

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO wishlist (number, title)
        VALUES ('SECOND-001', 'Owned')
    """)
    conn.execute("""
        INSERT INTO videos (path, number, title)
        VALUES ('/lib/SECOND-001.mp4', 'SECOND-001', 'v')
    """)
    conn.commit()
    conn.close()

    real_delete_many = WishlistRepository.delete_many
    second_phase = {"active": False}
    second_calls = []

    def _counting_delete_many(self, numbers):
        if second_phase["active"]:
            second_calls.append(list(numbers))
        return real_delete_many(self, numbers)

    monkeypatch.setattr(
        "core.database.WishlistRepository.delete_many",
        _counting_delete_many,
    )

    first = client.get("/api/wishlist")
    assert first.status_code == 200

    notif_after_first = client.get("/api/notifications").json()["items"]
    assert len(notif_after_first) == 1

    second_phase["active"] = True
    second = client.get("/api/wishlist")
    assert second.status_code == 200

    notif_after_second = client.get("/api/notifications").json()["items"]
    assert len(notif_after_second) == 1
    assert second_calls == []


def test_cleanup_endpoint_removed(client):
    """TASK-141a-T4 DoD 4: POST /api/wishlist/cleanup 端點已移除，不再回 200 + deleted_count。

    Card 原文寫「回 404」；實際是 **405 Method Not Allowed**——`DELETE /{number}` 那條
    路徑模板仍然匹配 `/cleanup` 這個路徑，只是不接受 POST。端點確實不存在了
    （不再回 `deleted_count`），前端 `!resp.ok` 對 404／405 行為相同。
    """
    resp = client.post("/api/wishlist/cleanup")
    assert resp.status_code == 405
    assert resp.json() != {"deleted_count": 0}
    assert "deleted_count" not in resp.json()


def test_list_wishlist_reconcile_then_delete_race_converges(client, tmp_db, monkeypatch):
    """TASK-141a-T4 DoD 5: 對帳與 list_all 之間插入手動刪除 → 收斂到刪除後狀態。"""
    from core.database import WishlistRepository

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        INSERT INTO wishlist (number, title, created_at)
        VALUES
        ('RACE-X', 'Will Be Manually Deleted', '2026-01-01 10:00:00'),
        ('RACE-Y', 'Survives', '2026-01-02 10:00:00')
    """)
    conn.commit()
    conn.close()

    real_list_all = WishlistRepository.list_all
    call_count = {"n": 0}

    def _wrapped_list_all(self):
        call_count["n"] += 1
        if call_count["n"] == 2:
            # 模擬使用者在對帳送出與清單渲染之間手動刪除 RACE-X
            WishlistRepository().remove("RACE-X")
        return real_list_all(self)

    monkeypatch.setattr(
        "core.database.WishlistRepository.list_all",
        _wrapped_list_all,
    )

    resp = client.get("/api/wishlist")
    assert resp.status_code == 200
    numbers = [item["number"] for item in resp.json()]
    assert "RACE-X" not in numbers
    assert "RACE-Y" in numbers


def test_add_wishlist_already_owned_blocks_write(client, tmp_db):
    """TASK-141a-T3 DoD 1: 片庫已有（大小寫不同）→ 拒絕寫入、帶完整 local_status、書籤表無新增列。"""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO videos (path, number, title) VALUES (?, ?, ?)",
        ("/lib/abc-123.mp4", "abc-123", "Already Owned"),
    )
    conn.commit()
    conn.close()

    before_count = client.get("/api/wishlist/count").json()["count"]

    from core.database import VideoRepository
    from core.scraper import normalize_number

    normalized = normalize_number("ABC-123")
    expected_videos = VideoRepository().get_by_numbers([normalized]).get(normalized) or []

    resp = client.post("/api/wishlist", json={
        "number": "ABC-123",
        "title": "Should Not Be Added",
        "cover": "http://example.com/c.jpg",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["already_owned"] is True
    assert data["local_status"]["exists"] is True
    assert data["local_status"]["count"] == len(expected_videos)
    assert data["local_status"]["paths"] == [v.path for v in expected_videos]

    after_count = client.get("/api/wishlist/count").json()["count"]
    assert after_count == before_count

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT COUNT(*) FROM wishlist WHERE UPPER(number) = UPPER(?)",
        ("ABC-123",),
    ).fetchone()
    conn.close()
    assert row[0] == 0
