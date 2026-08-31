"""
test_detect_mode_139.py - _detect_mode 路由標籤單元測試 (TASK-139-T9, DoD-3 / DoD-7)
"""
from collections import Counter
import ast
from pathlib import Path
import pytest

from core.scraper import is_number_format, is_partial_number, is_prefix_only
from web.routers.search import _detect_mode


def test_detect_mode_bracket_wrapped_returns_exact():
    """DoD-7: [ABC-123] 帶包裝字串經 _detect_mode 判為 exact（改前為 actress）。"""
    assert _detect_mode("[ABC-123]") == "exact"


def test_detect_mode_actress_returns_actress():
    """DoD-7: 真實女優名經 _detect_mode 維持 actress。"""
    assert _detect_mode("三上悠亜") == "actress"


def test_detect_mode_partial_returns_partial():
    """DoD-7 / D4: 部分番號 SONE-0 經 _detect_mode 維持 partial。"""
    assert _detect_mode("SONE-0") == "partial"


def test_detect_mode_prefix_returns_prefix():
    """DoD-7 / D4: 前綴字串 IPZZ 經 _detect_mode 維持 prefix。"""
    assert _detect_mode("IPZZ") == "prefix"


def test_oracle_b_detect_mode():
    """DoD-3 Oracle B: _detect_mode 標籤對照（206 筆語料，C-only）"""
    corpus_file = Path(__file__).parent / "test_number_corpus_139.py"
    with open(corpus_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    corpus_182 = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CORPUS":
                    corpus_182 = [item["input"] for item in ast.literal_eval(node.value)]
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "CORPUS":
                corpus_182 = [item["input"] for item in ast.literal_eval(node.value)]

    extra_24 = [
        "SONE-0", "ABP-12", "HITMA-1",                      # partial：必須維持 partial
        "IPZZ", "SONE", "ABP",                              # prefix：必須維持 prefix
        "[ABC-123]", "ABC-123.mp4", "【ABC-123】", "(ABC-123)",
        "[JavBus] ABC-123 標題.mp4", "ABC-123 - 中文字幕.mkv",  # residual #6 的包裝
        "FC2-PPV-4914771-C", "HEYZO-1234-C", "FC2PPV-4943690-1080P",  # 收窄修復對象
        "N0762", "K0150", "T1234",                          # [A-Z]\d{4}：退出 G
        "JULIA 2024", "2024", "VR 8K", "MOODYZ 25周年",      # 對抗性：抽不出番號
        "三上悠亜", "波多野結衣",                             # 真實女優名
    ]
    corpus_206 = corpus_182 + extra_24

    def old_dm_mode(q: str) -> str:
        if is_number_format(q):
            return "exact"
        elif is_partial_number(q):
            return "partial"
        elif is_prefix_only(q):
            return "prefix"
        else:
            return "actress"

    moves = []
    diff = []
    for q in corpus_206:
        old_m = old_dm_mode(q)
        new_m = _detect_mode(q)
        if old_m != new_m:
            moves.append((old_m, new_m))
            diff.append((q, old_m, new_m))

    allowed_transitions_dm = {('actress', 'exact')}
    expected_counts_dm = {('actress', 'exact'): 165}

    # ① 方向不變式（只准 actress -> exact）
    assert set(moves) <= allowed_transitions_dm
    # ② 筆數對帳
    assert dict(Counter(moves)) == expected_counts_dm
