"""
Claude API router integration tests (TASK-170-T3).

Covers /api/claude/models and /api/claude/test.
Patch layers:
- behaviour / kind mapping → web.routers.claude_translate.{list_models,request_translation}
- end-to-end classifier wiring → core.anthropic_client.httpx.AsyncClient
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from core.anthropic_client import DEFAULT_CLAUDE_MODEL, AnthropicError
from core.config import ClaudeConfig
from web.app import app

client = TestClient(app)

TEST_KEY = "sk-ant-test-key-aaaa"

# 11 AnthropicError.kind → router error key (CD-170-5)
KIND_TO_ERROR = [
    ("auth_failed", "auth_failed"),
    ("forbidden", "forbidden"),
    ("not_found", "not_found"),
    ("rate_limited", "rate_limited"),
    ("connection_timeout", "connection_timeout"),
    ("connection_failed", "connection_failed"),
    ("http_error", "http_error"),
    ("refused", "translate_failed"),
    ("truncated", "translate_failed"),
    ("empty_response", "translate_failed"),
    ("api_error", "translate_failed"),
]


def _cfg(locale: str = "zh-TW", api_key: str = TEST_KEY) -> dict:
    return {
        "general": {"locale": locale},
        "translate": {"claude": {"api_key": api_key}},
    }


def _make_mock_httpx_client(get_response=None, post_response=None, raise_on_get=None, raise_on_post=None):
    mock_client = AsyncMock()
    if raise_on_get is not None:
        mock_client.get = AsyncMock(side_effect=raise_on_get)
    elif get_response is not None:
        mock_client.get = AsyncMock(return_value=get_response)
    if raise_on_post is not None:
        mock_client.post = AsyncMock(side_effect=raise_on_post)
    elif post_response is not None:
        mock_client.post = AsyncMock(return_value=post_response)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_client


def _http_response(status_code: int, json_body: dict | None = None, reason_phrase: str = ""):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.reason_phrase = reason_phrase
    if json_body is not None:
        mock_resp.json = MagicMock(return_value=json_body)
    else:
        mock_resp.json = MagicMock(side_effect=ValueError("no json"))
    return mock_resp


# ===========================================================================
# /api/claude/models
# ===========================================================================

class TestClaudeModels:
    def test_models_filtered_sorted_with_latest_haiku(self):
        """opus filtered out; haiku/sonnet sorted newest-first; latest row is sonnet → latest_haiku still haiku."""
        upstream = {
            "data": [
                {"id": "claude-opus-4", "created_at": "2025-05-01T00:00:00Z"},
                {"id": "claude-haiku-3", "created_at": "2024-06-01T00:00:00Z"},
                {"id": "claude-sonnet-4", "created_at": "2025-06-01T00:00:00Z"},
                {"id": "claude-haiku-4", "created_at": "2025-03-01T00:00:00Z"},
            ]
        }
        with patch(
            "web.routers.claude_translate.list_models",
            new=AsyncMock(return_value=upstream),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post("/api/claude/models", json={"api_key": TEST_KEY})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["models"] == [
            "claude-sonnet-4",
            "claude-haiku-4",
            "claude-haiku-3",
        ]
        assert data["latest_haiku"] == "claude-haiku-4"
        assert data["default_model"] == "claude-haiku-5-5"
        assert data["error"] == ""

    def test_models_no_haiku_latest_empty(self):
        upstream = {
            "data": [
                {"id": "claude-sonnet-4", "created_at": "2025-06-01T00:00:00Z"},
                {"id": "claude-opus-4", "created_at": "2025-01-01T00:00:00Z"},
            ]
        }
        with patch(
            "web.routers.claude_translate.list_models",
            new=AsyncMock(return_value=upstream),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post("/api/claude/models", json={"api_key": TEST_KEY})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["models"] == ["claude-sonnet-4"]
        assert data["latest_haiku"] == ""
        assert data["default_model"] == DEFAULT_CLAUDE_MODEL

    def test_models_missing_key(self):
        mock_list = AsyncMock()
        with patch(
            "web.routers.claude_translate.list_models",
            new=mock_list,
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(api_key=""),
        ):
            resp = client.post("/api/claude/models", json={"api_key": ""})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "missing_key"
        assert data["default_model"] == DEFAULT_CLAUDE_MODEL
        mock_list.assert_not_called()

    def test_models_unexpected_exception_not_500(self):
        with patch(
            "web.routers.claude_translate.list_models",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post("/api/claude/models", json={"api_key": TEST_KEY})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "http_error"
        assert data["default_model"] == DEFAULT_CLAUDE_MODEL
        assert "boom" not in resp.text
        assert TEST_KEY not in resp.text


# ===========================================================================
# /api/claude/test — kind mapping + ja_skip + validation + fallback
# ===========================================================================

class TestClaudeTranslate:
    @pytest.mark.parametrize("kind,expected", KIND_TO_ERROR)
    def test_error_kind_maps_to_error_key(self, kind, expected):
        """Table-driven: each AnthropicError.kind maps via module ERROR_KIND_MAP (BE-TEST-23)."""
        with patch(
            "web.routers.claude_translate.request_translation",
            new=AsyncMock(side_effect=AnthropicError(kind, 400, "", "")),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": TEST_KEY, "model": "claude-haiku-5-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == expected

    def test_test_endpoint_ja_locale_skips_upstream(self):
        mock_rt = AsyncMock()
        with patch(
            "web.routers.claude_translate.request_translation",
            new=mock_rt,
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(locale="ja"),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": TEST_KEY, "model": "claude-haiku-5-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["translation"] == "ja_skip"
        mock_rt.assert_not_called()

    def test_test_missing_model(self):
        mock_rt = AsyncMock()
        with patch(
            "web.routers.claude_translate.request_translation",
            new=mock_rt,
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": TEST_KEY, "model": ""},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "missing_model"
        mock_rt.assert_not_called()

    def test_test_missing_key(self):
        mock_rt = AsyncMock()
        with patch(
            "web.routers.claude_translate.request_translation",
            new=mock_rt,
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(api_key=""),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": "", "model": "claude-haiku-5-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "missing_key"
        mock_rt.assert_not_called()

    def test_test_endpoint_unexpected_exception_not_500(self, caplog):
        with patch(
            "web.routers.claude_translate.request_translation",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            with caplog.at_level("ERROR"):
                resp = client.post(
                    "/api/claude/test",
                    json={"api_key": TEST_KEY, "model": "claude-haiku-5-5"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "translate_failed"
        assert TEST_KEY not in resp.text
        assert TEST_KEY not in caplog.text

    def test_test_success(self):
        with patch(
            "web.routers.claude_translate.request_translation",
            new=AsyncMock(return_value="新人女演員出道"),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": TEST_KEY, "model": "claude-haiku-5-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["translation"] == "新人女演員出道"
        assert data["error"] == ""


# ===========================================================================
# End-to-end: router ↔ T1 classifier via real httpx.AsyncClient patch
# ===========================================================================

class TestClaudeE2EClassifier:
    """Prove router wires AnthropicError kinds from anthropic_client, not only mocked kinds."""

    @pytest.mark.parametrize(
        "setup,expected",
        [
            (
                {"status": 401, "body": {"error": {"type": "authentication_error", "message": "bad key"}}},
                "auth_failed",
            ),
            (
                {"status": 404, "body": {"error": {"type": "not_found_error", "message": "model gone"}}},
                "not_found",
            ),
            (
                {"status": 429, "body": {"error": {"type": "rate_limit_error", "message": "slow down"}}},
                "rate_limited",
            ),
            (
                {
                    "status": 400,
                    "body": {
                        "error": {
                            "type": "invalid_request_error",
                            "message": "Your credit balance is too low",
                        }
                    },
                },
                "rate_limited",
            ),
            ({"raise": httpx.TimeoutException("timed out")}, "connection_timeout"),
            ({"raise": httpx.ConnectError("refused")}, "connection_failed"),
            (
                {
                    "status": 200,
                    "body": {
                        "stop_reason": "max_tokens",
                        "content": [{"type": "text", "text": "半句"}],
                    },
                },
                "translate_failed",
            ),
        ],
        ids=[
            "401_auth",
            "404_not_found",
            "429_rate",
            "400_credit",
            "timeout",
            "connect",
            "max_tokens",
        ],
    )
    def test_e2e_upstream_maps_to_error_key(self, setup, expected):
        if "raise" in setup:
            cm, _ = _make_mock_httpx_client(raise_on_post=setup["raise"])
        else:
            cm, _ = _make_mock_httpx_client(
                post_response=_http_response(setup["status"], setup["body"])
            )

        with patch(
            "core.anthropic_client.httpx.AsyncClient",
            return_value=cm,
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post(
                "/api/claude/test",
                json={"api_key": TEST_KEY, "model": "claude-haiku-5-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == expected


# ===========================================================================
# Four-leg default model reconcile (T2 DoD ③ fourth leg, filled in T3)
# ===========================================================================

class TestDefaultModelReconcile:
    def test_default_model_four_way_reconcile(self):
        upstream = {"data": [{"id": "claude-haiku-4", "created_at": "2025-03-01T00:00:00Z"}]}
        with patch(
            "web.routers.claude_translate.list_models",
            new=AsyncMock(return_value=upstream),
        ), patch(
            "web.routers.claude_translate.load_config",
            return_value=_cfg(),
        ):
            resp = client.post("/api/claude/models", json={"api_key": TEST_KEY})

        assert resp.status_code == 200
        data = resp.json()
        default_json = json.loads(
            Path("web/config.default.json").read_text(encoding="utf-8")
        )
        assert data["default_model"] == DEFAULT_CLAUDE_MODEL
        assert ClaudeConfig().model == DEFAULT_CLAUDE_MODEL
        assert default_json["translate"]["claude"]["model"] == DEFAULT_CLAUDE_MODEL
        assert data["default_model"] == ClaudeConfig().model
