"""
TASK-168a-T5: `oa_shell` 伺服器能力訊號（CD-168a-6 / CD-168a-7）。

- 顯示格：設定頁 / 說明頁的桌面區塊只看「這個請求帶的殼種類」，不看伺服器行程。
- PIN 閘門格：閘門頁回應也要種 `oa_shell` cookie（middleware 在 lan_access_gate 外層）。
- 授權閘格：`/api/install-context`、`/api/trigger-update` 完全不讀這個訊號。
"""
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from web.app import app

# [lint-guard: pytest-justified] 驗 HTTP 跨層行為（middleware 順序、cookie 往返、SSR 依
# 請求訊號渲染）。答案要走完整個 request 才知道，lint 表達不了。下面對 response.text /
# set-cookie 的字面斷言均由本註解涵蓋。
REMOTE_CLIENT = ("192.168.1.50", 12345)
UPDATE_BTN = '@click="triggerUpdate()"'  # help.html 執行更新鈕（is_desktop 區塊內）
CLOSE_ACTION = 'id="closeAction"'
DESKTOP_ATTR = 'data-is-desktop="true"'


@pytest.fixture(autouse=True)
def _reset_access_auth_state(tmp_path, monkeypatch):
    # 與本機真實 DB 隔開（同 test_page_routes_render.py）
    monkeypatch.setattr(
        "core.access_auth.get_db_path", lambda: tmp_path / "access_auth_shell.db"
    )
    access_auth.reset_state_for_tests()
    access_auth.ensure_schema()
    yield
    access_auth.reset_state_for_tests()


def _set_server_kind(monkeypatch, kind):
    monkeypatch.setattr("web.app._is_windows_desktop", lambda: kind == "windows")
    monkeypatch.setattr("web.app._is_mac_desktop", lambda: kind == "mac")


def _fresh_client(cookies=None):
    c = TestClient(app)
    if cookies:
        for k, v in cookies.items():
            c.cookies.set(k, v)
    return c


# ── 顯示格：{server kind} × {無, windows, mac, evil, 僅 cookie} ────────────

SERVER_KINDS = [None, "windows", "mac"]
# (id, query, cookie, 期望的 shell)
MARKS = [
    ("none", "", None, None),
    ("q-windows", "?oa_shell=windows", None, "windows"),
    ("q-mac", "?oa_shell=mac", None, "mac"),
    ("q-evil", "?oa_shell=evil", None, None),
    ("cookie-windows", "", "windows", "windows"),
    ("cookie-mac", "", "mac", "mac"),
    ("cookie-evil", "", "evil", None),
]


@pytest.mark.parametrize("server_kind", SERVER_KINDS)
@pytest.mark.parametrize("mark_id,query,cookie,expected", MARKS, ids=[m[0] for m in MARKS])
def test_display_follows_shell_not_server_process(
    monkeypatch, server_kind, mark_id, query, cookie, expected
):
    _set_server_kind(monkeypatch, server_kind)
    client = _fresh_client({"oa_shell": cookie} if cookie else None)

    settings = client.get("/settings" + query)
    assert settings.status_code == 200
    assert (CLOSE_ACTION in settings.text) == (expected == "windows")

    help_page = client.get("/help" + query)
    assert help_page.status_code == 200
    assert (DESKTOP_ATTR in help_page.text) == (expected is not None)
    assert (UPDATE_BTN in help_page.text) == (expected is not None)


def test_evil_query_sets_no_cookie(monkeypatch):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get("/settings?oa_shell=evil")
    assert "oa_shell" not in resp.headers.get("set-cookie", "")


def test_valid_query_sets_session_cookie(monkeypatch):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get("/settings?oa_shell=windows")
    sc = resp.headers.get("set-cookie", "")
    assert "oa_shell=windows" in sc
    assert "HttpOnly" in sc
    assert "Max-Age" not in sc and "expires" not in sc.lower()


# ── PIN 閘門格 ────────────────────────────────────────────────────────────


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    db_path = tmp_path / "access_auth_test.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, "1234")
    return db_path


def _server_mode(monkeypatch, on):
    monkeypatch.setattr(
        "web.app.load_config", lambda: {"general": {"server_mode": on}}
    )


def test_pin_gate_response_carries_oa_shell_cookie(monkeypatch, auth_db):
    _server_mode(monkeypatch, True)
    client = TestClient(app, client=REMOTE_CLIENT)
    resp = client.get("/?oa_shell=windows")
    assert 'id="v"' in resp.text  # 確實是閘門頁
    assert "oa_shell=windows" in resp.headers.get("set-cookie", "")


def test_pin_login_then_settings_shows_desktop_block(monkeypatch, auth_db):
    _set_server_kind(monkeypatch, None)
    _server_mode(monkeypatch, True)
    client = TestClient(app, client=REMOTE_CLIENT)
    client.get("/?oa_shell=windows")
    resp = client.post("/api/access/verify", json={"pin": "1234"})
    assert resp.status_code == 200
    settings = client.get("/settings")  # 只帶 cookie
    assert settings.status_code == 200
    assert CLOSE_ACTION in settings.text


def test_single_machine_mode_remote_still_403_and_carries_cookie(monkeypatch, auth_db):
    _server_mode(monkeypatch, False)
    client = TestClient(app, client=REMOTE_CLIENT)
    resp = client.get("/?oa_shell=windows")
    assert resp.status_code == 403
    # LAN 403 由 lan_access_gate 直接回應；middleware 必須在它外層才帶得到 cookie
    assert "oa_shell=windows" in resp.headers.get("set-cookie", "")


# ── 授權閘格（CD-168a-7）──────────────────────────────────────────────────

_ACTION_HEADERS = {
    "X-OpenAver-Desktop-Action": "trigger-update",
    "origin": "http://127.0.0.1:8000",
}


def test_update_endpoints_ignore_shell_signal(monkeypatch):
    _set_server_kind(monkeypatch, None)  # Linux 伺服器：非桌面行程
    results = {}
    for label, cookies in (("plain", None), ("shell", {"oa_shell": "windows"})):
        client = _fresh_client(cookies)
        with mock.patch("web.app.subprocess.Popen") as popen:
            upd = client.post("/api/trigger-update", headers=_ACTION_HEADERS)
            ctx = client.get("/api/install-context")
            upd_q = client.post(
                "/api/trigger-update?oa_shell=windows", headers=_ACTION_HEADERS
            )
        popen.assert_not_called()
        assert upd.status_code == 403
        assert ctx.status_code == 403
        assert upd_q.status_code == 403
        results[label] = (upd.content, ctx.content, upd_q.content)
    assert results["plain"] == results["shell"]


# ── TASK-168b-T3: oa_mode 通道 + /connect 空殼 + 側欄 plug ─────────────────
CONNECT_LINK = 'href="/connect"'

# (id, query, 期望 plug 數, 期望 data-conn-mode 值或 None)
MODE_MARKS = [
    ("none", "", 0, None),
    ("windows-client", "?oa_shell=windows&oa_mode=client", 2, "client"),
    ("windows-local", "?oa_shell=windows&oa_mode=local", 2, "local"),
    ("mode-only", "?oa_mode=client", 0, None),
    ("windows-evil", "?oa_shell=windows&oa_mode=evil", 2, "local"),
    ("windows-nomode", "?oa_shell=windows", 2, "local"),
]


@pytest.mark.parametrize("server_kind", SERVER_KINDS)
@pytest.mark.parametrize("mark_id,query,count,mode", MODE_MARKS, ids=[m[0] for m in MODE_MARKS])
def test_shell_mode_follows_request_not_server_process(
    monkeypatch, server_kind, mark_id, query, count, mode
):
    _set_server_kind(monkeypatch, server_kind)
    monkeypatch.setattr("web.app.desktop_kind", lambda: server_kind)
    client = _fresh_client()
    for page in ("/search", "/help"):
        resp = client.get(page + query)
        assert resp.status_code == 200
        assert resp.text.count(CONNECT_LINK) == count
        if mode is None:
            # 前導空白排除 inline CSS 裡的 [data-conn-mode=...] 選擇器
            assert " data-conn-mode=" not in resp.text
        else:
            assert resp.text.count(f' data-conn-mode="{mode}"') == 2


def test_oa_mode_valid_query_sets_session_cookie(monkeypatch):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get("/settings?oa_shell=windows&oa_mode=client")
    sc = resp.headers.get("set-cookie", "")
    assert "oa_mode=client" in sc
    assert "oa_shell=windows" in sc
    assert "Max-Age" not in sc and "expires" not in sc.lower()


def test_oa_mode_evil_query_sets_no_cookie(monkeypatch):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get("/settings?oa_shell=windows&oa_mode=evil")
    sc = resp.headers.get("set-cookie", "")
    assert "oa_mode" not in sc
    assert "oa_shell=windows" in sc


def test_oa_mode_cookie_drives_display(monkeypatch):
    _set_server_kind(monkeypatch, None)
    client = _fresh_client({"oa_shell": "windows", "oa_mode": "client"})
    assert ' data-conn-mode="client"' in client.get("/search").text
    client = _fresh_client({"oa_shell": "windows", "oa_mode": "evil"})
    assert ' data-conn-mode="local"' in client.get("/search").text


def test_pin_gate_response_carries_oa_mode_cookie(monkeypatch, auth_db):
    _server_mode(monkeypatch, True)
    client = TestClient(app, client=REMOTE_CLIENT)
    resp = client.get("/?oa_shell=windows&oa_mode=client")
    assert 'id="v"' in resp.text
    sc = resp.headers.get("set-cookie", "")
    assert "oa_mode=client" in sc
    assert "Max-Age" not in sc and "expires" not in sc.lower()


def test_single_machine_403_carries_oa_mode_cookie(monkeypatch, auth_db):
    _server_mode(monkeypatch, False)
    client = TestClient(app, client=REMOTE_CLIENT)
    resp = client.get("/?oa_shell=windows&oa_mode=client")
    assert resp.status_code == 403
    sc = resp.headers.get("set-cookie", "")
    assert "oa_mode=client" in sc
    assert "Max-Age" not in sc and "expires" not in sc.lower()


def test_connect_page_200_with_shell(monkeypatch):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get("/connect?oa_shell=windows&oa_mode=client")
    assert resp.status_code == 200
    assert CONNECT_LINK in resp.text


def test_connect_page_404_without_shell(monkeypatch):
    _set_server_kind(monkeypatch, "windows")
    assert _fresh_client().get("/connect").status_code == 404
    assert _fresh_client().get("/connect?oa_mode=client").status_code == 404


def test_update_endpoints_ignore_oa_mode(monkeypatch):
    _set_server_kind(monkeypatch, None)
    results = {}
    for label, cookies in (
        ("plain", {"oa_shell": "windows"}),
        ("mode", {"oa_shell": "windows", "oa_mode": "client"}),
    ):
        client = _fresh_client(cookies)
        with mock.patch("web.app.subprocess.Popen") as popen:
            upd = client.post("/api/trigger-update", headers=_ACTION_HEADERS)
            ctx = client.get("/api/install-context")
            upd_q = client.post(
                "/api/trigger-update?oa_mode=client", headers=_ACTION_HEADERS
            )
        popen.assert_not_called()
        assert upd.status_code == 403
        assert ctx.status_code == 403
        results[label] = (upd.content, ctx.content, upd_q.content)
    assert results["plain"] == results["mode"]


# ── TASK-168c-T4: 設定頁 data-shell-mode 與「這台電腦」標籤 ─────────────────
LOCAL_TAG = "local-machine-tag"
SETTINGS_SHELL_MARKS = [
    ("none", "/settings", "", 0),
    ("windows_client", "/settings?oa_shell=windows&oa_mode=client", "client", 2),
    ("mac_client", "/settings?oa_shell=mac&oa_mode=client", "client", 1),
    ("windows_local", "/settings?oa_shell=windows&oa_mode=local", "local", 0),
    ("windows_evil", "/settings?oa_shell=windows&oa_mode=evil", "", 0),
]


@pytest.mark.parametrize(
    "mark_id,url,attr,tags",
    SETTINGS_SHELL_MARKS,
    ids=[m[0] for m in SETTINGS_SHELL_MARKS],
)
def test_settings_shell_mode_attr_and_local_tags(monkeypatch, mark_id, url, attr, tags):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get(url)
    assert resp.status_code == 200
    assert f'data-shell-mode="{attr}"' in resp.text
    assert resp.text.count(f'class="badge badge-ghost badge-sm {LOCAL_TAG}"') == tags


# ── TASK-168e-T5: 掃描頁 data-shell-mode SSR 屬性 ────────────────────────
SCANNER_SHELL_MARKS = [
    ("none", "/scanner", ""),
    ("windows_client", "/scanner?oa_shell=windows&oa_mode=client", "client"),
    ("windows_local", "/scanner?oa_shell=windows&oa_mode=local", "local"),
    ("windows_evil", "/scanner?oa_shell=windows&oa_mode=evil", ""),
]


@pytest.mark.parametrize(
    "mark_id,url,attr",
    SCANNER_SHELL_MARKS,
    ids=[m[0] for m in SCANNER_SHELL_MARKS],
)
def test_scanner_shell_mode_attr(monkeypatch, mark_id, url, attr):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get(url)
    assert resp.status_code == 200
    assert f'data-shell-mode="{attr}"' in resp.text


# ── TASK-168c-T5: 說明頁 data-shell-mode 與更新確認窗的 client 標題 ─────────
HELP_SHELL_MARKS = [
    ("none", "/help", "", False),
    ("windows_client", "/help?oa_shell=windows&oa_mode=client", "client", True),
    ("windows_local", "/help?oa_shell=windows&oa_mode=local", "local", True),
    ("windows_evil", "/help?oa_shell=windows&oa_mode=evil", "", True),
]


@pytest.mark.parametrize(
    "mark_id,url,attr,has_modal",
    HELP_SHELL_MARKS,
    ids=[m[0] for m in HELP_SHELL_MARKS],
)
def test_help_shell_mode_attr_and_client_modal(monkeypatch, mark_id, url, attr, has_modal):
    _set_server_kind(monkeypatch, None)
    resp = _fresh_client().get(url)
    assert resp.status_code == 200
    assert f'data-shell-mode="{attr}"' in resp.text
    # 更新確認窗在 {% if is_desktop %} 內：client 標題的 x-show 節點 ⇔ 有桌面殼標記
    assert resp.text.count('class="fluent-modal-title" x-show="_bridgeMode"') == (1 if has_modal else 0)
