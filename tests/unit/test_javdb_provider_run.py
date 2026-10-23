"""175b-T4a：JavDBProvider 本體（list_entity／search_keyword／enrich／run／節流）。

傳輸一律 patch `javdb_api.<name>` 模組屬性；回應全為內嵌合成資料，不連外、不存站方檔（BE-TEST-43）。
「不准呼叫」量 call_count（BE-TEST-46）；時序只用「事件序列／記錄的 sleep」驗，不寫時間窗。
"""

from __future__ import annotations

import concurrent.futures as cf
import threading
import time

import pytest

from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import javdb as jp
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import Kind, Window


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


# ------------------------------------------------------------------ 能力面


# ------------------------------------------------------------------ list_entity／search_keyword


# ------------------------------------------------------------------ run：CODE


# ------------------------------------------------------------------ run：KEYWORD／收尾／status


# ------------------------------------------------------------------ 傳輸例外往外丟
_EXCS = [SourceBlocked("b")]


@pytest.mark.parametrize("exc", _EXCS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("kind,target", [(Kind.CODE, "MIDV"), (Kind.PARTIAL, "MIDV-01")])
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


# ------------------------------------------------------------------ PARTIAL


def _page_for(site, monkeypatch, numbers, *, strict=False):
    """strict＝站方只回「號碼以查詢字開頭」的列；否則回整頁混合列（站方模糊命中，客戶端篩選要自己擋）。"""
    rows = [_list_row(i, n) for i, n in enumerate(numbers, 1)]
    for i in range(1, len(numbers) + 1):
        site.details[f"m{i}"] = _detail(i, actors=["A1"])

    def search_page(q, page, limit=50, proxies=None):
        site.search_calls.append((q, page))
        if page != 1:
            return []
        return [r for r in rows if not strict or r["number"].upper().startswith(q.upper())][:50]

    monkeypatch.setattr(javdb_api, "api_search_page", search_page)


@pytest.mark.parametrize("target,query", [("SONE-1", "SONE-01"), ])
def test_partial_single_digit_queries_expanded_prefix(site, monkeypatch, sync_executor, pipe_sleeps, target, query):
    _page_for(site, monkeypatch, [])
    _prov().run(Kind.PARTIAL, target, Window(0, 0))
    assert site.search_calls == [(query, 1)]


