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
@pytest.mark.parametrize(
    "site,typed",
    [("javbus", "あかね麗"), ("javdb", "二階堂麗")],
    ids=["javbus-あかね麗", "javdb-二階堂麗"],
)
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


# ---------------------------------------------------------------- 結果物件


# ---------------------------------------------------------------- 多 ref 視窗與守衛


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


def test_latin_input_without_candidates_falls_back_to_original(chain):
    jb, jd = swap_chain(chain, {"Yua Mikami": [R1]}, [])
    assert numbers(search("Yua Mikami")) == ["J-1"]
    assert jd.alt_calls == [(Kind.ACTOR, "Yua Mikami")]
    assert jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]


def test_disabled_javdb_means_no_swap(chain):
    jb = Multi("javbus", {}, {}, kw_cards=[card("K-1")])
    jd = Swapper("javdb", {}, {}, alt=["三上悠亜"], caps=ACTOR_CAPS)
    chain([jb, jd], enabled=["javbus"])
    assert search("Yua Mikami") == [card("K-1")]
    assert jd.alt_calls == [] and jb.resolve_calls == [(Kind.ACTOR, "Yua Mikami")]


@pytest.mark.parametrize("q", ["あかね", ],
                         ids=["hira", ])
def test_all_kana_input_never_swaps(chain, q):
    jb, jd = swap_chain(chain, {}, ["別名"])
    jb.kw_cards = [card("K-1")]
    assert search(q) == [card("K-1")]
    assert jd.alt_calls == []
    assert jb.resolve_calls == [(Kind.ACTOR, q)]


# ---------------------------------------------------------------- 換名失敗政策（BE-TEST-33）
@pytest.mark.parametrize(
    "exc",
    [SourceBlocked("b")],
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


# ---------------------------------------------------------------- 別名表的讀取


