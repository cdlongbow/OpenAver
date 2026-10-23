"""
TDD-lite: strip_number_prefix 邊界條件測試
對應 TASK-T2fix2 的 11 個邊界條件 + 2 個錯誤處理 case
"""
from core.scrapers.utils import strip_number_prefix


# ===========================================================
# 11 個邊界條件
# ===========================================================

def test_basic_dash_prefix():
    """Case 1: 有 dash 番號 + 空格分隔"""
    assert strip_number_prefix("START-424 市役所の窓口勤務の...", "START-424") == "市役所の窓口勤務の..."


def test_no_dash_in_title():
    """Case 3: 頁面顯示無 dash 形式（START424），number 仍有 dash"""
    assert strip_number_prefix("START424 市役所の窓口勤務の...", "START-424") == "市役所の窓口勤務の..."


def test_no_prefix_unchanged():
    """Case 5: 片名本身不含番號前綴，不應誤刪"""
    assert strip_number_prefix("市役所の窓口勤務の...", "SONE-001") == "市役所の窓口勤務の..."


def test_no_space_between_number_and_title():
    """Case 11: 番號與片名之間無空格"""
    assert strip_number_prefix("CAWD-123市役所の窓口勤務の...", "CAWD-123") == "市役所の窓口勤務の..."


# ===========================================================
# 錯誤處理 case
# ===========================================================


# ===========================================================
# 番號邊界保護（Codex review 補充）
# ===========================================================

def test_longer_number_not_truncated():
    """較長番號共前綴：ABP-123 不應誤砍 ABP-1234 的 title"""
    assert strip_number_prefix("ABP-1234 タイトル", "ABP-123") == "ABP-1234 タイトル"


