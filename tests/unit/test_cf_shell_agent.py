"""168d-T3：windows/cf_shell.py（CfShellAgent／check_job）。

時序用假 `_sleep`＋`httpx.MockTransport`＋同步假 executor，不真等；每個腳本化 handler 都有硬上限，
被 mutation 改壞時會紅而不是卡死。唯一的真 socket／真執行緒是 `real_socket` 那一格。
"""
from __future__ import annotations

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = str(REPO_ROOT / 'windows')
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

import cf_shell  # noqa: E402
from core import client_settings  # noqa: E402
from core.cf_handoff import CF_SITE_ORIGINS  # noqa: E402
from core.cf_transport import CfChallengeRequired, CfTransportUnavailable  # noqa: E402
from core.proxy_policy import CfWindowProxy, cf_window_proxy_fingerprint  # noqa: E402

ORIGIN = 'http://shell-test.invalid:8765'
JL = CF_SITE_ORIGINS['javlibrary']
JT = CF_SITE_ORIGINS['fc-javten']
OK_NULL = {'ok': True, 'job': None}
MAX_CALLS = 20


# ---------------------------------------------------------------------------
# 假件
# ---------------------------------------------------------------------------
class SyncExecutor:
    def submit(self, fn, *a, **k):
        fn(*a, **k)

    def shutdown(self, *a, **k):
        pass


class FakeImpl:
    def __init__(self, sites=('fc-javten', 'javlibrary')):
        self.sites = list(sites)
        self.calls = []
        self.load_url_calls = 0
        self.raise_exc = None
        self.returns = {'fetch': '<html>x</html>', 'navigate_and_settle': 'https://javten.com/final',
                        'is_ready': True, 'begin_solve': None}

    def available_sites(self):
        return list(self.sites)

    def load_url(self, *a, **k):
        self.load_url_calls += 1

    def _do(self, name, *a):
        self.calls.append((name, a))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.returns[name]

    def fetch(self, url, cache_key='javlibrary'):
        return self._do('fetch', url, cache_key)

    def navigate_and_settle(self, url, cache_key):
        return self._do('navigate_and_settle', url, cache_key)

    def begin_solve(self, origin_url, cache_key='javlibrary'):
        return self._do('begin_solve', origin_url, cache_key)

    def is_ready(self, cache_key='javlibrary'):
        return self._do('is_ready', cache_key)


def make_windows(impl=None, *, jl=True, jt=True, proxy_ok=True, proxy_spec=None, local_direct=False):
    return types.SimpleNamespace(transport=impl, jl_win=object() if jl else None,
                                 javten_win=object() if jt else None, proxy_ok=proxy_ok,
                                 proxy_spec=proxy_spec, local_direct=local_direct)


class Harness:
    """腳本化伺服器：poll 依序吐 script 的項目，用完就 stop agent；result 只記錄。"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.polls = []
        self.results = []
        self.agent = None
        self.sleeps = []

    @property
    def exhausted(self):
        return not self.script

    def handler(self, request):
        self.requests.append(request)
        if len(self.requests) > MAX_CALLS:
            raise AssertionError('handler called too many times')
        body = json.loads(request.content or b'{}')
        if request.url.path == cf_shell.RESULT_PATH:
            self.results.append(body)
            return httpx.Response(200, json={'ok': True, 'accepted': True})
        self.polls.append(body)
        item = self.script.pop(0) if self.script else OK_NULL
        if self.exhausted and self.agent is not None:
            self.agent.stop()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    def fake_sleep(self, s):
        self.sleeps.append(s)
        if len(self.sleeps) > MAX_CALLS:
            raise AssertionError('sleep called too many times')
        if self.exhausted and self.agent is not None:
            self.agent.stop()


@pytest.fixture
def make(monkeypatch):
    def _make(script, *, token=None, windows=None, shell='windows', supported=True, server_remote=False):
        h = Harness(script)
        monkeypatch.setattr(cf_shell, '_sleep', h.fake_sleep)
        agent = cf_shell.CfShellAgent(
            ORIGIN, token, windows if windows is not None else make_windows(FakeImpl()),
            shell=shell, server_remote=server_remote, supported=supported,
            http_transport=httpx.MockTransport(h.handler), executor=SyncExecutor())
        h.agent = agent
        return agent, h
    return _make


def job(kind, **args):
    return {'ok': True, 'job': {'id': 'j1', 'kind': kind, 'args': args}}


# ---------------------------------------------------------------------------
# check_job：白名單矩陣（通過／拒絕分開，BE-TEST-11）
# ---------------------------------------------------------------------------
def _mk(kind, **args):
    return {'id': 'j1', 'kind': kind, 'args': args}


PASS_JOBS = [
    _mk('fetch', url=JL + 'ja/?v=1', cache_key='javlibrary'),
    _mk('fetch', url='https://javten.com/search?kw=1', cache_key='fc-javten'),
    _mk('navigate_and_settle', url='https://JAVTEN.com/', cache_key='fc-javten'),
    _mk('begin_solve', origin_url=JL, cache_key='javlibrary'),
    _mk('begin_solve', origin_url=JT, cache_key='fc-javten'),
    _mk('is_ready', cache_key='javlibrary'),
    _mk('is_ready', cache_key='fc-javten'),
    # 168d Codex F3：javten 站方會落地 www.（fc2_javten 同收兩個 netloc）
    _mk('fetch', url='https://www.javten.com/search?kw=1', cache_key='fc-javten'),
    _mk('navigate_and_settle', url='https://WWW.javten.com/', cache_key='fc-javten'),
]
# 通過格期望：impl 方法名與回報值（fake impl 的回傳值）
EXPECT = {'fetch': ('fetch', '<html>x</html>'), 'navigate_and_settle': ('navigate_and_settle', 'https://javten.com/final'),
          'begin_solve': ('begin_solve', True), 'is_ready': ('is_ready', True)}

LOOKALIKE = [
    'https://eviljavlibrary.com/',
    'https://www.javlibrary.com.evil.com/ja/',
    'https://evil.com/?x=https://javten.com/',
    'http://javten.com/',
    'https://javten.com:8443/',
    'https://user@javten.com/',
    'https://javten.com@evil.com/',
    'https://xjavten.com/',
    'file:///etc/passwd',
    'javascript:alert(1)',
    'https://[::1/',
    'about:blank',
    '',
]
_URL_FIELD = {'fetch': 'url', 'navigate_and_settle': 'url', 'begin_solve': 'origin_url'}

LOOKALIKE_JOBS = [_mk(k, **{f: u, 'cache_key': key}) for u in LOOKALIKE for k, f in _URL_FIELD.items()
                  for key in ('javlibrary', 'fc-javten')]
MISMATCH_JOBS = [_mk(k, **{f: u, 'cache_key': key}) for k, f in _URL_FIELD.items()
                 for key, u in (('javlibrary', JT + 'x'), ('fc-javten', JL + 'x'))]
MALFORMED_JOBS = [
    _mk('fetch', url=JL, cache_key='nope'),
    _mk('fetch', url=JL),
    _mk('is_ready', cache_key='nope'),
    _mk('eval_js', url=JL, cache_key='javlibrary'),
    {'id': 'j1', 'kind': 'fetch', 'args': 'not-a-dict'},
    _mk('fetch', url=123, cache_key='javlibrary'),
    _mk('fetch', url=None, cache_key='javlibrary'),
    _mk('fetch', url=['https://javten.com/'], cache_key='fc-javten'),
    {'id': 'j1', 'kind': ['fetch'], 'args': {}},
    {'id': 'j1'},
]
# F3 反向格：netloc 必須整串屬於集合；port／userinfo／scheme／別站 www 都不行
JAVTEN_REJECT_URLS = [
    'https://javten.com.evil.com/', 'https://www.javten.com.evil.com/',
    'https://javten.com:8443/', 'https://www.javten.com:8443/',
    'https://u@javten.com/', 'https://u@www.javten.com/',
    'http://www.javten.com/', 'http://javten.com/',
]
LOOKALIKE_JOBS += [_mk(k, **{f: u, 'cache_key': 'fc-javten'}) for u in JAVTEN_REJECT_URLS
                   for k, f in _URL_FIELD.items()]
# javlibrary 不收 javten 的 www 變體；javten key 不收 javlibrary
MISMATCH_JOBS += [_mk('fetch', url='https://www.javten.com/', cache_key='javlibrary')]
ALL_REJECT_JOBS = LOOKALIKE_JOBS + MISMATCH_JOBS + MALFORMED_JOBS


@pytest.mark.parametrize('j', LOOKALIKE_JOBS)
def test_check_job_rejects_lookalike_hosts(j):
    assert cf_shell.check_job(j) is False


@pytest.mark.parametrize('j', MISMATCH_JOBS)
def test_check_job_rejects_key_origin_mismatch(j):
    assert cf_shell.check_job(j) is False




# ---------------------------------------------------------------------------
# 經 agent 執行路徑：同一份矩陣；通過恰呼叫 impl 一次、拒絕零呼叫且回報 rejected
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('j', PASS_JOBS)
def test_allowed_job_calls_impl_exactly_once_and_posts_value(make, j):
    impl = FakeImpl()
    agent, h = make([{'ok': True, 'job': j}], windows=make_windows(impl))
    agent.run()
    name, value = EXPECT[j['kind']]
    assert [c[0] for c in impl.calls] == [name]
    assert impl.load_url_calls == 0
    assert h.results == [{'id': 'j1', 'ok': True, 'value': value}]


@pytest.mark.parametrize('j', ALL_REJECT_JOBS)
def test_rejected_job_never_reaches_impl_and_reports_rejected(make, j):
    impl = FakeImpl()
    agent, h = make([{'ok': True, 'job': j}], windows=make_windows(impl))
    agent.run()
    assert impl.calls == [] and impl.load_url_calls == 0
    assert h.results == [{'id': 'j1', 'ok': False, 'error': 'error', 'message': 'rejected'}]


@pytest.mark.parametrize('exc,error', [
    (CfChallengeRequired('c'), 'challenge'),
    (CfTransportUnavailable('u'), 'unavailable'),
    (TimeoutError('t'), 'timeout'),
    (ValueError('boom'), 'error'),
])
def test_impl_exceptions_map_to_error_codes(make, exc, error):
    impl = FakeImpl()
    impl.raise_exc = exc
    agent, h = make([job('fetch', url=JL, cache_key='javlibrary')], windows=make_windows(impl))
    agent.run()
    (res,) = h.results
    assert res['ok'] is False and res['error'] == error and res['message'] == str(exc)


def test_no_transport_reports_unavailable(make):
    agent, h = make([job('is_ready', cache_key='javlibrary')], windows=make_windows(None))
    agent.run()
    assert h.results[0]['ok'] is False and h.results[0]['error'] == 'unavailable'


# ---------------------------------------------------------------------------
# I-P1 退避
# ---------------------------------------------------------------------------
def test_backoff_sequence_then_reset(make):
    err = httpx.ConnectError('down')
    agent, h = make([err, err, err, OK_NULL, err, OK_NULL])
    agent.run()
    assert h.sleeps == [1, 2, 4, 1]
    # 恢復後第一次請求就帶完整登記資料（I-P1）
    assert h.polls[3] == {'shell': 'windows', 'sites': ['fc-javten', 'javlibrary'], 'applied_proxy': None,
                          'server_remote': False, 'hold': cf_shell.HOLD_S, 'preparing': []}


def test_backoff_caps_at_ten_seconds(make):
    err = httpx.ConnectError('down')
    agent, h = make([err] * 7 + [OK_NULL])
    agent.run()
    assert h.sleeps == [1, 2, 4, 8, 10, 10, 10]


@pytest.mark.parametrize('resp', [
    httpx.Response(500, text='boom'),
    httpx.Response(400, json={}),
    httpx.Response(200, text='<html>not json</html>'),
    httpx.Response(200, json=['not', 'a', 'dict']),
    httpx.Response(200, json={'ok': False}),
    httpx.Response(200, json={'ok': True, 'job': 'str'}),
    httpx.ReadTimeout('slow'),
])
def test_retryable_failures_back_off_and_recover(make, resp):
    agent, h = make([resp, OK_NULL])
    agent.run()
    assert h.sleeps == [1]
    assert agent.public_status()['reason'] != 'unreachable'


# ---------------------------------------------------------------------------
# I-P2 一次性降級
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('resp,reason', [
    (httpx.Response(404), 'server_old'),
    (httpx.Response(405), 'server_old'),
    (httpx.Response(401), 'unauthorized'),
    (httpx.Response(403), 'unauthorized'),
    (httpx.Response(302, headers={'Location': 'https://evil.example/x'}), 'unauthorized'),
])
def test_404_stops_poller_zero_second_request(make, resp, reason):
    agent, h = make([resp, OK_NULL, OK_NULL])
    agent.run()                                  # 自己返回，不靠測試呼叫 stop
    assert len(h.requests) == 1 and h.sleeps == []
    st = agent.public_status()
    assert (st['state'], st['reason']) == ('not_ready', reason)
    agent.start()                                # 終態後不再起新緒
    assert agent._thread is None and len(h.requests) == 1




# ---------------------------------------------------------------------------
# I-P3 轉址／回應內網址／憑證
# ---------------------------------------------------------------------------
def test_redirect_not_followed_zero_second_request(make):
    agent, h = make([httpx.Response(302, headers={'Location': 'https://evil.example/x'}), OK_NULL], token='T')
    agent.run()
    assert len(h.requests) == 1
    assert all(r.url.host != 'evil.example' for r in h.requests)


def test_response_body_urls_never_used(make):
    evil = {'next_url': 'https://evil.example/n', 'url': 'https://evil.example/u',
            'origin': 'https://evil.example', 'redirect': 'https://evil.example/r'}
    script = [{**OK_NULL, **evil}, {**job('fetch', url=JL, cache_key='javlibrary'), **evil}, {**OK_NULL, **evil}]
    agent, h = make(script, token='T')
    agent.run()
    for r in h.requests:
        assert str(r.url).startswith(ORIGIN + '/api/cf/shell/')
        assert r.url.host != 'evil.example'
    assert len(h.requests) >= 4


def test_local_mode_sends_no_authorization_even_if_client_json_has_token(make, monkeypatch):
    monkeypatch.setattr(client_settings, 'server_pair', lambda: ('http://x', 'TOKEN'))
    agent, h = make([job('is_ready', cache_key='javlibrary'), OK_NULL], token=None)
    agent.run()
    assert len(h.requests) >= 3
    assert all('authorization' not in r.headers for r in h.requests)


def test_client_mode_sends_bearer_on_every_request(make):
    agent, h = make([job('is_ready', cache_key='javlibrary'), OK_NULL], token='T')
    agent.run()
    assert len(h.requests) >= 3
    assert all(r.headers.get('authorization') == 'Bearer T' for r in h.requests)


def test_agent_never_logs_or_exposes_token_in_status(make):
    agent, _ = make([OK_NULL], token='TOKEN')
    agent.run()
    assert 'TOKEN' not in repr(agent.public_status())


# ---------------------------------------------------------------------------
# 請求內容
# ---------------------------------------------------------------------------
def test_poll_body_windows_carries_fingerprint_and_flags(make):
    spec = CfWindowProxy(server='http://127.0.0.1:7890', username='u', password='p', usable=True)
    agent, h = make([OK_NULL], windows=make_windows(FakeImpl(sites=('javlibrary',)), proxy_spec=spec),
                    server_remote=True)
    agent.run()
    assert h.polls[0] == {'shell': 'windows', 'sites': ['javlibrary'],
                          'applied_proxy': cf_window_proxy_fingerprint(spec),
                          'server_remote': True, 'hold': cf_shell.HOLD_S,
                          'preparing': []}


def test_poll_body_mac_never_reports_proxy(make):
    spec = CfWindowProxy(server='http://127.0.0.1:7890', username=None, password=None, usable=True)
    agent, h = make([OK_NULL], shell='mac', windows=make_windows(FakeImpl(), proxy_spec=spec))
    agent.run()
    assert h.polls[0]['shell'] == 'mac' and h.polls[0]['applied_proxy'] is None


def test_poll_body_without_transport_has_empty_sites(make):
    agent, h = make([OK_NULL], windows=make_windows(None))
    agent.run()
    assert h.polls[0]['sites'] == []


def test_shell_defaults_from_desktop_kind(monkeypatch):
    monkeypatch.setattr(cf_shell, 'desktop_kind', lambda: 'mac')
    assert cf_shell.CfShellAgent(ORIGIN, None, make_windows())._shell == 'mac'
    monkeypatch.setattr(cf_shell, 'desktop_kind', lambda: 'windows')
    assert cf_shell.CfShellAgent(ORIGIN, None, make_windows())._shell == 'windows'


def test_announce_is_a_hold_zero_poll_and_failure_is_not_fatal(make):
    agent, h = make([OK_NULL, httpx.ConnectError('down')])
    assert agent.announce() is True
    assert h.polls[0]['hold'] == 0
    assert agent.announce() is False            # 失敗不致命、不拋、不睡
    assert h.sleeps == []



# ---------------------------------------------------------------------------
# 168e-T13 I-5：逾時分流（announce 3／長輪詢 HOLD_S+10／補送 RESULT_TIMEOUT_S）
# ---------------------------------------------------------------------------
@pytest.fixture
def post_timeouts(monkeypatch):
    seen = []
    real_post = httpx.Client.post

    def spy(self, url, *a, **k):
        seen.append((str(url).rsplit('/', 1)[-1], k.get('timeout')))
        return real_post(self, url, *a, **k)

    monkeypatch.setattr(httpx.Client, 'post', spy)
    return seen


def test_announce_uses_announce_timeout_not_result_timeout(make, post_timeouts):
    agent, h = make([OK_NULL])
    assert cf_shell.ANNOUNCE_TIMEOUT_S == 3
    assert agent.announce() is True
    assert post_timeouts == [('poll', cf_shell.ANNOUNCE_TIMEOUT_S)]


def test_announce_failure_does_not_stop_later_long_poll_registration(make):
    agent, h = make([httpx.ConnectError('down'), OK_NULL])
    assert agent.announce() is False
    agent.run()
    assert [p['hold'] for p in h.polls][0] == 0
    assert any(p['hold'] > 0 for p in h.polls)
    assert agent.public_status()['state'] == 'ready'


# ---------------------------------------------------------------------------
# 168e-T13 B：refresh_now
# ---------------------------------------------------------------------------
def _join_poller(agent):
    t = agent._thread
    if t is not None:
        t.join(timeout=5)
        assert not t.is_alive(), 'poller thread leaked (BE-TEST-45)'
    st = agent._sync_thread
    if st is not None:
        agent._stop.set()
        agent._sync_wake.set()
        st.join(timeout=5)
        assert not st.is_alive(), 'sync thread leaked (BE-TEST-45)'


@pytest.mark.parametrize('resp,terminal', [(httpx.Response(404), 'server_old'), (httpx.Response(401), 'unauthorized')])
def test_refresh_now_clears_recoverable_terminal_and_reregisters(make, post_timeouts, resp, terminal):
    agent, h = make([resp, OK_NULL])
    agent.run()
    assert agent.public_status()['reason'] == terminal
    try:
        assert agent.refresh_now() is True
        assert agent._terminal is None
        assert h.polls[1]['hold'] == 0                       # 先同步 hold=0 登記
        _join_poller(agent)                                  # 輪詢緒被重啟並因腳本用盡而收掉
        assert agent.public_status()['state'] == 'ready'
    finally:
        agent.stop()
        _join_poller(agent)


class _ParkedTerminal:
    """把舊輪詢緒卡在「終態已公布、尚未返回 run()」；之後的長輪詢也停住（模擬真的長輪詢）。"""

    def __init__(self, agent):
        self.entered, self.release_old, self.park = threading.Event(), threading.Event(), threading.Event()
        self._first = True
        self._orig = agent._poll_once
        agent._poll_once = self

    def __call__(self, hold, timeout=None):
        if hold == 0:
            return self._orig(hold, timeout)
        if self._first:
            self._first = False
            out = self._orig(hold, timeout)
            self.entered.set()
            if not self.release_old.wait(10):
                raise AssertionError('old poller never released (BE-TEST-45)')
            return out
        self.park.wait(10)
        return 'ok'


def _poller_threads():
    return [t for t in threading.enumerate() if t.name == 'cf-shell-poller' and t.is_alive()]


def _wait_flag(pred, what):
    import time as _t
    end = _t.monotonic() + 5
    while not pred():
        if _t.monotonic() > end:
            pytest.fail(what + ' (BE-TEST-45)')
        _t.sleep(0.005)


def test_refresh_now_waits_for_old_terminal_poller_and_leaves_exactly_one_live_poller(make):
    agent, h = make([httpx.Response(401), OK_NULL, OK_NULL])
    gate = _ParkedTerminal(agent)
    agent.start()
    old = agent._thread
    out = []
    refresher = threading.Thread(target=lambda: out.append(agent.refresh_now()), daemon=True)
    try:
        assert gate.entered.wait(5), 'old poller never published the terminal'
        refresher.start()
        _wait_flag(agent._stop.is_set, 'refresh_now never asked the old poller to exit')
        gate.release_old.set()
        refresher.join(5)
        assert not refresher.is_alive() and out == [True]
        assert not old.is_alive()
        assert agent._thread is not old and agent._thread.is_alive()
        assert _poller_threads() == [agent._thread]
        assert agent._terminal is None
    finally:
        gate.release_old.set()
        agent._stop.set()
        gate.park.set()
        refresher.join(5)
        _join_poller(agent)


def test_refresh_now_reports_failure_when_old_poller_does_not_exit(make, monkeypatch):
    monkeypatch.setattr(cf_shell, 'REFRESH_JOIN_S', 0.05)
    agent, h = make([httpx.Response(401), OK_NULL])
    gate = _ParkedTerminal(agent)
    agent.start()
    try:
        assert gate.entered.wait(5)
        assert agent.refresh_now() is False                 # 不假裝 ready
        assert agent._terminal == 'unauthorized'
    finally:
        gate.release_old.set()
        gate.park.set()
        agent._stop.set()
        _join_poller(agent)


def test_malformed_job_response_wakes_status_waiters(make):
    agent, h = make([{'ok': True, 'job': 'not-a-dict'}])
    agent.status_changed.clear()
    assert agent._poll_once(0) == 'retry'
    assert agent.status_changed.is_set()


def test_refresh_now_still_refused_falls_back_to_terminal(make):
    agent, h = make([httpx.Response(401), httpx.Response(401)])
    agent.run()
    try:
        assert agent.refresh_now() is False
        assert agent.public_status()['reason'] == 'unauthorized'
        assert agent._thread is None or not agent._thread.is_alive()
    finally:
        agent.stop()
        _join_poller(agent)


def test_refresh_now_unsupported_does_nothing(make):
    agent, h = make([OK_NULL], supported=False)
    assert agent.refresh_now() is False
    assert h.requests == []
    assert agent.public_status()['state'] == 'unsupported'



# ---------------------------------------------------------------------------
# public_status 真值表
# ---------------------------------------------------------------------------
def _status(make, script, **kw):
    agent, _ = make(script, **kw)
    agent.run()
    return agent.public_status()


def test_status_proxy_unusable(make):
    st = _status(make, [OK_NULL], windows=make_windows(FakeImpl(), proxy_ok=False))
    assert (st['state'], st['reason']) == ('not_ready', 'proxy_unusable')


def test_status_unusable_proxy_spec_is_proxy_unusable(make):
    """代理規格套不上（socks5 帶帳密，usable=False）：即使視窗與 transport 都在，也不是「正在啟動」。"""
    spec = CfWindowProxy(server='socks5://192.168.1.250:1080', username='u', password='p', usable=False)
    st = _status(make, [OK_NULL], windows=make_windows(FakeImpl(sites=()), proxy_spec=spec))
    assert (st['state'], st['reason']) == ('not_ready', 'proxy_unusable')
    assert st['proxy_note'] is None
    assert 'socks5' not in repr(st) and '192.168' not in repr(st)


def test_status_no_windows(make):
    st = _status(make, [OK_NULL], windows=make_windows(FakeImpl(), jl=False, jt=False))
    assert (st['state'], st['reason']) == ('not_ready', 'no_windows')


def test_status_unreachable_while_retrying(make):
    st = _status(make, [httpx.ConnectError('down')])
    assert (st['state'], st['reason']) == ('not_ready', 'unreachable')


def test_status_starting_before_any_response(make):
    agent, _ = make([OK_NULL])
    assert agent.public_status()['reason'] == 'starting'


def test_status_starting_when_sites_empty(make):
    st = _status(make, [OK_NULL], windows=make_windows(FakeImpl(sites=())))
    assert (st['state'], st['reason'], st['sites']) == ('not_ready', 'starting', [])


def test_status_ready(make):
    st = _status(make, [OK_NULL])
    assert (st['state'], st['reason'], st['sites']) == ('ready', None, ['fc-javten', 'javlibrary'])




class FailingImpl(FakeImpl):
    """有 failed_sites() 的 transport（168e-T13 CD-4）。"""

    def __init__(self, sites=(), failed=()):
        super().__init__(sites=sites)
        self.failed = list(failed)

    def failed_sites(self):
        return list(self.failed)


def test_status_webview2_failed_when_no_site_usable_and_some_failed(make):
    st = _status(make, [OK_NULL], windows=make_windows(FailingImpl(sites=(), failed=('javlibrary', 'fc-javten'))))
    assert (st['state'], st['reason'], st['sites']) == ('not_ready', 'webview2_failed', [])


def test_status_webview2_failed_not_shown_when_one_site_is_usable(make):
    st = _status(make, [OK_NULL], windows=make_windows(FailingImpl(sites=('javlibrary',), failed=('fc-javten',))))
    assert (st['state'], st['reason'], st['sites']) == ('ready', None, ['javlibrary'])


def test_status_starting_when_nothing_failed_and_sites_empty(make):
    st = _status(make, [OK_NULL], windows=make_windows(FailingImpl(sites=(), failed=())))
    assert st['reason'] == 'starting'


def test_status_not_ready_until_server_confirms_current_sites(make):
    """子集判斷獨立場景：最近一次回應成功、視窗也已可用，但伺服器確認收下的 sites 還沒含該站 → 不是 ready。"""
    impl = FakeImpl(sites=())
    agent, _ = make([OK_NULL], windows=make_windows(impl))
    agent.run()                                   # 以空 sites 登記成功：_last_ok=True、_last_sent_sites=∅
    impl.sites = ['javlibrary']                   # 視窗之後才 confirm_ready
    st = agent.public_status()
    assert (st['state'], st['reason']) == ('not_ready', 'starting')


def test_status_proxy_note_variants(make):
    spec = CfWindowProxy(server='http://127.0.0.1:7890', username=None, password=None, usable=True)
    applied = _status(make, [OK_NULL], windows=make_windows(FakeImpl(), proxy_spec=spec))
    assert applied['proxy_note'] == 'applied'
    direct = _status(make, [OK_NULL], windows=make_windows(FakeImpl(), local_direct=True))
    assert direct['proxy_note'] == 'server_local_direct'
    mac = _status(make, [OK_NULL], shell='mac', windows=make_windows(FakeImpl(), proxy_spec=spec, local_direct=True))
    assert mac['proxy_note'] is None
    plain = _status(make, [OK_NULL])
    assert plain['proxy_note'] is None
    assert 'TOKEN' not in repr(applied) and '7890' not in repr(applied)


# ---------------------------------------------------------------------------
# runtime：真 socket、真 httpx、真輪詢緒、真 worker pool
# ---------------------------------------------------------------------------
class _Srv:
    def __init__(self):
        self.auth = []
        self.results = []
        self.got_result = threading.Event()
        self.sent_job = False
        self.lock = threading.Lock()


def _start_server(srv):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            with srv.lock:
                srv.auth.append(self.headers.get('Authorization'))
                reply = {'ok': True, 'job': None}
                if self.path == '/api/cf/shell/poll':
                    if body.get('hold', 0) > 0 and not srv.sent_job:
                        srv.sent_job = True
                        reply = {'ok': True, 'job': {'id': 'rs1', 'kind': 'fetch',
                                                     'args': {'url': JL + 'ja/?v=1', 'cache_key': 'javlibrary'}}}
                elif self.path == '/api/cf/shell/result':
                    srv.results.append(body)
                    srv.got_result.set()
                    reply = {'ok': True, 'accepted': True}
            data = json.dumps(reply).encode()
            if self.path == '/api/cf/shell/poll' and reply['job'] is None and body.get('hold', 0) > 0:
                threading.Event().wait(0.05)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.mark.parametrize('token,expected_auth', [('T', 'Bearer T'), (None, None)])
def test_real_socket_round_trip(token, expected_auth):
    srv = _Srv()
    httpd = _start_server(srv)
    impl = FakeImpl()
    agent = cf_shell.CfShellAgent(f'http://127.0.0.1:{httpd.server_address[1]}', token,
                                  make_windows(impl), shell='windows')
    try:
        assert agent.announce() is True
        agent.start()
        assert srv.got_result.wait(5), 'no result posted'
        assert srv.results == [{'id': 'rs1', 'ok': True, 'value': '<html>x</html>'}]
        assert [c[0] for c in impl.calls] == ['fetch']
        assert set(srv.auth) == {expected_auth}
        status = agent.public_status()
        print('public_status =', status)  # noqa: T201
        assert status['state'] == 'ready'
        thread = agent._thread
    finally:
        agent.stop()
        httpd.shutdown()
        httpd.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("server_remote,env_proxy_used", [(False, False), (True, False)])
def test_local_mode_client_ignores_proxy_env_vars(monkeypatch, server_remote, env_proxy_used):
    """client 路徑一律直連：不論 server_remote，都不吃 HTTP_PROXY 環境變數（168e E37，主機在區網）。"""
    monkeypatch.setenv('HTTP_PROXY', 'http://env-proxy.invalid:3128')
    monkeypatch.setenv('http_proxy', 'http://env-proxy.invalid:3128')
    monkeypatch.setenv('ALL_PROXY', 'http://env-proxy.invalid:3128')
    agent = cf_shell.CfShellAgent(ORIGIN, None, make_windows(FakeImpl()), shell='windows',
                                  server_remote=server_remote)
    client = agent._make_client()
    try:
        assert bool(client._mounts) is env_proxy_used
    finally:
        client.close()


def test_cf_shell_client_ignores_system_proxy(monkeypatch):
    """168e-T1 E37：環境代理壞掉（127.0.0.1:9）時，遠端模式的 poll 仍直連本機真 HTTP 假伺服器。"""
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.setenv(k, 'http://127.0.0.1:9')
    for k in ('NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(k, raising=False)
    httpd = _start_server(_Srv())
    agent = cf_shell.CfShellAgent(f'http://127.0.0.1:{httpd.server_address[1]}', 'T',
                                  make_windows(FakeImpl()), shell='windows', server_remote=True)
    try:
        assert agent._poll_once(0) == 'ok'
    finally:
        agent.stop()
        httpd.shutdown()
        httpd.server_close()
