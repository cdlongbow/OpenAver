"""
tests/unit/test_installer_api.py — _is_mac_desktop() 真值表、/api/install-context、
/api/trigger-update、capabilities 守衛（全 mock，不需真 desktop 環境）
"""
import json
import pytest
from fastapi.testclient import TestClient

import web.app as _web_app


@pytest.fixture
def client():
    return TestClient(_web_app.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────
# 1. _is_mac_desktop() 真值表
# ─────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────
# 2. GET /api/install-context
# ─────────────────────────────────────────────────────────


def test_install_context_windows_non_default_path(client, monkeypatch):
    """Windows desktop：sys.executable 在非預設路徑 → is_default_path=False"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)

    fake_exe = "/custom/path/python/pythonw.exe"
    monkeypatch.setattr(_web_app.sys, "platform", "win32")
    monkeypatch.setattr(_web_app.sys, "executable", fake_exe)

    resp = client.get("/api/install-context")
    assert resp.status_code == 200
    assert resp.json() == {"is_default_path": False}


# ─────────────────────────────────────────────────────────
# 3. POST /api/trigger-update
# ─────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────
# 4. capabilities 守衛：trigger-update 不在 blob
# ─────────────────────────────────────────────────────────

def test_trigger_update_not_in_capabilities(client, tmp_path, monkeypatch):
    """capabilities JSON blob 不得含 trigger-update（不揭露給 AI agent）"""
    # GET /api/capabilities 冷啟動時會呼叫 load_snapshot()（core/access_auth.py），
    # 未 mock 前連上 output/openaver.db（同手法見
    # tests/integration/test_capabilities_auth.py 的 auth_db fixture／
    # 127b-T4 已修正的 test_capabilities.py／test_scraper_b3.py）。
    import core.access_auth as access_auth
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: tmp_path / "access.db")
    access_auth.ensure_schema()
    access_auth.reset_state_for_tests()
    try:
        blob = json.dumps(client.get("/api/capabilities").json(), ensure_ascii=False).lower()
    finally:
        access_auth.reset_state_for_tests()
    assert "trigger-update" not in blob, "capabilities 不得揭露 trigger-update"
    assert "/api/trigger-update" not in blob, "capabilities 不得揭露 /api/trigger-update"


# ---------------------------------------------------------------------------
# Opus 複核追加（110b-T6）：三層護欄的兩個 helper 的真值表。
# 這兩條各自對應一個實測抓到的失敗模式，矩陣 11 格沒涵蓋 —— 沒測試就沒鎖。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host,expected", [
    ("::ffff:127.0.0.1", True),   # IPv4-mapped IPv6 —— 見下方 docstring
    ("evil.example", False),
    (None, False),
])
def test_is_loopback_host_truth_table(host, expected):
    """`_is_loopback_host` 真值表。

    **`::ffff:127.0.0.1` 這格是重點**：實測
    `ipaddress.ip_address('::ffff:127.0.0.1').is_loopback` 回 **False**
    （`is_loopback` 只認 `::1`）。dual-stack socket 上的 uvicorn 有機會把本機連線的
    peer 回報成這個形式；`_is_loopback_host` 若不先解回 IPv4 就會把桌面版自己鎖在
    門外 —— plan-110b §4 風險表列為「最嚴重」的那一條。
    拿掉實作裡的 `ipv4_mapped` 解析 → 這一格變紅。

    > **已知的上游殘留（本 Phase 不治，非本 task 引入）**：全域
    > `lan_access_gate` middleware 用的是 `_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}`
    > 精確名單，**不認** `::ffff:127.0.0.1`。所以真有 dual-stack peer 回報成該形式
    > 時，會在 middleware 就被 403（`server_mode=False` 下），整個 app 都連不上，
    > 不只 trigger-update。本 task 依 task card 明令不得動 middleware，故此處只把
    > 端點層做對（defense in depth）；middleware 那一層列為具名 backlog。
    """
    from web.app import _is_loopback_host
    assert _is_loopback_host(host) is expected


@pytest.mark.parametrize("origin,expected", [
    ("http://127.0.0.1.evil.example", False),  # 前綴碰撞式偽裝
])
def test_is_loopback_origin_truth_table(origin, expected):
    """`_is_loopback_origin` 真值表（判 host 不判 port，CD-110b-5）。

    **`http://[::1` 這格是重點**：實測 `urlparse('http://[::1')` 會拋
    `ValueError: Invalid IPv6 URL`。不接住的話端點會變成未處理例外 → **500**，
    既不是 fail-closed 的 403，也讓 T8 真跑驗收分不出「被護欄擋下」與「伺服器壞了」。
    拿掉實作裡的 `except ValueError` → 這一格會拋例外而變紅。

    `http://127.0.0.1.evil.example` 那格鎖的是「判的是 hostname 不是字串前綴」——
    若有人把實作改成 `origin.startswith('http://127.0.0.1')` 就會變綠（即放行），
    這一格會抓到。
    """
    from web.app import _is_loopback_origin
    assert _is_loopback_origin(origin) is expected
