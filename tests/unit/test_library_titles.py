"""core/library_titles 邏輯片單 helper 與 VideoRepository.get_library_title_rows 測試（173-T1）

真 sqlite（temp_db fixture），不 mock 連線。
"""
import pytest

from core.database import Video, VideoRepository
from core.library_titles import (
    first_members,
    logical_title_firsts,
    release_parts,
    rows_in_library_dirs,
)
from core.path_utils import to_file_uri

LIB = "C:/Lib"
LIB_URI = to_file_uri(LIB)
OUT = "C:/Elsewhere"


def _video(base, name, number, **kw):
    return Video(path=to_file_uri(f"{base}/{name}"), number=number, title=number, **kw)


@pytest.fixture
def repo(temp_db):
    r = VideoRepository(temp_db)
    r.upsert_batch([
        _video(LIB, "AAA-001.mp4", "AAA-001", maker="  片商甲 ", director="導演甲", release_date="2020-06-15"),
        _video(LIB, "MUL-001-cd1.mp4", "MUL-001", maker="片商乙", director="導演乙", release_date="2019-08-01"),
        _video(LIB, "MUL-001-cd2.mp4", "MUL-001", maker="片商乙", director="導演乙", release_date="2019-08-01"),
        _video(OUT, "OUT-001.mp4", "OUT-001", maker="目錄外片商", director="導演丙", release_date="2018-01-01"),
    ])
    return r


def test_light_rows_carry_maker_and_release_date(repo):
    rows = {v.number + v.path[-8:]: v for v in repo.get_library_title_rows()}
    row = next(v for v in rows.values() if v.number == "AAA-001")
    assert row.maker == "  片商甲 "
    assert row.release_date == "2020-06-15"
    assert row.path == to_file_uri(f"{LIB}/AAA-001.mp4")
    assert row.director in (None, "")  # 不取 director，不得把導演當片商


def test_rows_outside_library_dirs_excluded(repo):
    kept = rows_in_library_dirs(repo.get_library_title_rows(), [LIB_URI])
    numbers = {v.number for v in kept}
    assert "OUT-001" not in numbers
    assert {"AAA-001", "MUL-001"} <= numbers
    assert len(kept) == 3


def test_multipart_counts_as_one_title(repo):
    firsts = logical_title_firsts(repo.get_library_title_rows(), [LIB_URI], {})
    assert len(firsts) == 2
    mul = next(v for v in firsts if v.number == "MUL-001")
    assert mul.path.endswith("MUL-001-cd1.mp4")
    # 組合版 == 兩步版
    two_step = first_members(rows_in_library_dirs(repo.get_library_title_rows(), [LIB_URI]), {})
    assert [v.path for v in two_step] == [v.path for v in firsts]


def test_partial_month_date_is_none():
    assert release_parts("2026-09") == (2026, "2026-09", None)


@pytest.mark.parametrize("raw, expected", [
    ("2020-06-15", (2020, "2020-06", "2020-06-15")),
    ("2021", (2021, None, None)),
    ("2021-13-01", (2021, None, None)),
    ("2022-02-32", (2022, "2022-02", None)),
    ("garbage", (None, None, None)),
    (None, (None, None, None)),
])
def test_release_parts_cases(raw, expected):
    assert release_parts(raw) == expected
