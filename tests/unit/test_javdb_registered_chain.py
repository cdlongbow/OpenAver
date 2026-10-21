"""175b-T4b：JavDB 註冊後的端到端接力（真 registry＋真 JavDBProvider，只 patch javdb_api 傳輸）。

順序與開關 patch 使用端 core.scraper.*（BE-TEST-01／02）；JavBus／DMM 用真的回 [] 並記錄 run 的替身；
「不准呼叫」量 JavDBProvider.run 的 call_count（BE-TEST-46）與傳輸次數。不連外、不存站方檔（BE-TEST-43）。
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from unittest.mock import MagicMock, patch

import pytest

from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import javdb as jp
from core.search_providers import registry, relay
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import Kind, Window

W = Window(0, 20)
BASE_CAPS = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE})


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
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


class Other:
    """JavBus／DMM 的替身：run 真的回 cards（預設 []）並記錄呼叫。"""

    def __init__(self, pid, cards=(), discovery=False):
        self.id = pid
        self.capabilities = BASE_CAPS
        self.supports_discovery = discovery
        self.fallback_streaming = True
        self.cards = list(cards)
        self.run_calls = []

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append(kind)
        return list(self.cards)


class Site:
    def __init__(self):
        self.typed = {}
        self.pages = {}
        self.details = {}
        self.calls = []  # 所有傳輸（含詳情）

    def search_typed(self, t, q, proxies=None):
        self.calls.append(("typed", t, q))
        return self.typed.get((t, q), [])

    def list_tags(self, filter_by, page, limit=50, proxies=None):
        self.calls.append(("list", filter_by, page))
        return self.pages.get((filter_by, page), [])

    def search_page(self, q, page, limit=50, proxies=None):
        self.calls.append(("search", q, page))
        return self.pages.get((q, page), [])

    def movie_detail(self, movie_id, proxies=None):
        self.calls.append(("detail", movie_id))
        d = self.details.get(movie_id)
        if isinstance(d, BaseException):
            raise d
        if d is None:
            raise SourceUnreachable("no detail")
        return d


def _row(i, number):
    return {"id": f"m{i}", "number": number, "title": f"t{i}", "origin_title": f"jt{i}",
            "cover_url": f"http://c/{i}.jpg", "release_date": "2026-01-01"}


def _detail(i, actors):
    return {"id": f"m{i}", "title": f"jt{i}", "release_date": "2026-01-01", "cover_url": f"http://c/{i}.jpg",
            "actors": [{"id": a, "name": f"n{a}", "gender": 0} for a in actors]}


def _actress_site(site, actor_ids):
    site.typed[("actor", "someone")] = [
        {"id": "A1", "name": "someone", "name_zht": "", "other_name": "", "videos_count": 50, "type": 0}]
    site.pages[("0:a:A1", 1)] = [_row(i, f"AAA-{i:03d}") for i in range(1, 4)]
    for i in range(1, 4):
        site.details[f"m{i}"] = _detail(i, actor_ids)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    clear_resolve_cache()
    javdb_api.clear_actor_name_cache()
    monkeypatch.setattr(jp, "_sleep", lambda s: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(JavDBProvider, "_proxies", lambda self: None)
    yield
    clear_resolve_cache()
    javdb_api.clear_actor_name_cache()


@pytest.fixture
def site(monkeypatch):
    s = Site()
    monkeypatch.setattr(javdb_api, "api_search_typed", s.search_typed)
    monkeypatch.setattr(javdb_api, "api_list_tags", s.list_tags)
    monkeypatch.setattr(javdb_api, "api_search_page", s.search_page)
    monkeypatch.setattr(javdb_api, "api_movie_detail", s.movie_detail)
    return s


@pytest.fixture
def run_spy():
    with patch.object(JavDBProvider, "run", autospec=True, side_effect=JavDBProvider.run) as m:
        yield m


@pytest.fixture
def chain_env(monkeypatch, site, run_spy):
    def setup(order, enabled=None, others=None, discovery=False):
        others = others or {}
        fakes = {pid: Other(pid, others.get(pid, ()), discovery) for pid in ("javbus", "dmm")}
        for pid, f in fakes.items():
            monkeypatch.setitem(registry._REGISTRY, pid, lambda f=f: f)
        on = set(order) if enabled is None else set(enabled)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)
        return fakes

    return setup


# ------------------------------------------------------------------ 註冊後被問到
def test_javdb_answers_when_earlier_providers_are_empty(chain_env, site, run_spy):
    fakes = chain_env(["javbus", "dmm", "javdb"])
    _actress_site(site, ["A1"])
    out = relay.search_by_intent("actress", "someone", W)
    assert sorted(c["number"] for c in out) == ["AAA-001", "AAA-002", "AAA-003"]
    assert {c["_source"] for c in out} == {"javdb"}
    assert len(fakes["javbus"].run_calls) == 1 and len(fakes["dmm"].run_calls) == 1  # 先問過、都查無
    assert run_spy.call_count == 0  # 走實體梯子，不是 KEYWORD


def test_javdb_answers_keyword_after_earlier_providers_empty(chain_env, site, run_spy):
    fakes = chain_env(["javbus", "dmm", "javdb"])
    site.pages[("人妻", 1)] = [_row(1, "AAA-001"), _row(2, "AAA-002")]
    for i in (1, 2):
        site.details[f"m{i}"] = _detail(i, ["A1"])
    out = relay.search_by_intent("actress", "人妻", W)
    assert len(out) == 2 and {c["_source"] for c in out} == {"javdb"}
    assert len(fakes["javbus"].run_calls) == 1 and len(fakes["dmm"].run_calls) == 1
    assert run_spy.call_count == 1


def test_javdb_asked_first_when_ordered_first(chain_env, site, run_spy):
    fakes = chain_env(["javdb", "javbus", "dmm"], others={"javbus": [{"number": "X-1"}]})
    _actress_site(site, ["A1"])
    out = relay.search_by_intent("actress", "someone", W)
    assert {c["_source"] for c in out} == {"javdb"}
    assert fakes["javbus"].run_calls == []


def test_latest_listing_falls_through_to_next_provider(chain_env, site, run_spy):
    """站方靜默回全站最新：3 部詳情皆不屬於她 ⇒ JavDB 回 []、seed 0 次、換下一家。"""
    fakes = chain_env(["javdb", "dmm"], others={"dmm": [{"number": "D-1", "title": "dmm"}]})
    _actress_site(site, ["SOMEONE_ELSE"])
    seeds = MagicMock()
    out = relay.search_by_intent("actress", "someone", W, result_callback=seeds)
    assert out == [{"number": "D-1", "title": "dmm"}]
    assert len([c for c in site.calls if c[0] == "detail"]) == 3  # 只驗守衛那 3 部
    assert seeds.call_count == 0  # seed 0 次
    assert run_spy.call_count == 0  # 該家命中實體（雖然不屬於）⇒ 不再問 KEYWORD
    assert len(fakes["dmm"].run_calls) == 1


# ------------------------------------------------------------------ 開關
@pytest.mark.parametrize("mode", ["actress", "partial", "prefix"])
def test_javdb_disabled_in_settings_is_never_asked(chain_env, site, run_spy, mode):
    chain_env(["javbus", "dmm", "javdb"], enabled=["javbus", "dmm"])
    _actress_site(site, ["A1"])
    out = relay.search_by_intent(mode, "someone", W)
    assert out == []
    assert run_spy.call_count == 0
    assert site.calls == []  # 傳輸 0 次


# ------------------------------------------------------------------ 探索模式
@pytest.mark.parametrize("mode", ["actress", "prefix"])
def test_discovery_only_never_touches_javdb(chain_env, site, run_spy, mode):
    chain_env(["javbus", "dmm", "javdb"], discovery=True)
    _actress_site(site, ["A1"])
    out = relay.search_by_intent(mode, "someone", W, discovery_only=True)
    assert out == []
    assert run_spy.call_count == 0  # 只量傳輸會被 run 自己的 discovery_only 早退蓋住
    assert site.calls == []


# ------------------------------------------------------------------ 梯子可觀測
def test_entity_ladder_reports_status_for_javdb_only(chain_env, site, run_spy):
    fakes = chain_env(["javbus", "dmm", "javdb"])
    _actress_site(site, ["A1"])
    status = MagicMock()
    relay.search_by_intent("actress", "someone", W, status_callback=status)
    events = [c.args for c in status.call_args_list]
    assert ("javdb", "searching") in events
    assert ("done", "found:3") in events
    assert [e for e in events if e[0] in ("javbus", "dmm")] == []  # JavBus／DMM 梯子零事件
    assert fakes["javbus"].run_calls  # 它們只問了 KEYWORD


@pytest.mark.parametrize("exc,blocked", [(SourceBlocked("b"), True), (SourceUnreachable("u"), False)])
def test_ladder_failure_moves_on_and_logs_blocked_suffix(chain_env, site, run_spy, caplog, exc, blocked):
    chain_env(["javdb", "dmm"], others={"dmm": [{"number": "D-1"}]})
    def boom(t, q, proxies=None):
        raise exc

    with patch.object(javdb_api, "api_search_typed", boom), caplog.at_level("WARNING"):
        out = relay.search_by_intent("actress", "someone", W)
    assert out == [{"number": "D-1"}]
    line = [r.getMessage() for r in caplog.records if "entity ladder failed" in r.getMessage()]
    assert len(line) == 1 and ("/blocked" in line[0]) is blocked


# ------------------------------------------------------------------ smart_search 的 prefix → actress 退路（Codex P2）
def test_prefix_miss_actress_fallback_stays_discovery_only(monkeypatch, site, run_spy):
    """探索模式前綴查無 → actress 退路也要維持 discovery_only：DMM／JavDB 的 run 都 0 次。"""
    from core.scraper import smart_search

    jb, dmm = Other("javbus", discovery=True), Other("dmm", discovery=False)
    monkeypatch.setitem(registry._REGISTRY, "javbus", lambda: jb)
    monkeypatch.setitem(registry._REGISTRY, "dmm", lambda: dmm)
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ["javbus", "dmm", "javdb"])
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: True)
    monkeypatch.setattr("core.scraper.search_jav321_keyword", lambda *a, **kw: [])
    assert smart_search("MIDV", discovery_only=True) == []
    assert run_spy.call_count == 0
    assert dmm.run_calls == []
    assert site.calls == []
