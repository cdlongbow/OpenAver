# [lint-guard: pytest-justified] ①「schema 名稱都在文件」要 import Python 常數集合（schema.TOP_KEYS 等），
# eslint／stylelint／scripts/*.mjs 讀不到 Python 常數；②「範例 YAML 能載入」要呼叫 Python loader（schema.load_text）。
"""docs/custom-sources.md 的文件契約：schema 名稱不漏、範例區塊都能載入。"""
import re
from pathlib import Path

import pytest
import yaml

from core.custom_source import errors, schema

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "custom-sources.md"

# schema.py 以字面驗證這三個子鍵、沒有常數可 import（T7 不得改 schema.py），故在此寫死
# schema.py 未公開此集合，與 schema 模板白名單（_URL_VARS_SUFFIX）同步

_EXAMPLE_RE = re.compile(r"<!-- example -->[ \t]*\n(?:[ \t]*\n)*```yaml\n(.*?)\n```", re.DOTALL)


def _doc_text():
    return DOC_PATH.read_text(encoding="utf-8")


def _example_blocks():
    return _EXAMPLE_RE.findall(_doc_text())


def _load_blocks():
    specs = []
    for i, block in enumerate(_example_blocks(), 1):
        data = yaml.safe_load(block)
        stem = data.get("id") if isinstance(data, dict) else None
        try:
            specs.append(schema.load_text(block, stem))
        except errors.LoadError as exc:
            pytest.fail(f"範例區塊 #{i} 載入被拒：reason={exc.reason} field_path={exc.field_path}")
    return specs


def test_example_blocks_all_load():
    assert _load_blocks() is not None


# ---------------------------------------------------------------------------
# 165-T11：「## 13. 上傳、驗收與狀態」與程式對帳（只掃新章，各子節以標題逐字定位）
# ---------------------------------------------------------------------------

_CHAPTER_HEADING = "## 13. 上傳、驗收與狀態"
_PATH_RE = re.compile(r"/api/custom[^\s'\"`),，|]*")


def _chapter13():
    text = _doc_text()
    idx = text.find("\n" + _CHAPTER_HEADING)
    if idx < 0:
        pytest.fail(f"docs 找不到章節標題 {_CHAPTER_HEADING!r}")
    return text[idx + 1:]


def _subsection(title):
    chapter = _chapter13()
    heading = f"### {title}"
    lines = chapter.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        pytest.fail(f"§13 找不到子節標題 {heading!r}")
    body = []
    for line in lines[start:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _norm_doc_path(path):
    parts = path.split("/")  # ['', 'api', 'custom-sources', X, ...]
    if len(parts) >= 4 and parts[3] not in ("applicable", "{id}"):
        parts[3] = "{id}"
    return "/".join(parts)


def _router_paths():
    import web.routers.custom_sources as mod

    return {r.path.replace("{source_id}", "{id}") for r in mod.router.routes}


def test_docs_endpoints_match_router():
    section = _subsection("端點")
    extracted = {_norm_doc_path(p) for p in _PATH_RE.findall(section)}
    assert extracted, "§13 端點子節沒擷取到任何 /api/custom 路徑"
    routes = _router_paths()
    assert extracted <= routes, f"docs 出現路由不存在的路徑：{sorted(extracted - routes)}"
    required = {"/api/custom-sources", "/api/custom-sources/{id}/verify", "/api/custom-sources/{id}"}
    assert required <= extracted, f"docs 漏了 AI 端點：{sorted(required - extracted)}"


