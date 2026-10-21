"""175b-T8b：片商接力 relay.search_maker＋JavDBProvider.run_maker＋search_maker_latest shim。

鏈順序與開關 patch 使用端 core.scraper.*（BE-TEST-01／02）；JavDB 傳輸 patch javdb_api.<name>；
JavBus 一律 patch JavBusProvider.run_maker 並量 call_count（BE-TEST-46）。不連外、不存站方檔（BE-TEST-43）。
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from unittest.mock import MagicMock, patch

import pytest

from core.database import init_db, maker_javbus_map
from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import javdb as jp
from core.search_providers import relay
from core.search_providers.javbus import JavBusProvider
from core.search_providers.javdb import JavDBProvider, clear_resolve_cache
from core.search_providers.types import MakerSearchResult

KW = dict(titles=[], today="2026-10-21")
ARGS = ("mk", "片商", ["片商"])


def R(*nums):
    return MakerSearchResult([{"number": n, "title": n} for n in nums], False, None)


def E(code):
    return MakerSearchResult([], False, code)


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


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    clear_resolve_cache()
    relay._reset_maker_answerers()
    monkeypatch.setattr(jp, "_sleep", lambda s: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(JavDBProvider, "_proxies", lambda self: None)
    yield
    clear_resolve_cache()
    relay._reset_maker_answerers()


@pytest.fixture
def order(monkeypatch):
    def setup(ids, enabled=None):
        on = set(ids) if enabled is None else set(enabled)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(ids))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)

    return setup


@pytest.fixture
def bus():
    with patch.object(JavBusProvider, "run_maker", autospec=True) as m:
        m.return_value = E("maker_not_found")
        yield m


@pytest.fixture
def dev():
    with patch.object(JavDBProvider, "run_maker", autospec=True) as m:
        m.return_value = E("maker_not_found")
        yield m


def search(offset=0, **kw):
    return relay.search_maker(*ARGS, offset, **KW, **kw)


# ------------------------------------------------------------------ 載入更多固定同一家（175b-F1）
def _twenty(prefix):
    return R(*[f"{prefix}-{i}" for i in range(20)])


def test_load_more_stays_with_fallback_provider_when_first_choice_still_blocked(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_unreachable")
    bus.return_value = _twenty("B")
    assert len(search(offset=0, limit=20).results) == 20
    dev.reset_mock()
    out = search(offset=20, limit=20)
    assert dev.call_count == 0
    assert bus.call_count == 2 and len(out.results) == 20


def test_load_more_stays_with_fallback_provider_after_first_choice_recovers(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_unreachable")
    bus.return_value = _twenty("B")
    search(offset=0, limit=20)
    dev.reset_mock()
    dev.return_value = _twenty("A")
    out = search(offset=20, limit=20)
    assert dev.call_count == 0
    assert out.results[0]["number"] == "B-0"


def test_load_more_ends_when_answering_provider_fails(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = _twenty("A")
    search(offset=0, limit=20)
    dev.return_value = E("maker_unreachable")
    bus.return_value = _twenty("B")
    assert search(offset=20, limit=20) == E("maker_unreachable")
    assert bus.call_count == 0


def test_load_more_without_record_keeps_current_behavior(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_not_found")
    bus.return_value = R("B-1")
    out = search(offset=20, limit=20)
    assert out.results[0]["number"] == "B-1"
    assert dev.call_count == 1 and bus.call_count == 1


def test_answering_provider_disabled_midway_ends_list(order, bus, dev):
    order(["javdb", "javbus"])
    bus.return_value = _twenty("B")
    search(offset=0, limit=20)
    dev.reset_mock()
    order(["javdb", "javbus"], enabled=["javdb"])
    dev.return_value = _twenty("A")
    assert search(offset=20, limit=20) == E("maker_unreachable")
    assert dev.call_count == 0


def test_typed_and_capsule_lists_are_recorded_separately(order, bus, dev):
    order(["javdb", "javbus"])

    def dev_side(self, key, label, spellings, offset, *, limit=None, **kw):
        return _twenty("A") if limit is None else E("maker_not_found")

    dev.side_effect = dev_side
    bus.return_value = _twenty("B")
    search(offset=0, limit=20)  # javdb not_found -> javbus
    search(offset=0, limit=None)  # javdb answers
    dev.reset_mock()
    bus.reset_mock()
    typed = search(offset=20, limit=20)
    assert dev.call_count == 0 and bus.call_count == 1 and typed.results[0]["number"] == "B-0"
    dev.reset_mock()
    bus.reset_mock()
    capsule = search(offset=30, limit=None)
    assert bus.call_count == 0 and dev.call_count == 1 and capsule.results[0]["number"] == "A-0"


# ------------------------------------------------------------------ 鏈與換家
def test_first_non_empty_wins_and_later_not_asked(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = R("A-1")
    assert search().results[0]["number"] == "A-1"
    assert bus.call_count == 0


def test_javdb_not_found_switches_to_javbus(order, bus, dev):
    order(["javdb", "javbus"])
    bus.return_value = R("B-1")
    out = search()
    assert out.results[0]["number"] == "B-1"
    assert dev.call_count == 1 and bus.call_count == 1


def test_both_not_found_reports_not_found(order, bus, dev):
    order(["javdb", "javbus"])
    assert search() == E("maker_not_found")


def test_all_providers_failing_with_unreachable_reports_unreachable(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_unreachable")
    bus.return_value = E("maker_not_found")
    assert search() == E("maker_unreachable")
    dev.return_value = E("maker_not_found")
    bus.return_value = E("maker_unreachable")
    assert search() == E("maker_unreachable")


def test_all_no_sample_reports_no_sample_mixed_reports_not_found(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_no_sample")
    bus.return_value = E("maker_no_sample")
    assert search() == E("maker_no_sample")
    dev.return_value = E("maker_not_found")
    assert search() == E("maker_not_found")


def test_maker_empty_at_list_end_does_not_fall_through_to_next_provider(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_empty")
    bus.return_value = R("B-1")
    out = search(offset=30)
    assert out == E("maker_empty")
    assert bus.call_count == 0


def test_listed_but_no_cards_without_error_code_is_terminal(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E(None)
    assert search() == E(None)
    assert bus.call_count == 0


def test_maker_empty_is_terminal_at_offset_zero_too(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_empty")
    assert search(offset=0) == E("maker_empty")
    assert bus.call_count == 0


def test_unreachable_result_at_offset_gt_zero_is_terminal(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_unreachable")
    assert search(offset=30) == E("maker_unreachable")
    assert bus.call_count == 0


def test_exception_at_offset_gt_zero_is_terminal_unreachable(order, bus, dev):
    order(["javdb", "javbus"])
    dev.side_effect = SourceBlocked("cf")
    assert search(offset=30) == E("maker_unreachable")
    assert bus.call_count == 0


def test_exception_at_offset_zero_switches_to_next(order, bus, dev):
    order(["javdb", "javbus"])
    dev.side_effect = RuntimeError("boom")
    bus.return_value = R("B-1")
    assert search(offset=0).results[0]["number"] == "B-1"
    assert bus.call_count == 1


def test_exception_everywhere_at_offset_zero_reports_unreachable(order, bus, dev):
    order(["javdb", "javbus"])
    dev.side_effect = RuntimeError("boom")
    bus.side_effect = SourceUnreachable("down")
    assert search() == E("maker_unreachable")


def test_empty_chain_is_not_found_with_zero_requests(order, bus, dev):
    order(["javdb", "javbus"], enabled=[])
    assert search() == E("maker_not_found")
    assert bus.call_count == 0 and dev.call_count == 0


def test_limit_and_args_forwarded_to_provider(order, bus, dev):
    order(["javdb"])
    dev.return_value = R("A-1")
    search(offset=20, limit=20)
    kwargs = dev.call_args.kwargs
    assert kwargs["limit"] == 20 and kwargs["titles"] == [] and kwargs["today"] == "2026-10-21"
    assert dev.call_args.args[1:5] == ("mk", "片商", ["片商"], 20)


def test_seed_callback_goes_to_first_provider_only_once(order, bus, dev):
    order(["javdb", "javbus"])
    cbs = []

    def javdb_run(self, *a, result_callback=None, **kw):
        cbs.append(("javdb", result_callback))
        return E("maker_not_found")

    def javbus_run(self, *a, result_callback=None, **kw):
        cbs.append(("javbus", result_callback))
        return R("B-1")

    dev.side_effect = javdb_run
    bus.side_effect = javbus_run
    search(result_callback=MagicMock())
    assert cbs[0][1] is not None
    assert cbs[1][1] is None  # JavDB fallback_streaming=False ⇒ 後備拿不到；JavBus 排第二亦同


# ------------------------------------------------------------------ oracle 1／2（含 shim 入口）
@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    return db


def test_javdb_first_with_javbus_off_never_touches_javbus_or_map(order, bus, dev, tmp_db):
    """(oracle 1) 順序 [javdb, javbus]、JavBus 關：JavDB 回答、JavBus 0 次、maker_javbus_map 無新增列。"""
    from core.scraper import search_maker_latest

    order(["javdb", "javbus"], enabled=["javdb"])
    dev.return_value = R("A-1")
    with patch("core.scraper.resolve_maker_studio") as rms:
        out = search_maker_latest(*ARGS, 0, **KW, db_path=tmp_db)
    assert out.results[0]["number"] == "A-1"
    assert bus.call_count == 0 and rms.call_count == 0
    assert maker_javbus_map.get_mapping("mk", db_path=tmp_db) is None


def test_javdb_off_javbus_answers_with_zero_javdb_transport(order, monkeypatch, tmp_db):
    """(oracle 2) JavDB 關：JavBus 回答（resolve_maker_studio 為 found），JavDB 傳輸 0 次。"""
    from core.maker_latest import Resolution
    from core.scraper import search_maker_latest
    from core.scrapers.javbus import JavBusScraper

    order(["javdb", "javbus"], enabled=["javbus"])
    transport = MagicMock()
    for name in ("api_search_typed", "api_list_tags", "api_search_page", "api_movie_detail"):
        monkeypatch.setattr(javdb_api, name, transport)
    with patch("core.scraper.resolve_maker_studio", return_value=Resolution("found", "censored", "7q")), \
         patch.object(JavBusScraper, "get_ids_from_studio", side_effect=lambda ref, page: ["MKR-001"]), \
         patch("core.scraper.search_jav", side_effect=lambda n, source=None, *a, **k: {"number": n, "title": n}):
        out = search_maker_latest(*ARGS, 0, **KW, db_path=tmp_db)
    assert [r["number"] for r in out.results] == ["MKR-001"]
    assert transport.call_count == 0


def test_capsule_shim_follows_chain_and_switches(order, bus, dev):
    from core.scraper import search_maker_latest

    order(["javdb"], enabled=["javdb"])
    dev.return_value = R("A-1")
    out = search_maker_latest(*ARGS, 0, **KW)
    assert out.results[0]["number"] == "A-1"
    assert bus.call_count == 0  # 設定頁沒開 JavBus ⇒ 膠囊路徑不得打 JavBus
    order(["javdb", "javbus"])
    dev.return_value = E("maker_not_found")
    bus.return_value = R("B-1")
    out = search_maker_latest(*ARGS, 0, **KW)
    assert out.results[0]["number"] == "B-1"


# ------------------------------------------------------------------ JavDBProvider.run_maker（真 provider，只 patch 傳輸）
class Site:
    def __init__(self):
        self.typed = {}
        self.pages = {}
        self.details = {}
        self.calls = []
        self.typed_exc = None
        self.list_exc = None

    def search_typed(self, t, q, proxies=None):
        self.calls.append(("typed", t, q))
        if self.typed_exc is not None:
            raise self.typed_exc
        return self.typed.get((t, q), [])

    def list_tags(self, filter_by, page, limit=50, proxies=None):
        self.calls.append(("list", filter_by, page))
        if self.list_exc is not None:
            raise self.list_exc
        return self.pages.get((filter_by, page), [])

    def movie_detail(self, movie_id, proxies=None):
        self.calls.append(("detail", movie_id))
        d = self.details.get(movie_id)
        if d is None:
            raise SourceUnreachable("no detail")
        return d


@pytest.fixture
def site(monkeypatch):
    s = Site()
    monkeypatch.setattr(javdb_api, "api_search_typed", s.search_typed)
    monkeypatch.setattr(javdb_api, "api_list_tags", s.list_tags)
    monkeypatch.setattr(javdb_api, "api_movie_detail", s.movie_detail)
    return s


def _maker_site(site, maker_id_in_detail="M1", n=3):
    site.typed[("maker", "片商")] = [
        {"id": "M1", "name": "片商", "name_zht": "", "other_name": "", "videos_count": 99, "type": 0}]
    site.pages[("0:m:M1", 1)] = [
        {"id": f"m{i}", "number": f"AAA-{i:03d}", "title": f"t{i}", "origin_title": f"jt{i}",
         "cover_url": "http://c/x.jpg", "release_date": f"2026-0{i}-01"} for i in range(1, n + 1)]
    for i in range(1, n + 1):
        site.details[f"m{i}"] = {"id": f"m{i}", "title": f"jt{i}", "release_date": f"2026-0{i}-01",
                                 "cover_url": "http://c/x.jpg", "maker_id": maker_id_in_detail}


def _run(**kw):
    return JavDBProvider().run_maker(*ARGS, 0, **KW, **kw)


def test_javdb_run_maker_happy_path_sorted_with_source_and_status(site):
    _maker_site(site)
    events = []
    out = _run(status_callback=lambda a, b: events.append((a, b)))
    assert out.error_code is None
    assert [c["number"] for c in out.results] == ["AAA-003", "AAA-002", "AAA-001"]
    assert {c["_source"] for c in out.results} == {"javdb"}
    assert out.has_more is False
    assert events[0] == ("javdb", "searching") and events[-1] == ("done", "found:3")
    assert ("list", "0:m:M1", 1) in site.calls


def test_javdb_run_maker_resolve_none_is_not_found(site):
    assert _run() == E("maker_not_found")
    assert not [c for c in site.calls if c[0] in ("list", "detail")]


def test_javdb_run_maker_resolve_error_is_unreachable_not_not_found(site):
    site.typed_exc = SourceBlocked("cf")
    assert _run() == E("maker_unreachable")


def test_javdb_run_maker_list_error_is_unreachable(site):
    _maker_site(site)
    site.list_exc = SourceUnreachable("down")
    assert _run() == E("maker_unreachable")


def test_javdb_run_maker_empty_listing_is_maker_empty(site):
    _maker_site(site)
    site.pages[("0:m:M1", 1)] = []
    assert _run() == E("maker_empty")


def test_javdb_run_maker_does_not_swallow_base_exception(site):
    site.typed_exc = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _run()


def test_javdb_maker_latest_listing_guard_rejects_unrelated_page(site, order, bus):
    """站方篩選失效回全站最新：詳情 maker id 都不是 M1 ⇒ JavDB maker_not_found、seed 0 次、換 JavBus。"""
    _maker_site(site, maker_id_in_detail="OTHER")
    order(["javdb", "javbus"])
    bus.return_value = R("B-1")
    seeds = MagicMock()
    out = search(result_callback=seeds)
    assert [r["number"] for r in out.results] == ["B-1"]
    assert bus.call_count == 1
    assert seeds.call_count == 0
    assert _run() == E("maker_not_found")


def test_javdb_run_maker_limit_none_uses_30_window(site):
    _maker_site(site)
    out = _run()
    assert out.error_code is None
    out2 = _run(limit=2)
    assert len(out2.results) <= 2


def test_default_window_is_30_and_load_more_continues_without_gap(site, order, bus):
    """45 部、日期新到舊：offset=0 預設視窗恰 30 部（第 1–30），offset=30 得第 31–45，零重複合計 45。"""
    import datetime

    order(["javdb"])
    site.typed[("maker", "片商")] = [
        {"id": "M1", "name": "片商", "name_zht": "", "other_name": "", "videos_count": 99, "type": 0}]
    day0 = datetime.date(2026, 1, 1)
    rows = []
    for i in range(1, 46):
        d = (day0 + datetime.timedelta(days=100 - i)).isoformat()
        rows.append({"id": f"m{i}", "number": f"AAA-{i:03d}", "title": f"t{i}", "origin_title": f"jt{i}",
                     "cover_url": "http://c/x.jpg", "release_date": d})
        site.details[f"m{i}"] = {"id": f"m{i}", "title": f"jt{i}", "release_date": d,
                                 "cover_url": "http://c/x.jpg", "maker_id": "M1"}
    site.pages[("0:m:M1", 1)] = rows
    first = search(offset=0)
    second = search(offset=30)
    n1 = [r["number"] for r in first.results]
    n2 = [r["number"] for r in second.results]
    assert n1 == [f"AAA-{i:03d}" for i in range(1, 31)]
    assert n2 == [f"AAA-{i:03d}" for i in range(31, 46)]
    assert not set(n1) & set(n2) and len(n1) + len(n2) == 45
    assert bus.call_count == 0


# ------------------------------------------------------------------ 175b-T8c 膠囊列政策
@pytest.mark.parametrize(
    "ids,enabled,use_map",
    [
        (["javbus"], True, True),
        (["javdb"], True, False),
        (["javdb", "javbus"], True, False),
        ([], False, False),
    ],
)
def test_capsule_policy_matrix(order, ids, enabled, use_map):
    order(["javdb", "javbus"], enabled=ids)
    p = relay.maker_capsule_policy()
    assert p.enabled is enabled and p.use_not_found_map is use_map
