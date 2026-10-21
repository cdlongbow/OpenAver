"""
test_javdb_resolve.py - JavDB「名字→實體」resolve（175b-T3）

候選全為檔內合成列；patch javdb_api.api_search_typed（模組屬性）與 javdb.py 內兩個對照表載入函式。
不連外、不存站方 fixture。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import javdb as jp
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import EntityRef, Kind


class _Scraper:
    def _proxy_kwargs(self):
        return {}


def _row(id_, name, *, type_=0, vc=100, zht="", other=""):
    return {"id": id_, "name": name, "name_zht": zht, "other_name": other, "videos_count": vc, "type": type_}


@pytest.fixture(autouse=True)
def _clean():
    clear_resolve_cache()
    with patch.object(jp, "_sleep", lambda s: None):
        yield
    clear_resolve_cache()


class _Site:
    """依 (type, q) 回合成列並記錄呼叫。"""

    def __init__(self, table=None, default=None, exc=None):
        self.table = table or {}
        self.default = default if default is not None else []
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    def __call__(self, t, q, proxies=None):
        self.calls.append((t, q))
        if self.exc is not None:
            raise self.exc
        return self.table.get((t, q), self.default)


def _resolve(kind, q, site, name_map=None, search_aliases=None):
    with patch.object(javdb_api, "api_search_typed", site), \
         patch.object(jp, "load_name_mapping", lambda: name_map or {}), \
         patch.object(jp, "load_search_aliases", lambda: search_aliases or {}):
        return JavDBProvider(scraper=_Scraper()).resolve(kind, q)


# ------------------------------------------------------------------ ACTOR
def test_actor_exact_name_accepted_and_records_name():
    site = _Site({("actor", "三上悠亜"): [_row("X", "別人"), _row("Av2e", "三上悠亜", vc=318)]})
    ref = _resolve(Kind.ACTOR, "三上悠亜", site)
    assert ref == EntityRef(Kind.ACTOR, "Av2e", "三上悠亜")


def test_actor_type1_candidate_rejected():
    # 使用者打「人妻」→ 若 type==1 的同名雜項條目被當成女優，清單變成那個條目的作品，而不是標題含「人妻」的片
    site = _Site({("actor", "人妻"): [_row("M1", "人妻", type_=1, vc=42)]})
    assert _resolve(Kind.ACTOR, "人妻", site) is None


def test_actor_single_candidate_romaji_accepted():
    site = _Site({("actor", "Yua Mikami"): [_row("Av2e", "三上悠亜", zht="三上悠亜", other="鬼头桃菜")]})
    assert _resolve(Kind.ACTOR, "Yua Mikami", site).id == "Av2e"


def test_actor_single_candidate_substring_rejected():
    # 使用者打「三上」想搜標題關鍵字 → 站方恰回 1 位名字含「三上」的女優，若被認成她，關鍵字結果被吃掉
    site = _Site({("actor", "三上"): [_row("Av2e", "三上悠亜")]})
    assert _resolve(Kind.ACTOR, "三上", site) is None


def test_actor_multiple_candidates_without_exact_rejected():
    # 使用者打泛詞「巨乳」→ 站方回多位不相干女優，若取第一位就顯示某位女優的作品
    site = _Site({("actor", "巨乳"): [_row("A", "甲子"), _row("B", "乙子"), _row("C", "巨乳C子")]})
    assert _resolve(Kind.ACTOR, "巨乳", site) is None


def test_actor_alias_in_other_name_list_accepted():
    # 使用者打改名前的舊名「橋本ありな」→ 舊名在別名清單裡，不切開就認不出 → 看到標題含該字的片而不是她的作品
    site = _Site({("actor", "橋本ありな"): [
        _row("8pk9", "藤森里穂", vc=1041, other="山本しゅり,橋本優希"),
        _row("RJM8", "新有菜", vc=324, zht="新有菜", other="橋本ありな,上乃木まな,橋本有菜"),
        _row("QVy", "夏目りんか、橋本ななみ", type_=1, vc=0),
    ]})
    assert _resolve(Kind.ACTOR, "橋本ありな", site).id == "RJM8"


@pytest.mark.parametrize("sep", [",", "、", "，", "/", "／"])
def test_actor_other_name_all_separators(sep):
    site = _Site({("actor", "旧名"): [_row("Z", "新名", other=f"甲{sep}旧名{sep}乙"), _row("Y", "他人")]})
    assert _resolve(Kind.ACTOR, "旧名", site).id == "Z"


def test_actor_other_name_partial_string_not_accepted():
    site = _Site({("actor", "橋本ありな"): [_row("A", "甲", other="橋本ありな子"), _row("B", "乙")]})
    assert _resolve(Kind.ACTOR, "橋本ありな", site) is None


def test_actor_misc_type1_not_counted_in_exactly_one():
    # 使用者打「明日花キララ」→ 站方除真女優外夾一筆雜項，若雜項算進筆數就認不出她
    site = _Site({("actor", "明日花キララ"): [
        _row("wm9B", "明日花綺羅", zht="明日花綺羅", vc=402),
        _row("B8aRA", "明日花キララ", type_=1, vc=1),
    ]})
    assert _resolve(Kind.ACTOR, "明日花キララ", site).id == "wm9B"


def test_actor_multiple_exact_picks_largest():
    site = _Site({("actor", "あい"): [_row("S", "あい", vc=3), _row("L", "あい", vc=90), _row("M", "あい", vc=90)]})
    assert _resolve(Kind.ACTOR, "あい", site).id == "L"


# ------------------------------------------------------------------ 泛詞 × 三種
@pytest.mark.parametrize("word", ["温泉", "人妻", "巨乳", "素人"])
@pytest.mark.parametrize("kind,t", [(Kind.ACTOR, "actor"), (Kind.SERIES, "series"), (Kind.DIRECTOR, "director")])
def test_generic_words_never_resolve(word, kind, t):
    rows = [_row("a", f"{word}の女王", vc=900), _row("b", f"超{word}", vc=800), _row("c", f"{word}x", vc=3)]
    assert _resolve(kind, word, _Site({(t, word): rows})) is None


# ------------------------------------------------------------------ SERIES / DIRECTOR
@pytest.mark.parametrize("kind,t", [(Kind.SERIES, "series"), (Kind.DIRECTOR, "director")])
def test_series_director_exact_accepted(kind, t):
    site = _Site({(t, "ABC"): [_row("n", "ABC2", vc=50), _row("ok", "abc", vc=20)]})
    assert _resolve(kind, "ABC", site) == EntityRef(kind, "ok", "abc")


@pytest.mark.parametrize("kind,t", [(Kind.SERIES, "series"), (Kind.DIRECTOR, "director")])
def test_series_director_below_5_videos_rejected(kind, t):
    # 使用者打「素人」→ 站上有個只有 2 部的系列叫「素人」，若被當系列，只看到那 2 部而不是關鍵字結果
    site = _Site({(t, "素人"): [_row("s", "素人", vc=2)]})
    assert _resolve(kind, "素人", site) is None


def test_series_substring_rejected():
    site = _Site({("series", "ABC"): [_row("s", "ABC特集", vc=300)]})
    assert _resolve(Kind.SERIES, "ABC", site) is None


# ------------------------------------------------------------------ CODE
def test_code_exact_name_accepted():
    site = _Site({("code", "SSIS"): [_row("x", "SSIS-", vc=9), _row("y", "ssis", vc=500)]})
    assert _resolve(Kind.CODE, "SSIS", site) == EntityRef(Kind.CODE, "ssis", "ssis")


def test_code_no_equal_name_none():
    assert _resolve(Kind.CODE, "SSI", _Site({("code", "SSI"): [_row("x", "SSIS")]})) is None


# ------------------------------------------------------------------ MAKER
def test_maker_empty_shell_rejected():
    # 使用者搜片商 → 若選到 0 部的空殼，片商清單是空的，使用者以為 JavDB 沒有這家
    site = _Site({("maker", "カリビアンコム"): [_row("e", "カリビアンコム", vc=0)]})
    assert _resolve(Kind.MAKER, "カリビアンコム", site) is None


def test_maker_same_name_picks_largest():
    # 使用者搜片商 → 5 部的同名空殼排在 6529 部正牌前面時，清單只有 5 部，畫面看似正常但漏掉絕大多數作品
    site = _Site({("maker", "Foo"): [_row("small", "Foo", vc=5), _row("big", "Foo", vc=6529)]})
    assert _resolve(Kind.MAKER, "Foo", site).id == "big"


def test_maker_s1_resolved_by_candidate_set_in_one_request():
    nm = {"S1": "S1 NO.1 STYLE"}
    site = _Site({("maker", "S1"): [_row("z", "S1 NO.1 STYLE", vc=2000), _row("w", "S1X", vc=10)]})
    ref = _resolve(Kind.MAKER, "S1", site, name_map=nm)
    assert ref.id == "z" and len(site.calls) == 1


def test_maker_tries_names_in_order_and_stops_at_first_hit():
    nm = {"A社": "Alpha", "Aちゃん": "Alpha"}
    site = _Site({("maker", "Alpha"): [_row("hit", "Alpha", vc=7)]})
    ref = _resolve(Kind.MAKER, "A社", site, name_map=nm)
    assert ref.id == "hit"
    assert site.calls == [("maker", "A社"), ("maker", "Alpha")]


def test_maker_search_aliases_join_candidate_set():
    site = _Site({("maker", "SOD"): [_row("q", "ソフト・オン・デマンド", vc=50)]})
    ref = _resolve(Kind.MAKER, "SOD", site,
                   name_map={"SOD": "ソフト・オン・デマンド"}, search_aliases={"SODクリエイト": "ソフト・オン・デマンド"})
    assert ref.id == "q"


def test_maker_all_miss_none_and_at_most_4_requests():
    nm = {f"a{i}": "Canon" for i in range(8)}
    site = _Site(default=[_row("n", "Unrelated", vc=9)])
    assert _resolve(Kind.MAKER, "Canon", site, name_map=nm) is None
    assert 1 <= len(site.calls) <= 4


def test_maker_requests_are_spaced():
    # 使用者搜一個要試好幾個別名的片商 → 若連打不間隔，壓力高於今天，IP 更容易被擋
    nm = {"a1": "Canon", "a2": "Canon"}
    sleeps: list[float] = []
    site = _Site(default=[])
    with patch.object(jp, "_sleep", sleeps.append):
        _resolve(Kind.MAKER, "Canon", site, name_map=nm)
    assert len(site.calls) == 3
    # 175b-T4a：節流併入單一後置點（每次請求完成後 sleep），3 次請求 ⇒ 3 次
    assert len(sleeps) == 3 and all(s >= 0.3 for s in sleeps)


# ------------------------------------------------------------------ 快取
_CACHE_CASES = [
    (Kind.ACTOR, "actor", "名前", [_row("A1", "名前")]),
    (Kind.ACTOR, "actor", "巨乳", [_row("a", "巨乳A"), _row("b", "巨乳B")]),  # 被拒＝確定查無
    (Kind.SERIES, "series", "シリーズ", [_row("S", "シリーズ", vc=50)]),
    (Kind.SERIES, "series", "素人", [_row("S", "素人", vc=1)]),
    (Kind.DIRECTOR, "director", "監督", [_row("D", "監督", vc=50)]),
    (Kind.CODE, "code", "SSIS", [_row("c", "SSIS")]),
    (Kind.MAKER, "maker", "Foo", [_row("M", "Foo", vc=5)]),
    (Kind.MAKER, "maker", "Nope", []),
]


@pytest.mark.parametrize("kind,t,q,rows", _CACHE_CASES)
def test_second_resolve_sends_no_request(kind, t, q, rows):
    # 使用者每次打字／載入更多，同一個字都重打 type= 請求 → 請求量暴增、IP 更容易被擋
    site = _Site({(t, q): rows})
    first = _resolve(kind, q, site)
    n1 = len(site.calls)
    assert n1 > 0
    second = _resolve(kind, q, site)
    assert len(site.calls) == n1
    assert second == first


def test_cache_hit_does_not_build_scraper():
    site = _Site({("actor", "名前"): [_row("A1", "名前")]})
    _resolve(Kind.ACTOR, "名前", site)
    p = JavDBProvider()  # 無注入 scraper：命中快取不得建 scraper
    with patch.object(javdb_api, "api_search_typed", site):
        assert p.resolve(Kind.ACTOR, "名前").id == "A1"
    assert p._scraper_obj is None


def test_cache_key_is_normalized():
    site = _Site({("maker", "Foo"): [_row("M", "Foo", vc=5)]})
    _resolve(Kind.MAKER, "Foo", site)
    n = len(site.calls)
    _resolve(Kind.MAKER, " ＦＯＯ ", site)
    assert len(site.calls) == n


@pytest.mark.parametrize("exc", [SourceBlocked("b"), SourceUnreachable("u"), ConnectionError("c")])
@pytest.mark.parametrize("kind", [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE])
def test_exception_not_cached_and_propagates(kind, exc):
    bad = _Site(exc=exc)
    with pytest.raises(type(exc)):
        _resolve(kind, "名前", bad)
    n_bad = len(bad.calls)
    assert n_bad > 0
    good = _Site(default=[])
    _resolve(kind, "名前", good)
    assert len(good.calls) > 0  # 例外沒有被記成「確定查無」


# ------------------------------------------------------------------ provider 面
def test_capabilities_exact():
    assert JavDBProvider.capabilities == frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD})


@pytest.mark.parametrize("kind", [Kind.LABEL, Kind.KEYWORD, Kind.PARTIAL])
def test_unsupported_kind_none_no_request(kind):
    site = _Site()
    assert _resolve(kind, "x", site) is None
    assert site.calls == []


def test_empty_after_fold_none_no_request():
    site = _Site()
    assert _resolve(Kind.ACTOR, " ・-_ ", site) is None
    assert site.calls == []
