"""通知抽屜的 Alpine 連結契約。"""

import re
from pathlib import Path


BASE_HTML = Path(__file__).resolve().parents[3] / "web" / "templates" / "base.html"


def test_notification_url_renders_clickable_link():
    html = BASE_HTML.read_text(encoding="utf-8")
    # [lint-guard: pytest-justified] 跨 base.html 與 Alpine 綁定，現有前端契約測試採原始碼檢查。
    assert re.search(r'<template\s+x-if="item\.url">\s*<a\b[^>]*:href="item\.url"[^>]*target="_blank"[^>]*rel="noopener"', html)
    # [lint-guard: pytest-justified] 同一模板的文字綁定必須是 x-text，避免通知內容作為 HTML 執行。
    assert re.search(r'<a\b[^>]*:href="item\.url"[^>]*>\s*<span[^>]*x-text="item\.message"', html)
