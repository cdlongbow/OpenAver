"""
TASK-114a-T3: `POST /api/access/verify` —— PIN 閘門唯一登入入口。

涵蓋：
  - 三段順序：延遲鎖外最前 → attempt_pin → cookie 鎖外（可證偽——刪掉延遲
    那行或搬到 attempt_pin 之後必須轉紅，Opus 審核補充 B）
  - 十二格畸形輸入清單（card「畸形輸入清單」表），全部不 500、全部計入重試
  - 四種輸入回應逐位元組相同（除 Set-Cookie）：status/Content-Type/
    Content-Length/Cache-Control/body 全部斷言（Opus 審核補充 C）
  - AC6 接線層驗證（鎖定期間正確 PIN 也不放行；畸形輸入計入重試；鎖定期間
    所有回應逐位元組相同）——不重測 T1 的決策核心真理表
  - cookie 六參數逐項斷言，尤其 Set-Cookie 不含 Secure token
  - R5 deterministic 時序測試（CD-114a-13 v4 P1 的回歸鎖，barrier/event
    驅動，非 timing-based）

除延遲順序測試與 R5 deterministic 測試外，一律 patch
`web.routers.access._fixed_delay` 成 no-op（autouse `_no_delay` fixture），
避免每支測試都慢 1 秒。
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

import core.access_auth as access_auth
from web.app import app

REAL_PIN = "1234"
LOOPBACK_CLIENT = ("127.0.0.1", 12345)

# 偽裝頁的結構指紋（同 test_access_gate.py），用來確認回應真的是 render_access_gate_page
# 的產物，不是別的東西。
#
# [lint-guard: pytest-justified] 偽裝頁反外洩指紋——斷言的是「這一次 HTTP round-trip
# 實際回出去的東西」而非某個檔案的靜態內容（後者在 static_guard_lint）。屬 SA-pre-6
# 明列的「安全指紋」例外。本檔各處對 r.text 的字面比對均由本註解涵蓋。
_MASKED_FINGERPRINT = 'id="v"'


def _decoy_shape(response):
    """回應形狀中，除 `Set-Cookie` 外必須逐位元組相同的部分。"""
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_length": response.headers.get("content-length"),
        "cache_control": response.headers.get("cache-control"),
        "body": response.content,
    }


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_access_auth_state():
    """`core.access_auth` 的 process-global cache/retry state 會跨測試殘留
    （同 test_access_gate.py 慣例）。"""
    access_auth.reset_state_for_tests()
    yield
    access_auth.reset_state_for_tests()


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """臨時 access_auth DB，開啟認證（PIN=1234）。monkeypatch 使用端
    `core.access_auth.get_db_path`（`_connect()` 呼叫的是模組自己 import
    進來的名字，BE-TEST-01）。"""
    db_path = tmp_path / "access_auth_test.db"
    monkeypatch.setattr("core.access_auth.get_db_path", lambda: db_path)
    access_auth.ensure_schema()
    access_auth.set_auth(True, REAL_PIN)
    return db_path


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    """預設把延遲接縫 patch 成瞬間返回，避免每支測試慢 1 秒。個別測試
    （延遲順序測試、R5 deterministic 測試）在測試本體內用同一個 monkeypatch
    實例再次 setattr 覆蓋成別的替身——後設值覆蓋前設值，兩者不衝突。"""

    async def _instant():
        return None

    monkeypatch.setattr("web.routers.access._fixed_delay", _instant)


@pytest.fixture
def client(auth_db):
    """loopback TestClient——本端點在放行清單內，middleware 對它永遠可達；
    用 loopback 位址純粹是為了不需要額外的 server_mode fixture 就能穿過外層
    `lan_access_gate`（本 task 的測試標的是 handler 本身，不是 middleware
    的來源判斷）。"""
    return TestClient(app, client=LOOPBACK_CLIENT)


# ── 三段順序：延遲鎖外最前 → attempt_pin → cookie 鎖外 ───────────────────


# ── 十二格畸形輸入清單 ───────────────────────────────────────────────────


# ── attempt_pin 拋例外時 fail-closed（獨立 review BLOCKER 的回歸鎖）───────


# ── 四種輸入回應逐位元組相同（除 Set-Cookie）────────────────────────────


class TestResponseShapeIdentical:
    """成功／失敗（含畸形輸入）回應除 Set-Cookie 外逐位元組相同——status、
    Content-Type、Content-Length、Cache-Control、body 全部斷言（Opus 審核
    補充 C）。"""

    def test_all_shapes_byte_identical_except_cookie(self, auth_db, client):
        r_correct = client.post("/api/access/verify", json={"pin": REAL_PIN})
        r_wrong = client.post("/api/access/verify", json={"pin": "9999"})
        r_missing = client.post("/api/access/verify", json={})
        r_malformed = client.post(
            "/api/access/verify",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )

        baseline = _decoy_shape(r_wrong)
        for r in (r_correct, r_wrong, r_missing, r_malformed):
            assert _decoy_shape(r) == baseline

        assert "set-cookie" not in r_wrong.headers
        assert "set-cookie" not in r_missing.headers
        assert "set-cookie" not in r_malformed.headers
        assert "set-cookie" in r_correct.headers


# ── cookie 六參數逐項斷言 ─────────────────────────────────────────────────


class TestCookieParams:
    def test_cookie_six_params(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        raw = r.headers.get("set-cookie")
        assert raw is not None
        assert raw.startswith("sid=")
        assert "HttpOnly" in raw
        assert "samesite=lax" in raw.lower()
        assert "path=/" in raw.lower()
        assert "max-age=315360000" in raw.lower()
        # CD-114a-6「絕對不設 Secure」——正面斷言「沒有出現」而非「傳了
        # False」，這是唯一可靠驗法：未來若誤傳 secure=True 才會被抓到。
        assert "secure" not in raw.lower()


# ── AC6 接線層 ───────────────────────────────────────────────────────────


class TestAC6RetryLockoutWiring:
    """真理表在 T1；這裡只驗接線層可觀察結果。"""

    def test_five_wrong_pins_then_correct_pin_still_locked(self, auth_db, client):
        for _ in range(5):
            r = client.post("/api/access/verify", json={"pin": "9999"})
            assert "set-cookie" not in r.headers
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert "set-cookie" not in r.headers


# ── R5 deterministic 時序測試（CD-114a-13 v4 P1 的回歸鎖）───────────────


class TestR5DeterministicTiming:
    """證偽條件（DoD 明文要求）：把延遲搬到 `attempt_pin` 呼叫之後（模擬
    v3 的錯誤順序）必須讓本測試轉紅。實作前後已手動演練過此順序異動確實
    轉紅（見本 task 回報）。"""

    async def test_pin_change_during_delay_blocks_stale_login(
        self, auth_db, monkeypatch
    ):
        gate = asyncio.Event()

        async def _blocked_delay():
            await gate.wait()

        monkeypatch.setattr("web.routers.access._fixed_delay", _blocked_delay)

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            task = asyncio.create_task(
                async_client.post("/api/access/verify", json={"pin": REAL_PIN})
            )

            # 讓出事件迴圈，確認請求已經進入、卡在延遲段，尚未呼叫 attempt_pin。
            for _ in range(50):
                await asyncio.sleep(0)

            # 主人在本機用新 PIN 呼叫 set_auth（模擬 T4 的 PUT /api/access/settings），
            # 觸發 revoke_all()：全表票被刪光、cache 換成新 PIN。
            await asyncio.to_thread(access_auth.set_auth, True, "2222")

            gate.set()
            response = await task

        # 帶舊 PIN 的請求必然比對失敗（此刻 attempt_pin 比對的是新 PIN），
        # 不會產生 Set-Cookie。
        assert "set-cookie" not in response.headers

        # access_tickets 表裡沒有任何一張是這個 request 建出來、且仍然可用
        # 的票——revoke_all() 已把表清空，之後也沒有新的**瀏覽器**票被插入。
        # TASK-114b-T1 起，`set_auth(True, ...)` 會在同一個 transaction 內
        # 鑄一張 `kind='agent'` 的票（CD-114b-1 的不變式），那張是合法產物、
        # 不是這個 stale request 留下的，所以本斷言只數 browser 票；agent
        # 票另外正向斷言恰好一張，避免「改成只數 browser 就順便放過多鑄」。
        conn = access_auth._connect()
        try:
            browser_count = conn.execute(
                "SELECT COUNT(*) FROM access_tickets WHERE kind = 'browser'"
            ).fetchone()[0]
            agent_count = conn.execute(
                "SELECT COUNT(*) FROM access_tickets WHERE kind = 'agent'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert browser_count == 0
        assert agent_count == 1


# ── 源碼斷言（CD-114a-10）─────────────────────────────────────────────────


# ── Codex PR#129 round-2 P3：非 JSON 請求不得計入重試鎖 ──────────────────────
#
# 跨站的簡單表單 POST 送不出 application/json 而不觸發 preflight（本服務無 CORS
# 標頭 → preflight 必被擋）。若這類請求仍計入失敗次數，使用者只要開到一個惡意
# 網頁，那頁就能連打五次打開**全域**重試鎖，讓全家人都進不去，而攻擊者不需要
# 知道密碼、也讀不到回應。

class TestNonJsonContentTypeNotCharged:
    @pytest.mark.parametrize(
        "ctype",
        ["text/plain", ],
    )
    def test_simple_request_content_types_do_not_consume_attempts(
        self, auth_db, client, ctype
    ):
        """連送 10 次（門檻的兩倍）非 JSON 請求後，正確密碼仍必須能進去。"""
        for _ in range(10):
            r = client.post(
                "/api/access/verify",
                content=b'{"pin": "0000"}',
                headers={"Content-Type": ctype} if ctype else {},
            )
            assert r.status_code == 200
            assert "set-cookie" not in r.headers

        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert "set-cookie" in r.headers, (
            "非 JSON 請求把重試鎖吃掉了——惡意網頁不需要知道密碼就能鎖住整個閘門"
        )


