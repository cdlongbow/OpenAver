"""DMMProvider（175a-T5）：列表＋逐部補詳情的行為。合成資料，不連外。"""
import concurrent.futures as cf
import copy
import time
from unittest.mock import MagicMock, patch

import pytest

from core.scrapers.dmm import DMMScraper, ListResult
from core.scrapers.errors import SourceUnreachable
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
    {"side_effect": ValueError("bad")},
    {"side_effect": SourceUnreachable("down")},
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


def test_dmm_progressive_adds_no_inter_request_delay(monkeypatch):
    rec = []
    monkeypatch.setattr(time, "sleep", lambda s: rec.append(s))
    _run(_rows(3), {"return_value": _enriched("SONE-001")})
    assert rec and all(s == 0 for s in rec)


def test_dmm_source_stamped_after_callbacks():
    payloads = []
    out, _, _ = _run(_rows(2), {"return_value": _enriched("SONE-001")},
                     result_cb=lambda s, d: payloads.append(copy.deepcopy(d)))
    assert all(c["_source"] == "dmm" for c in out)
    item_payloads = [p for p in payloads if isinstance(p, dict)]
    assert item_payloads and all("_source" not in p for p in item_payloads)


def test_dmm_done_status_sent_once_and_no_result_callback_ok():
    statuses = []
    out, _, _ = _run(_rows(2), {"return_value": _enriched("SONE-001")},
                     status_cb=lambda k, v: statuses.append((k, v)))
    assert statuses == [("dmm", "searching"), ("done", "found:2")]
    assert len(out) == 2


def test_dmm_emits_searching_status_before_search():
    order = []
    rows = _rows(1)
    with patch.object(DMMScraper, "list_contents",
                      side_effect=lambda *a, **k: order.append("search") or ListResult(rows, None, False)), \
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
    rows = [] if case == "empty" else _rows(1)
    if case == "wrong_kind":
        kind = Kind.CODE
    if case == "discovery":
        kw["discovery_only"] = True
    with patch.object(DMMScraper, "list_contents", return_value=ListResult(rows, None, False)) as search, \
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


# ─── 175c-T6：列表轉換（rows → WorkItem／shallow 卡）production 向量 ──────────────
# 期望值是刪除舊的關鍵字列表函式之前，用它對同一份 JSON 實跑抄下的字面常數
# （不用 _content_id_to_number 現算：同源恆真）。13dsvr／h_／55t 的「錯」番號是現行行為，官方番號是 T8 的事。
_VECTOR_ROWS = [
    {"id": "13dsvr01774", "title": "VR タイトル A", "packageImage": {"largeUrl": "https://img.invalid/13dsvr01774pl.jpg"},
     "deliveryStartAt": "2024-05-01T00:00:00Z", "releaseStatus": "RELEASED",
     "actresses": [{"id": "1093154", "name": "あかね麗（二階堂麗）"}, {"id": "1030262", "name": "三上悠亜"}],
     "maker": {"id": "3152", "name": "エスワン ナンバーワンスタイル"}},
    {"id": "h_113id00057", "title": "タイトル B", "packageImage": {"largeUrl": "https://img.invalid/h_113id00057pl.jpg"},
     "deliveryStartAt": "2023-01-02T00:00:00Z", "releaseStatus": "RELEASED",
     "actresses": [{"id": "2001", "name": "テスト女優"}],
     "maker": {"id": "1509", "name": "ムーディーズ"}},
    {"title": "id 欠落列", "packageImage": {"largeUrl": "https://img.invalid/noid.jpg"},
     "actresses": [{"id": "3", "name": "丟棄女優"}], "maker": {"id": "9", "name": "丟棄片商"}},
    {"id": "sone00205", "title": "最小列", "packageImage": None, "actresses": None, "maker": None},
    {"id": "55t28103", "title": "數字前綴", "packageImage": {"largeUrl": "https://img.invalid/55t28103pl.jpg"},
     "deliveryStartAt": "2022-03-04T00:00:00Z", "releaseStatus": "PRE_ORDER",
     "actresses": [{"id": "4001", "name": "女優甲（舊名）"}, {"id": "4002", "name": ""}],
     "maker": {"id": "1227", "name": "アタッカーズ"}},
]

# (content_id, number, title, cover_url, date, 女優名, maker, source, detail_url)
_VECTOR_EXPECTED = [
    ('13dsvr01774', 'DSVR-1774', 'VR タイトル A', 'https://img.invalid/13dsvr01774pl.jpg', '',
     ['あかね麗', '三上悠亜'], 'エスワン ナンバーワンスタイル', 'dmm',
     'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=13dsvr01774/'),
    ('h_113id00057', 'h_113id00057', 'タイトル B', 'https://img.invalid/h_113id00057pl.jpg', '',
     ['テスト女優'], 'ムーディーズ', 'dmm',
     'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=h_113id00057/'),
    ('sone00205', 'SONE-205', '最小列', '', '', [], '', 'dmm',
     'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=sone00205/'),
    ('55t28103', 'T-28103', '數字前綴', 'https://img.invalid/55t28103pl.jpg', '',
     ['女優甲'], 'アタッカーズ', 'dmm',
     'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=55t28103/'),
]


def _json_resp(status=200, data=None):
    r = MagicMock()
    r.status_code = status
    r.json = lambda: data
    return r


def _provider_with_post(response):
    scraper = DMMScraper()
    return DMMProvider(scraper), patch.object(scraper._session, "post", return_value=response)


def test_search_keyword_row_conversion_matches_pre_deletion_vector():
    """使用者搜 あかね麗：卡片女優欄是『あかね麗』而不是『あかね麗（二階堂麗）』；缺 id 列丟棄、缺 maker／女優列照收。"""
    body = {"data": {"legacySearchPPV": {"result": {
        "pageInfo": {"totalCount": 5, "hasNext": False}, "contents": _VECTOR_ROWS}}}}
    provider, post_patch = _provider_with_post(_json_resp(200, body))
    with post_patch as post:
        page = provider.search_keyword("キーワード", Window(0, 40))
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["variables"] == {
        "limit": 40, "offset": 0, "sort": "RELEASE_DATE", "queryWord": "キーワード"}
    got = [(it.ref[0], it.number, it.title, it.cover_url, it.date,
            [a.name for a in it.ref[1].actresses], it.ref[1].maker, it.source, it.ref[1].detail_url)
           for it in page.items]
    assert got == _VECTOR_EXPECTED
    # WorkItem 欄位與 shallow 卡一致、actors 維持 None
    assert all(it.actors is None and it.ref[1].number == it.number and it.ref[1].title == it.title
               and it.ref[1].source == "dmm" for it in page.items)
    assert page.has_next is False and page.total == 5  # T8：Page.has_next／total 取自 pageInfo


def test_search_keyword_has_next_and_total_come_from_page_info():
    """T8（CD-175c-7）：has_next／total 取自 pageInfo，不再用『筆數 ≥ 視窗』猜（缺 id 的丟掉後恆為 4 部）。"""
    for has_next, window_limit in ((True, 5), (False, 4)):  # 不滿一頁而站方說還有、整頁滿而站方說沒有
        body = {"data": {"legacySearchPPV": {"result": {
            "pageInfo": {"totalCount": 999, "hasNext": has_next}, "contents": _VECTOR_ROWS}}}}
        provider, post_patch = _provider_with_post(_json_resp(200, body))
        with post_patch:
            page = provider.search_keyword("x", Window(0, window_limit))
        assert page.has_next is has_next and page.total == 999
