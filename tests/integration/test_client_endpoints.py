"""TASK-168b-T2: /api/client/{hello,token,sources} 握手端點、握手放行分支、
`client_token_gate`（oa_token 入口轉址）。

oracle 對應 plan CD-168b-1 ①–⑨ 與 CD-168b-4。非 loopback 一律顯式
`TestClient(app, client=REMOTE_CLIENT)`（conftest 預設是 loopback，不傳就等於
繞過兩道閘，閘門格會假綠）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from core.version import VERSION
# 守衛測試需讀放行常數本體（同 test_access_gate.py）
from web.app import (
    app,
)

REMOTE_CLIENT = ("192.168.1.50", 12345)
LOOPBACK_CLIENT = ("127.0.0.1", 12345)

# [lint-guard: pytest-justified] 偽裝頁指紋：斷言「這一次 HTTP round-trip 實際回給
# 未認證來源的東西是偽裝頁」，靜態掃檔表達不出來（同 test_access_gate.py）。
_MASKED_FINGERPRINT = 'id="v"'


def _assert_masked(response):
    assert response.status_code == 200
    assert _MASKED_FINGERPRINT in response.text
    assert "OpenAver" not in response.text


@pytest.fixture(autouse=True)
def _reset_access_auth_state():
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    async def _instant():
        return None

    monkeypatch.setattr("web.routers.access._fixed_delay", _instant)


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    db_path = tmp_path / "client_endpoints.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, "1234")
    return db_path


@pytest.fixture
def pin_off_db(tmp_path, monkeypatch):
    db_path = tmp_path / "client_endpoints_off.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(False, "")
    return db_path


@pytest.fixture
def server_mode(monkeypatch):
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": True}})


@pytest.fixture
def single_mode(monkeypatch):
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": False}})


@pytest.fixture
def gated_client(auth_db, server_mode):
    return TestClient(app, client=REMOTE_CLIENT)


@pytest.fixture
def valid_token(auth_db):
    token = access_auth.attempt_pin("1234")
    assert token is not None
    return token


@pytest.fixture
def sources_config(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.mp4").write_bytes(b"")
    cfg = {"gallery": {"directories": [str(tmp_path / "a")]}, "search": {"favorite_folder": ""}}
    monkeypatch.setattr("web.routers.client.load_config", lambda: cfg)
    return tmp_path


# ── hello ────────────────────────────────────────────────────────────────


class TestHello:
    def test_unauthenticated_hello_reports_auth_required(self, gated_client):
        r = gated_client.get("/api/client/hello")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["app"] == "openaver"
        assert body["version"] == VERSION
        assert body["auth_required"] is True
        assert body["authed"] is False
        assert "kind" in body

    def test_valid_bearer_reports_authed(self, gated_client, valid_token):
        r = gated_client.get("/api/client/hello", headers={"Authorization": f"Bearer {valid_token}"})
        assert r.status_code == 200
        assert r.json()["authed"] is True


    def test_pin_off_reports_no_auth_required(self, pin_off_db, server_mode):
        c = TestClient(app, client=REMOTE_CLIENT)
        body = c.get("/api/client/hello").json()
        assert body["auth_required"] is False
        assert body["authed"] is True


    @pytest.mark.parametrize(
        "synology,desktop,expected",
        [(True, "windows", "synology"), (False, None, "linux"), (False, "windows", "windows"), (False, "mac", "mac")],
    )
    def test_kind_four_values(self, gated_client, monkeypatch, synology, desktop, expected):
        monkeypatch.setattr("core.platform_info.is_synology", lambda: synology)
        monkeypatch.setattr("core.platform_info.desktop_kind", lambda: desktop)
        assert gated_client.get("/api/client/hello").json()["kind"] == expected


# ── token ────────────────────────────────────────────────────────────────


class TestToken:
    def test_correct_pin_returns_token_usable_on_sources(self, gated_client, sources_config):
        r = gated_client.post("/api/client/token", json={"pin": "1234"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        token = body["token"]
        assert token
        r2 = gated_client.get("/api/client/sources", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["success"] is True

    def test_wrong_pin_is_401_bad_pin(self, gated_client):
        r = gated_client.post("/api/client/token", json={"pin": "0000"})
        assert r.status_code == 401
        assert r.json() == {"success": False, "reason": "bad_pin"}

    def test_non_json_content_type_is_401_and_not_counted(self, gated_client):
        for _ in range(6):
            r = gated_client.post("/api/client/token", content="pin=0000", headers={"Content-Type": "text/plain"})
            assert r.status_code == 401
        r = gated_client.post("/api/client/token", json={"pin": "1234"})
        assert r.status_code == 200

    def test_five_wrong_pins_lock_out_correct_pin(self, gated_client):
        for _ in range(5):
            assert gated_client.post("/api/client/token", json={"pin": "0000"}).status_code == 401
        r = gated_client.post("/api/client/token", json={"pin": "1234"})
        assert r.status_code == 401
        assert r.json() == {"success": False, "reason": "bad_pin"}

    def test_lockout_shared_gate_page_then_token(self, gated_client):
        for _ in range(5):
            gated_client.post("/api/access/verify", json={"pin": "0000"})
        r = gated_client.post("/api/client/token", json={"pin": "1234"})
        assert r.status_code == 401


# ── sources ──────────────────────────────────────────────────────────────


class TestSources:
    def test_sources_unauthenticated_masked(self, gated_client):
        _assert_masked(gated_client.get("/api/client/sources"))

    def test_sources_with_valid_bearer_lists_sources(self, gated_client, valid_token, sources_config):
        r = gated_client.get("/api/client/sources", headers={"Authorization": f"Bearer {valid_token}"})
        assert r.status_code == 200
        sources = r.json()["sources"]
        assert sources[0]["path"] == str(sources_config / "a")
        assert sources[0]["kind"] == "directory"
        assert sources[0]["sample"] == str(sources_config / "a" / "x.mp4")


# ── 握手放行粒度 / 三端點的 LAN 閘 ────────────────────────────────────────


class TestHandshakeGate:

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/client/token"),
            ("GET", "/api/client/other"),
        ],
    )
    def test_handshake_does_not_open_other_client_paths(self, gated_client, method, path):
        r = gated_client.request(method, path)
        _assert_masked(r)

    def test_single_mode_remote_gets_403_on_all_three(self, auth_db, single_mode):
        c = TestClient(app, client=REMOTE_CLIENT)
        for method, path in [("GET", "/api/client/hello"), ("POST", "/api/client/token"), ("GET", "/api/client/sources")]:
            r = c.request(method, path, json={"pin": "1234"} if method == "POST" else None)
            assert r.status_code == 403
            assert r.text == "Forbidden"


# ── client_token_gate（oa_token 入口）──────────────────────────────────────


class TestClientTokenGate:
    def test_client_token_gate_pin_open_remote_valid_token_redirects(self, gated_client, valid_token):
        r = gated_client.get(f"/settings?oa_token={valid_token}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/settings"
        assert f"sid={valid_token}" in r.headers["set-cookie"]

    def test_oa_token_redirect_location_has_no_token(self, gated_client, valid_token):
        r = gated_client.get(f"/settings?a=1&oa_token={valid_token}&b=2", follow_redirects=False)
        assert r.status_code == 303
        assert valid_token not in r.headers["location"]
        assert "oa_token" not in r.headers["location"]
        assert r.headers["location"] == "/settings?a=1&b=2"
        assert valid_token not in r.text

    def test_cookie_is_session_cookie(self, gated_client, valid_token):
        r = gated_client.get(f"/settings?oa_token={valid_token}", follow_redirects=False)
        cookie = r.headers["set-cookie"].lower()
        assert "max-age" not in cookie
        assert "expires" not in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie


    def test_invalid_token_falls_to_gate_page(self, gated_client):
        r = gated_client.get("/settings?oa_token=bogus", follow_redirects=False)
        _assert_masked(r)


    def test_revoke_all_invalidates_token_and_cookie(self, gated_client, valid_token):
        r = gated_client.get(f"/settings?oa_token={valid_token}", follow_redirects=False)
        assert r.status_code == 303
        access_auth.revoke_all()
        _assert_masked(gated_client.get("/settings", follow_redirects=False))
        fresh = TestClient(app, client=REMOTE_CLIENT)
        _assert_masked(fresh.get(f"/settings?oa_token={valid_token}", follow_redirects=False))


    def test_cold_cache_valid_token_still_redirects(self, auth_db, server_mode):
        token = access_auth.attempt_pin("1234")
        access_auth.reset_state_for_tests()
        assert access_auth.snapshot() is None
        c = TestClient(app, client=REMOTE_CLIENT)
        r = c.get(f"/settings?oa_token={token}", follow_redirects=False)
        assert r.status_code == 303


