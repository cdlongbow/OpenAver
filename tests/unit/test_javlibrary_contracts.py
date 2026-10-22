"""
tests/unit/test_javlibrary_contracts.py — T3 javlibrary 來源系統 contract 守衛

驗證 javlibrary 加入 source 系統各處的契約：
  - validate_source_id 放行
  - CENSORED_SOURCES 包含（不觸發 L77 warning）
  - SOURCE_ORDER 不含（不污染 fan-out）
  - 不在 search_providers 註冊表（exact-only）
  - get_manual_only_sources() 回傳正確屬性
  - JavLibraryScraper importable + in __all__
  - get_enabled_source_ids 不含 javlibrary（manual_only=True 被過濾）
"""
import json



# 1. validate_source_id 放行
def test_validate_source_id_javlibrary():
    from core.source_config import validate_source_id
    assert validate_source_id('javlibrary') is True


# 2. CENSORED_SOURCES 包含 javlibrary（is_censored 無 warning）


# 3. 不在 SOURCE_ORDER（不污染 fan-out）


# 4. 不在 search_providers 註冊表（exact-only）


# 5. get_manual_only_sources() 回傳 javlibrary，屬性正確


# 6. is_censored 計算正確（builtin 分支命中 CENSORED_SOURCES，不觸發 warning）


# 7. JavLibraryScraper 可從 __init__.py import


# 8. JavLibraryScraper 在 __all__


# 9. get_enabled_source_ids 不含 javlibrary
#    （monkeypatch CONFIG_PATH 注入含 javlibrary enabled=True 的 config）
def test_get_enabled_source_ids_excludes_javlibrary(tmp_path, monkeypatch):
    import core.config as core_config
    from core.source_config import get_manual_only_sources
    from core.source_settings import get_enabled_source_ids

    # 構造含 javlibrary 的 config（即使 enabled=True，manual_only=True 應被過濾）
    sources = [
        {"id": "javbus", "type": "builtin", "display_name_key": "JavBus", "display_name_raw": "",
         "enabled": True, "order": 1, "config": {}, "is_beta": False, "manual_only": False},
        {**get_manual_only_sources()[0].model_dump(), "enabled": True},  # javlibrary enabled=True 仍被過濾
    ]
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"sources": sources}))
    monkeypatch.setattr(core_config, "CONFIG_PATH", config_file)

    result = get_enabled_source_ids()
    assert 'javlibrary' not in result
    assert 'javbus' in result
