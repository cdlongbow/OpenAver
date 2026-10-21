"""175b-T10：search_aliases 內容（CD-175b-5）。真 JSON、期望值字面寫死（BE-TEST-23）。"""
from unittest.mock import patch

import pytest

import core.maker_mapping as mm
import core.maker_names as mn
from core.maker_names import known_makers, maker_key_of, maker_spellings
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


def test_search_aliases_content_is_exactly_the_approved_set():
    assert mm.load_search_aliases() == EXPECTED_ALIASES


@pytest.mark.parametrize("q", [
    "SOD", "MOODYZ", "Attackers", "アタッカーズ", "本中", "カリビアンコム", "S1",
    "エスワン", "エスオーディー", "ソフト・オン・デマンド", "ムーディーズ", "レアル・ワークス",
])
def test_alias_queries_classify_as_maker(known, q):
    assert classify_query(q, known, resolve_makers=True).mode == "maker"


@pytest.mark.parametrize("q,must_contain", [
    ("S1", "S1 NO.1 STYLE"),
    ("カリビアンコム", "Caribbeancom"),
    ("エスオーディー", "SOD Create"),
    ("ソフト・オン・デマンド", "SOD Create"),
    ("レアル・ワークス", "Real Works"),
])
def test_javdb_candidate_set_contains_site_name(q, must_contain):
    names = _maker_names(q)
    assert must_contain in names, names
    assert len(names) <= 4


def test_javdb_candidate_set_exact_lists():
    assert _maker_names("カリビアンコム") == ["カリビアンコム", "Caribbeancom"]
    assert _maker_names("SOD") == ["SOD"]  # T10 前的值：SOD 與 SOD Create 是兩個獨立正名
    assert _maker_names("エスオーディー") == ["エスオーディー", "SOD Create", "SODクリエイト", "ソフト・オン・デマンド"]


@pytest.mark.parametrize("q,before", [  # 補別名前的快照：前綴順序與內容不得退步
    ("S1", ["S1", "エスワン ナンバーワンスタイル", "エスワンナンバーワンスタイル", "S1 NO.1 STYLE"]),
    ("MOODYZ", ["MOODYZ", "ムーディーズ"]),
    ("Attackers", ["Attackers", "アタッカーズ"]),
    ("本中", ["本中", "HONNAKA"]),
])
def test_existing_candidate_sets_not_degraded(q, before):
    assert _maker_names(q) == before


@pytest.mark.parametrize("q,expected", [
    # 會被 name_mapping 改寫的（既有行為）
    ("MOODYZ", "Moodyz"), ("ムーディーズ", "Moodyz"), ("本中", "HONNAKA"),
    ("S1 NO.1 STYLE", "S1"), ("レアルワークス", "Real Works"), ("SODクリエイト", "SOD Create"),
    # 不該被改寫的（別名只認不寫；併入 name_mapping 就會轉紅）
    ("カリビアンコム", "カリビアンコム"), ("エスワン", "エスワン"), ("エスオーディー", "エスオーディー"),
    ("ソフト・オン・デマンド", "ソフト・オン・デマンド"), ("SOD", "SOD"),
    ("レアル・ワークス", "レアル・ワークス"),
    ("S1", "S1"), ("Moodyz", "Moodyz"), ("HONNAKA", "HONNAKA"), ("Honnaka", "Honnaka"),
    ("SOD Create", "SOD Create"), ("Real Works", "Real Works"),
])
def test_search_aliases_never_leak_into_name_mapping(q, expected):
    assert mm.normalize_maker_name(q) == expected


def test_alias_keys_not_in_name_mapping():
    nm = mm.load_name_mapping()
    assert not set(EXPECTED_ALIASES) & set(nm)


def test_tables_unchanged_from_head_snapshot():
    nm, pm = mm.load_name_mapping(), mm.load_prefix_mapping()
    assert len(nm) == 114 and len(pm) == 583
    assert nm["本中"] == "HONNAKA" and nm["ムーディーズ"] == "Moodyz"
    assert nm["SODクリエイト"] == "SOD Create" and nm["レアルワークス"] == "Real Works"
    assert pm["CRB"] == "Caribbeancom" and pm["SNIS"] == "S1" and pm["GANA"] == "SOD"
    assert pm["SODS"] == "SOD Create"
    assert not set(EXPECTED_ALIASES) & set(nm)


def test_alias_upper_not_in_prefix_mapping_keys():
    pm = mm.load_prefix_mapping()
    for a in EXPECTED_ALIASES:
        assert a.upper() not in pm


def test_alias_values_are_existing_canonical_names():
    canon = set(mm.load_name_mapping().values()) | set(mm.load_prefix_mapping().values())
    for a, c in EXPECTED_ALIASES.items():
        assert c in canon, (a, c)


def test_alias_keys_do_not_collide_with_any_other_canon():
    """任何別名都不准與另一個正名同 key（零例外）。"""
    canon = set(mm.load_name_mapping().values()) | set(mm.load_prefix_mapping().values())
    ck = {}
    for c in canon:
        ck.setdefault(maker_key_of(c), set()).add(c)
    clash = {a for a, c in EXPECTED_ALIASES.items() if ck.get(maker_key_of(a), set()) - {c}}
    assert clash == set()


def test_independent_canonicals_are_not_merged():
    """SOD（prefix_mapping 獨立正名）與 SOD Create 不得被別名合併（Codex P2：JavBus 樣本會混進 SOD 集團）。"""
    assert "SOD" not in maker_spellings("SOD Create")
    assert maker_spellings("SOD") == ["SOD"]
    assert "SOD" not in _maker_names("SOD Create")
    assert maker_spellings("SOD Create") == ["SOD Create", "SODクリエイト", "エスオーディー", "ソフト・オン・デマンド"]
