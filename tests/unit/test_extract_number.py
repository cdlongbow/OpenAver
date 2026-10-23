"""
TestExtractNumber — extract_number 和 normalize_number 單元測試
（搬自 tests/integration/test_new_scrapers.py TestExtractNumber）

純邏輯測試，不需 mock
"""
import pytest
from core.scrapers.utils import extract_number, is_strict_number, normalize_number_impl


class TestExtractNumber:
    """extract_number 和 normalize_number 單元測試"""


    def test_extract_number_hyphen_2digit(self):
        """hyphen 格式 2-digit suffix 正確提取（T6b regex 修正）"""
        result = extract_number("041417-41.mp4")
        assert result == "041417-41"

    # --- TASK-73a-T2: 單字母 + 4 位無碼番號（Tokyo Hot）---

    def test_extract_single_letter_tokyo_hot_full_filename(self):
        """用戶 bug 本體：[無碼]n0762 Tokyo Hot n0762.mp4 → N0762（大寫無 hyphen）"""
        result = extract_number("[無碼]n0762 Tokyo Hot n0762.mp4")
        assert result == "N0762"


    # --- TASK-73a-T2: 回歸守衛（單字母 pattern 不得污染既有行為）---

    def test_regression_multiletter_no_hyphen_still_inserts(self):
        """SONE205.mp4 → SONE-205（多字母走 index 6，照舊插 hyphen）"""
        assert extract_number("SONE205.mp4") == "SONE-205"

    def test_regression_hyphen_format_unchanged(self):
        """ABC-123.mp4 → ABC-123（帶 hyphen 不變）"""
        assert extract_number("ABC-123.mp4") == "ABC-123"


    def test_regression_t28_unchanged(self):
        """T28-103.mp4 → T28-103（混合格式不變）"""
        assert extract_number("T28-103.mp4") == "T28-103"


    # --- TASK-73a-T2 bugfix: right-side digit boundary (no truncation) ---

    def test_no_truncate_5digit_n12345(self):
        """n12345.mp4 不應截斷為 N1234（單字母 + 5 位 → 不是 Tokyo Hot，應回 None）"""
        result = extract_number("n12345.mp4")
        # 5-digit after single letter is NOT Tokyo Hot (spec: exactly 4 digits)
        # Earlier patterns don't match either, so result must NOT be N1234
        assert result != "N1234"
        assert result is None


    # --- TASK-73e-T8: 前綴收窄負向 case ---

    def test_non_th_prefix_A_holiday(self):
        """holiday_A2024.mp4 → None（A 非 Tokyo Hot 前綴 n/k/c/m/s，不得誤抽）"""
        assert extract_number("holiday_A2024.mp4") is None


# --- TASK-caps: 7 字母前綴 cap 對齊（{1,6}/{2,6} → {1,7}/{2,7}）---

class TestExtractNumberCapAlignment:
    """7 字母前綴（如 PARATHD）不再被 re.search 滑窗截斷掉首字"""

    def test_parathd_hyphen_lowercase(self):
        """parathd-02976.mp4 → PARATHD-02976（7 字母前綴，帶 hyphen，小寫輸入）"""
        assert extract_number("parathd-02976.mp4") == "PARATHD-02976"


class TestExtractNumberTASK139T5BackendAccepts:
    """139-T5：前端不再改寫，三個代表例的原字串／trim 後字串，後端（C/H）仍接得住。"""

    @pytest.mark.parametrize("raw", ["n0762", ])
    def test_is_strict_number_accepts_raw_input(self, raw):
        assert is_strict_number(raw) is True

    def test_normalize_number_impl_n0762_no_hyphen(self):
        """n0762 → N0762，不是 N-0762（F8-2 must-not-break，本卡要防的回歸就是這個）"""
        assert normalize_number_impl("n0762") == "N0762"


class TestExtractNumberSpecSection2Coverage:
    """
    TASK-103-T5 DoD #1：spec §2 明列的格式（日期式/底線式/方括號/Tokyo Hot/123ABC）
    在刪除前端 extractNumber 後，這是唯一還能證明「後端 9-pattern 權威版涵蓋
    這些格式」的地方——JS 側 4-pattern 簡化版本來就沒實作這幾種，只有 Python
    側測試能證明 spec §2 的承諾成立。
    """


    def test_bracket_format_abc_123(self):
        """[ABC-123].mp4 → ABC-123（方括號式，spec §2 明列格式）"""
        assert extract_number("[ABC-123].mp4") == "ABC-123"


class TestExtractNumberTASK139T1b:
    """TASK-139-T1b: A（extract_number）FC2 收斂與 F8/F9 守衛測試。"""

    # FC2_TOKEN_PATTERN 的左邊界守衛（第 3 輪 review：grok 與 sonnet 各自獨立命中）。
    # patterns[0] 從精確字面 `FC2-PPV-\d+` 放寬成子字串比對後排在第一順位，
    # 沒有左邊界的話 re.search 會咬進**別的 token 中間**：一部本來解得出 SONE-205 的片
    # 會變成 FC2-1，錯番號直接寫進 NFO 與收藏庫。
    @pytest.mark.parametrize("filename,expected", [
        ("SONE-205fc21.mp4", "SONE-205"),        # 不得變成 FC2-1
    ])
    def test_fc2_token_requires_left_boundary(self, filename, expected):
        assert extract_number(filename) == expected

    # 反向：左邊界是非英數時**必須**照抓（這一組是本卡的改善，不得被上面那條守衛誤殺）
    @pytest.mark.parametrize("filename", [
        "hhd800.com@FC2PPV4943690.mp4",   # 改動前解成 HHD-800（抓到域名），現在正確
    ])
    def test_fc2_still_matched_after_non_alnum(self, filename):
        assert extract_number(filename) == "FC2-4943690"

    @pytest.mark.parametrize("filename", [
        "FC2PPV-4943690.mp4",
        "FC2-PPV-4943690.mp4",
    ])
    def test_extract_number_seven_fc2_shapes(self, filename):
        """七形 FC2 檔名全部解析為 FC2-4943690。"""
        assert extract_number(filename) == "FC2-4943690"


    # --- F8 must-not-break 四條 ---

    def test_f8_dmm_content_id_1sdms00808(self):
        """F8-1: 1sdms00808.mp4 → SDMS-00808（不被破壞）"""
        assert extract_number("1sdms00808.mp4") == "SDMS-00808"


    def test_f8_date_format_delimiters_not_swapped(self):
        """F8-3: 一本道/加勒比日期格式分隔符不互換（020317-001 與 090122_001）"""
        assert extract_number("020317-001.mp4") == "020317-001"
        assert extract_number("090122_001.mp4") == "090122_001"

    # --- F9 反向鎖 ---


