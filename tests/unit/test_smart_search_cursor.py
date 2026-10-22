"""175d-T5：smart_search 層的續頁（CD-175d-9）＋ core.scraper shim 對 cursor／meta 的轉傳。

patch 使用端 core.scraper.*（BE-TEST-01）；search_prefix／search_actress／search_jav321_keyword 是我們自己的函式，
替身只記錄呼叫、不模擬任何站方回應（BE-TEST-43）。「不准呼叫」量呼叫記錄，每個零呼叫案配一個 offset=0 的對照（BE-TEST-23／46）。
"""

from types import SimpleNamespace

import pytest

import core.scraper as sc

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


# ================================================================ cursor／meta 轉傳


def test_fallback_actress_gets_the_same_meta_and_its_write_is_final(env):
    """prefix 查無 → 退到 actress：meta 以最後一次回答者（actress）為最終值。"""
    rec = env(Rec(prefix=[], actress=[_card("A-1")]))
    rec.actress_meta_write = {"cursor": "ACTRESS-TOKEN", "answered_by": "dmm"}
    meta = {"has_more": True}
    out = sc.smart_search("MIDV", offset=0, meta=meta)
    assert out and rec.calls["actress"][0].meta is meta
    assert meta["cursor"] == "ACTRESS-TOKEN" and meta["answered_by"] == "dmm"


# ================================================================ shim 轉傳


# ================================================================ 端到端：smart_search → shim → relay（stub 鏈）