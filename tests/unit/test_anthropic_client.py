"""
test_anthropic_client.py — Anthropic Messages API 請求／解析層單元測試

mock 一律 patch 使用端 core.anthropic_client.httpx.AsyncClient；
回應為內嵌合成 dict，不連真 API。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.anthropic_client import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_VERSION,
    DEFAULT_CLAUDE_MODEL,
    MAX_TOKENS,
    AnthropicError,
    build_headers,
    build_translate_payload,
    classify_http_error,
    extract_text,
    list_models,
    pick_translate_models,
    request_translation,
)


FAKE_KEY = "sk-ant-test-fake-key-not-real"


def _mock_response(*, status_code=200, json_data=None, reason_phrase="OK", json_side_effect=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = reason_phrase
    if json_side_effect is not None:
        resp.json.side_effect = json_side_effect
    else:
        resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _mock_async_client(post_return=None, get_return=None, post_side_effect=None, get_side_effect=None):
    client = MagicMock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ============ payload / headers (I2 oracle) ============


def test_payload_keys_exact():
    """payload key 集合恰為 {model, max_tokens, messages, output_config}"""
    payload = build_translate_payload("claude-haiku-5-5", "請翻譯：測試")
    assert set(payload.keys()) == {"model", "max_tokens", "messages", "output_config"}
    assert payload["max_tokens"] == MAX_TOKENS == 1024
    assert payload["output_config"] == {"effort": "low"}
    assert payload["model"] == "claude-haiku-5-5"
    assert payload["messages"] == [{"role": "user", "content": "請翻譯：測試"}]
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "system"):
        assert forbidden not in payload


def test_headers_include_anthropic_version():
    """headers 含 anthropic-version／x-api-key，不含 Authorization"""
    headers = build_headers(FAKE_KEY)
    assert headers["anthropic-version"] == ANTHROPIC_VERSION == "2023-06-01"
    assert headers["x-api-key"] == FAKE_KEY
    assert headers["content-type"] == "application/json"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_request_translation_i2_oracle_via_post():
    """request_translation 實際 post 的 json／headers 符合 I2"""
    ok = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "譯文"}],
    }
    client = _mock_async_client(post_return=_mock_response(json_data=ok))
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "prompt", timeout=30)

    assert result == "譯文"
    kwargs = client.post.call_args.kwargs
    assert set(kwargs["json"].keys()) == {"model", "max_tokens", "messages", "output_config"}
    assert kwargs["json"]["max_tokens"] == 1024
    assert kwargs["json"]["output_config"] == {"effort": "low"}
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["headers"]["x-api-key"] == FAKE_KEY
    assert "Authorization" not in kwargs["headers"]
    assert client.post.call_args.args[0] == f"{ANTHROPIC_BASE_URL}/v1/messages"


# ============ extract_text 區塊判定 ============


def test_extract_text_skips_thinking_block():
    """content=[thinking, text] → 只回 text；跳過 thinking"""
    data = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "先想一下…"},
            {"type": "text", "text": "  繁中譯文  "},
        ],
    }
    assert extract_text(data) == "繁中譯文"


def test_extract_text_thinking_only_is_empty_response():
    """content=[thinking] 單獨 → empty_response"""
    data = {
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": "只有思考"}],
    }
    with pytest.raises(AnthropicError) as ei:
        extract_text(data)
    assert ei.value.kind == "empty_response"


def test_extract_text_max_tokens_is_failure():
    """stop_reason=max_tokens 即使有 text 仍拋 truncated"""
    data = {
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": "半句譯文"}],
    }
    with pytest.raises(AnthropicError) as ei:
        extract_text(data)
    assert ei.value.kind == "truncated"


def test_extract_text_refusal_is_failure():
    """stop_reason=refusal 即使有 text 仍拋 refused"""
    data = {
        "stop_reason": "refusal",
        "content": [{"type": "text", "text": "我無法翻譯這個"}],
    }
    with pytest.raises(AnthropicError) as ei:
        extract_text(data)
    assert ei.value.kind == "refused"


# ============ classify_http_error ============


def test_classify_404_not_found():
    resp = _mock_response(
        status_code=404,
        json_data={"type": "error", "error": {"type": "not_found_error", "message": "model not found"}},
        reason_phrase="Not Found",
    )
    err = classify_http_error(resp)
    assert isinstance(err, AnthropicError)
    assert err.kind == "not_found"
    assert err.status == 404
    assert err.error_type == "not_found_error"


def test_classify_400_credit_balance_is_rate_limited():
    resp = _mock_response(
        status_code=400,
        json_data={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the Anthropic API.",
            },
        },
        reason_phrase="Bad Request",
    )
    err = classify_http_error(resp)
    assert err.kind == "rate_limited"
    assert err.status == 400


def test_classify_401_auth_failed():
    resp = _mock_response(
        status_code=401,
        json_data={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
    )
    err = classify_http_error(resp)
    assert err.kind == "auth_failed"


def test_classify_403_forbidden():
    resp = _mock_response(
        status_code=403,
        json_data={"type": "error", "error": {"type": "permission_error", "message": "no access"}},
    )
    err = classify_http_error(resp)
    assert err.kind == "forbidden"


def test_classify_429_rate_limited():
    resp = _mock_response(
        status_code=429,
        json_data={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
    )
    err = classify_http_error(resp)
    assert err.kind == "rate_limited"


def test_classify_502_non_json_is_http_error():
    """閘道 502 HTML → http_error，error_type==''，不拋 ValueError"""
    resp = _mock_response(
        status_code=502,
        reason_phrase="Bad Gateway",
        json_side_effect=ValueError("No JSON"),
    )
    err = classify_http_error(resp)
    assert err.kind == "http_error"
    assert err.error_type == ""
    assert err.message == "Bad Gateway"
    assert err.status == 502


def test_classify_logs_without_api_key(caplog):
    """log 含 error.type／message，不含金鑰"""
    import logging

    resp = _mock_response(
        status_code=401,
        json_data={
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        },
    )
    with caplog.at_level(logging.WARNING):
        # classify itself logs before returning (callers raise the returned error)
        err = classify_http_error(resp)
    assert err.kind == "auth_failed"
    joined = "\n".join(r.message for r in caplog.records)
    assert "authentication_error" in joined
    assert "invalid x-api-key" in joined
    assert FAKE_KEY not in joined
    assert "sk-ant-" not in joined


# ============ pick_translate_models ============


def test_pick_models_filters_opus():
    data = {
        "data": [
            {"id": "claude-opus-4-20250514", "created_at": "2025-05-14T00:00:00Z"},
            {"id": "claude-haiku-5-5", "created_at": "2025-10-01T00:00:00Z"},
            {"id": "claude-sonnet-4-20250514", "created_at": "2025-05-14T00:00:00Z"},
        ]
    }
    ids = pick_translate_models(data)
    assert all("opus" not in mid.lower() or "haiku" in mid.lower() or "sonnet" in mid.lower() for mid in ids)
    assert "claude-opus-4-20250514" not in ids
    assert "claude-haiku-5-5" in ids
    assert "claude-sonnet-4-20250514" in ids


def test_pick_models_sorted_newest_first():
    data = {
        "data": [
            {"id": "claude-haiku-old", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "claude-sonnet-new", "created_at": "2025-10-01T00:00:00Z"},
            {"id": "claude-haiku-mid", "created_at": "2025-06-01T00:00:00Z"},
        ]
    }
    ids = pick_translate_models(data)
    assert ids == ["claude-sonnet-new", "claude-haiku-mid", "claude-haiku-old"]


def test_pick_models_missing_created_at_last_stable():
    data = {
        "data": [
            {"id": "claude-haiku-a"},  # no created_at
            {"id": "claude-sonnet-dated", "created_at": "2025-01-01T00:00:00Z"},
            {"id": "claude-haiku-b"},  # no created_at
        ]
    }
    ids = pick_translate_models(data)
    assert ids[0] == "claude-sonnet-dated"
    # 缺 created_at 者排最後且彼此維持原順序
    assert ids[1:] == ["claude-haiku-a", "claude-haiku-b"]


def test_pick_models_mixed_case_kept():
    data = {
        "data": [
            {"id": "Claude-HAIKU-x", "created_at": "2025-01-01T00:00:00Z"},
            {"id": "CLAUDE-SONNET-y", "created_at": "2025-02-01T00:00:00Z"},
        ]
    }
    ids = pick_translate_models(data)
    assert "Claude-HAIKU-x" in ids
    assert "CLAUDE-SONNET-y" in ids


def test_pick_models_no_haiku_latest_empty():
    """無 haiku → 呼叫端取 latest_haiku 為空字串"""
    data = {
        "data": [
            {"id": "claude-sonnet-4", "created_at": "2025-05-01T00:00:00Z"},
        ]
    }
    ids = pick_translate_models(data)
    latest_haiku = next((m for m in ids if "haiku" in m.lower()), "")
    assert latest_haiku == ""
    assert ids == ["claude-sonnet-4"]


# ============ request_translation / list_models 整合行為 ============


@pytest.mark.asyncio
async def test_request_translation_api_error_missing_content():
    """200 但缺 content → api_error"""
    resp = _mock_response(status_code=200, json_data={"stop_reason": "end_turn"})
    client = _mock_async_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(AnthropicError) as ei:
            await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "p", timeout=10)
    assert ei.value.kind == "api_error"


@pytest.mark.asyncio
async def test_request_translation_http_error_raises():
    resp = _mock_response(
        status_code=404,
        json_data={"type": "error", "error": {"type": "not_found_error", "message": "gone"}},
        reason_phrase="Not Found",
    )
    client = _mock_async_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(AnthropicError) as ei:
            await request_translation(FAKE_KEY, "bad-model", "p", timeout=10)
    assert ei.value.kind == "not_found"


@pytest.mark.asyncio
async def test_request_translation_timeout():
    client = _mock_async_client(post_side_effect=httpx.TimeoutException("timed out"))
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(AnthropicError) as ei:
            await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "p", timeout=1)
    assert ei.value.kind == "connection_timeout"


@pytest.mark.asyncio
async def test_request_translation_connection_failed():
    client = _mock_async_client(post_side_effect=httpx.ConnectError("boom"))
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(AnthropicError) as ei:
            await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "p", timeout=1)
    assert ei.value.kind == "connection_failed"


@pytest.mark.asyncio
async def test_list_models_returns_raw_dict_and_warns_has_more(caplog):
    import logging

    raw = {
        "data": [{"id": "claude-haiku-5-5", "created_at": "2025-10-01T00:00:00Z"}],
        "has_more": True,
    }
    resp = _mock_response(json_data=raw)
    client = _mock_async_client(get_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with caplog.at_level(logging.WARNING):
            result = await list_models(FAKE_KEY, timeout=10)
    assert result == raw
    assert result["has_more"] is True
    kwargs = client.get.call_args.kwargs
    assert kwargs.get("params", {}).get("limit") == 1000 or (
        client.get.call_args.args and "limit=1000" in str(client.get.call_args)
    )
    url = client.get.call_args.args[0]
    assert url == f"{ANTHROPIC_BASE_URL}/v1/models"
    joined = "\n".join(r.message for r in caplog.records)
    assert "has_more" in joined.lower() or "more" in joined.lower()
    assert FAKE_KEY not in joined


@pytest.mark.asyncio
async def test_request_translation_log_oracle_no_key(caplog):
    """失敗 log 含 type／msg，不含 sk-ant- 金鑰"""
    import logging

    resp = _mock_response(
        status_code=401,
        json_data={
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        },
    )
    client = _mock_async_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        with caplog.at_level(logging.WARNING):
            with pytest.raises(AnthropicError):
                await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "p", timeout=10)
    joined = "\n".join(r.message for r in caplog.records)
    assert "authentication_error" in joined
    assert "invalid x-api-key" in joined
    assert FAKE_KEY not in joined


# ============ 金鑰含空白／換行（Codex P1：不得洩漏進 log／message）============

_ILLEGAL_MSG = "Illegal header value b'sk-ant-FAKE-abc123\\n'"


def test_build_headers_strips_key_whitespace():
    assert build_headers("  sk-ant-x \n")["x-api-key"] == "sk-ant-x"


@pytest.mark.asyncio
async def test_request_translation_illegal_key_header_no_leak(caplog):
    import logging
    client = _mock_async_client(post_side_effect=httpx.LocalProtocolError(_ILLEGAL_MSG))
    with caplog.at_level(logging.DEBUG):
        with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
            with pytest.raises(AnthropicError) as ei:
                await request_translation(FAKE_KEY, DEFAULT_CLAUDE_MODEL, "p", timeout=1)
    assert ei.value.kind == "auth_failed"
    assert ei.value.error_type == "invalid_api_key_format"
    assert "sk-ant-FAKE" not in ei.value.message
    assert "sk-ant-FAKE" not in caplog.text


@pytest.mark.asyncio
async def test_list_models_illegal_key_header_no_leak(caplog):
    import logging
    client = _mock_async_client(get_side_effect=httpx.LocalProtocolError(_ILLEGAL_MSG))
    with caplog.at_level(logging.DEBUG):
        with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
            with pytest.raises(AnthropicError) as ei:
                await list_models(FAKE_KEY, timeout=1)
    assert ei.value.kind == "auth_failed"
    assert ei.value.error_type == "invalid_api_key_format"
    assert "sk-ant-FAKE" not in ei.value.message
    assert "sk-ant-FAKE" not in caplog.text


def test_pick_models_excludes_effort_unsupported():
    data = {"data": [
        {"id": "claude-haiku-5-5", "created_at": "2026-09-01T00:00:00Z",
         "capabilities": {"effort": {"supported": True}}},
        {"id": "claude-haiku-4-5-20251001", "created_at": "2025-10-01T00:00:00Z",
         "capabilities": {"effort": {"supported": False}}},
        {"id": "claude-haiku-legacy-nocaps", "created_at": "2025-01-01T00:00:00Z"},
        {"id": "claude-opus-5", "created_at": "2026-09-02T00:00:00Z",
         "capabilities": {"effort": {"supported": True}}},
    ]}
    assert pick_translate_models(data) == ["claude-haiku-5-5", "claude-haiku-legacy-nocaps"]
