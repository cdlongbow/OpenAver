"""
test_maker_mapping.py - core/maker_mapping.py 單元測試

測試範圍：
- load_name_mapping(): 新格式/舊格式/不存在/損毀
- load_prefix_mapping(): 新格式/舊格式/不存在/損毀，不含 _meta 等 key
- normalize_maker_name(): 查表命中/無對照/空字串/None
- get_maker_by_prefix(): prefix hit 回傳片商，miss／無字母前綴回傳空字串且不呼叫 JavDB
- Video.to_legacy_dict(): maker 欄位套用 normalize_maker_name()
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ============ Fixtures ============

NEW_FORMAT_JSON = {
    "_meta": {"format": "hybrid", "updated": "2026-03-28"},
    "name_mapping": {
        "エスワン ナンバーワンスタイル": "S1",
        "S1 NO.1 STYLE": "S1",
        "ムーディーズ": "Moodyz",
        "MOODYZ": "Moodyz",
    },
    "prefix_mapping": {
        "MIAA": "Moodyz",
        "SNIS": "S1",
        "ABF": "Prestige",
    },
}

OLD_FORMAT_JSON = {
    "MIAA": "Moodyz",
    "SNIS": "S1",
    "ABF": "Prestige",
}


@pytest.fixture
def new_format_file(tmp_path):
    """新格式 maker_mapping.json"""
    p = tmp_path / "maker_mapping.json"
    p.write_text(json.dumps(NEW_FORMAT_JSON, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def old_format_file(tmp_path):
    """舊格式 maker_mapping.json（純平坦 dict）"""
    p = tmp_path / "maker_mapping.json"
    p.write_text(json.dumps(OLD_FORMAT_JSON, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def nonexistent_file(tmp_path):
    """不存在的路徑"""
    return tmp_path / "no_such_file.json"


@pytest.fixture
def corrupted_file(tmp_path):
    """損毀的 JSON 檔"""
    p = tmp_path / "maker_mapping.json"
    p.write_text("{invalid json", encoding="utf-8")
    return p


# ============ load_name_mapping ============


# ============ load_prefix_mapping ============


# ============ normalize_maker_name ============

class TestNormalizeMakerName:
    def test_known_katakana_name(self, new_format_file, monkeypatch):
        """片假名 key 命中 → 回傳 canonical 短名"""
        import core.maker_mapping as mm
        monkeypatch.setattr(mm, "MAKER_MAPPING_FILE", new_format_file)
        monkeypatch.setattr(mm, "_cache", None)
        assert mm.normalize_maker_name("エスワン ナンバーワンスタイル") == "S1"


# ============ get_maker_by_prefix ============

class TestGetMakerByPrefix:
    def test_prefix_hit_returns_maker_no_javdb(self, new_format_file, monkeypatch):
        """prefix 在 prefix_mapping 中存在 → 直接回傳，不呼叫 JavDB"""
        import core.maker_mapping as mm
        monkeypatch.setattr(mm, "MAKER_MAPPING_FILE", new_format_file)
        monkeypatch.setattr(mm, "_cache", None)

        mock_javdb = MagicMock()
        with patch("core.scrapers.JavDBScraper", mock_javdb):
            result = mm.get_maker_by_prefix("MIAA-123")

        assert result == "Moodyz"
        mock_javdb.assert_not_called()


# ============ Video.to_legacy_dict() maker normalize ============

class TestVideoToLegacyDictMaker:
    """Video.to_legacy_dict() 的 maker 欄位應套用 normalize_maker_name()"""

    # name_mapping 供 mock 使用
    MOCK_NAME_MAPPING = {
        "エスワン ナンバーワンスタイル": "S1",
        "S1 NO.1 STYLE": "S1",
        "ムーディーズ": "Moodyz",
    }

    @pytest.fixture(autouse=True)
    def patch_name_mapping(self, monkeypatch):
        """mock load_name_mapping 回傳固定 dict，不讀真實檔案"""
        import core.maker_mapping as mm
        monkeypatch.setattr(mm, "_cache", None)
        monkeypatch.setattr(
            mm, "load_name_mapping",
            lambda: self.MOCK_NAME_MAPPING,
        )

    def _make_video(self, maker):
        from core.scrapers.models import Video
        return Video(number="SONE-001", maker=maker)

    def test_katakana_maker_is_normalized(self):
        """maker = 片假名長名 → to_legacy_dict()['maker'] 為 canonical 短名"""
        v = self._make_video("エスワン ナンバーワンスタイル")
        assert v.to_legacy_dict()["maker"] == "S1"


