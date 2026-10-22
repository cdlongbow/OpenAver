"""171-T5：/api/openai/test 失敗類別與 /test、/models 金鑰衛生。"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)
FAKE_KEY = "FAKEKEY-xyz"
BASE = "https://api.example.com/v1"
CFG = {"general": {"locale": "zh-TW"}}


def _cm(**methods):
    mock_client = AsyncMock()
    for k, v in methods.items():
        setattr(mock_client, k, v)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_client


def _resp(body):
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.json = MagicMock(return_value=body)
    r.raise_for_status = MagicMock(return_value=None)
    return r


def _post_test(body, cfg=CFG):
    cm, mc = _cm(post=AsyncMock(return_value=_resp(body)))
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=cm), \
         patch("web.routers.openai_translate.load_config", return_value=cfg):
        r = client.post("/api/openai/test", json={"base_url": BASE, "api_key": "k", "model": "m"})
    return r.json(), mc


def test_test_blocked_content_filter():
    data, _ = _post_test({"choices": [{"message": {"content": "x"}, "finish_reason": "content_filter"}]})
    assert data["success"] is False and data["error"] == "blocked"


def test_test_illegal_key_no_leak(caplog):
    post = AsyncMock(side_effect=httpx.LocalProtocolError(f"Illegal header value b'{FAKE_KEY}\\n'"))
    cm, _ = _cm(post=post)
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=cm), \
         patch("web.routers.openai_translate.load_config", return_value=CFG), \
         caplog.at_level(logging.DEBUG):
        r = client.post("/api/openai/test", json={"base_url": BASE, "api_key": FAKE_KEY + "\n", "model": "m"})
    data = r.json()
    assert data["success"] is False
    assert FAKE_KEY not in str(data)
    assert FAKE_KEY not in caplog.text


def test_models_illegal_key_no_leak(caplog):
    get = AsyncMock(side_effect=httpx.LocalProtocolError(f"Illegal header value b'{FAKE_KEY}\\n'"))
    cm, _ = _cm(get=get)
    with patch("web.routers.openai_translate.httpx.AsyncClient", return_value=cm), \
         patch("web.routers.openai_translate.load_config", return_value=CFG), \
         caplog.at_level(logging.DEBUG):
        r = client.post("/api/openai/models", json={"base_url": BASE, "api_key": FAKE_KEY + "\n"})
    data = r.json()
    assert data["success"] is False
    assert data["error"] == "auth_failed"
    assert FAKE_KEY not in str(data)
    assert FAKE_KEY not in caplog.text


