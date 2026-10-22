"""
utils.py 擴充函數的單元測試
"""
from core.scrapers.utils import (
    has_japanese, SOURCE_ORDER, SOURCE_NAMES
)


class TestHasJapanese:
    """has_japanese() 測試"""

    def test_hiragana(self):
        """平假名應返回 True"""
        assert has_japanese("これはテスト") is True


    def test_chinese_only(self):
        """純中文應返回 False"""
        assert has_japanese("中文標題") is False


class TestSourceConfig:
    """來源配置常數測試"""

    def test_source_order_not_empty(self):
        """SOURCE_ORDER 應包含至少三個主要來源"""
        assert isinstance(SOURCE_ORDER, list)
        assert len(SOURCE_ORDER) >= 3
        # 應無重複項目
        assert len(set(SOURCE_ORDER)) == len(SOURCE_ORDER)

    def test_source_order_content(self):
        """SOURCE_ORDER 應包含預期來源"""
        assert 'javbus' in SOURCE_ORDER
        assert 'jav321' in SOURCE_ORDER
        assert 'javdb' in SOURCE_ORDER

    def test_source_names_match_order(self):
        """SOURCE_NAMES 應包含所有 SOURCE_ORDER 的鍵"""
        assert isinstance(SOURCE_NAMES, dict)
        for source in SOURCE_ORDER:
            assert source in SOURCE_NAMES

    def test_source_names_values(self):
        """SOURCE_NAMES 的鍵值對格式應正確"""
        for key, name in SOURCE_NAMES.items():
            assert isinstance(key, str)
            assert key
            assert isinstance(name, str)
            assert name
            assert not name.isspace()
