"""171-T3：GeminiTranslateService 接線（translate_or_raise / translate_single）與 Claude 一格。"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core import gemini_client
from core.anthropic_client import AnthropicError
from core.cloud_translate import TranslateError, failure_category
from core.translate_service import (
    ClaudeTranslateService,
    GeminiTranslateService,
    build_cloud_translate_prompt,
)

FAKE_KEY = "FAKEKEY-xyz"
MODEL = "gemini-flash-lite-latest"


def _ok(text="翻譯結果"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def _mock_client(json_data=None, raise_for_status=None, post_side_effect=None):
    resp = MagicMock()
    resp.json.return_value = json_data if json_data is not None else _ok()
    resp.raise_for_status = MagicMock(side_effect=raise_for_status)
    inst = MagicMock()
    if post_side_effect is not None:
        inst.post = AsyncMock(side_effect=post_side_effect)
    else:
        inst.post = AsyncMock(return_value=resp)
    inst.__aenter__ = AsyncMock(return_value=inst)
    inst.__aexit__ = AsyncMock(return_value=False)
    return inst


def _svc(lang="zh-TW"):
    return GeminiTranslateService({"api_key": FAKE_KEY, "model": MODEL}, lang)


def _http_status_error(status, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = "x"
    resp.json.return_value = body if body is not None else {}
    return httpx.HTTPStatusError("err", request=MagicMock(), response=resp)


# ---- 外送等價 ----

@pytest.mark.asyncio
async def test_gemini_outbound_request_equals_gemini_client():
    inst = _mock_client()
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst) as ac:
        result = await _svc().translate_or_raise("テスト")
    assert result == "翻譯結果"
    call = inst.post.call_args
    assert call.args[0] == f"{gemini_client.GEMINI_BASE_URL}/models/{MODEL}:generateContent"
    assert call.kwargs["headers"] == gemini_client.build_headers(FAKE_KEY)
    expected = gemini_client.build_translate_payload(MODEL, build_cloud_translate_prompt("テスト", "zh-TW"))
    assert call.kwargs["json"] == expected
    assert "generationConfig" not in call.kwargs["json"]
    assert ac.call_args.kwargs["timeout"] == 60


@pytest.mark.asyncio
async def test_gemini_ja_short_circuit_no_client():
    with patch("core.cloud_translate.httpx.AsyncClient") as ac:
        svc = _svc("ja")
        assert await svc.translate_or_raise("テスト") == "テスト"
        assert await svc.translate_single("テスト") == "テスト"
    assert ac.call_count == 0


def test_gemini_missing_key_raises_value_error():
    with pytest.raises(ValueError):
        GeminiTranslateService({"api_key": ""}, "zh-TW")


# ---- kind 對應 ----

@pytest.mark.asyncio
@pytest.mark.parametrize("data,side,kind", [
    ({"candidates": [{"content": {"parts": [{"text": "半截"}]}, "finishReason": "MAX_TOKENS"}]}, None, "truncated"),
    ({"candidates": [{"finishReason": "PROHIBITED_CONTENT"}]}, None, "blocked"),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, None, "blocked"),
    (None, _http_status_error(429), "rate_limited"),
])
async def test_gemini_failure_kinds_and_single_returns_empty(data, side, kind):
    svc = _svc()
    inst = _mock_client(json_data=data, raise_for_status=side)
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst):
        with pytest.raises(TranslateError) as ei:
            await svc.translate_or_raise("テスト")
    assert ei.value.kind == kind
    inst = _mock_client(json_data=data, raise_for_status=side)
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst):
        assert await svc.translate_single("テスト") == ""


@pytest.mark.asyncio
async def test_gemini_failure_category_mapping():
    inst = _mock_client(json_data={"candidates": [{"finishReason": "SAFETY"}]})
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst):
        with pytest.raises(TranslateError) as ei:
            await _svc().translate_or_raise("テスト")
    assert failure_category(ei.value.kind) == "blocked"


@pytest.mark.asyncio
async def test_gemini_translate_single_swallows_translate_error():
    svc = _svc()
    svc_err = TranslateError("blocked", None, "SAFETY", "x")
    with patch("core.translate_service.gemini_client.request_translation", AsyncMock(side_effect=svc_err)):
        assert await svc.translate_single("テスト") == ""
        with pytest.raises(TranslateError):
            await svc.translate_or_raise("テスト")


@pytest.mark.asyncio
async def test_gemini_unexpected_exception_wrapped_as_api_error(caplog):
    svc = _svc()
    boom = RuntimeError(f"secret {FAKE_KEY}")
    with patch("core.translate_service.gemini_client.request_translation", AsyncMock(side_effect=boom)):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TranslateError) as ei:
                await svc.translate_or_raise("テスト")
            assert await svc.translate_single("テスト") == ""
    assert ei.value.kind == "api_error"
    assert FAKE_KEY not in ei.value.message
    assert FAKE_KEY not in caplog.text


@pytest.mark.asyncio
async def test_gemini_engine_illegal_key_no_leak(caplog):
    svc = _svc()
    err = httpx.LocalProtocolError(f"Illegal header value b'{FAKE_KEY}\\n'")
    with patch("core.cloud_translate.httpx.AsyncClient",
               return_value=_mock_client(post_side_effect=err)):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TranslateError) as ei:
                await svc.translate_or_raise("テスト")
            assert await svc.translate_single("テスト") == ""
    assert FAKE_KEY not in ei.value.message
    assert FAKE_KEY not in caplog.text


# ---- Claude 一格 ----

@pytest.mark.asyncio
async def test_claude_translate_or_raise_refused_is_blocked():
    svc = ClaudeTranslateService({"api_key": "k", "model": "m"}, "zh-TW")
    err = AnthropicError("refused", None, "", "x")
    with patch("core.translate_service.request_translation", AsyncMock(side_effect=err)):
        with pytest.raises(TranslateError) as ei:
            await svc.translate_or_raise("テスト")
        assert failure_category(ei.value.kind) == "blocked"
        assert await svc.translate_single("テスト") == ""
