"""CD-114a-4：access_gate 與 lan_access_gate 的真實執行序守衛（TASK-114a-T6-c）。

# [lint-guard: pytest-justified] 兩個 middleware 之間的執行期行為 contract
# 斷言的是 Starlette 疊加後的**可觀察後果**（status / body / Content-Type），
# 不是原始碼裡兩個 @app.middleware 的文字先後。static_guard_lint 只能做字串
# 指紋，抓不到「宣告順序對調後實際誰先跑」的 runtime contract，故留 pytest。

依 Starlette 疊加語意（後宣告者最外層先執行）：access_gate 宣告在
lan_access_gate 之前 → 實際執行序是 lan_access_gate 先、access_gate 後。

oracle（server_mode=False + 認證開啟 + 遠端未認證 + GET /search）：
  - 正確序：lan_access_gate 先擋 → 403 + body 逐字 "Forbidden" + text/plain
  - 反轉序：access_gate 先跑 → 200 + access_gate.html 偽裝頁 + text/html
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from web.app import app

# 與 tests/integration/test_access_gate.py 同源常數
REMOTE_CLIENT = ("192.168.1.50", 12345)


@pytest.fixture(autouse=True)
def _reset_access_auth_state():
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """臨時 access_auth DB，開啟認證（PIN=1234）。

    與 test_access_gate.py:56-68 同形——monkeypatch use-site
    core.access_auth.get_db_path。
    """
    db_path = tmp_path / "access_auth_order_test.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, "1234")
    return db_path


@pytest.fixture
def single_mode(monkeypatch):
    """單機模式：lan_access_gate 必須對非 loopback 回 403。

    與 test_access_gate.py 的 server_mode fixture 對稱，但 server_mode=False。
    不可依賴真實 config.json（CI / 本機預設可能不同 → flaky）。
    """
    monkeypatch.setattr(
        "web.app.load_config", lambda: {"general": {"server_mode": False}}
    )


def test_lan_gate_runs_before_access_gate_when_remote_single_mode(
    auth_db, single_mode
):
    """CD-114a-4：access_gate 宣告在 lan_access_gate 之前，但因 Starlette
    疊加語意（後宣告者最外層先執行），實際執行序是 lan_access_gate 先跑。

    這支測試斷言的是「執行序造成的可觀察後果」，不是原始碼位置——
    把兩個 middleware 的宣告順序對調，這支測試必須轉紅。
    """
    client = TestClient(app, client=REMOTE_CLIENT)
    r = client.get("/search")
    assert r.status_code == 403
    assert r.text == "Forbidden"
    assert r.headers["content-type"].startswith("text/plain")
