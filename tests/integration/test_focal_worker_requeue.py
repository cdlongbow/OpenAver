"""TASK-152b-T2 — D7 end-to-end: ABANDONED must not stamp focal_attempted_at.

Uses a real temp sqlite DB. Injects a fake detect_fn that returns
RunnerOutcome(kind="ABANDONED", ...); never calls subprocess_runner.
"""
import tempfile
from pathlib import Path

import pytest

from core.database import Video, VideoRepository, init_db
from core.focal.subprocess_runner import RunnerOutcome
from core.focal.worker import FocalWorker
from core.path_utils import to_file_uri


@pytest.fixture
def temp_db():
    """建立臨時資料庫（等同 tests/unit/conftest.py::temp_db，本地自帶）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        yield db_path


def test_abandoned_job_leaves_video_in_empty_focal_candidates(temp_db):
    """ABANDONED → no update_auto_focal → row stays in empty-focal candidates."""
    repo = VideoRepository(temp_db)
    path = to_file_uri("/focal_abandoned_requeue.mp4")
    cover_path = to_file_uri("/covers/abandoned.jpg")
    repo.upsert(Video(path=path, number="SIRO-9999", maker="", cover_path=cover_path))

    committed = []

    def commit(focal_str, fp):
        committed.append((focal_str, fp))
        repo.update_auto_focal(path, focal_str, cover_path)

    def fake_detect(fs_path, ratio, work_width):
        return RunnerOutcome(kind="ABANDONED", reason="detect_timeout")

    def fp_fn(fs_path):
        return ("fp1",)

    w = FocalWorker(detect_fn=fake_detect, fingerprint_fn=fp_fn, auto_start=False)
    w.submit("video", path, "/fake/cover.jpg", 0.71, commit)
    w._process_one()

    assert committed == [], "ABANDONED must never call job.commit"
    row = repo.get_by_path(path)
    assert row is not None
    assert row.focal_attempted_at is None

    candidates = repo.get_empty_focal_candidates([path])
    assert candidates == [(path, "SIRO-9999", "", cover_path)]
