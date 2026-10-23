"""tests/unit/test_maker_studio_resolver.py — 片商代號解析器（TASK-173-T4）。

DB 一律 tmp_path、今天一律注入、取回器替身或替身 _session，不連外網。
"""
import datetime
from types import SimpleNamespace

import pytest

from core.database import maker_javbus_map
from core.database.connection import init_db
from core.maker_latest import Resolution, pick_samples, resolve_maker_studio
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
    ([VA, VB, VB], "found", "B", 3),
])
def test_found_outcomes_write_found_row(db, outcomes, status, studio_id, calls):
    f = Fetcher(outcomes)
    r = run(f, db)
    assert (r.status, r.kind, r.studio_id) == (status, "censored", studio_id)
    assert f.call_count == calls
    row = maker_javbus_map.get_mapping(KEY, db_path=db)
    assert (row["status"], row["kind"], row["studio_id"], row["label"]) == ("found", "censored", studio_id, "S1")


def test_all_miss_is_absent_and_writes_not_found(db):
    f = Fetcher([M] * 5)
    r = run(f, db)
    assert r.status == "absent" and f.call_count == 5
    assert maker_javbus_map.get_mapping(KEY, db_path=db)["status"] == "not_found"


@pytest.mark.parametrize("outcomes", [[M, M, U]], ids=["miss-miss-unreachable"])
def test_unreachable_outcomes_never_write_not_found(db, outcomes):
    n = len(outcomes)
    f = Fetcher(outcomes)
    r = run(f, db, titles=five_titles()[:n])
    assert r.status == "unreachable"
    assert (r.kind, r.studio_id) == ("", "")
    assert f.call_count == n
    assert maker_javbus_map.get_mapping(KEY, db_path=db) is None


def test_existing_found_row_short_circuits(db):
    maker_javbus_map.record_found(KEY, "uncensored", "3a", "S1", db_path=db)
    f = Fetcher([])
    r = run(f, db)
    assert r == Resolution("found", "uncensored", "3a")
    assert f.call_count == 0


# ---------------- 取樣 ----------------

def nums(picked):
    return [n for n, _ in picked]


def test_pick_samples_prefers_titles_older_than_30_days():
    titles = [T(f"OLD-{i}", 60 + i) for i in range(5)] + [T(f"NEW-{i}", 1 + i) for i in range(3)]
    picked = nums(pick_samples(titles, TODAY))
    assert picked == ["OLD-0", "OLD-1", "OLD-2", "OLD-3", "OLD-4"]


def test_pick_samples_filters_spellings_and_invalid_numbers():
    scraper = JavBusScraper()
    assert scraper.validate_number("???") is False
    titles = [T("SONE-1", maker=" S1 "), T("SONE-2", maker="OTHER"), T("???", maker="S1")]
    picked = pick_samples(titles, TODAY, spellings={"S1"}, validate=scraper.validate_number)
    assert nums(picked) == ["SONE-1"]


@pytest.mark.parametrize("bad", [None, ], ids=["none", ])
def test_titles_without_number_are_skipped_not_crashing(db, bad):
    # 片庫有檔名認不出番號的檔（別家與同家各一）→ 照樣從有番號的片取樣
    titles = [T(bad, maker="OTHER"), T(bad, maker="S1")] + five_titles()[:2]
    assert nums(pick_samples(titles, TODAY, spellings={"S1"})) == ["SONE-200", "SONE-201"]
    f = Fetcher([V7Q, V7Q])
    r = run(f, db, titles)
    assert r.status == "found" and f.call_count == 2
