"""
tests/integration/test_notifications_api.py — 通知中心 API 端點測試（53b）

用 FastAPI TestClient 打 GET / POST / DELETE。依 CLAUDE.md 測試分層：API 端點 → integration/。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_buffer(monkeypatch, tmp_path):
    import web.routers.notifications as notif_mod
    from core.database.connection import init_db

    test_db = tmp_path / "integ_test.db"
    init_db(test_db)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: test_db)

    with notif_mod._lock:
        notif_mod._notifications.clear()
        notif_mod._read_ids.clear()
    while not notif_mod._write_queue.empty():
        try:
            notif_mod._write_queue.get_nowait()
            notif_mod._write_queue.task_done()
        except Exception:
            break

    yield

    with notif_mod._lock:
        notif_mod._notifications.clear()
        notif_mod._read_ids.clear()
    notif_mod.stop_notification_persistence()
    while not notif_mod._write_queue.empty():
        try:
            notif_mod._write_queue.get_nowait()
            notif_mod._write_queue.task_done()
        except Exception:
            break


@pytest.fixture
def client():
    from web.app import app
    return TestClient(app)


def test_get_with_items(client):
    """emit 2 筆後 GET 回最新在前 + 全部未讀。"""
    from web.routers.notifications import emit_notification
    emit_notification("info", "notif.scanner_started")
    emit_notification("warn", "notif.scanner_done_with_errors")
    body = client.get("/api/notifications").json()
    assert len(body["items"]) == 2
    assert body["items"][0]["title_key"] == "notif.scanner_done_with_errors"
    assert body["unread_count"] == 2
    assert body["highest_unread_level"] == "warn"


def test_notification_persists_across_restart(client, tmp_path, monkeypatch):
    """DoD-1 (M3): 發通知落 DB，模擬重啟後 GET /api/notifications 仍看得到它，且已讀狀態不變。"""
    from core.database.connection import init_db
    import web.routers.notifications as notif_mod
    from web.routers.notifications import emit_notification, start_notification_persistence, _write_queue

    test_db = tmp_path / "persist_test.db"
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: test_db)
    init_db(test_db)

    # 啟動持久化
    start_notification_persistence()

    emit_notification("info", "notif.persist_key", message="persisted message")
    _write_queue.join()

    # 模擬 process 重啟：清空記憶體緩衝
    # 先**真的**停掉舊 writer（哨兵 ＋ join），不要只把指標設成 None：
    # 那會留下一條仍活著、仍在消費同一個 module-level 佇列、而且綁著**舊 db_path**
    # 的孤兒 thread，把接下來該寫進新庫的通知寫到舊庫去。
    notif_mod.stop_notification_persistence()
    with notif_mod._lock:
        notif_mod._notifications.clear()
        notif_mod._read_ids.clear()

    # 重啟開機：呼叫 start_notification_persistence()
    start_notification_persistence()

    body = client.get("/api/notifications").json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title_key"] == "notif.persist_key"
    assert body["items"][0]["message"] == "persisted message"
    assert body["items"][0]["is_read"] is False
    assert body["unread_count"] == 1


def test_notification_clear_persists_across_restart(client, tmp_path, monkeypatch):
    """DoD-6 (M6): DELETE /api/notifications 清空後重啟，抽屜仍為空，不得從 DB 復活。"""
    from core.database.connection import init_db
    import web.routers.notifications as notif_mod
    from web.routers.notifications import emit_notification, start_notification_persistence, _write_queue

    test_db = tmp_path / "clear_persist_test.db"
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: test_db)
    init_db(test_db)

    start_notification_persistence()

    emit_notification("info", "notif.to_be_cleared")
    _write_queue.join()

    # 清空
    res = client.delete("/api/notifications")
    assert res.json()["ok"] is True
    _write_queue.join()

    # 模擬 process 重啟
    # 先**真的**停掉舊 writer（哨兵 ＋ join），不要只把指標設成 None：
    # 那會留下一條仍活著、仍在消費同一個 module-level 佇列、而且綁著**舊 db_path**
    # 的孤兒 thread，把接下來該寫進新庫的通知寫到舊庫去。
    notif_mod.stop_notification_persistence()
    with notif_mod._lock:
        notif_mod._notifications.clear()
        notif_mod._read_ids.clear()

    start_notification_persistence()

    body = client.get("/api/notifications").json()
    assert body["items"] == []
    assert body["unread_count"] == 0


