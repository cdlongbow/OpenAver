"""Unit tests for core/database/migrate.py::backfill_readonly_nfo_mtime (TASK-104).

Real temp SQLite DB (via core.database.connection.init_db) + real tmp files —
pure-logic unit test per CLAUDE.md 測試檔案放置規則 (no network / external service).
"""
import sqlite3
from pathlib import Path
from unittest.mock import patch


from core.database.connection import init_db
from core.database.video import Video, VideoRepository
from core.database.migrate import backfill_readonly_nfo_mtime, backfill_readonly_nfo_mtime_once
from core.version import VERSION
from core.path_utils import to_file_uri


def _make_video(path_uri: str, cover_path: str = "", nfo_mtime: float = 0.0,
                output_dir: str = "/ro/out") -> Video:
    return Video(
        path=path_uri,
        number="TEST-001",
        title="test",
        cover_path=cover_path,
        nfo_mtime=nfo_mtime,
        output_dir=output_dir,
    )


class TestBackfillReadonlyNfoMtime:
    def test_heals_row_with_sibling_nfo(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        cover_fs = tmp_path / "TEST-001.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        nfo_fs = tmp_path / "TEST-001.nfo"
        nfo_fs.write_text("<movie></movie>")

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "TEST-001.mp4"), {})
        repo.upsert(_make_video(video_uri, cover_path=cover_uri, nfo_mtime=0.0))

        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

        assert healed == 1
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == nfo_fs.stat().st_mtime
        assert row.nfo_mtime > 0


def _marker(db_path):
    conn = sqlite3.connect(db_path)
    try:
        r = conn.execute("SELECT value FROM app_meta WHERE key='backfill_readonly_nfo_mtime'").fetchone()
    finally:
        conn.close()
    return None if r is None else r[0]


def _add(repo, tmp_path, stem, *, with_nfo, output_dir="/ro/out", nfo_mtime=0.0):
    cover = tmp_path / f"{stem}.jpg"
    cover.write_bytes(b"x")
    nfo = tmp_path / f"{stem}.nfo"
    if with_nfo:
        nfo.write_text("<movie/>")
    uri = to_file_uri(str(tmp_path / f"{stem}.mp4"), {})
    repo.upsert(_make_video(uri, cover_path=to_file_uri(str(cover), {}),
                            nfo_mtime=nfo_mtime, output_dir=output_dir))
    return uri, nfo


def test_once_second_run_returns_none_without_disk_access(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    ro_uri, ro_nfo = _add(repo, tmp_path, "RO-001", with_nfo=True)
    gen_uri, _ = _add(repo, tmp_path, "GEN-002", with_nfo=True, output_dir="")
    miss_uri, _ = _add(repo, tmp_path, "RO-002", with_nfo=False)
    done_uri, _ = _add(repo, tmp_path, "RO-003", with_nfo=True, nfo_mtime=999.0)

    first = backfill_readonly_nfo_mtime_once(db_path=db_path, path_mappings={})
    assert first == 1
    assert repo.get_by_path(ro_uri).nfo_mtime == ro_nfo.stat().st_mtime
    assert repo.get_by_path(gen_uri).nfo_mtime == 0.0
    assert repo.get_by_path(miss_uri).nfo_mtime == 0.0
    assert repo.get_by_path(done_uri).nfo_mtime == 999.0
    assert _marker(db_path) == VERSION

    with patch.object(Path, "exists", return_value=False) as ex, \
            patch("core.database.migrate.nfo_mtime_or_none") as st:
        assert backfill_readonly_nfo_mtime_once(db_path=db_path, path_mappings={}) is None
    assert ex.call_count == 0
    assert st.call_count == 0


