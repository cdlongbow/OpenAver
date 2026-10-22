"""test_models.py - Video model 新欄位 + merge policy 測試"""
from core.scrapers.models import Video


# ============ 新欄位預設值 ============


def test_to_legacy_dict_new_keys():
    """to_legacy_dict() 包含新 key"""
    v = Video(
        number='TEST-001',
        director='山田',
        duration=119,
        label='S1',
        series='NTR',
        sample_images=['http://a.jpg'],
        preview_sample_images=['http://proxy/a.jpg'],
    )
    d = v.to_legacy_dict()
    assert d['director'] == '山田'
    assert d['duration'] == 119
    assert d['label'] == 'S1'
    assert d['series'] == 'NTR'
    assert d['sample_images'] == ['http://a.jpg']
    assert d['preview_sample_images'] == ['http://proxy/a.jpg']


# ============ Merge policy 測試 ============

def _make_video(**kwargs) -> Video:
    return Video(number='TEST-001', **kwargs)


def _run_merge(main: Video, backup: Video) -> Video:
    """模擬 scraper.py 中的 merge 邏輯（單輪）"""
    updates = {}
    if not main.title and backup.title:
        updates['title'] = backup.title
    if not main.maker and backup.maker:
        updates['maker'] = backup.maker
    if not main.date and backup.date:
        updates['date'] = backup.date
    if not main.actresses and backup.actresses:
        updates['actresses'] = backup.actresses
    if not main.cover_url and backup.cover_url:
        updates['cover_url'] = backup.cover_url
    if not main.tags and backup.tags:
        updates['tags'] = backup.tags
    # 新欄位 merge
    if not main.director and backup.director:
        updates['director'] = backup.director
    if main.duration is None and backup.duration is not None:
        updates['duration'] = backup.duration
    if not main.label and backup.label:
        updates['label'] = backup.label
    if not main.series and backup.series:
        updates['series'] = backup.series
    if not main.sample_images and backup.sample_images:
        updates['sample_images'] = backup.sample_images
    if updates:
        return main.model_copy(update=updates)
    return main


# ============ to_legacy_dict regression guard（US7 硬契約） ============


def test_to_legacy_dict_key_set_unchanged():
    """16 鍵固定集合（TASK-126-T2 新增 preview_sample_images）"""
    v = Video(number="TEST-001")
    expected_keys = {
        "number", "title", "actors", "date", "maker", "cover",
        "preview_cover_url", "tags", "source", "url", "director", "duration",
        "label", "series", "sample_images", "preview_sample_images",
    }
    assert set(v.to_legacy_dict().keys()) == expected_keys
