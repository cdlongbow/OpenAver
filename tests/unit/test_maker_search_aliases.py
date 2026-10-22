"""175b-T10：search_aliases 內容（CD-175b-5）。真 JSON、期望值字面寫死（BE-TEST-23）。"""
from unittest.mock import patch

import pytest

import core.maker_mapping as mm
import core.maker_names as mn
from core.maker_names import known_makers, maker_spellings
from core.query_intent import classify_query
from core.search_providers.javdb import _maker_names

# 裁可清單（逐字）
EXPECTED_ALIASES = {
    "カリビアンコム": "Caribbeancom",
    "エスワン": "S1",
    "エスオーディー": "SOD Create",
    "ソフト・オン・デマンド": "SOD Create",
    "レアル・ワークス": "Real Works",
}


@pytest.fixture
def known():
    mn._static_keys.cache_clear()
    with patch("core.maker_names.library_maker_names", return_value=set()):
        yield known_makers()
    mn._static_keys.cache_clear()


@pytest.mark.parametrize("q", [
    "カリビアンコム",
])
def test_alias_queries_classify_as_maker(known, q):
    assert classify_query(q, known, resolve_makers=True).mode == "maker"


@pytest.mark.parametrize("q,must_contain", [
    ("カリビアンコム", "Caribbeancom"),
])
def test_javdb_candidate_set_contains_site_name(q, must_contain):
    names = _maker_names(q)
    assert must_contain in names, names
    assert len(names) <= 4


@pytest.mark.parametrize("q,expected", [
    # 會被 name_mapping 改寫的（既有行為）
    # 不該被改寫的（別名只認不寫；併入 name_mapping 就會轉紅）
    ("カリビアンコム", "カリビアンコム"),
])
def test_search_aliases_never_leak_into_name_mapping(q, expected):
    assert mm.normalize_maker_name(q) == expected


def test_alias_values_are_existing_canonical_names():
    canon = set(mm.load_name_mapping().values()) | set(mm.load_prefix_mapping().values())
    for a, c in EXPECTED_ALIASES.items():
        assert c in canon, (a, c)


def test_independent_canonicals_are_not_merged():
    """SOD（prefix_mapping 獨立正名）與 SOD Create 不得被別名合併（Codex P2：JavBus 樣本會混進 SOD 集團）。"""
    assert "SOD" not in maker_spellings("SOD Create")
    assert maker_spellings("SOD") == ["SOD"]
    assert "SOD" not in _maker_names("SOD Create")
    assert maker_spellings("SOD Create") == ["SOD Create", "SODクリエイト", "エスオーディー", "ソフト・オン・デマンド"]
