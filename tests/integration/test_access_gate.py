"""
TASK-114a-T2: 認證閘門 middleware（`web.app.access_gate`）行為矩陣。

涵蓋：
  - AC1 deny-by-default 逐路徑（10 條 HTML 頁 + /motion-lab + /static + 23 支
    router 代表端點 + 4 支具名 API）
  - AC2 四種 loopback 形狀（server_mode=True 下）
  - 放行清單長度 == 2，且 (method, path) 落空不得變 404
  - GET /api/health 雙形狀
  - §4.4 分流（帶/不帶 Authorization）
  - request.client is None 邊界（Opus 補充 C）
  - 冷載（TestClient(app) 非 context manager）第一個請求仍正確判斷

不動 tests/integration/test_server_mode_gate.py（唯讀，AC8）。
"""
import sqlite3
from unittest.mock import patch

import pytest
import core.access_auth as access_auth
from fastapi.testclient import TestClient

from core.version import VERSION
from web.app import _AUTH_ALLOWLIST, _HEALTH_ENDPOINT, _VERIFY_ENDPOINT, app

REMOTE_CLIENT = ("192.168.1.50", 12345)
LOOPBACK_V4 = ("127.0.0.1", 12345)
LOOPBACK_V6 = ("::1", 12345)
LOOPBACK_LOCALHOST_NAME = ("localhost", 12345)
LOOPBACK_V4_MAPPED = ("::ffff:127.0.0.1", 12345)

# 偽裝頁的結構指紋：id="v" 只存在於 access_gate.html，不會出現在任何真實頁面/
# JSON 回應裡，用它判斷「這次回應是不是偽裝頁」比對整份 HTML 更不脆弱。
_MASKED_FINGERPRINT = 'id="v"'


def _assert_masked(response):
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert _MASKED_FINGERPRINT in response.text
    assert "OpenAver" not in response.text


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_access_auth_state():
    """`core.access_auth` 的 process-global cache/retry state 會跨測試殘留
    （T1 模組已提供 `reset_state_for_tests()` 這個測試專用 seam）。"""
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """臨時 access_auth DB，開啟認證（PIN=1234）。

    monkeypatch `core.access_auth.get_db_path`（use-site binding，非
    `core.database.connection.get_db_path`）——`_connect()` 在
    `core/access_auth.py` 內呼叫的是模組自己 import 進來的名字。
    """
    db_path = tmp_path / "access_auth_test.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, "1234")
    return db_path


@pytest.fixture
def server_mode(monkeypatch):
    """讓外層 `lan_access_gate` 放行非 loopback 流量。

    CD-114a-4 執行序：`lan_access_gate` 比本 task 的 `access_gate` 更外層、
    先執行——單機模式下它會先把遠端請求 403 掉，請求根本到不了本 task 的
    middleware。所有「非 loopback 的請求要真的碰到 access_gate」的測試都
    需要這個 fixture。"""
    monkeypatch.setattr(
        "web.app.load_config", lambda: {"general": {"server_mode": True}}
    )


@pytest.fixture
def gated_client(auth_db, server_mode):
    """非 loopback、認證已開啟、未帶任何票的 TestClient。"""
    return TestClient(app, client=REMOTE_CLIENT)


@pytest.fixture
def valid_token(auth_db):
    """直接呼叫 T1 的 `attempt_pin`（同步，非 HTTP）取得一張有效票——本 task
    不重測 attempt_pin 本身的正確性，只需要一張票來驗 middleware 的
    `authed` 分支。"""
    token = access_auth.attempt_pin("1234")
    assert token is not None
    return token


# ── AC1：deny-by-default 逐路徑 ─────────────────────────────────────────


class TestDenyByDefault:
    """未認證、非 loopback、認證已開啟時，以下路徑全部只看得到偽裝頁 200。"""

    # 10 條 HTML 頁面路由（含 / 與 /gallery 的 redirect，實測皆為 302 → 必須
    # 變成偽裝頁 200，不得回原本的 302）+ /motion-lab + /static。
    PAGE_ROUTES = [
        ("GET", "/"),
        ("GET", "/search"),
        ("GET", "/scraper"),
        ("GET", "/updater"),
        ("GET", "/scanner"),
        ("GET", "/gallery"),
        ("GET", "/showcase"),
        ("GET", "/settings"),
        ("GET", "/help"),
        ("GET", "/design-system"),
        ("GET", "/motion-lab"),
        ("GET", "/static/css/theme.css"),
    ]

    # 23 支 router 代表端點（每個 router 註冊各抽一支，見 task card「router
    # prefix 清單」）。
    ROUTER_ENDPOINTS = [
        ("GET", "/api/proxy-image"),
        ("GET", "/api/config"),
        ("POST", "/api/scrape-single"),
        ("POST", "/api/translate"),
        ("GET", "/api/gallery/generate"),
        ("POST", "/api/gemini/test"),
        ("POST", "/api/openai/models"),
        ("POST", "/api/parse-filename"),
        ("GET", "/api/showcase/videos"),
        ("GET", "/api/capabilities"),
        ("POST", "/api/collection/sql"),
        ("POST", "/api/user-tags"),
        ("POST", "/api/actresses/favorite"),
        ("GET", "/api/actress-aliases"),
        ("GET", "/api/tag-aliases"),
        ("GET", "/api/tags/top"),
        ("GET", "/api/notifications"),
        ("GET", "/api/similar-covers/by-number/0"),
        ("GET", "/api/settings/favorite-scanner-link"),
        ("GET", "/api/scraper-sources"),
        ("POST", "/api/settings/metatube/connect"),
        ("GET", "/api/cf/status"),
        ("POST", "/api/client-log"),
    ]

    # 4 支具名 API（CD-114a-8 明點；/api/capabilities 與上表重複抽樣，刻意
    # 不去重——它同時是「具名 API」與「router 代表端點」兩種身分）。
    NAMED_APIS = [
        ("GET", "/api/version"),
        ("GET", "/api/check-update"),
        ("GET", "/api/install-context"),
        ("GET", "/api/capabilities"),
    ]

    ALL_TARGETS = PAGE_ROUTES + ROUTER_ENDPOINTS + NAMED_APIS

    @pytest.mark.parametrize("method,path", ALL_TARGETS)
    def test_masked_page_for_every_path(self, gated_client, method, path):
        r = gated_client.request(method, path)
        _assert_masked(r)


# ── AC2：四種 loopback 形狀（server_mode=True 下）──────────────────────


class TestLoopbackShapes:
    """
    四種 loopback 形狀在認證開啟下一律免密碼（CD-114a-5：委派 `_is_loopback_host()`
    這個較寬的判斷，不是 middleware 短路用的窄 `_LOOPBACK_HOSTS`）。

    前提：這裡一律搭配 `server_mode` fixture（server_mode=True）——外層
    `lan_access_gate` 只認窄的 `_LOOPBACK_HOSTS`（僅 "127.0.0.1"/"::1" 兩個
    字面值），`localhost` 與 `::ffff:127.0.0.1` 在單機模式下會被外層先 403
    掉，永遠到不了本 task 的 middleware——這正是 AC2 DoD 要求附註的那句話。
    用 `/api/health` 驗證：loopback 短路發生在 middleware 最前面，連
    `snapshot()` 都不會被摸到，所以回應是逐位元組不變的已認證形狀
    `{"status": "ok", "version": VERSION}`。
    """

    @pytest.mark.parametrize(
        "peer",
        [LOOPBACK_V4, LOOPBACK_V6, LOOPBACK_LOCALHOST_NAME, LOOPBACK_V4_MAPPED],
    )
    def test_loopback_never_needs_pin(self, auth_db, server_mode, peer):
        c = TestClient(app, client=peer)
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": VERSION}


# ── 放行清單長度 + method/path 雙重比對 ─────────────────────────────────


class TestAllowlist:
    def test_allowlist_length_is_two(self):
        assert len(_AUTH_ALLOWLIST) == 2
        assert _AUTH_ALLOWLIST == frozenset({_VERIFY_ENDPOINT, _HEALTH_ENDPOINT})

    def test_mismatched_method_verify_path_falls_through_to_masked(
        self, gated_client
    ):
        """GET /api/access/verify（沒有人註冊這個 handler）：只比 path 會被
        call_next 放進路由層變成 404——那會洩漏「這裡有東西」。必須落到
        偽裝頁 200，不得是 404。"""
        r = gated_client.get("/api/access/verify")
        _assert_masked(r)

    def test_mismatched_method_health_path_falls_through_to_masked(
        self, gated_client
    ):
        """POST /api/health（同樣沒有 handler）：同上，必須是偽裝頁 200 不是
        404。"""
        r = gated_client.post("/api/health")
        _assert_masked(r)


# ── GET /api/health 雙形狀 ───────────────────────────────────────────────


class TestHealthDualShape:
    def test_unauthenticated_gets_minimal_shape_handler_not_called(
        self, gated_client
    ):
        r = gated_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_authenticated_gets_full_shape_with_version(
        self, gated_client, valid_token
    ):
        gated_client.cookies.set("sid", valid_token)
        r = gated_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": VERSION}

    def test_health_with_authorization_header_but_unauthenticated_still_ok(
        self, gated_client
    ):
        """健康檢查不該因為呼叫端多帶了一個 header 就改變回應——放行清單
        優先於 401 分支（決策清單第 7 步在第 9 步之前）。"""
        r = gated_client.get(
            "/api/health", headers={"Authorization": "Bearer whatever"}
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ── §4.4 分流：帶／不帶 Authorization ────────────────────────────────────


class TestAuthorizationHeaderFlow:
    def test_with_authorization_header_gets_401_json(self, gated_client):
        r = gated_client.get("/search", headers={"Authorization": "Bearer x"})
        assert r.status_code == 401
        assert r.json() == {"success": False, "reason": "unauthorized"}

    def test_without_authorization_header_gets_masked_page(self, gated_client):
        r = gated_client.get("/search")
        _assert_masked(r)

    def test_verify_endpoint_bypasses_even_with_authorization_header(
        self, gated_client
    ):
        """POST /api/access/verify 帶 Authorization：仍走 call_next（第 6 步
        在第 9 步之前），不回 401——這支端點本來就是給沒有票的人用的。T2
        尚未建立真正的 handler（T3 的範圍），call_next 之後落到 FastAPI
        路由層的標準 404，但重點是**不是** 401 也**不是**偽裝頁。"""
        r = gated_client.post(
            "/api/access/verify",
            json={"pin": "0000"},
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 404
        assert r.status_code != 401
        assert _MASKED_FINGERPRINT not in r.text

    def test_authenticated_with_authorization_header_not_401(
        self, gated_client, valid_token
    ):
        """authed 判斷（第 8 步）在 401 分支（第 9 步）之前——已通過認證的
        使用者就算多帶了一個 Authorization header 也不該被攔。"""
        gated_client.cookies.set("sid", valid_token)
        r = gated_client.get("/search", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        assert _MASKED_FINGERPRINT not in r.text

    def test_auth_disabled_ignores_authorization_header(
        self, auth_db, server_mode
    ):
        """認證關閉時，第 4 步已經 call_next 放行，Authorization header 完全
        不影響行為（AC8 逐位元組不變的一部分）。"""
        access_auth.set_auth(False, "")
        c = TestClient(app, client=REMOTE_CLIENT)
        r = c.get("/search", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        assert _MASKED_FINGERPRINT not in r.text


# ── request.client is None（Opus 補充 C）────────────────────────────────


class TestClientNone:
    def test_none_client_denies_not_500(self, auth_db, server_mode):
        """`request.client is None` 是 ASGI 邊界的合法情況——`_is_loopback_host(None)`
        已經 fail-closed 回 False（web/app.py 的既有實作），本測試釘住整條路徑
        （middleware → 偽裝頁）不因為 client 是 None 而放行或 500。"""
        c = TestClient(app, client=None)
        r = c.get("/search")
        _assert_masked(r)


# ── lifecycle：冷載第一個請求 ─────────────────────────────────────────────


class TestColdCache:
    def test_first_request_with_cold_cache_reads_db_correctly(
        self, auth_db, server_mode
    ):
        """`TestClient(app)`（非 context manager）不觸發 lifespan，`ensure_schema()`
        沒跑過。`snapshot()` 此時是 None——middleware 必須自己冷載
        （`await asyncio.to_thread(ensure_schema)`）才能在第一個請求就正確
        判斷認證狀態，不能假設 lifespan 一定跑過。"""
        access_auth.reset_state_for_tests()
        assert access_auth.snapshot() is None

        c = TestClient(app, client=REMOTE_CLIENT)
        r = c.get("/search")
        _assert_masked(r)
        # 冷載發生後 cache 應該被暖起來，供後續請求零 DB 使用。
        assert access_auth.snapshot() is not None

    def test_cold_load_exception_falls_back_to_masked_not_500(
        self, auth_db, server_mode
    ):
        """冷載呼叫 `ensure_schema()` 若拋例外（DB 檔案壞掉、磁碟滿等），必須
        fail-closed 回偽裝頁，不能讓例外冒泡成 500——未認證訪客看到的東西
        必須永遠長一樣，500 錯誤頁是另一種形狀，本身就是一種洩漏。只有非
        loopback 流量走得到這裡，所以「DB 壞掉時擋住 LAN」不會把主人鎖在
        門外（他在自己機器上照常進得去）。"""
        access_auth.reset_state_for_tests()
        assert access_auth.snapshot() is None

        c = TestClient(app, client=REMOTE_CLIENT)
        with patch(
            "web.app.ensure_schema",
            side_effect=sqlite3.OperationalError("disk I/O error"),
        ):
            r = c.get("/search")
        _assert_masked(r)
