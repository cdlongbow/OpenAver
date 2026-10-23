"""
test_gemini_client.py — Gemini generateContent 請求／判定／分類單元測試

一律 patch core.gemini_client.httpx.AsyncClient；回應為內嵌合成 dict，不連真 API。
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.cloud_translate import TranslateError
from core.gemini_client import (
    build_translate_payload,
    classify_http_error,
    extract_text,
    request_translation,
)


def _ok_resp(data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _err_resp(status, body=None, reason="Err", json_side_effect=None):
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = reason
    if json_side_effect is not None:
        resp.json.side_effect = json_side_effect
    else:
        resp.json.return_value = body if body is not None else {}
    return resp


def _client(post_return=None, post_side_effect=None):
    client = MagicMock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _cand(parts, finish=None):
    c = {"content": {"parts": parts}}
    if finish is not None:
        c["finishReason"] = finish
    return {"candidates": [c]}


# ============ payload / headers ============


def test_payload_keys_exact():
    payload = build_translate_payload("gemma-3", "請翻譯：測試")
    assert set(payload.keys()) == {"contents", "safetySettings"}
    assert payload["contents"] == [{"parts": [{"text": "請翻譯：測試"}]}]
    assert len(payload["safetySettings"]) == 4
    assert {s["threshold"] for s in payload["safetySettings"]} == {"BLOCK_NONE"}
    assert {s["category"] for s in payload["safetySettings"]} == {
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    }


# ============ extract_text 判定 ============


def test_ok_with_missing_finish_reason():
    assert extract_text(_cand([{"text": "譯文"}])) == "譯文"


def test_max_tokens_is_truncated():
    with pytest.raises(TranslateError) as ei:
        extract_text(_cand([{"text": "半句"}], finish="MAX_TOKENS"))
    assert ei.value.kind == "truncated"


def test_prohibited_content_is_blocked():
    with pytest.raises(TranslateError) as ei:
        extract_text({"candidates": [{"finishReason": "PROHIBITED_CONTENT"}]})
    assert ei.value.kind == "blocked"


def test_prompt_feedback_block_reason_wins_over_text():
    data = _cand([{"text": "可成功回傳的譯文"}], finish="STOP")
    data["promptFeedback"] = {"blockReason": "OTHER"}
    with pytest.raises(TranslateError) as ei:
        extract_text(data)
    assert ei.value.kind == "blocked"


def test_thought_parts_excluded():
    data = _cand([{"text": "想", "thought": True}, {"text": "譯"}], finish="STOP")
    assert extract_text(data) == "譯"


def test_only_error_is_api_error():
    with pytest.raises(TranslateError) as ei:
        extract_text({"error": {"message": "x"}})
    assert ei.value.kind == "api_error"


def test_empty_text_is_empty_response():
    with pytest.raises(TranslateError) as ei:
        extract_text(_cand([{"text": "  "}], finish="STOP"))
    assert ei.value.kind == "empty_response"


def test_think_tags_cleaned():
    assert extract_text(_cand([{"text": "<thought>先想</thought>譯"}])) == "譯"


# ============ classify_http_error ============


def test_429_rate_limited():
    assert classify_http_error(_err_resp(429, {"error": {"message": "q"}})).kind == "rate_limited"


def test_400_key_not_valid_is_auth_failed():
    body = {"error": {"message": "API key not valid. Please pass a valid API key."}}
    assert classify_http_error(_err_resp(400, body)).kind == "auth_failed"


# ============ request_translation ============


@pytest.mark.asyncio
async def test_request_sends_exact_shape_and_stripped_key():
    client = _client(post_return=_ok_resp(_cand([{"text": "譯"}], finish="STOP")))
    with patch("core.gemini_client.httpx.AsyncClient", return_value=client):
        out = await request_translation("  KEY\n", "gemma-3", "p", timeout=5)
    assert out == "譯"
    args, kwargs = client.post.call_args
    assert args[0] == "https://generativelanguage.googleapis.com/v1beta/models/gemma-3:generateContent"
    assert kwargs["headers"] == {"x-goog-api-key": "KEY"}
    assert set(kwargs["json"].keys()) == {"contents", "safetySettings"}


@pytest.mark.asyncio
async def test_local_protocol_error_does_not_leak_key(caplog):
    client = _client(post_side_effect=httpx.LocalProtocolError("Illegal header value b'FAKEKEY'"))
    with patch("core.gemini_client.httpx.AsyncClient", return_value=client):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TranslateError) as ei:
                await request_translation("FAKEKEY\n", "m", "p", timeout=5)
    assert ei.value.kind == "auth_failed"
    assert "FAKEKEY" not in ei.value.message
    assert "FAKEKEY" not in caplog.text
