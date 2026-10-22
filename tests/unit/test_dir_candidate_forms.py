"""test_dir_candidate_forms.py — `_dir_candidate_forms` URI-idempotency (PR#91 P2-D).

`_dir_candidate_forms` backs BOTH the /api/gallery/image and /api/gallery/video
directory allowlists. DirectoryConfig.path may be an FS path OR a file:/// URI
(schema「FS 路徑或 URI」). A URI input must yield the SAME candidate URI as the
equivalent FS input — never a double-wrapped `file:///file:///…` (which the
pre-fix `to_file_uri(os.path.normpath(raw_dir))` produced for URI input).

Pure function; each call uses a distinct raw_dir so the module-level TTL cache
(keyed on raw_dir) never cross-contaminates between assertions.
"""

import os

from core.path_utils import is_path_under_dir, to_file_uri
from web.routers.gallery_media import _dir_candidate_forms


class TestDirCandidateFormsUriIdempotent:


    def test_uri_dir_matches_child_file(self, tmp_path):
        """A file under a URI-form source dir is recognised as under one candidate form."""
        d = tmp_path / "srcU3"
        d.mkdir()
        child = d / "movie.mp4"
        child.write_bytes(b"x")

        forms = _dir_candidate_forms(to_file_uri(str(d), {}), {})
        child_uri = to_file_uri(os.path.realpath(str(child)), {})

        assert any(is_path_under_dir(child_uri, f) for f in forms)

    def test_fs_input_still_dual_form(self, tmp_path):
        """FS input keeps working (normpath + realpath dual-form preserved)."""
        d = tmp_path / "srcU4"
        d.mkdir()

        forms = _dir_candidate_forms(str(d), {})
        expected = to_file_uri(os.path.realpath(str(d)), {})

        assert expected in forms
