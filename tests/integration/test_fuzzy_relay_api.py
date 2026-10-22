"""test_fuzzy_relay_api.py — 路由接上片商搜尋（175b-T9）。

片商名單與 smart_search 皆在使用端以合成值替身，不連外、不碰真實片庫。
"""
from unittest.mock import patch, MagicMock

from core.maker_names import maker_key_of

LIMIT = 20


def _cards(n):
    return [{"number": f"SOD-{i:03d}", "title": f"t{i}", "actors": [], "_mode": "maker"} for i in range(n)]


def _smart(n, seen, more=None):
    def fake(q, limit=20, offset=0, status_callback=None, result_callback=None, **kwargs):
        seen.append(kwargs)
        if more is not None and kwargs.get("meta") is not None:
            kwargs["meta"]["has_more"] = more
        return _cards(n)
    return fake


def _rest_maker(client, n, more):
    with patch("web.routers.search.smart_search", side_effect=_smart(n, [], more)):
        return client.get("/api/search", params={"q": "SOD", "limit": LIMIT}).json()


def test_rest_typed_maker_uses_provider_has_more_when_page_is_short(client, monkeypatch):
    """這頁有 1 部詳情失敗只剩 19 張，來源說還有 → 「載入更多」不能消失"""
    _known(monkeypatch)
    body = _rest_maker(client, LIMIT - 1, True)
    assert body["mode"] == "maker" and body["has_more"] is True


def test_rest_typed_maker_last_full_page_without_more_is_false(client, monkeypatch):
    """最後一頁剛好 20 部、來源說沒了 → 不再多一顆空的「載入更多」"""
    _known(monkeypatch)
    assert _rest_maker(client, LIMIT, False)["has_more"] is False


def _stream_more(client, parse_sse_events, n, more):
    with patch("web.routers.search.smart_search", side_effect=_smart(n, [], more)):
        r = client.get("/api/search/stream", params={"q": "SOD", "limit": LIMIT})
    return _result(parse_sse_events(r.text))


def test_stream_typed_maker_uses_provider_has_more_when_page_is_short(client, parse_sse_events, monkeypatch):
    _known(monkeypatch)
    assert _stream_more(client, parse_sse_events, LIMIT - 1, True)["has_more"] is True


def test_stream_typed_maker_last_full_page_without_more_is_false(client, parse_sse_events, monkeypatch):
    _known(monkeypatch)
    assert _stream_more(client, parse_sse_events, LIMIT, False)["has_more"] is False


def _known(monkeypatch):
    monkeypatch.setattr("web.routers.search.known_makers", lambda: frozenset({maker_key_of("SOD")}))


def _stream(client, parse_sse_events, q, n, seen):
    with patch("web.routers.search.smart_search", side_effect=_smart(n, seen)):
        r = client.get("/api/search/stream", params={"q": q, "limit": LIMIT})
    return parse_sse_events(r.text)


def _result(events):
    return next(e for e in events if e.get("type") == "result")


def test_rest_typed_maker_reports_has_more_when_page_is_full(client, monkeypatch):
    _known(monkeypatch)
    seen = []
    with patch("web.routers.search.smart_search", side_effect=_smart(LIMIT, seen)):
        body = client.get("/api/search", params={"q": "SOD", "limit": LIMIT}).json()
    assert body["mode"] == "maker" and body["has_more"] is True


def test_rest_typed_maker_short_page_has_no_more(client, monkeypatch):
    _known(monkeypatch)
    with patch("web.routers.search.smart_search", side_effect=_smart(5, [])):
        body = client.get("/api/search", params={"q": "SOD", "limit": LIMIT}).json()
    assert body["mode"] == "maker" and body["has_more"] is False


def test_rest_auto_passes_resolve_makers_to_smart_search(client, monkeypatch):
    _known(monkeypatch)
    seen = []
    with patch("web.routers.search.smart_search", side_effect=_smart(3, seen)):
        client.get("/api/search", params={"q": "SOD", "offset": 20})
    assert seen and seen[0].get("resolve_makers") is True


def test_rest_explicit_mode_does_not_resolve_makers(client, monkeypatch):
    _known(monkeypatch)
    seen = []
    with patch("web.routers.search.smart_search", side_effect=_smart(3, seen)):
        client.get("/api/search", params={"q": "SOD", "mode": "prefix"})
    assert seen and "resolve_makers" not in seen[0]


def test_stream_typed_maker_first_event_is_maker_mode(client, parse_sse_events, monkeypatch):
    _known(monkeypatch)
    events = _stream(client, parse_sse_events, "SOD", 3, [])
    assert events[0] == {"type": "mode", "mode": "maker"}


def test_stream_typed_maker_reports_has_more_when_page_is_full(client, parse_sse_events, monkeypatch):
    _known(monkeypatch)
    assert _result(_stream(client, parse_sse_events, "SOD", LIMIT, []))["has_more"] is True
    assert _result(_stream(client, parse_sse_events, "SOD", 5, []))["has_more"] is False


def test_stream_passes_resolve_makers_to_smart_search(client, parse_sse_events, monkeypatch):
    _known(monkeypatch)
    seen = []
    _stream(client, parse_sse_events, "SOD", 3, seen)
    assert seen and seen[0].get("resolve_makers") is True


def test_stream_full_number_stays_exact_even_if_prefix_is_a_known_maker(client, parse_sse_events, monkeypatch):
    """R21：完整番號先判 exact，不被片商名單改判"""
    monkeypatch.setattr("web.routers.search.known_makers", lambda: frozenset({maker_key_of("SSIS")}))
    events = _stream(client, parse_sse_events, "SSIS-816", 1, [])
    assert events[0]["mode"] == "exact"


def test_batch_search_does_not_resolve_makers(client):
    seen = []

    def fake(q, *a, **kw):
        seen.append(kw)
        return []

    with patch("web.routers.search.smart_search", side_effect=fake):
        client.post("/api/batch-search", json={"numbers": ["SSIS-816"]})
    assert seen and all("resolve_makers" not in kw for kw in seen)


# ---------------------------------------------------------------- 175c-T9：DMM 經真 smart_search→relay.search_maker→真 DMMProvider.run_maker
#
# 與上面的案相反：這三組**不** patch smart_search／search_maker／relay，鏈固定只有 dmm，只 patch DMM 傳輸（類別層）與
# 使用端的名單／片庫／tmp DB，否則「由 DMM 回答」沒被測到。合成資料全為檔內字面，不連外、不存站方檔（BE-TEST-43）。
import datetime

import pytest

from core.database import init_db
from core.scrapers.dmm import DMMScraper, Facts, ListResult
from core.scrapers.models import Video
from core.search_providers import relay

_DMM_MAKER_ID = "3152"
_DMM_MAKER_NAME = "エスワン ナンバーワンスタイル"  # S1 的拼法集合內才有的 DMM 站上名稱


def _dmm_chain(monkeypatch, ids):
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ["dmm"])
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid in ids)


@pytest.fixture
def dmm_maker(monkeypatch, tmp_path):
    """鏈只有 dmm、使用端名單認得 S1、片庫空、tmp DB；回傳一個登記 DMM 傳輸罐頭的函式（登記後回呼叫紀錄）。"""
    relay._reset_maker_answerers()
    _dmm_chain(monkeypatch, {"dmm"})
    known = lambda: frozenset({maker_key_of("S1")})  # noqa: E731
    monkeypatch.setattr("core.maker_names.known_makers", known)
    monkeypatch.setattr("web.routers.search.known_makers", known)
    monkeypatch.setattr("core.scraper._library_title_list", lambda db_path: [])
    monkeypatch.setattr("core.scraper.is_uncensored_route", lambda *a, **kw: False)
    db = tmp_path / "t.db"
    monkeypatch.setattr("core.database.get_db_path", lambda: db)

    def install(n, has_next):
        listing = [(f"sone{i:05d}", f"SONE-{i:03d}") for i in range(300, 300 + n)]
        calls = {"probe": [], "list": [], "facts": []}

        def list_contents(scraper, query_word=None, filter=None, *, limit, offset):
            if filter is None:
                calls["probe"].append(query_word)
                maker = {"id": _DMM_MAKER_ID, "name": _DMM_MAKER_NAME}
                return ListResult([{"id": "probe00001", "title": "p", "maker": maker}], 1, False)
            calls["list"].append({"filter": filter, "limit": limit, "offset": offset})
            maker = {"id": _DMM_MAKER_ID, "name": _DMM_MAKER_NAME}
            rows = [{"id": cid, "title": f"t {cid}", "maker": maker} for cid, _ in listing]
            return ListResult(rows, 999, has_next)

        def fetch_facts(scraper, content_ids):
            calls["facts"].append(tuple(content_ids))
            return {cid: Facts(official, None, None, []) for cid, official in listing if cid in content_ids}

        def fetch_by_id(scraper, content_id):
            return Video(number=dict(listing)[content_id], title=f"full {content_id}", source="dmm")

        monkeypatch.setattr(DMMScraper, "list_contents", list_contents)
        monkeypatch.setattr(DMMScraper, "fetch_facts", fetch_facts)
        monkeypatch.setattr(DMMScraper, "_fetch_by_id", fetch_by_id)
        calls["numbers"] = [official for _, official in listing]
        return calls

    yield install
    relay._reset_maker_answerers()


@pytest.mark.parametrize("n,has_next", [(5, True), (LIMIT, False)])
def test_rest_typed_maker_answered_by_dmm(client, dmm_maker, n, has_next):
    """使用者只開 DMM、在搜尋框打 S1 → 看到 DMM 用片商 ID 列出的作品；『載入更多』以站方 hasNext 為準
    （這頁只有 5 部但站方說還有 → 要有；剛好滿 20 部但站方說沒了 → 不能多一顆空按鈕）"""
    calls = dmm_maker(n, has_next)
    body = client.get("/api/search", params={"q": "S1", "limit": LIMIT}).json()
    assert body["mode"] == "maker" and body["success"] is True
    assert [c["number"] for c in body["data"]] == calls["numbers"]
    assert {c["_source"] for c in body["data"]} == {"dmm"}
    assert body["has_more"] is has_next
    assert calls["probe"] == ["S1"] and len(calls["list"]) == 1
    assert calls["list"][0]["filter"] == {"makerIds": {"ids": [{"id": _DMM_MAKER_ID}], "op": "OR"}}
    assert (calls["list"][0]["limit"], calls["list"][0]["offset"]) == (LIMIT, 0)


@pytest.mark.parametrize("n,has_next", [(5, True), (LIMIT, False)])
def test_stream_typed_maker_answered_by_dmm(client, parse_sse_events, dmm_maker, n, has_next):
    calls = dmm_maker(n, has_next)
    r = client.get("/api/search/stream", params={"q": "S1", "limit": LIMIT})
    events = parse_sse_events(r.text)
    assert events[0] == {"type": "mode", "mode": "maker"}
    types = [e["type"] for e in events]
    assert types.count("seed") == 1 and types.index("seed") < types.index("result-item")
    result = _result(events)
    assert result["mode"] == "maker" and result["success"] is True
    assert [c["number"] for c in result["data"]] == calls["numbers"]
    assert result["has_more"] is has_next
    assert len(calls["list"]) == 1


def test_capsules_enabled_when_only_dmm_is_on(client, dmm_maker, monkeypatch, tmp_path):
    """使用者只開 DMM 進搜尋頁 → 片商膠囊列可用（DMM 宣告了 MAKER）；DMM 也關了 → 整排停用。"""
    db = tmp_path / "caps.db"
    init_db(db)
    monkeypatch.setattr("web.routers.search.get_db_path", lambda: db)
    monkeypatch.setattr("web.routers.search._today", lambda: datetime.date(2026, 10, 21))
    monkeypatch.setattr("web.routers.search.get_configured_gallery_dirs", lambda cfg: (set(), {}))
    body = client.get("/api/search/maker-capsules").json()
    assert body["success"] is True and body["maker_search_enabled"] is True
    assert body["hidden_keys"] == []  # 鏈不是恰為 javbus ⇒ 不信 JavBus 的「沒有這家」對照表
    _dmm_chain(monkeypatch, set())
    body = client.get("/api/search/maker-capsules").json()
    assert body["success"] is True and body["maker_search_enabled"] is False


def test_rest_capsule_alias_answered_by_dmm(client, dmm_maker, monkeypatch, tmp_path):
    """使用者只開 DMM、點 S1 片商膠囊（前端只送片庫寫法 spellings=S1）→ 看到 DMM 用片商 ID 列出的作品。
    DMM 站上的片商名是對照表裡 S1 的別名，比對候選沒展開別名就會回「找不到」。真對照表、真路由（maker_key 路徑）。"""
    calls = dmm_maker(5, True)
    db = tmp_path / "caps-rest.db"
    monkeypatch.setattr("web.routers.search.get_db_path", lambda: db)
    monkeypatch.setattr("web.routers.search._library_titles", lambda db_path: [])
    monkeypatch.setattr("web.routers.search._today", lambda: datetime.date(2026, 10, 21))
    body = client.get("/api/search", params={"maker_key": "s1", "maker": "S1", "spellings": ["S1"], "offset": 0}).json()
    assert body["success"] is True and body["mode"] == "maker" and body["maker_key"] == "s1"
    assert [c["number"] for c in body["data"]] == calls["numbers"]
    assert {c["_source"] for c in body["data"]} == {"dmm"} and body["has_more"] is True
    assert calls["probe"][0] == "S1" and len(calls["list"]) == 1
    assert (calls["list"][0]["limit"], calls["list"][0]["offset"]) == (30, 0)  # 膠囊路徑不帶 limit ⇒ 一頁 30
