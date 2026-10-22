"""168d-fix-T1：殼端「視窗一就緒立刻補報」——補送緒、_last_sent_sites、preparing、補送失敗不碰 liveness。

時序一律用 Event／Semaphore 等待（有逾時，逾時＝測試失敗），不 sleep 實時間。
長輪詢（hold>0）由 Semaphore 閘控；補送（hold=0）由逐筆 Event 閘控。
"""
from __future__ import annotations

import json
import sys
import threading
import types
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = str(REPO_ROOT / 'windows')
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

import cf_shell  # noqa: E402

ORIGIN = 'http://shell-test.invalid:8765'
OK_NULL = {'ok': True, 'job': None}
JL = 'javlibrary'
JT = 'fc-javten'
WAIT_S = 5


class FakeTransport:
    def __init__(self, sites=(), preparing=()):
        self.sites = list(sites)
        self.preparing = list(preparing)
        self.listener = None

    def available_sites(self):
        return list(self.sites)

    def preparing_sites(self):
        return list(self.preparing)

    def set_change_listener(self, cb):
        self.listener = cb

    def change(self):
        self.listener()


class Net:
    """hold>0：等 lp_permits 才回 OK_NULL；hold==0：第 n 筆等 sync_gates[n]（沒登記＝立刻回）。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.lp_arrived = threading.Semaphore(0)
        self.lp_permits = threading.Semaphore(0)
        self.sync_arrived = threading.Semaphore(0)
        self.sync_bodies = []
        self.lp_bodies = []
        self.sync_gates = {}
        self.sync_script = {}       # n -> Exception | httpx.Response
        self.calls = 0

    def handler(self, request):
        body = json.loads(request.content or b'{}')
        with self.lock:
            self.calls += 1
            if self.calls > 60:
                raise AssertionError('handler called too many times')
        if request.url.path != cf_shell.POLL_PATH:
            return httpx.Response(200, json={'ok': True, 'accepted': True})
        if body['hold'] > 0:
            self.lp_bodies.append(body)
            self.lp_arrived.release()
            if not self.lp_permits.acquire(timeout=WAIT_S):
                raise httpx.ConnectError('longpoll never released')
            return httpx.Response(200, json=OK_NULL)
        with self.lock:
            n = len(self.sync_bodies)
            self.sync_bodies.append(body)
        self.sync_arrived.release()
        gate = self.sync_gates.get(n)
        if gate is not None and not gate.wait(WAIT_S):
            raise httpx.ConnectError('sync never released')
        item = self.sync_script.get(n)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=OK_NULL)


def _windows(transport):
    return types.SimpleNamespace(transport=transport, jl_win=object(), javten_win=object(),
                                 proxy_ok=True, proxy_spec=None, local_direct=False)


@pytest.fixture
def mk(monkeypatch):
    agents = []
    nets = []

    def _mk(transport):
        net = Net()
        monkeypatch.setattr(cf_shell, '_sleep', lambda s: None)
        agent = cf_shell.CfShellAgent(ORIGIN, None, _windows(transport), shell='mac',
                                      http_transport=httpx.MockTransport(net.handler))
        agents.append(agent)
        nets.append(net)
        return agent, net
    yield _mk
    for agent, net in zip(agents, nets, strict=True):
        agent._stop.set()
        agent._sync_wake.set()
        for _ in range(10):
            net.lp_permits.release()
        for g in net.sync_gates.values():
            g.set()
        for th in (agent._thread, agent._sync_thread):
            if th is not None:
                th.join(timeout=WAIT_S)
                assert not th.is_alive(), 'daemon thread outlived the test'


# ---------------------------------------------------------------------------
def test_poll_body_carries_preparing_sites(mk):
    agent, net = mk(FakeTransport(sites=[JL], preparing=[JT]))
    assert agent.announce() is True
    assert net.sync_bodies[0]['preparing'] == [JT]
    assert net.sync_bodies[0]['sites'] == [JL]


def test_status_starting_until_server_knows_sites(mk):
    t = FakeTransport(sites=[JL])
    agent, net = mk(t)
    assert agent.announce() is True
    agent._last_ok = True
    assert agent.public_status()['state'] == 'ready'
    t.sites = [JL, JT]                       # 視窗新就緒，伺服器還不知道
    st = agent.public_status()
    assert (st['state'], st['reason']) == ('not_ready', 'starting')
    agent._sync_once()                       # 補送成功
    assert agent.public_status()['state'] == 'ready'


