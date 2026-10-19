"""171-T3：POST /api/translate 失敗帶 reason（blocked／rate_limited／other）。"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.cloud_translate import TranslateError
from core.translate_service import OllamaTranslateService
from web.app import app

client = TestClient(app)
CFG = {"translate": {"enabled": True}}


def _post():
    return client.post("/api/translate", json={"text": "テスト", "mode": "translate"})


def _engine(side_effect=None, return_value=None):
    svc = AsyncMock()
    svc.translate_or_raise = AsyncMock(side_effect=side_effect, return_value=return_value)
    return svc


@pytest.mark.parametrize("kind,reason", [("blocked", "blocked"), ("rate_limited", "rate_limited"), ("truncated", "other")])
def test_error_kinds_map_to_reason(kind, reason):
    svc = _engine(side_effect=TranslateError(kind, None, "", "x"))
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data == {"success": False, "error": "翻譯結果為空", "reason": reason}


def test_blocked_error_returns_blocked_reason():
    svc = _engine(side_effect=TranslateError("blocked", None, "SAFETY", "x"))
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data["success"] is False
    assert data["reason"] == "blocked"
    assert data["error"] == "翻譯結果為空"


def test_ollama_empty_result_reason_other():
    svc = OllamaTranslateService({"url": "http://localhost:1", "model": "m"}, "zh-TW")
    svc.translate_single = AsyncMock(return_value="")
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data["success"] is False
    assert data["reason"] == "other"
    assert data["error"] == "翻譯結果為空"


def test_success_has_no_reason():
    svc = _engine(return_value="譯文")
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data == {"success": True, "result": "譯文", "mode": "translate"}


def test_unexpected_exception_reason_other():
    svc = _engine(side_effect=RuntimeError("boom"))
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data == {"success": False, "error": "翻譯失敗", "reason": "other"}


def test_value_error_reason_other():
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", side_effect=ValueError("no key")):
        data = _post().json()
    assert data["error"] == "翻譯設定錯誤，請檢查 API Key 設定"
    assert data["reason"] == "other"
