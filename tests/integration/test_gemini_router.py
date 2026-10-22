"""
Gemini API router integration tests — TDD-lite for allowlist filtering.

Covers POST /api/gemini/test endpoint.
Uses TestClient + mock httpx.AsyncClient (no real HTTP connections).
"""
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from web.app import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(get_response=None, raise_on_get=None):
    """Build a mock httpx.AsyncClient context-manager with configurable responses."""
    mock_client = AsyncMock()

    if raise_on_get is not None:
        mock_client.get = AsyncMock(side_effect=raise_on_get)
    elif get_response is not None:
        mock_client.get = AsyncMock(return_value=get_response)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_http_response(status_code: int, json_body: dict | None = None):
    """Build a minimal mock httpx.Response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    if json_body is not None:
        mock_resp.json = MagicMock(return_value=json_body)
    if status_code >= 400:
        request = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                message=f"HTTP {status_code}",
                request=request,
                response=mock_resp,
            )
        )
    else:
        mock_resp.raise_for_status = MagicMock(return_value=None)
    return mock_resp


def _make_api_models(*names: str) -> dict:
    """Build a Gemini-style API response dict with the given model short-names."""
    return {
        "models": [
            {
                "name": f"models/{n}",
                "displayName": n.replace("-", " ").title(),
                "description": f"Model {n}",
            }
            for n in names
        ]
    }


ALLOWLIST = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGeminiAllowlist:

    def test_all_four_allowlist_models_returned_in_order(self):
        """BC1: API 回傳全部 4 個 allowlist model → response models 長度 4，順序依 allowlist。"""
        body = _make_api_models(*ALLOWLIST)
        # Include some extra noise so filtering is exercised
        body["models"].append({
            "name": "models/gemini-1.5-flash",
            "displayName": "Gemini 1.5 Flash",
            "description": "Old model",
        })
        resp = _make_http_response(200, body)
        mock_cm = _make_mock_client(get_response=resp)

        with patch("web.routers.gemini.httpx.AsyncClient", return_value=mock_cm):
            response = client.post("/api/gemini/test", json={"api_key": "valid-key"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 4
        assert len(data["models"]) == 4
        names = [m["name"] for m in data["models"]]
        assert names == ALLOWLIST


    def test_invalid_api_key_400(self):
        """BC5: API Key 無效 (HTTP 400) → success=False + error 非空。"""
        resp = _make_http_response(400)
        mock_cm = _make_mock_client(get_response=resp)

        with patch("web.routers.gemini.httpx.AsyncClient", return_value=mock_cm):
            response = client.post("/api/gemini/test", json={"api_key": "bad-key"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"]  # 非空即可，不鎖定具體文案


