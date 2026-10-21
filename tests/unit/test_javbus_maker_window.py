"""test_javbus_maker_window.py — JavBus 片商路徑的任意視窗與前綴探針（TASK-175b-T8a）。

DB 一律 tmp_path、JavBus 一律在使用端（類別層級）替身，不連外網。
"""
import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.database import init_db, maker_javbus_map
from core.scrapers.javbus import JavBusScraper, StudioVote
from core.search_providers.javbus import JavBusProvider

TODAY = datetime.date(2026, 10, 21)
KEY = "sod create"
LABEL = "SOD Create"
V7Q = StudioVote("censored", "7q")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    init_db(path)
    monkeypatch.setattr("core.scraper.MAX_WORKERS", 1)
    monkeypatch.setattr("core.scraper.REQUEST_DELAY", 0)
    return path


def _nums(n, start=1):
    return [f"MKR-{i:03d}" for i in range(start, start + n)]


def _detail(num, source=None, *a, **kw):
    return {"number": num, "title": f"t-{num}", "source": "javbus"}


def _studio_pages(pages):
    """依頁碼回不同清單；沒列的頁碼丟錯（表示不該被請求）。"""
    def fake(ref, page=1):
        if page not in pages:
            raise TimeoutError(f"page {page} must not be requested")
        return pages[page]
    return fake


class Fetcher:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, number):
        self.calls.append(number)
        return self.outcomes[len(self.calls) - 1]


def _mapped(db):
    maker_javbus_map.record_found(KEY, "censored", "7q", LABEL, db_path=db)


def _run(db, limit, offset, titles=()):
    return JavBusProvider().run_maker(
        KEY, LABEL, [LABEL], offset, titles=list(titles), today=TODAY, db_path=db, limit=limit)


def _listing(pages):
    return patch.object(JavBusScraper, "get_ids_from_studio", side_effect=_studio_pages(pages))


def _numbers(out):
    return sorted(c["number"] for c in out.results)


# ---------------------------------------------------------------- 視窗
def test_window_batches_cover_first_sixty_without_overlap(db):
    _mapped(db)
    pages = {1: _nums(30), 2: _nums(30, 31), 3: _nums(30, 61)}
    got = []
    with _listing(pages) as st, patch("core.scraper.search_jav", side_effect=_detail):
        for offset in (0, 20, 40):
            st.reset_mock()
            out = _run(db, 20, offset)
            assert out.error_code is None
            got.append((_numbers(out), [c.args[1] for c in st.call_args_list]))
    flat = [n for batch, _ in got for n in batch]
    assert sorted(flat) == _nums(60)
    assert all(len(b) == 20 for b, _ in got)
    assert got[1][1] == [1, 2]  # 第二批：第 1、2 頁共兩次列表請求


def test_window_has_more_true_when_more_pages_exist(db):
    _mapped(db)
    with _listing({1: _nums(30)}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0)
    assert len(out.results) == 20 and out.has_more is True


def test_window_short_first_page_has_no_more_and_requests_one_page(db):
    _mapped(db)
    with _listing({1: _nums(12)}) as st, patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0)
    assert len(out.results) == 12 and out.has_more is False and out.error_code is None
    assert st.call_count == 1


def test_window_beyond_end_is_maker_empty(db):
    _mapped(db)
    with _listing({1: _nums(12)}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 20)
    assert out.error_code == "maker_empty" and out.results == []


def test_window_list_failure_is_unreachable(db):
    _mapped(db)
    with _listing({}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0)
    assert out.error_code == "maker_unreachable"


def test_limit_none_still_rejects_unaligned_offset(db):
    with pytest.raises(ValueError):
        JavBusProvider().run_maker(KEY, LABEL, [LABEL], 20, titles=[], today=TODAY, db_path=db)


# ---------------------------------------------------------------- 探針
@pytest.fixture
def prefixes(monkeypatch):
    monkeypatch.setattr("core.maker_mapping.load_prefix_mapping", lambda: {
        "STARS": LABEL, "SOD": LABEL, "SDDE": LABEL, "ABP": "Prestige"})


def _search(by_prefix):
    def fake(self, keyword, page=1, search_type=0):
        if isinstance(by_prefix.get(keyword), Exception):
            raise by_prefix[keyword]
        return by_prefix.get(keyword, [])
    return patch.object(JavBusScraper, "get_ids_from_search", fake, create=False)


def _probe_run(db, by_prefix, outcomes=(V7Q,) * 5, titles=()):
    fetcher = Fetcher(outcomes)
    with _search(by_prefix), \
         patch.object(JavBusScraper, "fetch_studio_sample", side_effect=fetcher), \
         _listing({1: _nums(30)}), \
         patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0, titles)
    return out, fetcher


def test_probe_found_writes_mapping_and_lists(db, prefixes):
    out, fetcher = _probe_run(db, {"SOD": ["SOD-001", "SOD-002"], "STARS": ["STARS-001"]})
    assert out.error_code is None and len(out.results) == 20
    row = maker_javbus_map.get_mapping(KEY, db_path=db)
    assert row["status"] == "found" and row["studio_id"] == "7q"
    assert len(fetcher.calls) == 2  # 兩票一致即停


def test_probe_tries_more_prefixes_only_when_first_two_are_empty(db, prefixes):
    seen = []

    def fake(self, keyword, page=1, search_type=0):
        seen.append((keyword, page, search_type))
        return []

    with patch.object(JavBusScraper, "get_ids_from_search", fake):
        out = _run(db, 20, 0)
    assert out.error_code == "maker_no_sample"
    assert seen == [("SDDE", 1, 1), ("SOD", 1, 1), ("STARS", 1, 1)]


def _set_prefixes(monkeypatch, names):
    monkeypatch.setattr("core.maker_mapping.load_prefix_mapping", lambda: {n: LABEL for n in names})


def _recording_search(by_prefix, seen):
    def fake(self, keyword, page=1, search_type=0):
        seen.append(keyword)
        if isinstance(by_prefix.get(keyword), Exception):
            raise by_prefix[keyword]
        return by_prefix.get(keyword, [])
    return patch.object(JavBusScraper, "get_ids_from_search", fake)


def _swamped(names):
    """每個前綴只回更長前綴的番號（被擠滿），完全相同前綴過濾後全空。"""
    return {n: [f"{n}X-{i:03d}" for i in range(1, 4)] for n in names}


def _probe_recorded(db, by_prefix, seen):
    fetcher = Fetcher((V7Q,) * 5)
    with _recording_search(by_prefix, seen), \
         patch.object(JavBusScraper, "fetch_studio_sample", side_effect=fetcher), \
         _listing({1: _nums(30)}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0)
    return out, fetcher


def test_probe_continues_past_two_prefixes_when_first_two_are_swamped(db, monkeypatch):
    # 邊界 1：HMN→HMNF-*、HND→HNDS-*，第 3 個 HNDS 才拿到樣本
    _set_prefixes(monkeypatch, ["HMN", "HND", "HNDS"])
    by = {"HMN": ["HMNF-001", "HMNF-002"], "HND": ["HNDS-001"], "HNDS": ["HNDS-001", "HNDS-002"]}
    seen = []
    out, fetcher = _probe_recorded(db, by, seen)
    assert out.error_code is None and len(out.results) == 20
    assert seen == ["HMN", "HND", "HNDS"]
    assert fetcher.calls and all(n.startswith("HNDS-") for n in fetcher.calls)


def test_probe_two_prefixes_with_samples_makes_exactly_two_requests(db, monkeypatch):
    # 邊界 2：前 2 個就有樣本 → 恰 2 次請求（迴歸鎖）
    _set_prefixes(monkeypatch, ["ADN", "AKB", "ZZZ"])
    by = {"ADN": ["ADN-001"], "AKB": ["AKB-001"], "ZZZ": ["ZZZ-001"]}
    seen = []
    out, fetcher = _probe_recorded(db, by, seen)
    assert out.error_code is None
    assert seen == ["ADN", "AKB"]
    assert sorted(fetcher.calls) == ["ADN-001", "AKB-001"]


def test_probe_stops_after_four_requests_when_all_swamped(db, monkeypatch):
    # 邊界 3：6 個前綴全被蓋住 → 恰 4 次後停、無樣本、表無新增列
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    _set_prefixes(monkeypatch, names)
    seen = []
    out, fetcher = _probe_recorded(db, _swamped(names), seen)
    assert out.error_code == "maker_no_sample"
    assert seen == ["AAA", "BBB", "CCC", "DDD"]
    assert fetcher.calls == []
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


def test_probe_single_prefix_makes_one_request(db, monkeypatch):
    # 邊界 4：只有 1 個前綴 → 1 次請求
    _set_prefixes(monkeypatch, ["AAA"])
    seen = []
    out, _ = _probe_recorded(db, _swamped(["AAA"]), seen)
    assert out.error_code == "maker_no_sample"
    assert seen == ["AAA"]


def test_probe_third_prefix_exception_is_unreachable_and_writes_nothing(db, monkeypatch):
    # 邊界 5：第 3 個前綴丟例外 → maker_unreachable、表無新增列
    names = ["AAA", "BBB", "CCC"]
    _set_prefixes(monkeypatch, names)
    by = _swamped(["AAA", "BBB"])
    by["CCC"] = TimeoutError("t")
    seen = []
    out, fetcher = _probe_recorded(db, by, seen)
    assert out.error_code == "maker_unreachable"
    assert seen == names
    assert fetcher.calls == []
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


def test_probe_drops_other_makers_numbers(db, prefixes):
    out, fetcher = _probe_run(db, {"SDDE": ["ABC-001", "ABC-002", "SDDE-001"]})
    assert out.error_code is None
    assert fetcher.calls == ["SDDE-001"]


def test_probe_caps_samples_at_five(db, prefixes):
    ids = [f"SDDE-{i:03d}" for i in range(1, 9)]
    _, fetcher = _probe_run(db, {"SDDE": ids}, outcomes=tuple(StudioVote("censored", str(i)) for i in range(5)))
    assert len(fetcher.calls) <= 5


def test_probe_no_numbers_is_no_sample_and_writes_nothing(db, prefixes):
    out, fetcher = _probe_run(db, {})
    assert out.error_code == "maker_no_sample"
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None
    assert fetcher.calls == []


def test_probe_timeout_is_unreachable_and_writes_nothing(db, prefixes):
    out, fetcher = _probe_run(db, {"SDDE": TimeoutError("t"), "SOD": ["SOD-001"]})
    assert out.error_code == "maker_unreachable"
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None
    assert fetcher.calls == []


def test_probe_skipped_when_maker_already_mapped(db, prefixes):
    _mapped(db)
    with patch.object(JavBusScraper, "get_ids_from_search", return_value=["SOD-001"]) as gis, \
         _listing({1: _nums(30)}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0)
    assert out.error_code is None
    assert gis.call_count == 0


def test_probe_skipped_when_library_has_samples(db, prefixes):
    titles = [SimpleNamespace(maker=LABEL, number=f"SOD-{i:03d}", release_date="2026-01-01")
              for i in range(1, 4)]
    fetcher = Fetcher((V7Q, V7Q))
    with patch.object(JavBusScraper, "get_ids_from_search", return_value=["SDDE-001"]) as gis, \
         patch.object(JavBusScraper, "fetch_studio_sample", side_effect=fetcher), \
         _listing({1: _nums(30)}), patch("core.scraper.search_jav", side_effect=_detail):
        out = _run(db, 20, 0, titles)
    assert out.error_code is None
    assert gis.call_count == 0
    assert all(n.startswith("SOD-") for n in fetcher.calls)


def test_probe_passes_in_memory_synthetic_titles_to_resolver(db, prefixes, monkeypatch):
    captured = {}

    def fake_resolve(maker_key, label, spellings, titles, **kw):
        captured.update(spellings=list(spellings), titles=list(titles))
        return SimpleNamespace(status="no_sample")

    monkeypatch.setattr("core.scraper.resolve_maker_studio", fake_resolve)
    with _search({"SDDE": ["SDDE-001", "XYZ-009"]}):
        out = _run(db, 20, 0)
    assert out.error_code == "maker_no_sample"
    assert [(t.maker, t.number, t.release_date) for t in captured["titles"]] == [(LABEL, "SDDE-001", None)]
    assert LABEL in captured["spellings"]
