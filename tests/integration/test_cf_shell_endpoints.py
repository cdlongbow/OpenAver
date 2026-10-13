"""TASK-168d-T2：殼身分 middleware、/api/cf/shell/{poll,result}、SSR 窄化、config 兩處 or。

隔離（BE-TEST-45）：web.app import 時註冊的 transport 會被 test_cf_transport_registry 的
autouse fixture 清掉，所以本檔不依賴 import 時註冊——autouse fixture 自己換 broker、
註冊 transport、歸零 current_key，結尾還原。
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from core import cf_handoff
from core.cf_transport import CfTransportUnavailable, get_cf_transport, register_cf_transport
from web.app import app

POLL = "/api/cf/shell/poll"
RESULT = "/api/cf/shell/result"
REMOTE_CLIENT = ("192.168.1.50", 12345)


def _t(ticket: str) -> str:
    return "t:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]


def _bearer(ticket: str) -> dict:
    return {"Authorization": f"Bearer {ticket}"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    broker = cf_handoff.Broker()
    monkeypatch.setattr(cf_handoff, "_broker", broker)
    monkeypatch.setitem(cf_handoff.TIMEOUTS, "is_ready", (3, 3))
    monkeypatch.setattr("web.routers.cf_shell._POLL_INTERVAL_S", 0.01)
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


def _poll(client, headers=None, hold=0, sites=("javlibrary",), **extra):
    body = {"shell": "windows", "sites": list(sites), "applied_proxy": None, "server_remote": False, "hold": hold}
    body.update(extra)
    return client.post(POLL, json=body, headers=headers or {})


def _result(client, job_id, headers=None, ok=True, value=True, **extra):
    body = {"id": job_id, "ok": ok, "value": value}
    body.update(extra)
    return client.post(RESULT, json=body, headers=headers or {})


def _run_in_thread(fn):
    holder: dict = {}

    def _target():
        try:
            holder["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — 測試緒把例外帶回主緒
            holder["error"] = e

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    return th, holder


def _wait_for_job(broker, timeout=2.0):
    """等 submit 緒把 job 排進佇列，回傳 job id。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with broker._lock:
            ids = list(broker._jobs)
        if ids:
            return ids[0]
        time.sleep(0.005)
    raise AssertionError("job never enqueued")


# ---------------- poll ----------------

def test_poll_hold_zero_registers_and_never_claims(client, broker):
    r = _poll(client, sites=["javlibrary", "evil-site"])
    assert r.status_code == 200
    assert r.json() == {"ok": True, "job": None}
    info = broker.shell_info("loopback")
    assert info is not None
    assert info["sites"] == ["javlibrary"]  # 只收 CF_SITE_ORIGINS 的鍵

    # 先排一個 job，hold=0 的 poll 不得領走它
    th, holder = _run_in_thread(lambda: broker.submit("loopback", "is_ready", {"cache_key": "javlibrary"}))
    job_id = _wait_for_job(broker)
    r0 = _poll(client, hold=0)
    assert r0.json()["job"] is None
    # 他 key 的 poll 領不到
    other = _poll(client, headers=_bearer("someone-else"), hold=1)
    assert other.json()["job"] is None
    # 同 key hold>0 領得到的正是原本那個
    r1 = _poll(client, hold=2)
    job = r1.json()["job"]
    assert job["id"] == job_id and job["kind"] == "is_ready"
    assert job["args"] == {"cache_key": "javlibrary"}
    assert _result(client, job_id).json() == {"ok": True, "accepted": True}
    th.join(3)
    assert holder.get("value") is True


@pytest.mark.parametrize("hold", [-1, 21])
def test_poll_hold_out_of_range_is_422(client, hold):
    assert _poll(client, hold=hold).status_code == 422


@pytest.mark.parametrize("hdr", [{"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}])
def test_poll_rejects_browser_origin_header(client, broker, hdr):
    r = _poll(client, headers=hdr)
    assert r.status_code == 403
    assert broker.shells == {}
    # 對照格：同一個端點、不帶標頭、不同身分 → 200 且確實登記（BE-TEST-11）
    ok = _poll(client, headers=_bearer("plain-shell"))
    assert ok.status_code == 200
    assert list(broker.shells) == [_t("plain-shell")]


@pytest.mark.parametrize("hdr", [{"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "same-origin"}])
def test_result_rejects_browser_headers_and_keeps_job(client, broker, hdr):
    broker.register_shell("loopback", ["javlibrary"])
    th, holder = _run_in_thread(lambda: broker.submit("loopback", "is_ready", {"cache_key": "javlibrary"}))
    job_id = _wait_for_job(broker)
    assert broker.claim("loopback")["id"] == job_id
    r = _result(client, job_id, headers=hdr)
    assert r.status_code == 403
    assert broker._jobs[job_id].state == "claimed"  # 狀態不變
    assert th.is_alive()
    # 對照格：不帶標頭才會被接受
    assert _result(client, job_id).json() == {"ok": True, "accepted": True}
    th.join(3)
    assert holder.get("value") is True


# ---------------- result ----------------

def test_result_from_other_shell_rejected_job_not_woken(client, broker):
    ta, tb = "ticket-A", "ticket-B"
    assert _poll(client, headers=_bearer(ta)).status_code == 200
    assert _poll(client, headers=_bearer(tb)).status_code == 200
    assert {_t(ta), _t(tb)} == set(broker.shells)

    th, holder = _run_in_thread(
        lambda: TestClient(app).get("/api/cf/status", params={"key": "javlibrary"}, headers=_bearer(ta)).json()
    )
    job = _poll(client, headers=_bearer(ta), hold=2).json()["job"]
    assert job is not None and job["kind"] == "is_ready"

    # B 殼拿 A 的 job id 回報 → 被拒，A 的等待者不被喚醒
    rb = _result(client, job["id"], headers=_bearer(tb), value=True)
    assert rb.status_code == 200
    assert rb.json() == {"ok": True, "accepted": False}
    time.sleep(0.2)
    assert th.is_alive(), "A 的請求被 B 的回報喚醒了"
    assert "value" not in holder

    ra = _result(client, job["id"], headers=_bearer(ta), value=True)
    assert ra.json() == {"ok": True, "accepted": True}
    th.join(3)
    assert holder["value"] == {"ready": True}


def test_result_unknown_or_unclaimed_job_not_accepted(client, broker):
    broker.register_shell("loopback", ["javlibrary"])
    assert _result(client, "nope-1").json() == {"ok": True, "accepted": False}
    th, holder = _run_in_thread(lambda: broker.submit("loopback", "is_ready", {"cache_key": "javlibrary"}))
    job_id = _wait_for_job(broker)
    # 還在 queued（沒被領走）→ 不接受
    assert _result(client, job_id).json() == {"ok": True, "accepted": False}
    assert broker.claim("loopback")["id"] == job_id
    assert _result(client, job_id, ok=False, error="challenge", message="cf").json()["accepted"] is True
    th.join(3)
    assert isinstance(holder.get("error"), Exception)
    assert type(holder["error"]).__name__ == "CfChallengeRequired"


def test_result_bad_error_code_is_422(client):
    r = client.post(RESULT, json={"id": "x", "ok": False, "error": "weird"})
    assert r.status_code == 422


# ---------------- 身分在執行緒上的可見性 ----------------

def test_sync_route_job_reaches_requesting_shell(client, broker):
    assert _poll(client).status_code == 200  # 登記 loopback 殼
    stop = threading.Event()
    seen: list = []

    def shell():
        deadline = time.monotonic() + 3
        while not stop.is_set() and time.monotonic() < deadline:
            job = cf_handoff.get_broker().claim("loopback")
            if job is None:
                time.sleep(0.005)
                continue
            seen.append(job)
            cf_handoff.get_broker().complete("loopback", job["id"], True, value=True)
            return

    th = threading.Thread(target=shell, daemon=True)
    th.start()
    r = client.get("/api/cf/status", params={"key": "javlibrary"})
    stop.set()
    th.join(3)
    assert r.json() == {"ready": True}
    assert seen and seen[0]["kind"] == "is_ready"


def test_executor_thread_inside_route_is_fail_closed(client, broker, monkeypatch):
    """同一路由內另開 ThreadPoolExecutor 呼叫 transport：context 不跟過去 → _UNSET → 不可用。"""
    assert _poll(client).status_code == 200
    real = cf_handoff.transport()
    captured: list = []

    class _Wrapper:
        def is_ready(self, cache_key):
            with ThreadPoolExecutor(1) as ex:
                fut = ex.submit(real.is_ready, cache_key)
                try:
                    return fut.result(5)
                except BaseException as e:  # noqa: BLE001
                    captured.append(e)
                    raise

    monkeypatch.setattr("web.routers.cf.get_cf_transport", lambda: _Wrapper())
    r = client.get("/api/cf/status", params={"key": "javlibrary"})
    assert r.json() == {"ready": False, "unavailable": True}
    assert len(captured) == 1 and isinstance(captured[0], CfTransportUnavailable)
    # 沒有任何 job 被排進佇列（_require_key 在 enqueue 之前就擋掉）
    assert broker._jobs == {}


# ---------------- LAN 閘／PIN 閘：poll 不登記 ----------------

def test_poll_blocked_by_lan_gate_does_not_register(monkeypatch, broker):
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": False}})
    r = _poll(TestClient(app, client=REMOTE_CLIENT))
    assert r.status_code == 403
    assert broker.shells == {}


def test_poll_blocked_by_pin_gate_does_not_register(tmp_path, monkeypatch, broker):
    db_path = tmp_path / "cf_shell.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, "1234")
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": True}})
    r = _poll(TestClient(app, client=REMOTE_CLIENT))
    assert r.status_code != 200 or '"ok"' not in r.text
    assert broker.shells == {}


# ---------------- SSR 窄化 ----------------

def _ssr(html: str):
    avail = re.search(r"cf_transport_available:\s*(true|false)", html)
    sites = re.search(r"cf_sites:\s*(\[[^\]]*\])", html)
    assert avail and sites, "bootstrap 缺 cf_transport_available／cf_sites"
    return avail.group(1), sites.group(1)


def test_ssr_registered_shell_with_oa_shell_is_lit(temp_config_path, broker):
    boot = TestClient(app)
    _poll(boot, headers=_bearer("shell-T"))
    html = TestClient(app).get("/search?oa_shell=windows", headers=_bearer("shell-T")).text
    assert _ssr(html) == ("true", '["javlibrary"]')


def test_ssr_registered_shell_without_oa_shell_stays_dark(temp_config_path, broker):
    boot = TestClient(app)
    _poll(boot, headers=_bearer("shell-T"))
    assert broker.sites_for(_t("shell-T")) == ["javlibrary"]
    html = TestClient(app).get("/search", headers=_bearer("shell-T")).text
    assert _ssr(html) == ("false", "[]")


def test_ssr_unregistered_shell_is_dark_even_with_oa_shell(temp_config_path, broker):
    html = TestClient(app).get("/search?oa_shell=windows", headers=_bearer("never-registered")).text
    assert _ssr(html) == ("false", "[]")


def test_ssr_loopback_local_shell_is_lit_but_other_identity_is_dark(temp_config_path, broker):
    _poll(TestClient(app))  # 無票據 → loopback
    lit = TestClient(app).get("/search?oa_shell=windows").text
    assert _ssr(lit) == ("true", '["javlibrary"]')
    # 同機但帶了別的票據 → 身分不同 → 灰
    dark = TestClient(app).get("/search?oa_shell=windows", headers=_bearer("other")).text
    assert _ssr(dark) == ("false", "[]")


# ---------------- config 兩處 or ----------------

@pytest.mark.parametrize("patched,expected", [(True, True), (False, False)])
def test_config_get_and_put_restart_needed_or(client, temp_config_path, monkeypatch, patched, expected):
    monkeypatch.setattr("web.routers.config.cf_window_proxy_restart_needed", lambda: False)
    monkeypatch.setattr("web.routers.config.cf_handoff.restart_needed_here", lambda settings: patched)
    got = client.get("/api/config").json()
    assert got["cf_window_proxy_restart_needed"] is expected
    put = client.put("/api/config", json=got["data"]).json()
    assert put["success"] is True
    assert put["cf_window_proxy_restart_needed"] is expected


def test_config_old_function_true_still_wins(client, temp_config_path, monkeypatch):
    monkeypatch.setattr("web.routers.config.cf_window_proxy_restart_needed", lambda: True)
    monkeypatch.setattr("web.routers.config.cf_handoff.restart_needed_here", lambda settings: False)
    assert client.get("/api/config").json()["cf_window_proxy_restart_needed"] is True
