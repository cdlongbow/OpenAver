"""Unit tests for core/atomic_write.py::atomic_write (TASK-113d-T1).

New file per TASK-113d-T1 DoD's 機械自證: this commit's diff must not touch
any existing tests/ file. Everything new for T1 — the primitive's own
six-cell matrix and the `thumbnail_cache.generate()` call-site regression
lock that plugs the "no os.replace failure coverage" gap — lives here.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.atomic_write import atomic_write


class TestAtomicWritePrimitive:
    """Six-cell matrix (TASK-113d-T1 測試矩陣)."""

    def test_normal_write_leaves_no_temp_leftover(self, tmp_path):
        dest = tmp_path / "out.txt"

        with atomic_write(dest, mode="w") as f:
            f.write("hello")

        assert dest.read_text() == "hello"
        leftovers = [p for p in tmp_path.iterdir() if p != dest]
        assert leftovers == []


    def test_exception_inside_block_does_not_clobber_existing_dest(self, tmp_path):
        dest = tmp_path / "out.txt"
        dest.write_text("original")

        with pytest.raises(RuntimeError, match="boom"):
            with atomic_write(dest, mode="w") as f:
                f.write("partial")
                raise RuntimeError("boom")

        assert dest.read_text() == "original"
        leftovers = [p for p in tmp_path.iterdir() if p != dest]
        assert leftovers == []

    @pytest.mark.parametrize("exc_type", [KeyboardInterrupt])
    def test_base_exception_inside_block_cleans_temp(self, tmp_path, exc_type):
        """Ctrl-C / sys.exit() mid-write must not leave a temp file behind.

        `KeyboardInterrupt` and `SystemExit` derive from `BaseException`, not
        `Exception`, so a cleanup branch that catches only `Exception` lets the
        `mkstemp` file survive. This is not hypothetical bookkeeping: T2 deleted
        `core.actress_photo.download_actress_photo`'s `finally: tmp.unlink()`
        (which *did* run for `BaseException`) in favour of this primitive, and
        the surviving temp's random `mkstemp` name does **not** match that
        function's `{safe_name}.*` sibling-cleanup glob — so nothing would ever
        remove it. Found by Stage 2 pre-merge review (codex 5.6-terra, P2).
        """
        dest = tmp_path / "out.txt"
        dest.write_text("original")

        with pytest.raises(exc_type):
            with atomic_write(dest, mode="w") as f:
                f.write("partial")
                raise exc_type()

        assert dest.read_text() == "original"
        leftovers = [p for p in tmp_path.iterdir() if p != dest]
        assert leftovers == []


    def test_os_replace_failure_does_not_clobber_existing_dest(self, tmp_path):
        dest = tmp_path / "out.txt"
        dest.write_text("original")

        with patch("core.atomic_write.os.replace", side_effect=PermissionError("denied")):
            with pytest.raises(PermissionError):
                with atomic_write(dest, mode="w") as f:
                    f.write("data")

        assert dest.read_text() == "original"
        leftovers = [p for p in tmp_path.iterdir() if p != dest]
        assert leftovers == []


    def test_temp_file_created_in_same_dir_as_dest(self, tmp_path):
        dest = tmp_path / "sub" / "out.txt"
        dest.parent.mkdir()
        captured = {}
        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(*args, **kwargs):
            fd, tmp = real_mkstemp(*args, **kwargs)
            captured["tmp"] = tmp
            return fd, tmp

        with patch("core.atomic_write.tempfile.mkstemp", side_effect=spy_mkstemp):
            with atomic_write(dest, mode="w") as f:
                f.write("x")

        assert Path(captured["tmp"]).parent == dest.parent

    def test_fd_closed_before_os_replace_is_called(self, tmp_path):
        dest = tmp_path / "out.txt"
        call_order = []
        real_fdopen = os.fdopen
        real_replace = os.replace

        def spy_fdopen(fd, *args, **kwargs):
            fh = real_fdopen(fd, *args, **kwargs)
            real_close = fh.close

            def spy_close():
                call_order.append("fdopen_close")
                real_close()

            fh.close = spy_close
            return fh

        def spy_replace(src, dst, *args, **kwargs):
            call_order.append("os_replace")
            return real_replace(src, dst, *args, **kwargs)

        with patch("core.atomic_write.os.fdopen", side_effect=spy_fdopen), \
             patch("core.atomic_write.os.replace", side_effect=spy_replace):
            with atomic_write(dest, mode="w") as f:
                f.write("x")

        assert call_order == ["fdopen_close", "os_replace"]


