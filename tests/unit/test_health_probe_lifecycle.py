"""
TASK-130a-T3: windows/health_probe.py 伺服器 thread 生命週期與三態探活

驗證：
1. wait_for_server 簽章：server_thread 必填、回傳 PROBE_OK / PROBE_TIMEOUT / PROBE_THREAD_DIED。
2. thread 立刻死亡 → 提前中止（elapsed < 2s）回 PROBE_THREAD_DIED。
3. 活著的 thread ＋ 探活永遠失敗 → PROBE_TIMEOUT。
4. 探活拿到 200 → PROBE_OK。
5. run_server 未預期例外 → logger.exception 留痕且不往外拋。
6. 逾時／thread 死亡路徑各留痕恰好一次（含最後一次被吞例外）。
7. format_startup_message 兩句不同、含 port、不含代理字樣；PROBE_OK → ""；值域外 → 逾時文案。
8. 四種 flag 組合：活著×逾時／死掉×未逾時／死掉×已逾時／活著×200。
"""
import threading
import time
import urllib.request

import pytest

import windows.health_probe as health_probe
from windows.health_probe import wait_for_server


def _const(name: str) -> str:
    """Fetch a probe constant; AttributeError here means the T3 API is still missing."""
    return getattr(health_probe, name)


@pytest.fixture
def alive_thread():
    """daemon thread that stays alive until the fixture tears down."""
    stop = threading.Event()

    def _spin():
        stop.wait(60)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    assert t.is_alive()
    yield t
    stop.set()
    t.join(timeout=2)


def _dead_thread():
    """起一個立刻結束的 thread 並 join，讓 is_alive() 穩定為 False。

    ⚠️ 這裡故意**不**讓 target 拋例外。拋例外一樣會讓 thread 死掉，但會觸發
    `PytestUnhandledThreadExceptionWarning`，在整套 7000+ 測試的輸出裡變成看不出來源的雜訊
    ——而本測試要驗的是「thread 死了」，不是「thread 怎麼死的」。
    真實世界那條「因為未預期例外而死」的路徑由 `test_run_server_logs_unexpected_exception`
    覆蓋（`run_server` 自己的 try/except 會接住並留痕，所以那支不會噴 warning）。

    必須 `start()` 過：**沒 start() 的 thread 也回報 `is_alive() == False`**，
    用它會拿到一個假的 PROBE_THREAD_DIED，測試看起來綠但什麼都沒證明。
    """

    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()
    return t


def _failing_opener(monkeypatch, exc_factory=None):
    """Monkeypatch build_opener so every open() raises."""
    if exc_factory is None:
        def exc_factory():
            return OSError("Network unreachable")

    class StubOpener:
        def open(self, url, timeout=1):
            raise exc_factory()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())


# ----- D1: signature + return literals -----


# ----- D2 + flag: dead × not timed out -----

def test_thread_death_aborts_probe_early(monkeypatch):
    """D2 / AC-T3-2: 立刻死亡的 thread → PROBE_THREAD_DIED 且 elapsed < 2s。"""
    _failing_opener(monkeypatch)
    dead = _dead_thread()

    t0 = time.monotonic()
    result = wait_for_server(49152, dead, timeout=30)
    elapsed = time.monotonic() - t0

    assert result == _const("PROBE_THREAD_DIED")
    assert elapsed < 2.0, f"thread 死亡應遠早於 30s 中止，實際 elapsed={elapsed:.2f}s"


# ----- D3 + flag: alive × timeout -----


# ----- D4 + flag: alive × 200 -----


# ----- flag: dead × already timed out（檢查順序：thread 優先） -----


# ----- D5: run_server exception boundary -----


# ----- D6: once-only logging -----


# ----- D7: format_startup_message -----

def test_format_startup_message_variants():
    """D7 / AC-T3-5: 兩句不同、含 port、不含代理；OK→''；值域外→逾時文案。"""
    port = 49199
    fmt = health_probe.format_startup_message
    timeout_msg = fmt(_const("PROBE_TIMEOUT"), port)
    died_msg = fmt(_const("PROBE_THREAD_DIED"), port)
    ok_msg = fmt(_const("PROBE_OK"), port)
    unknown_msg = fmt("not-a-real-result", port)

    assert timeout_msg != died_msg
    assert str(port) in timeout_msg
    assert "debug.log" in timeout_msg
    assert "debug.log" in died_msg
    assert ok_msg == ""
    assert unknown_msg == timeout_msg

    proxy_needles = ("代理", "proxy", "Proxy", "PROXY", "HTTP_PROXY", "http_proxy")
    for needle in proxy_needles:
        assert needle not in timeout_msg, f"timeout 文案含代理字樣 {needle!r}"
        assert needle not in died_msg, f"thread_died 文案含代理字樣 {needle!r}"

    # 不得含原始例外內容
    assert "PermissionError" not in timeout_msg
    assert "PermissionError" not in died_msg
    assert "Traceback" not in timeout_msg
    assert "Traceback" not in died_msg
    assert "Error:" not in timeout_msg
    assert "Error:" not in died_msg


# [lint-guard: pytest-justified] 跨檔 runtime 契約：core/logger.py 的預設路徑
# 必須與 windows/health_probe.py::_debug_log_hint() 的實際輸出是同一個地方。
# 只把前兩條「logger 源碼含某字面」搬去 lint 會拆斷這個關係——那樣 lint pattern、
# 測試的 expected_tail、兩支產品碼會變成四份各自為政的字面，改一半而兩邊都綠。
