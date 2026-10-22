"""171-T5：OpenAICompatibleTranslateService 接 openai_client（translate_or_raise / translate_single）。"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core import openai_client
from core.cloud_translate import TranslateError
from core.translate_service import OpenAICompatibleTranslateService, build_cloud_translate_prompt

FAKE_KEY = "FAKEKEY-xyz"
MODEL = "gpt-4o-mini"
BASE = "https://api.example.com/v1"


def _ok(text="翻譯結果", finish_reason=None, refusal=None):
    choice = {"message": {"content": text}}
    if refusal:
        choice["message"]["refusal"] = refusal
    if finish_reason:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


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


def _svc(lang="zh-TW", key=FAKE_KEY):
    return OpenAICompatibleTranslateService(
        {"base_url": BASE + "/", "api_key": key, "model": MODEL}, lang
    )


def _http_status_error(status, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = "x"
    resp.json.return_value = body if body is not None else {}
    return httpx.HTTPStatusError("err", request=MagicMock(), response=resp)


@pytest.mark.asyncio
async def test_openai_outbound_request_equals_openai_client():
    inst = _mock_client()
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst):
        result = await _svc().translate_or_raise("テスト")
    assert result == "翻譯結果"
    call = inst.post.call_args
    assert call.args[0] == f"{BASE}/chat/completions"
    assert call.kwargs["headers"] == openai_client.build_headers(FAKE_KEY)
    expected = openai_client.build_translate_payload(MODEL, build_cloud_translate_prompt("テスト", "zh-TW"))
    assert call.kwargs["json"] == expected
    assert set(call.kwargs["json"].keys()) == {"model", "messages"}


@pytest.mark.asyncio
async def test_openai_ja_short_circuit_no_client():
    with patch("core.cloud_translate.httpx.AsyncClient") as ac:
        svc = _svc("ja")
        assert await svc.translate_or_raise("原題") == "原題"
        assert await svc.translate_single("原題") == "原題"
    assert ac.call_count == 0


@pytest.mark.asyncio
async def test_openai_rate_limited_429():
    inst = _mock_client(raise_for_status=_http_status_error(429))
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=inst):
        with pytest.raises(TranslateError) as ei:
            await _svc().translate_or_raise("テスト")
        assert ei.value.kind == "rate_limited"
        assert await _svc().translate_single("テスト") == ""


@pytest.mark.asyncio
async def test_openai_translate_single_swallows_translate_error():
    svc = _svc()
    with patch.object(
        OpenAICompatibleTranslateService,
        "translate_or_raise",
        AsyncMock(side_effect=TranslateError("blocked", None, "", "x")),
    ):
        assert await svc.translate_single("テスト") == ""


