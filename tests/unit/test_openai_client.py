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


def test_null_and_blank_content_is_empty_response():
    for content in (None, "   "):
        with pytest.raises(TranslateError) as ei:
            extract_text(_choice(content, finish="stop"))
        assert ei.value.kind == "empty_response"


def test_think_tags_cleaned():
    assert extract_text(_choice("<think>先想</think>譯", finish="stop")) == "譯"


# ============ classify_http_error ============


def test_429_rate_limited():
    assert classify_http_error(_err_resp(429, {"error": {"message": "q"}})).kind == "rate_limited"


def test_403_with_metadata_reasons_is_blocked():
    body = {"error": {"message": "x", "metadata": {"reasons": ["sexual"]}}}
    assert classify_http_error(_err_resp(403, body)).kind == "blocked"


def test_403_empty_reasons_key_is_blocked():
    body = {"error": {"message": "denied", "metadata": {"reasons": []}}}
    assert classify_http_error(_err_resp(403, body)).kind == "blocked"


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
async def test_local_protocol_error_does_not_leak_key(caplog):
    client = _client(post_side_effect=httpx.LocalProtocolError("Illegal header value b'FAKEKEY'"))
    with patch("core.openai_client.httpx.AsyncClient", return_value=client):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TranslateError) as ei:
                await request_translation("http://h/v1", "FAKEKEY\n", "m", "p", timeout=5)
    assert ei.value.kind == "auth_failed"
    assert "FAKEKEY" not in ei.value.message
    assert "FAKEKEY" not in caplog.text
