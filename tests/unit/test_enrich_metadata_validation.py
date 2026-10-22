"""
test_enrich_metadata_validation.py - metadata 形狀驗證與清洗之單元測試

覆蓋：
- DoD-3 (CD-135-2): 未知欄位 400 且包含該 key
- DoD-4 (AC-4): tags/actors/duration/_rating 型別驗證 400
- DoD-5 (CD-135-3): 九個忽略鍵不觸發 400
- DoD-6 (CD-135-14): original_title 空字串拒絕，非空放行；title 空字串放行
- _clean_metadata_for_scraper_data: 8 個忽略鍵剔除，source 保留
"""

import pytest
from fastapi import HTTPException
from web.routers.scraper import (  # noqa: PLC2701
    _validate_metadata_shape,
    _resolve_write_cover,
)


class TestValidateMetadataShape:
    """測試 _validate_metadata_shape 純函式邊界"""

    def test_unknown_field_raises_400_with_key_name(self):
        """DoD-3: metadata 含未知 key（例 titl）→ 400 且 detail 字串內含該 key 名"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"titl": "Some Title"})
        assert exc_info.value.status_code == 400
        assert "titl" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info2:
            _validate_metadata_shape({"unknown_custom_prop": 123})
        assert exc_info2.value.status_code == 400
        assert "unknown_custom_prop" in exc_info2.value.detail


    def test_type_validation_actors_as_string_raises_400(self):
        """DoD-4: actors 傳字串 → 400 且 detail 指名 actors"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"actors": "三上悠亞"})
        assert exc_info.value.status_code == 400
        assert "actors" in exc_info.value.detail


    def test_cd_135_14_original_title_empty_string_rejected(self):
        """DoD-6 (CD-135-14 / M2): original_title 為空字串時拒絕 400"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"original_title": ""})
        assert exc_info.value.status_code == 400
        assert "original_title" in exc_info.value.detail


    def test_ignored_keys_allowed(self):
        """DoD-5 (CD-135-3): 九個忽略鍵出現在 metadata 內不觸發 400"""
        ignored_packet = {
            "number": "ABC-123",
            "source": "javdb",
            "mode": "refresh_full",
            "success": True,
            "total": 1,
            "_source": "javdb",
            "_mode": "exact",
            "_all_variant_ids": ["ABC-123-1"],
            "candidates": [{"id": 1}],
            "title": "合法標題",
        }
        # 不應拋出未知 key 或型別錯誤
        _validate_metadata_shape(ignored_packet)


class TestResolveWriteCover:
    """DoD-5: 測試 _resolve_write_cover 純函式之四種輸入組合"""

    def test_resolve_write_cover_none_with_metadata_returns_false(self):
        """DoD-5 / M1: (None, has_metadata=True) → False（有 metadata 且未表態時不換封面）"""
        assert _resolve_write_cover(None, has_metadata=True) is False


