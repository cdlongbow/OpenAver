"""TASK-98a-T3: core/focal/gate.py — requires_face_detection / gate_verdict.

Acts on OpenAver canonical `videos.number` + `videos.maker` — never on
filenames, never via trim(). See feature/98-focal-crop/TASK-98a-T3.md for
the DoD list and the deliberate divergence (num-alpha rule dropped).
"""
import pytest

from core.focal.gate import (
    requires_face_detection,
)


# ---- DoD-1: [4SSIS-296] regression lock ------------------------------------

@pytest.mark.parametrize("number", ["4SSIS-296"])
def test_censored_regression_lock(number):
    assert requires_face_detection(number) is False


# ---- DoD-2: real uncensored numbers -> True --------------------------------

@pytest.mark.parametrize("number", [
    "FC2-1234567",
    "200GANA-1234",
    "HEYZO-1234",
    "022509-995",
])
def test_real_uncensored_hits_true(number):
    assert requires_face_detection(number) is True


# ---- DoD-3: maker whitelist -------------------------------------------------

@pytest.mark.parametrize("maker", ["Caribbeancom"])
def test_maker_whitelist_true_when_number_no_match(maker):
    # number doesn't match any number-based rule; maker whitelist saves it.
    assert requires_face_detection("ABC-123", maker) is True


# ---- DoD-4: digit-prefixed censored -> False (drop num_alpha) -------------


# ---- DoD-5: empty-input tolerance ------------------------------------------


def test_none_number_none_maker():
    assert requires_face_detection(None, None) is False


# ---- DoD-6: SSOT import sanity ----------------------------------------------


# ---- gate_verdict reason strings -------------------------------------------


# Note: DoD-7 mutation testing (temporarily re-adding a num-alpha rule /
# neutering _SHIROUTO_RE against the real core/focal/gate.py, confirming
# RED, then reverting) was performed manually as a one-off verification
# pass -- see TASK-98a-T3 completion report. It is not encoded as a
# permanent test here because mutating the SUT in-place inside the
# committed suite would defeat the point (the mutation must be reverted
# for the suite to reflect shipped behavior).
