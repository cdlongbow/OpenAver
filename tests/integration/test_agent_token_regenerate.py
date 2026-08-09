"""
TASK-114b-T3: `POST /api/access/agent-token/regenerate` —— 重新產生 agent token。

(a) loopback POST → 200，token 換新
(b) non-loopback POST → 403，舊 token 仍有效
(c) 換票後：舊 token 401、新 token 200（Bearer）
(d) 換票後瀏覽器 cookie 票仍有效（CD-114b-9）
(e) 認證未開啟 → 400，票表零 agent 票
(f) 回傳的 token 字串不出現在 log
"""
from __future__ import annotations

import core.access_auth as access_auth
import pytest
from fastapi.testclient import TestClient

from web.app import app

LOOPBACK_CLIENT = ("127.0.0.1", 12345)
REMOTE_CLIENT = ("192.168.1.50", 12345)

PATH = "/api/access/agent-token/regenerate"


# ── Fixtures（複用 test_access_settings.py 既有機制）─────────────────────


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    db_path = tmp_path / "access.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield db_path
    access_auth.reset_state_for_tests()


@pytest.fixture
def server_mode_true(monkeypatch):
    monkeypatch.setattr(
        "web.app.load_config",
        lambda: {"general": {"server_mode": True}},
    )


@pytest.fixture
def loopback_client(auth_db):
    return TestClient(app, client=LOOPBACK_CLIENT)


@pytest.fixture
def remote_client(auth_db, server_mode_true):
    return TestClient(app, client=REMOTE_CLIENT)


def _remote_authed_client(token: str) -> TestClient:
    client = TestClient(app, client=REMOTE_CLIENT)
    client.cookies.set("sid", token)
    return client


# ── Tests ────────────────────────────────────────────────────────────────


class TestRegenerateAgentToken:
    def test_a1_loopback_regenerate_returns_new_token(self, loopback_client):
        access_auth.set_auth(True, "1234")
        old_token = access_auth.snapshot().agent_token
        r = loopback_client.post(PATH)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["token"].startswith("oav_")
        assert body["token"] != old_token

    def test_b1_remote_forbidden_old_token_still_valid(self, server_mode_true):
        access_auth.set_auth(True, "1234")
        old_token = access_auth.snapshot().agent_token
        # 持票過 access_gate 才能到達 handler 的 loopback 檢查；未持票時
        # middleware 會先回 200 偽裝頁，永遠測不到本端點 403。
        # （card 原文 remote_client 裸 POST 在 auth enabled 下無法到達 handler；
        #  見回報 §5。）
        remote = _remote_authed_client(old_token)
        r = remote.post(PATH)
        assert r.status_code == 403
        assert r.json() == {
            "success": False,
            "reason": "remote_forbidden",
            "error": "重新產生 agent token 僅能在主機本機操作",
        }
        assert access_auth.verify_ticket(old_token) is True
        assert access_auth.snapshot().agent_token == old_token

    def test_b2_auth_disabled_remote_is_still_forbidden(self, remote_client):
        """認證**關閉**時是本 handler 自己的 loopback 檢查唯一生效的一格：
        `access_gate` 的第 4 步（`if not snap.enabled: return await
        call_next(...)`）會直接放行，middleware 不做任何篩選。拿掉 handler
        裡的 `_is_loopback_host` 判斷，這一格會從 403 變成 400——差別是
        「區網上的裝置連問都不准問」與「它問得到、只是這次沒東西可換」。"""
        access_auth.set_auth(False, "")
        r = remote_client.post(PATH)
        assert r.status_code == 403
        assert r.json()["reason"] == "remote_forbidden"

    def test_c1_old_token_401_new_token_200_via_bearer(
        self, loopback_client, server_mode_true
    ):
        access_auth.set_auth(True, "1234")
        old_token = access_auth.snapshot().agent_token
        r = loopback_client.post(PATH)
        assert r.status_code == 200
        new_token = r.json()["token"]

        remote = TestClient(app, client=REMOTE_CLIENT)
        r_old = remote.get(
            "/search", headers={"Authorization": f"Bearer {old_token}"}
        )
        assert r_old.status_code == 401

        r_new = remote.get(
            "/search", headers={"Authorization": f"Bearer {new_token}"}
        )
        assert r_new.status_code == 200

    def test_d1_browser_cookie_ticket_survives_regenerate(self, loopback_client):
        access_auth.set_auth(True, "1234")
        browser_token = access_auth.attempt_pin("1234")
        assert browser_token is not None
        assert access_auth.verify_ticket(browser_token) is True

        r = loopback_client.post(PATH)
        assert r.status_code == 200

        assert access_auth.verify_ticket(browser_token) is True

    def test_e1_auth_disabled_returns_400_no_ticket_created(self, loopback_client):
        access_auth.set_auth(False, "")
        r = loopback_client.post(PATH)
        assert r.status_code == 400
        assert r.json() == {
            "success": False,
            "reason": "auth_disabled",
            "error": "尚未開啟認證，無 agent token 可重新產生",
        }
        conn = access_auth._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM access_tickets WHERE kind = 'agent'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0

    def test_f1_token_not_in_caplog(self, loopback_client, caplog):
        access_auth.set_auth(True, "1234")
        caplog.set_level("DEBUG")
        r = loopback_client.post(PATH)
        assert r.status_code == 200
        token = r.json()["token"]
        assert token not in caplog.text
