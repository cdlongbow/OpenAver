"""Unit tests for core/readonly_producer.py (TDD-lite, T-1 scope).

All filesystem / DB access is mocked — zero real I/O.
"""
import inspect
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Guard test: producer must not contain forbidden names (DoD / CD-88b-1)
# ---------------------------------------------------------------------------

def test_guard_no_forbidden_names():
    """Producer source code must not reference organize_file / enrich_single / scan_file."""
    import core.readonly_producer as mod
    src = inspect.getsource(mod)
    for name in ("organize_file", "enrich_single", "scan_file"):
        assert name not in src, (
            f"core/readonly_producer.py must not import or call '{name}' (CD-88b-1)"
        )


# ---------------------------------------------------------------------------
# _min_size_bytes
# ---------------------------------------------------------------------------

class TestMinSizeBytes:
    def test_zero_when_not_set(self):
        from core.readonly_producer import _min_size_bytes
        assert _min_size_bytes({}) == 0

    def test_converts_mb_to_bytes(self):
        from core.readonly_producer import _min_size_bytes
        assert _min_size_bytes({"min_size_mb": 2}) == 2 * 1024 * 1024

    def test_truncates_float(self):
        from core.readonly_producer import _min_size_bytes
        # int() truncates
        assert _min_size_bytes({"min_size_mb": 1.9}) == 1 * 1024 * 1024

    def test_zero_explicit(self):
        from core.readonly_producer import _min_size_bytes
        assert _min_size_bytes({"min_size_mb": 0}) == 0


# ---------------------------------------------------------------------------
# _list_source_videos
# ---------------------------------------------------------------------------

FAKE_FILES = [
    {"path": "/src/a.mp4", "mtime": 1.0, "size": 100, "nfo_mtime": 0.0},
    {"path": "/src/b.mkv", "mtime": 2.0, "size": 200, "nfo_mtime": 0.0},
]


class TestListSourceVideos:
    def test_calls_fast_scan_with_normalised_path(self):
        """_list_source_videos must delegate to fast_scan_directory (no direct read)."""
        from core.readonly_producer import _list_source_videos

        with patch("core.readonly_producer.fast_scan_directory", return_value=FAKE_FILES) as mock_scan, \
             patch("core.readonly_producer.normalize_path", return_value="/src") as mock_norm:
            result = _list_source_videos("/src", {".mp4", ".mkv"}, 0)

        mock_norm.assert_called_once_with("/src")
        mock_scan.assert_called_once_with("/src", {".mp4", ".mkv"}, 0)
        assert result == FAKE_FILES

    def test_returns_raw_list_unchanged(self):
        from core.readonly_producer import _list_source_videos

        with patch("core.readonly_producer.fast_scan_directory", return_value=FAKE_FILES), \
             patch("core.readonly_producer.normalize_path", return_value="/src"):
            result = _list_source_videos("/src", {".mp4"}, 1024)

        assert result is FAKE_FILES


# ---------------------------------------------------------------------------
# _should_skip  (truth table — 4 cases)
# ---------------------------------------------------------------------------

class TestShouldSkip:
    OUTPUT_URI = "file:///output"
    COVER_URI = "file:///output/movie/cover.jpg"
    SOURCE_URI = "file:///src/a.mp4"

    def test_no_row_returns_false(self):
        """cover_index has no entry for source_uri → rebuild."""
        from core.readonly_producer import _should_skip
        cover_index = {}
        assert _should_skip(self.SOURCE_URI, self.OUTPUT_URI, cover_index) is False

    def test_cover_under_output_but_file_missing_returns_false(self):
        """cover is under output but file does not exist on disk → rebuild."""
        from core.readonly_producer import _should_skip
        cover_index = {self.SOURCE_URI: self.COVER_URI}

        with patch("core.readonly_producer.is_path_under_dir", return_value=True), \
             patch("core.readonly_producer.uri_to_fs_path", return_value="/output/movie/cover.jpg"), \
             patch("core.readonly_producer.Path") as mock_path_cls:
            mock_path_inst = MagicMock()
            mock_path_inst.exists.return_value = False
            mock_path_cls.return_value = mock_path_inst
            result = _should_skip(self.SOURCE_URI, self.OUTPUT_URI, cover_index)

        assert result is False

    def test_cover_not_under_output_returns_false(self):
        """cover is not under this output_uri → rebuild."""
        from core.readonly_producer import _should_skip
        cover_index = {self.SOURCE_URI: "file:///other/cover.jpg"}

        with patch("core.readonly_producer.is_path_under_dir", return_value=False):
            result = _should_skip(self.SOURCE_URI, self.OUTPUT_URI, cover_index)

        assert result is False

    def test_all_conditions_met_returns_true(self):
        """cover under output AND file exists → skip."""
        from core.readonly_producer import _should_skip
        cover_index = {self.SOURCE_URI: self.COVER_URI}

        with patch("core.readonly_producer.is_path_under_dir", return_value=True), \
             patch("core.readonly_producer.uri_to_fs_path", return_value="/output/movie/cover.jpg"), \
             patch("core.readonly_producer.Path") as mock_path_cls:
            mock_path_inst = MagicMock()
            mock_path_inst.exists.return_value = True
            mock_path_cls.return_value = mock_path_inst
            result = _should_skip(self.SOURCE_URI, self.OUTPUT_URI, cover_index)

        assert result is True


# ---------------------------------------------------------------------------
# _build_cover_index
# ---------------------------------------------------------------------------

class TestBuildCoverIndex:
    OUTPUT_URI = "file:///output"

    def _make_repo(self, full_index: dict) -> MagicMock:
        repo = MagicMock()
        repo.get_cover_index.return_value = full_index
        return repo

    def test_filters_out_empty_cover(self):
        from core.readonly_producer import _build_cover_index
        repo = self._make_repo({
            "file:///src/a.mp4": "",
            "file:///src/b.mp4": "file:///output/b/cover.jpg",
        })
        with patch("core.readonly_producer.is_path_under_dir",
                   side_effect=lambda c, o: c.startswith("file:///output")):
            result = _build_cover_index(repo, self.OUTPUT_URI)

        # empty cover must be excluded
        assert "file:///src/a.mp4" not in result
        assert "file:///src/b.mp4" in result

    def test_filters_out_cover_not_under_output(self):
        from core.readonly_producer import _build_cover_index
        repo = self._make_repo({
            "file:///src/a.mp4": "file:///other/cover.jpg",
            "file:///src/b.mp4": "file:///output/b/cover.jpg",
        })
        with patch("core.readonly_producer.is_path_under_dir",
                   side_effect=lambda c, o: c.startswith("file:///output")):
            result = _build_cover_index(repo, self.OUTPUT_URI)

        assert "file:///src/a.mp4" not in result
        assert "file:///src/b.mp4" in result

    def test_empty_db_returns_empty(self):
        from core.readonly_producer import _build_cover_index
        repo = self._make_repo({})
        with patch("core.readonly_producer.is_path_under_dir", return_value=True):
            result = _build_cover_index(repo, self.OUTPUT_URI)
        assert result == {}

    def test_null_cover_filtered(self):
        """None cover_path must be treated as falsy and excluded."""
        from core.readonly_producer import _build_cover_index
        repo = self._make_repo({
            "file:///src/a.mp4": None,
        })
        with patch("core.readonly_producer.is_path_under_dir", return_value=True):
            result = _build_cover_index(repo, self.OUTPUT_URI)
        assert result == {}
