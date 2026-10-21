"""175b-T4a：JavDBProvider 本體（list_entity／search_keyword／enrich／run／節流）。

傳輸一律 patch `javdb_api.<name>` 模組屬性；回應全為內嵌合成資料，不連外、不存站方檔（BE-TEST-43）。
「不准呼叫」量 call_count（BE-TEST-46）；時序只用「事件序列／記錄的 sleep」驗，不寫時間窗。
"""

from __future__ import annotations

import concurrent.futures as cf
import threading
import time
from unittest.mock import patch

import pytest

from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import javdb as jp
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import EntityRef, Kind, Window, WorkItem

REQUEST_DELAY = 0.3  # 硬寫：mutation 會改 core.scraper 的常數，測試不能跟著變


class _Scraper:
    def _proxy_kwargs(self):
        return {}


class SyncExecutor:
    """submit 當下就跑完：完成順序＝提交順序（決定性）。"""

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
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    clear_resolve_cache()
    monkeypatch.setattr(jp, "_sleep", lambda s: None)
    yield
    clear_resolve_cache()


@pytest.fixture
def pipe_sleeps(monkeypatch):
    """pipeline 詳情階段的 time.sleep 記錄（provider 的 _sleep 已另外 patch，不混入）。"""
    rec: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: rec.append(s))
    return rec


@pytest.fixture
def sync_executor(monkeypatch):
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)


def _list_row(i, number, date="2026-01-01"):
    return {"id": f"m{i}", "number": number, "title": f"t{i}", "origin_title": f"jt{i}",
            "cover_url": f"http://c/{i}.jpg", "release_date": date}


def _detail(i, *, actors=(), maker=None, series=None, director=None):
    return {"id": f"m{i}", "title": f"jt{i}", "release_date": "2026-01-01",
            "cover_url": f"http://c/{i}.jpg",
            "actors": [{"id": a, "name": f"n{a}", "gender": 0} for a in actors],
            "maker_id": maker, "series_id": series, "director_id": director}


class Site:
    """合成 JavDB：各傳輸函式的假實作，記錄呼叫。"""

    def __init__(self):
        self.typed: dict[tuple[str, str], list] = {}
        self.pages: dict[tuple[str, int], list] = {}  # (key, page) -> rows；key＝filter_by 或關鍵字
        self.details: dict[str, object] = {}  # movie id -> dict | Exception
        self.default_detail = None
        self.events: list[tuple] = []
        self.detail_calls: dict[str, int] = {}
        self.list_calls: list[tuple[str, int]] = []
        self.typed_calls: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, int]] = []
        self.exc: BaseException | None = None
        self._lock = threading.Lock()

    def _maybe_raise(self):
        if self.exc is not None:
            raise self.exc

    def search_typed(self, t, q, proxies=None):
        self.events.append(("req", "typed"))
        self.typed_calls.append((t, q))
        self._maybe_raise()
        return self.typed.get((t, q), [])

    def list_tags(self, filter_by, page, limit=50, proxies=None):
        self.events.append(("req", "list"))
        self.list_calls.append((filter_by, page))
        self._maybe_raise()
        return self.pages.get((filter_by, page), [])

    def search_page(self, q, page, limit=50, proxies=None):
        self.events.append(("req", "search"))
        self.search_calls.append((q, page))
        self._maybe_raise()
        return self.pages.get((q, page), [])

    def movie_detail(self, movie_id, proxies=None):
        with self._lock:
            self.detail_calls[movie_id] = self.detail_calls.get(movie_id, 0) + 1
        self._maybe_raise()
        d = self.details.get(movie_id, self.default_detail)
        if isinstance(d, BaseException):
            raise d
        if d is None:
            raise SourceUnreachable("no detail")
        return d

    def total_requests(self):
        return len(self.typed_calls) + len(self.list_calls) + len(self.search_calls) + sum(self.detail_calls.values())


@pytest.fixture
def site(monkeypatch):
    s = Site()
    monkeypatch.setattr(javdb_api, "api_search_typed", s.search_typed)
    monkeypatch.setattr(javdb_api, "api_list_tags", s.list_tags)
    monkeypatch.setattr(javdb_api, "api_search_page", s.search_page)
    monkeypatch.setattr(javdb_api, "api_movie_detail", s.movie_detail)
    return s


def _prov():
    return JavDBProvider(scraper=_Scraper())


def _code_row(name="MIDV", vc=100):
    return {"id": "c1", "name": name, "name_zht": "", "other_name": "", "videos_count": vc, "type": None}


def _fill_list(site, key, numbers, page=1, start=0):
    site.pages[(key, page)] = [_list_row(start + i, n) for i, n in enumerate(numbers)]
    for i, _ in enumerate(numbers):
        site.details.setdefault(f"m{start + i}", _detail(start + i, actors=["A1"]))


# ------------------------------------------------------------------ 能力面
def test_capabilities_exact_seven_without_label():
    assert JavDBProvider.capabilities == frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD})
    assert Kind.LABEL not in JavDBProvider.capabilities


def test_supports_discovery_is_false():
    assert JavDBProvider.supports_discovery is False


def test_fallback_streaming_is_false():
    assert JavDBProvider.fallback_streaming is False


# ------------------------------------------------------------------ list_entity／search_keyword
@pytest.mark.parametrize("kind,flag", [(Kind.ACTOR, "a"), (Kind.SERIES, "s"), (Kind.DIRECTOR, "d"),
                                       (Kind.MAKER, "m"), (Kind.CODE, "c")])
def test_list_entity_filter_by_flag(site, kind, flag):
    site.pages[(f"0:{flag}:X9", 1)] = [_list_row(1, "AAA-001")]
    page = _prov().list_entity(EntityRef(kind, "X9", "x"), Window(0, 20))
    assert site.list_calls == [(f"0:{flag}:X9", 1)]
    assert [i.number for i in page.items] == ["AAA-001"]


@pytest.mark.parametrize("kind", [Kind.LABEL, Kind.KEYWORD, Kind.PARTIAL])
def test_list_entity_unsupported_kind_raises_without_request(site, kind):
    with pytest.raises(ValueError):
        _prov().list_entity(EntityRef(kind, "x", "x"), Window(0, 20))
    assert site.total_requests() == 0


def test_search_keyword_uses_search_page(site):
    site.pages[("人妻", 1)] = [_list_row(1, "AAA-001")]
    page = _prov().search_keyword("人妻", Window(0, 20))
    assert site.search_calls == [("人妻", 1)]
    assert [i.number for i in page.items] == ["AAA-001"]


# ------------------------------------------------------------------ enrich／belongs
def test_enrich_belongs_requires_same_actor_id(site):
    site.details["m1"] = _detail(1, actors=["A1"])
    site.details["m2"] = _detail(2, actors=["B2"])  # 有女優，但不是她
    ref = EntityRef(Kind.ACTOR, "A1", "x")
    p = _prov()
    yes = p.enrich(WorkItem("AAA-001", "t", "", "", None, "javdb", ref="m1"), ref)
    no = p.enrich(WorkItem("AAA-002", "t", "", "", None, "javdb", ref="m2"), ref)
    assert yes.belongs is True and no.belongs is False


@pytest.mark.parametrize("kind,field", [(Kind.SERIES, "series"), (Kind.DIRECTOR, "director"), (Kind.MAKER, "maker")])
def test_enrich_belongs_by_entity_id(site, kind, field):
    site.details["m1"] = _detail(1, **{field: "E1"})
    site.details["m2"] = _detail(2, **{field: "E2"})
    site.details["m3"] = _detail(3)
    ref = EntityRef(kind, "E1", "x")
    p = _prov()
    got = [p.enrich(WorkItem("AAA-00%d" % i, "t", "", "", None, "javdb", ref=f"m{i}"), ref).belongs for i in (1, 2, 3)]
    assert got == [True, False, False]


def test_enrich_belongs_code_prefix_and_none_ref(site):
    site.details["m1"] = _detail(1)
    p = _prov()
    ref = EntityRef(Kind.CODE, "MIDV", "MIDV")
    assert p.enrich(WorkItem("MIDV-001", "t", "", "", None, "javdb", ref="m1"), ref).belongs is True
    assert p.enrich(WorkItem("ABC-001", "t", "", "", None, "javdb", ref="m1"), ref).belongs is False
    assert p.enrich(WorkItem("MIDV-001", "t", "", "", None, "javdb", ref="m1"), None).belongs is None


def test_enrich_card_has_source_and_no_sleep(site, pipe_sleeps):
    site.details["m1"] = _detail(1, actors=["A1"])
    out = _prov().enrich(WorkItem("AAA-001", "t", "", "", None, "javdb", ref="m1"), None)
    assert out.card["_source"] == "javdb" and out.card["number"] == "AAA-001"
    assert pipe_sleeps == []  # enrich 不自己 sleep


# ------------------------------------------------------------------ run：CODE
def _code_site(site, numbers, details=None):
    site.typed[("code", "MIDV")] = [_code_row()]
    _fill_list(site, "0:c:MIDV", numbers)
    for k, v in (details or {}).items():
        site.details[k] = v


def test_code_latest_listing_is_rejected_by_guard(site, sync_executor, pipe_sleeps):
    # 站方靜默回全站最新：前 3 部都不是 MIDV
    _code_site(site, ["ABC-001", "DEF-002", "GHI-003", "MIDV-004"])
    got = []
    out = _prov().run(Kind.CODE, "midv", Window(0, 20), result_callback=lambda s, c: got.append(s))
    assert out == [] and got == []
    assert site.detail_calls.get("m3", 0) == 0  # 守衛只抓前 3 部


def test_code_guard_passes_when_one_of_three_belongs(site, sync_executor, pipe_sleeps):
    _code_site(site, ["ABC-001", "DEF-002", "MIDV-003", "MIDV-004"])
    out = _prov().run(Kind.CODE, " midv ", Window(0, 20))
    assert {c["number"] for c in out} == {"ABC-001", "DEF-002", "MIDV-003", "MIDV-004"}
    assert site.list_calls == [("0:c:MIDV", 1)]


def test_code_guard_two_false_one_exception_is_empty(site, sync_executor, pipe_sleeps):
    _code_site(site, ["ABC-001", "DEF-002", "MIDV-003"], {"m2": SourceUnreachable("x")})
    got = []
    out = _prov().run(Kind.CODE, "MIDV", Window(0, 20), result_callback=lambda s, c: got.append(s))
    assert out == [] and got == []


def test_code_unresolved_prefix_is_empty_without_list_request(site):
    out = _prov().run(Kind.CODE, "ZZZZ", Window(0, 20))
    assert out == [] and site.list_calls == []


# ------------------------------------------------------------------ run：KEYWORD／收尾／status
def test_keyword_run_sorted_source_and_status(site, sync_executor, pipe_sleeps):
    site.pages[("人妻", 1)] = [_list_row(1, "AAA-001", "2025-01-01"), _list_row(2, "BBB-002", "2026-05-05")]
    site.details["m1"] = _detail(1, actors=["A1"])
    site.details["m2"] = SourceUnreachable("boom")  # 降級卡也要有 _source
    status = []
    out = _prov().run(Kind.KEYWORD, "人妻", Window(0, 20), status_callback=lambda a, b: status.append((a, b)))
    assert [c["number"] for c in out] == ["BBB-002", "AAA-001"]  # 日期新到舊
    assert all(c["_source"] == "javdb" for c in out)
    assert status[0] == ("javdb", "searching") and status[-1] == ("done", "found:2")


def test_unsupported_run_kind_raises(site):
    with pytest.raises(ValueError):
        _prov().run(Kind.MAKER, "x", Window(0, 20))


@pytest.mark.parametrize("kind", [Kind.CODE, Kind.KEYWORD, Kind.PARTIAL])
def test_discovery_only_is_empty_with_zero_requests(site, kind):
    assert _prov().run(kind, "MIDV", Window(0, 20), discovery_only=True) == []
    assert site.total_requests() == 0


# ------------------------------------------------------------------ 傳輸例外往外丟
_EXCS = [SourceBlocked("b"), SourceUnreachable("u"), ConnectionError("c")]


@pytest.mark.parametrize("exc", _EXCS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("kind,target", [(Kind.CODE, "MIDV"), (Kind.KEYWORD, "人妻"), (Kind.PARTIAL, "MIDV-01")])
def test_transport_errors_propagate(site, exc, kind, target):
    site.exc = exc
    with pytest.raises(type(exc)):
        _prov().run(kind, target, Window(0, 20))


@pytest.mark.parametrize("exc", _EXCS, ids=lambda e: type(e).__name__)
def test_transport_errors_propagate_from_list_stage(site, exc):
    site.typed[("code", "MIDV")] = [_code_row()]
    site.exc = None
    p = _prov()
    ref = p.resolve(Kind.CODE, "MIDV")
    site.exc = exc
    with pytest.raises(type(exc)):
        p.list_entity(ref, Window(0, 20))
    with pytest.raises(type(exc)):
        p.search_keyword("x", Window(0, 20))


# ------------------------------------------------------------------ 視窗
def test_window_beyond_cap_sends_no_list_request(site):
    out = _prov().run(Kind.KEYWORD, "人妻", Window(4950, 20))
    assert out == [] and site.list_calls == [] and site.search_calls == []


def test_window_spanning_two_pages_requests_two_lists_and_twenty_details(site, sync_executor, pipe_sleeps):
    # 第 1 頁 50 列（含缺 id／number 的壞列），第 2 頁 50 列；offset 40 limit 20 ⇒ 跨兩頁
    p1 = [_list_row(i, f"P1-{i:03d}") for i in range(50)]
    p1[3] = {"number": "NOID-1"}
    p1[4] = {"id": "x", "number": ""}
    p2 = [_list_row(100 + i, f"P2-{i:03d}") for i in range(50)]
    site.pages[("kw", 1)] = p1
    site.pages[("kw", 2)] = p2
    for r in p1 + p2:
        if "id" in r:
            site.details[r["id"]] = _detail(0, actors=["A1"])
    out = _prov().run(Kind.KEYWORD, "kw", Window(40, 20))
    assert site.search_calls == [("kw", 1), ("kw", 2)]
    assert sum(site.detail_calls.values()) == 20
    assert len(out) == 20


# ------------------------------------------------------------------ 補卡階段失敗
def _kw_site(site, n):
    site.pages[("kw", 1)] = [_list_row(i, f"AAA-{i:03d}") for i in range(n)]
    for i in range(n):
        site.details[f"m{i}"] = _detail(i, actors=["A1"])


def test_one_detail_failure_degrades_only_that_card_no_retry(site, sync_executor, pipe_sleeps):
    _kw_site(site, 20)
    site.details["m6"] = ValueError("bad")  # 第 7 部
    out = _prov().run(Kind.KEYWORD, "kw", Window(0, 20))
    assert len(out) == 20
    empty = [c["number"] for c in out if c["actors"] == []]
    assert empty == ["AAA-006"]
    assert site.detail_calls["m6"] == 1


def test_consecutive_blocked_details_stop_new_requests(site, sync_executor, pipe_sleeps):
    _kw_site(site, 20)
    for k in (3, 4, 5):  # 第 4–6 部連續被擋
        site.details[f"m{k}"] = SourceBlocked("blocked")
    out = _prov().run(Kind.KEYWORD, "kw", Window(0, 20))
    assert len(out) == 20
    called = {k: v for k, v in site.detail_calls.items()}
    assert all(called.get(f"m{k}", 0) == 0 for k in range(7, 20)), called  # 第 7 部起零新發起


# ------------------------------------------------------------------ I-A1
def test_detail_phase_respects_i_a1(site, monkeypatch, pipe_sleeps):
    created = []
    real = cf.ThreadPoolExecutor

    class Spy(real):
        def __init__(self, *a, **kw):
            created.append(kw.get("max_workers", a[0] if a else None))
            super().__init__(*a, **kw)

    monkeypatch.setattr(cf, "ThreadPoolExecutor", Spy)
    _kw_site(site, 8)
    out = _prov().run(Kind.KEYWORD, "kw", Window(0, 20))
    assert len(out) == 8
    assert created and all(m is not None and m <= 2 for m in created)
    assert len(pipe_sleeps) >= 8 and all(s >= REQUEST_DELAY for s in pipe_sleeps)


def test_sequential_requests_are_paced(site, monkeypatch):
    # 3 次查名（片商候選名）＋ 2 頁列表：每兩次請求之間、以及最後一次請求之後，都要有 ≥REQUEST_DELAY 的 sleep
    events: list[tuple] = []
    monkeypatch.setattr(jp, "_sleep", lambda s: events.append(("sleep", s)))
    for name in ("Canon", "a1", "a2"):
        site.typed[("maker", name)] = []
    p1 = [_list_row(i, f"P1-{i:03d}") for i in range(50)]
    site.pages[("0:m:M1", 1)] = p1
    site.pages[("0:m:M1", 2)] = [_list_row(100, "P2-001")]

    def log(real):
        def f(*a, **kw):
            events.append(("req", real.__name__))
            return real(*a, **kw)
        return f

    monkeypatch.setattr(javdb_api, "api_search_typed", log(site.search_typed))
    monkeypatch.setattr(javdb_api, "api_list_tags", log(site.list_tags))
    with patch.object(jp, "load_name_mapping", lambda: {"a1": "Canon", "a2": "Canon"}), \
            patch.object(jp, "load_search_aliases", lambda: {}):
        p = _prov()
        assert p.resolve(Kind.MAKER, "Canon") is None
        p.list_entity(EntityRef(Kind.MAKER, "M1", "m"), Window(0, 60))
    reqs = [i for i, e in enumerate(events) if e[0] == "req"]
    assert len(reqs) == 5
    for a, b in zip(reqs, reqs[1:] + [len(events)]):
        between = [e for e in events[a + 1:b] if e[0] == "sleep"]
        assert between and all(s >= REQUEST_DELAY for _, s in between), events


# ------------------------------------------------------------------ PARTIAL
def _partial_site(site):
    site.pages[("MIDV-01", 1)] = [
        _list_row(1, "MIDV-010", "2026-01-01"),   # 該留
        _list_row(2, "DV-905", "2026-01-02"),     # 該丟（站方前綴比對混進來的）
        _list_row(3, "MIDV-011", "2024-01-01"),   # 撞號：舊
        _list_row(4, "MIDV-011", "2026-03-03"),   # 撞號：新
        _list_row(5, "MIDV-012", "2025-01-01"),   # 撞號：新在前
        _list_row(6, "MIDV-012", "2020-01-01"),   # 撞號：舊在後
        _list_row(7, "XMIDV-013", "2026-01-01"),  # 該丟：非開頭
    ]
    site.pages[("midv-01", 1)] = site.pages[("MIDV-01", 1)]  # 小寫輸入也要過濾得到
    for i in range(1, 8):
        site.details[f"m{i}"] = _detail(i, actors=["A1"])


def test_partial_filters_by_normalized_prefix(site, sync_executor, pipe_sleeps):
    _partial_site(site)
    out = _prov().run(Kind.PARTIAL, "midv-01", Window(0, 0))
    nums = {c["number"] for c in out}
    assert "DV-905" not in nums and "XMIDV-013" not in nums
    assert nums == {"MIDV-010", "MIDV-011", "MIDV-012"}


def test_partial_same_number_keeps_newer(site, sync_executor, pipe_sleeps):
    _partial_site(site)
    _prov().run(Kind.PARTIAL, "MIDV-01", Window(0, 0))
    fetched = {k for k, v in site.detail_calls.items() if v}
    assert "m4" in fetched and "m3" not in fetched      # 後出現但較新 → 留後者
    assert "m5" in fetched and "m6" not in fetched      # 先出現且較新 → 留前者


def test_partial_ignores_zero_limit_and_fetches_one_page(site, sync_executor, pipe_sleeps):
    _partial_site(site)
    out = _prov().run(Kind.PARTIAL, "MIDV-01", Window(0, 0))
    assert len(out) == 3 and site.search_calls == [("MIDV-01", 1)]


def test_partial_offset_positive_is_empty_zero_requests(site):
    _partial_site(site)
    assert _prov().run(Kind.PARTIAL, "MIDV-01", Window(20, 20)) == []
    assert site.total_requests() == 0
