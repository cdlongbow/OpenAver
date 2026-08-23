"""
tests/integration/test_installer_api.py — install-context / trigger-update 端點 403 gate
+ trigger-update 三層護欄矩陣（AC2，TASK-110b-T6，CD-110b-5／CD-110b-9）

三層護欄：① desktop 且 loopback client（硬條件）② Origin 存在時只接受 loopback
origin（判 host 不判 port）③ 自訂 header `X-OpenAver-Desktop-Action` 存在。
11 個具名案例（1–8、9a、9b、10）覆蓋 desktop × loopback client × Origin ×
header × server_mode 的正交組合矩陣（詳見 TASK-110b-T6.md）。

**CD-110b-9① 假綠陷阱**：Starlette `TestClient` 預設 `request.client.host` 是
`"testclient"`（非 loopback IP），若不處理，案例 1–8、10 會被端點自己新增的
loopback 硬條件全數擋成 403（假綠：看起來護欄很嚴，其實護欄把自己鎖死）。
本庫 `tests/conftest.py` 已有全域 patch，把 `TestClient` 的 `client` 參數
setdefault 成 `("127.0.0.1", 50000)`（見該檔案註解，非本 task 新增），下面
沿用該預設代表「loopback client」；案例 9a/9b 需要「非 loopback client」，
顯式傳 `client=("8.8.8.8", 12345)` 覆寫 setdefault。

**CD-110b-9② 對照 IP 陷阱**：非 loopback 對照 IP 不可用 RFC 5737/3849 文件保留段
（如 `192.0.2.0/24`）——會被 `ipaddress` 誤判 `is_private=True`（`BE-TEST-03`）。
本檔用 `8.8.8.8`（真實全域可路由 IP）。
"""
import pytest
from unittest import mock
from fastapi.testclient import TestClient
from web.app import app


def test_install_context_non_desktop_returns_403(monkeypatch):
    """dev/uvicorn 裸跑（無 OPENAVER_STANDALONE）→ 403。"""
    monkeypatch.delenv("OPENAVER_STANDALONE", raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/install-context")
    assert resp.status_code == 403


def test_trigger_update_non_desktop_returns_403(monkeypatch):
    """dev/uvicorn 裸跑（無 OPENAVER_STANDALONE）→ 403。"""
    monkeypatch.delenv("OPENAVER_STANDALONE", raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/trigger-update")
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────
# POST /api/trigger-update — 三層護欄矩陣（AC2 具名案例 1–8、9a、9b、10）
# ─────────────────────────────────────────────────────────

def _loopback_client():
    """loopback client（沿用 tests/conftest.py 全域 setdefault 127.0.0.1）。"""
    return TestClient(app, raise_server_exceptions=False)


def _non_loopback_client():
    """非 loopback client，顯式覆寫 conftest 的 loopback setdefault。"""
    return TestClient(app, raise_server_exceptions=False, client=("8.8.8.8", 12345))


def test_trigger_update_case1_loopback_no_origin_header_ok_returns_200(monkeypatch):
    """案例1：loopback／無 Origin／header✓／desktop✓／server_mode=F → 200
    （PyWebView 可能不送 Origin，不得因此拒絕）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )
    assert resp.status_code == 200


def test_trigger_update_case2_loopback_ip_origin_returns_200(monkeypatch):
    """案例2：loopback／Origin=http://127.0.0.1:<任意 port>／header✓ → 200"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "http://127.0.0.1:54321",
            },
        )
    assert resp.status_code == 200


def test_trigger_update_case3_localhost_origin_returns_200(monkeypatch):
    """案例3：loopback／Origin=http://localhost:8000（launcher.py 固定 port 形式）／header✓ → 200"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "http://localhost:8000",
            },
        )
    assert resp.status_code == 200


def test_trigger_update_case4_evil_origin_returns_403(monkeypatch):
    """案例4（關鍵案例）：loopback／Origin=https://evil.example／header✓ → 403
    唯一能證明 Origin host 真的被驗的一格——若 Origin host 驗證是空殼，這格會變 200。"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "https://evil.example",
            },
        )
    assert resp.status_code == 403


def test_trigger_update_case5_null_origin_returns_403(monkeypatch):
    """案例5：loopback／Origin="null"／header✓ → 403（沙箱 iframe 會送 null，不得當成「沒有 Origin」放行）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "null",
            },
        )
    assert resp.status_code == 403


@pytest.mark.parametrize("malformed_origin", ["http://", "not-a-url"])
def test_trigger_update_case6_malformed_origin_returns_403(malformed_origin, monkeypatch):
    """案例6：loopback／Origin malformed（urlparse 解析不出 hostname）／header✓ → 403（fail-closed）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": malformed_origin,
            },
        )
    assert resp.status_code == 403


def test_trigger_update_case7_missing_header_no_origin_returns_403(monkeypatch):
    """案例7：loopback／無 Origin／header✗ → 403"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post("/api/trigger-update")
    assert resp.status_code == 403


def test_trigger_update_case8_missing_header_valid_origin_returns_403(monkeypatch):
    """案例8：loopback／合法 loopback Origin／header✗ → 403"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={"origin": "http://127.0.0.1:54321"},
        )
    assert resp.status_code == 403


def test_trigger_update_case9a_non_loopback_server_mode_off_returns_403(monkeypatch):
    """案例9a：非 loopback（8.8.8.8）／server_mode=F → 403
    既有 lan_access_gate middleware 直接擋下，handler 根本沒被呼叫
    （驗既有行為沒壞；9a 與 9b 必須拆開，見案例9b 說明）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": False}})
    client = _non_loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )
    assert resp.status_code == 403


def test_trigger_update_case9b_non_loopback_server_mode_on_returns_403(monkeypatch, tmp_path):
    """案例9b（本 Phase 新關的 LAN 暴露面）：非 loopback（8.8.8.8）／server_mode=T → 403
    middleware 因 server_mode=True 放行非 loopback 流量後，由端點自己的 loopback
    硬條件擋下。9b 必須顯式把 server_mode 設 True，否則流量根本不會抵達 handler，
    mutation 測不到任何東西（Codex delta review P1-A）。"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": True}})
    # server_mode=True 讓非 loopback 流量抵達 access_gate middleware，其冷啟動
    # `await asyncio.to_thread(ensure_schema)`（web/app.py:327）未 mock 前會連上
    # output/openaver.db。同手法見 tests/integration/test_capabilities_auth.py。
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: tmp_path / "access.db")
    client = _non_loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={"X-OpenAver-Desktop-Action": "trigger-update"},
        )
    assert resp.status_code == 403


def test_trigger_update_case10_loopback_non_desktop_returns_403(monkeypatch):
    """案例10：loopback／合法 Origin／header✓／desktop✗ → 403（既有 desktop gate 不得因新護欄而失效）"""
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: False)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "http://127.0.0.1:54321",
            },
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Opus 複核追加（110b-T6）：兩條實測抓到的邊界。矩陣 11 格沒涵蓋，而它們各自
# 對應一個真實失敗模式，沒有測試就沒有鎖。
# ---------------------------------------------------------------------------

def test_trigger_update_unclosed_ipv6_origin_returns_403_not_500(monkeypatch):
    """未閉合 IPv6 字面值的 Origin（`http://[::1`）→ **403 而非 500**。

    實測 `urlparse('http://[::1')` 會拋 `ValueError: Invalid IPv6 URL`。不接住的話
    會變成未處理例外 → 500，既非 fail-closed 的 403，也把「被擋下」與「伺服器壞了」
    混在一起（T8 真跑驗收會分不出來）。`_is_loopback_origin` 必須接住回 False。
    拿掉那個 except ValueError → 本測試會看到 500 而變紅。
    """
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: True)
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: False)
    client = _loopback_client()
    with mock.patch("web.app.subprocess.Popen"):
        resp = client.post(
            "/api/trigger-update",
            headers={
                "X-OpenAver-Desktop-Action": "trigger-update",
                "origin": "http://[::1",
            },
        )
    assert resp.status_code == 403
