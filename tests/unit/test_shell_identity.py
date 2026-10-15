"""TASK-168d-T2 / CD-168d-4：web.shell_identity.shell_key 純函式。

期望值在測試內獨立算（不 import 被測函式來算），Request 用真 starlette scope 組。
"""
from __future__ import annotations

import hashlib

import pytest
from starlette.requests import Request

from core import access_auth
from web.shell_identity import shell_key


@pytest.fixture(autouse=True)
def _reset_access_auth_snapshot():
    """core.access_auth 的模組級 _snapshot 會被前序測試（跑過 app lifespan）留下 enabled=False，
    shell_key 在 PIN 關閉時忽略票證 → 本檔前後各重置一次，避免順序相依。"""
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


def _req(*, host="127.0.0.1", cookie=None, bearer=None, no_client=False):
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"sid={cookie}".encode()))
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""}
    if not no_client:
        scope["client"] = (host, 12345)
    return Request(scope)


def _t(ticket: str) -> str:
    return "t:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]


def test_shell_key_loopback_without_ticket():
    assert shell_key(_req(host="127.0.0.1")) == "loopback"
    assert shell_key(_req(host="::1")) == "loopback"
    assert shell_key(_req(host="::ffff:127.0.0.1")) == "loopback"


def test_shell_key_remote_without_ticket_gets_ip_key():
    assert shell_key(_req(host="192.168.1.50")) == "ip:192.168.1.50"
    assert shell_key(_req(host="192.168.1.51")) == "ip:192.168.1.51"


def test_shell_key_bearer_matches_sid_cookie_of_same_ticket():
    by_cookie = shell_key(_req(host="192.168.1.50", cookie="TICKET-A"))
    by_bearer = shell_key(_req(host="192.168.1.50", bearer="TICKET-A"))
    assert by_cookie == _t("TICKET-A")
    assert by_bearer == _t("TICKET-A")


def test_shell_key_different_tickets_differ_and_ticket_beats_host():
    assert shell_key(_req(bearer="A")) != shell_key(_req(bearer="B"))
    # 有票據時不論來源位址（含 loopback）都用票據身分
    assert shell_key(_req(host="127.0.0.1", bearer="A")) == _t("A")


def test_shell_key_cookie_takes_precedence_over_bearer():
    assert shell_key(_req(cookie="C", bearer="B")) == _t("C")




# ---------------- 168d Codex F1：PIN 關閉時忽略票據 ----------------

def _set_pin(monkeypatch, enabled):
    import core.access_auth as aa
    snap = None if enabled is None else aa.AuthSnapshot(
        enabled=enabled, pin="", valid_tokens=frozenset(), agent_token=None)
    monkeypatch.setattr(aa, "_snapshot", snap)




def test_shell_key_pin_off_ignores_sid_cookie(monkeypatch):
    _set_pin(monkeypatch, False)
    assert shell_key(_req(host="192.168.1.50", cookie="STALE")) == "ip:192.168.1.50"
    assert shell_key(_req(host="::1", cookie="STALE")) == "loopback"




def test_shell_key_cold_snapshot_looks_at_ticket(monkeypatch):
    _set_pin(monkeypatch, None)
    assert shell_key(_req(host="192.168.1.50", bearer="T1")) == _t("T1")
