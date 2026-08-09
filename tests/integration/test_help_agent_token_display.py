"""
TASK-114b-T4：Help 頁 agent token 顯示區塊——SSR context 契約。

(a) 認證關閉 → /help 不含任何新增錨點（AC8）
(b) 認證開啟 + loopback → /help 含面板錨點 + 真值 token（CD-114b-6 的唯一合法出口）
(c) 認證開啟 + 非 loopback（含已通過 PIN 的持票裝置）→ /help 不含真值、不含面板錨點
(d) 認證開啟 + loopback + 快取冷（reset_state_for_tests 模擬重啟後第一個請求）→ 200，不拋例外

**AC8 是逐位元組成立的**（Codex PR review P3）：初版新增的 `{% if %}` / `{% else %}`
標籤在認證關閉時多吐 5 個空白行（+65 bytes），當時判定「沒有可見差異就夠了」並把
定義寫在這裡——那是在**沒有 owner 改判的情況下私自縮窄 AC**。已改為用 Jinja
whitespace control（`{%- if %}` / `{%- else %}` / `{%- endif %}`，共 5 個標記）把輸出
還原，並實測核對：把 T4 之前那版 `help.html`（commit `258242a1`）用**同一份 context**
渲染一次，與現在 `GET /help`（認證關閉）的回應比對，**180778 vs 180778，delta 0，
逐位元組相同**。

本檔的斷言仍然是「新增的東西一個都不會出現」（那是可持續維護的形狀）；逐位元組
那一次是合併前的一次性機械核對，不落成 golden 檔——釘一份 180KB 的黃金輸出，
維護成本會壓垮它守住的那個性質。
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
    # [lint-guard: pytest-justified] 這四個 class 斷言的是「同一份 help.html 依
    # 請求狀態（認證開關 × 來源是否 loopback）渲染出不同輸出」——static_guard_lint
    # 掃的是模板源碼的字面存在，看不到 SSR 之後的結果，表達不了「非 loopback 這次
    # 渲染不含 oav_」。守的又是安全指紋（token 真值只有一個合法出口，CD-114b-6）。
    def test_no_new_anchor_no_i18n_leak_no_token_marker(self):
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() not in resp.content
        assert b"help.agent_auth" not in resp.content
        assert b"oav_" not in resp.content
        assert b"Authorization: Bearer" not in resp.content
        # 為什麼是 `"Authorization: Bearer"` 而不是 bare `"Authorization"`：
        # `settings.openai.openai_api_key_placeholder` 早把「不送 Authorization
        # header」嵌進每頁的 `window.__i18n` 全量字典（`get_merged_translations()`
        # 回整份、不分頁過濾），bare 字串當不了錨點。
        #
        # 這條**今天**掃不到東西（curl 範例由前端 `curlDisplayText()` 在瀏覽器
        # 組出來，SSR 不產生這個字串），但它不是死斷言。實際 mutation 量過它什麼
        # 時候會紅（Codex PR review 二審 P3）：
        #   ① 只把那行改成 Jinja 伺服器端渲染 → **兩支都還是綠的**（那個區塊仍在
        #      `{% if show_agent_auth %}` 內，關閉／遠端都不會渲染）；
        #   ② 再把閘門「順手合回」`auth_enabled`（＝本 branch P2 犯過的錯的反向）
        #      → **遠端那支紅**；
        #   ③ 或者那行變成無條件渲染 → **兩支都紅**。
        # 也就是說它守的是「SSR 化 ＋ 閘門走鬆」這個組合，而組合裡的第二步這條
        # branch 真的發生過一次。第一段的「單獨 SSR 化」不會紅是它的已知邊界，
        # 寫在這裡以免下一個人以為它涵蓋了它其實沒涵蓋的東西。
        #
        # 我先前把這條刪掉時宣稱它「永遠不可能紅」——那是把 `/api/capabilities`
        # 那條（認證關閉時 `curl_auth` 為空、確實恆真）的結論直接搬過來，兩者的
        # 產生路徑不同，搬錯了。


class TestLoopbackAuthEnabledShowsRealToken:
    # [lint-guard: pytest-justified] 同上——SSR 之後的結果依請求狀態而變，lint 掃不到；
    # 這一格守的是「token 真值只在 loopback 的 /help 出現」這個唯一合法出口。
    def test_loopback_sees_panel_and_real_token(self):
        access_auth.set_auth(True, "AB12")
        real_token = access_auth.snapshot().agent_token
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() in resp.content
        assert real_token.encode() in resp.content


class TestNonLoopbackNeverSeesRealToken:
    # [lint-guard: pytest-justified] 安全指紋 ＋ 跨層 contract：斷言「已通過 PIN 的
    # 遠端裝置渲染出來的 /help 不含 oav_ 也不含面板錨點」。這是 request 狀態的函式，
    # 模板源碼裡那些字串永遠存在，static_guard_lint 只會永遠通過。
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
        # plan §4 T4 的機械面之一：非 loopback 不得拿到 token，也不得拿到 agent
        # curl 的形狀。理由見 TestAuthDisabledByteIdentical 那條同款斷言的註解。
        assert b"Authorization: Bearer" not in resp.content

    def test_remote_authed_request_still_gets_the_auth_enabled_security_copy(
        self, server_mode_true
    ):
        """Codex PR review P2：安全提示那句文案的條件是「認證開沒開」，**不是**
        「認證開了而且是本機」。兩者綁在一起的後果，是一台剛剛才輸完密碼的家人
        手機打開說明頁，讀到的是「本程式不設帳號密碼」——它剛做的事就否證了這
        句話。token 面板該不該顯示（守祕密）與這句話該怎麼寫（陳述事實）是兩個
        問題，本測試釘住它們不會再被合併成一個旗標。"""
        access_auth.set_auth(True, "AB12")
        browser_token = access_auth.attempt_pin("AB12")
        assert browser_token is not None
        client = TestClient(app, client=REMOTE_CLIENT)
        client.cookies.set("sid", browser_token)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert "已設定密碼保護" in resp.text
        assert "本程式不設帳號密碼" not in resp.text
        # 同一個回應仍然不得夾帶 token（兩個旗標分開之後這條更需要正向釘住）
        assert ANCHOR_CLASS.encode() not in resp.content
        assert b"oav_" not in resp.content

    def test_auth_disabled_keeps_the_original_security_copy(self):
        """反向：認證關閉時仍是原本那句（AC8——那句話在關閉時完全正確）。"""
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert "本程式不設帳號密碼" in resp.text
        assert "已設定密碼保護" not in resp.text


class TestColdSnapshotCacheDoesNotCrash:
    # [lint-guard: pytest-justified] 時序契約（重啟後第一個請求 snapshot 為冷）——
    # 靜態掃描沒有「第幾個請求」這個維度。
    def test_cold_cache_still_200(self):
        access_auth.set_auth(True, "AB12")
        access_auth.reset_state_for_tests()  # 模擬重啟後 snapshot() 回 None
        client = TestClient(app, client=LOOPBACK_CLIENT)
        resp = client.get("/help")
        assert resp.status_code == 200
        assert ANCHOR_CLASS.encode() in resp.content  # 冷路徑補完後仍要正確顯示
