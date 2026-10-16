"""168d-fix-T2：可用性單一來源。SSR（window.__ADVANCED_SEARCH__ 三欄）與 GET /api/cf/availability
由同一個函式產生，每格同時斷言預期值與兩邊相等；端點不得派工給殼（CD-4）。"""
from __future__ import annotations

import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from core import cf_handoff
from core.cf_transport import get_cf_transport, register_cf_transport
from web.app import app

POLL = "/api/cf/shell/poll"
AVAIL = "/api/cf/availability"
REMOTE_CLIENT = ("192.168.1.50", 12345)


def _bearer(ticket: str) -> dict:
    return {"Authorization": f"Bearer {ticket}"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    broker = cf_handoff.Broker()
    monkeypatch.setattr(cf_handoff, "_broker", broker)
    monkeypatch.setitem(cf_handoff.TIMEOUTS, "is_ready", (1, 1))
    prev = get_cf_transport()
    register_cf_transport(cf_handoff.transport())
    tok = cf_handoff.current_key.set(cf_handoff._UNSET)
    yield broker
    cf_handoff.current_key.reset(tok)
    register_cf_transport(prev)


@pytest.fixture(autouse=True)
def _reset_access_auth_state():
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


@pytest.fixture
def broker(_isolated):
    return _isolated


def _poll(client, headers=None, sites=("javlibrary",), preparing=()):
    body = {"shell": "windows", "sites": list(sites), "preparing": list(preparing),
            "applied_proxy": None, "server_remote": False, "hold": 0}
    return client.post(POLL, json=body, headers=headers or {})


def _ssr(html: str) -> dict:
    avail = re.search(r"cf_transport_available:\s*(true|false)", html)
    sites = re.search(r"cf_sites:\s*(\[[^\]]*\]|null)", html)
    prep = re.search(r"cf_preparing:\s*(\[[^\]]*\]|null)", html)
    assert avail and sites and prep, "bootstrap 缺 cf_transport_available／cf_sites／cf_preparing"
    return {"available": json.loads(avail.group(1)), "sites": json.loads(sites.group(1)),
            "preparing": json.loads(prep.group(1))}


def _both(make_client, query="", headers=None):
    """同一組條件（client／header／query）各打 SSR 與端點一次。"""
    ssr = _ssr(make_client().get("/search" + query, headers=headers or {}).text)
    ep = make_client().get(AVAIL + query, headers=headers or {})
    assert ep.status_code == 200
    return ssr, ep.json()


def test_loopback_without_oa_shell_is_lit_ssr_equals_endpoint(temp_config_path, broker):
    _poll(TestClient(app))
    ssr, ep = _both(lambda: TestClient(app))
    assert ssr == ep == {"available": True, "sites": ["javlibrary"], "preparing": []}


def test_ip_key_without_oa_shell_is_dark_ssr_equals_endpoint(temp_config_path, broker, monkeypatch):
    from core.config import load_config as _real_load
    monkeypatch.setattr("web.app.load_config", lambda: _real_load() | {
        "general": {**_real_load().get("general", {}), "server_mode": True}})
    monkeypatch.setattr(access_auth, "_snapshot", access_auth.AuthSnapshot(
        enabled=False, pin="", valid_tokens=frozenset(), agent_token=None))
    _poll(TestClient(app, client=REMOTE_CLIENT))
    assert broker.sites_for("ip:192.168.1.50") == ["javlibrary"]
    ssr, ep = _both(lambda: TestClient(app, client=REMOTE_CLIENT))
    assert ssr == ep == {"available": False, "sites": [], "preparing": []}


def test_ip_key_with_oa_shell_is_lit_ssr_equals_endpoint(temp_config_path, broker, monkeypatch):
    from core.config import load_config as _real_load
    monkeypatch.setattr("web.app.load_config", lambda: _real_load() | {
        "general": {**_real_load().get("general", {}), "server_mode": True}})
    monkeypatch.setattr(access_auth, "_snapshot", access_auth.AuthSnapshot(
        enabled=False, pin="", valid_tokens=frozenset(), agent_token=None))
    _poll(TestClient(app, client=REMOTE_CLIENT))
    ssr, ep = _both(lambda: TestClient(app, client=REMOTE_CLIENT), query="?oa_shell=windows")
    assert ssr == ep == {"available": True, "sites": ["javlibrary"], "preparing": []}


def test_preparing_site_ssr_equals_endpoint(temp_config_path, broker):
    _poll(TestClient(app), sites=["javlibrary"], preparing=["fc-javten", "evil-site"])
    ssr, ep = _both(lambda: TestClient(app))
    assert ssr == ep == {"available": True, "sites": ["javlibrary"], "preparing": ["fc-javten"]}


def test_unavailable_forces_empty_preparing(temp_config_path, broker):
    """沒殼登記 → available=false，preparing 一律 []（對照格：上一格登記後同形狀回有值）。"""
    ssr, ep = _both(lambda: TestClient(app))
    assert ssr == ep == {"available": False, "sites": [], "preparing": []}


def test_availability_endpoint_dispatches_no_job(temp_config_path, broker, monkeypatch):
    _poll(TestClient(app))
    calls = []
    orig = cf_handoff.Broker._enqueue

    def _counting(self, key, kind, args):
        calls.append((key, kind))
        return orig(self, key, kind, args)
    monkeypatch.setattr(cf_handoff.Broker, "_enqueue", _counting)
    r = TestClient(app).get(AVAIL)
    assert r.status_code == 200
    assert r.json()["available"] is True
    assert calls == []


def _in_shell(html: str) -> bool:
    m = re.search(r"in_shell:\s*(true|false)", html)
    assert m, "bootstrap 缺 in_shell"
    return m.group(1) == "true"


@pytest.mark.parametrize("path", ["/search", "/showcase"])
@pytest.mark.parametrize("query,expected", [
    ("?oa_mode=client", True),
    ("?oa_mode=local", True),
    ("", False),
    ("?oa_mode=bogus", False),
])
def test_in_shell_follows_oa_mode(temp_config_path, path, query, expected):
    html = TestClient(app).get(path + query).text
    assert _in_shell(html) is expected
