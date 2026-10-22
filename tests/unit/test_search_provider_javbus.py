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
from core.search_providers import cursor as cursor_codec
from core.search_providers import types as sp_types
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import EntityRef, Kind, WorkItem, Window
pytestmark = pytest.mark.usefixtures("no_entity_lookup")


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

            def get_ids_from_search(self, query, page=1, search_type=None, uncensored=False):
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


def numbers(cards):
    return sorted(c["number"] for c in cards)


# ---------------------------------------------------------------- 1. shim 把 offset 傳到底
@pytest.mark.parametrize("offset,first_page", [(40, 2)])
@pytest.mark.parametrize("kind", ["prefix", "keyword", "actress"])
def test_shim_forwards_offset(monkeypatch, kind, offset, first_page):
    env = Env(monkeypatch)
    token = cursor_codec.encode(cursor_codec.Token("javbus", "keyword"))  # offset>0 ⇒ 載入更多必須帶有效 token（175d）
    if kind == "prefix":
        out = scraper_mod.search_prefix("midv", 20, offset, cursor=token)
    elif kind == "actress":
        out = scraper_mod.search_actress("MIDV", 20, offset, cursor=token)
    else:
        out = scraper_mod._javbus_keyword_search("MIDV", 20, offset, None, None)
    assert env.id_calls[0][1] == first_page
    assert numbers(out) == [f"MIDV-{i:03d}" for i in range(offset + 1, offset + 21)]


# ---------------------------------------------------------------- 2. 失敗／無 title 丟棄


# ---------------------------------------------------------------- 3. 不斷路、不加延遲


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


# ---------------------------------------------------------------- 5. 事件序


# ---------------------------------------------------------------- 6b. 統一入口


# ---------------------------------------------------------------- 6. 片商
def _maker(env, monkeypatch, status="found", offset=0):
    res = SimpleNamespace(status=status, kind="studio", studio_id="sid")
    monkeypatch.setattr(scraper_mod, "resolve_maker_studio", lambda *a, **k: res)
    return JavBusProvider().run_maker("k", "label", ["l"], offset, titles=[], today=None)


@pytest.mark.parametrize("status,code", [
    ("absent", "maker_not_found"), ("unreachable", "maker_unreachable"),
    ])
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
