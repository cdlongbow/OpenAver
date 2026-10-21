"""175b-T2：JavDB parser（候選／列表列／詳情事實）。測試資料全為檔內合成 dict。"""

from __future__ import annotations

import pytest

from core.search_providers.javdb import (
    Candidate,
    DetailFacts,
    list_page,
    parse_candidates,
    parse_detail_facts,
    parse_list_rows,
)


class TestParseCandidates:
    def test_keeps_good_rows_and_drops_bad_ones(self):
        rows = [
            {"id": "Av2e", "name": "三上悠亜", "name_zht": "三上悠亜", "other_name": "鬼头桃菜", "videos_count": 318, "type": 0},
            {"name": "沒有id", "videos_count": 5},  # 缺 id
            {"id": "Zzz"},  # 缺 name
            {"id": "Q1", "name": ""},  # 空 name
            "oops",
            None,
            {"id": "S1", "name": "S1 NO.1 STYLE", "videos_count": 8355, "type": 1},
        ]
        got = parse_candidates(rows)
        assert [c.id for c in got] == ["Av2e", "S1"]
        assert got[0] == Candidate("Av2e", "三上悠亜", "三上悠亜", "鬼头桃菜", 318, 0)
        assert got[1].name_zht == "" and got[1].other_name == ""

    @pytest.mark.parametrize("bad", [None, "12", "x", 1.5, True, [], {}])
    def test_videos_count_non_int_becomes_zero(self, bad):
        got = parse_candidates([{"id": "a", "name": "n", "videos_count": bad}])
        assert got[0].videos_count == 0

    @pytest.mark.parametrize("t,expected", [(0, 0), (1, 1), (None, None), ("1", None), (True, None)])
    def test_type_int_or_none(self, t, expected):
        assert parse_candidates([{"id": "a", "name": "n", "type": t}])[0].type == expected

    @pytest.mark.parametrize("rows", [None, "x", {}, 3])
    def test_non_list_input_is_empty(self, rows):
        assert parse_candidates(rows) == []

    def test_other_name_not_split(self):
        got = parse_candidates([{"id": "a", "name": "n", "other_name": "甲, 乙"}])
        assert got[0].other_name == "甲, 乙"


class TestParseListRows:
    def test_keeps_good_rows_and_drops_bad_ones(self):
        rows = [
            {"id": "m1", "number": "SSIS-001", "title": "中文翻譯", "origin_title": "日文原題",
             "cover_url": "https://x/c.jpg", "thumb_url": "https://x/t.jpg", "release_date": "2021-01-01"},
            {"number": "NOID-001"},  # 缺 id
            {"id": "m2"},  # 缺 number
            {"id": "m3", "number": ""},
            ["not", "dict"],
            None,
            {"id": "m4", "number": "ABP-900", "title": "只有中文", "origin_title": "", "thumb_url": "https://x/t4.jpg"},
        ]
        got = parse_list_rows(rows)
        assert [w.number for w in got] == ["SSIS-001", "ABP-900"]
        first, second = got
        assert first.title == "日文原題"
        assert first.cover_url == "https://x/c.jpg"
        assert first.date == "2021-01-01"
        assert first.actors is None
        assert first.source == "javdb"
        assert first.ref == "m1"
        assert second.title == "只有中文"  # origin_title 空則退 title
        assert second.cover_url == "https://x/t4.jpg"

    def test_title_goes_through_strip_number_prefix(self):
        got = parse_list_rows([{"id": "m1", "number": "START-424", "origin_title": "START-424 市役所の窓口勤務の"}])
        assert got[0].title == "市役所の窓口勤務の"

    def test_integer_id_is_accepted(self):
        got = parse_list_rows([{"id": 7, "number": "A-1"}])
        assert got[0].ref == "7"

    @pytest.mark.parametrize("rows", [None, "x", {}])
    def test_non_list_input_is_empty(self, rows):
        assert parse_list_rows(rows) == []


def _rows(n):
    return [{"id": f"m{i}", "number": f"AAA-{i:03d}"} for i in range(n)]


class TestListPage:
    def test_full_page_below_cap_has_next(self):
        p = list_page(_rows(50), 98)
        assert p.has_next is True
        assert len(p.items) == 50
        assert p.total is None

    def test_list_page_has_next_stops_at_max_page(self):
        assert list_page(_rows(50), 98).has_next is True
        assert list_page(_rows(50), 99).has_next is False

    def test_short_page_has_no_next(self):
        assert list_page(_rows(49), 1).has_next is False

    def test_empty_page_has_no_next(self):
        p = list_page([], 1)
        assert p.has_next is False and p.items == []
        assert list_page(None, 1).has_next is False

    def test_has_next_counts_raw_rows_not_survivors(self):
        rows = _rows(40) + [{"junk": 1}] * 10  # 站方給滿 50 列，其中 10 列被丟棄
        p = list_page(rows, 1)
        assert len(p.items) == 40
        assert p.has_next is True


class TestParseDetailFacts:
    def test_full_movie(self):
        movie = {
            "maker_id": "7R", "series_id": "s1", "director_id": "d1", "publisher_id": "XG4",
            "actors": [{"id": "Av2e", "gender": 1}, {"id": "Bb", "gender": 0}, {"name": "noid"}, "x", {"id": ""}],
            "origin_title": "日文", "title": "中文",
        }
        f = parse_detail_facts(movie)
        assert f == DetailFacts("7R", "s1", "d1", "XG4", frozenset({"Av2e", "Bb"}), "日文", "中文")

    @pytest.mark.parametrize("empty", [None, "", "  ", [], {}])
    def test_empty_ids_are_none(self, empty):
        f = parse_detail_facts({"maker_id": empty, "series_id": empty, "director_id": empty, "publisher_id": empty})
        assert f.maker_id is f.series_id is f.director_id is f.publisher_id is None

    @pytest.mark.parametrize("movie", [None, "x", [], 3])
    def test_non_dict_is_all_empty(self, movie):
        f = parse_detail_facts(movie)
        assert f == DetailFacts(None, None, None, None, frozenset(), "", "")

    @pytest.mark.parametrize("actors", [None, "x", {}, 3])
    def test_actors_not_list(self, actors):
        assert parse_detail_facts({"actors": actors}).actor_ids == frozenset()
