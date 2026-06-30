"""Unit tests for core/readonly_producer.py (TDD-lite, T-1 scope).

All filesystem / DB access is mocked — zero real I/O.
"""
import inspect
from pathlib import Path
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


# ---------------------------------------------------------------------------
# T-2 tests: _format_data, _folder_parts, _build_basename, _movie_dir
# ---------------------------------------------------------------------------

class TestFormatData:
    """Tests for _format_data (organizer off-mode format_data construction)."""

    BASE_CONFIG = {
        'max_title_length': 20,
        'suffix_keywords': ['-C', '-U'],
        'filename_format': '{num} {title}',
        'max_filename_length': 60,
    }

    def test_long_title_truncated(self):
        from core.readonly_producer import _format_data
        meta = {'number': 'ABC-123', 'title': 'A' * 30}
        fd = _format_data(meta, '/src/ABC-123.mp4', self.BASE_CONFIG)
        assert len(fd['title']) <= 20
        assert fd['title'].endswith('...')

    def test_prefix_stripped_from_title(self):
        from core.readonly_producer import _format_data
        meta = {'number': 'ABC-123', 'title': '[ABC-123]Original Title'}
        fd = _format_data(meta, '/src/ABC-123.mp4', self.BASE_CONFIG)
        assert 'ABC-123' not in fd['title']
        assert 'Original Title' in fd['title']

    def test_suffix_detected_from_basename(self):
        from core.readonly_producer import _format_data
        meta = {'number': 'ABC-123', 'title': 'Some Title'}
        fd = _format_data(meta, '/src/ABC-123-C.mp4', self.BASE_CONFIG)
        assert '-c' in fd['suffix'].lower()

    def test_no_suffix_when_no_match(self):
        from core.readonly_producer import _format_data
        meta = {'number': 'ABC-123', 'title': 'Some Title'}
        fd = _format_data(meta, '/src/ABC-123.mp4', self.BASE_CONFIG)
        assert fd['suffix'] == ''

    def test_truncated_title_consistent_in_folder_and_basename(self):
        """Same truncated title feeds both _folder_parts and _build_basename (no drift)."""
        from core.readonly_producer import _build_basename, _folder_parts, _format_data
        long_title = 'VeryLong' * 5
        meta = {'number': 'ABC-123', 'title': long_title}
        config = {
            'max_title_length': 15,
            'suffix_keywords': [],
            'filename_format': '{num} {title}',
            'max_filename_length': 60,
            'folder_layers': ['{title}'],
        }
        fd = _format_data(meta, '/src/ABC-123.mp4', config)
        folder = _folder_parts(fd, config)
        basename = _build_basename(fd, '/src/ABC-123.mp4', config)
        # folder parts include the title
        assert folder[0] == fd['title']
        # basename also includes the same truncated title
        assert fd['title'] in basename


class TestFolderParts:
    """Tests for _folder_parts."""

    def test_two_layers(self):
        from core.readonly_producer import _folder_parts
        config = {'folder_layers': ['{actor}', '{num}'], 'max_filename_length': 60}
        fd = {'number': 'ABC-123', 'title': 'Title', 'actors': ['Actress'], 'maker': '', 'date': '', 'suffix': ''}
        parts = _folder_parts(fd, config)
        assert len(parts) == 2

    def test_more_than_3_layers_capped(self):
        from core.readonly_producer import _folder_parts
        config = {
            'folder_layers': ['{num}', '{num}', '{num}', '{num}'],
            'max_filename_length': 60,
        }
        fd = {'number': 'ABC-123', 'title': '', 'actors': [], 'maker': '', 'date': '', 'suffix': ''}
        parts = _folder_parts(fd, config)
        assert len(parts) <= 3

    def test_empty_layer_skipped(self):
        from core.readonly_producer import _folder_parts
        # An empty-string layer formats to '' and must be dropped by the `if part` guard.
        config = {'folder_layers': ['{num}', ''], 'max_filename_length': 60}
        fd = {'number': 'ABC-123', 'title': 'Title', 'actors': [], 'maker': '', 'date': '', 'suffix': ''}
        parts = _folder_parts(fd, config)
        # empty layer dropped → only the number layer survives (RED if `if part` guard removed)
        assert parts == ['ABC-123']

    def test_folder_format_fallback(self):
        """When folder_layers is empty, folder_format is used."""
        from core.readonly_producer import _folder_parts
        config = {
            'folder_layers': [],
            'folder_format': '{num}',
            'max_filename_length': 60,
        }
        fd = {'number': 'ABC-123', 'title': '', 'actors': [], 'maker': '', 'date': '', 'suffix': ''}
        parts = _folder_parts(fd, config)
        assert parts == ['ABC-123']

    def test_no_layers_no_folder_format_defaults_num(self):
        from core.readonly_producer import _folder_parts
        config = {'max_filename_length': 60}
        fd = {'number': 'XYZ-001', 'title': '', 'actors': [], 'maker': '', 'date': '', 'suffix': ''}
        parts = _folder_parts(fd, config)
        assert parts == ['XYZ-001']


class TestBuildBasename:
    """Tests for _build_basename (off-mode filename stem generation)."""

    BASE_FD = {
        'number': 'ABC-123',
        'title': 'Normal Title',
        'actors': [],
        'maker': '',
        'date': '',
        'suffix': '',
    }
    BASE_CONFIG = {
        'filename_format': '{num} {title}',
        'max_filename_length': 60,
        'suffix_keywords': [],
    }

    def test_vr_tail_present_for_vr_file(self):
        from core.readonly_producer import _build_basename
        with patch('core.readonly_producer._detect_vr_cluster', return_value='180_LR'):
            result = _build_basename(self.BASE_FD, '/src/ABC-123_180_LR.mp4', self.BASE_CONFIG)
        assert result.endswith('_180_LR')

    def test_no_vr_tail_for_normal_file(self):
        from core.readonly_producer import _build_basename
        with patch('core.readonly_producer._detect_vr_cluster', return_value=None):
            result = _build_basename(self.BASE_FD, '/src/ABC-123.mp4', self.BASE_CONFIG)
        # BASE_FD title has no underscore → any '_' means an erroneous VR tail (RED if injected)
        assert '_' not in result

    def test_suffix_not_truncated_in_two_pass(self):
        """When {suffix} in template, suffix is not cut off by truncation."""
        from core.readonly_producer import _build_basename
        fd = dict(self.BASE_FD, suffix='-C', title='X' * 60)
        config = dict(self.BASE_CONFIG, filename_format='{num} {title}{suffix}', max_filename_length=30)
        with patch('core.readonly_producer._detect_vr_cluster', return_value=None):
            result = _build_basename(fd, '/src/ABC-123-C.mp4', config)
        # suffix '-c' / '-C' should survive truncation
        assert result.endswith('-c') or result.endswith('-C') or '-c' in result.lower()

    def test_plain_num_title_no_vr_tail(self):
        from core.readonly_producer import _build_basename
        with patch('core.readonly_producer._detect_vr_cluster', return_value=None):
            result = _build_basename(self.BASE_FD, '/src/ABC-123.mp4', self.BASE_CONFIG)
        assert result == 'ABC-123 Normal Title'


class TestBuildOwners:
    """Tests for _build_owners."""

    def test_builds_dir_to_source_map(self):
        from core.readonly_producer import _build_owners
        cover_index = {
            'file:///src/a.mp4': 'file:///output/MovieA/cover.jpg',
        }
        with patch('core.readonly_producer.uri_to_fs_path', side_effect=lambda u: u[7:]):
            owners = _build_owners(cover_index)
        assert '/output/MovieA' in owners
        assert owners['/output/MovieA'] == 'file:///src/a.mp4'

    def test_empty_cover_skipped(self):
        from core.readonly_producer import _build_owners
        cover_index = {'file:///src/a.mp4': ''}
        owners = _build_owners(cover_index)
        assert owners == {}

    def test_none_cover_skipped(self):
        from core.readonly_producer import _build_owners
        cover_index = {'file:///src/a.mp4': None}
        owners = _build_owners(cover_index)
        assert owners == {}


class TestMovieLeafBase:
    """Tests for _movie_leaf_base."""

    def test_empty_stem_returns_number(self):
        from core.readonly_producer import _movie_leaf_base
        # sanitize_filename of an empty stem returns ''
        with patch('core.readonly_producer.uri_to_fs_path', return_value='/'), \
             patch('core.readonly_producer.sanitize_filename', return_value=''):
            result = _movie_leaf_base('ABC-123', 'file:///')
        assert result == 'ABC-123'

    def test_stem_equals_number_normalised(self):
        from core.readonly_producer import _movie_leaf_base
        with patch('core.readonly_producer.uri_to_fs_path', return_value='/src/ABC-123.mp4'), \
             patch('core.readonly_producer.normalize_number', return_value='ABC-123'), \
             patch('core.readonly_producer.sanitize_filename', side_effect=lambda x: x):
            result = _movie_leaf_base('ABC-123', 'file:///src/ABC-123.mp4')
        assert result == 'ABC-123'

    def test_stem_contains_number_returns_stem(self):
        from core.readonly_producer import _movie_leaf_base
        with patch('core.readonly_producer.uri_to_fs_path', return_value='/src/ABC-123-VR.mp4'), \
             patch('core.readonly_producer.normalize_number', return_value='ABC-123-VR'), \
             patch('core.readonly_producer.sanitize_filename', side_effect=lambda x: x):
            result = _movie_leaf_base('ABC-123', 'file:///src/ABC-123-VR.mp4')
        # stem 'ABC-123-VR' contains 'ABC-123'
        assert result == 'ABC-123-VR'

    def test_unrelated_stem_prefixes_number(self):
        from core.readonly_producer import _movie_leaf_base
        with patch('core.readonly_producer.uri_to_fs_path', return_value='/src/random_name.mp4'), \
             patch('core.readonly_producer.normalize_number', return_value='RANDOM_NAME'), \
             patch('core.readonly_producer.sanitize_filename', side_effect=lambda x: x):
            result = _movie_leaf_base('ABC-123', 'file:///src/random_name.mp4')
        assert result == 'ABC-123-random_name'


class TestMovieDir:
    """Tests for _movie_dir collision-avoidance."""

    OUTPUT_ROOT = '/output'
    BASE_CONFIG = {
        'folder_layers': [],
        'folder_format': '{num}',
        'max_filename_length': 60,
        'filename_format': '{num} {title}',
    }

    def _fd(self, number='ABC-123'):
        return {'number': number, 'title': 'Title', 'actors': [], 'maker': '', 'date': '', 'suffix': ''}

    def _patch_leaf(self, leaf):
        return patch('core.readonly_producer._movie_leaf_base', return_value=leaf)

    def _patch_exists(self, exists=False):
        return patch('core.readonly_producer.Path.exists', return_value=exists)

    def test_same_number_two_paths_distinct_dirs(self):
        """Same number → same leaf for two source URIs in ONE run → second collides → hashed dir."""
        from core.readonly_producer import _movie_dir
        fd = self._fd('ABC-123')
        owners: dict = {}
        src_a = 'file:///a/ABC-123.mp4'
        src_b = 'file:///b/ABC-123.mp4'

        # both resolve to the SAME leaf → exercises the in-run collision/hash branch
        with patch('core.readonly_producer._movie_leaf_base', return_value='ABC-123'), \
             self._patch_exists(False):
            dir_a = _movie_dir(self.OUTPUT_ROOT, fd, src_a, self.BASE_CONFIG, owners)
            dir_b = _movie_dir(self.OUTPUT_ROOT, fd, src_b, self.BASE_CONFIG, owners)

        assert dir_a.name == 'ABC-123'                 # first source: bare leaf, no hash
        assert dir_b != dir_a                          # collision → hashed (RED if hash branch removed)
        assert dir_b.name.startswith('ABC-123-')       # hash suffix present
        assert owners[str(dir_a)] == src_a             # first owner not overwritten by second

    def test_cross_run_existing_owner_not_overwritten(self):
        """owners pre-seeded with movie_dir→srcA; srcB hashes to new dir, srcA entry unchanged."""
        from core.readonly_producer import _movie_dir
        fd = self._fd('ABC-123')
        src_a = 'file:///a/ABC-123.mp4'
        src_b = 'file:///b/ABC-123.mp4'
        movie_dir_a = str(Path(self.OUTPUT_ROOT, 'ABC-123'))
        owners = {movie_dir_a: src_a}

        with self._patch_leaf('ABC-123'), self._patch_exists(False):
            dir_b = _movie_dir(self.OUTPUT_ROOT, fd, src_b, self.BASE_CONFIG, owners)

        assert str(dir_b) != movie_dir_a
        assert owners[movie_dir_a] == src_a  # not overwritten

    def test_disk_orphan_gets_hashed_dir(self):
        """Candidate exists on disk, owners empty → hash suffix applied."""
        from core.readonly_producer import _movie_dir
        fd = self._fd('ABC-123')
        owners: dict = {}
        src = 'file:///src/ABC-123.mp4'

        with self._patch_leaf('ABC-123'), self._patch_exists(True):
            result = _movie_dir(self.OUTPUT_ROOT, fd, src, self.BASE_CONFIG, owners)

        # The plain candidate exists → hash suffix; result should not be bare 'ABC-123'
        assert result.name != 'ABC-123'

    def test_idempotent_same_source(self):
        """Calling _movie_dir twice with same source_uri → same dir."""
        from core.readonly_producer import _movie_dir
        fd = self._fd('ABC-123')
        owners: dict = {}
        src = 'file:///src/ABC-123.mp4'

        with self._patch_leaf('ABC-123'), self._patch_exists(False):
            dir1 = _movie_dir(self.OUTPUT_ROOT, fd, src, self.BASE_CONFIG, owners)
            dir2 = _movie_dir(self.OUTPUT_ROOT, fd, src, self.BASE_CONFIG, owners)

        assert dir1 == dir2

    def test_leaf_enforcement_different_numbers(self):
        """folder_layers=['{actor}'], same actor, different numbers → different dirs."""
        from core.readonly_producer import _movie_dir
        config = dict(self.BASE_CONFIG, folder_layers=['{actor}'])
        fd_a = {'number': 'ABC-001', 'title': 'T', 'actors': ['Actress A'], 'maker': '', 'date': '', 'suffix': ''}
        fd_b = {'number': 'ABC-002', 'title': 'T', 'actors': ['Actress A'], 'maker': '', 'date': '', 'suffix': ''}
        owners: dict = {}
        src_a = 'file:///src/ABC-001.mp4'
        src_b = 'file:///src/ABC-002.mp4'

        with patch('core.readonly_producer._movie_leaf_base', side_effect=['ABC-001', 'ABC-002']), \
             self._patch_exists(False):
            dir_a = _movie_dir(self.OUTPUT_ROOT, fd_a, src_a, config, owners)
            dir_b = _movie_dir(self.OUTPUT_ROOT, fd_b, src_b, config, owners)

        assert dir_a != dir_b
