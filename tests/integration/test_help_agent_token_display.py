"""
TASK-114b-T4：Help 頁 agent token 顯示區塊——SSR context 契約。

(a) 認證關閉 → /help 不含任何新增錨點（AC8）
(b) 認證開啟 + loopback → /help 含面板錨點 + 真值 token（CD-114b-6 的唯一合法出口）
(c) 認證開啟 + 非 loopback（含已通過 PIN 的持票裝置）→ /help 不含真值、不含面板錨點
(d) 認證開啟 + loopback + 快取冷（reset_state_for_tests 模擬重啟後第一個請求）→ 200，不拋例外

**AC8 的準確措辭**：認證關閉時的回應與改動前**沒有任何可見差異**，但不是逐位元組
相同——Jinja 預設不開 `trim_blocks`/`lstrip_blocks`，新增的 `{% if %}` / `{% else %}`
標籤本身會留下幾個空白行（實測 +65 bytes 全是換行）。那對瀏覽器、對任何斷言、對
任何 hash 都沒有影響（全庫沒有任何地方對頁面 body 做雜湊或長度比對），所以不改用
`{%- -%}` 去追求真正的位元組相等——那會讓模板為了一個沒有讀者的性質變難讀。
本檔守的是「**新增的東西一個都不會出現**」，那才是 AC8 真正要的。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.access_auth as access_auth
from web.app import app

LOOPBACK_CLIENT = ("127.0.0.1", 12345)
REMOTE_CLIENT = ("192.168.1.50", 12345)
ANCHOR_CLASS = "help-agent-token-panel"


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
    monkeypatch.setattr("web.app.load_config", lambda: {"general": {"server_mode": True}})


class TestAuthDisabledByteIdentical:
    def test_no_new_anchor_no_i18n_leak_no_token_marker(self):
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() not in resp.content
        assert b"help.agent_auth" not in resp.content
        assert b"oav_" not in resp.content
        # 這裡**刻意沒有**「不得出現 Authorization 字面」這條斷言：
        # ① bare "Authorization" 當不了錨點——`settings.openai.openai_api_key_placeholder`
        #    早把「不送 Authorization header」嵌進每頁的 `window.__i18n` 全量字典
        #    （`get_merged_translations()` 回整份、不分頁過濾），與本 task 無關；
        # ② 收窄成 "Authorization: Bearer" 則是一條**永遠不可能紅**的死斷言——
        #    那個字串由前端 `curlDisplayText()` 在瀏覽器組出來，SSR 回應裡任何
        #    情況下都不會有它。真正的洩漏面是 token 本身與面板錨點，由上面三條
        #    斷言涵蓋。留一條驗不到東西的斷言比沒有更糟：它看起來像防線。


class TestLoopbackAuthEnabledShowsRealToken:
    def test_loopback_sees_panel_and_real_token(self):
        access_auth.set_auth(True, "AB12")
        real_token = access_auth.snapshot().agent_token
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() in resp.content
        assert real_token.encode() in resp.content


class TestNonLoopbackNeverSeesRealToken:
    def test_remote_authed_request_gets_no_token_no_anchor(self, server_mode_true):
        access_auth.set_auth(True, "AB12")
        browser_token = access_auth.attempt_pin("AB12")
        assert browser_token is not None
        client = TestClient(app, client=REMOTE_CLIENT)
        client.cookies.set("sid", browser_token)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() not in resp.content
        assert b"oav_" not in resp.content
        assert b"Authorization: Bearer" not in resp.content


class TestColdSnapshotCacheDoesNotCrash:
    def test_cold_cache_still_200(self):
        access_auth.set_auth(True, "AB12")
        access_auth.reset_state_for_tests()  # 模擬重啟後 snapshot() 回 None
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() in resp.content  # 冷路徑補完後仍要正確顯示
