"""
test_collection_analysis.py — Unit tests for _is_western, _is_corrupted_number,
_has_japanese_tags helpers and is_number_format (no_nfo group filter).

All tests are pure Python — no FS, no DB, no network.
Updated for TASK-139: is_number_format delegates to is_strict_number.
"""

import pytest
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

    def test_western_path_05_returns_true(self):
        """《05》路徑 → True"""
        assert self._is_western("file:///library/《05》歐美/SOME-001.mp4") is True

    def test_western_path_xiyangfolder_returns_true(self):
        """含「西洋」字串路徑 → True"""
        assert self._is_western("file:///library/西洋/test.mp4") is True

    def test_non_western_path_returns_false(self):
        """一般日本片路徑 → False"""
        assert self._is_western("file:///library/宮島めい/SONE-205.mp4") is False

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

    def test_tk_prefix_returns_true(self):
        """TK_prefix: TKIPZ-154 → True"""
        assert self._is_corrupted_number("TKIPZ-154") is True

    def test_k9_prefix_returns_true(self):
        """K9_prefix: K9IPZ-154 → True"""
        assert self._is_corrupted_number("K9IPZ-154") is True

    def test_r_prefix_returns_true(self):
        """R_prefix: R-IPZ-154 → True"""
        assert self._is_corrupted_number("R-IPZ-154") is True

    def test_normal_number_returns_false(self):
        """正常番號 IPZ-154 → False"""
        assert self._is_corrupted_number("IPZ-154") is False

    def test_none_returns_false(self):
        """None → False（None-guard 不拋例外）"""
        assert self._is_corrupted_number(None) is False

    def test_lowercase_digit_prefix_returns_true(self):
        """小寫 digit_prefix: 7ipz-154 → True（upper() 轉換後匹配）"""
        assert self._is_corrupted_number("7ipz-154") is True


# ── U3: _has_japanese_tags ────────────────────────────────────────────────────

class TestHasJapaneseTags:
    """U3: _has_japanese_tags 應正確辨識含假名的 tags JSON"""

    def setup_method(self):
        from web.routers.collection import _has_japanese_tags
        self._has_japanese_tags = _has_japanese_tags

    def test_katakana_tags_returns_true(self):
        """含片假名 tag → True"""
        assert self._has_japanese_tags('["ハイビジョン","巨乳"]') is True

    def test_hiragana_tags_returns_true(self):
        """含平假名 tag → True"""
        assert self._has_japanese_tags('["単体作品","なんでも"]') is True

    def test_english_only_tags_returns_false(self):
        """純英文 tag → False"""
        assert self._has_japanese_tags('["big boobs","amateur"]') is False

    def test_empty_array_returns_false(self):
        """空陣列 → False"""
        assert self._has_japanese_tags('[]') is False

    def test_empty_string_returns_false(self):
        """空字串 → False"""
        assert self._has_japanese_tags('') is False

    def test_none_returns_false(self):
        """None → False（None-guard 不拋例外）"""
        assert self._has_japanese_tags(None) is False

    def test_invalid_json_returns_false(self):
        """非法 JSON → False（不拋例外）"""
        assert self._has_japanese_tags('not valid json [') is False


# ── U4: is_number_format (no_nfo group filter) ────────────────────────────────

class TestIsNumberFormatNoNfoFilter:
    """U4: 確認 core.scraper.is_number_format 行為符合 no_nfo group 篩選需求"""

    def test_ipz_154_returns_true(self):
        """IPZ-154 → True（標準番號格式）"""
        assert is_number_format("IPZ-154") is True

    def test_sone_205_returns_true(self):
        """SONE-205 → True"""
        assert is_number_format("SONE-205") is True

    def test_fc2_ppv_returns_true(self):
        """FC2-PPV-1234567 → True（符合 is_strict_number）"""
        assert is_number_format("FC2-PPV-1234567") is True

    def test_digit_prefix_returns_true(self):
        """7IPZ-154 → True（符合 is_strict_number）"""
        assert is_number_format("7IPZ-154") is True
