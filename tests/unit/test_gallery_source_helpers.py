"""Unit tests for iter_gallery_sources / get_gallery_source_paths helpers.

TDD-lite: each test is written to go RED if the helper logic is broken.
"""

from core.config import DirectoryConfig, iter_gallery_sources, get_gallery_source_paths


# ---------------------------------------------------------------------------
# Container-type edge cases
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Element-type: str
# ---------------------------------------------------------------------------

class TestStrElement:
    def test_str_coerced_to_directory_config(self):
        result = iter_gallery_sources({"directories": ["/videos"]})
        assert len(result) == 1
        assert isinstance(result[0], DirectoryConfig)
        assert result[0].path == "/videos"


# ---------------------------------------------------------------------------
# Element-type: dict
# ---------------------------------------------------------------------------

class TestDictElement:
    def test_full_dict_element_preserved(self):
        elem = {"path": "/x", "readonly": True, "output_path": "/out"}
        result = iter_gallery_sources({"directories": [elem]})
        assert len(result) == 1
        dc = result[0]
        assert dc.path == "/x"
        assert dc.readonly is True
        assert dc.output_path == "/out"


# ---------------------------------------------------------------------------
# Element-type: DirectoryConfig instance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Unknown element types — must be skipped, not crash
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mixed list: all three types together, order preserved
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GalleryConfig container (model instance)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# get_gallery_source_paths — thin wrapper equivalence
# ---------------------------------------------------------------------------

class TestGetGallerySourcePaths:


    def test_dict_element_path_extracted(self):
        cfg = {"directories": [{"path": "/x", "readonly": True, "output_path": ""}]}
        assert get_gallery_source_paths(cfg) == ["/x"]


# ---------------------------------------------------------------------------
# DirectoryConfig model: field defaults & combinations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Robustness / security hardening (P1 + P2 findings)
# ---------------------------------------------------------------------------

class TestRobustness:
    """Verify that iter_gallery_sources DROPS entries without a usable non-empty string path
    and coerces null/wrong-type optional fields instead of crashing.

    P1: empty/missing path must not yield '' which becomes file:/// (universal allowlist bypass).
    P2: path=null must not raise ValidationError (dict key present with None value).
    """


    def test_dict_path_empty_string_skipped(self):
        """{'path': ''} must be silently skipped (P1: empty path → file:/// bypass)."""
        result = iter_gallery_sources({"directories": [{"path": ""}]})
        assert result == []


    def test_dict_readonly_none_coerced_to_false(self):
        """readonly=null must NOT crash; coerced to False."""
        result = iter_gallery_sources({"directories": [{"path": "/x", "readonly": None}]})
        assert len(result) == 1
        assert result[0].readonly is False


