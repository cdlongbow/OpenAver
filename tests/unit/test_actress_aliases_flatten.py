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

from web.routers.actress import _flatten_aliases


class TestFlattenAliases:


    def test_none_input(self):
        """None → 回傳空 list"""
        assert _flatten_aliases(None) == []

    def test_mixed_dict_and_str(self):
        """混合 dict + str → 正確處理兩種型別"""
        raw = [{"ja": "A"}, "B"]
        assert _flatten_aliases(raw) == ["A", "B"]

