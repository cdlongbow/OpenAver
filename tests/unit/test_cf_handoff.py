"""core/cf_handoff.py 不變式 oracle（168d-T1）：I-H1～I-H5、I-R、例外映射、大小上限、
available_sites liveness、current_key 三態、last_failure、restart_needed_here。

時序全用假時鐘＋替身 Event（呼叫端省略 timeout 立即 AssertionError），不真等；
只有「真執行緒」兩格用真 Event（逾時設在 2 秒內完成）。
"""
import contextvars
import inspect
import threading
import time

import pytest

from core import cf_handoff as m
from core.cf_transport import CfChallengeRequired, CfTransport, CfTransportUnavailable
from core.proxy_policy import ProxySettings, cf_window_proxy, cf_window_proxy_fingerprint

_MISSING = object()


class _Env:
    def __init__(self):
        self.t = 100.0
        self.hooks = []          # 依序在每次 wait 時消耗一個
        self.waits = []          # 每次 wait 的 timeout


class _FakeEvent:
    env: _Env = None

    def __init__(self):
        self._flag = False

    def set(self):
        self._flag = True

    def is_set(self):
        return self._flag

    def wait(self, timeout=_MISSING):
        if timeout is _MISSING:
            raise AssertionError("Event.wait() called without timeout")
        env = type(self).env
        env.waits.append(timeout)
        if not self._flag and env.hooks:
            env.hooks.pop(0)()
        if not self._flag:
            env.t += timeout
        return self._flag


@pytest.fixture(autouse=True)
def _reset_current_key():
    """ContextVar 會跨測試殘留（BE-TEST-45）：每格歸零為 _UNSET。"""
    tok = m.current_key.set(m._UNSET)
    yield
    m.current_key.reset(tok)


@pytest.fixture
def env(monkeypatch):
    e = _Env()
    _FakeEvent.env = e
    monkeypatch.setattr(m, "_now", lambda: e.t)
    monkeypatch.setattr(m, "_event_factory", _FakeEvent)
    monkeypatch.setattr(m, "_broker", m.Broker())
    return e


@pytest.fixture
def real_broker(monkeypatch):
    b = m.Broker()
    monkeypatch.setattr(m, "_broker", b)
    return b


def _shell(env, key, ok=True, value="html", error=None, message=""):
    """假殼：下一次 wait 時領走該 key 的 job 並回結果。"""
    def hook():
        job = m._broker.claim(key)
        assert job is not None
        assert m._broker.complete(key, job["id"], ok, value=value, error=error, message=message)
    env.hooks.append(hook)


def _claim_only(env, key, box=None):
    def hook():
        job = m._broker.claim(key)
        if box is not None:
            box.append(job)
    env.hooks.append(hook)


def _b():
    return m._broker


# ---------------- I-H1 ----------------

def test_no_shell_raises_immediately_without_waiting(env):
    with pytest.raises(CfTransportUnavailable):
        _b().submit("k", "fetch", {"url": "u", "cache_key": "javlibrary"})
    assert env.waits == []
    assert _b().last_failure["k"] == "shell_lost"


def test_stale_shell_raises_immediately_without_waiting(env):
    _b().register_shell("k", ["javlibrary"])
    env.t += m.LIVENESS_S + 1
    with pytest.raises(CfTransportUnavailable):
        _b().submit("k", "fetch", {})
    assert env.waits == []
    assert _b().last_failure["k"] == "shell_lost"


def test_registered_but_never_claims_times_out_after_claim_timeout(env):
    _b().register_shell("k", ["javlibrary"])
    start = env.t
    with pytest.raises(CfTransportUnavailable):
        _b().submit("k", "fetch", {})
    assert env.waits == [m.TIMEOUTS["fetch"][0]]       # 只等了 claim，沒進 exec
    assert env.t - start == m.TIMEOUTS["fetch"][0]
    assert _b().last_failure["k"] == "shell_lost"


def test_claimed_but_never_returns_times_out_after_exec_timeout(env):
    _b().register_shell("k", ["javlibrary"])
    env.t += 0  # fresh
    _claim_only(env, "k")
    with pytest.raises(CfTransportUnavailable):
        _b().submit("k", "fetch", {})
    claim_t, exec_t = m.TIMEOUTS["fetch"]
    assert env.waits == [claim_t, exec_t]
    assert _b().last_failure["k"] == "shell_lost"


def test_exec_wait_always_passes_timeout(env):
    """exec 等待必帶 timeout：替身 Event 省略 timeout 即 AssertionError（突變以紅燈收場）。"""
    _b().register_shell("k", [])
    _claim_only(env, "k")
    with pytest.raises(CfTransportUnavailable):
        _b().submit("k", "is_ready", {"cache_key": "javlibrary"})
    assert env.waits[-1] == m.TIMEOUTS["is_ready"][1]


# ---------------- I-H2 ----------------

def test_claim_cross_key_returns_none(env):
    b = _b()
    b.register_shell("A", [])
    job = b._enqueue("A", "fetch", {})
    assert b.claim("B") is None
    assert job.state == "queued"
    got = b.claim("A")
    assert got["id"] == job.id


def test_result_from_other_key_is_rejected_and_job_not_woken(env):
    b = _b()
    b.register_shell("A", [])
    b.register_shell("B", [])
    ja = b._enqueue("A", "fetch", {})
    jb = b._enqueue("B", "fetch", {})
    assert b.claim("A")["id"] == ja.id
    assert b.claim("B")["id"] == jb.id
    assert b.complete("B", ja.id, True, value="evil") is False
    assert ja.state == "claimed" and not ja.done.is_set()
    assert b.complete("A", ja.id, True, value="good") is True
    assert ja.value == "good"


# ---------------- I-H3 ----------------

def test_claimed_job_never_redelivered(env):
    b = _b()
    b.register_shell("A", [])
    j = b._enqueue("A", "fetch", {})
    assert b.claim("A")["id"] == j.id
    assert b.claim("A") is None
    assert b.claim("A") is None


def test_late_result_after_exec_timeout_rejected(env):
    b = _b()
    b.register_shell("A", [])
    box = []
    _claim_only(env, "A", box)
    with pytest.raises(CfTransportUnavailable):
        b.submit("A", "fetch", {})
    old_id = box[0]["id"]
    assert b.complete("A", old_id, True, value="stale-html") is False


def test_late_result_after_claim_timeout_rejected(env):
    b = _b()
    b.register_shell("A", [])
    with pytest.raises(CfTransportUnavailable):
        b.submit("A", "fetch", {})
    assert b.claim("A") is None   # 放棄的 job 不再投遞


# ---------------- I-H4 ----------------

def test_concurrent_fetches_each_get_own_result(real_broker):
    b = real_broker
    b.register_shell("k", ["javlibrary"])
    n = 8
    results = {}

    def worker(i):
        m.current_key.set("k")
        results[i] = m.transport().fetch(f"http://x/{i}", "javlibrary")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    claimed = []
    deadline = time.monotonic() + 2
    while len(claimed) < n and time.monotonic() < deadline:
        job = b.claim("k")
        if job is None:
            time.sleep(0.005)
        else:
            claimed.append(job)
    assert len(claimed) == n
    for job in reversed(claimed):                      # 亂序回覆
        assert b.complete("k", job["id"], True, value="html:" + job["args"]["url"])
    for t in threads:
        t.join(2)
    assert results == {i: f"html:http://x/{i}" for i in range(n)}


# ---------------- I-H5 ----------------

def test_navigate_then_fetch_target_same_key(env, monkeypatch):
    b = _b()
    b.register_shell("shellK", ["javlibrary"])
    keys = []
    orig = b._enqueue

    def spy(key, kind, args):
        keys.append(key)
        return orig(key, kind, args)

    monkeypatch.setattr(b, "_enqueue", spy)
    _shell(env, "shellK", value="https://final/")
    _shell(env, "shellK", value="<html/>")

    def run():
        m.current_key.set("shellK")
        t = m.transport()
        return t.navigate_and_settle("https://u/", "javlibrary"), t.fetch("https://final/", "javlibrary")

    assert contextvars.copy_context().run(run) == ("https://final/", "<html/>")
    assert keys == ["shellK", "shellK"]


# ---------------- I-R ----------------

# ---------------- 例外映射／大小上限 ----------------

def test_challenge_error_maps_to_cf_challenge_required(env):
    _b().register_shell("k", [])
    _shell(env, "k", ok=False, error="challenge", message="cf page")
    with pytest.raises(CfChallengeRequired, match="cf page"):
        _b().submit("k", "fetch", {})


@pytest.mark.parametrize("error,exc", [
    ("unavailable", CfTransportUnavailable),
    ("timeout", TimeoutError),
    ("error", RuntimeError),
    ("whatever", RuntimeError),
])
def test_other_errors_map_to_exceptions(env, error, exc):
    _b().register_shell("k", [])
    _shell(env, "k", ok=False, error=error, message="msg")
    with pytest.raises(exc, match="msg") as ei:
        _b().submit("k", "fetch", {})
    assert not isinstance(ei.value, CfChallengeRequired)
    if exc is RuntimeError:
        assert not isinstance(ei.value, CfTransportUnavailable)


def test_oversize_result_is_consumed_not_rejected(env):
    b = _b()
    b.register_shell("k", [])
    j = b._enqueue("k", "fetch", {})
    b.claim("k")
    assert b.complete("k", j.id, True, value="x" * (8 * 1024 * 1024 + 1)) is True
    assert j.ok is False and j.error == "error"


# ---------------- available_sites liveness ----------------

def test_available_sites_empty_after_liveness_expired(env):
    b = _b()
    b.register_shell("k", ["javlibrary", "fc-javten"])
    m.current_key.set("k")
    assert m.transport().available_sites() == ["fc-javten", "javlibrary"]
    assert m.transport().available_here() is True
    env.t += m.LIVENESS_S - 1
    assert m.transport().available_sites() == ["fc-javten", "javlibrary"]
    env.t += 2
    assert m.transport().available_sites() == []
    assert m.transport().available_here() is False


# ---------------- current_key 三態 ----------------

@pytest.mark.parametrize("state", ["none", "unset"])
def test_job_methods_fail_closed_without_key(env, state):
    _b().register_shell("loopback", ["javlibrary"])
    if state == "none":
        m.current_key.set(None)
    t = m.transport()
    for call in (lambda: t.fetch("u", "javlibrary"), lambda: t.navigate_and_settle("u", "javlibrary"),
                 lambda: t.begin_solve("u", "javlibrary"), lambda: t.is_ready("javlibrary")):
        with pytest.raises(CfTransportUnavailable):
            call()
    assert env.waits == []


def test_current_key_three_states_for_reads(env):
    _b().register_shell("loopback", ["javlibrary"])
    _b().register_shell("k", ["fc-javten"])
    t = m.transport()
    # _UNSET：唯讀 fallback 到 loopback 殼
    assert t.available_sites() == ["javlibrary"]
    assert t.available_here() is False
    m.current_key.set(None)
    assert t.available_sites() == []
    assert t.available_here() is False
    m.current_key.set("k")
    assert t.available_sites() == ["fc-javten"]
    assert t.available_here() is True


# ---------------- last_failure ----------------

def test_last_failure_recorded_consumed_and_cleared_on_success(env):
    b = _b()
    b.register_shell("k", [])
    _claim_only(env, "k")
    with pytest.raises(CfTransportUnavailable):
        b.submit("k", "fetch", {})
    assert m.consume_failure_here("k") == "shell_lost"
    assert m.consume_failure_here("k") is None          # 消費即清

    with pytest.raises(CfTransportUnavailable):
        b.submit("k", "fetch", {})                       # claim 逾時也記
    assert b.last_failure["k"] == "shell_lost"
    b.register_shell("k", [])
    _shell(env, "k", value="ok")
    assert b.submit("k", "fetch", {}) == "ok"
    assert m.consume_failure_here("k") is None           # 成功 result 清除


# ---------------- restart_needed_here ----------------

def _register_like_shell(key, settings, shell="windows", server_remote=False):
    if shell == "mac":
        spec = None
    else:
        eff, _ = m.client_cf_settings(settings, server_remote)
        spec = cf_window_proxy(eff)
    _b().register_shell(key, ["javlibrary"], applied_proxy=cf_window_proxy_fingerprint(spec),
                        shell=shell, server_remote=server_remote)


def test_restart_needed_unregistered_is_false(env):
    m.current_key.set("ghost")
    assert m.restart_needed_here(ProxySettings(url="http://h:1", scope="all")) is False
    m.current_key.set(m._UNSET)
    assert m.restart_needed_here(ProxySettings(url="http://h:1", scope="all")) is False


@pytest.mark.parametrize("shell,remote,url", [
    ("windows", False, ""),
    ("windows", False, "http://h:1"),
    ("windows", True, "http://127.0.0.1:7890"),
    ("mac", False, "http://h:1"),
])
def test_restart_not_needed_when_settings_unchanged(env, shell, remote, url):
    s = ProxySettings(url=url, scope="all")
    _register_like_shell("k", s, shell, remote)
    m.current_key.set("k")
    assert m.restart_needed_here(s) is False


@pytest.mark.parametrize("shell,remote,old,new", [
    ("windows", False, "http://h:1", "http://h:2"),
    ("windows", False, "", "http://h:2"),
    ("windows", True, "", "http://192.168.1.5:7890"),
    ("windows", True, "http://127.0.0.1:7890", "http://192.168.1.5:7890"),
])
def test_restart_needed_when_effective_spec_changes(env, shell, remote, old, new):
    _register_like_shell("k", ProxySettings(url=old, scope="all"), shell, remote)
    m.current_key.set("k")
    assert m.restart_needed_here(ProxySettings(url=new, scope="all")) is True


def test_restart_scope_change_under_proxy_needs_restart(env):
    _register_like_shell("k", ProxySettings(url="http://h:1", scope="all"))
    m.current_key.set("k")
    assert m.restart_needed_here(ProxySettings(url="http://h:1", scope="dmm")) is True


@pytest.mark.parametrize("new", ["http://h:9", "http://127.0.0.1:1", ""])
def test_restart_not_needed_for_mac_any_change(env, new):
    _register_like_shell("k", ProxySettings(url="http://h:1", scope="all"), shell="mac")
    m.current_key.set("k")
    assert m.restart_needed_here(ProxySettings(url=new, scope="all")) is False


def test_restart_not_needed_loopback_to_other_loopback_under_remote(env):
    _register_like_shell("k", ProxySettings(url="http://127.0.0.1:1", scope="all"), server_remote=True)
    m.current_key.set("k")
    assert m.restart_needed_here(ProxySettings(url="http://localhost:9", scope="all")) is False


# ---------------- 真執行緒 ----------------

def test_real_thread_shell_round_trip(real_broker):
    b = real_broker
    b.register_shell("k", ["javlibrary"])
    stop = threading.Event()

    def shell():
        deadline = time.monotonic() + 2
        while not stop.is_set() and time.monotonic() < deadline:
            job = b.claim("k")
            if job is None:
                time.sleep(0.005)
                continue
            b.complete("k", job["id"], True, value="real:" + job["args"]["url"])
            return

    th = threading.Thread(target=shell, daemon=True)
    th.start()
    m.current_key.set("k")
    t0 = time.monotonic()
    assert m.transport().fetch("http://u/", "javlibrary") == "real:http://u/"
    assert time.monotonic() - t0 < 2
    stop.set()
    th.join(2)


# ---------------- 其他 ----------------

@pytest.mark.parametrize("name", ["begin_solve", "is_ready", "available_sites", "fetch", "navigate_and_settle"])
def test_transport_signatures_match_protocol(name):
    want = inspect.signature(getattr(CfTransport, name))
    got = inspect.signature(getattr(m.HandoffCfTransport, name))
    assert list(got.parameters) == list(want.parameters)
