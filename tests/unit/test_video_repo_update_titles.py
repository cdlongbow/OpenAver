"""VideoRepository.update_titles 單欄 mutator 測試（172-T2）

真 sqlite（temp_db fixture），以 SELECT * 與 get_showcase_revision() 觀察，不 mock 連線。
"""
import pytest

from core.database import Video, VideoRepository, get_connection
from core.database.version_tracker import get_showcase_revision
from core.path_utils import to_file_uri

PATH = to_file_uri("C:/Videos/T2-001.mp4")
COVER = to_file_uri("C:/Videos/T2-001.jpg")
OLD_STAMP = "2000-01-01 00:00:00"
CHANGED = {"title", "original_title", "nfo_mtime", "updated_at"}


def _row(repo, path=PATH):
    conn = get_connection(repo.db_path)
    try:
        cur = conn.execute("SELECT * FROM videos WHERE path = ?", (path,))
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row, strict=True)) if row else None
    finally:
        conn.close()


def _raw_update(repo, sql, params=()):
    conn = get_connection(repo.db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def repo(temp_db, seed_crop_mode):
    r = VideoRepository(temp_db)
    r.upsert(Video(
        path=PATH, number="T2-001", title="原標題", original_title="原文",
        user_tags=["標籤甲", "標籤乙"], cover_path=COVER,
        output_dir=to_file_uri("C:/Videos/out"),
        scrape_attempted_at=1234.5, nfo_mtime=100.0,
    ))
    assert r.set_user_rating(PATH, 1)  # upsert 不寫 user_rating（CD-123-3）
    assert r.update_auto_focal(PATH, "0.3,0.4", expected_cover_path=COVER)
    assert seed_crop_mode(r, PATH, "default")
    _raw_update(r, "UPDATE videos SET updated_at = ?, scrape_attempted_at = ? WHERE path = ?",
                (OLD_STAMP, 1234.5, PATH))
    return r


def test_update_titles_happy_path_reads_back(repo):
    assert repo.update_titles(PATH, "譯文", "日本語原文", 555.0) is True
    v = repo.get_by_path(PATH)
    assert v.title == "譯文"
    assert v.original_title == "日本語原文"
    assert v.nfo_mtime == 555.0


def test_update_titles_leaves_other_columns_untouched(repo):
    before = _row(repo)
    # 種子欄位確實非預設，否則比對空轉
    assert before["user_tags"] not in (None, "", "[]")
    assert before["cover_path"] == COVER
    assert before["output_dir"]
    assert before["scrape_attempted_at"] == 1234.5
    assert before["user_rating"] == 1
    assert before["auto_focal"] == "0.3,0.4"
    assert before["crop_mode"] == "default"
    assert repo.update_titles(PATH, "譯文", "", 999.0) is True
    after = _row(repo)
    keep = set(before) - CHANGED
    assert {k: before[k] for k in keep} == {k: after[k] for k in keep}
    assert after["updated_at"] != OLD_STAMP
    assert after["title"] == "譯文"


def test_update_titles_bumps_showcase_revision(repo):
    before = get_showcase_revision()
    assert repo.update_titles(PATH, "譯文", "原文", 1.0) is True
    assert get_showcase_revision() > before


def test_update_titles_missing_path_returns_false(repo):
    missing = to_file_uri("C:/Videos/none.mp4")
    assert repo.get_by_path(missing) is None
    assert repo.update_titles(missing, "x", "y", 1.0) is False
    assert repo.get_by_path(missing) is None


def test_update_titles_empty_original_title_stored_as_empty(repo):
    assert repo.get_by_path(PATH).original_title == "原文"
    assert repo.update_titles(PATH, "復原後標題", "", 2.0) is True
    assert _row(repo)["original_title"] == ""
    assert repo.get_by_path(PATH).title == "復原後標題"
