"""175d-T5：relay 續頁（CD-175d-8 的 I-C1～I-C5）——token 往返、只問被釘的那一家、不重算第一頁、無答覆記憶。

全部用測試檔內的合成 provider（回我們自己的 EntityRef／WorkItem／卡 dict），不 import 真爬蟲、不連網（BE-TEST-43）。
「不准呼叫」量呼叫記錄（BE-TEST-46）：total_calls 一次數 resolve／resolve_all／alt_names／list_entity／run／run_maker／enrich
＋別名庫讀取；每個零呼叫案都配一個「同設定、去掉 token 或改 offset=0 ⇒ 一定有呼叫」的對照（BE-TEST-23）。
stub 的 enrich 依收到的 ref.id 算 belongs（由 token 重建的 ref 沒有 label）。
"""

import concurrent.futures as cf
import time

import pytest

from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import cursor, registry, relay
from core.search_providers.types import (
    Enriched,
    EntityRef,
    Kind,
    MakerSearchResult,
    Page,
    Window,
    WorkItem,
)

BASE_CAPS = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE})
ACTOR_CAPS = BASE_CAPS | {Kind.ACTOR}
R1, R2 = (EntityRef(Kind.ACTOR, f"r{k}", f"n{k}") for k in (1, 2))
ALIASES_2 = [("二階堂麗", ["あかね麗"])]


def card(n):
    return {"number": n, "title": f"t {n}"}


def wi(number, date, owner):
    return WorkItem(number, f"t {number}", "", date, None, "p", ref=owner)


def numbers(cards):
    return [c["number"] for c in cards]


class P:
    """relay 層 provider stub（形狀同 test_search_relay_actor.py 的 P）：list 以 w.offset 切片，enrich 的 belongs 比 ref.id。"""

    fallback_streaming = False

    def __init__(self, pid, table=None, lists=None, *, caps=ACTOR_CAPS, kw_cards=(), run_raises=None,
                 discovery=False):
        self.id = pid
        self.capabilities = caps
        self.supports_discovery = discovery
        self.table = table or {}
        self.lists = lists or {}
        self.kw_cards = list(kw_cards)
        self.run_raises = run_raises
        self.resolve_calls = []
        self.list_calls = []
        self.enrich_calls = []
        self.run_calls = []

    def resolve(self, kind, name):
        self.resolve_calls.append((kind, name))
        found = self.table.get(name, []) if kind is Kind.ACTOR else []
        return found[0] if found else None

    def list_entity(self, ref, w):
        self.list_calls.append((ref.id, w))
        full = self.lists.get(ref.id, [])
        return Page(list(full[w.offset : w.offset + w.limit]), w.offset + w.limit < len(full))

    def enrich(self, item, ref):
        self.enrich_calls.append((item.number, ref.id))
        return Enriched(card(item.number), ref.id == item.ref)

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append((kind, target, w))
        if self.run_raises is not None:
            raise self.run_raises
        return list(self.kw_cards)


class Multi(P):
    """JavBus 型：resolve_all 回同名多代號。"""

    def resolve_all(self, kind, name):
        self.resolve_calls.append((kind, name))
        return list(self.table.get(name, [])) if kind is Kind.ACTOR else []


class Swapper(P):
    """JavDB 型：alt_names 可設候選或例外。"""

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


class MakerP(P):
    """片商型：run_maker 依序吐 script 裡的 MakerSearchResult（或例外）。"""

    def __init__(self, pid, script=(), **kw):
        super().__init__(pid, caps=BASE_CAPS | {Kind.MAKER}, **kw)
        self.script = list(script)
        self.maker_calls = []  # offset

    def run_maker(self, maker_key, label, spellings, offset, **kw):
        self.maker_calls.append(offset)
        nxt = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


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
    """aliases(groups)：換掉本機別名表；回呼叫計數 list（別名庫讀取次數＝len）。預設（未呼叫）時為空表、不計數。"""

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


def tok(p, k, refs=()):
    return cursor.encode(cursor.Token(p, k, tuple(refs)))


def total_calls(*providers, alias_calls=()):
    """一次數完全部方法的呼叫次數＋別名庫讀取次數。"""
    attrs = ("resolve_calls", "list_calls", "enrich_calls", "run_calls", "alt_calls", "maker_calls", "single_calls")
    return sum(len(getattr(p, a, [])) for p in providers for a in attrs) + len(alias_calls)


def go(mode, q, offset, limit=20, **kw):
    return relay.search_by_intent(mode, q, Window(offset, limit), **kw)


def seven(owner="r1"):
    return [wi(f"S-{k}", f"2026-01-{20 - k:02d}", owner) for k in range(1, 8)]


# 兩個代號、日期交錯（同 test_search_relay_actor.py 的形狀；期望序手算）
LISTS_2 = {
    "r1": [wi("N-1", "2026-03-10", "r1"), wi("N-2", "2026-02-01", "r1"), wi("N-3", "2025-12-31", "r1"),
           wi("N-4", "2025-12-30", "r1")],
    "r2": [wi("M-1", "2026-03-10", "r2"), wi("M-2", "2026-02-15", "r2"), wi("n-2", "2026-02-01", "r2"),
           wi("M-3", "2025-12-31", "r2")],
}
EXPECT_2 = ["N-1", "M-1", "M-2", "N-2", "N-3", "M-3", "N-4"]


# ================================================================ I-C2：新搜尋不被釘
@pytest.mark.parametrize(
    "mode,token",
    [
        ("actress", tok("dmm", "keyword")),
    ],
)
def test_new_search_with_token_is_not_pinned(chain, aliases, mode, token):
    aliases([])
    a = P("javbus", kw_cards=[card("A-1")])
    b = P("dmm", kw_cards=[card("B-1")])
    chain([a, b])
    meta = {}
    out = go(mode, "x", 0, cursor=token, meta=meta)
    assert out == [card("A-1")]  # token 的 p=dmm 被忽略，鏈上第一家照常回答
    assert b.run_calls == [] and meta["answered_by"] == "javbus"


# ================================================================ I-C5：缺／壞 token ⇒ 空＋零呼叫
INVALID = {
    "missing": None,
}
MISMATCH = [  # Q1：k 與呼叫的 mode 不符 ⇒ 視為無效
    ("prefix", tok("dmm", "entity", [("actor", "r1", 0)])),
    ("actress", tok("dmm", "maker")),
]


def _bad_world(chain, aliases):
    alias_calls = aliases(ALIASES_2)
    a = Swapper("javbus", {"x": [R1]}, {"r1": seven()}, kw_cards=[card("A-1")], alt=["y"])
    b = Swapper("dmm", {"x": [R1]}, {"r1": seven()}, kw_cards=[card("B-1")], alt=["y"])
    chain([a, b])
    return a, b, alias_calls


@pytest.mark.parametrize("mode", ["actress"])
@pytest.mark.parametrize("name", sorted(INVALID))
def test_missing_or_invalid_token_gives_empty_and_zero_calls(chain, aliases, mode, name):
    a, b, alias_calls = _bad_world(chain, aliases)
    meta = {}
    assert go(mode, "x", 20, cursor=INVALID[name], meta=meta) == []
    assert total_calls(a, b, alias_calls=alias_calls) == 0 and meta == {}
    # 對照：同一個世界，offset=0（不看 token）一定有呼叫
    assert go(mode, "x", 0, cursor=INVALID[name]) and total_calls(a, b) > 0


@pytest.mark.parametrize("mode,token", MISMATCH)
def test_token_kind_not_matching_mode_gives_empty_and_zero_calls(chain, aliases, mode, token):
    a, b, alias_calls = _bad_world(chain, aliases)
    assert go(mode, "x", 20, cursor=token) == []
    assert total_calls(a, b, alias_calls=alias_calls) == 0
    assert go(mode, "x", 0, cursor=token) and total_calls(a, b) > 0  # 對照


def decode_ok(s):
    t = cursor.decode(s)
    assert t is not None
    return t


# ================================================================ I-C1：entity 續頁不重算
def test_entity_continuation_never_resolves_or_swaps(chain, aliases):
    """反方向案：第一頁 JavDB 換名失敗而由原字命中；續頁 JavDB 恢復——清單仍是 token 內那組 refs。"""
    alias_calls = aliases([])
    lists = {"r1": seven("r1"), "r2": [wi(f"Z-{k}", f"2026-02-{k:02d}", "r2") for k in range(1, 8)]}
    jb = Multi("javbus", {"rio": [R1]}, lists)
    jd = Swapper("javdb", alt=["二階堂麗"], alt_raises=SourceUnreachable("down"), caps=BASE_CAPS)
    chain([jb, jd])
    meta = {}
    first = go("actress", "rio", 0, 3, meta=meta)
    assert numbers(first) == ["S-1", "S-2", "S-3"]
    assert len(jd.alt_calls) == 1  # 第一頁確實問過換名（失敗）
    # 換名服務恢復、且新的解析會得到另一份清單
    jd.alt_raises = None
    jb.table["二階堂麗"] = [R2]
    before = (len(jb.resolve_calls), len(jd.alt_calls), len(alias_calls), len(jb.list_calls))
    second = go("actress", "rio", 20, 3, cursor=meta["cursor"], meta=meta)
    assert numbers(second) == ["S-4", "S-5", "S-6"]  # 仍是 r1 的下一段，不是 r2
    assert (len(jb.resolve_calls), len(jd.alt_calls), len(alias_calls)) == before[:3]  # resolve／alt_names／別名庫 0 次
    assert len(jb.list_calls) == before[3] + 1 and jb.list_calls[-1][0] == "r1"
    # 對照：同一世界的新搜尋（offset=0）會走新的解析而換清單，證明上面的「0 次」不是 stub 沒接上
    assert go("actress", "rio", 0, 3, meta={}) and len(jd.alt_calls) == 2


def test_entity_single_ref_walks_pages_through_tokens(chain, aliases):
    aliases([])
    p = P("javbus", {"x": [R1]}, {"r1": seven()})
    chain([p])
    got, meta, pages, offset = [], {}, [], 0
    out = go("actress", "x", 0, 3, meta=meta)
    while out:
        pages.append(numbers(out))
        got += numbers(out)
        offset += 3
        out = go("actress", "x", offset, 3, cursor=meta["cursor"], meta=meta)
    assert pages == [["S-1", "S-2", "S-3"], ["S-4", "S-5", "S-6"], ["S-7"]]
    assert got == [f"S-{k}" for k in range(1, 8)]
    assert len(p.resolve_calls) == 1  # 只有第一頁 resolve 過


def test_entity_multi_ref_walk_equals_one_shot_sequence(chain, aliases, merge_spy):
    aliases(ALIASES_2)
    p = Multi("javbus", {"二階堂麗": [R1, R2]}, LISTS_2)
    chain([p])
    meta, pages = {}, []
    out = go("actress", "二階堂麗", 0, 3, meta=meta)
    resolved_on_first_page = len(p.resolve_calls)
    assert resolved_on_first_page == 2  # 名稱組兩個名字各問一次
    offset = 0
    while out:
        pages.append(numbers(out))
        offset += 3
        out = go("actress", "二階堂麗", offset, 3, cursor=meta["cursor"], meta=meta)
    assert pages == [EXPECT_2[0:3], EXPECT_2[3:6], EXPECT_2[6:]]  # 3＋3＋1，手算期望
    assert len(merge_spy) == 3  # 每頁都經 relay.merge_windows
    assert len(p.resolve_calls) == resolved_on_first_page  # 續頁沒有再 resolve
    assert decode_ok(meta["cursor"]).refs == (("actor", "r1", -1), ("actor", "r2", -1))
    before = total_calls(p)
    assert go("actress", "二階堂麗", offset + 3, 3, cursor=meta["cursor"]) == []
    assert total_calls(p) == before  # 全部耗盡 ⇒ 零呼叫


# ================================================================ keyword 續頁


# ================================================================ I-C1：釘住
@pytest.mark.parametrize("exc", [SourceBlocked("cf"), ])
def test_pinned_provider_failure_means_no_more_never_asks_the_other(chain, aliases, exc):
    aliases([])
    a = P("javbus", kw_cards=[card("A-1")])
    b = P("dmm", kw_cards=[card("B-1")], run_raises=exc)
    chain([a, b])
    meta = {}
    assert go("prefix", "x", 20, cursor=tok("dmm", "keyword"), meta=meta) == []
    assert total_calls(a) == 0 and len(b.run_calls) == 1 and meta == {}
    assert go("prefix", "x", 0)  # 對照：新搜尋 A 照常回答


def test_pinned_provider_disabled_or_absent_means_no_more_and_zero_calls(chain, aliases):
    aliases([])
    a = P("javbus", kw_cards=[card("A-1")])
    b = P("dmm", kw_cards=[card("B-1")])
    chain([a, b], enabled=["javbus"])  # dmm 在註冊表裡（token 合法）但被設定頁關掉
    t = tok("dmm", "keyword")
    assert cursor.decode(t) is not None
    assert go("prefix", "x", 20, cursor=t) == []
    assert total_calls(a, b) == 0
    chain([a, b])  # 對照：開回來就問得到
    assert go("prefix", "x", 20, cursor=t) == [card("B-1")]


# ================================================================ I-C3：無答覆記憶


# ================================================================ I-C4：meta


# ================================================================ 片商
MK = dict(titles=[], today="2026-10-21")


def mk(offset, **kw):
    return relay.search_maker("mk", "片商", ["片商"], offset, **MK, **kw)


def R(*nums):
    return MakerSearchResult([card(n) for n in nums], True, None)


def E(code):
    return MakerSearchResult([], False, code)


@pytest.mark.parametrize("name", sorted(INVALID))
def test_maker_missing_or_invalid_token_is_unreachable_with_zero_calls(chain, name):
    a = MakerP("javbus", [R("A-1")])
    b = MakerP("dmm", [R("B-1")])
    chain([a, b])
    meta = {}
    assert mk(30, cursor=INVALID[name], meta=meta) == E("maker_unreachable")
    assert total_calls(a, b) == 0 and meta == {}
    assert mk(0, cursor=INVALID[name]).results and total_calls(a, b) > 0  # 對照


@pytest.mark.parametrize("exc", [SourceBlocked("cf"), ])
def test_maker_pinned_provider_exception_is_terminal(chain, exc):
    a = MakerP("javbus", [R("A-1")])
    b = MakerP("dmm", [exc])
    chain([a, b])
    assert mk(30, cursor=tok("dmm", "maker")) == E("maker_unreachable")
    assert total_calls(a) == 0 and b.maker_calls == [30]


def test_maker_terminal_codes_still_hold_on_pinned_page(chain):
    for code in ("maker_empty", "maker_unreachable"):
        b = MakerP("dmm", [E(code)])
        chain([MakerP("javbus", [R("A-1")]), b])
        assert mk(30, cursor=tok("dmm", "maker")) == E(code)


