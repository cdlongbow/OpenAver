"""168e-T13：windows/cf_boot.py（CfShellController）——連線頁「重試」的殼端補建／重讀。

時序只驗不變式＋oracle：等待走可注入點（``cf_boot._wait_for`` 的 wake／``_monotonic``），逾時一律
``pytest.fail``（BE-TEST-45）；背景緒測試在 finally 放行並 join。假 webview.create_window／假 transport，
不碰真視窗、真網路。
"""
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from core import client_settings
from core.proxy_policy import ProxySettings

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = REPO_ROOT / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

from windows import cf_boot, cf_shell, cf_windows  # noqa: E402
from windows.cf_windows import CfWindowSet  # noqa: E402

SERVER = "http://192.168.1.180:8000"
TOKEN = "TKN-SENTINEL-T13"
LOCAL = "http://localhost:8000"
OK_NULL = {"ok": True, "job": None}


# ---------------------------------------------------------------------------
# 假件
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeWake:
    """取代 agent.status_changed：``wait(timeout)`` 走注入時鐘；script 是 [(delay, action)]，
    第一項 delay <= timeout 就在那個時間點執行 action 並回 True，否則時鐘走滿 timeout 回 False。"""

    def __init__(self, clock, script=()):
        self.clock, self.script, self.waits = clock, list(script), []

    def set(self):
        pass

    def clear(self):
        pass

    def wait(self, timeout):
        self.waits.append(timeout)
        if len(self.waits) > 50:
            raise AssertionError("wait called too many times (BE-TEST-45)")
        if self.script and self.script[0][0] <= timeout:
            delay, action = self.script.pop(0)
            self.clock.t += delay
            action()
            return True
        self.clock.t += timeout
        return False


class FakeTransport:
    def __init__(self, sites=(), failed=()):
        self.sites, self.failed = list(sites), list(failed)
        self.listener = None

    def available_sites(self):
        return list(self.sites)

    def preparing_sites(self):
        return []

    def failed_sites(self):
        return list(self.failed)

    def set_change_listener(self, cb):
        self.listener = cb


class SyncExecutor:
    def submit(self, fn, *a, **k):
        fn(*a, **k)

    def shutdown(self, *a, **k):
        pass


class _Evt:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class CWin:
    """假 pywebview 視窗：closing／closed 事件、hide／destroy 記錄。"""

    def __init__(self, title, log):
        self.title, self._log = title, log
        self.events = types.SimpleNamespace(closing=_Evt(), closed=_Evt())
        self.hidden = False
        self.destroyed = 0
        self.uid = title

    def hide(self):
        self.hidden = True

    def destroy(self):
        self.destroyed += 1
        self._log.append(("destroy", self.title))

    def load_url(self, url):
        pass


class FakeLifecycle:
    def __init__(self):
        self.registered = []
        self.quitting = False

    def register_cf_windows(self, mapping):
        self.registered.append(dict(mapping))


class Env:
    pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    e = Env()
    e.clock = FakeClock()
    e.log = []
    e.created = []            # create_window 呼叫（標題）
    e.fetches = []
    e.fetch_ok = True
    e.fetch_reason = "unreachable"
    e.agents = []
    e.script = []             # 傳給下一個 agent 的 FakeWake script
    e.http_script = []        # 伺服器回應腳本（poll）
    e.polls = []
    e.transport_sites = ["fc-javten", "javlibrary"]
    e.use_real_build = True
    e.build_hold = None       # threading.Event：卡住 create_window（模擬 GUI Invoke）
    e.build_entered = threading.Event()
    e.threads = []

    def fetch(server_url, token, server_origin):
        e.fetches.append((server_url, token, server_origin))
        if e.fetch_ok:
            return True, None, ProxySettings(url="", scope="dmm"), False, False
        return False, e.fetch_reason, None, False, False

    def create_window(title, url, **kw):
        e.created.append(title)
        e.build_entered.set()
        if e.build_hold is not None and not e.build_hold.wait(10):
            pytest.fail("create_window hold never released (BE-TEST-45)")
        return CWin(title, e.log)

    monkeypatch.setattr(cf_windows, "fetch_client_cf", fetch)
    monkeypatch.setattr(cf_windows, "cf_shell_supported", lambda: True)
    monkeypatch.setattr(cf_windows.webview, "create_window", create_window)
    monkeypatch.setattr(cf_boot, "_monotonic", e.clock)

    def handler(request):
        e.polls.append(request)
        if len(e.polls) > 40:
            raise AssertionError("handler called too many times")
        item = e.http_script.pop(0) if e.http_script else OK_NULL
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json=item) if isinstance(item, dict) else item

    real_agent = cf_shell.CfShellAgent

    class TestAgent(real_agent):
        def __init__(self, *a, **kw):
            super().__init__(*a, http_transport=httpx.MockTransport(handler), executor=SyncExecutor(), **kw)
            self.status_changed = FakeWake(e.clock, e.script)
            self.started = 0
            e.agents.append(self)

        def start(self):                      # 不開執行緒
            self.started += 1

    monkeypatch.setattr(cf_shell, "CfShellAgent", TestAgent)
    monkeypatch.setattr(cf_shell, "_sleep", lambda s: None)
    return e


def make_controller(env, kind="client", logger=None):
    return cf_boot.CfShellController(logger or MagicMock(), kind, LOCAL)


def write_client(url=SERVER, token=TOKEN):
    client_settings.save_client_settings({"version": 1, "server": {"url": url, "token": token}})


def bind(ctl, lifecycle=None, quitting=None):
    quitting = quitting if quitting is not None else {"v": False}
    ctl.bind(lifecycle, lambda: lifecycle.quitting if lifecycle is not None else quitting["v"])
    return quitting


def run_thread(env, fn, box):
    def target():
        box.append(fn())

    t = threading.Thread(target=target, daemon=True)
    env.threads.append(t)
    t.start()
    return t


def join_all(env):
    for t in env.threads:
        t.join(5)
    alive = [t for t in env.threads if t.is_alive()]
    if alive:
        pytest.fail(f"thread leaked: {alive} (BE-TEST-45)")


# ---------------------------------------------------------------------------
# I-1 set-once
# ---------------------------------------------------------------------------
def test_retry_fetch_failure_builds_no_windows_even_after_three_retries(env):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    for _ in range(3):
        reply = ctl.retry()
        assert reply["ok"] is True and reply["cf"]["reason"] == "unreachable"
    assert env.created == []
    assert len(env.fetches) == 4                      # 啟動一次＋每按一次重試一次，沒有任何自動補試


def test_retry_builds_at_most_one_window_set(env):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    env.fetch_ok = True
    for _ in range(3):
        assert ctl.retry()["ok"] is True
    assert len(env.created) == 2                      # 恰好一組（JavLibrary＋FC2-javten）
    assert len(env.agents) == 1


def test_concurrent_retries_build_exactly_one_set(env):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    env.fetch_ok = True
    env.build_hold = threading.Event()
    boxes = [[], []]
    t1 = run_thread(env, ctl.retry, boxes[0])
    try:
        assert env.build_entered.wait(5), "first retry never reached create_window"
        t2 = run_thread(env, ctl.retry, boxes[1])
        t2.join(5)
        assert not t2.is_alive()
    finally:
        env.build_hold.set()
        join_all(env)
    replies = [boxes[0][0], boxes[1][0]]
    assert sorted(r["ok"] for r in replies) == [False, True]
    assert len(env.created) == 2


def test_retry_after_build_attempt_with_zero_windows_never_rebuilds(env, monkeypatch):
    """Q6：build 嘗試過即 set-once（兩窗皆建失敗也不再 build，避免代理套用器多包一層）。"""
    write_client()
    builds = []
    monkeypatch.setattr(cf_windows, "build_cf_windows",
                        lambda logger, settings, local_direct=False: builds.append(1) or CfWindowSet())
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    ctl.retry()
    ctl.retry()
    assert builds == [1]


# ---------------------------------------------------------------------------
# I-2 補建後狀態（等待走注入點）
# ---------------------------------------------------------------------------
def _never_built_controller(env, transport):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    env.fetch_ok = True

    def fake_build(logger, settings, local_direct=False):
        return CfWindowSet(transport=transport, jl_win=CWin("jl", env.log), javten_win=CWin("jt", env.log))

    return ctl, fake_build


def test_retry_waits_until_ready_within_settle_window(env, monkeypatch):
    transport = FakeTransport(sites=())
    ctl, fake_build = _never_built_controller(env, transport)
    monkeypatch.setattr(cf_windows, "build_cf_windows", fake_build)

    def window_confirms_and_server_accepts():
        transport.sites = ["fc-javten", "javlibrary"]
        env.agents[0]._sync_once()

    env.script.append((1.0, window_confirms_and_server_accepts))
    reply = ctl.retry()
    assert reply["ok"] is True
    assert (reply["cf"]["state"], reply["cf"]["reason"]) == ("ready", None)
    assert env.clock.t <= cf_boot.RETRY_SETTLE_S


def test_retry_not_ready_within_window_returns_starting_after_at_most_settle_seconds(env, monkeypatch):
    transport = FakeTransport(sites=())
    ctl, fake_build = _never_built_controller(env, transport)
    monkeypatch.setattr(cf_windows, "build_cf_windows", fake_build)
    reply = ctl.retry()
    assert reply["ok"] is True and (reply["cf"]["state"], reply["cf"]["reason"]) == ("not_ready", "starting")
    assert env.clock.t > 0                              # 注入時鐘真的被等待推進過
    assert env.clock.t <= cf_boot.RETRY_SETTLE_S


def test_retry_webview2_failure_settles_as_webview2_failed(env, monkeypatch):
    transport = FakeTransport(sites=())
    ctl, fake_build = _never_built_controller(env, transport)
    monkeypatch.setattr(cf_windows, "build_cf_windows", fake_build)
    env.script.append((0.5, lambda: setattr(transport, "failed", ["javlibrary", "fc-javten"])))
    reply = ctl.retry()
    assert reply["cf"]["reason"] == "webview2_failed"
    assert env.clock.t <= cf_boot.RETRY_SETTLE_S


def test_retry_on_built_set_only_refreshes_and_never_builds(env, monkeypatch):
    write_client()
    transport = FakeTransport(sites=["javlibrary"])
    builds = []
    monkeypatch.setattr(cf_windows, "build_cf_windows",
                        lambda logger, settings, local_direct=False:
                        builds.append(1) or CfWindowSet(transport=transport, jl_win=CWin("jl", env.log),
                                                        javten_win=CWin("jt", env.log)))
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    refreshed = []
    agent = env.agents[0]
    agent.refresh_now = lambda: refreshed.append(1) or True
    reply = ctl.retry()
    assert builds == [1] and refreshed == [1] and len(env.agents) == 1
    assert env.fetches == [(SERVER, TOKEN, SERVER)]      # 已建過：不再抓設定
    assert reply["ok"] is True


def test_retry_settle_wait_goes_through_injected_wait(env, monkeypatch):
    write_client()
    monkeypatch.setattr(cf_windows, "build_cf_windows",
                        lambda logger, settings, local_direct=False:
                        CfWindowSet(transport=FakeTransport(sites=()), jl_win=CWin("jl", env.log)))
    seen = []

    def fake_wait_for(pred, timeout, wake):
        seen.append(timeout)
        return pred()

    monkeypatch.setattr(cf_boot, "_wait_for", fake_wait_for)
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    env.agents[0].refresh_now = lambda: True
    ctl.retry()
    assert seen == [cf_boot.RETRY_SETTLE_S]


# ---------------------------------------------------------------------------
# I-3 無背景重試
# ---------------------------------------------------------------------------
def test_no_path_but_retry_refetches_cf_settings(env, monkeypatch):
    from windows import shell_sync
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    assert len(env.fetches) == 1
    # 頁面載入鉤子 ×5（副作用口換假件：這裡只證明鉤子不會碰 CF 抓設定）
    monkeypatch.setattr(shell_sync, "sync_tray_locale", lambda w: None)
    monkeypatch.setattr(shell_sync, "_run_async", lambda fn, *a: None)
    monkeypatch.setattr(shell_sync.update_notice, "try_show", lambda *a, **k: None)
    for gen in range(5):
        shell_sync.on_page_loaded("server", MagicMock(), gen)
    # 注入時鐘快轉 10 分鐘：被測碼的等待／睡眠都走這些注入點
    env.clock.t += 600
    cf_shell._sleep(600)
    wake = FakeWake(env.clock)
    cf_boot._wait_for(lambda: False, 600, wake)
    assert env.clock.t >= 1200 and wake.waits                 # 時鐘確實被推進、等待確實走注入點
    assert len(env.fetches) == 1
    assert env.created == [] and env.agents == []
    assert ctl.status()["reason"] == "unreachable"


# ---------------------------------------------------------------------------
# I-15 busy／status
# ---------------------------------------------------------------------------
def test_retry_reentry_returns_busy_and_status_not_blocked(env):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    env.fetch_ok = True
    env.build_hold = threading.Event()
    box = []
    first = run_thread(env, ctl.retry, box)
    try:
        assert env.build_entered.wait(5), "first retry never reached create_window"
        assert ctl.retry() == {"ok": False, "reason": "busy"}
        status_box = []
        st = threading.Thread(target=lambda: status_box.append(ctl.status()), daemon=True)
        env.threads.append(st)
        st.start()
        st.join(2)
        assert not st.is_alive(), "status() blocked behind the in-flight retry"
        assert status_box and status_box[0]["state"] == "not_ready"
        assert box == [] and first.is_alive()                 # 第一次要等 Invoke 返回才回覆
    finally:
        env.build_hold.set()
        join_all(env)
    assert box[0]["ok"] is True


def test_retry_exception_replies_failed_without_leaking_detail(env, monkeypatch):
    write_client()
    env.fetch_ok = False
    logger = MagicMock()
    ctl = make_controller(env, logger=logger)
    ctl.initial()
    bind(ctl)

    def boom(*a, **k):
        raise RuntimeError("SECRET-DETAIL-xyz")

    monkeypatch.setattr(cf_windows, "fetch_client_cf", boom)
    assert ctl.retry() == {"ok": False, "reason": "failed"}
    logged = " ".join(str(c) for c in logger.warning.call_args_list)
    assert "RuntimeError" in logged and "SECRET-DETAIL-xyz" not in logged
    assert ctl.retry()["reason"] != "busy"                  # 例外後 busy 一定被釋放


# ---------------------------------------------------------------------------
# 登記點
# ---------------------------------------------------------------------------
def _retry_built(env, lifecycle=None):
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    quitting = bind(ctl, lifecycle)
    env.fetch_ok = True
    assert ctl.retry()["ok"] is True
    return ctl, quitting


def test_retry_build_attaches_close_guards_that_hide_until_quitting(env):
    ctl, quitting = _retry_built(env)
    jl, jt = ctl.cf_set.jl_win, ctl.cf_set.javten_win
    assert len(jl.events.closing.handlers) == 1 and len(jt.events.closing.handlers) == 1
    assert jl.events.closing.handlers[0]() is False and jl.hidden       # 使用者按 X：只隱藏
    quitting["v"] = True
    assert jt.events.closing.handlers[0]() is None                       # 結束 App：放行


def test_main_close_after_retry_destroys_retry_built_windows(env):
    ctl, _ = _retry_built(env)
    built = [ctl.cf_set.jl_win, ctl.cf_set.javten_win]
    assert all(w is not None for w in built)
    ctl.destroy_all()
    assert [w.destroyed for w in built] == [1, 1]


def test_retry_build_registers_windows_with_lifecycle(env):
    lifecycle = FakeLifecycle()
    ctl, _ = _retry_built(env, lifecycle)
    assert lifecycle.registered == [{"javlibrary": ctl.cf_set.jl_win, "fc-javten": ctl.cf_set.javten_win}]


def test_retry_build_announces_then_starts_the_agent(env):
    ctl, _ = _retry_built(env)
    (agent,) = env.agents
    assert agent.started == 1
    assert env.polls and json_hold(env.polls[0]) == 0           # 補建後先 hold=0 登記


def json_hold(request):
    import json
    return json.loads(request.content)["hold"]


def test_retry_end_to_end_reaches_ready_with_real_transport(env):
    """最小 runtime 證據：真 build_cf_windows＋真 PyWebViewCfTransport＋假 create_window，retry() 回 ready。"""
    ctl, _ = _retry_built(env)
    cf = ctl.status()
    assert (cf["state"], cf["reason"]) == ("ready", None) and cf["sites"] == ["fc-javten", "javlibrary"]


def test_quit_during_inflight_build_destroys_late_built_windows_and_never_registers(env):
    """F1：建窗在途時使用者關主視窗 → build 返回後新建的兩窗當場銷毀、不登記到 lifecycle、不啟動 agent。"""
    lifecycle = FakeLifecycle()
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl, lifecycle)
    env.fetch_ok = True
    env.build_hold = threading.Event()
    box = []
    run_thread(env, ctl.retry, box)
    try:
        assert env.build_entered.wait(5), "retry never reached create_window"
        ctl.destroy_all()                                   # 啟動時的集合是空的；不得等 busy 鎖
    finally:
        env.build_hold.set()
        join_all(env)
    assert box[0]["ok"] is True
    assert sorted(w for op, w in env.log if op == "destroy") == sorted(env.created)
    assert len(env.created) == 2 and lifecycle.registered == []
    assert env.agents[0].started == 0 and env.polls == []


class QuitOnRegisterLifecycle(FakeLifecycle):
    """模擬競態：控制器的 _shutting_down() 檢查通過之後、register 之前，真 lifecycle 已跑完 _begin_quit
    （只銷毀自己 cf_windows 裡的舊集）；register 照真實 tray 邏輯處理晚到的窗。"""

    def __init__(self):
        super().__init__()
        self.destroyed = []

    def register_cf_windows(self, mapping):
        self.quitting = True
        for win in mapping.values():
            if win is not None:
                win.destroy()
                self.destroyed.append(win)


def test_lifecycle_finishing_quit_before_register_does_not_leave_windows_behind(env):
    lifecycle = QuitOnRegisterLifecycle()
    ctl, _ = _retry_built(env, lifecycle)
    assert len(lifecycle.destroyed) == 2
    assert sorted(w for op, w in env.log if op == "destroy") == sorted(env.created)


def test_quit_via_lifecycle_during_inflight_build_also_destroys_late_windows(env):
    lifecycle = FakeLifecycle()
    write_client()
    env.fetch_ok = False
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl, lifecycle)
    env.fetch_ok = True
    env.build_hold = threading.Event()
    run_thread(env, ctl.retry, [])
    try:
        assert env.build_entered.wait(5)
        lifecycle.quitting = True                           # 托盤「結束」：lifecycle 先於控制器知道
    finally:
        env.build_hold.set()
        join_all(env)
    assert len(env.log) == 2 and lifecycle.registered == []


# ---------------------------------------------------------------------------
# 今天現況（initial）與 Q5
# ---------------------------------------------------------------------------
def test_initial_offline_boot_fetches_and_builds_nothing(env):
    ctl = make_controller(env, kind="offline")
    ctl.initial()
    assert env.fetches == [] and env.created == [] and ctl.agent is None
    assert ctl.status() == {"state": "not_ready", "reason": "offline_boot", "proxy_note": None, "sites": []}


def test_retry_from_offline_boot_rereads_saved_pair_at_call_time(env):
    ctl = make_controller(env, kind="offline")
    ctl.initial()
    bind(ctl)
    write_client()                                  # 啟動後才設好連線
    assert ctl.retry()["ok"] is True
    assert env.fetches == [(SERVER, TOKEN, SERVER)]
    assert len(env.created) == 2


def test_retry_unsupported_platform_does_not_fetch(env, monkeypatch):
    monkeypatch.setattr(cf_windows, "cf_shell_supported", lambda: False)
    write_client()
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    reply = ctl.retry()
    assert reply["ok"] is True and reply["cf"]["state"] == "unsupported"
    assert env.fetches == [] and env.created == []


def test_local_kind_uses_local_origin_without_token(env):
    write_client()                                  # client.json 殘留 token 也不得帶出去
    ctl = make_controller(env, kind="local")
    ctl.initial()
    assert env.fetches == [(LOCAL, None, LOCAL)]
    assert env.agents[0]._origin == LOCAL and env.agents[0]._token is None


def test_initial_does_not_announce_until_asked(env):
    write_client()
    ctl = make_controller(env)
    ctl.initial()
    bind(ctl)
    assert env.polls == []                          # Q1：announce 由入口在原位置呼叫
    ctl.announce_initial()
    assert len(env.polls) == 1 and json_hold(env.polls[0]) == 0
