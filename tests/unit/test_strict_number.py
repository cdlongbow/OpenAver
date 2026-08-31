import pytest
from core.scrapers.utils import (
    is_lenient_number,
    is_strict_number,
    is_strict_uncensored_number,
)


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

POSITIVE_NO_HYPHEN = [
    "SONE205",
    "ABC123",
    "T28103",
    "sone205",
]

ALL_POSITIVE = (
    POSITIVE_NUMERIC_PREFIX
    + POSITIVE_STANDARD
    + POSITIVE_FC2_VARIANTS
    + POSITIVE_UNCENSORED
    + POSITIVE_SURROUNDING_WHITESPACE
    + POSITIVE_NO_HYPHEN
)

NEGATIVE_PARTIAL_NUMBERS = [
    # 一般形（鎖 `[A-Z]+-?\d{3,}` 的位數下限）
    "ABP-01",
    "ABP-1",
    "SNIS-1",
    "ABC-12",
    "SONE-01",
    # 數字前綴形（鎖 `\d{1,4}[A-Z]+-\d{3,}` 的位數下限）
    "200GANA-36",
    "7IPZ-01",
    "529STCV-1",
    # 混合形（鎖 `[A-Z]+\d+-\d{3,}` 的位數下限）
    "T28-01",
    "T28-12",
    # FC2 / HEYZO 形（鎖那三條 uncensored pattern 的位數下限）——
    # 少了下限，使用者打 HEYZO-12 想瀏覽系列會被判成完整番號、候選清單消失
    "FC21",
    "FC2-12",
    "HEYZO1",
    "HEYZO-12",
]

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
] + NEGATIVE_PARTIAL_NUMBERS


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


@pytest.mark.parametrize("num", POSITIVE_NO_HYPHEN)
def test_strict_number_positive_no_hyphen(num: str):
    """DoD 增補正向鎖：無 hyphen 形 SONE205/ABC123/T28103/sone205 皆為 True"""
    assert is_strict_number(num) is True


@pytest.mark.parametrize("num", NEGATIVE_PARTIAL_NUMBERS)
def test_strict_number_negative_partial_numbers(num: str):
    """DoD 增補反向鎖：部分番號 ABP-01/ABP-1/SNIS-1/ABC-12/SONE-01 皆為 False"""
    assert is_strict_number(num) is False


def test_is_number_format_and_is_partial_number_exclusive():
    """DoD 增補：is_number_format 與 is_partial_number 不得同時為 True"""
    from core.scraper import is_number_format, is_partial_number
    for s in ["SNIS-1", "ABP-01", "ABC-12", "SONE-01",
              # grok review 抓到 sonnet 漏掉的一組：FC2/HEYZO 的短尾也必須留給 partial
              "FC21", "HEYZO1", "HEYZO-12"]:
        assert is_number_format(s) is False, f"is_number_format({s!r}) 應為 False"
        assert is_partial_number(s) is True, f"is_partial_number({s!r}) 應為 True"


# ============ TASK-139-T8：D 專用寬表測試 ============

# 舊 D（139b 之前）= is_strict_number(s)；新 D = is_lenient_number(s)
CORPUS_T8 = [
    # 短尾碼（1-2 位，收窄修復對象——舊 D 收、is_strict_number 不收）
    "HITMA-16", "T28-10", "ABC-1", "SONE-01", "IPZZ-03", "SNIS-1", "ABP-01",
    # ❗數字前綴 ＋ 1-2 位尾碼：**舊 D 也不收**（`^[A-Z]+-\d+$` 要求字母開頭），
    # 不是回歸、不在本卡範圍。放進語料是為了「反向鎖住它仍然不收」。
    "200GANA-36", "529STCV-1",
    # 唯一已知殘留（承重段窮舉出的 1 筆例外，仍收不到）
    "FC2-PPV-12",
    # 無 hyphen 形（T4 的既有放寬，不得回退——is_strict_number 已收，is_lenient_number 應維持收）
    "SONE205", "HEYZO1234", "ABC123",
    # 一般合法番號（is_strict_number 已收，is_lenient_number 應維持收）
    "SONE-205", "200GANA-3360", "FC2PPV-4943690", "090122_001", "020317-001",
    # 帶尾綴／雜訊（皆不應被 D 收，短尾碼 pattern 不吃字母結尾或路徑雜訊）
    "SONE-205-C", "../etc/passwd/SONE-103", "https://evil.com/SONE-103",
    "hhd800.com@SONE-103", "SONE-103\nSSIS-001",
    # 空值 / 純中文
    "", "三上悠亜",
]
EXPECTED_DIFF_T8 = [
    ("HITMA-16", False, True), ("T28-10", False, True), ("ABC-1", False, True),
    ("SONE-01", False, True), ("IPZZ-03", False, True), ("SNIS-1", False, True),
    ("ABP-01", False, True),
    # ❗`200GANA-36` / `529STCV-1` **不在差集裡**——見上方語料註解，兩者 old_D 也是 False。
]


def test_t8_diff_matches_expected():
    diff = [
        (s, is_strict_number(s), is_lenient_number(s))
        for s in CORPUS_T8
        if is_strict_number(s) != is_lenient_number(s)
    ]
    assert diff == EXPECTED_DIFF_T8


def test_t8_fullwidth_space_preserved():
    """全形空白反向鎖：U+3000 全形空白在 is_strict_number, is_lenient_number, extract_number 均維持正常。"""
    assert is_strict_number("FC2　1234567") is True
    assert is_lenient_number("HEYZO　1234") is True
    from core.scrapers.utils import extract_number
    assert extract_number("FC2　1234567") == "FC2-1234567"


def test_t8_crlf_rejected():
    """\r\n 正向鎖：含換行的字串被排除，不通過 strict 與 lenient 驗證。"""
    assert is_strict_number("HEYZO\r\n1234") is False
    assert is_lenient_number("HEYZO\r\n1234") is False


