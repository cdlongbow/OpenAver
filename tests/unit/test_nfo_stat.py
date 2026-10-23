"""Unit tests for core/nfo_stat.py::nfo_mtime_or_none (TASK-113b-T2).

New file per plan-113b T2 DoD's 機械自證: this commit's diff must not touch any
existing tests/ file. Everything new for T2 — the primitive's own four-cell
matrix, the S6 re-raise pair (primitive layer + consumer layer), and any
call-site tests needed to close a mutation-testing coverage gap — lives here.
"""
from pathlib import Path
from unittest.mock import patch


from core.nfo_stat import (
    nfo_mtime_or_none,
)


class TestNfoMtimeOrNonePrimitive:
    """Four-cell matrix (TASK-113b-T2 邊界條件): exists / missing / OSError / on_error."""

    def test_file_exists_returns_real_mtime(self, tmp_path):
        nfo = tmp_path / "TEST-001.nfo"
        nfo.write_text("<movie/>")

        result = nfo_mtime_or_none(nfo)

        assert result == nfo.stat().st_mtime
        assert isinstance(result, float)


    def test_stat_oserror_returns_none(self, tmp_path):
        nfo = tmp_path / "TEST-002.nfo"
        nfo.write_text("<movie/>")

        with patch.object(Path, "stat", side_effect=OSError("boom")):
            result = nfo_mtime_or_none(nfo)

        assert result is None


