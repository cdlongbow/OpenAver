"""175d-T6：路由契約——REST／stream／片商收 `cursor`，輸出 `cursor` 與 `answered_by`（CD-175d-10）。

走真的 ASGI 路由、真的 smart_search／search_maker_latest、真的 relay；站方一律換成登進註冊表的 stub provider
（回我們自己的卡 dict，零站方回應、不連外）。

零呼叫斷言量 stub 的呼叫記錄（BE-TEST-46），且每個零呼叫案都配「同設定換有效 token ⇒ 被釘那家被問並回卡」的對照
（BE-TEST-23）——否則路由根本沒轉傳 cursor 時，缺 token 的 offset>0 本來就零呼叫，會假綠。
token 的 p 一律是已註冊 id（javbus／dmm），有效 token 一律取自第一頁回應，只有「無效 token」才手工造。
"""

import base64
import datetime
import json
from unittest.mock import patch

import pytest

from core.database import init_db
from core.search_providers import cursor as cursor_codec
from core.search_providers import registry
from core.search_providers.types import Enriched, EntityRef, Kind, MakerSearchResult, Page, Window, WorkItem

REST = "/api/search"
SSE = "/api/search/stream"
TODAY = datetime.date(2026, 10, 21)
LIMIT = 3
Q = "MIDV"  # 前綴（prefix）
NAME = "二階堂麗"  # 女優（actress）
MAKER = {"maker_key": "s1", "maker": "S1", "spellings": ["S1"]}
KEYS_175C = {"success", "data", "total", "mode", "offset", "has_more", "actress_profile"}
VIAS = ["rest", "stream"]


# ---------------------------------------------------------------- stub provider（回我們自己的卡 dict）
def _card(number):
    return {"number": number, "title": f"t {number}", "actors": []}


class Stub:
    """所有方法都記錄在 calls（零呼叫量的就是它）。

    cards：run 回的張數（0＝空）；maker_cards：run_maker 回的張數（0＝maker_not_found）；
    people：{名字: EntityRef}、works：{ref.id: 作品編號 list}（梯子用）。run／run_maker 有拿到 result_callback 就先送 seed。"""

    supports_discovery = False
    fallback_streaming = True

    def __init__(self, pid, *, cards=0, maker_cards=0, people=None, works=None):
        self.id = pid
        self.cards = cards
        self.maker_cards = maker_cards
        self.people = people or {}
        self.works = works or {}
        caps = {Kind.KEYWORD, Kind.PARTIAL, Kind.CODE, Kind.MAKER}
        self.capabilities = frozenset(caps | ({Kind.ACTOR} if people is not None else set()))
        self.calls = []
        self.windows = []  # run／list_entity／run_maker 收到的視窗（offset, limit）

    def reset(self):
        self.calls.clear()
        self.windows.clear()

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.calls.append("run")
        self.windows.append(w)
        cards = [_card(f"{target}-{w.offset + i:03d}") for i in range(self.cards)]
        if result_callback is not None:
            result_callback(-1, [c["number"] for c in cards])
        return cards

    def run_maker(self, maker_key, label, spellings, offset, *, limit=None, titles, today,
                  status_callback=None, result_callback=None, db_path=None):
        self.calls.append("run_maker")
        self.windows.append(offset)
        if not self.maker_cards:
            return MakerSearchResult([], False, "maker_not_found")
        cards = [_card(f"MKR-{offset + i:03d}") for i in range(self.maker_cards)]
        if result_callback is not None:
            result_callback(-1, [c["number"] for c in cards])
        return MakerSearchResult(cards, True, None)

    def resolve(self, kind, name):
        self.calls.append("resolve")
        return self.people.get(name) if kind is Kind.ACTOR else None

    def list_entity(self, ref, w):
        self.calls.append("list_entity")
        self.windows.append(w)
        full = self.works.get(ref.id, [])
        got = full[w.offset : w.offset + w.limit]
        items = [WorkItem(n, f"t {n}", "", "2026-01-01", [], "x", ref=ref.id) for n in got]
        return Page(items, w.offset + w.limit < len(full))

    def search_keyword(self, q, w):
        self.calls.append("search_keyword")
        return Page()

    def enrich(self, item, ref):
        self.calls.append("enrich")
        return Enriched(_card(item.number), True)


R1 = EntityRef(Kind.ACTOR, "r1", "麗")
WORKS = [f"ACT-{i:03d}" for i in range(1, 8)]  # 7 部：LIMIT=3 ⇒ 第一頁位置 3、第二頁位置 6


# ---------------------------------------------------------------- fixtures / helpers
@pytest.fixture
def chain(tmp_path, monkeypatch):
    """chain(A, B, …)：把 stub 放進註冊表（順序＝傳入順序），並擋掉片庫／片商名單／無碼／節流。"""
    db = tmp_path / "t.db"
    init_db(db)
    monkeypatch.setattr("web.routers.search.get_db_path", lambda: db)
    monkeypatch.setattr("web.routers.search._today", lambda: TODAY)
    monkeypatch.setattr("web.routers.search._library_titles", lambda db_path: [])
    monkeypatch.setattr("web.routers.search.known_makers", lambda: frozenset())
    monkeypatch.setattr("core.maker_names.known_makers", lambda: frozenset())
    monkeypatch.setattr("core.scraper.is_uncensored_route", lambda target: False)
    monkeypatch.setattr("core.scraper.REQUEST_DELAY", 0)
    monkeypatch.setattr("core.scraper.MAX_WORKERS", 1)
    monkeypatch.setattr("core.search_providers.actor_names.load_alias_groups", lambda: [])

    def setup(*stubs):
        ids = [s.id for s in stubs]
        for s in stubs:
            monkeypatch.setitem(registry._REGISTRY, s.id, lambda s=s: s)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(ids))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in ids)

    return setup


@pytest.fixture
def kw(chain):
    """關鍵字（前綴）鏈：A＝javbus 無卡、B＝dmm 有卡 ⇒ 第一頁由 B 回答。"""
    a, b = Stub("javbus"), Stub("dmm", cards=LIMIT)
    chain(a, b)
    return a, b


@pytest.fixture
def mk(chain):
    """片商鏈：A＝javbus 回 maker_not_found、B＝dmm 有卡。"""
    a, b = Stub("javbus"), Stub("dmm", maker_cards=LIMIT)
    chain(a, b)
    return a, b


@pytest.fixture
def ask(client, parse_sse_events):
    """ask(via, **params) → 回應 dict（REST 的 JSON／stream 最後一個 result 事件）。"""

    def _ask(via, **params):
        if via == "rest":
            r = client.get(REST, params=params)
            assert r.status_code == 200
            return r.json()
        r = client.get(SSE, params=params)
        assert r.status_code == 200
        return [e for e in parse_sse_events(r.text) if e["type"] == "result"][-1]

    return _ask


def _raw(obj) -> str:
    """手工造壞 token（不依賴 encode 的簽名）。"""
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()


def _nums(body):
    return [c["number"] for c in body["data"]]


def _reset(*stubs):
    for s in stubs:
        s.reset()


def _untouched(*stubs):
    assert [s.calls for s in stubs] == [[] for _ in stubs]


def _page(offset):
    return {"q": Q, "limit": LIMIT, "offset": offset}


def _maker_page(offset):
    return {**MAKER, "offset": offset}


# ---------------------------------------------------------------- 輸出：第一頁帶 cursor／answered_by
def test_rest_success_reports_cursor_and_answerer(client, kw):
    body = client.get(REST, params=_page(0)).json()
    assert body["success"] is True and body["answered_by"] == "dmm"
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "keyword")


def test_stream_result_reports_cursor_and_answerer(client, parse_sse_events, kw):
    events = parse_sse_events(client.get(SSE, params=_page(0)).text)
    result = [e for e in events if e["type"] == "result"][-1]
    assert result["success"] is True and result["answered_by"] == "dmm"
    assert cursor_codec.decode(result["cursor"]) == cursor_codec.Token("dmm", "keyword")


def test_stream_result_complete_reports_the_same_cursor_and_answerer(client, parse_sse_events, kw):
    events = parse_sse_events(client.get(SSE, params=_page(0)).text)
    complete = [e for e in events if e["type"] == "result-complete"]
    assert len(complete) == 1  # 漸進路徑被用到（A 的 seed 已送）才會有；沒有就是 stub 沒送 seed，不能跳過
    result = [e for e in events if e["type"] == "result"][-1]
    assert complete[0]["cursor"] == result["cursor"] and complete[0]["cursor"] is not None
    assert complete[0]["answered_by"] == result["answered_by"] == "dmm"


@pytest.mark.parametrize("via", VIAS)
def test_maker_first_page_reports_cursor_and_answerer(ask, mk, via):
    body = ask(via, **_maker_page(0))
    assert body["success"] is True and body["mode"] == "maker" and body["answered_by"] == "dmm"
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "maker")


def test_rest_actress_ladder_reports_entity_cursor(client, chain):
    a, b = Stub("javbus", people={}), Stub("dmm", people={NAME: R1}, works={"r1": WORKS})
    chain(a, b)
    body = client.get(REST, params={"q": NAME, "limit": LIMIT}).json()
    assert body["success"] is True and body["mode"] == "actress" and body["answered_by"] == "dmm"
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "entity", (("actor", "r1", LIMIT),))
    assert _nums(body) == WORKS[:LIMIT]


def test_exact_mode_success_has_null_cursor_and_answerer(client, chain):
    chain(Stub("javbus"), Stub("dmm"))
    with patch("web.routers.search.search_jav", return_value=_card("SSIS-001")):
        body = client.get(REST, params={"q": "SSIS-001", "mode": "exact"}).json()
    assert body["success"] is True
    assert "cursor" in body and body["cursor"] is None
    assert "answered_by" in body and body["answered_by"] is None


# ---------------------------------------------------------------- I-R2：第一頁其他欄位與 175c 逐欄相同
EXPECTED_DATA = [{"number": f"MIDV-{i:03d}", "title": f"t MIDV-{i:03d}", "actors": [], "_mode": "prefix"} for i in range(3)]


def test_rest_first_page_matches_175c_shape(client, kw):
    body = client.get(REST, params=_page(0)).json()
    assert set(body) - {"cursor", "answered_by"} == KEYS_175C
    assert {k: body[k] for k in KEYS_175C} == {
        "success": True, "data": EXPECTED_DATA, "total": 3, "mode": "prefix",
        "offset": 0, "has_more": True, "actress_profile": None,
    }


def test_stream_first_page_result_matches_175c_shape(client, parse_sse_events, kw):
    events = parse_sse_events(client.get(SSE, params=_page(0)).text)
    result = [e for e in events if e["type"] == "result"][-1]
    assert set(result) - {"cursor", "answered_by"} == KEYS_175C | {"type"}
    assert {k: result[k] for k in KEYS_175C | {"type"}} == {
        "type": "result", "success": True, "data": EXPECTED_DATA, "total": 3, "mode": "prefix",
        "offset": 0, "has_more": True, "actress_profile": None,
    }


# ---------------------------------------------------------------- 續頁：只問被釘的那家
def _check_keyword_continuation(ask, via, a, b):
    token = ask(via, **_page(0))["cursor"]
    _reset(a, b)
    body = ask(via, **_page(LIMIT), cursor=token)
    assert a.calls == []  # 單獨是恆真的（缺 token 也零呼叫），所以下面必須正向斷言 B 被問到、回卡
    assert b.calls == ["run"] and b.windows == [Window(LIMIT, LIMIT)]
    assert body["success"] is True and _nums(body) == ["MIDV-003", "MIDV-004", "MIDV-005"]
    assert body["answered_by"] == "dmm"
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "keyword")


def test_rest_continuation_asks_only_the_pinned_provider(ask, kw):
    _check_keyword_continuation(ask, "rest", *kw)


def test_stream_continuation_asks_only_the_pinned_provider(ask, kw):
    _check_keyword_continuation(ask, "stream", *kw)


@pytest.mark.parametrize("via", VIAS)
def test_maker_continuation_asks_only_the_pinned_provider(ask, mk, via):
    a, b = mk
    token = ask(via, **_maker_page(0))["cursor"]
    _reset(a, b)
    body = ask(via, **_maker_page(30), cursor=token)
    assert a.calls == []
    assert b.calls == ["run_maker"] and b.windows == [30]
    assert body["success"] is True and _nums(body) == ["MKR-030", "MKR-031", "MKR-032"]
    assert body["answered_by"] == "dmm" and body["offset"] == 30
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "maker")


@pytest.mark.parametrize("via", VIAS)
def test_actress_continuation_skips_resolve_and_asks_only_the_pinned_provider(ask, chain, via):
    a, b = Stub("javbus", people={}), Stub("dmm", people={NAME: R1}, works={"r1": WORKS})
    chain(a, b)
    token = ask(via, q=NAME, limit=LIMIT)["cursor"]
    _reset(a, b)
    body = ask(via, q=NAME, limit=LIMIT, offset=LIMIT, cursor=token)
    assert a.calls == []
    assert "resolve" not in b.calls and "list_entity" in b.calls  # 實體來自 token，不重算第一頁
    assert b.windows == [Window(LIMIT, LIMIT)]
    assert body["success"] is True and _nums(body) == WORKS[LIMIT : 2 * LIMIT]
    assert body["answered_by"] == "dmm"
    assert cursor_codec.decode(body["cursor"]) == cursor_codec.Token("dmm", "entity", (("actor", "r1", 2 * LIMIT),))


def test_rest_explicit_prefix_and_actress_modes_forward_the_cursor(client, kw, chain):
    a, b = kw
    token = client.get(REST, params=_page(0)).json()["cursor"]
    _reset(a, b)
    body = client.get(REST, params={**_page(LIMIT), "mode": "prefix", "cursor": token}).json()  # Q1：else 分支
    assert a.calls == [] and b.calls == ["run"] and body["success"] is True and body["answered_by"] == "dmm"
    a2, b2 = Stub("javbus", people={}), Stub("dmm", people={NAME: R1}, works={"r1": WORKS})
    chain(a2, b2)
    token = client.get(REST, params={"q": NAME, "limit": LIMIT, "mode": "actress"}).json()["cursor"]
    _reset(a2, b2)
    body = client.get(REST, params={"q": NAME, "limit": LIMIT, "offset": LIMIT, "mode": "actress", "cursor": token}).json()
    assert a2.calls == [] and "resolve" not in b2.calls and body["success"] is True and body["answered_by"] == "dmm"


# ---------------------------------------------------------------- token 往返與互通（續頁的新 token 可再續）
@pytest.mark.parametrize("order", [("rest", "stream", "rest"), ("stream", "rest", "stream")])
def test_keyword_token_round_trips_across_endpoints(ask, kw, order):
    a, b = kw
    first, second, third = order
    t1 = ask(first, **_page(0))["cursor"]
    _reset(a, b)
    page2 = ask(second, **_page(LIMIT), cursor=t1)
    assert page2["success"] is True and _nums(page2)[0] == "MIDV-003" and a.calls == []
    page3 = ask(third, **_page(2 * LIMIT), cursor=page2["cursor"])
    assert page3["success"] is True and _nums(page3)[0] == "MIDV-006" and a.calls == []
    assert b.windows == [Window(LIMIT, LIMIT), Window(2 * LIMIT, LIMIT)]


@pytest.mark.parametrize("order", [("rest", "stream", "rest"), ("stream", "rest", "stream")])
def test_maker_token_round_trips_across_endpoints(ask, mk, order):
    a, b = mk
    first, second, third = order
    t1 = ask(first, **_maker_page(0))["cursor"]
    _reset(a, b)
    page2 = ask(second, **_maker_page(30), cursor=t1)
    assert page2["success"] is True and _nums(page2)[0] == "MKR-030" and a.calls == []
    page3 = ask(third, **_maker_page(60), cursor=page2["cursor"])
    assert page3["success"] is True and _nums(page3)[0] == "MKR-060" and a.calls == []
    assert b.windows == [30, 60]


# ---------------------------------------------------------------- offset=0 不看 token（I-C2）
@pytest.mark.parametrize("via", VIAS)
def test_first_page_ignores_a_token_pinned_to_b(ask, kw, via):
    a, b = kw
    token = ask(via, **_page(0))["cursor"]  # 第一頁由 B 回答 ⇒ token 釘 dmm
    a.cards = LIMIT  # 現在 A 也有卡了：若 token 被當真，offset=0 會直接問 B
    _reset(a, b)
    body = ask(via, **_page(0), cursor=token)
    assert a.calls == ["run"] and b.calls == []  # 鏈第一家 A 仍先被問
    assert body["success"] is True and body["answered_by"] == "javbus"  # 回答者以實際為準


# ---------------------------------------------------------------- 無效 token ⇒ 查無且零呼叫（附對照）
BAD_TOKENS = {
    "json-not-an-object": _raw([]),
    "p-wrong-type": _raw({"p": 1, "k": "keyword"}),
    "triple-missing-item": _raw({"p": "dmm", "k": "entity", "r": [["actor", "x"]]}),
}


@pytest.mark.parametrize("bad", list(BAD_TOKENS))
@pytest.mark.parametrize("via", VIAS)
def test_invalid_token_means_nothing_more_and_asks_nobody(ask, kw, via, bad):
    a, b = kw
    good = ask(via, **_page(0))["cursor"]
    _reset(a, b)
    body = ask(via, **_page(LIMIT), cursor=BAD_TOKENS[bad])
    assert body["success"] is False and body["data"] == []
    _untouched(a, b)
    control = ask(via, **_page(LIMIT), cursor=good)  # 對照：同設定換有效 token ⇒ B 被問到、有卡
    assert control["success"] is True and b.calls == ["run"] and a.calls == []


@pytest.mark.parametrize("via", VIAS)
def test_empty_cursor_counts_as_missing(ask, kw, via):
    a, b = kw
    good = ask(via, **_page(0))["cursor"]
    _reset(a, b)
    body = ask(via, **_page(LIMIT), cursor="")
    assert body["success"] is False and body["data"] == []
    _untouched(a, b)
    assert ask(via, **_page(LIMIT), cursor=good)["success"] is True and b.calls == ["run"]  # 對照


@pytest.mark.parametrize("via", VIAS)
def test_empty_cursor_reaches_smart_search_as_none(ask, kw, via):
    """「空字串＝未帶」要在 smart_search 的縫上量：回應上 "" 與缺 token 在核心結果相同，看不出來。"""
    seen = []

    def fake(q, *args, **kwargs):
        seen.append(kwargs)
        return [dict(_card("MIDV-021"), _mode="prefix")]

    with patch("web.routers.search.smart_search", side_effect=fake):
        ask(via, **_page(20), cursor="")
        ask(via, **_page(20), cursor="Zm9v")
        ask(via, **_page(20))
    assert [kwargs["cursor"] for kwargs in seen] == [None, "Zm9v", None]  # 鍵必須在；非空原樣轉傳


# ---------------------------------------------------------------- 超長／非法字元 ⇒ 422；剛好 512 的合法字元 ⇒ 查無
@pytest.mark.parametrize("url", [REST, SSE], ids=["rest", "stream"])
@pytest.mark.parametrize(
    "cursor", ["A" * 513, "a b", "a/b", "a+b", "a.b"], ids=["513-chars", "space", "slash", "plus", "dot"]
)
def test_oversized_or_illegal_cursor_is_rejected_before_any_provider(client, kw, url, cursor):
    r = client.get(url, params={**_page(LIMIT), "cursor": cursor})
    assert r.status_code == 422
    _untouched(*kw)


@pytest.mark.parametrize("via", VIAS)
def test_exactly_512_legal_chars_is_not_a_token_but_not_a_422(ask, kw, via):
    body = ask(via, **_page(LIMIT), cursor="A" * 512)  # ask 內斷言 HTTP 200
    assert body["success"] is False and body["data"] == []
    _untouched(*kw)
