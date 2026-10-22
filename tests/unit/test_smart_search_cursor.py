"""175d-T5：smart_search 層的續頁（CD-175d-9）＋ core.scraper shim 對 cursor／meta 的轉傳。

patch 使用端 core.scraper.*（BE-TEST-01）；search_prefix／search_actress／search_jav321_keyword 是我們自己的函式，
替身只記錄呼叫、不模擬任何站方回應（BE-TEST-43）。「不准呼叫」量呼叫記錄，每個零呼叫案配一個 offset=0 的對照（BE-TEST-23／46）。
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import core.scraper as sc
from core.search_providers import cursor, registry
from core.search_providers.types import Kind, MakerSearchResult, Window

TOKEN = "TOKEN-FROM-CLIENT"


def _card(n):
    return {"number": n, "title": f"t {n}"}


class Rec:
    """三個退路替身：依 script 回卡片，並記錄每次呼叫的 (args, kwargs)。"""

    def __init__(self, prefix=(), actress=(), jav321=()):
        self.cards = {"prefix": list(prefix), "actress": list(actress), "jav321": list(jav321)}
        self.calls = {"prefix": [], "actress": [], "jav321": []}
        self.actress_meta_write = None

    def prefix(self, query, limit=20, offset=0, status_callback=None, result_callback=None, discovery_only=False, *,
               cursor=None, meta=None):
        self.calls["prefix"].append(SimpleNamespace(query=query, limit=limit, offset=offset, cursor=cursor, meta=meta))
        return [dict(c) for c in self.cards["prefix"]]

    def actress(self, name, limit=20, offset=0, status_callback=None, result_callback=None, discovery_only=False, *,
                cursor=None, meta=None):
        self.calls["actress"].append(SimpleNamespace(query=name, limit=limit, offset=offset, cursor=cursor, meta=meta))
        if meta is not None and self.actress_meta_write and self.cards["actress"]:
            meta.update(self.actress_meta_write)
        return [dict(c) for c in self.cards["actress"]]

    def jav321(self, keyword, limit=20, status_callback=None):
        self.calls["jav321"].append(SimpleNamespace(query=keyword, limit=limit))
        return [dict(c) for c in self.cards["jav321"]]


@pytest.fixture
def env(monkeypatch):
    """prefix 分支能走到：javbus 在鏈上（能做前綴）、jav321 開著（否則 jav321 退路本來就走不到，mutation 沒牙）。"""
    monkeypatch.setattr(sc, "get_all_source_ids_ordered", lambda: ["javbus", "jav321"])
    monkeypatch.setattr(sc, "is_source_enabled", lambda sid: True)
    monkeypatch.setattr(sc, "is_uncensored_route", lambda target: False)

    def install(rec):
        monkeypatch.setattr(sc, "search_prefix", rec.prefix)
        monkeypatch.setattr(sc, "search_actress", rec.actress)
        monkeypatch.setattr(sc, "search_jav321_keyword", rec.jav321)
        return rec

    return install


# ================================================================ CD-9：offset>0 不退路
def test_load_more_on_exhausted_prefix_does_not_fall_back(env):
    rec = env(Rec(prefix=[], actress=[_card("A-1")], jav321=[_card("J-1")]))
    assert sc.smart_search("MIDV", limit=20, offset=20, cursor=TOKEN) == []
    assert len(rec.calls["prefix"]) == 1
    assert rec.calls["actress"] == [] and rec.calls["jav321"] == []


def test_first_page_exhausted_prefix_still_falls_back_in_order(env):
    """對照：offset=0 時退路照舊（先女優、再 jav321）。"""
    rec = env(Rec(prefix=[], actress=[], jav321=[_card("J-1")]))
    out = sc.smart_search("MIDV", limit=20, offset=0)
    assert [c["number"] for c in out] == ["J-1"] and out[0]["_mode"] == "keyword"
    assert len(rec.calls["actress"]) == 1 and len(rec.calls["jav321"]) == 1


def test_first_page_fallback_to_actress_marks_actress_mode(env):
    rec = env(Rec(prefix=[], actress=[_card("A-1")], jav321=[_card("J-1")]))
    out = sc.smart_search("MIDV", offset=0)
    assert out[0]["number"] == "A-1" and out[0]["_mode"] == "actress"
    assert rec.calls["jav321"] == []


def test_load_more_with_prefix_cards_returns_them_without_touching_fallbacks(env):
    rec = env(Rec(prefix=[_card("P-21")], actress=[_card("A-1")], jav321=[_card("J-1")]))
    out = sc.smart_search("MIDV", limit=20, offset=20, cursor=TOKEN)
    assert [c["number"] for c in out] == ["P-21"] and out[0]["_mode"] == "prefix"
    assert rec.calls["actress"] == [] and rec.calls["jav321"] == []


# ================================================================ cursor／meta 轉傳
def test_prefix_branch_forwards_cursor_and_meta(env):
    rec = env(Rec(prefix=[_card("P-1")]))
    meta = {}
    sc.smart_search("MIDV", limit=20, offset=20, cursor=TOKEN, meta=meta)
    got = rec.calls["prefix"][0]
    assert got.cursor == TOKEN and got.meta is meta and got.offset == 20


def test_fallback_actress_gets_the_same_meta_and_its_write_is_final(env):
    """prefix 查無 → 退到 actress：meta 以最後一次回答者（actress）為最終值。"""
    rec = env(Rec(prefix=[], actress=[_card("A-1")]))
    rec.actress_meta_write = {"cursor": "ACTRESS-TOKEN", "answered_by": "dmm"}
    meta = {"has_more": True}
    out = sc.smart_search("MIDV", offset=0, meta=meta)
    assert out and rec.calls["actress"][0].meta is meta
    assert meta["cursor"] == "ACTRESS-TOKEN" and meta["answered_by"] == "dmm"


def test_actress_branch_forwards_cursor_and_meta(env):
    rec = env(Rec(actress=[_card("A-21")]))
    meta = {}
    out = sc.smart_search("三上悠亜", limit=20, offset=20, cursor=TOKEN, meta=meta)
    got = rec.calls["actress"][0]
    assert got.cursor == TOKEN and got.meta is meta and got.offset == 20
    assert out[0]["_mode"] == "actress"


def test_partial_branch_passes_neither_meta_nor_cursor(env, monkeypatch):
    seen = {}

    def fake_partial(partial, status_callback=None, result_callback=None, discovery_only=False, **kw):
        seen.update(kw)
        return [_card("PART-1")]

    monkeypatch.setattr(sc, "search_partial", fake_partial)
    out = sc.smart_search("ABC-12", offset=0, cursor=TOKEN, meta={})
    assert out and out[0]["_mode"] == "partial"
    assert seen == {}  # 局部搜尋不傳 meta／cursor ⇒ 路由輸出 null


def test_maker_branch_forwards_cursor_and_meta():
    with patch("core.maker_names.known_makers", return_value=frozenset({"sod"})), \
         patch("core.scraper.is_uncensored_route", return_value=False), \
         patch("core.scraper._library_title_list", return_value=["T"]), \
         patch("core.scraper.search_maker") as sm:
        sm.return_value = MakerSearchResult([_card("SOD-1")], False, None)
        meta = {}
        sc.smart_search("SOD", offset=30, resolve_makers=True, cursor=TOKEN, meta=meta)
    kwargs = sm.call_args.kwargs
    assert kwargs["cursor"] == TOKEN and kwargs["meta"] is meta
    assert meta == {"has_more": False}  # _search_maker_intent 自己不往 meta 加 cursor／answered_by，只有 relay 寫


# ================================================================ shim 轉傳
@pytest.fixture
def intent_spy():
    with patch("core.scraper.search_by_intent") as m:
        m.return_value = []
        yield m


def test_search_prefix_shim_forwards_window_cursor_meta(intent_spy):
    meta = {}
    sc.search_prefix("MIDV", 20, 40, cursor=TOKEN, meta=meta)
    args, kwargs = intent_spy.call_args
    assert args == ("prefix", "MIDV", Window(40, 20))
    assert kwargs["cursor"] == TOKEN and kwargs["meta"] is meta


def test_search_actress_shim_forwards_window_cursor_meta(intent_spy):
    meta = {}
    sc.search_actress("三上悠亜", 20, 40, cursor=TOKEN, meta=meta)
    args, kwargs = intent_spy.call_args
    assert args == ("actress", "三上悠亜", Window(40, 20))
    assert kwargs["cursor"] == TOKEN and kwargs["meta"] is meta


def test_search_partial_shim_forwards_cursor_meta(intent_spy):
    meta = {}
    sc.search_partial("ABC-12", cursor=TOKEN, meta=meta)
    args, kwargs = intent_spy.call_args
    assert args == ("partial", "ABC-12", Window(0, 0))
    assert kwargs["cursor"] == TOKEN and kwargs["meta"] is meta


@pytest.mark.parametrize("call", [
    lambda: sc.search_prefix("MIDV"),
    lambda: sc.search_actress("x"),
    lambda: sc.search_partial("ABC-12"),
])
def test_shims_default_cursor_and_meta_are_none(intent_spy, call):
    call()
    assert intent_spy.call_args.kwargs["cursor"] is None and intent_spy.call_args.kwargs["meta"] is None


def test_search_maker_latest_shim_forwards_cursor_meta():
    meta = {}
    with patch("core.scraper.search_maker") as sm:
        sm.return_value = MakerSearchResult([], False, "maker_empty")
        sc.search_maker_latest("mk", "片商", ["片商"], 30, titles=[], today="2026-10-21", cursor=TOKEN, meta=meta)
        sc.search_maker_latest("mk", "片商", ["片商"], 0, titles=[], today="2026-10-21")
    first, second = sm.call_args_list
    assert first.kwargs["cursor"] == TOKEN and first.kwargs["meta"] is meta
    assert second.kwargs["cursor"] is None and second.kwargs["meta"] is None


# ================================================================ 端到端：smart_search → shim → relay（stub 鏈）
class Stub:
    fallback_streaming = False
    supports_discovery = False
    capabilities = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE, Kind.ACTOR})

    def __init__(self, pid, cards=()):
        self.id = pid
        self.cards = list(cards)
        self.calls = []

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.calls.append(("run", kind, target, w))
        return [dict(c) for c in self.cards]

    def resolve(self, kind, name):
        self.calls.append(("resolve", kind, name))
        return None


def test_end_to_end_prefix_pages_stay_with_first_answerer_and_end_without_fallback(monkeypatch, env):
    a, b = Stub("javbus"), Stub("dmm", [_card("P-1")])
    for p in (a, b):
        monkeypatch.setitem(registry._REGISTRY, p.id, lambda p=p: p)
    monkeypatch.setattr(sc, "get_all_source_ids_ordered", lambda: ["javbus", "dmm", "jav321"])
    jav321 = []
    monkeypatch.setattr(sc, "search_jav321_keyword", lambda *a, **k: jav321.append(1) or [_card("J-1")])
    meta = {}
    first = sc.smart_search("MIDV", limit=3, offset=0, meta=meta)
    assert [c["number"] for c in first] == ["P-1"] and meta["answered_by"] == "dmm"
    assert cursor.decode(meta["cursor"]) == cursor.Token("dmm", "keyword", ())
    a_calls = len(a.calls)
    # 載入更多：只問 dmm
    second = sc.smart_search("MIDV", limit=3, offset=3, cursor=meta["cursor"], meta=meta)
    assert [c["number"] for c in second] == ["P-1"]
    assert len(a.calls) == a_calls and b.calls[-1] == ("run", Kind.CODE, "MIDV", Window(3, 3))
    # 前綴到底：回空，不退到女優（resolve 不被問）、不退到 jav321
    b.cards = []
    b_before = len(b.calls)
    assert sc.smart_search("MIDV", limit=3, offset=6, cursor=meta["cursor"], meta={}) == []
    assert len(a.calls) == a_calls and jav321 == []
    assert [c[0] for c in b.calls[b_before:]] == ["run"]  # 只有那一次 CODE 查詢，沒有 resolve
    # 對照：沒有 token 的 offset=6 ⇒ 沒有任何 provider 被問
    n = len(a.calls) + len(b.calls)
    assert sc.smart_search("MIDV", limit=3, offset=6) == [] and len(a.calls) + len(b.calls) == n and jav321 == []
    # 對照：offset=0 前綴查無 ⇒ 退路照舊被問（jav321 命中）
    assert sc.smart_search("MIDV", limit=3, offset=0)[0]["number"] == "J-1" and jav321 == [1]
