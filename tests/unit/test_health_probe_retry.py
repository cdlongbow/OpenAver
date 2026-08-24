"""
TASK-130a-T2: windows/health_probe.py 探活重試迴圈故障注入測試

驗證：
1. ConnectionResetError 不穿出 wait_for_server，持續重試直到逾時回傳 False。
2. http.client.BadStatusLine 等 http.client.HTTPException 不穿出，持續重試直到逾時回傳 False。
3. http.client.RemoteDisconnected 不穿出（注意其 MRO 橫跨 OSError 與 HTTPException 兩邊，見該函式 docstring）。
4. 前 3 次連線失敗、第 4 次成功（HTTP 200）時，wait_for_server 回傳 True 且確實重試 4 次。
5. 連續失敗直到逾時後正常回傳 False，不拋出例外。
"""
import http.client
import urllib.request

from windows.health_probe import wait_for_server


class _StubResponse:
    """模擬 opener.open() 回傳的 context manager 回應物件"""

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_connection_reset_is_retried_not_raised(monkeypatch):
    """AC-T2-1: ConnectionResetError 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 False"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise ConnectionResetError("Connection reset by peer")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, timeout=0.5)
    assert result is False
    assert call_count >= 2


def test_bad_status_line_is_retried_not_raised(monkeypatch):
    """AC-T2-2: http.client.BadStatusLine 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 False"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise http.client.BadStatusLine("???")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, timeout=0.5)
    assert result is False
    assert call_count >= 2


def test_remote_disconnected_is_retried_not_raised(monkeypatch):
    """RemoteDisconnected 被重試迴圈捕獲，不穿出 wait_for_server，逾時回傳 False。

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

    result = wait_for_server(49152, timeout=0.5)
    assert result is False
    assert call_count >= 2


def test_retries_then_succeeds(monkeypatch):
    """AC-T2-4 / DoD 4: 前 3 次連線失敗、第 4 次回傳 200 時，回傳 True 且確實重試 4 次"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionResetError("Connection reset by peer")
            return _StubResponse(status=200)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, timeout=2.0)
    assert result is True
    assert call_count == 4


def test_timeout_returns_false_not_raises(monkeypatch):
    """AC-T2-3: 連線持續拋出 OSError 時，wait_for_server 於逾時後回傳 False 而非拋出例外"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise OSError("Network unreachable")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    result = wait_for_server(49152, timeout=0.5)
    assert result is False
    assert call_count >= 2
