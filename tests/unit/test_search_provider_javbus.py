"""175a-T4：JavBusProvider（原封包入）＋ core.scraper 四個 shim。

全部合成資料、patch 使用端（core.scraper.*），不連網（BE-TEST-43）。
「不准呼叫」量 call_count（BE-TEST-46）。
"""

import concurrent.futures as cf
import threading
import time
from types import SimpleNamespace

import pytest

import core.scraper as scraper_mod
from core.scrapers.errors import SourceBlocked
from core.search_providers import types as sp_types
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import EntityRef, Kind, WorkItem, Window


# ---------------------------------------------------------------- fixtures
class _SyncExecutor:
    def __init__(self, max_workers=None, **_):
        self.max_workers = max_workers

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
def sleeps(monkeypatch):
    rec = []
    monkeypatch.setattr(time, "sleep", lambda s: rec.append(s))
    return rec


@pytest.fixture(autouse=True)
def sync_executor(monkeypatch):
    monkeypatch.setattr(cf, "ThreadPoolExecutor", _SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))


@pytest.fixture(autouse=True)
def fixed_source_order(monkeypatch):
    """shim 現在經 relay：固定來源順序與開關，不吃 live config（BE-TEST-02／01，patch 使用端）。"""
    monkeypatch.setattr(scraper_mod, "get_all_source_ids_ordered", lambda: ["javbus"])
    monkeypatch.setattr(scraper_mod, "is_source_enabled", lambda sid: sid == "javbus")


class Env:
    """合成的 JavBus：每頁 30 筆、最多 pages 頁；search_jav 依 script 回應。"""

    def __init__(self, monkeypatch, pages=3, prefix="MIDV", script=None):
        self.id_calls = []  # (query, page, search_type)
        self.studio_calls = []
        self.jav_calls = []
        self.script = script or {}
        self.lock = threading.Lock()
        self.pages = pages
        self.prefix = prefix
        self.per_page = 30
        self.studio_ids = []
        self.studio_error = None
        env = self

        class FakeScraper:
            def __init__(self, lang=None):
                env.lang = lang

            def get_ids_from_search(self, query, page=1, search_type=None):
                env.id_calls.append((query, page, search_type))
                if page > env.pages:
                    return []
                return [f"{env.prefix}-{(page - 1) * 30 + i:03d}" for i in range(1, env.per_page + 1)]

            def get_ids_from_studio(self, ref, page):
                env.studio_calls.append((ref, page))
                if env.studio_error:
                    raise env.studio_error
                return env.studio_ids

        monkeypatch.setattr(scraper_mod, "JavBusScraper", FakeScraper)
        monkeypatch.setattr(scraper_mod, "get_javbus_lang", lambda: "zh-tw")
        monkeypatch.setattr(scraper_mod, "search_jav", self.search_jav)

    def search_jav(self, number, source):
        with self.lock:
            self.jav_calls.append((number, source))
        act = self.script.get(number, "OK")
        if isinstance(act, Exception):
            raise act
        if act is None or act == "NONE":
            return None
        if act == "NOTITLE":
            return {"number": number, "title": "", "date": "2026-01-01"}
        return {"number": number, "title": f"t {number}", "date": "2026-01-01", "actors": ["a"]}


def collect():
    ev = []
    return ev, lambda src, msg: ev.append(("s", src, msg)), lambda slot, data: ev.append(("r", slot, data))


def numbers(cards):
    return sorted(c["number"] for c in cards)


# ---------------------------------------------------------------- 1. shim 把 offset 傳到底
@pytest.mark.parametrize("offset,first_page", [(20, 1), (40, 2)])
@pytest.mark.parametrize("kind", ["prefix", "keyword", "actress"])
def test_shim_forwards_offset(monkeypatch, kind, offset, first_page):
    env = Env(monkeypatch)
    if kind == "prefix":
        out = scraper_mod.search_prefix("midv", 20, offset)
    elif kind == "actress":
        out = scraper_mod.search_actress("MIDV", 20, offset)
    else:
        out = scraper_mod._javbus_keyword_search("MIDV", 20, offset, None, None)
    assert env.id_calls[0][1] == first_page
    assert numbers(out) == [f"MIDV-{i:03d}" for i in range(offset + 1, offset + 21)]


# ---------------------------------------------------------------- 2. 失敗／無 title 丟棄
def test_failed_detail_is_dropped_not_degraded(monkeypatch):
    env = Env(monkeypatch, script={"MIDV-002": ValueError("boom"), "MIDV-003": "NONE"})
    ev, st, rs = collect()
    out = JavBusProvider().run_prefix("MIDV", 4, 0, st, rs, False)
    assert numbers(out) == ["MIDV-001", "MIDV-004"]
    assert [e[1] for e in ev if e[0] == "r" and e[1] >= 0] == [0, 3]
    assert not any(c.get("title") == "" for c in out)
    assert len(env.jav_calls) == 4


def test_titleless_detail_is_dropped(monkeypatch):
    Env(monkeypatch, script={"MIDV-002": "NOTITLE"})
    ev, st, rs = collect()
    out = JavBusProvider().run_keyword("MIDV", 3, 0, st, rs)
    assert numbers(out) == ["MIDV-001", "MIDV-003"]
    assert [e[1] for e in ev if e[0] == "r" and e[1] >= 0] == [0, 2]


def test_all_detail_failed_returns_empty_but_seed_was_sent(monkeypatch):
    Env(monkeypatch, script={f"MIDV-{i:03d}": "NONE" for i in range(1, 4)})
    ev, st, rs = collect()
    assert JavBusProvider().run_prefix("MIDV", 3, 0, st, rs, False) == []
    assert ("r", -1, ["MIDV-001", "MIDV-002", "MIDV-003"]) in ev
    assert ev[-1] == ("s", "done", "found:0")


# ---------------------------------------------------------------- 3. 不斷路、不加延遲
def test_javbus_window_never_trips_breaker(monkeypatch):
    script = {f"MIDV-{i:03d}": SourceBlocked("blocked") for i in range(1, 4)}
    env = Env(monkeypatch, script=script)
    out = JavBusProvider().run_keyword("MIDV", 6, 0, None, None)
    assert len(env.jav_calls) == 6
    assert numbers(out) == ["MIDV-004", "MIDV-005", "MIDV-006"]


def test_javbus_window_adds_no_delay(monkeypatch, sleeps):
    Env(monkeypatch)
    JavBusProvider().run_prefix("MIDV", 4, 0, None, None, False)
    JavBusProvider().run_partial("SONE-0", None, None, False)
    assert sleeps and all(s == 0 for s in sleeps)


# ---------------------------------------------------------------- 4. Provider 合約
def test_list_entity_code_uses_prefix_search_type_and_window(monkeypatch):
    env = Env(monkeypatch)
    page = JavBusProvider().list_entity(EntityRef(Kind.CODE, "MIDV", "MIDV"), Window(20, 20))
    assert [i.number for i in page.items] == [f"MIDV-{i:03d}" for i in range(21, 41)]
    assert env.id_calls[0] == ("MIDV", 1, 1)
    assert all(isinstance(i, WorkItem) and i.source == "javbus" and i.actors is None for i in page.items)
    env.id_calls.clear()
    JavBusProvider().list_entity(EntityRef(Kind.CODE, "MIDV", "MIDV"), Window(40, 20))
    assert env.id_calls[0][1] == 2


def test_search_keyword_window_has_no_search_type(monkeypatch):
    env = Env(monkeypatch)
    page = JavBusProvider().search_keyword("温泉", Window(0, 5))
    assert len(page.items) == 5
    assert env.id_calls == [("温泉", 1, None)]


def test_list_entity_partial_returns_candidates_and_ignores_limit(monkeypatch):
    Env(monkeypatch)
    monkeypatch.setattr(scraper_mod, "expand_partial_number", lambda p: ["SONE-001", "SONE-002", "SONE-003"])
    p = JavBusProvider()
    ref = EntityRef(Kind.PARTIAL, "SONE-0", "SONE-0")
    assert [i.number for i in p.list_entity(ref, Window(0, 1)).items] == ["SONE-001", "SONE-002", "SONE-003"]
    assert p.list_entity(ref, Window(30, 20)).items == []


# ---------------------------------------------------------------- 5. 事件序
def test_prefix_details_progress_reaches_n_of_n_with_failure(monkeypatch):
    Env(monkeypatch, script={"MIDV-002": ValueError("boom")})
    ev, st, rs = collect()
    out = JavBusProvider().run_prefix("midv", 3, 0, st, rs, False)
    assert [e[:3] if e[0] == "s" else ("r", e[1]) for e in ev] == [
        ("s", "javbus", "searching"),
        ("s", "javbus", "found:3"),
        ("s", "javbus", "fetching_details"),
        ("r", -1),
        ("s", "javbus", "details:1/3"),
        ("r", 0),
        ("s", "javbus", "details:2/3"),
        ("s", "javbus", "details:3/3"),
        ("r", 2),
        ("s", "done", "found:2"),
    ]
    assert numbers(out) == ["MIDV-001", "MIDV-003"]


def test_keyword_event_sequence_and_no_ids(monkeypatch):
    env = Env(monkeypatch, pages=0)
    ev, st, rs = collect()
    assert JavBusProvider().run_keyword("nothing", 20, 0, st, rs) == []
    assert ev == [("s", "javbus", "searching")]
    env.pages = 1
    ev, st, rs = collect()
    JavBusProvider().run_keyword("MIDV", 2, 0, st, rs)
    assert ev[0] == ("s", "javbus", "searching") and ev[1] == ("s", "javbus", "found:2")
    assert ev[2][:2] == ("r", -1) and ev[-1] == ("s", "done", "found:2")


def test_prefix_without_any_id_reports_found_zero(monkeypatch):
    Env(monkeypatch, pages=0)
    ev, st, rs = collect()
    assert JavBusProvider().run_prefix("ZZZ", 20, 0, st, rs, False) == []
    assert ev == [("s", "javbus", "searching"), ("s", "javbus", "found:0")]


@pytest.mark.parametrize("flow", ["prefix", "keyword"])
def test_offset_past_available_ids_reports_found_zero_then_done(monkeypatch, flow):
    env = Env(monkeypatch, pages=1)
    env.per_page = 5
    ev, st, rs = collect()
    p = JavBusProvider()
    out = p.run_prefix("MIDV", 20, 10, st, rs, False) if flow == "prefix" else p.run_keyword("MIDV", 20, 10, st, rs)
    assert out == []
    msgs = [e[2] for e in ev if e[0] == "s"]
    assert "found:0" in msgs and msgs[-1] == "found:0" and ev[-1] == ("s", "done", "found:0")
    assert not any(e[0] == "r" for e in ev)


def test_partial_discovery_still_sends_seed_then_returns_stubs(monkeypatch):
    env = Env(monkeypatch)
    monkeypatch.setattr(scraper_mod, "expand_partial_number", lambda p: ["SONE-001", "SONE-002"])
    ev, st, rs = collect()
    out = JavBusProvider().run_partial("SONE-0", st, rs, True)
    assert ev == [
        ("s", "javbus", "searching"),
        ("r", -1, ["SONE-001", "SONE-002"]),
        ("s", "done", "found:2"),
    ]
    assert out == [{"number": "SONE-001", "title": ""}, {"number": "SONE-002", "title": ""}]
    assert env.jav_calls == []


def test_partial_full_run_seed_then_results(monkeypatch):
    Env(monkeypatch)
    monkeypatch.setattr(scraper_mod, "expand_partial_number", lambda p: ["SONE-001", "SONE-002"])
    ev, st, rs = collect()
    out = JavBusProvider().run_partial("SONE-0", st, rs, False)
    assert [(e[0], e[1]) for e in ev] == [("s", "javbus"), ("r", -1), ("r", 0), ("r", 1), ("s", "done")]
    assert numbers(out) == ["SONE-001", "SONE-002"]


# ---------------------------------------------------------------- 6b. 統一入口
def test_run_dispatches_by_kind(monkeypatch):
    env = Env(monkeypatch)
    monkeypatch.setattr(scraper_mod, "expand_partial_number", lambda p: ["SONE-001"])
    p = JavBusProvider()
    assert numbers(p.run(Kind.CODE, "MIDV", Window(20, 3))) == ["MIDV-021", "MIDV-022", "MIDV-023"]
    assert env.id_calls[0] == ("MIDV", 1, 1)
    env.id_calls.clear()
    assert len(p.run(Kind.KEYWORD, "温泉", Window(0, 2))) == 2
    assert env.id_calls[0] == ("温泉", 1, None)
    assert numbers(p.run(Kind.PARTIAL, "SONE-0", Window(0, 20))) == ["SONE-001"]
    assert p.run(Kind.PARTIAL, "SONE-0", Window(20, 20)) == []
    with pytest.raises(ValueError):
        p.run(Kind.MAKER, "x", Window(0, 30))


# ---------------------------------------------------------------- 6. 片商
def _maker(env, monkeypatch, status="found", offset=0):
    res = SimpleNamespace(status=status, kind="studio", studio_id="sid")
    monkeypatch.setattr(scraper_mod, "resolve_maker_studio", lambda *a, **k: res)
    return JavBusProvider().run_maker("k", "label", ["l"], offset, titles=[], today=None)


@pytest.mark.parametrize("status,code", [
    ("absent", "maker_not_found"), ("unreachable", "maker_unreachable"),
    ("no_sample", "maker_no_sample"), ("weird", "maker_unreachable")])
def test_maker_resolution_error_codes(monkeypatch, status, code):
    env = Env(monkeypatch)
    out = _maker(env, monkeypatch, status)
    assert out == sp_types.MakerSearchResult([], False, code)
    assert env.studio_calls == []


def test_maker_list_failure_empty_and_has_more(monkeypatch):
    env = Env(monkeypatch)
    env.studio_error = RuntimeError("down")
    assert _maker(env, monkeypatch).error_code == "maker_unreachable"
    env.studio_error = None
    env.studio_ids = []
    assert _maker(env, monkeypatch).error_code == "maker_empty"
    env.studio_ids = [f"AAA-{i:03d}" for i in range(1, 31)]
    full = _maker(env, monkeypatch, offset=30)
    assert full.error_code is None and full.has_more is True and len(full.results) == 30
    assert env.studio_calls[-1] == (("studio", "sid"), 2)
    env.studio_ids = [f"AAA-{i:03d}" for i in range(1, 6)]
    part = _maker(env, monkeypatch)
    assert part.has_more is False and len(part.results) == 5


def test_protocol_pages_do_not_claim_more_past_the_end(monkeypatch):
    """查到資料末端 → provider 不得宣告還能繼續取頁（否則「載入更多」一直顯示）。"""
    env = Env(monkeypatch, pages=1)
    env.per_page = 5
    p = JavBusProvider()
    ref = EntityRef(Kind.CODE, "MIDV", "MIDV")
    assert p.list_entity(ref, Window(0, 20)).has_next is False  # 只有 5 筆
    assert p.list_entity(ref, Window(10, 20)).has_next is False  # offset 超出可得資料
    assert p.search_keyword("x", Window(0, 20)).has_next is False
    env.pages, env.per_page = 3, 30
    assert p.search_keyword("x", Window(0, 20)).has_next is True  # 還有更多
    assert p.list_entity(ref, Window(0, 20)).has_next is True
