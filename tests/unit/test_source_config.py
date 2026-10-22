"""TASK-61a-1: SourceConfig 模型 + helper + validator 單元測試"""
from core.scrapers.utils import SOURCE_ORDER
from core.source_config import (
    SourceConfig,
    build_metatube_sources,
    get_builtin_sources,
    get_manual_only_sources,
    validate_source_id,
)


# ---------------------------------------------------------------------------
# MAX_ENABLED_SOURCES 常數
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# render_name 雙模式
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# get_builtin_sources
# ---------------------------------------------------------------------------


def test_get_builtin_sources_all_enabled():
    assert all(s.enabled is True for s in get_builtin_sources())


# ---------------------------------------------------------------------------
# validate_source_id
# ---------------------------------------------------------------------------
def test_validate_source_id_known_builtins():
    for sid in SOURCE_ORDER:
        assert validate_source_id(sid) is True


# ---------------------------------------------------------------------------
# manual_only default
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# is_censored computed field
# ---------------------------------------------------------------------------


def test_is_censored_builtin_uncensored_fc2():
    s = SourceConfig(id='fc2', type='builtin', display_name_key='FC2')
    assert s.is_censored is False


# ---------------------------------------------------------------------------
# get_source_enum（TASK-61a-4）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# A. display_name_key=None 可建構（TASK-63a-1 CD-63a-1）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# B. requires_proxy default / builtin DMM / builtin 其餘（CD-63a-3）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# C. validate_source_id metatube 放行（63c，CD-63c-1）
# ---------------------------------------------------------------------------
def test_validate_source_id_metatube_fanza_true():
    """63c 放行：metatube:FANZA → True"""
    assert validate_source_id('metatube:FANZA') is True


# ---------------------------------------------------------------------------
# D. build_metatube_sources() 各欄正確（CD-63a-5）
# ---------------------------------------------------------------------------
def test_build_metatube_sources_basic_fields():
    """build_metatube_sources 回傳 3 筆，各欄正確"""
    results = build_metatube_sources(['FANZA', 'HEYZO', 'UnknownX'])
    assert len(results) == 3
    for s in results:
        assert s.type == 'metatube'
        assert s.enabled is False
        assert s.manual_only is False
        assert s.id == f'metatube:{s.display_name_raw}'


# ---------------------------------------------------------------------------
# E. canonical order（不吃輸入順序）（CD-63a-5）
# ---------------------------------------------------------------------------
def test_canonical_order_fanza_before_heyzo():
    """FANZA 在 METATUBE_PROVIDER_ORDER 靠前 → FANZA.order < HEYZO.order"""
    by_name = {s.display_name_raw: s for s in build_metatube_sources(['HEYZO', 'FANZA'])}
    assert by_name['FANZA'].order < by_name['HEYZO'].order


# ---------------------------------------------------------------------------
# F. is_censored computed 驗 builder 填值正確（CD-63a-4）
# ---------------------------------------------------------------------------


def test_is_censored_builder_heyzo_false():
    """build_metatube_sources(['HEYZO']) → HEYZO.is_censored is False"""
    sources = build_metatube_sources(['HEYZO'])
    assert sources[0].is_censored is False


# ---------------------------------------------------------------------------
# G. requires_proxy derives on reconstruct from stored dict（Fix 1 / P1a）
# ---------------------------------------------------------------------------

def test_requires_proxy_derives_on_reconstruct_from_stored_dict_dmm():
    """舊 dict（無 requires_proxy key）重建 → builtin dmm 應 derive True"""
    old_dict = {
        'id': 'dmm',
        'type': 'builtin',
        'display_name_key': 'DMM',
        # 故意不含 requires_proxy key（模擬舊 config.json 存的 entry）
    }
    s = SourceConfig(**old_dict)
    assert s.requires_proxy is True


# ---------------------------------------------------------------------------
# TASK-118a-T2：fc-javten manual_only 來源登記
# ---------------------------------------------------------------------------
def test_validate_source_id_fc_javten():
    """CD-118a-10：validate_source_id 查 manual_only 集合，不是字面 if。"""
    assert validate_source_id('fc-javten') is True


def test_get_manual_only_sources_returns_fc_javten_second():
    """CD-118a-1／-11／-14／-17：第二筆是 fc-javten，欄位值定案。"""
    sources = get_manual_only_sources()
    assert len(sources) == 2
    assert sources[0].id == 'javlibrary'
    fc = sources[1]
    assert fc.id == 'fc-javten'
    assert fc.display_name_key == 'FC2-javten'
    assert fc.order == 100
    assert fc.enabled is False
    assert fc.manual_only is True
    assert fc.is_beta is True
    assert fc.type == 'builtin'


def test_validate_source_id_custom_slug():
    """custom:<slug> 純語法判斷：合法 slug True；路徑穿越、空、大寫、過長 False。"""
    assert validate_source_id('custom:foo') is True
    assert validate_source_id('custom:a-1') is True
    assert validate_source_id('custom:../x') is False
    assert validate_source_id('custom:') is False
    assert validate_source_id('custom:A') is False
    assert validate_source_id('custom:' + 'a' * 33) is False
    assert validate_source_id('custom:' + 'a' * 32) is True
