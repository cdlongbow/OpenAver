"""Unit tests for core/database/migrate.py::backfill_readonly_nfo_mtime (TASK-104).

Real temp SQLite DB (via core.database.connection.init_db) + real tmp files —
pure-logic unit test per CLAUDE.md 測試檔案放置規則 (no network / external service).
"""
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

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

    def test_skips_missing_nfo(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        cover_fs = tmp_path / "TEST-002.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        # 刻意不建立 sibling .nfo

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "TEST-002.mp4"), {})
        repo.upsert(_make_video(video_uri, cover_path=cover_uri, nfo_mtime=0.0))

        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

        assert healed == 0
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == 0.0

    def test_ignores_healthy_rows(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        cover_fs = tmp_path / "TEST-003.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        nfo_fs = tmp_path / "TEST-003.nfo"
        nfo_fs.write_text("<movie></movie>")

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "TEST-003.mp4"), {})
        repo.upsert(_make_video(video_uri, cover_path=cover_uri, nfo_mtime=12345.0))

        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

        assert healed == 0
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == 12345.0

    def test_ignores_no_cover_rows(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        video_uri = to_file_uri(str(tmp_path / "TEST-004.mp4"), {})
        repo.upsert(_make_video(video_uri, cover_path="", nfo_mtime=0.0))

        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

        assert healed == 0
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == 0.0

    def test_idempotent_second_run_heals_zero(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        cover_fs = tmp_path / "TEST-005.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        nfo_fs = tmp_path / "TEST-005.nfo"
        nfo_fs.write_text("<movie></movie>")

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "TEST-005.mp4"), {})
        repo.upsert(_make_video(video_uri, cover_path=cover_uri, nfo_mtime=0.0))

        first = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})
        assert first == 1
        healed_mtime = repo.get_by_path(video_uri).nfo_mtime

        second = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})
        assert second == 0
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == healed_mtime


class TestBackfillReadonlyNfoMtimeFanartCover:
    """P0-1（TASK-112-T2c）：cover_path 指向 `<stem>-fanart.jpg` 時，NFO 推導不得再用
    `Path(cover_fs).with_suffix('.nfo')`（會推出永不存在的 `<stem>-fanart.nfo`），
    必須用 `cover_base_stem(cover_fs) + '.nfo'` 剝掉 -fanart 後綴才能找到真正的 `<stem>.nfo`。
    """

    def test_heals_row_with_fanart_cover(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        # 外部庫掃描情境：DB cover_path 記成 -fanart.jpg（find_cover_image L1.5 命中）
        cover_fs = tmp_path / "TEST-006-fanart.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        nfo_fs = tmp_path / "TEST-006.nfo"
        nfo_fs.write_text("<movie></movie>")

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "TEST-006.mp4"), {})
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


def test_app_meta_table_exists_and_init_idempotent(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "app_meta" in names


def test_general_rows_never_touch_disk(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    uri, _ = _add(repo, tmp_path, "GEN-001", with_nfo=True, output_dir="")

    # Per-row errors are swallowed by the backfill, so count calls instead of raising.
    with patch.object(Path, "exists", return_value=False) as ex, \
            patch("core.database.migrate.nfo_mtime_or_none") as st:
        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

    assert ex.call_count == 0
    assert st.call_count == 0
    assert healed == 0
    assert repo.get_by_path(uri).nfo_mtime == 0.0


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


def test_once_marks_even_when_no_nfo_found(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    _add(repo, tmp_path, "RO-010", with_nfo=False)
    _add(repo, tmp_path, "RO-011", with_nfo=False)

    assert backfill_readonly_nfo_mtime_once(db_path=db_path, path_mappings={}) == 0
    assert backfill_readonly_nfo_mtime_once(db_path=db_path, path_mappings={}) is None


def test_once_raise_leaves_no_marker(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    with patch("core.database.migrate.backfill_readonly_nfo_mtime",
               side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            backfill_readonly_nfo_mtime_once(db_path=db_path, path_mappings={})
    assert _marker(db_path) is None


def test_backfill_does_not_overwrite_concurrent_real_value(tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    uri, _ = _add(repo, tmp_path, "RO-020", with_nfo=True)
    other_uri, other_nfo = _add(repo, tmp_path, "RO-021", with_nfo=True)

    import core.database.migrate as migrate
    real = migrate.nfo_mtime_or_none

    def racing(nfo_path, **kw):
        if Path(nfo_path).name == "RO-020.nfo":
            c = sqlite3.connect(db_path)
            try:
                c.execute("UPDATE videos SET nfo_mtime = 777.0 WHERE path = ?", (uri,))
                c.commit()
            finally:
                c.close()
            return 1.5  # stale stat value
        return real(nfo_path, **kw)

    with patch("core.database.migrate.nfo_mtime_or_none", side_effect=racing):
        healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

    assert healed == 1
    assert repo.get_by_path(uri).nfo_mtime == 777.0
    assert repo.get_by_path(other_uri).nfo_mtime == other_nfo.stat().st_mtime
