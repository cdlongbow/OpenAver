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
import inspect
import logging
import pathlib
import sys
import threading
import time
import types
import urllib.request
from pathlib import Path

import pytest

import windows.health_probe as health_probe
from windows.health_probe import run_server, wait_for_server

LOGGER_NAME = "OpenAver.windows.health_probe"


def _const(name: str) -> str:
    """Fetch a probe constant; AttributeError here means the T3 API is still missing."""
    return getattr(health_probe, name)


class _StubResponse:
    """模擬 opener.open() 回傳的 context manager 回應物件"""

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


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


def _ok_opener(monkeypatch):
    class StubOpener:
        def open(self, url, timeout=1):
            return _StubResponse(status=200)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())


# ----- D1: signature + return literals -----

def test_signature_server_thread_required_three_state_returns(alive_thread, monkeypatch):
    """D1: server_thread 無預設值；回傳值恰為三態常數之一。"""
    sig = inspect.signature(wait_for_server)
    params = list(sig.parameters.values())
    assert params[0].name == "port"
    assert params[1].name == "server_thread"
    assert params[1].default is inspect.Parameter.empty, (
        "server_thread 必須是必填位置參數，不可有預設值"
    )

    _ok_opener(monkeypatch)
    assert wait_for_server(49152, alive_thread, timeout=2.0) == _const("PROBE_OK")

    _failing_opener(monkeypatch)
    assert wait_for_server(49152, alive_thread, timeout=0.4) == _const("PROBE_TIMEOUT")

    _failing_opener(monkeypatch)
    assert wait_for_server(49152, _dead_thread(), timeout=5.0) == _const("PROBE_THREAD_DIED")


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

def test_alive_thread_probe_timeout(alive_thread, monkeypatch):
    """D3 / AC-T3-3: 活著的 thread ＋ 探活永遠失敗 → PROBE_TIMEOUT。"""
    _failing_opener(monkeypatch)
    result = wait_for_server(49152, alive_thread, timeout=0.5)
    assert result == _const("PROBE_TIMEOUT")


# ----- D4 + flag: alive × 200 -----

def test_alive_thread_probe_ok(alive_thread, monkeypatch):
    """D4 / AC-T3-3: 探活拿到 200 → PROBE_OK。"""
    _ok_opener(monkeypatch)
    result = wait_for_server(49152, alive_thread, timeout=2.0)
    assert result == _const("PROBE_OK")


# ----- flag: dead × already timed out（檢查順序：thread 優先） -----

def test_dead_and_timed_out_returns_thread_died(monkeypatch):
    """死掉 × 已逾時：先檢查 thread 存活 → 回 PROBE_THREAD_DIED（非 timeout）。"""
    _failing_opener(monkeypatch)
    dead = _dead_thread()
    # timeout=0 → 時間條件已到期；若先查逾時會回 PROBE_TIMEOUT
    result = wait_for_server(49152, dead, timeout=0)
    assert result == _const("PROBE_THREAD_DIED")


# ----- D5: run_server exception boundary -----

def test_run_server_logs_unexpected_exception(monkeypatch, caplog):
    """D5 / AC-T3-1: run_server 未預期例外 → logger.exception 留痕且不往外拋。"""
    web_mod = types.ModuleType("web")
    web_app_mod = types.ModuleType("web.app")
    web_app_mod.app = object()
    monkeypatch.setitem(sys.modules, "web", web_mod)
    monkeypatch.setitem(sys.modules, "web.app", web_app_mod)

    class BoomServer:
        def __init__(self, config):
            pass

        def run(self):
            raise RuntimeError("simulated server crash")

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            pass

    uvicorn_mod = types.ModuleType("uvicorn")
    uvicorn_mod.Config = FakeConfig
    uvicorn_mod.Server = BoomServer
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_mod)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        run_server(49152, debug_mode=False)  # must not raise

    matching = [
        r for r in caplog.records
        if r.name == LOGGER_NAME and r.exc_info is not None
    ]
    assert matching, (
        f"expected logger.exception record on {LOGGER_NAME}, got: {caplog.text!r}"
    )
    assert "simulated server crash" in caplog.text


# ----- D6: once-only logging -----

def test_timeout_logs_last_swallowed_exception(alive_thread, monkeypatch, caplog):
    """D6 / AC-T3-4 / CD-130a-8: 逾時路徑留痕恰好一次，含最後例外型別與訊息。"""
    def exc_factory():
        return PermissionError("firewall blocked probe")

    _failing_opener(monkeypatch, exc_factory=exc_factory)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = wait_for_server(49152, alive_thread, timeout=0.5)

    assert result == _const("PROBE_TIMEOUT")
    warnings = [
        r for r in caplog.records
        if r.name == LOGGER_NAME and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, (
        f"逾時留痕必須恰好 1 筆，實際 {len(warnings)}：{[r.getMessage() for r in warnings]}"
    )
    msg = warnings[0].getMessage()
    assert "PermissionError" in msg
    assert "firewall blocked probe" in msg


def test_thread_death_logs_once(monkeypatch, caplog):
    """D6: thread 死亡路徑留痕恰好一次（不是每輪）。"""
    call_count = 0

    class StubOpener:
        def open(self, url, timeout=1):
            nonlocal call_count
            call_count += 1
            raise OSError("still failing")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: StubOpener())

    # Thread that dies after a couple of probe attempts so last_exc is set
    stop = threading.Event()

    def _short_life():
        time.sleep(0.35)
        # fall off end → thread dies

    t = threading.Thread(target=_short_life, daemon=True)
    t.start()

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = wait_for_server(49152, t, timeout=5.0)

    assert result == _const("PROBE_THREAD_DIED")
    warnings = [
        r for r in caplog.records
        if r.name == LOGGER_NAME and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, (
        f"thread 死亡留痕必須恰好 1 筆，實際 {len(warnings)}：{[r.getMessage() for r in warnings]}"
    )
    stop.set()


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


def test_timeout_message_contains_actual_port():
    """DoD D1 / AC-T4-1: 逾時文案含實際傳入的 port（非寫死 8000）。"""
    port = 49152
    msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, port)
    assert str(port) in msg
    assert "8000" not in msg

    other_port = 55555
    other_msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, other_port)
    assert str(other_port) in other_msg
    assert "8000" not in other_msg


def test_debug_log_path_is_real_on_this_platform():
    """DoD D3 / AC-T4-3: 兩句話都含當前平台上合法的 debug.log 絕對路徑（非 %USERPROFILE%）。"""
    expected_path = str(Path.home() / "OpenAver" / "logs" / "debug.log")
    home_prefix = str(Path.home())

    timeout_msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, 49152)
    died_msg = health_probe.format_startup_message(health_probe.PROBE_THREAD_DIED, 49152)

    assert expected_path in timeout_msg
    assert expected_path in died_msg
    assert home_prefix in timeout_msg
    assert home_prefix in died_msg
    assert "%USERPROFILE%" not in timeout_msg
    assert "%USERPROFILE%" not in died_msg


def test_timeout_message_contains_startup_timeout_constant(monkeypatch):
    """DoD D2: 逾時文案含逾時秒數，且取自 STARTUP_TIMEOUT 常數。"""
    msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, 49152)
    assert str(health_probe.STARTUP_TIMEOUT) in msg

    monkeypatch.setattr(health_probe, "STARTUP_TIMEOUT", 45)
    custom_msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, 49152)
    assert "45" in custom_msg


def test_thread_death_message_does_not_mention_timeout_or_port():
    """DoD D4 / AC-T4-2: thread 死亡文案不含「逾時」、不含 port 號、且與逾時文案不相等。"""
    port = 49152
    died_msg = health_probe.format_startup_message(health_probe.PROBE_THREAD_DIED, port)
    timeout_msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, port)

    assert died_msg != timeout_msg
    assert "逾時" not in died_msg
    assert str(port) not in died_msg


def test_debug_log_hint_fallback_on_runtime_error(monkeypatch):
    """DoD D6: Path.home() 拋 RuntimeError 時不崩潰，仍回傳安全 fallback 文案。"""
    def _boom():
        raise RuntimeError("simulated HOME unset")

    monkeypatch.setattr(Path, "home", _boom)

    timeout_msg = health_probe.format_startup_message(health_probe.PROBE_TIMEOUT, 49152)
    died_msg = health_probe.format_startup_message(health_probe.PROBE_THREAD_DIED, 49152)

    assert timeout_msg != ""
    assert died_msg != ""
    assert "49152" in timeout_msg
    assert "逾時" not in died_msg
    assert "logs" in timeout_msg
    assert "logs" in died_msg



def test_debug_log_hint_matches_core_logger_default():
    """跨檔守衛：_debug_log_hint() 與 core/logger.py 的預設 log 路徑必須是同一個地方。

    這兩處是分開寫死的（health_probe 刻意不 import core.logger 的私有 _log_dir，
    理由見該函式 docstring），所以需要一支測試把它們綁在一起。

    使用者流程：有人改了 core/logger.py 的預設 log 目錄 → 啟動失敗訊息還指著舊路徑
    → 使用者照著訊息去開那個檔，檔案不在那裡 → 又是一次「叫我去看的東西不存在」，
    而這正是 TASK-130a-T4 存在的理由。

    兩位 reviewer（sonnet / grok-4.5）在 T4 review 各自獨立指出：原本的做法只有一行註解，
    drift 掉不會有任何東西轉紅。
    """
    logger_src = (pathlib.Path(__file__).parents[2] / "core" / "logger.py").read_text(encoding="utf-8")

    assert 'Path.home() / "OpenAver" / "logs"' in logger_src, (
        "core/logger.py 的預設 log 目錄變了，但 windows/health_probe.py::_debug_log_hint() "
        "還在組舊路徑 —— 啟動失敗訊息會指向一個不存在的檔案。兩處要一起改。"
    )
    assert 'log_dir / "debug.log"' in logger_src, (
        "core/logger.py 的 log 檔名變了，但 windows/health_probe.py::_debug_log_hint() "
        "還在指 debug.log —— 兩處要一起改。"
    )

    # 反向：health_probe 這邊組出來的東西，結尾必須真的是 .../OpenAver/logs/debug.log
    hint = health_probe._debug_log_hint()
    expected_tail = str(pathlib.Path("OpenAver") / "logs" / "debug.log")
    assert hint.endswith(expected_tail), (
        f"_debug_log_hint() 回傳 {hint!r}，結尾不是 {expected_tail!r}"
    )
