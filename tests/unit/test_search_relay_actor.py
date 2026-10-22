"""175d-T4：relay 梯子第一頁——名稱組、多代號歸併、懶換名（CD-175d-2／-3／-6／-7）。

全部用測試檔內的合成 provider（回我們自己的 EntityRef／WorkItem／卡 dict），不 import 真爬蟲、不連網（BE-TEST-43）。
別名表一律在測試內 patch 使用端 `core.search_providers.actor_names.load_alias_groups`（BE-TEST-01）；
「不准呼叫」量呼叫記錄（BE-TEST-46）；每個「換名 0 次」的案都有一個「該有的條件下會被呼叫」的對照（BE-TEST-23）。
stub 的 enrich 依「收到的 ref」算 belongs（ref.id == item.ref），所以 relay 傳錯 ref 會讓守衛案紅。
"""

import concurrent.futures as cf
import time

import pytest

from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import registry, relay
from core.search_providers.types import Enriched, EntityRef, Kind, Page, Window, WorkItem

W = Window(0, 20)
BASE_CAPS = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE})
ACTOR_CAPS = BASE_CAPS | {Kind.ACTOR}
R1, R2, R3, R4, R5 = (EntityRef(Kind.ACTOR, f"r{k}", f"n{k}") for k in range(1, 6))
ALIASES_2 = [("二階堂麗", ["あかね麗"])]
ALIASES_5 = [("甲", ["乙", "丙", "丁", "戊"])]


def card(n):
    return {"number": n, "title": f"t {n}"}


def wi(number, date, owner):
    return WorkItem(number, f"t {number}", "", date, None, "p", ref=owner)


def numbers(cards):
    return [c["number"] for c in cards]


class P:
    """relay 層 provider stub：resolve 查 table（name -> [ref…]，單代號型只回第一個）、list_entity 依 ref.id 回清單、
    enrich 的 belongs＝(收到的 ref.id == 該部的擁有者)。所有呼叫都記錄參數。"""

    fallback_streaming = False

    def __init__(self, pid, table=None, lists=None, *, caps=ACTOR_CAPS, kw_cards=(), resolve_raises=None,
                 discovery=False, series=None):
        self.id = pid
        self.capabilities = caps
        self.supports_discovery = discovery
        self.table = table or {}
        self.series = series or {}
        self.lists = lists or {}
        self.kw_cards = list(kw_cards)
        self.resolve_raises = resolve_raises or {}
        self.resolve_calls = []  # (kind, name)
        self.list_calls = []  # (ref.id, Window)
        self.enrich_calls = []  # (number, ref.id)
        self.run_calls = []  # (kind, target, Window)

    def _lookup(self, kind, name):
        if name in self.resolve_raises:
            raise self.resolve_raises[name]
        if kind is Kind.ACTOR:
            return list(self.table.get(name, []))
        if kind is Kind.SERIES:
            return list(self.series.get(name, []))
        return []

    def resolve(self, kind, name):
        self.resolve_calls.append((kind, name))
        found = self._lookup(kind, name)
        return found[0] if found else None

    def list_entity(self, ref, w):
        self.list_calls.append((ref.id, w))
        full = self.lists.get(ref.id, [])
        got = full[w.offset : w.offset + w.limit]
        return Page(list(got), w.offset + w.limit < len(full))

    def enrich(self, item, ref):
        self.enrich_calls.append((item.number, ref.id))
        return Enriched(card(item.number), ref.id == item.ref)

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append((kind, target, w))
        return list(self.kw_cards)


class Multi(P):
    """JavBus 型：有 resolve_all（同名多代號）。resolve 若被呼叫另記 single_calls（relay 該優先走 resolve_all）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.single_calls = []

    def resolve(self, kind, name):
        self.single_calls.append((kind, name))
        return super().resolve(kind, name)

    def resolve_all(self, kind, name):
        self.resolve_calls.append((kind, name))
        return self._lookup(kind, name)


class Swapper(P):
    """JavDB 型：單代號 resolve ＋ alt_names（可設候選或例外）。"""

    def __init__(self, *a, alt=(), alt_raises=None, **kw):
        super().__init__(*a, **kw)
        self.alt = list(alt)
        self.alt_raises = alt_raises
        self.alt_calls = []

    def alt_names(self, kind, q):
        self.alt_calls.append((kind, q))
        if self.alt_raises is not None:
            raise self.alt_raises
        return list(self.alt)


class SyncExecutor:
    def __init__(self, max_workers=None, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        fut = cf.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 — 與真 executor 相同
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)


@pytest.fixture
def chain(monkeypatch):
    """chain(providers, enabled=None)：把 stub 放進註冊表，順序＝傳入順序；enabled 預設全開。"""

    def setup(providers, enabled=None):
        for p in providers:
            monkeypatch.setitem(registry._REGISTRY, p.id, lambda p=p: p)
        ids = [p.id for p in providers]
        on = set(ids) if enabled is None else set(enabled)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(ids))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)

    return setup


@pytest.fixture
def aliases(monkeypatch):
    """aliases(groups)：把本機別名表換成 groups（晚於 conftest 的 autouse，會蓋過它）。回呼叫計數 list。"""

    def setup(groups):
        calls = []

        def load():
            calls.append(1)
            return groups

        monkeypatch.setattr("core.search_providers.actor_names.load_alias_groups", load)
        return calls

    return setup


@pytest.fixture
def merge_spy(monkeypatch):
    calls = []
    orig = relay.merge_windows

    def wrapper(*a, **kw):
        calls.append(a)
        return orig(*a, **kw)

    monkeypatch.setattr(relay, "merge_windows", wrapper)
    return calls


def search(q, w=W, **kw):
    return relay.search_by_intent("actress", q, w, **kw)


def ladder(provider, q, *, others=(), w=W, cb=None, status=None):
    """直接跑一次梯子（chain＝provider＋others），回 _LadderHit | None。"""
    names = relay._ActorNames(q, [provider, *others])
    return relay._entity_ladder(provider, names, w, cb, status)


# 兩個代號的清單（日期交錯、含同日、含跨 ref 同號）：期望序由手算
LISTS_2 = {
    "r1": [wi("N-1", "2026-03-10", "r1"), wi("N-2", "2026-02-01", "r1"), wi("N-3", "2025-12-31", "r1"),
           wi("N-4", "2025-12-30", "r1")],
    "r2": [wi("M-1", "2026-03-10", "r2"), wi("M-2", "2026-02-15", "r2"), wi("n-2", "2026-02-01", "r2"),
           wi("M-3", "2025-12-31", "r2")],
}
# 同日以 ref 序（r1 先）；n-2 與 N-2 同號（大小寫不同）被丟
EXPECT_2 = ["N-1", "M-1", "M-2", "N-2", "N-3", "M-3", "N-4"]


def two_ref_provider(kind):
    if kind == "javbus":
        return Multi("javbus", {"二階堂麗": [R1, R2], "あかね麗": [R2]}, LISTS_2)
    return P("javdb", {"二階堂麗": [R1], "あかね麗": [R2]}, LISTS_2)


# ---------------------------------------------------------------- A：多代號歸併（CD-7、I-X2、I-X4）
@pytest.mark.parametrize("typed", ["二階堂麗", "あかね麗"])
@pytest.mark.parametrize("site", ["javbus", "javdb"])
def test_two_refs_merge_into_one_newest_first_list(chain, aliases, merge_spy, site, typed):
    aliases(ALIASES_2)
    p = two_ref_provider(site)
    chain([p])
    seeds = []
    out = search(typed, result_callback=lambda slot, payload: seeds.append((slot, payload)))
    assert numbers(out) == EXPECT_2  # 新→舊、同日依 ref 序、無重複
    assert len(merge_spy) == 1
    assert [s for s in seeds if s[0] == -1] == [(-1, EXPECT_2)]  # seed 恰 1 次、順序＝歸併序
    if site == "javbus":
        assert p.single_calls == []  # 有 resolve_all 就不走 resolve


def test_ref_order_independent_of_which_alias_was_typed(aliases):
    aliases(ALIASES_5)
    results = {}
    for typed in ["甲", "乙", "丙", "丁", "戊"]:
        p = Multi("javbus", {"甲": [R1], "乙": [R2], "丙": [R3], "丁": [R4], "戊": [R5]},
                  {r.id: [wi(f"{r.id.upper()}-{k}", "2026-01-01", r.id) for k in range(2)] for r in (R1, R2, R3, R4)})
        hit = ladder(p, typed)
        results[typed] = (hit.refs, numbers(hit.cards), hit.positions)
    base = results["甲"]
    assert base[0] == [R1, R2, R3, R4]  # 第 5 個名字被截掉，名字組固定順序
    assert base[1] == ["R1-0", "R1-1", "R2-0", "R2-1", "R3-0", "R3-1", "R4-0", "R4-1"]  # 同日 ⇒ 依 ref 序
    assert base[2] == [-1, -1, -1, -1]
    for typed, got in results.items():
        assert got == base, typed  # refs、卡片序列、positions 三樣逐筆相等（只比卡片會被「同代號不同序」蓋掉）


def test_same_id_from_two_names_collapses_to_single_ref(aliases, merge_spy):
    aliases(ALIASES_2)
    p = P("dmm", {"二階堂麗": [R1], "あかね麗": [R1]}, {"r1": [wi("D-1", "2026-01-02", "r1"), wi("D-2", "2026-01-01", "r1")]})
    hit = ladder(p, "あかね麗")
    assert hit.refs == [R1]
    assert [c[0] for c in p.list_calls] == ["r1"]  # 同一份清單只取一遍
    assert merge_spy == []
    assert p.resolve_calls == [(Kind.ACTOR, "二階堂麗"), (Kind.ACTOR, "あかね麗")]
    assert numbers(hit.cards) == ["D-1", "D-2"]


def test_ref_cap_four_and_stop_asking_names_once_full(aliases):
    aliases([("甲", ["乙", "丙"])])
    p = Multi("javbus", {"甲": [R1, R2], "乙": [R3, R4, R5], "丙": [R5]},
              {r.id: [wi(f"{r.id}-x", "2026-01-01", r.id)] for r in (R1, R2, R3, R4, R5)})
    hit = ladder(p, "甲")
    assert hit.refs == [R1, R2, R3, R4]
    assert p.resolve_calls == [(Kind.ACTOR, "甲"), (Kind.ACTOR, "乙")]  # 湊滿 4 個後不再問「丙」


def test_resolve_prefers_resolve_all_when_available():
    p = Multi("javbus", {"x": [R1, R2]})
    assert relay._resolve_refs(p, Kind.ACTOR, ["x"]) == [R1, R2]
    assert p.single_calls == []


def test_resolve_raising_on_second_name_gives_empty_not_half_list(chain, aliases, caplog):
    aliases(ALIASES_2)
    jb = P("javbus", {"二階堂麗": [R1]}, LISTS_2, resolve_raises={"あかね麗": SourceUnreachable("u")})
    nxt = P("dmm", kw_cards=[card("D-9")], caps=BASE_CAPS)
    chain([jb, nxt])
    with caplog.at_level("WARNING"):
        out = search("二階堂麗")
    assert out == [card("D-9")]  # 別家照接力
    assert jb.list_calls == []  # 不回只含前一個名字的半份片單
    assert jb.run_calls == []  # 有 ref 卻整家失敗：該家不再問 KEYWORD
    assert len([r for r in caplog.records if "entity ladder failed" in r.getMessage()]) == 1


# ---------------------------------------------------------------- 單 ref 路徑與 175c 逐位元相同（I-X1，期望表手寫）
def test_single_ref_path_call_sequence_matches_175c(merge_spy):
    items = [wi("S-1", "2026-01-03", "r1"), wi("S-2", "2026-01-02", "r1"), wi("S-3", "2026-01-01", "r1")]
    p = P("javbus", {"someone": [R1]}, {"r1": items})
    hit = ladder(p, "someone")
    assert p.resolve_calls == [(Kind.ACTOR, "someone")]
    assert len(p.list_calls) == 1 and p.list_calls[0][0] == "r1" and p.list_calls[0][1] is W  # 傳入的視窗本身，不是塊大小 30
    assert p.enrich_calls == [("S-1", "r1"), ("S-2", "r1"), ("S-3", "r1")]
    assert p.run_calls == []
    assert merge_spy == []  # 單 ref 不呼叫 merge_windows
    assert numbers(hit.cards) == ["S-1", "S-2", "S-3"] and hit.refs == [R1] and hit.provider_id == "javbus"


def test_single_ref_falls_through_kinds_then_keyword_like_175c(chain):
    caps = ACTOR_CAPS | {Kind.SERIES, Kind.DIRECTOR, Kind.LABEL}
    miss = P("javdb", caps=caps, kw_cards=[card("K-1")])
    chain([miss])
    assert search("someone") == [card("K-1")]
    assert miss.resolve_calls == [(Kind.ACTOR, "someone"), (Kind.SERIES, "someone"), (Kind.DIRECTOR, "someone"),
                                  (Kind.LABEL, "someone")]
    assert miss.run_calls == [(Kind.KEYWORD, "someone", W)] and miss.list_calls == []


def test_series_hit_after_actor_miss_resolves_series_with_plain_query_only(chain, aliases):
    aliases([("someone", ["他名"])])
    caps = ACTOR_CAPS | {Kind.SERIES}
    p = P("javdb", series={"someone": [R1]}, lists={"r1": [wi("S-1", "2026-01-01", "r1")]}, caps=caps)
    chain([p])
    assert numbers(search("someone")) == ["S-1"]
    # ACTOR 用名稱組（別名展開）；SERIES 只問原字，不展開、不換名
    assert p.resolve_calls == [(Kind.ACTOR, "someone"), (Kind.ACTOR, "他名"), (Kind.SERIES, "someone")]
    assert p.run_calls == []


# ---------------------------------------------------------------- 結果物件
def test_ladder_hit_positions_single_ref_has_next_true_and_false():
    full = [wi(f"S-{k:02d}", "2026-01-01", "r1") for k in range(60)]
    p = P("javdb", {"x": [R1]}, {"r1": full})
    assert ladder(p, "x", w=Window(0, 20)).positions == [20]
    p = P("javdb", {"x": [R1]}, {"r1": full})
    assert ladder(p, "x", w=Window(20, 20)).positions == [40]
    p = P("javdb", {"x": [R1]}, {"r1": full})
    assert ladder(p, "x", w=Window(40, 20)).positions == [-1]  # 恰好最後一頁
    p = P("javdb", {"x": [R1]}, {"r1": full[:3]})
    assert ladder(p, "x", w=Window(0, 20)).positions == [-1]


def test_ladder_hit_positions_multi_ref_follow_merge_windows():
    lists = {
        "r1": [wi(f"A-{k}", f"2026-05-0{9 - k}", "r1") for k in range(5)],  # 全部比 r2 新
        "r2": [wi("B-0", "2026-01-02", "r2"), wi("B-1", "2026-01-01", "r2")],
    }
    p = Multi("javbus", {"x": [R1, R2]}, lists)
    hit = ladder(p, "x", w=Window(0, 3))
    assert numbers(hit.cards) == ["A-0", "A-1", "A-2"]
    assert hit.refs == [R1, R2]
    assert hit.positions == [3, 0]  # r1 消耗 3、r2 一部都沒消耗
    p = Multi("javbus", {"x": [R1, R2]}, lists)
    assert ladder(p, "x", w=Window(0, 20)).positions == [-1, -1]


def test_ladder_hit_without_cards_has_empty_refs_and_positions():
    p = P("javdb", {"x": [R1]}, {"r1": [wi("S-1", "2026-01-01", "someone-else")]})  # belongs 恆 False
    hit = ladder(p, "x")
    assert hit.cards == [] and hit.refs == [] and hit.positions == [] and hit.provider_id == "javdb"


def test_ladder_returns_none_when_no_ref_hits_anywhere():
    assert ladder(P("javdb"), "x") is None


# ---------------------------------------------------------------- 多 ref 視窗與守衛
def test_multi_ref_guard_uses_item_origin_not_first_ref():
    """前 3 部（守衛看的）全來自第 2 個 ref：enrich 收到的必須是各部的 origin 才過守衛。"""
    lists = {
        "r1": [wi(f"A-{k}", "2025-01-01", "r1") for k in range(3)],
        "r2": [wi(f"B-{k}", f"2026-06-0{k + 1}", "r2") for k in range(3)][::-1],
    }
    p = Multi("javbus", {"x": [R1, R2]}, lists)
    hit = ladder(p, "x")
    assert numbers(hit.cards) == ["B-2", "B-1", "B-0", "A-0", "A-1", "A-2"]
    assert [c for c in p.enrich_calls[:3]] == [("B-2", "r2"), ("B-1", "r2"), ("B-0", "r2")]
    assert {ref for _, ref in p.enrich_calls} == {"r1", "r2"}


def test_multi_ref_guard_failure_seeds_nothing_and_asks_next_provider_not_keyword(chain):
    lists = {"r1": [wi("A-1", "2026-01-01", "other")], "r2": [wi("B-1", "2026-01-02", "other")]}
    jb = Multi("javbus", {"x": [R1, R2]}, lists, kw_cards=[card("SHOULD-NOT")])
    nxt = P("dmm", kw_cards=[card("D-1")], caps=BASE_CAPS)
    chain([jb, nxt])
    seeds = []
    out = search("x", result_callback=lambda slot, payload: seeds.append(slot))
    assert out == [card("D-1")]
    assert seeds == []  # 守衛不過 ⇒ 沒送 seed
    assert jb.run_calls == []  # 有 ref 守衛不過：該家不問 KEYWORD
    assert nxt.run_calls != []  # 下一家被問


def test_multi_ref_guard_failure_sends_no_seed():
    lists = {"r1": [wi("A-1", "2026-01-01", "other")], "r2": [wi("B-1", "2026-01-02", "other")]}
    p = Multi("javbus", {"x": [R1, R2]}, lists)
    seeds = []
    hit = ladder(p, "x", cb=lambda slot, payload: seeds.append(slot))
    assert hit.cards == [] and seeds == []


def test_multi_ref_status_events_found_count_equals_cards():
    p = Multi("javbus", {"x": [R1, R2]}, LISTS_2)
    events = []
    hit = ladder(p, "x", status=lambda a, b: events.append((a, b)))
    assert events == [("javbus", "searching"), ("done", f"found:{len(hit.cards)}")]
    assert len(hit.cards) == 7


# ---------------------------------------------------------------- B：懶換名（CD-6）
def swap_chain(chain, jb_table, alt, **jb_kw):
    jb = Multi("javbus", jb_table, jb_kw.pop("lists", {"r1": [wi("J-1", "2026-01-01", "r1")]}), **jb_kw)
    jd = Swapper("javdb", {}, {}, alt=alt, caps=ACTOR_CAPS)
    chain([jb, jd])
    return jb, jd


def test_chinese_input_misses_then_swaps_once_and_first_provider_answers(chain):
    jb, jd = swap_chain(chain, {"三上悠亜": [R1]}, ["三上悠亜", "鬼头桃菜"])
    assert numbers(search("三上悠亞")) == ["J-1"]
    assert jb.resolve_calls == [(Kind.ACTOR, "三上悠亞"), (Kind.ACTOR, "三上悠亜")]  # 原字落空 → 換名後命中
    assert jd.alt_calls == [(Kind.ACTOR, "三上悠亞")]
    assert jd.resolve_calls == [] and jd.list_calls == [] and jd.run_calls == []  # 後面家 0 次


def test_latin_input_swaps_before_asking_original(chain):
    jb, jd = swap_chain(chain, {"三上悠亜": [R1], "Yua Mikami": [R3]}, ["三上悠亜", "鬼头桃菜"])
    assert numbers(search("Yua Mikami")) == ["J-1"]
    assert jb.resolve_calls == [(Kind.ACTOR, "三上悠亜")]  # 第一次 resolve 就是換名後的日文正名
    assert jd.alt_calls == [(Kind.ACTOR, "Yua Mikami")]


def test_first_winning_name_group_only_never_mixes_groups(chain):
    jb, jd = swap_chain(chain, {"三上悠亜": [R1], "鬼头桃菜": [R2], "Yua Mikami": [R3]}, ["三上悠亜", "鬼头桃菜"])
    hit = relay._entity_ladder(jb, relay._ActorNames("Yua Mikami", [jb, jd]), W, None)
    assert hit.refs == [R1]
    assert [n for _, n in jb.resolve_calls] == ["三上悠亜"]  # 勝出後不再問後面的組（I-X3）


def test_latin_input_without_candidates_falls_back_to_original(chain):
    jb, jd = swap_chain(chain, {"Yua Mikami": [R1]}, [])
    assert numbers(search("Yua Mikami")) == ["J-1"]
    assert jd.alt_calls == [(Kind.ACTOR, "Yua Mikami")]
    assert jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]


def test_japanese_input_never_calls_alt_names_when_asked_provider_hits(chain):
    jb, jd = swap_chain(chain, {"三上悠亜": [R1]}, ["別名"])
    assert numbers(search("三上悠亜")) == ["J-1"]
    assert jd.alt_calls == []
    assert jb.resolve_calls == [(Kind.ACTOR, "三上悠亜")]


def test_japanese_input_miss_asks_original_first_then_swaps(chain):
    """對照（BE-TEST-23）：同樣的日文輸入、原字落空 ⇒ alt_names 會被呼叫，且排在原字之後。"""
    jb, jd = swap_chain(chain, {"別名": [R1]}, ["別名"])
    assert numbers(search("三上悠亜")) == ["J-1"]
    assert jd.alt_calls == [(Kind.ACTOR, "三上悠亜")]
    assert jb.resolve_calls == [(Kind.ACTOR, "三上悠亜"), (Kind.ACTOR, "別名")]


def test_no_swapper_in_chain_means_no_swap_and_175c_sequence(chain):
    jb = Multi("javbus", {}, {}, kw_cards=[card("K-1")])
    chain([jb])
    assert search("Yua Mikami") == [card("K-1")]
    assert jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]
    assert jb.run_calls == [(Kind.KEYWORD, "Yua Mikami", W)]


def test_disabled_javdb_means_no_swap(chain):
    jb = Multi("javbus", {}, {}, kw_cards=[card("K-1")])
    jd = Swapper("javdb", {}, {}, alt=["三上悠亜"], caps=ACTOR_CAPS)
    chain([jb, jd], enabled=["javbus"])
    assert search("Yua Mikami") == [card("K-1")]
    assert jd.alt_calls == [] and jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]


def test_swapper_is_never_asked_to_swap_for_itself(chain):
    jd = Swapper("javdb", {}, {}, alt=["三上悠亜"], caps=ACTOR_CAPS, kw_cards=[card("K-1")])
    chain([jd])
    assert search("Yua Mikami") == [card("K-1")]
    assert jd.alt_calls == [] and jd.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]


def test_candidates_equal_to_input_means_no_extra_names(chain):
    """`葵司` 型：換名候選＝輸入 ⇒ 被濾空；alt_names 本來就被呼叫 1 次，resolve 次數＝原字組大小。"""
    jb, jd = swap_chain(chain, {}, ["葵司"])
    jb.kw_cards = [card("K-1")]
    assert search("葵司") == [card("K-1")]
    assert jd.alt_calls == [(Kind.ACTOR, "葵司")]
    assert jb.resolve_calls == [(Kind.ACTOR, "葵司")]


@pytest.mark.parametrize("q", ["あかね", "アカネ", "エリー", "ｱｶﾈ", "あか ね", "ｴﾘｰ･ﾛｰｽﾞ"],
                         ids=["hira", "kata", "choon", "halfwidth", "spaced", "halfwidth-middledot"])
def test_all_kana_input_never_swaps(chain, q):
    jb, jd = swap_chain(chain, {}, ["別名"])
    jb.kw_cards = [card("K-1")]
    assert search(q) == [card("K-1")]
    assert jd.alt_calls == []
    assert jb.resolve_calls == [(Kind.ACTOR, q)]


def test_kana_plus_kanji_input_is_not_all_kana_and_does_swap(chain):
    """對照：`あかね麗` 有漢字，不是全假名 ⇒ 原字落空後 alt_names 被呼叫 1 次。"""
    jb, jd = swap_chain(chain, {}, ["別名"])
    jb.kw_cards = [card("K-1")]
    search("あかね麗")
    assert jd.alt_calls == [(Kind.ACTOR, "あかね麗")]
    assert jb.resolve_calls == [(Kind.ACTOR, "あかね麗"), (Kind.ACTOR, "別名")]


@pytest.mark.parametrize("q,expect", [("あかね", True), ("カタカナー", True), ("ｱｶﾈ", True), ("ｴﾘｰ･ﾛｰｽﾞ", True), ("   ", False),
                                      ("", False), ("あかね麗", False), ("abc", False), ("あ1", False)])
def test_is_all_kana(q, expect):
    assert relay._is_all_kana(q) is expect


@pytest.mark.parametrize("discovery,asked", [(True, 0), (False, 1)])
def test_discovery_only_asks_no_names(chain, discovery, asked):
    jb = Multi("javbus", {}, {}, discovery=True, kw_cards=[card("K-1")])
    jd = Swapper("javdb", {}, {}, alt=["三上悠亜"], caps=ACTOR_CAPS, discovery=True, kw_cards=[card("K-2")])
    chain([jb, jd])
    search("Yua Mikami", discovery_only=discovery)
    assert len(jd.alt_calls) == asked  # 探索模式梯子整個跳過；對照：一般模式會換名
    assert (jb.resolve_calls == []) is (asked == 0)


# ---------------------------------------------------------------- 換名失敗政策（BE-TEST-33）
@pytest.mark.parametrize(
    "exc",
    [SourceBlocked("b"), SourceUnreachable("u"), TimeoutError(), RuntimeError("r")],
    ids=lambda e: type(e).__name__,
)
def test_alt_names_failure_falls_back_to_original_name(chain, caplog, exc):
    jb = Multi("javbus", {"Yua Mikami": [R1]}, {"r1": [wi("J-1", "2026-01-01", "r1")]})
    jd = Swapper("javdb", {}, {}, alt_raises=exc, caps=ACTOR_CAPS)
    chain([jb, jd])
    with caplog.at_level("WARNING"):
        out = search("Yua Mikami")
    assert len(jd.alt_calls) == 1  # (a)
    assert jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]  # (b)
    assert numbers(out) == ["J-1"]  # (c) 原字命中那家回答、例外沒有外洩
    msgs = [r.getMessage() for r in caplog.records]
    assert len([m for m in msgs if "actor name swap failed" in m]) == 1
    assert [m for m in msgs if "entity ladder failed" in m] == []  # 換名失敗不是梯子失敗，也不污染那條 log
    assert jd.resolve_calls == [] and jd.run_calls == []


def test_alt_names_base_exception_is_not_swallowed(chain):
    class Fatal(BaseException):
        pass

    jb = Multi("javbus", {}, {})
    jd = Swapper("javdb", {}, {}, alt_raises=Fatal(), caps=ACTOR_CAPS)
    chain([jb, jd])
    with pytest.raises(Fatal):
        search("Yua Mikami")


@pytest.mark.parametrize("raises", [None, SourceUnreachable("u")], ids=["ok", "failed"])
def test_alt_names_result_computed_once_per_search(chain, raises):
    """換名結果（含失敗記為 []）整次搜尋只算一次：排第一與第二的家都要換名時，後面的家不重打。"""
    jb = Multi("javbus", {}, {})
    dmm = P("dmm", {}, {})
    jd = Swapper("javdb", {}, {}, alt=["三上悠亜"], alt_raises=raises, caps=ACTOR_CAPS)
    chain([jb, dmm, jd])
    search("Yua Mikami")
    assert len(jd.alt_calls) == 1
    asked = [n for _, n in dmm.resolve_calls]
    assert asked == (["三上悠亜", "Yua Mikami"] if raises is None else ["Yua Mikami"])


# ---------------------------------------------------------------- 別名表的讀取
def test_aliases_loaded_lazily_and_once_per_search(chain, aliases):
    calls = aliases(ALIASES_2)
    jb = Multi("javbus", {}, {})
    dmm = P("dmm", {}, {})
    chain([jb, dmm])
    search("二階堂麗")
    assert len(calls) == 1  # 兩家都問了名字，只讀一次


def test_aliases_not_loaded_when_no_actor_ladder_runs(chain, aliases):
    calls = aliases(ALIASES_2)
    chain([P("dmm", caps=BASE_CAPS, kw_cards=[card("K-1")])])
    assert search("二階堂麗") == [card("K-1")]
    assert calls == []  # 沒有任何家宣告 ACTOR ⇒ 不讀 DB
