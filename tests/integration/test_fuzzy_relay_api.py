"""test_fuzzy_relay_api.py — 路由接上片商搜尋（175b-T9）。

片商名單與 smart_search 皆在使用端以合成值替身，不連外、不碰真實片庫。
"""
from unittest.mock import patch, MagicMock

from core.maker_names import maker_key_of

LIMIT = 20


def _cards(n):
    return [{"number": f"SOD-{i:03d}", "title": f"t{i}", "actors": [], "_mode": "maker"} for i in range(n)]


def _smart(n, seen):
    def fake(q, limit=20, offset=0, status_callback=None, result_callback=None, **kwargs):
        seen.append(kwargs)
        return _cards(n)
    return fake


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
