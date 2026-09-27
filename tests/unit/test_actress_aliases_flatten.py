"""
Unit tests for _flatten_aliases helper in web/routers/actress.py

Tests the 6 specified cases:
1. dict list 格式 → extract "ja" field
2. string list (wiki format) → pass-through unchanged
3. empty list → []
4. None → []
5. mixed dict + str → handle both correctly
6. dict without "ja" key → fallback to empty string
"""

import pytest
from web.routers.actress import _flatten_aliases


class TestFlattenAliases:
    def test_dict_list_format(self):
        """dict-list 格式來源回傳 dict list，應取出 ja 欄"""
        raw = [{"ja": "笹川そら", "hiragana": "ささがわそら", "romaji": "Sasagawa Sora"}]
        assert _flatten_aliases(raw) == ["笹川そら"]

    def test_string_list_wiki_format(self):
        """wiki scraper 回傳純字串 list，應保持不變"""
        raw = ["上川星空", "笹川そら"]
        assert _flatten_aliases(raw) == ["上川星空", "笹川そら"]

    def test_empty_list(self):
        """空 list → 回傳空 list"""
        assert _flatten_aliases([]) == []

    def test_none_input(self):
        """None → 回傳空 list"""
        assert _flatten_aliases(None) == []

    def test_mixed_dict_and_str(self):
        """混合 dict + str → 正確處理兩種型別"""
        raw = [{"ja": "A"}, "B"]
        assert _flatten_aliases(raw) == ["A", "B"]

    def test_dict_without_ja_key(self):
        """dict 無 ja key → fallback 空字串"""
        raw = [{"en": "foo"}]
        assert _flatten_aliases(raw) == [""]
