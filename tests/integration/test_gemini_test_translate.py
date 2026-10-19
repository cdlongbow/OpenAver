"""POST /api/gemini/test-translate（TASK-171-T4）：測試鈕走真翻譯同一條路。

只 patch 全域 httpx.AsyncClient；回應是檔內合成 dict。
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)

URL = "/api/gemini/test-translate"
MODEL = "gemini-flash-lite-latest"
KEY = "TESTKEY-aaaa"
OK_BODY = {"candidates": [{"content": {"parts": [{"text": "新人女優出道"}]}}]}


def _cfg(locale: str = "zh-TW", key: str = KEY) -> dict:
    return {"general": {"locale": locale}, "translate": {"gemini": {"api_key": key}}}


def _resp(status: int = 200, body: dict | None = None, http_error: bool = False):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.reason_phrase = "x"
    r.json = MagicMock(return_value=body if body is not None else {})
    if http_error:
        r.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=r)
        )
    else:
        r.raise_for_status = MagicMock(return_value=None)
    return r


def _cm(post_response=None, post_exc=None):
    mc = AsyncMock()
    mc.post = AsyncMock(return_value=post_response, side_effect=post_exc)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mc)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mc


def _call(cm, cfg=None, api_key=KEY):
    with patch("core.cloud_translate.httpx.AsyncClient", return_value=cm) as ac, \
         patch("web.routers.gemini.load_config", return_value=cfg or _cfg()):
        resp = client.post(URL, json={"api_key": api_key, "model": MODEL})
    return resp, ac


def test_success_returns_translation():
    cm, mc = _cm(_resp(body=OK_BODY))
    resp, _ = _call(cm)
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "translation": "新人女優出道", "error": ""}


def test_translation_not_stripped_of_html():
    cm, _ = _cm(_resp(body={"candidates": [{"content": {"parts": [{"text": "<b>x</b>"}]}}]}))
    resp, _ = _call(cm)
    assert resp.json()["translation"] == "<b>x</b>"


ERROR_CASES = [
    ("blocked_finish", dict(status=200, body={"candidates": [{"finishReason": "SAFETY"}]}), "blocked"),
    ("blocked_prompt", dict(status=200, body={"promptFeedback": {"blockReason": "OTHER"}}), "blocked"),
    ("max_tokens", dict(status=200, body={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "a"}]}}]}), "translate_failed"),
    ("401", dict(status=401, body={"error": {"status": "UNAUTHENTICATED", "message": "x"}}, http_error=True), "auth_failed"),
    ("400_key_invalid", dict(status=400, body={"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid", "details": [{"reason": "API_KEY_INVALID"}]}}, http_error=True), "auth_failed"),
    ("429", dict(status=429, body={"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}}, http_error=True), "rate_limited"),
    ("403", dict(status=403, body={"error": {"message": "x"}}, http_error=True), "forbidden"),
    ("404", dict(status=404, body={"error": {"message": "x"}}, http_error=True), "not_found"),
    ("500", dict(status=500, body={"error": {"message": "x"}}, http_error=True), "http_error"),
]


@pytest.mark.parametrize("kw,expected", [(c[1], c[2]) for c in ERROR_CASES], ids=[c[0] for c in ERROR_CASES])
def test_error_kind_maps_to_settings_key(kw, expected):
    cm, _ = _cm(_resp(**kw))
    resp, _ = _call(cm)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"] == expected


def test_timeout_maps_to_connection_timeout():
    cm, _ = _cm(post_exc=httpx.ReadTimeout("slow"))
    resp, _ = _call(cm)
    assert resp.json()["error"] == "connection_timeout"


def test_connect_error_maps_to_connection_failed():
    cm, _ = _cm(post_exc=httpx.ConnectError("down"))
    resp, _ = _call(cm)
    assert resp.json()["error"] == "connection_failed"


def test_test_translate_timeout_is_60():
    cm, _ = _cm(_resp(body=OK_BODY))
    _, ac = _call(cm)
    assert ac.call_args.kwargs["timeout"] == 60


def test_ja_locale_skips_without_connecting():
    cm, _ = _cm(_resp(body=OK_BODY))
    resp, ac = _call(cm, cfg=_cfg(locale="ja"))
    assert resp.json() == {"success": True, "translation": "ja_skip", "error": ""}
    assert ac.call_count == 0


def test_empty_key_returns_missing_key_without_connecting():
    cm, _ = _cm(_resp(body=OK_BODY))
    resp, ac = _call(cm, cfg=_cfg(key=""), api_key="")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"] == "missing_key"
    assert ac.call_count == 0


def test_key_whitespace_stripped_in_header():
    cm, mc = _cm(_resp(body=OK_BODY))
    resp, _ = _call(cm, api_key="  KEY\n")
    assert resp.json()["success"] is True
    assert mc.post.call_args.kwargs["headers"]["x-goog-api-key"] == "KEY"


def test_illegal_key_not_leaked(caplog):
    exc = httpx.LocalProtocolError("Illegal header value b'FAKEKEY-xyz\\n'")
    cm, _ = _cm(post_exc=exc)
    with caplog.at_level(logging.DEBUG):
        resp, _ = _call(cm, api_key="FAKEKEY-xyz")
    assert resp.json()["error"] == "auth_failed"
    assert "FAKEKEY-xyz" not in resp.text
    assert "FAKEKEY-xyz" not in caplog.text


def test_unexpected_exception_maps_to_translate_failed(caplog):
    cm, _ = _cm(post_exc=RuntimeError("boom FAKEKEY-xyz"))
    with caplog.at_level(logging.DEBUG):
        resp, _ = _call(cm)
    # RuntimeError 非 httpx 例外，cloud_request 不接，端點兜底
    assert resp.json()["error"] == "translate_failed"
    assert "FAKEKEY-xyz" not in resp.text
