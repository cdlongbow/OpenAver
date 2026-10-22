"""tests/unit/test_maker_studio_resolver.py — 片商代號解析器（TASK-173-T4）。

DB 一律 tmp_path、今天一律注入、取回器替身或替身 _session，不連外網。
"""
import datetime
from types import SimpleNamespace

import pytest

from core.database import maker_javbus_map
from core.database.connection import init_db
from core.maker_latest import Resolution, decide, pick_samples, resolve_maker_studio
from core.scrapers.javbus import STUDIO_MISS, STUDIO_UNREACHABLE, JavBusScraper, StudioVote

TODAY = datetime.date(2026, 10, 21)
KEY = "s1"
V7Q = StudioVote("censored", "7q")
VA = StudioVote("censored", "A")
VB = StudioVote("censored", "B")
M, U = STUDIO_MISS, STUDIO_UNREACHABLE


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "x.db"
    init_db(path)
    return path


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def T(number, days=100, maker="S1", date=None):
    return SimpleNamespace(number=number, maker=maker, release_date=date if date is not None else days_ago(days))


def five_titles():
    return [T(f"SONE-{200 + i}", 100 + i) for i in range(5)]


class Fetcher:
    """依序回不同結果並記錄被呼叫的番號。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, number):
        self.calls.append(number)
        return self.outcomes[len(self.calls) - 1]

    @property
    def call_count(self):
        return len(self.calls)


def run(fetcher, db, titles=None):
    return resolve_maker_studio(
        KEY, "S1", ["S1"], titles if titles is not None else five_titles(),
        today=TODAY, fetch_sample=fetcher, db_path=db,
    )


# ---------------- oracle 表 ----------------

@pytest.mark.parametrize("outcomes,status,studio_id,calls", [
    ([V7Q, V7Q], "found", "7q", 2),
    ([V7Q, M, M, M, M], "found", "7q", 5),
    ([VA, VB, VB], "found", "B", 3),
    ([V7Q, U, M, M, M], "found", "7q", 5),
])
def test_found_outcomes_write_found_row(db, outcomes, status, studio_id, calls):
    f = Fetcher(outcomes)
    r = run(f, db)
    assert (r.status, r.kind, r.studio_id) == (status, "censored", studio_id)
    assert f.call_count == calls
    row = maker_javbus_map.get_mapping(KEY, db_path=db)
    assert (row["status"], row["kind"], row["studio_id"], row["label"]) == ("found", "censored", studio_id, "S1")


def test_tie_prefers_vote_of_newer_sample(db):
    # 較新者（距今 <30 天）排在取樣序列較後面，證明比的是日期不是出場順序
    titles = [T("SONE-1", 100), T("SONE-2", 5)]
    f = Fetcher([VA, VB])
    r = run(f, db, titles)
    assert f.calls == ["SONE-1", "SONE-2"]
    assert r.studio_id == "B"
    assert decide([(VA, days_ago(100)), (VB, days_ago(200))]).studio_id == "A"


def test_all_miss_is_absent_and_writes_not_found(db):
    f = Fetcher([M] * 5)
    r = run(f, db)
    assert r.status == "absent" and f.call_count == 5
    assert maker_javbus_map.get_mapping(KEY, db_path=db)["status"] == "not_found"


@pytest.mark.parametrize("outcomes", [[M, M, U], [U] * 5], ids=["miss-miss-unreachable", "unreachable-x5"])
def test_unreachable_outcomes_never_write_not_found(db, outcomes):
    n = len(outcomes)
    f = Fetcher(outcomes)
    r = run(f, db, titles=five_titles()[:n])
    assert r.status == "unreachable"
    assert (r.kind, r.studio_id) == ("", "")
    assert f.call_count == n
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


def test_zero_samples_returns_no_sample_and_writes_nothing(db):
    f = Fetcher([])
    r = run(f, db, titles=[])
    assert r.status == "no_sample"
    assert f.call_count == 0
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None
    assert decide([]).status == "no_sample"
    # 片庫有片但沒有一部屬於這家片商 → 同樣零樣本
    assert run(f, db, titles=[T("SONE-1", maker="OTHER")]).status == "no_sample"
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


def test_existing_found_row_short_circuits(db):
    maker_javbus_map.record_found(KEY, "uncensored", "3a", "S1", db_path=db)
    f = Fetcher([])
    r = run(f, db)
    assert r == Resolution("found", "uncensored", "3a")
    assert f.call_count == 0


def test_existing_not_found_row_short_circuits_and_table_unchanged(db):
    maker_javbus_map.record_not_found(KEY, "S1", db_path=db)
    before = maker_javbus_map.get_mapping(KEY, db_path=db)
    f = Fetcher([])
    assert run(f, db).status == "absent"
    assert f.call_count == 0
    assert maker_javbus_map.get_mapping(KEY, db_path=db) == before


def test_unexpected_exception_propagates_and_writes_nothing(db):
    def boom(number):
        raise RuntimeError("bug")
    with pytest.raises(RuntimeError):
        run(boom, db)
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


# ---------------- 取樣 ----------------

def nums(picked):
    return [n for n, _ in picked]


def test_pick_samples_prefers_titles_older_than_30_days():
    titles = [T(f"OLD-{i}", 60 + i) for i in range(5)] + [T(f"NEW-{i}", 1 + i) for i in range(3)]
    picked = nums(pick_samples(titles, TODAY))
    assert picked == ["OLD-0", "OLD-1", "OLD-2", "OLD-3", "OLD-4"]


def test_pick_samples_tops_up_with_recent_when_old_short():
    titles = [T("OLD-0", 40), T("OLD-1", 90)] + [T(f"NEW-{i}", 2 + 3 * i) for i in range(4)]
    assert nums(pick_samples(titles, TODAY)) == ["OLD-0", "OLD-1", "NEW-0", "NEW-1", "NEW-2"]


def test_pick_samples_30_day_boundary():
    titles = [T("DAY-29", 29), T("DAY-30", 30)]
    assert nums(pick_samples(titles, TODAY, k=1)) == ["DAY-30"]
    assert nums(pick_samples(titles, TODAY)) == ["DAY-30", "DAY-29"]


def test_pick_samples_undated_last_and_invalid_dates_count_as_undated():
    titles = [T("BAD-1", date="2026-09"), T("BAD-2", date="2026-02-31"), T("NONE", date=""), T("OK-1", 3)]
    assert nums(pick_samples(titles, TODAY)) == ["OK-1", "BAD-1", "BAD-2", "NONE"]


def test_pick_samples_dedupes_case_insensitive_number():
    titles = [T("sone-205", 100), T("SONE-205", 90)]
    assert len(pick_samples(titles, TODAY)) == 1


def test_pick_samples_filters_spellings_and_invalid_numbers():
    scraper = JavBusScraper()
    assert scraper.validate_number("???") is False
    titles = [T("SONE-1", maker=" S1 "), T("SONE-2", maker="OTHER"), T("???", maker="S1")]
    picked = pick_samples(titles, TODAY, spellings={"S1"}, validate=scraper.validate_number)
    assert nums(picked) == ["SONE-1"]


def test_fetcher_called_with_picked_numbers_in_order_at_most_five(db):
    titles = [T(f"SONE-{i}", 100 + i) for i in range(8)]
    f = Fetcher([M] * 8)
    run(f, db, titles)
    assert f.calls == [f"SONE-{i}" for i in range(5)]


@pytest.mark.parametrize("bad", [None, "", "   "], ids=["none", "empty", "blank"])
def test_titles_without_number_are_skipped_not_crashing(db, bad):
    # 片庫有檔名認不出番號的檔（別家與同家各一）→ 照樣從有番號的片取樣
    titles = [T(bad, maker="OTHER"), T(bad, maker="S1")] + five_titles()[:2]
    assert nums(pick_samples(titles, TODAY, spellings={"S1"})) == ["SONE-200", "SONE-201"]
    f = Fetcher([V7Q, V7Q])
    r = run(f, db, titles)
    assert r.status == "found" and f.call_count == 2
