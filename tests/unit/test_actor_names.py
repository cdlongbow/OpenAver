"""175d-T1：名稱組純函式（actor_names）。期望值字面寫死，輸入全是我們自己的字串與 tmp sqlite。"""

import sqlite3

import pytest

from core.search_providers.actor_names import (
    expand_actor_names,
    load_alias_groups,
    needs_swap_first,
    swap_candidates,
)

G_AKANE = ("二階堂麗", ["あかね麗"])
G_MIRU = ("坂道みる", ["miru"])
G_FIVE = ("甲", ["乙", "丙", "丁", "戊"])


# ---------- expand_actor_names ----------


@pytest.mark.parametrize("q", ["あかね麗", "二階堂麗"])
def test_expand_same_list_from_any_member(q):
    assert expand_actor_names(q, [G_AKANE]) == ["二階堂麗", "あかね麗"]


def test_expand_same_list_from_first_and_fifth_of_five():
    assert expand_actor_names("甲", [G_FIVE]) == ["甲", "乙", "丙", "丁"]
    assert expand_actor_names("戊", [G_FIVE]) == ["甲", "乙", "丙", "丁"]


@pytest.mark.parametrize("q", ["MIRU", "ｍｉｒｕ", "Ｍiru"])
def test_expand_folds_width_and_case(q):
    assert expand_actor_names(q, [G_AKANE, G_MIRU]) == ["坂道みる", "miru"]


def test_expand_caps_at_four():
    out = expand_actor_names("乙", [G_FIVE])
    assert out == ["甲", "乙", "丙", "丁"]
    assert "戊" not in out


@pytest.mark.parametrize(
    "q,groups",
    [("山田花子", [G_AKANE, G_MIRU]), ("山田花子", []), ("", [G_AKANE]), ("・-", [G_AKANE])],
)
def test_expand_miss_returns_query_itself(q, groups):
    assert expand_actor_names(q, groups) == [q]


def test_expand_dedups_fold_collision_keeps_first():
    group = ("二階堂麗", ["あかね・麗", "あかね麗", "あ か ね 麗"])
    assert expand_actor_names("あかね麗", [group]) == ["二階堂麗", "あかね・麗"]


# ---------- needs_swap_first ----------


@pytest.mark.parametrize(
    "q,expected",
    [
        ("Yua Mikami", True),
        ("Ｙｕａ", True),
        ("miru", True),
        ("あかね麗", False),
        ("ひらがな", False),
        ("Yua三上", False),
        ("123", False),
        ("", False),
        ("   ", False),
    ],
)
def test_needs_swap_first(q, expected):
    assert needs_swap_first(q) is expected


# ---------- swap_candidates ----------


def test_swap_candidates_drops_candidate_equal_to_tried():
    assert swap_candidates(["葵司", "葵つかさ"], ["葵司"]) == ["葵つかさ"]


def test_swap_candidates_drops_by_fold_not_raw_string():
    assert swap_candidates(["ＭＩＲＵ", "坂道みる"], ["miru"]) == ["坂道みる"]


def test_swap_candidates_dedups_by_fold_keeps_order():
    assert swap_candidates(["あかね麗", "あかね・麗", "二階堂麗"], []) == ["あかね麗", "二階堂麗"]


def test_swap_candidates_truncates_at_limit_default_three():
    names = ["甲", "乙", "丙", "丁", "戊"]
    assert swap_candidates(names, []) == ["甲", "乙", "丙"]
    assert swap_candidates(names, [], limit=2) == ["甲", "乙"]


def test_swap_candidates_skips_empty_and_non_str():
    assert swap_candidates(["", "・", None, 5, "甲"], ["乙", None]) == ["甲"]


# ---------- load_alias_groups ----------


@pytest.fixture
def db_dir(tmp_path, monkeypatch):
    """DB 路徑導到 tmp 下一個『目錄存在、檔案不存在』的位置。"""
    d = tmp_path / "dbdir"
    d.mkdir()
    path = d / "openaver.db"
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: path)
    return path


def _listing(path):
    return sorted(p.name for p in path.parent.iterdir())


def test_load_alias_groups_missing_file_returns_empty_and_creates_nothing(db_dir):
    before = _listing(db_dir)
    assert load_alias_groups() == []
    assert _listing(db_dir) == before == []


def test_load_alias_groups_returns_groups_from_tmp_db(db_dir):
    from core.database import AliasRepository, init_db

    init_db(db_dir)
    repo = AliasRepository(db_dir)
    repo.add("二階堂麗", ["あかね麗"])
    repo.add("坂道みる", ["miru", "Miru S"])
    assert load_alias_groups() == [("二階堂麗", ["あかね麗"]), ("坂道みる", ["miru", "Miru S"])]


def test_load_alias_groups_file_without_table_returns_empty(db_dir):
    sqlite3.connect(str(db_dir)).close()
    assert load_alias_groups() == []


def test_load_alias_groups_swallows_generic_exception_and_warns(db_dir, monkeypatch, caplog):
    from core.database import init_db

    init_db(db_dir)

    def boom(self):
        raise Exception("boom")

    monkeypatch.setattr("core.database.alias.AliasRepository.get_all", boom)
    with caplog.at_level("WARNING"):
        assert load_alias_groups() == []
    assert any("boom" in r.getMessage() for r in caplog.records)


# =====================================================================
# 175d-T2：provider 可選方法（JavBus resolve_all／JavDB alt_names）
# 輸入全是我們自己構造的 StarCard／Candidate／EntityRef；私有縫 _lookup 被 stub，不碰傳輸。
# =====================================================================
from core.scrapers.errors import SourceUnreachable  # noqa: E402
from core.scrapers.javbus import StarCard  # noqa: E402
from core.search_providers import javdb as _jdb  # noqa: E402
from core.search_providers.javbus import JavBusProvider, _pick_stars  # noqa: E402
from core.search_providers.javdb import Candidate, JavDBProvider, actor_alt_names  # noqa: E402
from core.search_providers.types import EntityRef, Kind  # noqa: E402

# ---------- _pick_stars ----------


def test_pick_stars_censored_before_uncensored_whatever_page_order():
    cards = [StarCard("uncensored/star/23f", "美咲愛", True), StarCard("star/36h", "美咲愛", False)]
    assert [c.id for c in _pick_stars(cards, "美咲愛")] == ["star/36h", "uncensored/star/23f"]


def test_pick_stars_keeps_only_first_of_each_class():
    cards = [
        StarCard("star/aaa", "美咲愛", False),
        StarCard("star/bbb", "美咲愛", False),
        StarCard("uncensored/star/ccc", "美咲愛", True),
        StarCard("uncensored/star/ddd", "美咲愛", True),
    ]
    assert [c.id for c in _pick_stars(cards, "美咲愛")] == ["star/aaa", "uncensored/star/ccc"]


def test_pick_stars_only_uncensored_gives_one():
    cards = [StarCard("uncensored/star/23f", "美咲愛", True)]
    assert [c.id for c in _pick_stars(cards, "美咲愛")] == ["uncensored/star/23f"]


def test_pick_stars_rejects_substring_and_accepts_width_case():
    cards = [StarCard("star/x", "美咲愛子", False), StarCard("star/m", "ＭＩＲＵ", False)]
    assert _pick_stars(cards, "美咲愛") == []
    assert [c.id for c in _pick_stars(cards, "miru")] == ["star/m"]


def test_pick_stars_empty():
    assert _pick_stars([], "美咲愛") == []


# ---------- actor_alt_names ----------


def _cand(name, zht, other):
    return Candidate("A", name, zht, other, 1, 0)


def test_actor_alt_names_name_first_split_drop_latin():
    assert actor_alt_names(_cand("三上悠亜", "三上悠亞", "鬼头桃菜, Yua Mikami")) == ["三上悠亜", "鬼头桃菜"]


def test_actor_alt_names_never_includes_name_zht():
    assert actor_alt_names(_cand("三上悠亜", "三上悠亞", "")) == ["三上悠亜"]


def test_actor_alt_names_folds_duplicates_keeps_order():
    assert actor_alt_names(_cand("坂道ｍ", "坂道ｍ", "AB、乙, 乙，坂道M / 丙")) == ["坂道ｍ", "乙", "丙"]


def test_actor_alt_names_no_other_name():
    assert actor_alt_names(_cand("葵司", "葵司", "")) == ["葵司"]


# ---------- JavBus resolve_all ----------

_REF_C = EntityRef(Kind.ACTOR, "star/36h", "美咲愛")
_REF_U = EntityRef(Kind.ACTOR, "uncensored/star/23f", "美咲愛")


def _stub_lookup(monkeypatch, results):
    calls = []

    def stub(self, kind, name):
        calls.append((kind, name))
        r = results[min(len(calls), len(results)) - 1]
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(JavBusProvider, "_lookup", stub)
    return calls


def test_javbus_resolve_all_returns_both_refs_censored_first(monkeypatch):
    _stub_lookup(monkeypatch, [(_REF_C, _REF_U)])
    assert JavBusProvider().resolve_all(Kind.ACTOR, "美咲愛") == [_REF_C, _REF_U]


def test_javbus_resolve_is_first_of_resolve_all(monkeypatch):
    _stub_lookup(monkeypatch, [(_REF_C, _REF_U)])
    assert JavBusProvider().resolve(Kind.ACTOR, "美咲愛") == _REF_C


def test_javbus_resolve_none_when_no_match(monkeypatch):
    _stub_lookup(monkeypatch, [()])
    assert JavBusProvider().resolve(Kind.ACTOR, "美咲愛") is None


@pytest.mark.parametrize("kind", [Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD])
def test_javbus_resolve_all_non_entity_kinds_zero_lookups(monkeypatch, kind):
    calls = _stub_lookup(monkeypatch, [(_REF_C,)])
    assert JavBusProvider().resolve_all(kind, "美咲愛") == []
    assert len(calls) == 0


def test_javbus_resolve_all_blank_name_zero_lookups(monkeypatch):
    calls = _stub_lookup(monkeypatch, [(_REF_C,)])
    assert JavBusProvider().resolve_all(Kind.ACTOR, "  ") == []
    assert len(calls) == 0


def test_javbus_series_gives_at_most_one(monkeypatch):
    ref = EntityRef(Kind.SERIES, "s1", "系列")
    _stub_lookup(monkeypatch, [(ref,)])
    assert JavBusProvider().resolve_all(Kind.SERIES, "系列") == [ref]


def test_javbus_confirmed_miss_is_cached(monkeypatch):
    calls = _stub_lookup(monkeypatch, [()])
    p = JavBusProvider()
    assert p.resolve_all(Kind.ACTOR, "查無此人") == []
    assert p.resolve_all(Kind.ACTOR, "查無此人") == []
    assert len(calls) == 1


def test_javbus_lookup_exception_is_not_cached(monkeypatch):
    calls = _stub_lookup(monkeypatch, [SourceUnreachable("down"), (_REF_C,)])
    p = JavBusProvider()
    with pytest.raises(SourceUnreachable):
        p.resolve_all(Kind.ACTOR, "美咲愛")
    assert p.resolve_all(Kind.ACTOR, "美咲愛") == [_REF_C]
    assert len(calls) == 2


# ---------- JavDB alt_names ----------


@pytest.fixture
def _javdb_clean():
    _jdb.clear_resolve_cache()
    yield
    _jdb.clear_resolve_cache()


def _stub_javdb(monkeypatch, cand):
    calls = []

    def stub(self, kind, q, qf):
        calls.append((kind, q))
        return cand

    monkeypatch.setattr(JavDBProvider, "_lookup", stub)
    return calls


_YUA = Candidate("Zx1", "三上悠亜", "三上悠亞", "鬼头桃菜, Yua Mikami", 99, 0)


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_come_from_resolve_candidate(monkeypatch):
    _stub_javdb(monkeypatch, _YUA)
    assert JavDBProvider().alt_names(Kind.ACTOR, "三上悠亞") == ["三上悠亜", "鬼头桃菜"]


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_no_candidate_is_empty(monkeypatch):
    calls = _stub_javdb(monkeypatch, None)
    p = JavDBProvider()
    assert p.alt_names(Kind.ACTOR, "查無此人") == []
    assert p.alt_names(Kind.ACTOR, "查無此人") == []
    assert len(calls) == 1


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_non_actor_empty_zero_lookups(monkeypatch):
    calls = _stub_javdb(monkeypatch, _YUA)
    assert JavDBProvider().alt_names(Kind.SERIES, "x") == []
    assert len(calls) == 0


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_blank_query_zero_lookups(monkeypatch):
    calls = _stub_javdb(monkeypatch, _YUA)
    assert JavDBProvider().alt_names(Kind.ACTOR, " ") == []
    assert len(calls) == 0


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_resolve_then_alt_names_share_one_lookup(monkeypatch):
    calls = _stub_javdb(monkeypatch, _YUA)
    p = JavDBProvider()
    assert p.resolve(Kind.ACTOR, "三上悠亞").id == "Zx1"
    assert p.alt_names(Kind.ACTOR, "三上悠亞") == ["三上悠亜", "鬼头桃菜"]
    assert len(calls) == 1


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_then_resolve_share_one_lookup(monkeypatch):
    calls = _stub_javdb(monkeypatch, _YUA)
    p = JavDBProvider()
    p.alt_names(Kind.ACTOR, "三上悠亞")
    assert p.resolve(Kind.ACTOR, "三上悠亞").id == "Zx1"
    assert len(calls) == 1


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_clear_resolve_cache_clears_names_too(monkeypatch):
    calls = _stub_javdb(monkeypatch, _YUA)
    p = JavDBProvider()
    p.alt_names(Kind.ACTOR, "三上悠亞")
    _jdb.clear_resolve_cache()
    p.alt_names(Kind.ACTOR, "三上悠亞")
    assert len(calls) == 2


@pytest.mark.usefixtures("_javdb_clean")
def test_javdb_alt_names_returns_fresh_list(monkeypatch):
    _stub_javdb(monkeypatch, _YUA)
    p = JavDBProvider()
    first = p.alt_names(Kind.ACTOR, "三上悠亞")
    first.append("污染")
    assert p.alt_names(Kind.ACTOR, "三上悠亞") == ["三上悠亜", "鬼头桃菜"]
