"""core/client_connect.py 單元測試（168b-T1）。httpx.MockTransport，不開真 socket。"""
import json

import httpx
import pytest

from core import client_connect, client_settings

URL = "http://192.168.1.190:8765"
HELLO = {"success": True, "app": "openaver", "version": "0.17.7", "kind": "synology",
         "auth_required": True, "authed": False}


def _install(monkeypatch, handler):
    calls = []

    def _h(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(client_connect, "_new_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(_h), timeout=httpx.Timeout(3.0)))
    return calls


@pytest.fixture(autouse=True)
def _local_version(monkeypatch):
    monkeypatch.setattr(client_connect, "LOCAL_VERSION", "0.17.7")


@pytest.mark.parametrize("local,server,status,hint", [
    ("0.17.10", "0.17.7", "server_old", "upgrade_server"),
    ("0.17.10", "0.17.9", "server_old", "upgrade_server"),
    ("0.17.10", "0.17.10", "ok", ""),
    ("0.17.10", "0.17.12", "patch_diff", ""),
    ("0.17.10", "0.18.0", "client_old", "upgrade_client"),
    ("0.17.10", "1.0.0", "client_old", "upgrade_client"),
    ("0.17.10", "0.16.9", "server_old", "upgrade_server"),
    ("0.17.10", "0.17.10-rc1", "ok", ""),
    ("0.17.10", "", "unparseable", ""),
    ("0.17.10", "abc", "unparseable", ""),
    ("abc", "0.17.10", "unparseable", ""),
])
def test_check_compat_truth_table(monkeypatch, local, server, status, hint):
    monkeypatch.setattr(client_settings, "MIN_SERVER_VERSION", (0, 17, 10))
    c = client_connect.check_compat(local, server)
    assert (c.status, c.hint) == (status, hint)
    assert client_connect.is_connectable(c) == (status in ("ok", "patch_diff"))


def test_probe_ok_and_bearer(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(200, json={**HELLO, "authed": True})

    _install(monkeypatch, handler)
    r = client_connect.probe(URL, token="TKN")
    assert seen == ["Bearer TKN"]
    assert r["ok"] is True and r["reason"] is None
    assert (r["version"], r["kind"], r["auth_required"], r["authed"]) == ("0.17.7", "synology", True, True)
    assert r["compat"].status == "ok"
    client_connect.probe(URL)
    assert seen[-1] is None


@pytest.mark.parametrize("exc,reason", [
    (httpx.ConnectTimeout("x"), "timeout"),
    (httpx.ReadTimeout("x"), "timeout"),
    (httpx.ConnectError("x"), "unreachable"),
])
def test_probe_exception_reasons_no_health_retry(monkeypatch, exc, reason):
    def handler(req):
        raise exc

    calls = _install(monkeypatch, handler)
    r = client_connect.probe(URL)
    assert (r["ok"], r["reason"]) == (False, reason)
    assert len(calls) == 1  # 連線錯誤不試 /api/health


def test_probe_tls(monkeypatch):
    import ssl

    def handler(req):
        err = httpx.ConnectError("x")
        err.__cause__ = ssl.SSLError("bad cert")
        raise err

    _install(monkeypatch, handler)
    assert client_connect.probe("https://nas.local")["reason"] == "tls"


def test_probe_lan_forbidden(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(403, text="Forbidden"))
    r = client_connect.probe(URL)
    assert (r["ok"], r["reason"]) == (False, "lan_forbidden")


def test_probe_not_openaver(monkeypatch):
    def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(404, text="nope")
        return httpx.Response(200, text="<html>router</html>")

    calls = _install(monkeypatch, handler)
    r = client_connect.probe(URL)
    assert (r["ok"], r["reason"]) == (False, "not_openaver")
    assert [c.url.path for c in calls] == ["/api/client/hello", "/api/health"]


def test_probe_old_server_without_hello_is_server_old(monkeypatch):
    def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": "0.16.2"})
        return httpx.Response(404, json={"detail": "Not Found"})

    _install(monkeypatch, handler)
    r = client_connect.probe(URL)
    assert r["ok"] is False and r["reason"] is None
    assert r["version"] == "0.16.2"
    assert r["compat"].status == "server_old" and r["compat"].hint == "upgrade_server"


@pytest.mark.parametrize("legacy", ["0.17.7", "0.17.9", "0.18.0"])
def test_probe_health_fallback_always_server_old(monkeypatch, legacy):
    # 沒有 hello 的伺服器：即使 health 版本等於本機／MIN，也固定 server_old＋升級伺服器提示
    def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": legacy})
        return httpx.Response(404, json={})

    _install(monkeypatch, handler)
    r = client_connect.probe(URL)
    assert r["compat"] == client_connect.Compat("server_old", "upgrade_server")


def test_probe_invalid_url(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=HELLO))
    r = client_connect.probe("ftp://x")
    assert (r["ok"], r["reason"]) == (False, "unreachable")
    assert calls == []


def test_new_client_timeout_all_three_seconds():
    c = client_connect._new_client()
    try:
        t = c.timeout
        assert (t.connect, t.read, t.write, t.pool) == (3.0, 3.0, 3.0, 3.0)
    finally:
        c.close()


def test_login_results(monkeypatch):
    def handler(req):
        body = json.loads(req.content)
        if body["pin"] == "1234":
            return httpx.Response(200, json={"success": True, "token": "TKN-SENTINEL-9"})
        return httpx.Response(401, json={"success": False, "reason": "bad_pin"})

    _install(monkeypatch, handler)
    assert client_connect.login(URL, "1234") == {"ok": True, "reason": None, "token": "TKN-SENTINEL-9"}
    r = client_connect.login(URL, "0000")
    assert (r["ok"], r["reason"]) == (False, "bad_pin") and not r.get("token")


def test_login_no_pin_required_and_errors(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(200, json={"success": True, "token": None, "auth_required": False}))
    r = client_connect.login(URL, "")
    assert r["ok"] is True and r["token"] is None

    def boom(req):
        raise httpx.ConnectTimeout("x")

    _install(monkeypatch, boom)
    assert client_connect.login(URL, "1")["reason"] == "timeout"


def test_fetch_sources(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(200, json={"success": True, "sources": [{"path": "/v", "kind": "directory"}]})

    _install(monkeypatch, handler)
    r = client_connect.fetch_sources(URL, "TKN")
    assert seen == ["Bearer TKN"]
    assert r["ok"] is True and r["sources"] == [{"path": "/v", "kind": "directory"}]
    _install(monkeypatch, lambda req: httpx.Response(401, json={}))
    assert client_connect.fetch_sources(URL, "TKN")["ok"] is False


def _preflight(monkeypatch, handler, token="TKN"):
    calls = _install(monkeypatch, handler)
    return client_connect.preflight(URL, token), calls


@pytest.mark.parametrize("auth_required,authed,token,status,reason", [
    (True, True, "TKN", "ok", None),
    (True, False, "TKN", "offline", "relogin"),
    (True, False, "", "offline", "relogin"),
    (False, False, "", "ok", None),
    (False, True, "TKN", "ok", None),
])
def test_preflight_auth_matrix(monkeypatch, auth_required, authed, token, status, reason):
    body = {**HELLO, "auth_required": auth_required, "authed": authed}
    p, calls = _preflight(monkeypatch, lambda req: httpx.Response(200, json=body), token=token)
    assert (p.status, p.reason) == (status, reason)
    assert len(calls) <= 2
    assert all(c.url.path == "/api/client/hello" for c in calls)  # 不碰 token／sources 端點


@pytest.mark.parametrize("exc,reason", [
    (httpx.ConnectTimeout("x"), "unreachable"),
    (httpx.ReadTimeout("x"), "unreachable"),
    (httpx.ConnectError("x"), "unreachable"),
])
def test_preflight_black_hole_budget(monkeypatch, exc, reason):
    def handler(req):
        raise exc

    p, calls = _preflight(monkeypatch, handler)
    assert (p.status, p.reason) == ("offline", reason)
    assert len(calls) <= 2


def test_preflight_other_offline_reasons(monkeypatch):
    p, _ = _preflight(monkeypatch, lambda req: httpx.Response(403, text="Forbidden"))
    assert p.reason == "lan_forbidden"
    p, _ = _preflight(monkeypatch, lambda req: httpx.Response(200, text="<html/>") if req.url.path != "/api/health" else httpx.Response(404))
    assert p.reason == "incompatible"
    p, _ = _preflight(monkeypatch, lambda req: httpx.Response(200, json={**HELLO, "version": "0.18.0"}))
    assert (p.status, p.reason) == ("offline", "incompatible")
    p, _ = _preflight(monkeypatch, lambda req: httpx.Response(200, json={**HELLO, "version": "0.17.9", "authed": True}))
    assert p.status == "ok"  # patch_diff 仍可連


def test_secrets_never_logged(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)

    def handler(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"success": True, "token": "TKN-SENTINEL-9"})
        return httpx.Response(200, json={**HELLO, "authed": True})

    _install(monkeypatch, handler)
    client_connect.login(URL, "PIN-SENTINEL-1")
    client_connect.preflight(URL, "TKN-SENTINEL-9")
    client_connect.probe(URL, "TKN-SENTINEL-9")
    assert "TKN-SENTINEL-9" not in caplog.text and "PIN-SENTINEL-1" not in caplog.text


# ───────────────────────── 168c-T1：fetch_video_extensions ─────────────────────────

def _cfg_resp(exts):
    return httpx.Response(200, json={"success": True, "data": {"scraper": {"video_extensions": exts}}})


def test_fetch_video_extensions_ok_sorted_normalized_with_bearer(monkeypatch):
    calls = _install(monkeypatch, lambda req: _cfg_resp(["MP4", "mkv", ".avi"]))
    r = client_connect.fetch_video_extensions(URL, "TKN")
    assert r == {"ok": True, "reason": None, "extensions": [".avi", ".mkv", ".mp4"]}
    assert calls[0].url.path == "/api/config"
    assert calls[0].headers["authorization"] == "Bearer TKN"


def _timeout(req):
    raise httpx.ReadTimeout("t")


def _refuse(req):
    raise httpx.ConnectError("c")


@pytest.mark.parametrize("handler,reason", [
    (_timeout, "timeout"),
    (_refuse, "unreachable"),
    (lambda req: httpx.Response(401, json={"success": False}), "unauthorized"),
    (lambda req: httpx.Response(403, json={"success": False}), "unauthorized"),
    (lambda req: httpx.Response(500, json={}), "bad_response"),
    (lambda req: httpx.Response(200, content=b"nope"), "bad_response"),
    (lambda req: httpx.Response(200, json={"success": True}), "bad_response"),
    (lambda req: httpx.Response(200, json={"success": True, "data": {"scraper": {}}}), "bad_response"),
    (lambda req: _cfg_resp([]), "bad_response"),
    (lambda req: _cfg_resp(None), "bad_response"),
    (lambda req: _cfg_resp([".mp4", 5]), "bad_response"),
    (lambda req: httpx.Response(200, json={"data": [1]}), "bad_response"),
    (lambda req: httpx.Response(200, json={"data": "oops"}), "bad_response"),
    (lambda req: httpx.Response(200, json={"data": {"scraper": [1]}}), "bad_response"),
])
def test_fetch_video_extensions_failures_keep_ok_false(monkeypatch, handler, reason):
    _install(monkeypatch, handler)
    r = client_connect.fetch_video_extensions(URL, "TKN")
    assert r == {"ok": False, "reason": reason, "extensions": []}


