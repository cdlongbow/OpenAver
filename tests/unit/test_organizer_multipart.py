"""
測試 core/organizer.py 中的多段 token 純函式：
  - MULTIPART_TOKENS 常數
  - _detect_multipart_token(filename) -> Optional[Tuple[str, int]]
  - _strip_part_token(stem) -> str

TDD-lite：先 RED，實作後 GREEN。
"""
from core.organizer import (
    _detect_multipart_token,
    _strip_part_token,
)


# ---------------------------------------------------------------------------
# MULTIPART_TOKENS 常數
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _detect_multipart_token — Positive cases
# ---------------------------------------------------------------------------

class TestDetectMultipartTokenPositive:
    def test_cd1(self):
        assert _detect_multipart_token('MIRD-151-cd1.mkv') == ('cd1', 1)


    def test_rightmost_match_wins(self):
        """多個 token 時取最右（靠後）那個"""
        result = _detect_multipart_token('MIRD-cd1-cd2.mkv')
        assert result == ('cd2', 2)


# ---------------------------------------------------------------------------
# _detect_multipart_token — Negative cases
# ---------------------------------------------------------------------------

class TestDetectMultipartTokenNegative:

    def test_cd10_two_digits(self):
        """cd10 數字≥10，不匹配"""
        assert _detect_multipart_token('cd10') is None


    def test_apartment1_no_false_positive(self):
        """apartment1：前緣是字母 t，part1 不得誤命中"""
        assert _detect_multipart_token('apartment1.mkv') is None


# ---------------------------------------------------------------------------
# _strip_part_token
# ---------------------------------------------------------------------------

class TestStripPartToken:
    def test_strip_dash_cd1(self):
        """MIRD-151-cd1 → MIRD-151（連前導 - 一起剝）"""
        assert _strip_part_token('MIRD-151-cd1') == 'MIRD-151'


