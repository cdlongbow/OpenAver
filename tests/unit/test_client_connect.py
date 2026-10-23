"""core/client_connect.py 單元測試（168b-T1）。httpx.MockTransport；僅 I-6 直連格開本機真 socket。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                        lambda timeout=3.0: httpx.Client(transport=httpx.MockTransport(_h),
                                                         timeout=httpx.Timeout(timeout)))
    return calls


@pytest.fixture(autouse=True)
def _local_version(monkeypatch):
    monkeypatch.setattr(client_connect, "LOCAL_VERSION", "0.17.7")


@pytest.mark.parametrize("local,server,status,hint", [
    ("0.17.10", "0.17.7", "server_old", "upgrade_server"),
    ("0.17.10", "0.17.10", "ok", ""),
    ("0.17.10", "0.18.0", "client_old", "upgrade_client"),
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
    (False, False, "", "ok", None),
])
def test_preflight_auth_matrix(monkeypatch, auth_required, authed, token, status, reason):
    body = {**HELLO, "auth_required": auth_required, "authed": authed}
    p, calls = _preflight(monkeypatch, lambda req: httpx.Response(200, json=body), token=token)
    assert (p.status, p.reason) == (status, reason)
    assert len(calls) <= 2
    assert all(c.url.path == "/api/client/hello" for c in calls)  # 不碰 token／sources 端點


@pytest.mark.parametrize("exc,reason", [
    (httpx.ConnectTimeout("x"), "unreachable"),
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


@pytest.mark.parametrize("handler,reason", [
    (_timeout, "timeout"),
    (lambda req: httpx.Response(500, json={}), "bad_response"),
])
def test_fetch_video_extensions_failures_keep_ok_false(monkeypatch, handler, reason):
    _install(monkeypatch, handler)
    r = client_connect.fetch_video_extensions(URL, "TKN")
    assert r == {"ok": False, "reason": reason, "extensions": []}


# ---- fetch_proxy_settings（168d-T1）----

def _cfg(url="http://127.0.0.1:7890", scope="all"):
    return {"success": True, "data": {"search": {"proxy_url": url, "proxy_scope": scope}}}


def test_fetch_proxy_settings_ok(monkeypatch):
    calls = _install(monkeypatch, lambda r: httpx.Response(200, json=_cfg()))
    r = client_connect.fetch_proxy_settings(URL, "tok")
    assert r["ok"] is True and r["reason"] is None
    assert (r["settings"].url, r["settings"].scope) == ("http://127.0.0.1:7890", "all")
    assert calls[0].url.path == "/api/config"
    assert calls[0].headers["Authorization"] == "Bearer tok"


def test_fetch_proxy_settings_empty_proxy_is_valid(monkeypatch):
    _install(monkeypatch, lambda r: httpx.Response(200, json=_cfg(url="")))
    r = client_connect.fetch_proxy_settings(URL, None)
    assert r["ok"] is True and r["settings"].url == ""


def _boom(exc):
    def h(request):
        raise exc
    return h


@pytest.mark.parametrize("handler,reason", [
    (_boom(httpx.ConnectTimeout("t")), "timeout"),
    (lambda r: httpx.Response(500, json=_cfg()), "bad_response"),
])
def test_fetch_proxy_settings_failures_never_return_settings(monkeypatch, handler, reason):
    _install(monkeypatch, handler)
    r = client_connect.fetch_proxy_settings(URL, "tok")
    assert r == {"ok": False, "reason": reason, "settings": None}


# ---------------------------------------------------------------------------
# 168e-T1：E37 一律直連（真 HTTP，不走 transport=，否則 httpx 不建代理路由會假綠）
# ---------------------------------------------------------------------------
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def _serve_routes():
    """本機真 HTTP 假伺服器（127.0.0.1:0）；回 (httpd, port)。呼叫端負責 shutdown／server_close。"""
    routes = {
        ("GET", "/api/client/hello"): HELLO,
        ("POST", "/api/client/token"): {"success": True, "token": "T"},
        ("GET", "/api/client/sources"): {"success": True, "sources": []},
        ("GET", "/api/config"): {"data": {"scraper": {"video_extensions": [".mp4"]}}},
    }

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, method):
            if method == "POST":
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = routes.get((method, self.path))
            data = json.dumps(body if body is not None else {}).encode()
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._reply("GET")

        def do_POST(self):
            self._reply("POST")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


@pytest.fixture
def lan_server():
    httpd, port = _serve_routes()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def broken_env_proxy(monkeypatch):
    for k in _PROXY_VARS:
        monkeypatch.setenv(k, "http://127.0.0.1:9")
    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("fn,args", [
    (client_connect.probe, ()),
], ids=lambda v: getattr(v, "__name__", None))
def test_client_connect_ignores_system_proxy(broken_env_proxy, lan_server, fn, args):
    r = fn(lan_server, *args)
    assert r["ok"] is True, r


# ---------------------------------------------------------------------------
# 168e-T1：E11 fetch_sources 逾時放寬（MockTransport 讀 request 的 read timeout 模擬延遲，不真 sleep）
# ---------------------------------------------------------------------------
def _slow_nas(monkeypatch, delay):
    real = client_connect._new_client

    def h(request):
        if delay > request.extensions["timeout"]["read"]:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"success": True, "sources": []})

    monkeypatch.setattr(client_connect, "_new_client",
                        lambda timeout=3.0: real(transport=httpx.MockTransport(h), timeout=timeout))


def test_fetch_sources_tolerates_slow_nas(monkeypatch):
    _slow_nas(monkeypatch, 5)
    assert client_connect.fetch_sources(URL, "T")["ok"] is True


