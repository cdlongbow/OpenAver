"""
TASK-130a-T2: windows/health_probe.py 探活重試迴圈故障注入測試

驗證：
1. ConnectionResetError 不穿出 wait_for_server，持續重試直到逾時回傳 PROBE_TIMEOUT。
2. http.client.BadStatusLine 等 http.client.HTTPException 不穿出，持續重試直到逾時回傳 PROBE_TIMEOUT。
3. http.client.RemoteDisconnected 不穿出（注意其 MRO 橫跨 OSError 與 HTTPException 兩邊，見該函式 docstring）。
4. 前 3 次連線失敗、第 4 次成功（HTTP 200）時，wait_for_server 回傳 PROBE_OK 且確實重試 4 次。
5. 連續失敗直到逾時後正常回傳 PROBE_TIMEOUT，不拋出例外。

（TASK-130a-T3 起回傳值由 bool 換成三態字串常數；本檔的呼叫點與斷言一併更新。）
"""
import http.client
import threading
import urllib.request

import pytest

from windows.health_probe import PROBE_OK, PROBE_TIMEOUT, wait_for_server


@pytest.fixture
def alive_thread():
    """一個活著的 daemon thread（wait_for_server 只會對它呼叫 is_alive()）。

    TASK-130a-T3 起 `wait_for_server` 的 `server_thread` 是必填參數且**沒有預設值**
    （刻意的：給 None 預設值等於開一條永遠回不了 PROBE_THREAD_DIED 的路徑）。
    這裡用真 thread 而不是 stub，是因為「忘了 start() 的 thread 也回報 is_alive() == False」
    正是這支 API 最容易寫出假 PROBE_THREAD_DIED 的地方——用真的才測得到那個陷阱。
    """
    stop = threading.Event()

    def _spin():
        stop.wait(60)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    assert t.is_alive()
    yield t
    stop.set()
    t.join(timeout=5)


class _StubResponse:
    """模擬 opener.open() 回傳的 context manager 回應物件"""

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_connection_reset_is_retried_not_raised(alive_thread, monkeypatch):
    """AC-T2-1: ConnectionResetError 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 PROBE_TIMEOUT"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise ConnectionResetError("Connection reset by peer")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, alive_thread, timeout=0.5)
    assert result == PROBE_TIMEOUT
    assert call_count >= 2


def test_bad_status_line_is_retried_not_raised(alive_thread, monkeypatch):
    """AC-T2-2: http.client.BadStatusLine 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 PROBE_TIMEOUT。

    這支是鎖住 tuple 裡 `http.client.HTTPException` 那一項的唯一見證：BadStatusLine 只繼承
    HTTPException，不是 OSError 子類（對照 test_remote_disconnected 的 docstring）。
    """
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise http.client.BadStatusLine("???")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, alive_thread, timeout=0.5)
    assert result == PROBE_TIMEOUT
    assert call_count >= 2


def test_remote_disconnected_is_retried_not_raised(alive_thread, monkeypatch):
    """RemoteDisconnected 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 PROBE_TIMEOUT。

    ⚠️ 這支**不能**用來證明 tuple 裡的 `http.client.HTTPException` 是必要的：
    `RemoteDisconnected` 同時繼承 `ConnectionResetError`（→ `OSError`）與 `BadStatusLine`
    （→ `HTTPException`），光靠 `OSError` 那一項就接得到。
    真正鎖住 `HTTPException` 那一項的是 `test_bad_status_line_is_retried_not_raised`
    （`BadStatusLine` 只繼承 `HTTPException`，不是 `OSError`）——mutation 點也是打在那支。
    本支的價值是覆蓋真實世界最常見的那個類別，不是證明 tuple 的哪一項。
    """
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise http.client.RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, alive_thread, timeout=0.5)
    assert result == PROBE_TIMEOUT
    assert call_count >= 2


def test_retries_then_succeeds(alive_thread, monkeypatch):
    """AC-T2-4 / DoD 4: 前 3 次連線失敗、第 4 次回傳 200 時，回傳 PROBE_OK 且確實重試 4 次"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionResetError("Connection reset by peer")
            return _StubResponse(status=200)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, alive_thread, timeout=2.0)
    assert result == PROBE_OK
    assert call_count == 4


def test_timeout_returns_probe_timeout_not_raises(alive_thread, monkeypatch):
    """AC-T2-3: 連線持續拋出 OSError 時，wait_for_server 於逾時後回傳 PROBE_TIMEOUT 而非拋出例外"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise OSError("Network unreachable")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, alive_thread, timeout=0.5)
    assert result == PROBE_TIMEOUT
    assert call_count >= 2
