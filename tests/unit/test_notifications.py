"""
tests/unit/test_notifications.py — 通知 buffer 純函式邏輯測試（53b）

全 mock，不啟動 FastAPI。依 CLAUDE.md 測試分層：純邏輯 → unit/。
"""
import sqlite3
import pytest


@pytest.fixture(autouse=True)
def reset_buffer(monkeypatch, tmp_path):
    """每個 test 前後清空 buffer 與佇列，確保 DB 隔離，防止狀態污染。"""
    import web.routers.notifications as notif_mod
    from core.database.connection import init_db

    test_db = tmp_path / "unit_test.db"
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


def test_emit_notification_dedup_same_title_and_message():
    """DoD-3 (M1): 同 title_key 且同 message 在**還沒被看過**之前不重複寫入。

    去重只作用在 ``task_type="auto_organize"``（見下面那支反向鎖）。
    """
    from web.routers.notifications import emit_notification, _notifications, _read_ids
    emit_notification("info", "notif.auto_organize_summary", message="v1.0.0",
                      task_type="auto_organize")
    assert len(_notifications) == 1
    first_id = _notifications[0]["id"]
    first_time = _notifications[0]["timestamp"]

    # 連發相同 title_key 且相同 message（都還沒讀過）→ 合併，時間戳不動
    emit_notification("info", "notif.auto_organize_summary", message="v1.0.0",
                      task_type="auto_organize")
    assert len(_notifications) == 1
    assert _notifications[0]["id"] == first_id
    assert _notifications[0]["timestamp"] == first_time
    assert first_id not in _read_ids

    # 同 title_key 但不同 message → 應新增第二筆
    emit_notification("info", "notif.auto_organize_summary", message="v1.0.1",
                      task_type="auto_organize")
    assert len(_notifications) == 2
    assert _notifications[0]["message"] == "v1.0.1"


def test_dedup_does_not_touch_other_features():
    """去重不得跨出定時整理的邊界。

    使用者流程：從來沒開過定時整理的人按「產生影片列表」→ 側欄出「掃描開始」→
    沒點開通知抽屜就再按一次 → 修正前第二則被吃掉，使用者以為掃描沒跑。
    main 上完全沒有去重，這條規則是本 branch 加的，不該外溢到別的功能。
    """
    from web.routers.notifications import emit_notification, _notifications

    emit_notification("info", "notif.scanner_started", message="", task_type="scanner")
    emit_notification("info", "notif.scanner_started", message="", task_type="scanner")
    assert len(_notifications) == 2, "掃描類通知被定時整理的去重規則吃掉"

    # task_type 沒帶的呼叫點（更新提醒等）同樣不受影響
    emit_notification("info", "notif.update_available", message="v1.0.0")
    emit_notification("info", "notif.update_available", message="v1.0.0")
    assert len(_notifications) == 4


def test_start_notification_persistence_is_fail_soft(tmp_path, monkeypatch):
    """讀不到通知歷史時不得拋——App 啟動不能被側欄的歷史通知拖垮。

    lifespan 裡的鄰居（`backfill_readonly_nfo_mtime`、`source_reachability`）都是
    try/except 包起來的，而「側欄的歷史通知」比那兩者都不重要。載不回來就不啟動
    writer（讀不到的庫多半也寫不進去），以純記憶體模式運作。
    """
    import web.routers.notifications as notif_mod

    notif_mod.stop_notification_persistence()

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("core.database.connection.get_db_path", _boom)

    notif_mod.start_notification_persistence()  # 不得拋
    assert notif_mod._writer_thread is None, "載不回來時不該啟動 writer thread"

    # 純記憶體模式下 emit 照常可用
    notif_mod.emit_notification("info", "notif.fail_soft_probe", message="still works")
    assert any(
        n["title_key"] == "notif.fail_soft_probe" for n in notif_mod._notifications
    )


def test_emit_notification_stays_memory_only_and_never_blocks(monkeypatch):
    """DoD-2: emit_notification 必須維持「純記憶體」——這條路徑上一次 DB 連線都不准發生。

    契約三件事，缺一不可：
    1. **零 DB 連線**：整個呼叫期間 `sqlite3.connect` 的呼叫次數必須是 0。
    2. **不卡**：呼叫耗時 < 0.1 秒。
    3. **真的做了事**：那筆通知確實進了記憶體那一份。

    ⚠️ **為什麼第 1 條是計數而不是「patch 成會拋、然後斷言沒拋」**（T8 review，grok 實測）：
    `emit_notification()` 本身根本不碰 DB（寫入在背景 thread），所以把 `sqlite3.connect`
    patch 成拋例外時，**那個 patch 在受測路徑上是死碼**——實測呼叫次數 0 ⇒
    「沒有拋出來」是恆真的，什麼都沒證明。更糟的是它會誤導：把同步 `insert_notification`
    搬回這條路徑的 mutation 之所以轉紅，是因為那個 patch **讓它拋了**，
    不是因為耗時斷言——沒有 patch 時同步寫入只花約 40ms，`< 0.1s` 抓不住它。
    而只要有人把同步寫入包進 `try/except` 吞掉，三條舊斷言就會**全綠**。

    改成計數之後，「裸的同步寫入」與「包 try/except 吞掉的同步寫入」**兩種都擋得住**，
    而且不依賴任何時間門檻。DB 真的鎖住時的存活由
    `test_writer_thread_survives_db_locked_exception`（背景 thread 那條）負責，不在這裡重複。
    """
    import time
    import uuid
    from web.routers.notifications import emit_notification, _notifications

    connect_calls = []
    real_connect = sqlite3.connect

    def _counting_connect(*args, **kwargs):
        connect_calls.append(args[0] if args else None)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("sqlite3.connect", _counting_connect)

    # 去重早退防呆（邊界條件②）：emit_notification() 對「同 title_key ＋ 同 message」
    # 會提早 return，不走 appendleft／put_nowait。用唯一值確保走完整條路徑，
    # 否則下面三條斷言都會在一個根本沒執行的路徑上假綠。
    unique_key = f"notif.test_unique_{uuid.uuid4()}"
    unique_msg = f"msg_{uuid.uuid4()}"

    t0 = time.perf_counter()
    emit_notification("info", unique_key, message=unique_msg)
    elapsed = time.perf_counter() - t0

    assert connect_calls == [], (
        f"emit_notification 在呼叫端開了 DB 連線：{connect_calls!r}。"
        "這條路徑必須維持純記憶體（appendleft ＋ put_nowait）——"
        "一旦有人把同步 DB 寫入搬回來，批次補完 SSE 那條熱路徑會被 DB 鎖卡住。"
    )
    assert elapsed < 0.1, f"emit_notification 呼叫耗時過長：{elapsed:.4f}s >= 0.1s"
    assert any(
        n["title_key"] == unique_key and n["message"] == unique_msg
        for n in _notifications
    ), "通知沒有真的進到記憶體那一份（前兩條斷言在空操作上也會綠）"


def test_read_notification_does_not_silence_the_next_occurrence():
    """pre-merge SA-pre-9 P2-2：使用者看過之後，同一件事再發生要重新出聲。

    使用者流程：開著定時整理 → 第一次失敗，側欄出現一則紅色「定時整理失敗」→
    使用者打開通知抽屜（`base.html` 的 toggleDrawer 會 POST /notifications/read
    把當下全部標讀）→ 之後每 12 小時又失敗一次，但去重只比對記憶體 deque
    ⇒ **側欄再也不出現任何東西、未讀角標也不亮**，使用者以為排程在跑，
    其實幾週來一部片都沒整理到。

    這支釘的就是「已讀之後不再被去重吃掉」。
    """
    from web.routers.notifications import emit_notification, _notifications, _read_ids

    emit_notification("error", "notif.auto_organize_failed", message="")
    assert len(_notifications) == 1
    first_id = _notifications[0]["id"]

    # 使用者打開抽屜 → 全部標讀
    _read_ids.add(first_id)

    # 12 小時後同一件事再發生
    emit_notification("error", "notif.auto_organize_failed", message="")

    assert len(_notifications) == 2, (
        "已讀之後同內容再發生必須新增一筆，否則背景失敗會永遠靜默"
    )
    newest = _notifications[0]
    assert newest["id"] != first_id
    assert newest["id"] not in _read_ids, "新那筆必須是未讀，未讀角標才會亮"


