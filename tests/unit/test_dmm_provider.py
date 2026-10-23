"""DMMProvider（175a-T5）：列表＋逐部補詳情的行為。合成資料，不連外。"""
import concurrent.futures as cf
import copy
from unittest.mock import patch

import pytest

from core.scrapers.dmm import DMMScraper, ListResult
from core.scrapers.models import Video
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import Kind, Window

# 175c-T8：DMM 列表多一次 fetch_facts（官方番號）；這些案只 patch list_contents，facts 換成 {}＝推導番號退路＝今天的斷言值
pytestmark = pytest.mark.usefixtures("no_dmm_facts")


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


def _rows(n=2):
    """合成 list_contents rows：真格式 cid（假 cid 推不出 SONE-001）。"""
    return [{"id": f"sone{i:05d}", "title": "shallow"} for i in range(1, n + 1)]


def _num(cid):
    """測試用的 cid → 預期番號（字面對照，不呼叫 _content_id_to_number）。"""
    return {"sone00001": "SONE-001", "sone00002": "SONE-002", "sone00003": "SONE-003"}[cid]


def _shallow(cid):
    """provider 為該列組出的 shallow 卡的預期值（字面構造）。"""
    return Video(number=_num(cid), title="shallow", source="dmm",
                 detail_url=f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={cid}/")


def _enriched(number):
    return _video(number, title="full", maker="Maker", series="S", director="D")


def _run(rows, fetch, w=Window(0, 20), status_cb=None, result_cb=None, **kw):
    with patch.object(DMMScraper, "list_contents", return_value=ListResult(rows, None, False)) as search, \
         patch.object(DMMScraper, "_fetch_by_id", **fetch) as fetched:
        out = DMMProvider(DMMScraper()).run(Kind.KEYWORD, "q", w, status_callback=status_cb,
                                            result_callback=result_cb, **kw)
    return out, search, fetched


def test_dmm_seed_then_items_in_slot_order():
    rows = _rows(3)
    events = []
    out, _, _ = _run(rows, {"side_effect": lambda cid: _enriched(_num(cid))},
                     result_cb=lambda s, d: events.append((s, copy.deepcopy(d))))
    assert [e for e in events if e[0] == -1] == [(-1, ["SONE-001", "SONE-002", "SONE-003"])]
    assert events[0][0] == -1
    assert sorted(e[0] for e in events[1:]) == [0, 1, 2]
    assert [c["number"] for c in out] == ["SONE-001", "SONE-002", "SONE-003"]
    assert all(c["title"] == "full" for c in out)


def test_dmm_search_passes_offset_for_load_more():
    out, search, _ = _run(_rows(1), {"return_value": _enriched("SONE-001")}, w=Window(20, 15))
    search.assert_called_once_with("q", limit=15, offset=20)
    assert len(out) == 1


@pytest.mark.parametrize("failure", [
    {"return_value": None},
    {"side_effect": RuntimeError("boom")},
])
def test_dmm_detail_failure_falls_back_to_shallow_card(failure):
    rows = _rows(2)
    ok = _enriched("SONE-002")

    def fetch(cid):
        if cid == "sone00001":
            if "side_effect" in failure:
                raise failure["side_effect"]
            return failure["return_value"]
        return ok

    seen = []
    out, _, _ = _run(rows, {"side_effect": fetch}, result_cb=lambda s, d: seen.append(s))
    assert out[0] == {**_shallow("sone00001").to_legacy_dict(), "_source": "dmm"}
    assert out[1]["title"] == "full"
    assert seen == [-1, 0, 1]


