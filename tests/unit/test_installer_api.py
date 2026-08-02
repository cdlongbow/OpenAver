"""
tests/unit/test_installer_api.py — _is_mac_desktop() 真值表、/api/install-context、
/api/trigger-update、capabilities 守衛（全 mock，不需真 desktop 環境）
"""
import json
import pytest
from pathlib import Path
from unittest import mock
from fastapi.testclient import TestClient

import web.app as _web_app


@pytest.fixture
def client():
    return TestClient(_web_app.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────
# 1. _is_mac_desktop() 真值表
# ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("standalone_val,platform_val,expected", [
    ("1",  "darwin", True),   # 桌面 macOS → True
    ("1",  "win32",  False),  # standalone 但非 darwin → False
    ("1",  "linux",  False),  # standalone 但非 darwin → False
    ("0",  "darwin", False),  # darwin 但非 standalone → False
    (None, "darwin", False),  # env 未設 + darwin → False
])
def test_is_mac_desktop_truth_table(standalone_val, platform_val, expected, monkeypatch):
    """五象限：OPENAVER_STANDALONE × sys.platform"""
    monkeypatch.delenv("OPENAVER_STANDALONE", raising=False)
    if standalone_val is not None:
        monkeypatch.setenv("OPENAVER_STANDALONE", standalone_val)
    monkeypatch.setattr(_web_app.sys, "platform", platform_val)

    assert _web_app._is_mac_desktop() is expected, (
        f"standalone_val={standalone_val!r}, platform={platform_val!r} → expected {expected}"
    )


# ─────────────────────────────────────────────────────────
# 2. GET /api/install-context
# ─────────────────────────────────────────────────────────

def test_install_context_non_desktop_returns_403(client, monkeypatch):
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: False)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    resp = client.get("/api/install-context")
    assert resp.status_code == 403


def test_install_context_windows_default_path(client, monkeypatch):
    """Windows desktop：sys.executable 在 ~/OpenAver/python/pythonw.exe → is_default_path=True"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)

    home = Path.home()
    fake_exe = home / "OpenAver" / "python" / "pythonw.exe"
    monkeypatch.setattr(_web_app.sys, "platform", "win32")
    monkeypatch.setattr(_web_app.sys, "executable", str(fake_exe))

    resp = client.get("/api/install-context")
    assert resp.status_code == 200
    assert resp.json() == {"is_default_path": True}


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


def test_install_context_macos_default_path(client, monkeypatch):
    """macOS desktop：sys.executable 在 ~/OpenAver/python/bin/python3 → is_default_path=True"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: False)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: True)

    home = Path.home()
    fake_exe = home / "OpenAver" / "python" / "bin" / "python3"
    monkeypatch.setattr(_web_app.sys, "platform", "darwin")
    monkeypatch.setattr(_web_app.sys, "executable", str(fake_exe))

    resp = client.get("/api/install-context")
    assert resp.status_code == 200
    assert resp.json() == {"is_default_path": True}


def test_install_context_path_exception_fallback(client, monkeypatch):
    """路徑計算異常 → fallback is_default_path=True（保守）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    monkeypatch.setattr(_web_app.sys, "platform", "win32")

    # Path("") 會導致 Path.parent.parent 算出 "." / "." 而非 OSError，
    # 所以改 patch Path 本身拋出例外
    original_path = _web_app.Path

    def raise_path(*args, **kwargs):
        if args and args[0] == _web_app.sys.executable:
            raise OSError("simulated path error")
        return original_path(*args, **kwargs)

    monkeypatch.setattr("web.app.Path", raise_path)
    monkeypatch.setattr(_web_app.sys, "executable", "/some/exe")

    resp = client.get("/api/install-context")
    assert resp.status_code == 200
    assert resp.json() == {"is_default_path": True}


# ─────────────────────────────────────────────────────────
# 3. POST /api/trigger-update
# ─────────────────────────────────────────────────────────

def test_trigger_update_non_desktop_returns_403(client, monkeypatch):
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: False)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    resp = client.post("/api/trigger-update")
    assert resp.status_code == 403


def test_trigger_update_windows_calls_powershell(client, monkeypatch):
    """Windows → subprocess.Popen 以 powershell.exe + CREATE_NEW_CONSOLE 呼叫"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    monkeypatch.setattr(_web_app.sys, "platform", "win32")
    # 110b-T6：TestClient 的 request.client.host 是 "testclient"（非 loopback IP）。
    # 本測試驗 subprocess.Popen 呼叫形狀，不驗三層護欄本身（那是
    # tests/integration/test_installer_api.py 的職責）→ 直接放行硬條件②的 client 檢查。
    monkeypatch.setattr("web.app._is_loopback_host", lambda host: True)

    # CREATE_NEW_CONSOLE (0x10) 在 Linux 上不存在，以 mock.patch.object(create=True) 跨平台 patch
    CREATE_NEW_CONSOLE = 0x00000010
    with mock.patch.object(_web_app.subprocess, "CREATE_NEW_CONSOLE", CREATE_NEW_CONSOLE, create=True), \
         mock.patch("web.app.subprocess.Popen") as mock_popen:
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    mock_popen.assert_called_once()
    call_args, call_kwargs = mock_popen.call_args
    cmd = call_args[0]
    assert cmd[0] == "powershell.exe"
    assert call_kwargs.get("creationflags") == CREATE_NEW_CONSOLE


def test_trigger_update_macos_calls_osascript(client, monkeypatch):
    """macOS → subprocess.Popen 以 osascript 呼叫"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: False)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: True)
    monkeypatch.setattr(_web_app.sys, "platform", "darwin")
    # 110b-T6：同上，放行硬條件②的 loopback client 檢查（TestClient host 非 loopback）。
    monkeypatch.setattr("web.app._is_loopback_host", lambda host: True)

    with mock.patch("web.app.subprocess.Popen") as mock_popen:
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    mock_popen.assert_called_once()
    call_args, _ = mock_popen.call_args
    cmd = call_args[0]
    assert cmd[0] == "osascript"


def test_trigger_update_subprocess_oserror_returns_500(client, monkeypatch):
    """subprocess.Popen 拋 OSError → HTTP 500"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    monkeypatch.setattr(_web_app.sys, "platform", "win32")
    # 110b-T6：同上，放行硬條件②的 loopback client 檢查（TestClient host 非 loopback）。
    monkeypatch.setattr("web.app._is_loopback_host", lambda host: True)

    with mock.patch("web.app.subprocess.Popen", side_effect=OSError("not found")):
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )

    assert resp.status_code == 500


# ─────────────────────────────────────────────────────────
# 4. capabilities 守衛：trigger-update 不在 blob
# ─────────────────────────────────────────────────────────

def test_trigger_update_not_in_capabilities(client):
    """capabilities JSON blob 不得含 trigger-update（不揭露給 AI agent）"""
    blob = json.dumps(client.get("/api/capabilities").json(), ensure_ascii=False).lower()
    assert "trigger-update" not in blob, "capabilities 不得揭露 trigger-update"
    assert "/api/trigger-update" not in blob, "capabilities 不得揭露 /api/trigger-update"


# ---------------------------------------------------------------------------
# Opus 複核追加（110b-T6）：三層護欄的兩個 helper 的真值表。
# 這兩條各自對應一個實測抓到的失敗模式，矩陣 11 格沒涵蓋 —— 沒測試就沒鎖。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True),
    ("::1", True),
    ("127.0.0.2", True),          # 127.0.0.0/8 其餘位址（字串 == '127.0.0.1' 會漏）
    ("::ffff:127.0.0.1", True),   # IPv4-mapped IPv6 —— 見下方 docstring
    ("localhost", True),          # 純位址比對會漏（ip_address 對它拋 ValueError）
    ("8.8.8.8", False),
    ("1.1.1.1", False),
    ("testclient", False),        # TestClient 的預設 host
    ("evil.example", False),
    (None, False),
    ("", False),
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
    ("http://127.0.0.1:49152", True),          # 生產入口的動態 port
    ("http://127.0.0.1:8000", True),
    ("http://localhost:8000", True),           # launcher.py 的形式
    ("http://[::1]:49152", True),
    ("https://evil.example", False),           # 外站
    ("http://127.0.0.1.evil.example", False),  # 前綴碰撞式偽裝
    ("null", False),                           # 沙箱 iframe
    ("http://", False),                        # malformed
    ("not-a-url", False),                      # malformed
    ("http://[::1", False),                    # 未閉合 IPv6 —— 見下方 docstring
    ("", False),
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
