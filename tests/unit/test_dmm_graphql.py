"""175c-T6：DMM GraphQL 傳輸層（list_contents／fetch_facts）。

合成 JSON 全內嵌，不連外、不存站方回應。一律在 `scraper._session.post` 層注入（BE-TEST-33／43），
patch 掉 list_contents 就測不到失敗分類。「不發請求」量 post.call_count（BE-TEST-46）。
"""
import json
import re
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.proxy_policy import ProxySettings
from core.scrapers.dmm import DMMScraper, Facts, ListResult, Named
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.models import ScraperConfig


def _resp(status_code=200, json_data=None, json_exc=None):
    r = MagicMock()
    r.status_code = status_code
    if json_exc is not None:
        r.json = MagicMock(side_effect=json_exc)
    else:
        r.json = lambda: json_data
    return r


def _list_body(contents, page_info=None, *, with_page_info=True):
    result = {"contents": contents}
    if with_page_info:
        result["pageInfo"] = page_info if page_info is not None else {"totalCount": len(contents), "hasNext": False}
    return {"data": {"legacySearchPPV": {"result": result}}}


@pytest.fixture
def dmm(monkeypatch):
    import core.scrapers.dmm as dmm_module

    monkeypatch.setattr(dmm_module, "rate_limit", lambda *a, **kw: None)
    return DMMScraper(ScraperConfig(proxy_settings=ProxySettings(url="")))


def _list(s):
    return s.list_contents("三上悠亜", limit=40, offset=0)


def _facts(s):
    return s.fetch_facts(["sone00205", "ssis00001"])


# 兩個傳輸函式共用同一張失敗分類表（CD-175c-9）
TRANSPORTS = [pytest.param(_list, id="list"), pytest.param(_facts, id="facts")]

_BLOCKED_OR_NOT = [
    (403, SourceBlocked), (429, SourceBlocked), (503, SourceBlocked),
    (500, SourceUnreachable), (422, SourceUnreachable), (404, SourceUnreachable),
]


# ─── 邊界條件 1：失敗必須長得像失敗 ───────────────────────────────────────────

@pytest.mark.parametrize("status, expected", _BLOCKED_OR_NOT)
def test_list_contents_non_200_raises_not_empty(dmm, status, expected):
    """使用者搜女優名／點片商膠囊時 DMM 暫擋：非 200 不得被吞成『查無』。"""
    with patch.object(dmm._session, "post", return_value=_resp(status)):
        with pytest.raises(Exception) as ei:
            _list(dmm)
    assert type(ei.value) is expected
    assert str(status) in str(ei.value)


@pytest.mark.parametrize("call", TRANSPORTS)
@pytest.mark.parametrize("exc", [requests.Timeout("x"), requests.ConnectionError("x"),
                                 requests.exceptions.ReadTimeout("x")])
def test_requests_exception_raises_source_unreachable(dmm, call, exc):
    with patch.object(dmm._session, "post", side_effect=exc):
        with pytest.raises(Exception) as ei:
            call(dmm)
    assert type(ei.value) is SourceUnreachable


@pytest.mark.parametrize("call", TRANSPORTS)
@pytest.mark.parametrize("exc", [requests.exceptions.JSONDecodeError("bad", "<html>", 0), ValueError("bad")],
                         ids=["requests-JSONDecodeError", "ValueError"])
def test_non_json_200_raises_source_unreachable(dmm, call, exc):
    """200 但 body 不是 JSON（CF 挑戰頁之類）：兩種例外形狀都要接住。"""
    with patch.object(dmm._session, "post", return_value=_resp(200, json_exc=exc)):
        with pytest.raises(Exception) as ei:
            call(dmm)
    assert type(ei.value) is SourceUnreachable


_BAD_BODIES = [
    pytest.param({"errors": [{"message": "validation error"}], "data": None}, id="errors-with-null-data"),
    pytest.param({"errors": [{"message": "x"}], "data": _list_body([{"id": "a"}])["data"]}, id="errors-with-data"),
    pytest.param({}, id="empty-object"),
    pytest.param({"data": None}, id="data-null"),
    pytest.param({"data": "oops"}, id="data-not-dict"),
    pytest.param([], id="body-list"),
    pytest.param(None, id="body-null"),
]


@pytest.mark.parametrize("body", _BAD_BODIES)
@pytest.mark.parametrize("call", TRANSPORTS)
def test_bad_body_raises_source_unreachable(dmm, call, body):
    with patch.object(dmm._session, "post", return_value=_resp(200, body)):
        with pytest.raises(Exception) as ei:
            call(dmm)
    assert type(ei.value) is SourceUnreachable


@pytest.mark.parametrize("body", [
    pytest.param({"data": {}}, id="no-legacySearchPPV"),
    pytest.param({"data": {"legacySearchPPV": None}}, id="legacySearchPPV-null"),
    pytest.param({"data": {"legacySearchPPV": {}}}, id="no-result"),
    pytest.param({"data": {"legacySearchPPV": {"result": None}}}, id="result-null"),
    pytest.param({"data": {"legacySearchPPV": {"result": {}}}}, id="no-contents"),
    pytest.param({"data": {"legacySearchPPV": {"result": {"contents": None}}}}, id="contents-null"),
    pytest.param({"data": {"legacySearchPPV": {"result": {"contents": "x"}}}}, id="contents-not-list"),
])
def test_list_contents_shape_mismatch_raises_source_unreachable(dmm, body):
    with patch.object(dmm._session, "post", return_value=_resp(200, body)):
        with pytest.raises(Exception) as ei:
            _list(dmm)
    assert type(ei.value) is SourceUnreachable


def test_list_contents_empty_contents_is_definite_none(dmm):
    """contents: [] ＝確定沒有（與『連不上』分開）。errors 是空陣列不算錯誤。"""
    body = _list_body([], {"totalCount": 0, "hasNext": False})
    body["errors"] = []
    with patch.object(dmm._session, "post", return_value=_resp(200, body)):
        result = _list(dmm)
    assert result == ListResult([], 0, False)


# ─── 邊界條件 2：offset／limit ──────────────────────────────────────────────

@pytest.mark.parametrize("offset", [10001, 10_000_000])
def test_list_contents_offset_over_cap_sends_no_request(dmm, offset):
    """翻過站方 10000 筆上限：本地擋下，回『已到底』，不發請求。"""
    with patch.object(dmm._session, "post", return_value=_resp(200, _list_body([{"id": "x"}]))) as post:
        result = dmm.list_contents("三上悠亜", limit=40, offset=offset)
    assert post.call_count == 0
    assert result == ListResult([], None, False)


def test_list_contents_offset_at_cap_still_sends(dmm):
    body = _list_body([{"id": "x"}], {"totalCount": 10001, "hasNext": False})
    with patch.object(dmm._session, "post", return_value=_resp(200, body)) as post:
        result = dmm.list_contents("三上悠亜", limit=40, offset=10000)
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["variables"]["offset"] == 10000
    assert result.rows == [{"id": "x"}]


@pytest.mark.parametrize("limit, sent", [(500, 100), (101, 100), (100, 100), (40, 40), (1, 1)])
def test_list_contents_limit_clamped_to_100(dmm, limit, sent):
    with patch.object(dmm._session, "post", return_value=_resp(200, _list_body([]))) as post:
        dmm.list_contents("x", limit=limit, offset=0)
    assert post.call_args.kwargs["json"]["variables"]["limit"] == sent


# ─── 邊界條件 3：請求形狀（離線 A/B 的 calls 逐位元比對靠它）────────────────────

def test_list_contents_keyword_request_shape(dmm):
    with patch.object(dmm._session, "post", return_value=_resp(200, _list_body([]))) as post:
        dmm.list_contents("あかね麗", limit=40, offset=80)
    assert post.call_args.args == (dmm.API_URL,)
    assert set(post.call_args.kwargs) == {"json", "timeout"}
    assert post.call_args.kwargs["timeout"] == dmm.config.timeout
    payload = post.call_args.kwargs["json"]
    assert set(payload) == {"query", "variables"}
    assert payload["query"] == DMMScraper.SEARCH_LIST_QUERY
    # 精確字典：多一個 filter: None 鍵，A/B 的 calls 就會出現 W4 以外的差異
    assert payload["variables"] == {"limit": 40, "offset": 80, "sort": "RELEASE_DATE", "queryWord": "あかね麗"}
    assert list(payload["variables"]) == ["limit", "offset", "sort", "queryWord"]


# [lint-guard: pytest-justified] 對外 GraphQL contract（$filter 未宣告時 filter 失效會把全站最新當片商清單；pageInfo／id 欄位缺失會讓載入更多消失、名稱解析靜默落空）
@pytest.mark.parametrize("fragment", [
    "$filter: ContentSearchPPVFilterInput",
    "filter: $filter",
    "pageInfo { totalCount hasNext }",
    "actresses { id name }",
    "maker { id name }",
])
def test_search_list_query_declares_filter_and_selects_new_fields(fragment):
    """filter 變數沒宣告時站方會靜默忽略它（整站最新列表），所以宣告本身要鎖。"""
    assert fragment in re.sub(r"\s+", " ", DMMScraper.SEARCH_LIST_QUERY)


def test_list_contents_missing_page_info_is_not_an_error(dmm):
    """D2：pageInfo 缺 → total=None、has_next=False，不當錯誤。"""
    body = _list_body([{"id": "sone00205"}], with_page_info=False)
    with patch.object(dmm._session, "post", return_value=_resp(200, body)):
        result = dmm.list_contents("x", limit=40, offset=0)
    assert result == ListResult([{"id": "sone00205"}], None, False)


# ─── 邊界條件 4：fetch_facts ────────────────────────────────────────────────

_ALIAS_RE = re.compile(r'\ba(\d+)\s*:\s*ppvContent\(\s*id\s*:\s*("(?:[^"\\]|\\.)*")')


def _alias_ids(query):
    return [(int(n), json.loads(lit)) for n, lit in _ALIAS_RE.findall(query)]


def _facts_body(**by_alias):
    return {"data": by_alias}


def test_fetch_facts_one_request_with_n_aliases(dmm):
    ids = ["sone00205", "13dsvr01774", "h_113id00057", "55t28103", "ssis00001"]
    with patch.object(dmm._session, "post", return_value=_resp(200, _facts_body())) as post:
        dmm.fetch_facts(ids)
    assert post.call_count == 1
    assert post.call_args.args == (dmm.API_URL,)
    assert set(post.call_args.kwargs) == {"json", "timeout"}
    payload = post.call_args.kwargs["json"]
    assert set(payload) == {"query"}
    assert _alias_ids(payload["query"]) == list(enumerate(ids))
    for field in ("makerContentId", "series", "label", "directors"):
        assert len(re.findall(rf"\b{field}\b", payload["query"])) == len(ids), field


def test_fetch_facts_parses_response(dmm):
    ids = ["13dsvr01774", "missing-alias", "null-alias", "sparse"]
    body = _facts_body(
        a0={"makerContentId": "3DSVR-1774",
            "series": {"id": "233224", "name": "PLATINUM SOAP"},
            "label": {"id": "4325", "name": "MOODYZ DIVA"},
            "directors": [{"id": "101211", "name": "TAKE-D"}, {"id": "101212", "name": "監督B"}]},
        a2=None,
        a3={"makerContentId": "", "series": None, "label": None, "directors": None},
    )
    with patch.object(dmm._session, "post", return_value=_resp(200, body)):
        facts = dmm.fetch_facts(ids)
    # a1 整個沒回、a2 為 null：不入 dict
    assert set(facts) == {"13dsvr01774", "sparse"}
    assert facts["13dsvr01774"] == Facts("3DSVR-1774", Named("233224", "PLATINUM SOAP"), Named("4325", "MOODYZ DIVA"),
                                         [Named("101211", "TAKE-D"), Named("101212", "監督B")])
    # series／label null → None、directors null → []、makerContentId 空字串 → None
    assert facts["sparse"] == Facts(None, None, None, [])
    assert facts["sparse"].maker_content_id is None


def test_fetch_facts_over_100_ids_raises_value_error_without_request(dmm):
    with patch.object(dmm._session, "post") as post:
        with pytest.raises(ValueError):
            dmm.fetch_facts([f"id{i}" for i in range(101)])
    assert post.call_count == 0


def test_fetch_facts_exactly_100_ids_is_one_request(dmm):
    ids = [f"id{i}" for i in range(100)]
    with patch.object(dmm._session, "post", return_value=_resp(200, _facts_body())) as post:
        dmm.fetch_facts(ids)
    assert post.call_count == 1
    assert len(_alias_ids(post.call_args.kwargs["json"]["query"])) == 100


# ─── 公開型別形狀 ────────────────────────────────────────────────────────────
