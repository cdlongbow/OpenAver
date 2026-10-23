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
from core.search_providers import relay
from core.search_providers import javdb as jp
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
    monkeypatch.setattr(jp, "_sleep", lambda s: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(JavDBProvider, "_proxies", lambda self: None)
    yield
    clear_resolve_cache()


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


# ------------------------------------------------------------------ 載入更多固定同一家（175b-F1；175d 起由請求帶的 token 釘住）
# ------------------------------------------------------------------ 鏈與換家


def test_javdb_not_found_switches_to_javbus(order, bus, dev):
    order(["javdb", "javbus"])
    bus.return_value = R("B-1")
    out = search()
    assert out.results[0]["number"] == "B-1"
    assert dev.call_count == 1 and bus.call_count == 1


def test_all_providers_failing_with_unreachable_reports_unreachable(order, bus, dev):
    order(["javdb", "javbus"])
    dev.return_value = E("maker_unreachable")
    bus.return_value = E("maker_not_found")
    assert search() == E("maker_unreachable")
    dev.return_value = E("maker_not_found")
    bus.return_value = E("maker_unreachable")
    assert search() == E("maker_unreachable")


def test_exception_at_offset_zero_switches_to_next(order, bus, dev):
    order(["javdb", "javbus"])
    dev.side_effect = RuntimeError("boom")
    bus.return_value = R("B-1")
    assert search(offset=0).results[0]["number"] == "B-1"
    assert bus.call_count == 1


def test_empty_chain_is_not_found_with_zero_requests(order, bus, dev):
    order(["javdb", "javbus"], enabled=[])
    assert search() == E("maker_not_found")
    assert bus.call_count == 0 and dev.call_count == 0


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


# ------------------------------------------------------------------ JavDBProvider.run_maker（真 provider，只 patch 傳輸）
# ------------------------------------------------------------------ 175b-T8c 膠囊列政策
@pytest.mark.parametrize(
    "ids,enabled,use_map",
    [
        (["javbus"], True, True),
        ([], False, False),
    ],
)
def test_capsule_policy_matrix(order, ids, enabled, use_map):
    order(["javdb", "javbus"], enabled=ids)
    p = relay.maker_capsule_policy()
    assert p.enabled is enabled and p.use_not_found_map is use_map


@pytest.mark.parametrize("ids", [["dmm"], ])
def test_capsule_policy_counts_dmm(order, ids):
    """175c-T9：DMM 宣告 MAKER 後也算鏈上做得到片商的一家（膠囊列啟用），且鏈不是恰為 javbus ⇒ 不信 JavBus 的「沒有這家」對照表。
    〔只開 DMM 的使用者進搜尋頁空狀態 → 若 DMM 沒宣告 MAKER，片商膠囊列整排停用；預設順序（DMM 排第一）下使用者在
    JavBus 對照表標「沒有」的片商，膠囊不再被藏（plan 殘留 14）〕"""
    order(["dmm", "javdb", "javbus"], enabled=ids)
    p = relay.maker_capsule_policy()
    assert p.enabled is True and p.use_not_found_map is False
