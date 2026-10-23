"""core.cloud_translate 共用層（171-T1）：清理 oracle、錯誤分類、cloud_request 例外映射。"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.anthropic_client import extract_text
from core.cloud_translate import (
    TranslateError,
    cloud_request,
    failure_category,
    finalize_translation,
)

FAKE_KEY = "FAKEKEY-xyz"


def _mock_client(post=None, get=None):
    client = MagicMock()
    client.post = post or AsyncMock()
    client.get = get or AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload if payload is not None else {})
    return r


# ---- finalize_translation ----

@pytest.mark.parametrize("raw,expected", [
    ("<thought>先想</thought>譯", "譯"),
])
def test_finalize_cleans_thinking(raw, expected):
    assert finalize_translation("T", raw) == expected


def test_finalize_unpaired_marker_fails(caplog):
    with pytest.raises(TranslateError) as ei:
        finalize_translation("Claude", "<thought>只有思考")
    assert ei.value.kind == "empty_response"
    assert "Claude" in caplog.text and "empty_response" in caplog.text


# ---- 錯誤分類 ----

@pytest.mark.parametrize("kind,expected", [
    ("blocked", "blocked"),
    ("refused", "blocked"),
    ("rate_limited", "rate_limited"),
    ("auth_failed", "other"),
    ("whatever", "other"),
])
def test_failure_category_table(kind, expected):
    assert failure_category(kind) == expected


# ---- cloud_request ----

@pytest.mark.asyncio
async def test_cloud_request_illegal_key_no_leak(caplog):
    post = AsyncMock(side_effect=httpx.LocalProtocolError(
        f"Illegal header value b'{FAKE_KEY}\\n'"))
    cm, _ = _mock_client(post=post)
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=cm):
        with pytest.raises(TranslateError) as ei:
            await cloud_request("T", "post", "https://x", headers={}, timeout=1, json={})
    e = ei.value
    assert e.kind == "auth_failed"
    assert e.error_type == "invalid_api_key_format"
    assert "FAKEKEY" not in e.message
    assert "FAKEKEY" not in caplog.text
    assert e.__suppress_context__ and e.__cause__ is None


@pytest.mark.asyncio
async def test_cloud_request_non_ascii_key_is_auth_failed(caplog):
    """使用者貼進全形字金鑰 → 歸「認證失敗」而非例外穿出；金鑰不進訊息／log。"""
    post = AsyncMock(side_effect=UnicodeEncodeError("ascii", "ＡKEY", 0, 1, "ordinal not in range"))
    cm, _ = _mock_client(post=post)
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=cm):
        with pytest.raises(TranslateError) as ei:
            await cloud_request("T", "post", "https://x", headers={}, timeout=1, json={})
    e = ei.value
    assert e.kind == "auth_failed"
    assert "ＡKEY" not in e.message
    assert "ＡKEY" not in caplog.text


# ---- Claude 對齊 ----

def test_claude_extract_text_strips_thought():
    data = {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "<thought>想</thought>譯"}]}
    assert extract_text(data) == "譯"


