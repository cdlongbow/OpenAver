"""
test_openai_client.py — OpenAI 相容 chat/completions 請求／判定／分類單元測試

一律 patch core.openai_client.httpx.AsyncClient；回應為內嵌合成 dict，不連真 API。
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.cloud_translate import TranslateError
from core.openai_client import (
    build_headers,
    build_translate_payload,
    classify_http_error,
    extract_text,
    request_translation,
)

FAKE_KEY = "sk-test-fake-key-not-real"


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


def _choice(content, finish=None, refusal=None):
    msg = {"content": content}
    if refusal is not None:
        msg["refusal"] = refusal
    c = {"message": msg}
    if finish is not None:
        c["finish_reason"] = finish
    return {"choices": [c]}


# ============ payload / headers ============


def test_payload_keys_exact():
    payload = build_translate_payload("gpt-x", "請翻譯：測試")
    assert set(payload.keys()) == {"model", "messages"}
    assert payload["model"] == "gpt-x"
    assert payload["messages"] == [{"role": "user", "content": "請翻譯：測試"}]


def test_headers_strip_key():
    headers = build_headers("  KEY\n")
    assert headers == {"Content-Type": "application/json", "Authorization": "Bearer KEY"}


def test_empty_key_has_no_authorization():
    assert build_headers("") == {"Content-Type": "application/json"}
    assert build_headers("  \n") == {"Content-Type": "application/json"}


# ============ extract_text 判定 ============


def test_ok_with_missing_finish_reason():
    assert extract_text(_choice("譯文")) == "譯文"


def test_length_is_truncated():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice("半句", finish="length"))
    assert ei.value.kind == "truncated"


def test_content_filter_is_blocked():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice("x", finish="content_filter"))
    assert ei.value.kind == "blocked"


def test_refusal_is_blocked():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice(None, finish="stop", refusal="I can't help"))
    assert ei.value.kind == "blocked"


def test_refusal_wins_over_length():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice("半句", finish="length", refusal="I can't help"))
    assert ei.value.kind == "blocked"


def test_null_and_blank_content_is_empty_response():
    for content in (None, "   "):
        with pytest.raises(TranslateError) as ei:
            extract_text(_choice(content, finish="stop"))
        assert ei.value.kind == "empty_response"


def test_only_error_is_api_error():
    with pytest.raises(TranslateError) as ei:
        extract_text({"error": {"message": "x"}})
    assert ei.value.kind == "api_error"


def test_think_tags_cleaned():
    assert extract_text(_choice("<think>先想</think>譯", finish="stop")) == "譯"


def test_unpaired_thought_is_empty_response():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice("<thought>只有思考"))
    assert ei.value.kind == "empty_response"


def test_think_only_is_empty_response():
    with pytest.raises(TranslateError) as ei:
        extract_text(_choice("<think>x</think>"))
    assert ei.value.kind == "empty_response"


# ============ classify_http_error ============


def test_429_rate_limited():
    assert classify_http_error(_err_resp(429, {"error": {"message": "q"}})).kind == "rate_limited"


def test_403_with_metadata_reasons_is_blocked():
    body = {"error": {"message": "x", "metadata": {"reasons": ["sexual"]}}}
    assert classify_http_error(_err_resp(403, body)).kind == "blocked"


def test_403_moderation_message_is_blocked():
    body = {"error": {"message": "Input was flagged by moderation"}}
    assert classify_http_error(_err_resp(403, body)).kind == "blocked"


def test_403_empty_reasons_key_is_blocked():
    body = {"error": {"message": "denied", "metadata": {"reasons": []}}}
    assert classify_http_error(_err_resp(403, body)).kind == "blocked"


def test_plain_403_is_forbidden():
    assert classify_http_error(_err_resp(403, {"error": {"message": "no"}})).kind == "forbidden"


def test_401_404_5xx():
    assert classify_http_error(_err_resp(401)).kind == "auth_failed"
    assert classify_http_error(_err_resp(404)).kind == "not_found"
    assert classify_http_error(_err_resp(500)).kind == "http_error"


def test_non_json_body_still_translate_error():
    err = classify_http_error(_err_resp(502, json_side_effect=ValueError("no json"), reason="Bad Gateway"))
    assert isinstance(err, TranslateError)
    assert err.kind == "http_error"
    assert err.message == "Bad Gateway"


# ============ request_translation ============


@pytest.mark.asyncio
async def test_request_sends_exact_shape_and_url():
    client = _client(post_return=_ok_resp(_choice("譯", finish="stop")))
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        out = await request_translation("http://h:1/v1/", "  KEY\n", "m", "p", timeout=5)
    assert out == "譯"
    args, kwargs = client.post.call_args
    assert args[0] == "http://h:1/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer KEY"
    assert set(kwargs["json"].keys()) == {"model", "messages"}


@pytest.mark.asyncio
async def test_request_empty_key_no_authorization_header():
    client = _client(post_return=_ok_resp(_choice("譯")))
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        await request_translation("http://h/v1", "", "m", "p", timeout=5)
    assert "Authorization" not in client.post.call_args.kwargs["headers"]


@pytest.mark.asyncio
async def test_request_http_error_uses_raise_for_status_response():
    resp = _ok_resp({})
    resp.status_code = None  # 不得讀 resp.status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "x", request=MagicMock(), response=_err_resp(429, {"error": {"message": "q"}})
    )
    client = _client(post_return=resp)
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(TranslateError) as ei:
            await request_translation("http://h/v1", FAKE_KEY, "m", "p", timeout=5)
    assert ei.value.kind == "rate_limited"
    assert ei.value.status == 429


@pytest.mark.asyncio
async def test_request_invalid_json_is_api_error():
    resp = _ok_resp({})
    resp.json.side_effect = ValueError("bad")
    client = _client(post_return=resp)
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        with pytest.raises(TranslateError) as ei:
            await request_translation("http://h/v1", FAKE_KEY, "m", "p", timeout=5)
    assert ei.value.kind == "api_error"


@pytest.mark.asyncio
async def test_local_protocol_error_does_not_leak_key(caplog):
    client = _client(post_side_effect=httpx.LocalProtocolError("Illegal header value b'FAKEKEY'"))
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TranslateError) as ei:
                await request_translation("http://h/v1", "FAKEKEY\n", "m", "p", timeout=5)
    assert ei.value.kind == "auth_failed"
    assert "FAKEKEY" not in ei.value.message
    assert "FAKEKEY" not in caplog.text
