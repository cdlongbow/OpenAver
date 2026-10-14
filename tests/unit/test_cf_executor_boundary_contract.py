"""TASK-168d-T2 / CD-168d-4 (b)：ThreadPoolExecutor 邊界契約（AST）。

殼身分（current_key）是 ContextVar，`ThreadPoolExecutor.submit` 不會把 context 帶進 worker。
現有的 submit 目標都到不了 manual_only 的 JavLibrary／javten（已逐一稽核）；若這兩個檔
多了新的 submit 目標，就要回頭重判「要不要 copy_context」——所以新目標＝此測試紅。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ("core/scraper.py", "web/routers/search.py")
AUDITED = {"_search_one", "run_search", "shim.search", "search_jav", "dmm_scraper._fetch_by_id"}


def _submit_targets(rel: str) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "submit" and node.args):
            out.append(ast.unparse(node.args[0]))
    return out


def test_executor_submit_targets_are_the_audited_ones():
    found = {rel: _submit_targets(rel) for rel in FILES}
    assert any(found.values()), "找不到任何 .submit( — AST 掃描失效？"
    for rel, targets in found.items():
        unknown = sorted(set(targets) - AUDITED)
        assert not unknown, f"{rel} 出現未稽核的 executor.submit 目標 {unknown}：回報 Opus 重判 copy_context"
