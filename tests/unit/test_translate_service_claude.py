"""
test_translate_service_claude.py — ClaudeTranslateService 與工廠 claude 分支

mock patch 使用端 core.anthropic_client.httpx.AsyncClient（service 經 client 發請求）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.anthropic_client import DEFAULT_CLAUDE_MODEL
from core.translate_service import (
    ClaudeTranslateService,
    OpenAICompatibleTranslateService,
    TranslateService,
    build_cloud_translate_prompt,
    create_translate_service,
)


FAKE_KEY = "sk-ant-test-fake-key-not-real"


def _ok_response(text="繁中譯文"):
    resp = MagicMock()
    resp.status_code = 200
    resp.reason_phrase = "OK"
    resp.json.return_value = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
    }
    return resp


def _mock_client(post_return=None, post_side_effect=None):
    client = MagicMock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ============ ja 短路 ============


@pytest.mark.asyncio
async def test_translate_single_ja_does_not_call_api():
    """target_language=ja → 回原標題且 post 未被呼叫"""
    service = ClaudeTranslateService({"api_key": FAKE_KEY, "model": "claude-haiku-5-5"}, "ja")
    client = _mock_client(post_return=_ok_response())
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("オリジナルタイトル")
    assert result == "オリジナルタイトル"
    client.post.assert_not_called()


# ============ 缺金鑰 / 預設模型 / 工廠 ============


def test_missing_api_key_raises_value_error():
    with pytest.raises(ValueError) as ei:
        ClaudeTranslateService({}, "zh-TW")
    assert "API Key" in str(ei.value)


def test_factory_claude_missing_api_key():
    with pytest.raises(ValueError) as ei:
        create_translate_service({"provider": "claude", "claude": {}})
    assert "API Key" in str(ei.value)


def test_factory_claude_returns_service():
    service = create_translate_service({
        "provider": "claude",
        "claude": {"api_key": FAKE_KEY, "model": "claude-sonnet-4"},
    })
    assert isinstance(service, ClaudeTranslateService)
    assert isinstance(service, TranslateService)
    assert service.model == "claude-sonnet-4"
    assert service.api_key == FAKE_KEY


def test_default_model_when_missing_or_empty():
    s1 = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    assert s1.model == DEFAULT_CLAUDE_MODEL
    s2 = ClaudeTranslateService({"api_key": FAKE_KEY, "model": ""}, "zh-TW")
    assert s2.model == DEFAULT_CLAUDE_MODEL


# ============ 成功／失敗降級 ============


@pytest.mark.asyncio
async def test_translate_single_success():
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=_ok_response("  新人女演員出道  "))
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("新人女優デビュー")
    assert result == "新人女演員出道"


@pytest.mark.asyncio
async def test_translate_single_thinking_then_text():
    """content=[thinking, text] → 回 text"""
    resp = MagicMock()
    resp.status_code = 200
    resp.reason_phrase = "OK"
    resp.json.return_value = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "…"},
            {"type": "text", "text": "正確譯文"},
        ],
    }
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("テスト")
    assert result == "正確譯文"


@pytest.mark.asyncio
async def test_translate_single_thinking_only_returns_empty():
    resp = MagicMock()
    resp.status_code = 200
    resp.reason_phrase = "OK"
    resp.json.return_value = {
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": "only"}],
    }
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("テスト")
    assert result == ""


@pytest.mark.asyncio
async def test_translate_single_refusal_returns_empty():
    resp = MagicMock()
    resp.status_code = 200
    resp.reason_phrase = "OK"
    resp.json.return_value = {
        "stop_reason": "refusal",
        "content": [{"type": "text", "text": "拒絕說明"}],
    }
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("テスト")
    assert result == ""


@pytest.mark.asyncio
async def test_translate_single_max_tokens_returns_empty():
    resp = MagicMock()
    resp.status_code = 200
    resp.reason_phrase = "OK"
    resp.json.return_value = {
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": "半句"}],
    }
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("テスト")
    assert result == ""


@pytest.mark.asyncio
async def test_translate_single_http_error_returns_empty():
    resp = MagicMock()
    resp.status_code = 401
    resp.reason_phrase = "Unauthorized"
    resp.json.return_value = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "bad key"},
    }
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    client = _mock_client(post_return=resp)
    with patch("core.anthropic_client.httpx.AsyncClient", return_value=client):
        result = await service.translate_single("テスト")
    assert result == ""


@pytest.mark.asyncio
async def test_translate_batch_calls_single_per_title():
    service = ClaudeTranslateService({"api_key": FAKE_KEY}, "zh-TW")
    results_map = {"A": "甲", "B": "乙"}

    async def fake_single(title, context=None):
        return results_map[title]

    service.translate_single = fake_single
    out = await service.translate_batch(["A", "B"])
    assert out == ["甲", "乙"]


# ============ CD-170-4 prompt 等價 ============


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["zh-TW", "zh-CN", "en"])
async def test_build_cloud_translate_prompt_matches_openai(lang):
    """OpenAI 實際送出的 prompt 等於 build_cloud_translate_prompt 輸出"""
    title = "新人女優デビュー"
    expected = build_cloud_translate_prompt(title, lang)

    service = OpenAICompatibleTranslateService(
        {"base_url": "http://localhost/v1", "api_key": "", "model": "m"},
        lang,
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "x"}}]
    }
    mock_response.raise_for_status = MagicMock()

    client = MagicMock()
    client.post = AsyncMock(return_value=mock_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("core.translate_service.httpx.AsyncClient", return_value=client):
        await service.translate_single(title)

    sent = client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert sent == expected


def test_build_cloud_translate_prompt_unknown_lang_falls_back_zh_tw():
    title = "テスト"
    assert build_cloud_translate_prompt(title, "xx") == build_cloud_translate_prompt(title, "zh-TW")
