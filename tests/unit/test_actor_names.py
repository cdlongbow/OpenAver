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
