"""TASK-118-T4b：blocked / blocked_sources 回應契約。

Patch 對齊使用端（BE-TEST-01）：web.routers.search.* /
web.routers.scraper.*；search_jav_single_source 在 search 端點內 local
import，改 patch core.scraper.search_jav_single_source。
"""

from core.scrapers.errors import BlockedRecord


def _fc2_record(article_id="FC2-PPV-1234567", source_id="fc2"):
    return BlockedRecord(source_id=source_id, article_id=article_id, status=403)


def _fill_blocked(result, *records):
    """side_effect：把 records 寫進 caller 傳入的 blocked_out，再回 result。"""

    def _fn(*args, **kwargs):
        blocked_out = kwargs.get("blocked_out")
        if blocked_out is not None:
            blocked_out.extend(records)
        return result

    return _fn


def _scraper_hit(**kw):
    d = {
        "number": "SONE-205",
        "title": "Test Title",
        "maker": "Test Maker",
        "date": "2024-01-01",
        "cover": "https://example.com/cover.jpg",
        "tags": ["tag1"],
        "source": "javbus",
        "url": "https://example.com/SONE-205",
        "director": "",
        "duration": 120,
        "label": "",
        "series": "",
        "sample_images": [],
        "actors": ["Actor A"],
        "_source": "javbus",
    }
    d.update(kw)
    return d


# ── 1 REST auto：被擋且無結果 ──────────────────────────────────────────────


def test_rest_auto_blocked_no_results(client, mocker):
    """#1 REST /api/search?mode=auto：來源被擋且無結果。"""
    mocker.patch(
        "web.routers.search.smart_search",
        side_effect=_fill_blocked([], _fc2_record()),
    )

    response = client.get("/api/search", params={"q": "FC2-PPV-1234567", "mode": "auto"})

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert data["blocked_sources"] == ["fc2"]
    assert data["data"] == []
    assert data["total"] == 0


# ── 2 REST：有結果 ＋ 某來源被擋 → 不出聲 ─────────────────────────────────


def test_rest_has_results_source_blocked_is_silent(client, mocker):
    """#2 有結果時 blocked 恆 false、blocked_sources 恆 []。"""
    mocker.patch(
        "web.routers.search.smart_search",
        side_effect=_fill_blocked([_scraper_hit()], _fc2_record()),
    )

    response = client.get("/api/search", params={"q": "FC2-PPV-1234567", "mode": "auto"})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["blocked"] is False
    assert data["blocked_sources"] == []
    assert data["data"]


# ── 3 REST：無結果且無被擋 ────────────────────────────────────────────────


def test_rest_no_results_no_blocked_error_unchanged(client, mocker):
    """#3 無結果且無被擋 → blocked=false，既有 error 字串逐字不變。"""
    mocker.patch("web.routers.search.smart_search", return_value=[])

    q = "FAKE-999"
    response = client.get("/api/search", params={"q": q, "mode": "auto"})

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is False
    assert data["blocked_sources"] == []
    assert data["error"] == f"找不到 {q} 的資料"
    assert data["data"] == []


# ── 4 REST exact ＋ 明確選源 ──────────────────────────────────────────────


def test_rest_exact_single_source_blocked(client, mocker):
    """#4 REST exact ＋ 明確選源被擋 → blocked=true（接線點 #2）。"""
    mocker.patch(
        "core.scraper.search_jav_single_source",
        side_effect=_fill_blocked(None, _fc2_record()),
    )

    response = client.get(
        "/api/search",
        params={"q": "FC2-PPV-1234567", "mode": "exact", "source": "fc2"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert data["blocked_sources"] == ["fc2"]
    assert data["data"] == []


# ── REST exact 未指定來源（接線點 #3，DoD）────────────────────────────────


def test_rest_exact_search_jav_blocked(client, mocker):
    """接線點 #3：REST exact 未指定來源走 search_jav。"""
    mocker.patch(
        "web.routers.search.search_jav",
        side_effect=_fill_blocked(None, _fc2_record()),
    )

    response = client.get(
        "/api/search",
        params={"q": "FC2-PPV-1234567", "mode": "exact"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert data["blocked_sources"] == ["fc2"]
    assert data["data"] == []


# ── 5 SSE result event ＋ result-complete 不含兩欄 ────────────────────────


def test_sse_result_event_blocked_result_complete_omits_flags(
    client, mocker, parse_sse_events
):
    """#5 SSE 最終 result 含兩欄；被擋時 blocked=true；result-complete 不含這兩欄。"""

    def _smart_search(q, limit=20, offset=0, status_callback=None,
                      result_callback=None, **kwargs):
        blocked_out = kwargs.get("blocked_out")
        if blocked_out is not None:
            blocked_out.append(_fc2_record())
        if result_callback:
            result_callback(-1, ["FC2-PPV-1234567"])
        return []

    mocker.patch("web.routers.search.smart_search", side_effect=_smart_search)

    response = client.get("/api/search/stream", params={"q": "FC2-PPV-1234567"})
    events = parse_sse_events(response.text)

    result_events = [e for e in events if e.get("type") == "result"]
    assert len(result_events) == 1
    result = result_events[0]
    assert result["blocked"] is True
    assert result["blocked_sources"] == ["fc2"]
    assert result["data"] == []
    assert result["total"] == 0

    complete_events = [e for e in events if e.get("type") == "result-complete"]
    assert len(complete_events) == 1
    complete = complete_events[0]
    assert "blocked" not in complete
    assert "blocked_sources" not in complete


# ── 6 重刮 preview ────────────────────────────────────────────────────────


def test_rescrape_preview_blocked_and_success_flags(client, mocker):
    """#6 重刮 preview：被擋 → success false + 兩欄；成功 → blocked=false。"""
    mocker.patch(
        "web.routers.scraper.search_jav",
        side_effect=_fill_blocked(None, _fc2_record()),
    )
    blocked_resp = client.post(
        "/api/rescrape/preview",
        json={"number": "FC2-PPV-1234567", "source": "auto"},
    )
    assert blocked_resp.status_code == 200
    blocked_data = blocked_resp.json()
    assert blocked_data == {
        "success": False,
        "blocked": True,
        "blocked_sources": ["fc2"],
    }

    mocker.patch(
        "web.routers.scraper.search_jav",
        side_effect=_fill_blocked(_scraper_hit(), _fc2_record()),
    )
    ok_resp = client.post(
        "/api/rescrape/preview",
        json={"number": "SONE-205", "source": "auto"},
    )
    assert ok_resp.status_code == 200
    ok_data = ok_resp.json()
    assert ok_data["success"] is True
    assert ok_data["blocked"] is False
    assert ok_data["blocked_sources"] == []


# ── 7 scrape-single 補搜尋（接線點 #7，DoD）──────────────────────────────


def test_scrape_single_blocked_flags(client, mocker):
    """接線點 #7：/api/scrape-single 無 metadata 補搜尋被擋時只加旗標。"""
    mocker.patch(
        "web.routers.scraper.search_jav",
        side_effect=_fill_blocked(None, _fc2_record()),
    )

    response = client.post(
        "/api/scrape-single",
        json={"file_path": "/tmp/FC2-PPV-1234567.mp4", "number": "FC2-PPV-1234567"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "找不到 FC2-PPV-1234567 的資料"
    assert data["blocked"] is True
    assert data["blocked_sources"] == ["fc2"]


# ── 10 blocked_sources 去重且保序 ─────────────────────────────────────────


def test_blocked_sources_dedup_preserves_order(client, mocker):
    """#10 同一來源記兩次 → 去重後一個元素；不同來源保序。"""
    mocker.patch(
        "web.routers.search.smart_search",
        side_effect=_fill_blocked(
            [],
            _fc2_record(),
            _fc2_record(source_id="avsox"),
            _fc2_record(),
        ),
    )

    response = client.get("/api/search", params={"q": "FC2-PPV-1234567", "mode": "auto"})

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert data["blocked_sources"] == ["fc2", "avsox"]
