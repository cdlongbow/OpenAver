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
ALL_REJECT_JOBS = LOOKALIKE_JOBS + MISMATCH_JOBS + MALFORMED_JOBS
NON_DICT_JOBS = ['garbage', None]


@pytest.mark.parametrize('j', PASS_JOBS)
def test_check_job_accepts_exact_origins(j):
    assert cf_shell.check_job(j) is True
    assert cf_shell.CfShellAgent.check_job(j) is True


@pytest.mark.parametrize('j', LOOKALIKE_JOBS)
def test_check_job_rejects_lookalike_hosts(j):
    assert cf_shell.check_job(j) is False


@pytest.mark.parametrize('j', MISMATCH_JOBS)
def test_check_job_rejects_key_origin_mismatch(j):
    assert cf_shell.check_job(j) is False


@pytest.mark.parametrize('j', MALFORMED_JOBS + NON_DICT_JOBS)
def test_check_job_rejects_malformed_jobs(j):
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
                          'server_remote': False, 'hold': cf_shell.HOLD_S}


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


def test_terminal_state_via_announce_blocks_start(make):
    agent, h = make([httpx.Response(404)])
    assert agent.announce() is False
    agent.start()
    assert agent._thread is None and len(h.requests) == 1
    assert agent.public_status()['reason'] == 'server_old'


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
                          'server_remote': True, 'hold': cf_shell.HOLD_S}


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


def test_unsupported_platform_makes_zero_requests(make):
    agent, h = make([OK_NULL], supported=False)
    assert agent.announce() is False
    agent.start()
    assert agent._thread is None and h.requests == []
    assert agent.public_status() == {'state': 'unsupported', 'reason': None, 'proxy_note': None, 'sites': []}


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


def test_status_recovers_to_ready_after_retry(make):
    st = _status(make, [httpx.ConnectError('down'), OK_NULL])
    assert st['state'] == 'ready'


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


@pytest.mark.parametrize("server_remote,env_proxy_used", [(False, False), (True, True)])
def test_local_mode_client_ignores_proxy_env_vars(monkeypatch, server_remote, env_proxy_used):
    """本機模式（打 127.0.0.1 的自己人）不吃 HTTP_PROXY 環境變數：免得環境代理把本機請求繞出去、AC-1 回歸。"""
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
