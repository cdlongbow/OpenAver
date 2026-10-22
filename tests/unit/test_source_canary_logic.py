"""Deterministic unit tests for the 8-source health-canary decision-core.

Zero network, fully synthetic inputs. Carries spec §US1 acceptance
("verify the three-state decision logic with controllable mocks, not real
network"). This file is intentionally NOT marked @pytest.mark.smoke — it must
run in CI fast-run.
"""

import types

import pytest

from tests.smoke._canary_core import classify_one, numbers_match


def _video(number="SONE-205", title="Some Title", cover_url="http://x/c.jpg"):
    """Duck-typed fake video object with .number/.title/.cover_url."""
    return types.SimpleNamespace(number=number, title=title, cover_url=cover_url)


# ---------------------------------------------------------------------------
# classify_one — 6-state table
# ---------------------------------------------------------------------------

class TestClassifyOne:

    def test_video_number_mismatch_fails(self):
        # Row 3: returned Video but wrong number -> fail (not skip)
        v = _video(number="SONE-206")
        assert classify_one(v, True, "SONE-205", "dmm") == "fail"


    def test_none_group_a_probe_true_fails(self):
        # Row 4: None + Group A + probe reachable -> fail (parser broken)
        assert classify_one(None, True, "SONE-205", "javbus") == "fail"
        assert classify_one(None, True, "051119-917", "avsox") == "fail"  # avsox GROUP_A row 4


        # avsox is now GROUP_A — removed from this test


# ---------------------------------------------------------------------------
# numbers_match — canonical per source-class
# ---------------------------------------------------------------------------

class TestNumbersMatchYukoCensored:
    @pytest.mark.parametrize("source", ["javbus", ])
    def test_censored_match_variants(self, source):
        assert numbers_match("SONE-205", "sone205", source) is True
        assert numbers_match("SONE-205", "SONE205", source) is True
        assert numbers_match("sone205", "SONE-205", source) is True


    @pytest.mark.parametrize("source", ["javbus", ])
    def test_censored_non_match(self, source):
        assert numbers_match("SONE-205", "SONE-206", source) is False
        assert numbers_match("SONE-205", "SSNI-001", source) is False


# ---------------------------------------------------------------------------
# quorum_verdict
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Purity guard — static string check on the source file
# ---------------------------------------------------------------------------

