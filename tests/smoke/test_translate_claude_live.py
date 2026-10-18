"""
test_translate_claude_live.py - Claude (Anthropic) 翻譯 Smoke 金絲雀

只用於本地手動測試，不進 CI（需要真實 Anthropic API Key 與外網）

執行方式：
    ANTHROPIC_API_KEY=<KEY> pytest tests/smoke/test_translate_claude_live.py -v

前提條件：
- 環境變數 ANTHROPIC_API_KEY（唯一金鑰來源；沒有則整檔 skip）
- 可連 api.anthropic.com（連不上 skip，不算紅）

確認三件事仍與產品碼假設一致：模型清單、翻譯、錯誤分類。
"""

import os
import re
from unittest.mock import patch

import pytest

from core.anthropic_client import (
    DEFAULT_CLAUDE_MODEL,
    AnthropicError,
    list_models,
    pick_translate_models,
    request_translation,
)
import core.translate_service as _ts
from core.translate_service import ClaudeTranslateService

pytestmark = pytest.mark.smoke

# 金鑰只留在環境變數；測試內以 os.environ[...] 直接當參數傳入，不綁區域變數
# （避免 --showlocals 的 traceback 印出金鑰）。
HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
NEED_KEY = pytest.mark.skipif(not HAS_KEY, reason="未設定 ANTHROPIC_API_KEY，跳過 Claude 活 API 金絲雀")

_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_OFFLINE = ("connection_failed", "connection_timeout")


def _handle(kind: str, status, error_type: str) -> None:
    """連線類 skip，其餘 fail；pytrace=False 讓 --showlocals 無處可印。訊息不含 e.message。"""
    if kind in _OFFLINE:
        pytest.skip(f"無法連線 Anthropic API（kind={kind}）")
    pytest.fail(f"Anthropic 回 {kind} status={status} type={error_type}", pytrace=False)


@NEED_KEY
async def test_model_list_haiku_sonnet():
    """模型清單：非空、只含 haiku／sonnet、至少一個 haiku"""
    try:
        data = await list_models(os.environ["ANTHROPIC_API_KEY"], timeout=15)
    except AnthropicError as e:
        _handle(e.kind, e.status, e.error_type)
    models = pick_translate_models(data)
    assert models, "pick_translate_models 回空清單"
    assert all("haiku" in m.lower() or "sonnet" in m.lower() for m in models)
    assert any("haiku" in m.lower() for m in models)
    raw = {m.get("id"): m for m in data.get("data", []) if isinstance(m, dict)}
    for mid in models:
        supported = ((raw[mid].get("capabilities") or {}).get("effort") or {}).get("supported")
        assert supported is not False, f"{mid} 不支援 effort 卻進了清單"


@NEED_KEY
async def test_service_translate_default_model():
    """翻譯走服務層、config 不給 model（AC-5：預設模型可直接用）；只打一次請求"""
    service = ClaudeTranslateService({"api_key": os.environ["ANTHROPIC_API_KEY"]}, "zh-TW")
    assert service.model == DEFAULT_CLAUDE_MODEL

    failures: list[tuple] = []

    async def _recording(*args, **kwargs):
        try:
            return await request_translation(*args, **kwargs)
        except AnthropicError as e:
            failures.append((e.kind, e.status, e.error_type))
            raise

    with patch.object(_ts, "request_translation", _recording):
        result = await service.translate_single("新人女優デビュー")

    if not result:
        if failures:
            _handle(*failures[-1])
        pytest.fail("翻譯結果為空（無 AnthropicError）", pytrace=False)
    assert result.strip(), "翻譯結果為空"
    assert _HAN.search(result), "譯文不含漢字"
    assert not _KANA.search(result), "譯文仍含日文假名"
    assert "thinking" not in result.lower() and "思考" not in result


@NEED_KEY
async def test_invalid_key_auth_failed():
    """錯誤金鑰 → auth_failed"""
    with pytest.raises(AnthropicError) as ei:
        await request_translation("sk-ant-invalid", DEFAULT_CLAUDE_MODEL, "hi", timeout=15)
    if ei.value.kind in _OFFLINE:
        _handle(ei.value.kind, ei.value.status, ei.value.error_type)
    assert ei.value.kind == "auth_failed"


@NEED_KEY
async def test_nonexistent_model_not_found():
    """不存在的模型 → not_found"""
    try:
        await request_translation(
            os.environ["ANTHROPIC_API_KEY"], "claude-nonexistent-0", "hi", timeout=15
        )
    except AnthropicError as e:
        if e.kind in _OFFLINE or e.kind != "not_found":
            _handle(e.kind, e.status, e.error_type)
        return
    pytest.fail("預期 not_found 但請求成功", pytrace=False)
