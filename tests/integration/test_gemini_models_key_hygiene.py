"""171-T3：/api/gemini/test（模型清單）金鑰衛生——strip、LocalProtocolError 不洩金鑰。"""

import logging
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)
FAKE_KEY = "FAKEKEY-xyz"


def _cm(get):
    mock_client = AsyncMock()
    mock_client.get = get
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_client


def test_models_illegal_key_no_leak(caplog):
    get = AsyncMock(side_effect=httpx.LocalProtocolError(f"Illegal header value b'{FAKE_KEY}\\n'"))
    cm, _ = _cm(get)
    with patch("web.routers.gemini.httpx.AsyncClient", return_value=cm), caplog.at_level(logging.DEBUG):
        response = client.post("/api/gemini/test", json={"api_key": FAKE_KEY + "\n"})
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Invalid API Key"
    assert FAKE_KEY not in str(data)
    assert FAKE_KEY not in caplog.text


