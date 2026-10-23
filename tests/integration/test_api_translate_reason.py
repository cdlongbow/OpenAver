"""171-T3：POST /api/translate 失敗帶 reason（blocked／rate_limited／other）。"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.cloud_translate import TranslateError
from web.app import app

client = TestClient(app)
CFG = {"translate": {"enabled": True}}


def _post():
    return client.post("/api/translate", json={"text": "テスト", "mode": "translate"})


def _engine(side_effect=None, return_value=None):
    svc = AsyncMock()
    svc.translate_or_raise = AsyncMock(side_effect=side_effect, return_value=return_value)
    return svc


@pytest.mark.parametrize("kind,reason", [("blocked", "blocked"), ("rate_limited", "rate_limited")])
def test_error_kinds_map_to_reason(kind, reason):
    svc = _engine(side_effect=TranslateError(kind, None, "", "x"))
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", return_value=svc):
        data = _post().json()
    assert data == {"success": False, "error": "翻譯結果為空", "reason": reason}


def test_value_error_reason_other():
    with patch("web.routers.translate.load_config", return_value=CFG), \
         patch("web.routers.translate.get_translate_service", side_effect=ValueError("no key")):
        data = _post().json()
    assert data["error"] == "翻譯設定錯誤，請檢查 API Key 設定"
    assert data["reason"] == "other"
