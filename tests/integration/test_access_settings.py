"""
TASK-114a-T4: `GET`/`PUT /api/access/settings` —— 認證設定端點。

涵蓋 card 測試案例表 A–G：
  - A: GET reveal 依 loopback 決定（含 ::ffff:127.0.0.1）
  - B: PUT R4 loopback-only（含 mapped-IPv4 通過、遠端 403、lan_access_gate 純文字）
  - C: PIN 格式驗證（前導零保留、illegal 不寫入、enabled=false 跳過格式）
  - D: R5 三操作全撤（開／改不同／改相同／關）
  - E: lifecycle 對稱（拒絕路徑不撤票、不寫入）
  - F: AC4b server_mode 關再開不碰認證
  - G: CD-114a-9 DELETE /api/config 不碰認證 + 反向假綠防護
"""
from __future__ import annotations

import core.access_auth as access_auth
import core.config as core_config
import pytest
from fastapi.testclient import TestClient

from web.app import _is_loopback_host, app

LOOPBACK_CLIENT = ("127.0.0.1", 12345)
REMOTE_CLIENT = ("192.168.1.50", 12345)
MAPPED_LOOPBACK_CLIENT = ("::ffff:127.0.0.1", 12345)

SETTINGS_PATH = "/api/access/settings"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def auth_db(tmp_path, monkeypatch):
    """每測隔離 access_auth DB：先 patch 路徑 → ensure_schema → reset cache。

    loopback 請求不會觸發 middleware 冷路徑的 ensure_schema 補救，必須在此
    暖機；reset_state_for_tests 清掉 module-level cache/retry，避免跨測污染。
    """
    db_path = tmp_path / "access.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    yield db_path
    access_auth.reset_state_for_tests()


@pytest.fixture
def server_mode_true(monkeypatch):
    """讓 lan_access_gate 放行非 loopback（含 ::ffff:127.0.0.1）。"""
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


@pytest.fixture
def mapped_client(auth_db, server_mode_true):
    return TestClient(app, client=MAPPED_LOOPBACK_CLIENT)


def _remote_authed_client(token: str) -> TestClient:
    """遠端 + 持票：enabled=True 時 access_gate 才會放行到 settings handler。"""
    client = TestClient(app, client=REMOTE_CLIENT)
    client.cookies.set("sid", token)
    return client


# ── A. GET /api/access/settings ───────────────────────────────────────────


class TestGetAccessSettings:
    def test_a1_initial_disabled_loopback_reveals_empty_pin(self, loopback_client):
        r = loopback_client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": False,
            "pin": "",
            "pin_revealed": True,
        }

    def test_a2_enabled_loopback_reveals_real_pin(self, loopback_client):
        access_auth.set_auth(True, "0042")
        r = loopback_client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": True,
            "pin": "0042",
            "pin_revealed": True,
        }

    def test_a3_enabled_remote_masks_pin(self, remote_client, server_mode_true):
        access_auth.set_auth(True, "0042")
        token = access_auth.attempt_pin("0042")
        assert token is not None
        client = _remote_authed_client(token)
        r = client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": True,
            "pin": "••••",
            "pin_revealed": False,
        }

    def test_a4_enabled_mapped_loopback_reveals_real_pin(self, mapped_client):
        access_auth.set_auth(True, "0042")
        r = mapped_client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": True,
            "pin": "0042",
            "pin_revealed": True,
        }

    def test_a5_disabled_loopback(self, loopback_client):
        access_auth.set_auth(False, "")
        r = loopback_client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": False,
            "pin": "",
            "pin_revealed": True,
        }

    def test_a6_disabled_remote_masks_pin(self, remote_client):
        access_auth.set_auth(False, "")
        r = remote_client.get(SETTINGS_PATH)
        assert r.status_code == 200
        assert r.json() == {
            "success": True,
            "enabled": False,
            "pin": "••••",
            "pin_revealed": False,
        }


# ── B. PUT R4 loopback-only ───────────────────────────────────────────────


class TestPutR4:
    def test_b1_loopback_enables(self, loopback_client):
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "1234"}
        )
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert access_auth.get_auth_settings(True) == {
            "enabled": True,
            "pin": "1234",
        }

    def test_b2_remote_forbidden_no_write(self, remote_client):
        before = access_auth.get_auth_settings(True)
        assert before == {"enabled": False, "pin": ""}
        r = remote_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "1234"}
        )
        assert r.status_code == 403
        assert r.json() == {
            "success": False,
            "reason": "remote_forbidden",
            "error": "認證設定僅能在主機本機變更",
        }
        assert access_auth.get_auth_settings(True) == {
            "enabled": False,
            "pin": "",
        }

    def test_b3_mapped_loopback_passes_r4(self, mapped_client):
        r = mapped_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "1234"}
        )
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert access_auth.get_auth_settings(True) == {
            "enabled": True,
            "pin": "1234",
        }

    def test_b4_remote_server_mode_false_blocked_by_lan_gate(self, auth_db):
        """server_mode 未開：lan_access_gate 先擋，T4 router 碰不到。"""
        client = TestClient(app, client=REMOTE_CLIENT)
        r = client.put(SETTINGS_PATH, json={"enabled": True, "pin": "1234"})
        assert r.status_code == 403
        assert r.text == "Forbidden"
        assert access_auth.get_auth_settings(True) == {
            "enabled": False,
            "pin": "",
        }

    def test_client_none_is_not_loopback(self):
        """card 邊界：client=None 時 _is_loopback_host 回 False（fail-closed）。"""
        assert _is_loopback_host(None) is False


# ── C. PUT PIN 格式驗證 ───────────────────────────────────────────────────


class TestPutPinFormat:
    def test_c1_leading_zero_preserved(self, loopback_client):
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "0042"}
        )
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert access_auth.get_auth_settings(True)["pin"] == "0042"

    def test_c1b_alphanumeric_pin_accepted(self, loopback_client):
        """T7fix：密碼放寬成 4 位英數（大小寫保留，不折疊）。"""
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "aB92"}
        )
        assert r.status_code == 200
        assert access_auth.get_auth_settings(True)["pin"] == "aB92"

    def test_c1c_fullwidth_pin_stored_as_ascii(self, loopback_client):
        """T7fix：中文輸入法全形模式打出的密碼，存進去必須已折成半形——
        否則使用者用手機（輸入法關著）打同一組字，永遠對不上。"""
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "ａＢ９２"}
        )
        assert r.status_code == 200
        assert access_auth.get_auth_settings(True)["pin"] == "aB92"

    def test_c2_whitespace_rejected_no_write(self, loopback_client):
        access_auth.set_auth(True, "1111")
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "12 3"}
        )
        assert r.status_code == 400
        assert r.json() == {
            "success": False,
            "reason": "invalid_pin",
            "error": "密碼必須是 4 位英文或數字",
        }
        assert access_auth.get_auth_settings(True) == before

    def test_c3_five_digits_rejected(self, loopback_client):
        access_auth.set_auth(True, "1111")
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "12345"}
        )
        assert r.status_code == 400
        assert r.json()["reason"] == "invalid_pin"
        assert access_auth.get_auth_settings(True) == before

    def test_c4_empty_pin_rejected(self, loopback_client):
        access_auth.set_auth(True, "1111")
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": ""}
        )
        assert r.status_code == 400
        assert r.json()["reason"] == "invalid_pin"
        assert access_auth.get_auth_settings(True) == before

    def test_c5_unicode_digits_rejected(self, loopback_client):
        access_auth.set_auth(True, "1111")
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "१२३४"}
        )
        assert r.status_code == 400
        assert r.json()["reason"] == "invalid_pin"
        assert access_auth.get_auth_settings(True) == before

    def test_c6_disabled_ignores_garbage_pin(self, loopback_client):
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": False, "pin": "garbage"}
        )
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert access_auth.get_auth_settings(True) == {
            "enabled": False,
            "pin": "",
        }

    def test_c7_missing_enabled_422(self, loopback_client):
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(SETTINGS_PATH, json={"pin": "1234"})
        assert r.status_code == 422
        assert access_auth.get_auth_settings(True) == before

    def test_c8_enabled_non_bool_422(self, loopback_client):
        before = access_auth.get_auth_settings(True)
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": "yes", "pin": "1234"}
        )
        assert r.status_code == 422
        assert access_auth.get_auth_settings(True) == before


# ── D. R5 三操作全撤 ──────────────────────────────────────────────────────


class TestR5RevokeAll:
    def test_d1_open(self, loopback_client):
        access_auth.set_auth(False, "")
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "2222"}
        )
        assert r.status_code == 200
        assert access_auth.get_auth_settings(True) == {
            "enabled": True,
            "pin": "2222",
        }

    def test_d2_change_to_different_pin_revokes(self, loopback_client):
        access_auth.set_auth(True, "1111")
        token = access_auth.attempt_pin("1111")
        assert token is not None
        assert access_auth.verify_ticket(token) is True
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "3333"}
        )
        assert r.status_code == 200
        assert access_auth.verify_ticket(token) is False

    def test_d3_change_to_same_pin_still_revokes(self, loopback_client):
        access_auth.set_auth(True, "1111")
        token = access_auth.attempt_pin("1111")
        assert token is not None
        assert access_auth.verify_ticket(token) is True
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "1111"}
        )
        assert r.status_code == 200
        assert access_auth.verify_ticket(token) is False

    def test_d4_close_revokes(self, loopback_client):
        access_auth.set_auth(True, "1111")
        token = access_auth.attempt_pin("1111")
        assert token is not None
        assert access_auth.verify_ticket(token) is True
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": False, "pin": "1111"}
        )
        assert r.status_code == 200
        assert access_auth.verify_ticket(token) is False


# ── E. lifecycle 對稱 ─────────────────────────────────────────────────────


class TestLifecycleSymmetry:
    def test_e1_r4_reject_no_side_effects(self, remote_client):
        before = access_auth.get_auth_settings(True)
        assert before == {"enabled": False, "pin": ""}
        r = remote_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "1234"}
        )
        assert r.status_code == 403
        assert access_auth.get_auth_settings(True) == before

    def test_e2_invalid_pin_no_write_no_revoke(self, loopback_client):
        access_auth.set_auth(True, "1111")
        token = access_auth.attempt_pin("1111")
        assert token is not None
        assert access_auth.verify_ticket(token) is True
        before = access_auth.get_auth_settings(True)
        assert before == {"enabled": True, "pin": "1111"}
        r = loopback_client.put(
            SETTINGS_PATH, json={"enabled": True, "pin": "12 3"}
        )
        assert r.status_code == 400
        assert access_auth.get_auth_settings(True) == before
        assert access_auth.verify_ticket(token) is True


# ── F. AC4b server_mode 關再開 ────────────────────────────────────────────


class TestAC4bServerModeIndependent:
    def test_f_server_mode_toggle_leaves_auth_intact(
        self, loopback_client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.lan_listener.lan_listener.start", lambda *a, **k: 49200
        )
        monkeypatch.setattr(
            "web.lan_listener.lan_listener.stop", lambda *a, **k: None
        )
        monkeypatch.setattr(
            "web.lan_listener.get_lan_ip", lambda: "192.168.1.50"
        )

        access_auth.set_auth(True, "5555")
        token = access_auth.attempt_pin("5555")
        assert token is not None
        assert access_auth.verify_ticket(token) is True  # F1

        r2 = loopback_client.put(
            "/api/config/general/server_mode", json={"value": True}
        )
        assert r2.status_code == 200  # F2

        r3 = loopback_client.put(
            "/api/config/general/server_mode", json={"value": False}
        )
        assert r3.status_code == 200  # F3

        assert access_auth.get_auth_settings(True) == {
            "enabled": True,
            "pin": "5555",
        }
        assert access_auth.verify_ticket(token) is True  # F4


# ── G. CD-114a-9 DELETE /api/config ───────────────────────────────────────


class TestCD114a9ConfigResetIndependent:
    def test_g1_delete_config_leaves_auth_intact(
        self, loopback_client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.lan_listener.lan_listener.stop", lambda *a, **k: None
        )
        access_auth.set_auth(True, "6666")
        token = access_auth.attempt_pin("6666")
        assert token is not None
        assert access_auth.verify_ticket(token) is True

        r = loopback_client.delete("/api/config")
        assert r.status_code == 200
        assert access_auth.get_auth_settings(True) == {
            "enabled": True,
            "pin": "6666",
        }
        assert access_auth.verify_ticket(token) is True

    def test_g2_reverse_assertion_has_teeth(self, loopback_client, monkeypatch):
        """若 DELETE 被誤接上 set_auth(False)，G1 類斷言必須轉紅。"""
        monkeypatch.setattr(
            "web.lan_listener.lan_listener.stop", lambda *a, **k: None
        )

        def _fake_reset():
            access_auth.set_auth(False, "")
            return None

        monkeypatch.setattr("web.routers.config.reset_config_file", _fake_reset)

        access_auth.set_auth(True, "6666")
        token = access_auth.attempt_pin("6666")
        assert token is not None

        r = loopback_client.delete("/api/config")
        assert r.status_code == 200
        # 這支斷言必須失敗如果 G1 的「enabled 仍 True」沒咬力——此處我們
        # 主動注入會關掉 auth 的 fake，所以 enabled 應變 False。
        assert access_auth.get_auth_settings(True)["enabled"] is False
        # 同時證明 G1 的正向斷言形狀會因此轉紅（enabled 不再是 True）
        assert not (
            access_auth.get_auth_settings(True)
            == {"enabled": True, "pin": "6666"}
            and access_auth.verify_ticket(token) is True
        )
