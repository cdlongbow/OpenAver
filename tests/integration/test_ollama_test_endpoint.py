"""171-T7：/api/ollama/test 走引擎 translate_or_raise；四種失敗中文字串不變、ja → ja_skip。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)
URL = "http://ollama.test:11434"


def _cm(post_side_effect=None, status=200, content="新人女優出道"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json = MagicMock(return_value={"message": {"content": content}})
    inst = MagicMock()
    if post_side_effect is not None:
        inst.post = AsyncMock(side_effect=post_side_effect)
    else:
        inst.post = AsyncMock(return_value=resp)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=inst)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def _call(locale="zh-TW"):
    with patch("web.routers.config.load_config", return_value={"general": {"locale": locale}}):
        return await asyncio.to_thread(
            client.post, "/api/ollama/test", json={"url": URL, "model": "qwen3:8b"}
        )


@pytest.mark.asyncio
async def test_ollama_test_success():
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=_cm()):
        resp = await _call()
    assert resp.json() == {"success": True, "result": "回應：新人女優出道"}


ERRORS = [
    ("connection_timeout", dict(post_side_effect=httpx.ReadTimeout("t")), "連線逾時"),
    ("connection_failed", dict(post_side_effect=httpx.ConnectError("c")), "無法連線到 Ollama"),
    ("empty_response", dict(content="<think>x</think>"), "模型無回應"),
    ("api_error", dict(status=500), "測試模型失敗"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,kw,text", ERRORS, ids=[e[0] for e in ERRORS])
async def test_ollama_test_error_strings(kind, kw, text):
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=_cm(**kw)):
        resp = await _call()
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"] == text


@pytest.mark.asyncio
async def test_ollama_test_ja_skip():
    with patch("core.cloud_translate.httpx.AsyncClient") as ac:
        resp = await _call("ja")
    assert resp.json() == {"success": True, "result": "ja_skip"}
    assert ac.call_count == 0
