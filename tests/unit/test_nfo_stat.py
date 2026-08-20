"""Unit tests for core/nfo_stat.py::nfo_mtime_or_none (TASK-113b-T2).

New file per plan-113b T2 DoD's 機械自證: this commit's diff must not touch any
existing tests/ file. Everything new for T2 — the primitive's own four-cell
matrix, the S6 re-raise pair (primitive layer + consumer layer), and any
call-site tests needed to close a mutation-testing coverage gap — lives here.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.nfo_stat import (
    NFO_MTIME_FILL_MISSING,
    NFO_MTIME_ON_UPSERT,
    NFO_MTIME_REFRESH,
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

    def test_file_missing_returns_none_without_on_error(self, tmp_path):
        nfo = tmp_path / "does-not-exist.nfo"

        result = nfo_mtime_or_none(nfo)

        assert result is None

    def test_stat_oserror_returns_none(self, tmp_path):
        nfo = tmp_path / "TEST-002.nfo"
        nfo.write_text("<movie/>")

        with patch.object(Path, "stat", side_effect=OSError("boom")):
            result = nfo_mtime_or_none(nfo)

        assert result is None

    def test_on_error_called_with_original_exception_instance(self, tmp_path):
        nfo = tmp_path / "does-not-exist.nfo"
        received: list = []

        result = nfo_mtime_or_none(nfo, on_error=lambda e: received.append(e))

        assert result is None
        assert len(received) == 1
        assert isinstance(received[0], OSError)

    def test_no_on_error_does_not_raise_or_call_anything(self, tmp_path):
        nfo = tmp_path / "does-not-exist.nfo"

        # Must not raise — on_error is optional and absence must be silent.
        result = nfo_mtime_or_none(nfo)

        assert result is None

    def test_accepts_os_direntry_duck_typed(self, tmp_path):
        """S1 passes os.DirEntry directly (CD-113b-2) — must not require Path."""
        nfo = tmp_path / "TEST-003.nfo"
        nfo.write_text("<movie/>")

        with os.scandir(tmp_path) as entries:
            entry = next(e for e in entries if e.name == "TEST-003.nfo")
            result = nfo_mtime_or_none(entry)

        assert result == nfo.stat().st_mtime


class TestNfoMtimeOrNoneReraisePrimitiveLayer:
    """S6 re-raise, primitive layer (CD-113b-5): if on_error itself raises, that
    exception must propagate out of nfo_mtime_or_none — it must NOT be
    swallowed and turned into a `None` return. This is the guard against a
    callback silently degrading into "log only, don't re-raise"."""

    def test_on_error_raising_propagates_and_does_not_return_none(self, tmp_path):
        nfo = tmp_path / "does-not-exist.nfo"

        def _reraise(e):
            raise e

        with pytest.raises(OSError):
            nfo_mtime_or_none(nfo, on_error=_reraise)


class TestNfoMtimeOrNoneReraiseConsumerLayer:
    """S6 re-raise, consumer layer: core.readonly_producer._write_movie_assets
    must still fail the whole piece when the NFO it just wrote can't be
    stat()'d — this is the pre-existing "no try/except, exception propagates"
    semantics (CD-113b-5), now re-implemented via nfo_mtime_or_none +
    _reraise_nfo_stat_error instead of a bare os.stat() call. Real stat
    failure fault-injection (only the .nfo path is broken, so cover/sample
    writes earlier in the function are unaffected) rather than mocking the
    primitive, so this also exercises the real callback wiring end to end.
    """

    def test_write_movie_assets_propagates_when_nfo_stat_fails(self, tmp_path):
        from core.readonly_producer import _write_movie_assets
        from tests.unit.test_readonly_producer import (
            _T3_BASE_CONFIG,
            _T3_META,
            _cover_strategy_for,
            _t3_format_data,
            _t3_generate_nfo_side_effect,
        )

        movie_dir = str(tmp_path / "output" / "TEST-001")
        fd = _t3_format_data()

        real_stat = Path.stat

        def _selective_stat(self, *args, **kwargs):
            if str(self).endswith(".nfo"):
                raise OSError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        with patch("core.readonly_producer.download_image", return_value=True), \
             patch("core.readonly_producer.generate_jellyfin_images",
                   return_value={"poster": True, "fanart": True}), \
             patch("core.readonly_producer.generate_nfo",
                   side_effect=_t3_generate_nfo_side_effect), \
             patch.object(Path, "stat", _selective_stat), \
             pytest.raises(OSError):
            _write_movie_assets(
                movie_dir, _T3_META, fd, "/src/TEST-001.mp4", _T3_BASE_CONFIG,
                cover_strategy=_cover_strategy_for(_T3_META),
            )


class TestOnErrorTriggeredCallSites:
    """Mutation self-verification found a real gap (TASK-113b-T2 DoD): mutating
    the primitive to silently skip calling `on_error` on OSError left the
    *existing* S1/S2/S5 tests all green — none of them fault-inject a `.nfo`
    stat failure, so none of them can tell whether the callsite's `on_error`
    wiring actually fires. `test_on_error_called_with_original_exception_instance`
    above proves the primitive itself calls `on_error`; these three prove each
    callsite's own wiring (which concrete callback it passes) actually gets
    invoked when the .nfo stat fails — call-site tests as required by the DoD
    ("不可用 primitive 層測試充數"). S6 already has its own dedicated pair above.
    """

    def test_s1_gallery_scanner_on_skip_called_when_nfo_stat_fails(self, tmp_path):
        """S1 (core.gallery_scanner.fast_scan_directory): `on_error` is wired to
        `_safe_on_skip(entry.path, e)`. Fault-inject only the .nfo DirEntry's
        stat() (real os.scandir(), not a mocked primitive) and assert on_skip
        receives the .nfo path + the original OSError instance, and that the
        video's nfo_mtime index entry is left absent (falls back to 0 via
        dir_nfos.get(stem, 0), Q-3 unchanged)."""
        from core.gallery_scanner import fast_scan_directory

        (tmp_path / "TEST-010.mp4").write_bytes(b"fake video")
        (tmp_path / "TEST-010.nfo").write_text("<movie/>")

        real_stat = os.DirEntry.stat

        def _selective_stat(self, *args, **kwargs):
            if self.name.endswith(".nfo"):
                raise OSError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        skipped: list = []

        with patch.object(os.DirEntry, "stat", _selective_stat):
            results = fast_scan_directory(
                str(tmp_path), {".mp4"},
                on_skip=lambda p, e: skipped.append((p, e)),
            )

        assert len(skipped) == 1
        skipped_path, skipped_exc = skipped[0]
        assert skipped_path.endswith("TEST-010.nfo")
        assert isinstance(skipped_exc, OSError)
        assert len(results) == 1
        assert results[0]["nfo_mtime"] == 0

    def test_s2_db_inflow_logs_warning_when_nfo_stat_fails(self, tmp_path, caplog):
        """S2 (core.db_inflow.try_inflow_upsert): `on_error` is wired to
        `_reraise_stat_error`, which must let the existing outer
        `except OSError` catch it and log the warning below (Opus BLOCKER fix:
        `.exists()` restored, see db_inflow.py). Real TOCTOU shape: `.exists()`
        succeeds (file is really there), the *later* explicit stat via the
        primitive fails. A blanket "always raise for .nfo paths" patch would
        make `Path.exists()` itself raise too (it calls `self.stat()`
        internally and only swallows ENOENT/ENOTDIR/EBADF/ELOOP, not EACCES),
        collapsing this into a different path than the one being tested — a
        per-path call counter lets the 1st call (.exists()) succeed and the
        2nd call (the primitive's target.stat()) fail, same technique as the
        S5 TOCTOU test below.
        """
        from core.database import VideoRepository
        from core.path_utils import normalize_path, to_file_uri
        from tests.unit.test_db_inflow import _make_db, _make_video_info

        db_path = _make_db(tmp_path)
        repo = VideoRepository(db_path=db_path)

        video_path = tmp_path / "s2_stat_fail.mp4"
        nfo_path = tmp_path / "s2_stat_fail.nfo"
        video_path.write_bytes(b"fake video bytes")
        nfo_path.write_text("<movie/>", encoding="utf-8")

        new_uri = to_file_uri(normalize_path(str(video_path)), None)
        video_info = _make_video_info(new_uri, num="S2-001", title="S2 Video")

        real_stat = Path.stat
        call_counts: dict = {}

        def _selective_stat(self, *args, **kwargs):
            key = str(self)
            if key.endswith(".nfo"):
                call_counts[key] = call_counts.get(key, 0) + 1
                if call_counts[key] >= 2:
                    raise OSError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        import core.db_inflow as _db_inflow_mod

        with (
            patch.object(_db_inflow_mod, "load_config", return_value={
                "gallery": {"directories": [str(tmp_path)], "path_mappings": None}
            }),
            patch.object(_db_inflow_mod, "find_matched_directory", return_value=str(tmp_path)),
            patch.object(_db_inflow_mod, "VideoScanner") as MockScanner,
            patch.object(_db_inflow_mod, "VideoRepository", return_value=repo),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
            patch.object(Path, "stat", _selective_stat),
        ):
            MockScanner.return_value.scan_file.return_value = video_info
            with caplog.at_level("WARNING"):
                result = _db_inflow_mod.try_inflow_upsert(str(video_path), old_file_path=None)

        assert result == "synced"
        assert any("stat NFO 失敗" in r.message for r in caplog.records)
        row = repo.get_by_path(new_uri)
        assert row.nfo_mtime == 0.0

    def test_s5_migrate_reraises_and_logs_on_toctou_stat_failure(self, tmp_path, caplog):
        """S5 (core.database.migrate.backfill_readonly_nfo_mtime): `on_error` is
        wired to `_reraise_stat_error`, which must let the existing outer
        `except Exception` catch it (Opus 裁決 1 — the `.exists()` check stays,
        distinguishing "NFO missing" (silent) from "NFO exists but stat()
        fails" (warning + exc_info)). Fault-inject only the .nfo Path.stat()
        so `.exists()` returns True but `.stat()` raises, and assert the row
        is left unhealed while the existing warning still fires — this is the
        TOCTOU case plan-113b v7 / card A段 S5 identified as untested by any
        existing test_backfill_nfo_mtime.py test.
        """
        from core.database.connection import init_db
        from core.database.migrate import backfill_readonly_nfo_mtime
        from core.database.video import Video, VideoRepository
        from core.path_utils import to_file_uri

        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)

        cover_fs = tmp_path / "S5-TOCTOU.jpg"
        cover_fs.write_bytes(b"fake-jpg")
        nfo_fs = tmp_path / "S5-TOCTOU.nfo"
        nfo_fs.write_text("<movie/>")

        cover_uri = to_file_uri(str(cover_fs), {})
        video_uri = to_file_uri(str(tmp_path / "S5-TOCTOU.mp4"), {})
        repo.upsert(Video(path=video_uri, number="S5-TOCTOU", title="t",
                           cover_path=cover_uri, nfo_mtime=0.0))

        # migrate.py's `.exists()` check runs first and must still see the file
        # as present (real TOCTOU: exists() succeeds, the *later* explicit
        # .stat() fails) — a blanket "always raise for .nfo paths" patch would
        # make `Path.exists()` itself raise too (it calls `self.stat()`
        # internally and only swallows ENOENT/ENOTDIR/EBADF/ELOOP, not
        # EACCES), collapsing this into the already-covered "NFO missing"
        # branch instead of the TOCTOU branch this test targets. A per-path
        # call counter lets the 1st call (.exists()) succeed and the 2nd call
        # (the primitive's target.stat()) fail.
        real_stat = Path.stat
        call_counts: dict = {}

        def _selective_stat(self, *args, **kwargs):
            key = str(self)
            if key.endswith(".nfo"):
                call_counts[key] = call_counts.get(key, 0) + 1
                if call_counts[key] >= 2:
                    raise OSError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", _selective_stat), caplog.at_level("WARNING"):
            healed = backfill_readonly_nfo_mtime(db_path=db_path, path_mappings={})

        assert healed == 0
        row = repo.get_by_path(video_uri)
        assert row.nfo_mtime == 0.0
        assert any(
            "backfill_readonly_nfo_mtime: failed to heal row" in r.message
            for r in caplog.records
        )


class TestNoNfoIsSilentRegression:
    """Opus BLOCKER fix regression lock: deleting `core.enricher.enrich_single`'s
    S3 `.exists()` check (the original T2 mistake) made every NFO-absent piece
    — the common case for `write_nfo=False` pieces — log a spurious
    "nfo_mtime stat 失敗" warning on every enrich, because
    `nfo_mtime_or_none()` treats a missing file exactly like a stat failure
    (`FileNotFoundError` is an `OSError` subclass) and always invokes
    `on_error`. `.exists()` is what keeps "genuinely absent" and "present but
    unreadable" distinguishable at the call site. Without this test, the next
    person who deletes `.exists()` again gets no red signal — mutating it
    below must turn this test red.
    """

    def test_enrich_single_no_nfo_logs_no_stat_warning(self, tmp_path, caplog):
        import logging as _logging

        from core.database import VideoRepository, init_db
        from core.path_utils import to_file_uri, uri_to_fs_path

        db_file = tmp_path / "no_nfo_regression.db"
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / "NOFO-001.mp4"
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        # 刻意不建立 NOFO-001.nfo — 常態情境（write_nfo=False 或 organizer 刻意 skip）

        scraper_data = {
            "number": "NOFO-001", "title": "New", "actors": ["女優X"],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": "SOD", "director": "監督X", "series": "シリーズX", "label": "LABEL",
            "tags": ["タグ"], "sample_images": [], "source": "javbus",
        }
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
            caplog.at_level(_logging.WARNING, logger="OpenAver.core.enricher"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="NOFO-001", mode="fill_missing",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_called_once()
        assert result.success is True
        assert not any("stat 失敗" in r.message for r in caplog.records), (
            "NFO 不存在是常態，S3／S4 都不得記錄任何 stat 失敗 warning"
        )
        row = repo.get_by_path(to_file_uri(uri_to_fs_path(file_path)))
        assert row is not None
        assert row.nfo_mtime == 0.0


class TestNfoMtimePolicyConstants:
    """CD-113b-3: three distinct, non-behavioral policy literals."""

    def test_three_constants_are_distinct(self):
        values = {NFO_MTIME_REFRESH, NFO_MTIME_ON_UPSERT, NFO_MTIME_FILL_MISSING}
        assert len(values) == 3
