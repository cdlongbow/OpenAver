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
import pathlib
import sqlite3

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


class TestOrder:
    def test_delay_runs_before_attempt_pin(self, auth_db, monkeypatch, client):
        """不 patch 成 no-op，而是用能觀察順序的替身——刪掉 `await
        _fixed_delay()` 那行、或把它搬到 attempt_pin 之後，本測試必須轉紅
        （Opus 審核補充 B / CD-114a-13 v4 P1 的回歸鎖）。"""
        order = []

        async def _tracking_delay():
            order.append("delay")

        real_attempt_pin = access_auth.attempt_pin

        def _tracking_attempt_pin(candidate):
            order.append("attempt_pin")
            return real_attempt_pin(candidate)

        monkeypatch.setattr("web.routers.access._fixed_delay", _tracking_delay)
        monkeypatch.setattr("web.routers.access.attempt_pin", _tracking_attempt_pin)

        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert r.status_code == 200
        assert order == ["delay", "attempt_pin"], (
            f"expected delay to run before attempt_pin, got {order}"
        )


# ── 十二格畸形輸入清單 ───────────────────────────────────────────────────


class TestMalformedInputs:
    """card「畸形輸入清單」十二格——全部不 500、全部落到偽裝頁 200。"""

    def test_correct_pin_succeeds(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert r.status_code == 200
        assert "set-cookie" in r.headers

    def test_wrong_pin_correct_format(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": "9999"})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_missing_pin_field(self, auth_db, client):
        r = client.post("/api/access/verify", json={})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_pin_wrong_type_int(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": 42})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_pin_contains_whitespace(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": "12 3"})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_pin_wrong_length(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": "12345"})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_pin_unicode_digits(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": "१२३४"})
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_empty_body(self, auth_db, client):
        r = client.post(
            "/api/access/verify",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_non_json_text_body(self, auth_db, client):
        r = client.post(
            "/api/access/verify",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_top_level_json_array(self, auth_db, client):
        r = client.post("/api/access/verify", json=[1, 2, 3])
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_top_level_json_string_scalar(self, auth_db, client):
        r = client.post("/api/access/verify", json="a string")
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_top_level_json_number_scalar(self, auth_db, client):
        r = client.post("/api/access/verify", json=42)
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_top_level_json_null_scalar(self, auth_db, client):
        r = client.post(
            "/api/access/verify",
            content=b"null",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert "set-cookie" not in r.headers

    def test_extra_fields_ignored_same_result_as_correct(self, auth_db, client):
        r = client.post(
            "/api/access/verify", json={"pin": REAL_PIN, "extra": "x"}
        )
        assert r.status_code == 200
        assert "set-cookie" in r.headers

    def test_malformed_inputs_count_toward_retry_lockout(self, auth_db, client):
        """畸形輸入計入重試限制（不重測 T1 決策核心，只驗接線層可觀察結果）：
        連續 5 次缺欄位 → 緊接著送正確 PIN 仍鎖定。"""
        for _ in range(5):
            r = client.post("/api/access/verify", json={})
            assert "set-cookie" not in r.headers
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert "set-cookie" not in r.headers


# ── attempt_pin 拋例外時 fail-closed（獨立 review BLOCKER 的回歸鎖）───────


class TestAttemptPinFailsClosed:
    """DB 寫入失敗（磁碟滿／檔案被鎖）時，`attempt_pin` 的例外不得冒泡成
    500——那本身就是另一種「回應形狀跟平常不一樣」的洩漏，等同直接告訴
    未認證訪客「這裡真的在跑程式碼」。fail-closed：視同這次嘗試沒發生，
    回偽裝頁、不帶 cookie。

    mutation：拿掉 handler 裡 `attempt_pin` 呼叫外層的 try/except → 本測試
    必須轉紅（讓例外真的冒泡）。"""

    def test_attempt_pin_exception_returns_masked_not_500(
        self, auth_db, client, monkeypatch
    ):
        def _boom(candidate):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr("web.routers.access.attempt_pin", _boom)

        r = client.post("/api/access/verify", json={"pin": REAL_PIN})

        assert r.status_code == 200
        assert r.status_code != 500
        assert "set-cookie" not in r.headers
        assert _MASKED_FINGERPRINT in r.text
        assert r.headers.get("cache-control") == "no-store"


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

    def test_shape_is_the_masked_decoy_page(self, auth_db, client):
        """回應本體確實是 T2 的偽裝頁（同一份渲染函式的產物），不是第二份
        HTML。"""
        r = client.post("/api/access/verify", json={"pin": "9999"})
        assert _MASKED_FINGERPRINT in r.text
        assert "OpenAver" not in r.text
        assert r.headers.get("cache-control") == "no-store"


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

    def test_cookie_value_is_a_valid_verifiable_ticket(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        token = r.cookies.get("sid")
        assert token
        assert access_auth.verify_ticket(token) is True

    def test_no_cookie_header_at_all_on_failure(self, auth_db, client):
        r = client.post("/api/access/verify", json={"pin": "9999"})
        assert "set-cookie" not in r.headers


# ── AC6 接線層 ───────────────────────────────────────────────────────────


class TestAC6RetryLockoutWiring:
    """真理表在 T1；這裡只驗接線層可觀察結果。"""

    def test_five_wrong_pins_then_correct_pin_still_locked(self, auth_db, client):
        for _ in range(5):
            r = client.post("/api/access/verify", json={"pin": "9999"})
            assert "set-cookie" not in r.headers
        r = client.post("/api/access/verify", json={"pin": REAL_PIN})
        assert "set-cookie" not in r.headers

    def test_lockout_period_all_responses_byte_identical(self, auth_db, client):
        for _ in range(5):
            client.post("/api/access/verify", json={"pin": "9999"})

        baseline = None
        for _ in range(10):
            r = client.post("/api/access/verify", json={"pin": REAL_PIN})
            assert "set-cookie" not in r.headers
            shape = _decoy_shape(r)
            if baseline is None:
                baseline = shape
            else:
                assert shape == baseline


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
        # 的票——revoke_all() 已把表清空，之後也沒有新票被插入。
        conn = access_auth._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM access_tickets"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0


# ── 源碼斷言（CD-114a-10）─────────────────────────────────────────────────


class TestSourceGuards:
    def test_no_time_sleep_literal(self):
        src = (
            pathlib.Path(__file__).parents[2]
            / "web"
            / "routers"
            / "access.py"
        ).read_text(encoding="utf-8")
        assert "time.sleep" not in src
