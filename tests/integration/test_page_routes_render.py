"""頁面路由 TemplateResponse 渲染守衛（防 Starlette 簽名漂移 → 靜默 500）。

緣起：`web/routers/motion_lab.py` 沿用舊版兩參數 `TemplateResponse(name, context)`，
Starlette 1.0 移除該簽名後（改 `TemplateResponse(request, name, context)`），
`/motion-lab` 把 dict 當 template 名查 cache → `TypeError: unhashable type: 'dict'` → 500。
沙盒頁無人開、且既有測試只打 `/api/motion-lab/data`（JSON 端點）+ 自建 mini-app，
頁面渲染從未被測到。此守衛對「真實 web.app」每個頁面路由斷言 200，涵蓋所有
TemplateResponse 頁、擋住此類簽名漂移再次靜默回流。
"""
import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth


@pytest.fixture(autouse=True)
def _isolated_access_auth(tmp_path, monkeypatch):
    """把本檔與「跑測試那台機器上的真實 DB」隔開（TASK-114b-T4 新增）。

    本檔斷言的是「頁面渲染出什麼」，與存取密碼保護無關——但 `/help` 自 114b-T4
    起會依 `core.access_auth` 的**行程全域**狀態決定要不要渲染 agent token 區塊，
    而 `access_gate` middleware 也會依它決定遠端請求拿到頁面還是偽裝頁。不隔離的
    話，這幾支的結果會取決於開發者本機 DB 有沒有開密碼保護——而「開著」正是做完
    T4 的 CDP 驗收之後的狀態，於是 pre-merge 全套會冒出 5 支看起來像 `base_url`
    回歸、實際上與 base_url 無關的紅燈。CI 上是全新 DB 所以永遠綠，這種只在本機
    紅的假回歸最貴。
    """
    monkeypatch.setattr(
        "core.access_auth.get_db_path", lambda: tmp_path / "access_auth_page_routes.db"
    )
    access_auth.reset_state_for_tests()
    access_auth.ensure_schema()  # 全新 DB ＝ enabled=False，暖好快取避免熱路徑冷載
    yield
    access_auth.reset_state_for_tests()


PAGE_ROUTES = [
    "/search",
    "/showcase",
    "/scanner",
    "/settings",
    "/help",
    "/design-system",
    "/motion-lab",
]


@pytest.fixture(scope="module")
def client():
    from web.app import app
    return TestClient(app)


@pytest.mark.parametrize("route", PAGE_ROUTES)
def test_page_route_renders_200(client, route):
    """每個頁面路由的 TemplateResponse 都能成功渲染（200），非簽名漂移 500"""
    resp = client.get(route)
    assert resp.status_code == 200, \
        f"{route} 回 {resp.status_code}（TemplateResponse 渲染失敗 / 簽名漂移？）"
    assert b"<html" in resp.content.lower() or b"<!doctype" in resp.content.lower(), \
        f"{route} 回 200 但非 HTML 文件"


# ── 81b-T5：help curl base_url server-aware 注入矩陣 ─────────────────────────
#
# 桌面主機 server_mode 開 + lan_ip/lan_port 皆有 → curl 範例顯示可分享的
# http://lan_ip:lan_port；任一缺（單機 / socket 失敗 / listener 未起）→ 退
# loopback（request.base_url），HTTP 200 無例外。遠端裝置走 loopback fallback
# 即其自身 LAN base_url（TestClient base_url == http://testserver）。
#
# mock 慣例鏡像 tests/integration/test_server_mode_gate.py（patch web.app.load_config）。


LOOPBACK_CLIENT = ("127.0.0.1", 12345)
REMOTE_CLIENT = ("192.168.1.50", 12345)


def _fresh_client(client=None):
    from web.app import app
    if client is not None:
        return TestClient(app, raise_server_exceptions=True, client=client)
    return TestClient(app, raise_server_exceptions=True)


def _patch_server_mode(monkeypatch, enabled: bool):
    # get_common_context 以 function-local `from core.config import load_config` 讀 server_mode，
    # 故 patch core.config.load_config（web.app.load_config 為 middleware 用，亦一併 patch 保險）。
    cfg = lambda: {"general": {"server_mode": enabled}}
    monkeypatch.setattr("core.config.load_config", cfg)
    monkeypatch.setattr("web.app.load_config", cfg)


def _patch_lan_port(monkeypatch, port):
    from web.lan_listener import lan_listener
    monkeypatch.setattr(lan_listener, "_lan_port", port)


class TestHelpBaseUrlServerAware:
    """help route 的 base_url server-aware 注入（81b-T5）"""

    def test_server_mode_on_lan_available_shows_lan_url(self, monkeypatch):
        """桌面 loopback 主機 + server_mode ON + lan_ip + lan_port → curl 顯示 http://lan_ip:lan_port

        Codex P2：override 僅對 loopback 桌面主機生效，故此 case 必須用 loopback client。
        """
        _patch_server_mode(monkeypatch, True)
        monkeypatch.setattr("web.app.get_lan_ip", lambda: "192.168.1.50")
        _patch_lan_port(monkeypatch, 8001)
        resp = _fresh_client(client=LOOPBACK_CLIENT).get("/help")
        assert resp.status_code == 200
        assert "http://192.168.1.50:8001/api/capabilities" in resp.text

    def test_server_mode_on_remote_device_keeps_request_base_url(self, monkeypatch):
        """Codex P2：server_mode ON + lan_ip/lan_port 皆有，但 request 由遠端裝置（非 loopback）進入
        → 保留 request.base_url（其自身抵達位址，這裡由 Host header 決定），不改寫成裸 LAN IP。
        """
        _patch_server_mode(monkeypatch, True)
        monkeypatch.setattr("web.app.get_lan_ip", lambda: "192.168.1.50")
        _patch_lan_port(monkeypatch, 8001)
        # server_mode ON，lan_access_gate 對遠端 client 放行（200）。
        resp = _fresh_client(client=REMOTE_CLIENT).get(
            "/help", headers={"host": "nas.local:50123"}
        )
        assert resp.status_code == 200
        # 保留請求自身的可分享 base_url（由 Host header 驅動）。
        assert 'data-capabilities-base="http://nas.local:50123"' in resp.text
        # 未被改寫成偵測到的裸 LAN IP。
        assert "192.168.1.50:8001/api/capabilities" not in resp.text

    def test_server_mode_off_falls_back_to_loopback(self, monkeypatch):
        """server_mode OFF → lan_ip 自然 None → 退 loopback（testserver），無 192.168.*"""
        _patch_server_mode(monkeypatch, False)
        monkeypatch.setattr("web.app.get_lan_ip", lambda: "192.168.1.50")
        _patch_lan_port(monkeypatch, 8001)
        resp = _fresh_client().get("/help")
        assert resp.status_code == 200
        assert "http://testserver/api/capabilities" in resp.text
        # curl 範例（含 hero-terminal data-attr）不得帶 LAN IP；help.html 內另有
        # 無關的 192.168 範例說明文字 / i18n dump，故只針對 capabilities 端點比對。
        assert "192.168.1.50:8001/api/capabilities" not in resp.text
        assert 'data-capabilities-base="http://testserver"' in resp.text

    def test_server_mode_on_lan_ip_missing_falls_back_no_error(self, monkeypatch):
        """server_mode ON 但 get_lan_ip → None → 退 loopback，200 無 500"""
        _patch_server_mode(monkeypatch, True)
        monkeypatch.setattr("web.app.get_lan_ip", lambda: None)
        _patch_lan_port(monkeypatch, 8001)
        resp = _fresh_client().get("/help")
        assert resp.status_code == 200
        assert "http://testserver/api/capabilities" in resp.text

    def test_server_mode_on_lan_port_missing_falls_back_no_error(self, monkeypatch):
        """server_mode ON + lan_ip 有但 lan_port None（listener 未起）→ 退 loopback，200 無 500"""
        _patch_server_mode(monkeypatch, True)
        monkeypatch.setattr("web.app.get_lan_ip", lambda: "192.168.1.50")
        _patch_lan_port(monkeypatch, None)
        resp = _fresh_client().get("/help")
        assert resp.status_code == 200
        assert "http://testserver/api/capabilities" in resp.text
