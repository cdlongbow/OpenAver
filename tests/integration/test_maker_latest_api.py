"""test_maker_latest_api.py — 片商膠囊容量端點與 stream／REST 的 maker 分支（TASK-173-T6）。

DB 一律 tmp_path、今天一律注入、JavBus 一律在使用端替身，不連外網。
"""
import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.database import Video, VideoRepository, init_db, maker_javbus_map
from core.path_utils import to_file_uri
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers.relay import MakerCapsulePolicy
from core.scrapers.javbus import STUDIO_MISS, JavBusScraper, StudioVote

TODAY = datetime.date(2026, 10, 21)
KEY = "s1"
V7Q = StudioVote("censored", "7q")
SECRET = "secret-boom"
SSE = "/api/search/stream"
REST = "/api/search"
CAPS = "/api/search/maker-capsules"


# ---------------- fixtures / helpers ----------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    db = tmp_path / "t.db"
    init_db(db)
    monkeypatch.setattr("web.routers.search.get_db_path", lambda: db)
    monkeypatch.setattr("web.routers.search._today", lambda: TODAY)
    monkeypatch.setattr("web.routers.search.maker_capsule_policy", lambda: MakerCapsulePolicy(True, True))
    monkeypatch.setattr(
        "web.routers.search.get_configured_gallery_dirs",
        lambda cfg: ({to_file_uri(str(video_dir), {})}, {}),
    )
    monkeypatch.setattr("core.scraper.MAX_WORKERS", 1)
    # 175b-T8b：片商路徑改走接力；173 的情境只驗 JavBus，固定鏈＝只有 javbus
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ["javbus"])
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda sid: sid == "javbus")
    return type("Env", (), {"db": db, "dir": video_dir, "tmp": tmp_path})()


def add_videos(env, rows, outside=False):
    """rows: [(filename, number, maker, release_date)]"""
    base = env.tmp / "outside" if outside else env.dir
    base.mkdir(exist_ok=True)
    VideoRepository(env.db).upsert_batch([
        Video(path=to_file_uri(str(base / fn), {}), number=num, title=num, maker=maker,
              release_date=date, size_bytes=1, mtime=1.0)
        for fn, num, maker, date in rows
    ])


def five_s1(env):
    add_videos(env, [(f"SONE-{200 + i}.mp4", f"SONE-{200 + i}", "S1", f"2026-0{1 + i}-10") for i in range(5)])


def caps(client):
    r = client.get(CAPS)
    assert r.status_code == 200
    return r.json()


def by_maker(data):
    return {m["maker"]: m for m in data["makers"]}


def nums(n, start=1):
    return [f"MKR-{i:03d}" for i in range(start, start + n)]


def detail(missing=(), dates=None):
    def fake(num, source=None, *a, **kw):
        if num in missing:
            return None
        d = {"number": num, "title": f"t-{num}", "source": "javbus"}
        if dates:
            d["date"] = dates[num]
        return d
    return fake


class Fetcher:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, number):
        self.calls.append(number)
        return self.outcomes[len(self.calls) - 1]


def studio_pages(pages):
    """依頁碼回不同清單；沒列的頁碼丟錯（表示不該被請求）。"""
    def fake(ref, page=1):
        if page not in pages:
            raise TimeoutError(f"page {page} must not be requested")
        return pages[page]
    return fake


class Mocks:
    def __init__(self, sample, studio, sj):
        self.sample, self.studio, self.sj = sample, studio, sj


def maker_patches(sample_outcomes=(V7Q, V7Q), studio=None, sj=None):
    """回 (ExitStack-able contexts) — 以 contextmanager 形式使用。"""
    import contextlib

    @contextlib.contextmanager
    def cm():
        fetcher = Fetcher(sample_outcomes)
        with patch.object(JavBusScraper, "fetch_studio_sample", side_effect=fetcher) as fs, \
             patch.object(JavBusScraper, "get_ids_from_studio",
                          side_effect=studio or studio_pages({1: nums(30)})) as st, \
             patch("core.scraper.search_jav", side_effect=sj or detail()) as sjm:
            fs.fetcher = fetcher
            yield Mocks(fs, st, sjm)
    return cm()


PARAMS = {"maker_key": KEY, "maker": "S1", "spellings": ["S1"]}


def sse(client, parse_sse_events, **extra):
    r = client.get(SSE, params={**PARAMS, **extra})
    assert r.status_code == 200
    return r.text, parse_sse_events(r.text)


def sse_result(events):
    return [e for e in events if e["type"] == "result"][-1]


def rest(client, **extra):
    return client.get(REST, params={**PARAMS, **extra})


# ---------------- capsules ----------------

def test_recent_window_includes_since_day(client, env):
    add_videos(env, [
        ("A-001.mp4", "AAA-001", "Alpha", "2025-10-21"),
        ("A-002.mp4", "AAA-002", "Alpha", "2025-10-20"),
    ])
    data = caps(client)
    assert data["since"] == "2025-10-21"
    assert by_maker(data)["Alpha"] == {"maker": "Alpha", "total": 2, "recent": 1}


@pytest.mark.parametrize("today,since", [
    (datetime.date(2026, 10, 21), "2025-10-21"),
    (datetime.date(2026, 2, 28), "2025-02-28"),
    (datetime.date(2024, 2, 29), "2023-02-28"),
    (datetime.date(2028, 2, 29), "2027-02-28"),
])
def test_since_is_twelve_months_back_clamped(client, env, monkeypatch, today, since):
    monkeypatch.setattr("web.routers.search._today", lambda: today)
    assert caps(client)["since"] == since


def test_capsules_counting_rules(client, env):
    add_videos(env, [
        ("B-001.mp4", "BBB-001", "Beta", "2026-09"),        # 月份不全
        ("B-002.mp4", "BBB-002", "Beta", "2026-13-05"),     # 不合法日期
        ("B-003.mp4", "BBB-003", "Beta", "2026-03-05"),
        ("M-001-cd1.mp4", "MMM-001", " Multi ", "2026-03-05"),   # 分集片算一部
        ("M-001-cd2.mp4", "MMM-001", "Multi", "2026-03-05"),
        ("E-001.mp4", "EEE-001", "", "2026-03-05"),
        ("E-002.mp4", "EEE-002", "   ", "2026-03-05"),
        ("E-003.mp4", "EEE-003", None, "2026-03-05"),
    ])
    add_videos(env, [("O-001.mp4", "OOO-001", "Outside", "2026-03-05")], outside=True)
    data = caps(client)
    m = by_maker(data)
    assert m["Beta"] == {"maker": "Beta", "total": 3, "recent": 1}
    assert m["Multi"] == {"maker": "Multi", "total": 1, "recent": 1}
    assert set(m) == {"Beta", "Multi"}
    assert all(x["recent"] <= x["total"] for x in data["makers"])
    assert data["maker_search_enabled"] is True and not any("javbus" in k for k in data)


def test_not_found_maker_appears_in_hidden_keys(client, env):
    five_s1(env)
    assert caps(client)["hidden_keys"] == []
    with maker_patches(sample_outcomes=[STUDIO_MISS] * 5):
        body = rest(client).json()
    assert body["error_code"] == "maker_not_found"
    assert caps(client)["hidden_keys"] == [KEY]


def test_capsules_row_disabled_when_no_provider_can_answer(client, env, monkeypatch):
    five_s1(env)
    monkeypatch.setattr("web.routers.search.maker_capsule_policy", lambda: MakerCapsulePolicy(False, False))
    with patch("web.routers.search.init_db") as idb, \
         patch("web.routers.search.VideoRepository") as repo, \
         patch("web.routers.search.list_not_found_keys") as lnf:
        data = caps(client)
    assert data["success"] is True
    assert data["maker_search_enabled"] is False and not any("javbus" in k for k in data)
    assert data["makers"] == [] and data["hidden_keys"] == []
    assert idb.call_count == 0 and repo.call_count == 0 and lnf.call_count == 0


def test_capsules_hidden_keys_empty_when_javdb_also_answers(client, env, monkeypatch):
    five_s1(env)
    monkeypatch.setattr("web.routers.search.maker_capsule_policy", lambda: MakerCapsulePolicy(True, False))
    with patch("web.routers.search.list_not_found_keys", return_value=["x"]) as lnf:
        data = caps(client)
    assert data["maker_search_enabled"] is True and data["hidden_keys"] == []
    assert by_maker(data)["S1"]["total"] == 5
    assert lnf.call_count == 0


def test_capsules_hidden_keys_from_table_when_javbus_only(client, env):
    five_s1(env)
    with patch("web.routers.search.list_not_found_keys", return_value=["x", "y"]) as lnf:
        data = caps(client)
    assert data["hidden_keys"] == ["x", "y"] and lnf.call_count == 1


def test_capsules_missing_db_file_is_empty(client, env):
    env.db.unlink()
    data = caps(client)
    assert data["success"] is True and data["makers"] == [] and data["hidden_keys"] == []


def test_capsules_failure_hides_exception_text(client, env):
    with patch("web.routers.search.VideoRepository", side_effect=RuntimeError(SECRET)):
        r = client.get(CAPS)
    assert r.json()["success"] is False
    assert SECRET not in r.text


def test_capsules_is_sync_def():
    import inspect
    from web.routers import search as mod
    fn = mod.get_maker_capsules
    assert not inspect.iscoroutinefunction(fn)


# ---------------- SSE ----------------

def test_sse_found_event_order_and_no_actress_helpers(client, env, parse_sse_events):
    five_s1(env)
    with patch("web.routers.search._detect_mode") as dm, \
         patch("web.routers.search._analyze_top_actor") as ata, \
         patch("web.routers.search._fetch_actress_profile_with_db") as fap, \
         maker_patches():
        text, events = sse(client, parse_sse_events)
    types = [e["type"] for e in events]
    assert types[0] == "mode" and events[0]["mode"] == "maker"
    assert "status" in types
    seed = next(e for e in events if e["type"] == "seed")
    assert seed["total"] == 30
    assert types.index("seed") < types.index("result-item")
    assert types.count("result-item") == 30
    assert types.index("result-complete") < types.index("result")
    assert types[-1] == "result"
    res = sse_result(events)
    assert res["success"] is True and res["maker_key"] == KEY and res["total"] == 30
    assert next(e for e in events if e["type"] == "result-complete")["actress_profile"] is None
    assert dm.call_count == 0 and ata.call_count == 0 and fap.call_count == 0
    assert maker_javbus_map.get_mapping(KEY, db_path=env.db)["status"] == "found"


def test_first_click_resolves_from_library_titles(client, env):
    five_s1(env)
    with maker_patches() as m:
        body = rest(client).json()
    assert body["success"] is True
    called = set(m.sample.fetcher.calls)
    assert called and called <= {f"SONE-{200 + i}" for i in range(5)}
    assert len(called) == 2  # 兩票同值即停


# ---------------- REST paging / has_more ----------------

def test_second_page_reports_has_more_from_request_page(client, env):
    five_s1(env)
    with maker_patches(studio=studio_pages({1: nums(30), 2: nums(30, 100)})) as m:
        body = rest(client, offset=30).json()
        assert m.studio.call_count == 1
        assert m.studio.call_args_list[0].args[1] == 2
    assert body["success"] is True and body["total"] == 30 and body["has_more"] is True
    assert body["mode"] == "maker" and body["maker_key"] == KEY and body["offset"] == 30
    with maker_patches(studio=studio_pages({2: nums(12, 100)})):
        body = rest(client, offset=30).json()
    assert body["total"] == 12 and body["has_more"] is False


def test_second_request_skips_sample_fetch_but_still_lists(client, env):
    five_s1(env)
    with maker_patches() as m:
        first = rest(client).json()
        assert m.sample.call_count >= 1
        m.sample.reset_mock()
        second = rest(client).json()
        assert m.sample.call_count == 0
        assert m.studio.call_count == 2
        assert m.sj.call_count == 60
    assert first["success"] and second["success"]
    assert len(first["data"]) == len(second["data"]) == 30


# ---------------- failure shapes ----------------

def test_resolve_unreachable_writes_nothing_then_recovers(client, env):
    five_s1(env)
    bad = MagicMock()
    bad.get.side_effect = requests.ConnectionError("down")
    with patch.object(JavBusScraper, "_new_session", return_value=bad), \
         patch("core.scrapers.javbus.rate_limit"):
        body = rest(client).json()
    assert body["success"] is False and body["error_code"] == "maker_unreachable"
    assert maker_javbus_map.list_not_found_keys(db_path=env.db) == []
    assert maker_javbus_map.get_mapping(KEY, db_path=env.db) is None
    with maker_patches():
        body = rest(client).json()
    assert body["success"] is True
    assert maker_javbus_map.get_mapping(KEY, db_path=env.db)["status"] == "found"


def assert_found_not_hidden(env):
    row = maker_javbus_map.get_mapping(KEY, db_path=env.db)
    assert row["status"] == "found" and row["studio_id"] == "7q"
    assert maker_javbus_map.list_not_found_keys(db_path=env.db) == []


@pytest.mark.parametrize("exc", [SourceBlocked("b"), SourceUnreachable("u"), TimeoutError("t")])
def test_list_failure_after_resolve_is_unreachable_not_empty(client, env, exc, parse_sse_events):
    five_s1(env)
    with maker_patches(studio=MagicMock(side_effect=exc)):
        body = rest(client).json()
    assert body["success"] is False and body["error_code"] == "maker_unreachable"
    assert_found_not_hidden(env)


def test_not_found_skips_list_and_detail(client, env):
    five_s1(env)
    with maker_patches(sample_outcomes=[STUDIO_MISS] * 5) as m:
        body = rest(client).json()
    assert body["success"] is False and body["error_code"] == "maker_not_found"
    assert body["maker_key"] == KEY
    assert m.studio.call_count == 0 and m.sj.call_count == 0
    assert maker_javbus_map.get_mapping(KEY, db_path=env.db)["status"] == "not_found"


def test_no_sample_and_empty_pass_through_both_transports(client, env, parse_sse_events):
    # maker_no_sample：片庫沒有這家的樣本
    with maker_patches():
        assert rest(client).json()["error_code"] == "maker_no_sample"
        _, ev = sse(client, parse_sse_events)
    res = sse_result(ev)
    assert res["success"] is False and res["error_code"] == "maker_no_sample"
    # maker_empty：解析成功但該頁沒有番號
    five_s1(env)
    with maker_patches(studio=studio_pages({1: []})):
        assert rest(client).json()["error_code"] == "maker_empty"
        _, ev = sse(client, parse_sse_events)
    res = sse_result(ev)
    assert res["success"] is False and res["error_code"] == "maker_empty"


def test_found_but_all_details_missing_has_no_error_code(client, env):
    five_s1(env)
    ids = nums(3)
    with maker_patches(studio=studio_pages({1: ids}), sj=detail(missing=set(ids))):
        body = rest(client).json()
    assert body["success"] is False and "error_code" not in body


@pytest.mark.parametrize("where", ["resolver", "list"])
@pytest.mark.parametrize("transport", ["rest", "sse"])
def test_unexpected_exception_maps_to_maker_unreachable(client, env, parse_sse_events, where, transport):
    five_s1(env)
    boom = RuntimeError(SECRET)
    studio = MagicMock(side_effect=boom) if where == "list" else None
    url = REST if transport == "rest" else SSE
    with maker_patches(studio=studio):
        if where == "resolver":
            with patch("core.scraper.resolve_maker_studio", side_effect=boom):
                resp = client.get(url, params=PARAMS)
        else:
            resp = client.get(url, params=PARAMS)
    assert resp.status_code == 200
    assert SECRET not in resp.text
    if transport == "rest":
        body = resp.json()
    else:
        events = parse_sse_events(resp.text)
        assert events[-1]["type"] == "result"
        assert not [e for e in events if e["type"] == "error"]
        body = sse_result(events)
    assert body["success"] is False and body["error_code"] == "maker_unreachable"
    assert maker_javbus_map.list_not_found_keys(db_path=env.db) == []


# ---------------- validation ----------------

def test_bad_offset_rest_400_and_sse_error(client, env, parse_sse_events):
    with patch("web.routers.search.search_maker_latest") as sm:
        r = rest(client, offset=15)
        assert r.status_code == 400
        assert r.json()["success"] is False and r.json()["error"]
        _, events = sse(client, parse_sse_events, offset=15)
    assert [e["type"] for e in events] == ["error"]
    assert sm.call_count == 0


def test_too_many_spellings_is_400(client, env):
    with patch("web.routers.search.search_maker_latest") as sm:
        r = client.get(REST, params={"maker_key": KEY, "spellings": [f"s{i}" for i in range(21)]})
    assert r.status_code == 400
    assert sm.call_count == 0


@pytest.mark.parametrize("params", [
    {"maker_key": ""},
    {"maker_key": "x" * 201},
    {"maker_key": KEY, "spellings": ["y" * 201]},
])
def test_other_invalid_maker_params_are_400(client, env, params):
    with patch("web.routers.search.search_maker_latest") as sm:
        assert client.get(REST, params=params).status_code == 400
    assert sm.call_count == 0


def test_missing_q_and_maker_key_keeps_existing_error(client, env, parse_sse_events):
    assert client.get(REST).json()["error"] == "請輸入有效的搜尋關鍵字"
    r = client.get(SSE)
    assert json.loads(r.text.strip()[len("data: "):])["message"] == "請輸入有效的搜尋關鍵字"


def test_spellings_default_to_label(client, env):
    five_s1(env)
    with patch("web.routers.search.search_maker_latest") as sm:
        sm.return_value = MagicMock(results=[], has_more=False, error_code="maker_empty")
        client.get(REST, params={"maker_key": KEY, "maker": "S1"})
    assert sm.call_args.args[:3] == (KEY, "S1", ["S1"])
