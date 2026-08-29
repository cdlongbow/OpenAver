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
from web.routers.scraper import _validate_metadata_shape, _clean_metadata_for_scraper_data  # noqa: PLC2701


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

    def test_valid_whitelist_fields_pass(self):
        """所有 17 個白名單合法欄位均能順利通過驗證"""
        valid_meta = {
            "title": "合法標題",
            "original_title": "Original Title",
            "actors": ["演員A", "演員B"],
            "maker": "片商",
            "director": "導演",
            "series": "系列",
            "label": "廠牌",
            "tags": ["標籤1", "標籤2"],
            "date": "2025-01-01",
            "duration": 120,
            "cover": "https://example.com/cover.jpg",
            "preview_cover_url": "https://example.com/prev.jpg",
            "preview_sample_images": ["https://example.com/sample1.jpg"],
            "url": "https://example.com/movie",
            "sample_images": ["https://example.com/s1.jpg", "https://example.com/s2.jpg"],
            "_summary": "大綱簡介",
            "_rating": 4.5,
        }
        # 不應拋出任何例外
        _validate_metadata_shape(valid_meta)

    def test_duration_and_rating_nullable_or_numeric(self):
        """duration 接受 int 或 None；_rating 接受 float, int 或 None"""
        _validate_metadata_shape({"duration": None, "_rating": None})
        _validate_metadata_shape({"duration": 90, "_rating": 4})
        _validate_metadata_shape({"_rating": 3.8})

    def test_type_validation_string_fields(self):
        """字串型別欄位傳非字串 → 400 且指名該欄位"""
        for field in ["title", "maker", "director", "series", "label", "date", "cover", "preview_cover_url", "url", "_summary"]:
            with pytest.raises(HTTPException) as exc_info:
                _validate_metadata_shape({field: 12345})
            assert exc_info.value.status_code == 400
            assert field in exc_info.value.detail

    def test_type_validation_tags_as_string_raises_400(self):
        """DoD-4: tags 傳字串 → 400 且 detail 指名 tags"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"tags": "tag1,tag2"})
        assert exc_info.value.status_code == 400
        assert "tags" in exc_info.value.detail

    def test_type_validation_actors_as_string_raises_400(self):
        """DoD-4: actors 傳字串 → 400 且 detail 指名 actors"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"actors": "三上悠亞"})
        assert exc_info.value.status_code == 400
        assert "actors" in exc_info.value.detail

    def test_type_validation_duration_as_string_raises_400(self):
        """DoD-4: duration 傳 '120'（字串）或 bool → 400 且 detail 指名 duration"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"duration": "120"})
        assert exc_info.value.status_code == 400
        assert "duration" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info2:
            _validate_metadata_shape({"duration": True})
        assert exc_info2.value.status_code == 400
        assert "duration" in exc_info2.value.detail

    def test_type_validation_rating_as_string_raises_400(self):
        """_rating 傳字串或 bool → 400 且 detail 指名 _rating"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"_rating": "4.5"})
        assert exc_info.value.status_code == 400
        assert "_rating" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info2:
            _validate_metadata_shape({"_rating": False})
        assert exc_info2.value.status_code == 400
        assert "_rating" in exc_info2.value.detail

    def test_type_validation_list_elements_must_be_strings(self):
        """list 欄位（如 sample_images）內含非字串元素 → 400"""
        for field in ["actors", "tags", "preview_sample_images", "sample_images"]:
            with pytest.raises(HTTPException) as exc_info:
                _validate_metadata_shape({field: [123, "valid"]})
            assert exc_info.value.status_code == 400
            assert field in exc_info.value.detail

    def test_cd_135_14_original_title_empty_string_rejected(self):
        """DoD-6 (CD-135-14 / M2): original_title 為空字串時拒絕 400"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_metadata_shape({"original_title": ""})
        assert exc_info.value.status_code == 400
        assert "original_title" in exc_info.value.detail

    def test_cd_135_14_original_title_non_empty_passes(self):
        """DoD-6 (CD-135-14): original_title 為非空字串時通過"""
        _validate_metadata_shape({"original_title": "Valid Original Title"})

    def test_cd_135_14_title_empty_string_passes(self):
        """DoD-6 (CD-135-14): title 為空字串時不得 400（抓「拒絕所有空字串」的偷懶實作）"""
        _validate_metadata_shape({"title": ""})
        _validate_metadata_shape({"_summary": ""})

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


class TestCleanMetadataForScraperData:
    """測試 _clean_metadata_for_scraper_data 剔除行為"""

    def test_removes_eight_ignored_keys_and_preserves_source(self):
        """DoD-5 / M3: 清洗只剔除八個鍵，source 刻意保留"""
        packet = {
            "title": "標題",
            "source": "javdb",
            "number": "ABC-123",
            "mode": "refresh_full",
            "success": True,
            "total": 1,
            "_source": "javdb",
            "_mode": "exact",
            "_all_variant_ids": ["ABC-123"],
            "candidates": ["candidate1"],
            "tags": ["tag1"],
        }
        cleaned = _clean_metadata_for_scraper_data(packet)

        # source 必須被保留
        assert "source" in cleaned
        assert cleaned["source"] == "javdb"

        # 白名單欄位必須保留
        assert cleaned["title"] == "標題"
        assert cleaned["tags"] == ["tag1"]

        # 八個鍵必須被剔除
        eight_keys = ["number", "mode", "success", "total", "_source", "_mode", "_all_variant_ids", "candidates"]
        for k in eight_keys:
            assert k not in cleaned, f"Key '{k}' should be stripped by cleaner"
