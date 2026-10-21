"""DMMProvider（175a-T5）：列表＋逐部補詳情的行為。合成資料，不連外。"""
import concurrent.futures as cf
import copy
import time
from unittest.mock import patch

import pytest

from core.scrapers.dmm import DMMScraper
from core.scrapers.errors import SourceUnreachable
from core.scrapers.models import Video
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import Kind, Window


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
def sync_env(monkeypatch):
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)


def _video(number, title="shallow", **kw):
    return Video(number=number, title=title, source="dmm", date="2024-01-01", **kw)


def _pairs(n=2):
    return [(f"cid{i}", _video(f"SONE-{i:03d}")) for i in range(1, n + 1)]


def _enriched(number):
    return _video(number, title="full", maker="Maker", series="S", director="D")


def _run(pairs, fetch, w=Window(0, 20), status_cb=None, result_cb=None, **kw):
    with patch.object(DMMScraper, "search_by_keyword_with_ids", return_value=pairs) as search, \
         patch.object(DMMScraper, "_fetch_by_id", **fetch) as fetched:
        out = DMMProvider(DMMScraper()).run(Kind.KEYWORD, "q", w, status_callback=status_cb,
                                            result_callback=result_cb, **kw)
    return out, search, fetched


def test_dmm_seed_then_items_in_slot_order():
    pairs = _pairs(3)
    events = []
    out, _, _ = _run(pairs, {"side_effect": lambda cid: _enriched(dict(pairs)[cid].number)},
                     result_cb=lambda s, d: events.append((s, copy.deepcopy(d))))
    assert [e for e in events if e[0] == -1] == [(-1, ["SONE-001", "SONE-002", "SONE-003"])]
    assert events[0][0] == -1
    assert sorted(e[0] for e in events[1:]) == [0, 1, 2]
    assert [c["number"] for c in out] == ["SONE-001", "SONE-002", "SONE-003"]
    assert all(c["title"] == "full" for c in out)


def test_dmm_search_passes_offset_for_load_more():
    out, search, _ = _run(_pairs(1), {"return_value": _enriched("SONE-001")}, w=Window(20, 15))
    search.assert_called_once_with("q", limit=15, offset=20)
    assert len(out) == 1


@pytest.mark.parametrize("failure", [
    {"return_value": None},
    {"side_effect": ValueError("bad")},
    {"side_effect": SourceUnreachable("down")},
    {"side_effect": RuntimeError("boom")},
])
def test_dmm_detail_failure_falls_back_to_shallow_card(failure):
    pairs = _pairs(2)
    ok = _enriched("SONE-002")

    def fetch(cid):
        if cid == "cid1":
            if "side_effect" in failure:
                raise failure["side_effect"]
            return failure["return_value"]
        return ok

    seen = []
    out, _, _ = _run(pairs, {"side_effect": fetch}, result_cb=lambda s, d: seen.append(s))
    assert out[0] == {**pairs[0][1].to_legacy_dict(), "_source": "dmm"}
    assert out[1]["title"] == "full"
    assert seen == [-1, 0, 1]


def test_dmm_progressive_adds_no_inter_request_delay(monkeypatch):
    rec = []
    monkeypatch.setattr(time, "sleep", lambda s: rec.append(s))
    _run(_pairs(3), {"return_value": _enriched("SONE-001")})
    assert rec and all(s == 0 for s in rec)


def test_dmm_source_stamped_after_callbacks():
    payloads = []
    out, _, _ = _run(_pairs(2), {"return_value": _enriched("SONE-001")},
                     result_cb=lambda s, d: payloads.append(copy.deepcopy(d)))
    assert all(c["_source"] == "dmm" for c in out)
    item_payloads = [p for p in payloads if isinstance(p, dict)]
    assert item_payloads and all("_source" not in p for p in item_payloads)


def test_dmm_done_status_sent_once_and_no_result_callback_ok():
    statuses = []
    out, _, _ = _run(_pairs(2), {"return_value": _enriched("SONE-001")},
                     status_cb=lambda k, v: statuses.append((k, v)))
    assert statuses == [("dmm", "searching"), ("done", "found:2")]
    assert len(out) == 2


def test_dmm_emits_searching_status_before_search():
    order = []
    pairs = _pairs(1)
    with patch.object(DMMScraper, "search_by_keyword_with_ids",
                      side_effect=lambda *a, **k: order.append("search") or pairs), \
         patch.object(DMMScraper, "_fetch_by_id", return_value=_enriched("SONE-001")):
        DMMProvider(DMMScraper()).run(Kind.KEYWORD, "q", Window(0, 20),
                                      status_callback=lambda k, v: order.append((k, v)))
    assert order[:2] == [("dmm", "searching"), "search"]
    assert order[-1] == ("done", "found:1")


@pytest.mark.parametrize("case", ["empty", "wrong_kind", "discovery"])
def test_dmm_empty_wrong_kind_and_discovery(case):
    calls = []
    kw = {}
    kind = Kind.KEYWORD
    pairs = [] if case == "empty" else _pairs(1)
    if case == "wrong_kind":
        kind = Kind.CODE
    if case == "discovery":
        kw["discovery_only"] = True
    with patch.object(DMMScraper, "search_by_keyword_with_ids", return_value=pairs) as search, \
         patch.object(DMMScraper, "_fetch_by_id", return_value=_enriched("SONE-001")):
        p = DMMProvider(DMMScraper())
        args = (kind, "q", Window(0, 20))
        cbs = dict(status_callback=lambda *a: calls.append(a), result_callback=lambda *a: calls.append(a))
        if case == "wrong_kind":
            with pytest.raises(ValueError):
                p.run(*args, **cbs)
            return
        assert p.run(*args, **cbs, **kw) == []
    # 查無：只有「正在查 DMM」一個進度事件，沒有 done／seed；discovery 與例外情形則完全無事件
    assert calls == ([("dmm", "searching")] if case == "empty" else [])
    if case == "discovery":
        search.assert_not_called()
