import pytest
from core.scrapers.utils import is_strict_number, is_strict_uncensored_number


POSITIVE_NUMERIC_PREFIX = [
    "200GANA-3360",
    "529STCV-152",
    "7IPZ-154",
]

POSITIVE_STANDARD = [
    "SONE-205",
    "T28-103",
]

POSITIVE_FC2_VARIANTS = [
    "FC2PPV-4943690",
    "FC2PPV4943690",
    "FC2 PPV 4943690",
    "FC2PPV_4943690",
    "FC2-PPV-4943690",
    "FC2-4943690",
    "fc2ppv-4943690",
]

POSITIVE_UNCENSORED = [
    "090122_001",
    "020317-001",
    "n0762",
    # G（core/scraper.py:848）現況以 startswith('heyzo') 判無碼；本表是 C/D/G 的單一事實來源，不得漏
    "HEYZO-1234",
    "heyzo1234",
]

# 前置正規化 s.strip() 是刻意行為：使用者從別處貼進來的番號常帶前後空白/換行。
# 「整串判定」擋的是**夾在中間**的雜訊（見 ALL_NEGATIVE 的兩條），不是前後空白。
POSITIVE_SURROUNDING_WHITESPACE = [
    "  SONE-103  ",
    "SONE-103\n",
    "\tSONE-103",
    "　SONE-103　",  # 全形空白
]

ALL_POSITIVE = (
    POSITIVE_NUMERIC_PREFIX
    + POSITIVE_STANDARD
    + POSITIVE_FC2_VARIANTS
    + POSITIVE_UNCENSORED
    + POSITIVE_SURROUNDING_WHITESPACE
)

ALL_NEGATIVE = [
    "",
    "   ",
    "三上悠亜",
    "巨乳 2024",
    "S1 NO.1 STYLE",
    "IPZ",
    "2024",
    "../etc/passwd/SONE-103",
    "https://evil.com/SONE-103",
    "hhd800.com@SONE-103",
    "SONE-103\nSSIS-001",
    "SONE\n-103",
]


@pytest.mark.parametrize("num", POSITIVE_NUMERIC_PREFIX)
def test_strict_number_positive_numeric_prefix(num: str):
    assert is_strict_number(num) is True


@pytest.mark.parametrize("num", POSITIVE_STANDARD)
def test_strict_number_positive_standard(num: str):
    assert is_strict_number(num) is True


@pytest.mark.parametrize("num", POSITIVE_FC2_VARIANTS)
def test_strict_number_positive_fc2_variants(num: str):
    assert is_strict_number(num) is True


@pytest.mark.parametrize("num", POSITIVE_UNCENSORED)
def test_strict_number_positive_uncensored(num: str):
    assert is_strict_number(num) is True


@pytest.mark.parametrize("num", POSITIVE_SURROUNDING_WHITESPACE)
def test_strict_number_strips_surrounding_whitespace(num: str):
    """前後空白/換行是 strip 掉的（刻意）；夾在中間的換行仍必須 False（見 ALL_NEGATIVE）。"""
    assert is_strict_number(num) is True


@pytest.mark.parametrize("val", ALL_NEGATIVE)
def test_strict_number_negative_cases(val: str):
    assert is_strict_number(val) is False
    assert is_strict_uncensored_number(val) is False


def test_strict_number_none_case():
    assert is_strict_number(None) is False
    assert is_strict_uncensored_number(None) is False


def test_strict_uncensored_number_partition():
    # True for uncensored
    assert is_strict_uncensored_number("FC2-4943690") is True
    assert is_strict_uncensored_number("090122_001") is True
    assert is_strict_uncensored_number("020317-001") is True
    assert is_strict_uncensored_number("n0762") is True
    assert is_strict_uncensored_number("HEYZO-1234") is True
    assert is_strict_uncensored_number("heyzo1234") is True

    # False for censored
    assert is_strict_uncensored_number("SONE-205") is False
    assert is_strict_uncensored_number("200GANA-3360") is False
    assert is_strict_uncensored_number("T28-103") is False


def test_strict_number_structural_invariant():
    # 結構不變式：對全部正反例，is_strict_uncensored_number(x) is True ⇒ is_strict_number(x) is True
    for item in ALL_POSITIVE + ALL_NEGATIVE + [None]:
        uncensored_res = is_strict_uncensored_number(item)
        strict_res = is_strict_number(item)
        if uncensored_res:
            assert strict_res is True, f"Invariant violated for {item!r}: uncensored=True but strict=False"
