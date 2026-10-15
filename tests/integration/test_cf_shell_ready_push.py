"""168d-fix-T1 I-1：真 PyWebViewCfTransport＋真 CfShellAgent＋補送轉進真 TestClient 的 poll。

視窗狀態一變 → 伺服器端 broker.sites_for 變。長輪詢（hold>0）不轉進伺服器、卡在 release 上，
所以 sites_for 的變化只可能來自補送（hold=0）。等待一律用 Event（逾時＝失敗）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import types
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = str(REPO_ROOT / 'windows')
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

import cf_shell  # noqa: E402
from cf_transport_impl import PyWebViewCfTransport  # noqa: E402
from core import cf_handoff  # noqa: E402
from core.cf_transport import get_cf_transport, register_cf_transport  # noqa: E402
from web.app import app  # noqa: E402

TOKEN = 'shell-T'
KEY = 't:' + hashlib.sha256(TOKEN.encode('utf-8')).hexdigest()[:16]
JL = 'javlibrary'
JT = 'fc-javten'
WAIT_S = 5


class _Events:
    """pywebview 事件容器的最小替身：支援 `+=` 註冊與 fire()。"""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for h in self.handlers:
            h()


def _win():
    return types.SimpleNamespace(events=types.SimpleNamespace(closed=_Events()))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    broker = cf_handoff.Broker()
    monkeypatch.setattr(cf_handoff, '_broker', broker)
    monkeypatch.setattr('web.routers.cf_shell._POLL_INTERVAL_S', 0.01)
    prev = get_cf_transport()
    register_cf_transport(cf_handoff.transport())
    tok = cf_handoff.current_key.set(cf_handoff._UNSET)
    yield broker
    cf_handoff.current_key.reset(tok)
    register_cf_transport(prev)


class Rig:
    def __init__(self, broker, pending):
        self.broker = broker
        self.wins = {key: _win() for key in pending}
        self.transport = PyWebViewCfTransport(self.wins, {}, pending=set(pending))
        self.client = TestClient(app)
        self.release = threading.Event()
        self.pushed = threading.Event()
        self.push_bodies = []
        windows = types.SimpleNamespace(transport=self.transport, jl_win=object(), javten_win=object(),
                                        proxy_ok=True, proxy_spec=None, local_direct=False)
        self.agent = cf_shell.CfShellAgent(
            'http://shell-test.invalid:8765', TOKEN, windows, shell='mac',
            http_transport=httpx.MockTransport(self.handler))

    def handler(self, request):
        body = json.loads(request.content)
        if body['hold'] > 0:
            if not self.release.wait(WAIT_S):
                raise httpx.ConnectError('longpoll never released')
            return httpx.Response(200, json={'ok': True, 'job': None})
        resp = self.client.post(request.url.path, json=body,
                                headers={'Authorization': request.headers['Authorization']})
        self.push_bodies.append(body)
        self.pushed.set()
        return httpx.Response(resp.status_code, json=resp.json())

    def wait_push(self):
        assert self.pushed.wait(WAIT_S), 'no hold=0 push reached the server in time'
        self.pushed.clear()

    def sites(self):
        return self.broker.sites_for(KEY)


@pytest.fixture
def rig(_isolated):
    rigs = []

    def _rig(pending):
        r = Rig(_isolated, pending)
        rigs.append(r)
        assert r.agent.announce() is True          # 啟動 announce：伺服器端登記 sites=[]
        r.pushed.clear()
        r.push_bodies.clear()
        r.agent.start()
        return r
    yield _rig
    for r in rigs:
        r.agent._stop.set()
        r.release.set()
        r.agent._sync_wake.set()
        r.agent.stop()
        for th in (r.agent._thread, r.agent._sync_thread):
            if th is not None:
                th.join(timeout=WAIT_S)
                assert not th.is_alive(), 'daemon thread outlived the test'


def test_confirm_ready_pushes_site_to_server(rig):
    r = rig({JL})
    assert r.sites() == []                          # 補送前伺服器不含該站（且 key 確實已登記）
    assert r.broker.shell_info(KEY) is not None
    r.transport.confirm_ready(JL)
    r.wait_push()
    assert r.sites() == [JL]
    assert r.push_bodies[-1]['preparing'] == []


def test_closed_window_is_removed_from_server_sites(rig):
    r = rig({JL})
    r.transport.confirm_ready(JL)
    r.wait_push()
    assert r.sites() == [JL]
    r.wins[JL].events.closed.fire()
    r.wait_push()
    assert r.sites() == []
