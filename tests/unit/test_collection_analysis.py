"""
test_collection_analysis.py — Unit tests for _is_western, _is_corrupted_number,
_has_japanese_tags helpers and is_number_format (no_nfo group filter).

All tests are pure Python — no FS, no DB, no network.
Updated for TASK-139: is_number_format delegates to is_strict_number.
"""

from core.scraper import is_number_format


# ── U1: _is_western ───────────────────────────────────────────────────────────

class TestIsWestern:
    """U1: _is_western 應依路徑中的關鍵字正確回傳 True/False"""

    def setup_method(self):
        from web.routers.collection import _is_western
        self._is_western = _is_western

    def test_western_path_03_returns_true(self):
        """《03》路徑 → True"""
        assert self._is_western("file:///library/《03》西洋單片區/ABW-001.mp4") is True


    def test_empty_string_returns_false(self):
        """空字串 → False"""
        assert self._is_western("") is False


# ── U2: _is_corrupted_number ──────────────────────────────────────────────────

class TestIsCorruptedNumber:
    """U2: _is_corrupted_number 應正確辨識 4 種 corruption 模式"""

    def setup_method(self):
        from web.routers.collection import _is_corrupted_number
        self._is_corrupted_number = _is_corrupted_number

    def test_digit_prefix_returns_true(self):
        """digit_prefix: 7IPZ-154 → True"""
        assert self._is_corrupted_number("7IPZ-154") is True


# ── U3: _has_japanese_tags ────────────────────────────────────────────────────

class TestHasJapaneseTags:
    """U3: _has_japanese_tags 應正確辨識含假名的 tags JSON"""

    def setup_method(self):
        from web.routers.collection import _has_japanese_tags
        self._has_japanese_tags = _has_japanese_tags

    def test_katakana_tags_returns_true(self):
        """含片假名 tag → True"""
        assert self._has_japanese_tags('["ハイビジョン","巨乳"]') is True


    def test_english_only_tags_returns_false(self):
        """純英文 tag → False"""
        assert self._has_japanese_tags('["big boobs","amateur"]') is False


# ── U4: is_number_format (no_nfo group filter) ────────────────────────────────

class TestIsNumberFormatNoNfoFilter:
    """U4: 確認 core.scraper.is_number_format 行為符合 no_nfo group 篩選需求"""

    def test_ipz_154_returns_true(self):
        """IPZ-154 → True（標準番號格式）"""
        assert is_number_format("IPZ-154") is True


