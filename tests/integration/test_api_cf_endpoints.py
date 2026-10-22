"""
tests/integration/test_api_cf_endpoints.py — TASK-70-T6
========================================================
Integration tests for /api/cf/status, /api/cf/abandon,
rescrape_preview CF exceptions, and mounting guard.

Uses FastAPI TestClient (client fixture from conftest.py).
"""
import pytest
from unittest.mock import MagicMock

from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.scrapers.javlibrary import JAVLIBRARY_ORIGIN


# ── /api/cf/status ────────────────────────────────────────────────────────────

class TestCfStatusEndpoint:
    """GET /api/cf/status — transport probe 端點。"""


    def test_status_with_transport_is_ready_true(self, client, mocker):
        """transport 存在，is_ready=True → {ready: true}。"""
        mock_t = MagicMock()
        mock_t.is_ready.return_value = True
        mocker.patch("web.routers.cf.get_cf_transport", return_value=mock_t)
        resp = client.get("/api/cf/status")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


    def test_status_dead_transport_returns_unavailable(self, client, mocker):
        """
        CD-70c-2/3: transport is_ready() raises CfTransportUnavailable (window dead)
        → {ready: false, unavailable: true}, not {ready: false}.
        This is distinct from the None-transport path (which also → unavailable:true)
        and from a transient JS error (RuntimeError → {ready:false} without unavailable).
        """
        mock_t = MagicMock()
        mock_t.is_ready.side_effect = CfTransportUnavailable("JL window destroyed")
        mocker.patch("web.routers.cf.get_cf_transport", return_value=mock_t)
        resp = client.get("/api/cf/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data.get("unavailable") is True, (
            f"Dead transport must return unavailable:true, got: {data!r}"
        )


# ── /api/cf/abandon ──────────────────────────────────────────────────────────


class TestCfAbandonShellLost:
    """TASK-168d-T2 / CD-168d-12：abandon 依「這台殼剛失聯」選通知文案。"""

    @pytest.fixture
    def lost_shell(self, monkeypatch):
        import time

        from core import cf_handoff
        from core.cf_transport import get_cf_transport, register_cf_transport

        broker = cf_handoff.Broker()
        monkeypatch.setattr(cf_handoff, "_broker", broker)
        prev = get_cf_transport()
        register_cf_transport(cf_handoff.transport())
        tok = cf_handoff.current_key.set(cf_handoff._UNSET)
        broker.register_shell("loopback", ["javlibrary"])
        # 殼過期（> LIVENESS_S 沒再回報）→ is_ready 立即失敗並記下 shell_lost
        monkeypatch.setattr(cf_handoff, "_now", lambda: time.monotonic() + cf_handoff.LIVENESS_S + 100)
        yield broker
        cf_handoff.current_key.reset(tok)
        register_cf_transport(prev)

    def test_abandon_after_shell_lost_emits_cf_shell_lost(self, client, mocker, lost_shell):
        mock_emit = mocker.patch("web.routers.cf.emit_notification")
        status = client.get("/api/cf/status", params={"key": "javlibrary"})
        assert status.json() == {"ready": False, "unavailable": True}
        client.post("/api/cf/abandon")
        assert mock_emit.call_args.args[:2] == ("warn", "notif.cf_shell_lost")
        assert mock_emit.call_args.kwargs["task_type"] == "cf_abandon"

    def test_abandon_without_any_loss_keeps_timeout_text(self, client, mocker, lost_shell):
        mock_emit = mocker.patch("web.routers.cf.emit_notification")
        client.post("/api/cf/abandon", params={"key": "fc-javten"})
        assert mock_emit.call_args.args[1] == "notif.jl_cf_timeout"


# ── /api/rescrape/preview CF 例外處理 ─────────────────────────────────────────

class TestRescrapePreviewCfExceptions:
    """rescrape_preview_endpoint 對 CF 例外的回應。"""

    def test_cf_challenge_required_returns_cf_needed(self, client, mocker):
        """CfChallengeRequired → {success:false, cf_needed:true}，begin_solve 被呼叫。"""
        # source=javlibrary 現在走 search_javlib_versions 分支（T2），不再走 search_jav_single_source
        mocker.patch(
            "web.routers.scraper.search_javlib_versions",
            side_effect=CfChallengeRequired("CF challenge"),
        )
        mock_transport = MagicMock()
        mocker.patch("web.routers.scraper.get_cf_transport", return_value=mock_transport)

        resp = client.post("/api/rescrape/preview", json={
            "number": "SONE-205",
            "source": "javlibrary",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False
        assert data.get("cf_needed") is True
        mock_transport.begin_solve.assert_called_once_with(JAVLIBRARY_ORIGIN, 'javlibrary')

    def test_cf_transport_unavailable_returns_cf_unavailable(self, client, mocker):
        """CfTransportUnavailable → {success:false, cf_unavailable:true}，begin_solve 不被呼叫。"""
        # source=javlibrary 現在走 search_javlib_versions 分支（T2），不再走 search_jav_single_source
        mocker.patch(
            "web.routers.scraper.search_javlib_versions",
            side_effect=CfTransportUnavailable("no transport"),
        )
        mock_transport = MagicMock()
        mocker.patch("web.routers.scraper.get_cf_transport", return_value=mock_transport)

        resp = client.post("/api/rescrape/preview", json={
            "number": "SONE-205",
            "source": "javlibrary",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False
        assert data.get("cf_unavailable") is True
        mock_transport.begin_solve.assert_not_called()  # CfTransportUnavailable 不應觸發 begin_solve


# ── mounting guard ────────────────────────────────────────────────────────────


# ── FIX-2: /api/search?source=javlibrary CfChallengeRequired → 非 500 ──────────

class TestSearchJavlibraryCfExceptions:
    """FIX-2: GET /api/search?source=javlibrary 觸發 CF 例外 → 結構化非 500 回應。"""

    def test_cf_challenge_required_returns_non_500(self, client, mocker):
        """CfChallengeRequired → 200 + success:false + error 欄位（非 500）。"""
        # search_jav_single_source 在 search() 函式內以 local import 引入，
        # patch target 為 core.scraper 模組的屬性（local import 路徑）。
        mocker.patch(
            "core.scraper.search_jav_single_source",
            side_effect=CfChallengeRequired("CF challenge"),
        )
        resp = client.get("/api/search", params={"q": "TCD-332", "mode": "exact", "source": "javlibrary"})
        assert resp.status_code == 200, (
            f"CfChallengeRequired 不應產生 500，got: {resp.status_code}"
        )
        data = resp.json()
        assert data.get("success") is False
        assert "error" in data
        assert data.get("data") == []
        assert data.get("total") == 0


# ── FIX-3: begin_solve 拋例外 → cf_unavailable ───────────────────────────────

