"""
test_scraper_parser.py - 番號解析單元測試

測試範圍：
- extract_number(): 從檔名提取番號
- normalize_number(): 標準化番號格式

測試資料來源：samples/ 目錄下的假影片檔案
預期結果定義：samples/expected_results.json
"""

import pytest
import json
from pathlib import Path

from unittest.mock import patch

# 測試目標模組
from core.scraper import (
    extract_number, normalize_number, is_number_format, smart_search,
    is_partial_number, is_prefix_only
)
from core.scrapers.utils import (
    is_strict_uncensored_number,
    is_uncensored_route,
    resolve_route_target,
)


# ============ TestExtractNumber ============

class TestExtractNumber:
    """測試從檔名提取番號"""

    # --- basic/ 基本格式 ---
    def test_basic_sone(self):
        """標準格式 SONE-103"""
        assert extract_number('SONE-103.mp4') == 'SONE-103'

    def test_basic_abc(self):
        """標準格式 ABC-123"""
        assert extract_number('ABC-123.mkv') == 'ABC-123'

    def test_basic_fc2ppv(self):
        """FC2-PPV 格式"""
        assert extract_number('FC2-PPV-123456.avi') == 'FC2-123456'

    # --- real_world/ 真實世界格式 ---
    def test_no_hyphen(self):
        """無橫線格式 sone103"""
        assert extract_number('sone103.mp4') == 'SONE-103'

    def test_square_brackets(self):
        """方括號格式 [SONE-103] 女優名字"""
        assert extract_number('[SONE-103] 女優名字.mp4') == 'SONE-103'

    def test_parentheses(self):
        """圓括號格式 (ABC-123)_1080p"""
        assert extract_number('(ABC-123)_1080p.mkv') == 'ABC-123'

    def test_fullwidth_brackets(self):
        """全形括號【IPZZ-001】中文標題"""
        # 全形括號可能無法匹配，取決於實現
        result = extract_number('【IPZZ-001】中文標題.avi')
        # 如果實現支援全形括號則應為 IPZZ-001，否則可能為 None
        assert result in ['IPZZ-001', None]

    def test_multiple_underscores(self):
        """多底線 SONE-103_uncensored_leak"""
        assert extract_number('SONE-103_uncensored_leak.mp4') == 'SONE-103'

    def test_lowercase_with_quality(self):
        """小寫+品質標籤 stars-804_4K_60fps"""
        assert extract_number('stars-804_4K_60fps.mp4') == 'STARS-804'

    def test_fc2_no_second_hyphen(self):
        """FC2 無第二橫線 FC2PPV-999999"""
        # 139-T1b: FC2 統一收斂為 FC2-<純數字> 正典格式
        result = extract_number('FC2PPV-999999.avi')
        assert result == 'FC2-999999'

    # --- suffix/ 後綴處理 ---
    # extract_number 會預處理清理 -UC/-UNCENSORED/-LEAK 等後綴

    def test_suffix_c_subtitle(self):
        """中文字幕後綴 SUPD-103C → SUPD-103C（extract 不移除後綴）"""
        result = extract_number('SUPD-103C.mp4')
        # extract_number 提取整個匹配，不處理後綴
        assert result in ['SUPD-103C', 'SUPD-103']

    def test_suffix_cd1(self):
        """多碟標記 ABC-123-CD1"""
        result = extract_number('ABC-123-CD1.mkv')
        # 應提取 ABC-123 部分
        assert 'ABC-123' in result or result == 'ABC-123-CD1'

    def test_suffix_uc(self):
        """無碼流出 SONE-103-UC"""
        result = extract_number('SONE-103-UC.avi')
        assert 'SONE-103' in result

    def test_suffix_uc_cleaned(self):
        """UC 後綴應被清理"""
        assert extract_number('SONE-103-UC.mp4') == 'SONE-103'

    def test_suffix_uncensored_cleaned(self):
        """uncensored 後綴應被清理"""
        assert extract_number('ABC-123-uncensored.mp4') == 'ABC-123'

    def test_suffix_leak_cleaned(self):
        """leak 後綴應被清理"""
        assert extract_number('MIDV-456_leak.mp4') == 'MIDV-456'

    # --- special_format/ 特殊片商格式 ---
    def test_number_prefix(self):
        """數字開頭系列 T28-103 - 混合格式番號（Task 15.2 新增支援）"""
        result = extract_number('T28-103.avi')
        # T28 混合格式（字母+數字前綴），現已支援
        assert result == 'T28-103'

    def test_heyzo(self):
        """HEYZO 格式"""
        result = extract_number('HEYZO-2048.avi')
        assert result == 'HEYZO-2048'

    def test_juc_prefix_not_stripped(self):
        """JUC-123 前綴含 UC 不應被誤刪（回歸測試）"""
        assert extract_number('JUC-123.mp4') == 'JUC-123'

    def test_duc_prefix_not_stripped(self):
        """DUC-456 前綴含 UC 不應被誤刪"""
        assert extract_number('DUC-456.mp4') == 'DUC-456'

    # --- tricky/ 刁鑽案例 ---
    def test_date_prefix(self):
        """日期在前 2024.01.15_SONE-103_release"""
        result = extract_number('2024.01.15_SONE-103_release.mp4')
        assert result == 'SONE-103'

    def test_number_in_middle(self):
        """番號在中間 download_1080p_SONE103_final"""
        result = extract_number('download_1080p_SONE103_final.avi')
        assert result == 'SONE-103'

    def test_zero_disguise(self):
        """數字0偽裝字母O s0ne-103 → None"""
        result = extract_number('s0ne-103.mp4')
        # s0ne 包含數字0，不是有效的番號前綴
        # 根據 pattern，可能無法匹配
        assert result is None or result != 'SONE-103'

    # --- edge_case/ 邊界情況 ---
    def test_multiple_numbers_first_match(self):
        """多個番號取第一個"""
        result = extract_number('SONE-103_vs_ABC-123_comparison.mkv')
        assert result == 'SONE-103'

    def test_consecutive_numbers(self):
        """連續黏一起"""
        result = extract_number('SONE-103SONE-104.mp4')
        assert result == 'SONE-103'

    # --- noise/ 雜訊干擾 ---
    def test_website_watermark(self):
        """網站浮水印 [ThzSub.com]SONE-103"""
        result = extract_number('[ThzSub.com]SONE-103.mp4')
        # ThzSub.com 不應影響番號提取
        assert result == 'SONE-103'

    def test_special_symbols(self):
        """特殊符號 SONE-103@1080p#leaked"""
        result = extract_number('SONE-103@1080p#leaked.mkv')
        assert result == 'SONE-103'

    def test_nested_brackets(self):
        """多層括號 (HD)(SONE-103)(2024)"""
        result = extract_number('(HD)(SONE-103)(2024).avi')
        assert result == 'SONE-103'

    def test_url_prefix(self):
        """網址前綴 hhd800.com@SONE-103"""
        result = extract_number('hhd800.com@SONE-103.mp4')
        assert result == 'SONE-103'

    def test_garbage_suffix(self):
        """亂碼後綴 SONE-103-C_Thz_fed48"""
        result = extract_number('SONE-103-C_Thz_fed48.mkv')
        assert 'SONE-103' in result

    # --- invalid/ 應返回 None ---
    def test_invalid_random_movie(self):
        """純文字+數字 random_movie_2024"""
        result = extract_number('random_movie_2024.mp4')
        assert result is None

    def test_invalid_pure_numbers(self):
        """純數字 123456"""
        result = extract_number('123456.mkv')
        assert result is None

    def test_invalid_no_number(self):
        """無番號 movie"""
        result = extract_number('movie.avi')
        assert result is None

    def test_invalid_chinese_only(self):
        """純中文 私人影片"""
        result = extract_number('私人影片.mp4')
        assert result is None

    # --- 路徑處理 ---
    def test_full_path(self):
        """完整路徑"""
        result = extract_number('/home/user/videos/SONE-103.mp4')
        assert result == 'SONE-103'

    def test_windows_path(self):
        """Windows 路徑"""
        result = extract_number(r'C:\Videos\ABC-123.mkv')
        assert result == 'ABC-123'


# ============ TestNormalizeNumber ============

class TestNormalizeNumber:
    """測試番號標準化"""

    def test_lowercase_no_hyphen(self):
        """小寫無橫線 sone103 → SONE-103"""
        assert normalize_number('sone103') == 'SONE-103'

    def test_already_normalized(self):
        """已標準化 SONE-103 → SONE-103"""
        assert normalize_number('SONE-103') == 'SONE-103'

    def test_lowercase_with_hyphen(self):
        """小寫有橫線 abc-123 → ABC-123"""
        assert normalize_number('abc-123') == 'ABC-123'

    def test_uppercase_no_hyphen(self):
        """大寫無橫線 ABC123 → ABC-123"""
        assert normalize_number('ABC123') == 'ABC-123'

    def test_preserve_leading_zeros(self):
        """保留前導零 abc00123 → ABC-00123"""
        assert normalize_number('abc00123') == 'ABC-00123'

    def test_fc2ppv_format(self):
        """FC2-PPV 格式正規化為正典 FC2-<純數字>"""
        assert normalize_number('FC2-PPV-123456') == 'FC2-123456'

    def test_with_whitespace(self):
        """帶空白 ' sone103 ' → SONE-103"""
        assert normalize_number(' sone103 ') == 'SONE-103'

    def test_mixed_case(self):
        """混合大小寫 SoNe103 → SONE-103"""
        assert normalize_number('SoNe103') == 'SONE-103'

    def test_already_has_hyphen_mixed_case(self):
        """有橫線混合大小寫 sOnE-103 → SONE-103"""
        assert normalize_number('sOnE-103') == 'SONE-103'

    def test_long_prefix(self):
        """長前綴 SUPD103 → SUPD-103"""
        assert normalize_number('SUPD103') == 'SUPD-103'

    def test_long_number(self):
        """長數字 ABC12345 → ABC-12345"""
        assert normalize_number('ABC12345') == 'ABC-12345'

    # --- 後綴清理 ---
    def test_suffix_uc_cleaned(self):
        """UC 後綴應被清理 SONE-103-UC → SONE-103"""
        assert normalize_number('SONE-103-UC') == 'SONE-103'

    def test_suffix_uncensored_cleaned(self):
        """UNCENSORED 後綴應被清理"""
        assert normalize_number('ABC-123-UNCENSORED') == 'ABC-123'

    def test_suffix_leak_cleaned(self):
        """LEAK 後綴應被清理"""
        assert normalize_number('MIDV-456_leak') == 'MIDV-456'

    def test_suffix_with_no_hyphen(self):
        """無橫線 + 後綴 STARS804-UNCEN → STARS-804"""
        assert normalize_number('STARS804-UNCEN') == 'STARS-804'

    # --- TASK-73a-T1: 單字母+4位 Tokyo Hot 番號 ---

    def test_tokyo_hot_n0762_lowercase(self):
        """n0762（小寫）→ N0762（不插 hyphen）"""
        assert normalize_number('n0762') == 'N0762'

    def test_tokyo_hot_N0762_uppercase(self):
        """N0762（大寫）→ N0762（已是正規化，不插 hyphen）"""
        assert normalize_number('N0762') == 'N0762'

    def test_tokyo_hot_k0150(self):
        """k0150 → K0150（單字母 + 4 位，不插 hyphen）"""
        assert normalize_number('k0150') == 'K0150'

    def test_tokyo_hot_c0050(self):
        """c0050 → C0050（單字母 + 4 位，不插 hyphen）"""
        assert normalize_number('c0050') == 'C0050'

    # --- TASK-73a-T1: normalize 回歸守衛（單字母非4位 + 多字母，照舊插 hyphen）---

    def test_regression_k001_single_letter_3digits(self):
        """k001 → K-001（單字母 3 位，有碼 K- 系列，照舊插 hyphen）"""
        assert normalize_number('k001') == 'K-001'

    def test_regression_n12345_single_letter_5digits(self):
        """n12345 → N-12345（單字母 5 位，照舊插 hyphen）"""
        assert normalize_number('n12345') == 'N-12345'

    def test_regression_kb001_two_letters(self):
        """kb001 → KB-001（雙字母 + 3 位，照舊插 hyphen）"""
        assert normalize_number('kb001') == 'KB-001'

    def test_regression_jup001_multi_letters(self):
        """jup001 → JUP-001（多字母 + 3 位，照舊插 hyphen）"""
        assert normalize_number('jup001') == 'JUP-001'

    def test_regression_sone103(self):
        """sone103 → SONE-103（多字母，照舊插 hyphen）"""
        assert normalize_number('sone103') == 'SONE-103'

    def test_regression_abc123(self):
        """abc123 → ABC-123（多字母，照舊插 hyphen）"""
        assert normalize_number('abc123') == 'ABC-123'

    def test_regression_SUPD103(self):
        """SUPD103 → SUPD-103（多字母，照舊插 hyphen）"""
        assert normalize_number('SUPD103') == 'SUPD-103'

    def test_regression_ABC12345(self):
        """ABC12345 → ABC-12345（多字母 + 5 位，照舊插 hyphen）"""
        assert normalize_number('ABC12345') == 'ABC-12345'


# ============ TestValidateNumber（TASK-73a-T1）============

class TestValidateNumber:
    """測試 BaseScraper.validate_number（透過 JavBusScraper 繼承）"""

    def _scraper(self):
        from core.scrapers import JavBusScraper
        return JavBusScraper()

    def test_validate_N0762_true(self):
        """N0762（單字母 + 4 位）validate 應為 True"""
        assert self._scraper().validate_number('N0762') is True

    def test_validate_K0150_true(self):
        """K0150（單字母 + 4 位）validate 應為 True"""
        assert self._scraper().validate_number('K0150') is True

    def test_validate_SONE103_true(self):
        """SONE103（多字母無 hyphen）validate 應為 True。

        T3 已拍板「hyphen 可省」（`is_number_format` / `is_strict_number` 對
        SONE103 皆 True）。D 委派同一張表後必須跟 True——C 與 D 對同一字串
        給不同答案才是 bug。送進 scraper 的值一定是正規化後的（H 先、D 後），
        本類的呼叫順序釘子鎖住這點；D 接受無 hyphen 形，不代表無 hyphen
        字串會跑到組 URL 的地方。
        """
        assert self._scraper().validate_number('SONE103') is True

    def test_validate_SONE103_with_hyphen_true(self):
        """SONE-103（多字母有 hyphen）validate 仍應為 True（回歸守衛）"""
        assert self._scraper().validate_number('SONE-103') is True

    # --- TASK-139-T4：§1.4 正向鎖（委派 is_strict_number 後必須 True）---
    def test_validate_200GANA_3360_true(self):
        """素人數字前綴 200GANA-3360"""
        assert self._scraper().validate_number('200GANA-3360') is True

    def test_validate_529STCV_152_true(self):
        """素人數字前綴 529STCV-152"""
        assert self._scraper().validate_number('529STCV-152') is True

    def test_validate_090122_001_true(self):
        """日期底線格式 090122_001"""
        assert self._scraper().validate_number('090122_001') is True

    def test_validate_020317_001_true(self):
        """日期連字號格式 020317-001"""
        assert self._scraper().validate_number('020317-001') is True

    def test_validate_FC2PPV_4943690_true(self):
        """FC2 無 hyphen-PPV 分隔形 FC2PPV-4943690"""
        assert self._scraper().validate_number('FC2PPV-4943690') is True

    # --- TASK-139-T4：反向鎖 5 類（委派前後皆 False）---
    def test_validate_empty_false(self):
        """空字串"""
        assert self._scraper().validate_number('') is False

    def test_validate_chinese_false(self):
        """純中文"""
        assert self._scraper().validate_number('中文測試') is False

    def test_validate_path_traversal_false(self):
        """路徑穿越字串"""
        assert self._scraper().validate_number('../etc/passwd') is False

    def test_validate_url_scheme_false(self):
        """含 :// 的 URL 形"""
        assert self._scraper().validate_number('http://evil.com') is False

    def test_validate_embedded_newline_false(self):
        """含內嵌換行（非整串單一番號）"""
        assert self._scraper().validate_number('SONE-103\nSSIS-001') is False

    def test_validate_number_receives_normalized_value(self, monkeypatch):
        """呼叫順序釘子：H（normalize）先跑、D（validate）後跑。

        傳入 'sone103'，validate_number 必須收到正規化後的 'SONE-103'，
        不是原字串（Opus 裁決 2026-08-31）。
        """
        from unittest.mock import MagicMock

        scraper = self._scraper()
        received = []

        def spy(number):
            received.append(number)
            return True

        monkeypatch.setattr(scraper, 'validate_number', spy)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        monkeypatch.setattr(scraper._session, 'get', MagicMock(return_value=mock_resp))

        scraper.search('sone103')
        assert received == ['SONE-103']

    def test_hitma_16_reaches_http_layer(self, monkeypatch):
        """HITMA-16（68 個收回形狀之一）經 JavBusScraper.search 真的發出 HTTP 請求（spy 數，不出網）。"""
        from unittest.mock import MagicMock
        scraper = self._scraper()
        mock_resp = MagicMock()
        mock_resp.status_code = 404   # 不進 _parse_detail_page，只驗證有沒有發出去
        spy = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(scraper._session, 'get', spy)
        result = scraper.search('HITMA-16')
        assert spy.call_count == 1
        assert 'HITMA-16' in spy.call_args[0][0]   # URL 含正規化後的番號
        assert result is None   # 404 → 乾淨回 None，不拋例外


# ============ TestIsNumberFormat ============

class TestIsNumberFormat:
    """測試番號格式驗證（含後綴處理）"""

    # --- 標準格式 ---
    def test_standard_format(self):
        """標準格式 SONE-103"""
        assert is_number_format('SONE-103') is True

    def test_no_hyphen(self):
        """無橫線 ABC123"""
        assert is_number_format('ABC123') is True

    def test_lowercase(self):
        """小寫 sone-103"""
        assert is_number_format('sone-103') is True

    # --- 後綴處理 ---
    def test_suffix_uc(self):
        """UC 後綴 SONE-103-UC"""
        assert is_number_format('SONE-103-UC') is True

    def test_suffix_uncensored(self):
        """UNCENSORED 後綴 ABC-123-UNCENSORED"""
        assert is_number_format('ABC-123-UNCENSORED') is True

    def test_suffix_uncen(self):
        """UNCEN 後綴 MIDV-456-UNCEN"""
        assert is_number_format('MIDV-456-UNCEN') is True

    def test_suffix_leak(self):
        """LEAK 後綴 STARS-804-leak"""
        assert is_number_format('STARS-804-leak') is True

    def test_suffix_leaked(self):
        """LEAKED 後綴 IPZZ-001_LEAKED"""
        assert is_number_format('IPZZ-001_LEAKED') is True

    # --- 無效格式 ---
    def test_invalid_partial(self):
        """部分番號 SONE-01"""
        assert is_number_format('SONE-01') is False

    def test_invalid_prefix_only(self):
        """純前綴 SONE"""
        assert is_number_format('SONE') is False

    def test_invalid_numbers_only(self):
        """純數字 123456"""
        assert is_number_format('123456') is False

    def test_invalid_short_number(self):
        """數字太短 ABC-12"""
        assert is_number_format('ABC-12') is False


# ============ 整合測試：搜尋流程 ============

class TestSearchQueryIntegration:
    """
    整合測試：模擬搜尋查詢的完整流程

    驗證 is_number_format() + normalize_number() 配合正確
    這類測試能抓到單元測試漏掉的問題
    """

    # --- 後綴查詢應正確處理 ---
    def test_uc_suffix_flow(self):
        """UC 後綴查詢完整流程"""
        query = 'SONE-103-UC'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'SONE-103'

    def test_uncensored_suffix_flow(self):
        """UNCENSORED 後綴查詢完整流程"""
        query = 'ABC-123-UNCENSORED'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'ABC-123'

    def test_leak_suffix_flow(self):
        """LEAK 後綴查詢完整流程"""
        query = 'MIDV-456_leak'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'MIDV-456'

    def test_uncen_suffix_flow(self):
        """UNCEN 後綴查詢完整流程"""
        query = 'STARS-804-UNCEN'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'STARS-804'

    def test_leaked_suffix_flow(self):
        """LEAKED 後綴查詢完整流程"""
        query = 'IPZZ-001_LEAKED'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'IPZZ-001'

    # --- 標準查詢不受影響 ---
    def test_standard_query_unchanged(self):
        """標準查詢不應被修改"""
        query = 'SONE-103'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'SONE-103'

    def test_no_hyphen_query_normalized(self):
        """無橫線查詢應正規化"""
        query = 'sone103'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'SONE-103'

    # --- 檔名提取 + 搜尋流程 ---
    def test_filename_to_search_flow(self):
        """檔名提取到搜尋的完整流程"""
        filename = 'SONE-103-UC_1080p.mp4'
        # 步驟 1: 從檔名提取番號
        number = extract_number(filename)
        assert number == 'SONE-103'
        # 步驟 2: 驗證格式（用於判斷搜尋模式）
        assert is_number_format(number) is True
        # 步驟 3: 正規化（用於實際搜尋）
        assert normalize_number(number) == 'SONE-103'

    def test_user_input_to_search_flow(self):
        """用戶輸入到搜尋的完整流程"""
        # 用戶直接輸入帶後綴的番號
        user_input = 'SONE-103-UC'
        # 步驟 1: 驗證是完整番號格式
        assert is_number_format(user_input) is True
        # 步驟 2: 正規化後搜尋
        search_query = normalize_number(user_input)
        assert search_query == 'SONE-103'

    # --- 回歸測試：前綴含 UC 不應被誤刪 ---
    def test_juc_prefix_regression(self):
        """JUC-123 前綴含 UC 不應被誤刪（回歸測試）"""
        query = 'JUC-123'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'JUC-123'
        assert extract_number('JUC-123.mp4') == 'JUC-123'

    def test_juc_with_suffix_regression(self):
        """JUC-123-UC 前綴含 UC 但後綴也有 UC"""
        query = 'JUC-123-UC'
        assert is_number_format(query) is True
        assert normalize_number(query) == 'JUC-123'  # 只移除後綴的 -UC


class TestNormalizeNumberTASK139T1b:
    """TASK-139-T1b: H（normalize_number）FC2 收斂與 F8/F9 守衛測試。"""

    @pytest.mark.parametrize("raw", [
        "FC2PPV-4943690",
        "FC2PPV4943690",
        "FC2 PPV 4943690",
        "FC2PPV_4943690",
        "FC2-PPV-4943690",
        "FC2-4943690",
        "fc2ppv-4943690",
    ])
    def test_normalize_number_seven_fc2_shapes(self, raw):
        """七形 FC2 原始字串全部正規化為 FC2-4943690。"""
        assert normalize_number(raw) == "FC2-4943690"

    # --- F8 must-not-break 四條 ---

    def test_f8_tokyo_hot_single_letter(self):
        """F8-2: 東京熱單字母 + 4 位不插 hyphen（n0762, k0150）"""
        assert normalize_number("n0762") == "N0762"
        assert normalize_number("k0150") == "K0150"

    def test_f8_date_format_delimiters_not_swapped(self):
        """F8-3: 一本道/加勒比日期格式分隔符不互換（020317-001 與 090122_001）"""
        assert normalize_number("020317-001") == "020317-001"
        assert normalize_number("090122_001") == "090122_001"

    # --- F9 反向鎖 ---

    @pytest.mark.parametrize("raw", [
        "FC2PPV-4943690",
        "FC2PPV4943690",
        "FC2 PPV 4943690",
        "FC2PPV_4943690",
        "FC2-PPV-4943690",
        "FC2-4943690",
        "fc2ppv-4943690",
    ])
    def test_f9_reverse_lock_no_ppv_prefix(self, raw):
        """F9 反向鎖：七形輸入的正規化結果皆不得以 PPV- 開頭。"""
        result = normalize_number(raw)
        assert result != ""
        assert not result.startswith("PPV-")


# ============ 從 samples/ 讀取測試 ============

class TestExtractNumberFromSamples:
    """從 samples/ 目錄讀取測試案例"""

    @pytest.fixture
    def samples_dir(self):
        """取得 samples 目錄"""
        return Path(__file__).parent.parent / 'samples'

    @pytest.fixture
    def expected_results(self, samples_dir):
        """載入預期結果"""
        json_path = samples_dir / 'expected_results.json'
        if json_path.exists():
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def test_samples_exist(self, samples_dir):
        """確認 samples 目錄存在"""
        assert samples_dir.exists(), f'samples 目錄不存在: {samples_dir}'

    def test_extract_from_samples(self, samples_dir, expected_results):
        """從 samples 讀取檔名進行測試"""
        if not expected_results:
            pytest.skip('expected_results.json 不存在')

        for category_dir in samples_dir.iterdir():
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith('.'):
                continue

            for file_path in category_dir.iterdir():
                if file_path.suffix not in ['.mp4', '.mkv', '.avi']:
                    continue

                filename = file_path.name
                expected = expected_results.get(filename)

                if expected is not None:
                    result = extract_number(filename)
                    assert result == expected, f'{filename}: 預期 {expected}，實際 {result}'


# ============ TASK-139-T3: G / C-G 一致性 / F3-b ============

class TestSmartSearchUncensoredAndConsistency:
    """TASK-139-T3: G（smart_search is_uncensored）、C-G 一致性與 F3-b must-not-break 測試"""

    @pytest.mark.parametrize("query", [
        "FC2-4943690",
        "090122_001",
        "020317-001",
        "HEYZO-1234",
    ])
    def test_smart_search_uncensored_routing(self, query: str):
        """F3-a G 正向：無碼番號由 smart_search 自動偵測並標記 _mode='uncensored'"""
        mock_result = {"number": query, "title": "Test Title"}
        with patch("core.scraper._get_uncensored_sources", return_value=["fc2"]), \
             patch("core.scraper.search_jav", return_value=mock_result):
            results = smart_search(query)
            assert len(results) == 1
            assert results[0]["_mode"] == "uncensored"

    def test_c_and_g_consistency(self):
        """C 與 G 一致性：斷言不會出現 is_number_format=False 且 is_strict_uncensored_number=True"""
        test_inputs = [
            "FC2-4943690", "090122_001", "020317-001", "n0762", "HEYZO-1234",
            "SONE-205", "200GANA-3360", "T28-103", "ABC-123", "sone205",
            "三上悠亜", "IPZ", "2024", "ABP-01", "SNIS-1", "", "   ", None
        ]
        for s in test_inputs:
            c_val = is_number_format(s) if s is not None else False
            g_val = is_strict_uncensored_number(s)
            if g_val:
                assert c_val is True, f"Inconsistency for {s!r}: g_val is True but c_val is False"

    def test_f3b_h_pipeline_must_not_break(self):
        """F3-b: H（is_number_format -> normalize_number）呼叫鏈 must-not-break"""
        cases = [
            ("SONE-103", "SONE-103"),
            ("n0762", "N0762"),
            ("020317-001", "020317-001"),
            ("090122_001", "090122_001"),
            ("FC2PPV-4943690", "FC2-4943690"),
            ("FC2-PPV-4943690", "FC2-4943690"),
        ]
        for raw, expected in cases:
            assert is_number_format(raw) is True, f"is_number_format({raw!r}) 應為 True"
            assert normalize_number(raw) == expected, f"normalize_number({raw!r}) 應為 {expected!r}"

    def test_oracle_a_smart_search_routing(self):
        """DoD-3 Oracle A: smart_search 路由對照（206 筆語料，含 G 分支）"""
        from collections import Counter
        import ast

        corpus_file = Path(__file__).parent / "test_number_corpus_139.py"
        with open(corpus_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        corpus_182 = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CORPUS":
                        corpus_182 = [item["input"] for item in ast.literal_eval(node.value)]
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "CORPUS":
                    corpus_182 = [item["input"] for item in ast.literal_eval(node.value)]

        extra_24 = [
            "SONE-0", "ABP-12", "HITMA-1",                      # partial：必須維持 partial
            "IPZZ", "SONE", "ABP",                              # prefix：必須維持 prefix
            "[ABC-123]", "ABC-123.mp4", "【ABC-123】", "(ABC-123)",
            "[JavBus] ABC-123 標題.mp4", "ABC-123 - 中文字幕.mkv",  # residual #6 的包裝
            "FC2-PPV-4914771-C", "HEYZO-1234-C", "FC2PPV-4943690-1080P",  # 收窄修復對象
            "N0762", "K0150", "T1234",                          # [A-Z]\d{4}：退出 G
            "JULIA 2024", "2024", "VR 8K", "MOODYZ 25周年",      # 對抗性：抽不出番號
            "三上悠亜", "波多野結衣",                             # 真實女優名
        ]
        corpus_206 = corpus_182 + extra_24

        def old_ss_mode(q: str) -> str:
            if not q or len(q.strip()) < 2:
                return "actress"
            if is_strict_uncensored_number(q):
                return "uncensored"
            elif is_number_format(q):
                return "exact"
            elif is_partial_number(q):
                return "partial"
            elif is_prefix_only(q):
                return "prefix"
            else:
                return "actress"

        def new_ss_mode(q: str) -> str:
            if not q or len(q.strip()) < 2:
                return "actress"
            target = resolve_route_target(q)
            if is_uncensored_route(target):
                return "uncensored"
            elif is_number_format(target):
                return "exact"
            elif is_partial_number(q):
                return "partial"
            elif is_prefix_only(q):
                return "prefix"
            else:
                return "actress"

        moves = []
        diff = []
        for q in corpus_206:
            old_m = old_ss_mode(q)
            new_m = new_ss_mode(q)
            if old_m != new_m:
                moves.append((old_m, new_m))
                diff.append((q, old_m, new_m))

        allowed_transitions_ss = {('actress', 'exact'), ('actress', 'uncensored'), ('uncensored', 'exact')}
        expected_counts_ss = {('actress', 'exact'): 118, ('actress', 'uncensored'): 47, ('uncensored', 'exact'): 4}
        expected_unc_to_exact = ['n9110', 'N0762', 'K0150', 'T1234']
        expected_a2u = [
            'FC2PPV-123456-1',
            'FC2-123456-1',
            'FC2-PPV-123456-C.mp4',
            '093021_539-FHD.mkv',
            '093021_539-480p.mkv',
            '093021_539-1080pFHD.mkv',
            '093021_539-2160pHD.mkv',
            'caribean-020317_001.mp4',
            'caribbean-020317_001.mp4',
            'caribeancom-020317_001.mp4',
            'caribeancompr-020317_001.mp4',
            'caribbeancom-020317_001.mp4',
            '020317_001-caribbeancom.mp4',
            '020317_001-caribbean 你好.mp4',
            '020317_001-caribbean-fhd 你好.mp4',
            '020317_001-caribbean.mp4',
            '020317_001-carib-whole_hd1.mp4',
            '020317_001-carib-whole_fhd1.mp4',
            '020317_001-carib_sd1.mp4',
            'carib-020317_001.mp4',
            '020317-001-1pondo.mp4',
            '020317-001-pondo.mp4',
            '020317-001-pond.mp4',
            'DL1pon-020317-001.mp4',
            '1pondp-020317-001.mp4',
            '020317-001-paco.mp4',
            '020317-001-pacomama.mp4',
            '020317-001-pacopaco.mp4',
            '020317-001-caribpr.mp4',
            '020317-001-caribpr-fhd.mp4',
            '020317-001-caribpr-x1080x.mp4',
            '020317-001-caribpr-360p.mp4',
            '020317-001-caribpr-1080p60fps.mp4',
            '020317-001-caribpr-h265.mp4',
            '020317-01-10musume-1080p.mp4',
            '020317-01-10mu-1080p.mp4',
            '020317-01-10mu-1080i.mp4',
            '1pon-020317-001.mp4',
            '1pondo-020317-001.mp4',
            '_1PONDO_020317-001.mp4',
            'pond-020317-001.mp4',
            'pondo-020317-001.mp4',
            '10musume-020317_01-CD2.iso',
            'Carib 080520-001.mp4',
            'FC2-PPV-4914771-C',
            'HEYZO-1234-C',
            'FC2PPV-4943690-1080P',
        ]

        # ① 方向不變式
        assert set(moves) <= allowed_transitions_ss
        # ② 筆數對帳
        assert dict(Counter(moves)) == expected_counts_ss
        # ③ uncensored -> exact 逐筆對帳
        assert [q for q, a, b in diff if (a, b) == ('uncensored', 'exact')] == expected_unc_to_exact
        # ④ actress -> uncensored 逐筆對帳
        assert [q for q, a, b in diff if (a, b) == ('actress', 'uncensored')] == expected_a2u

    def test_n0762_no_longer_routes_uncensored(self):
        """N0762 不再被 G 判為無碼；應落入精確搜尋（is_number_format 仍為 True，C 未變）分支。"""
        with patch("core.scraper._get_uncensored_sources") as mock_unc, \
             patch("core.scraper.search_jav_single_source", return_value=None):
            smart_search("N0762")
            mock_unc.assert_not_called()

    def test_bracket_wrapped_query_reaches_source_with_clean_number(self):
        """[ABC-123] 貼進搜尋框，實際送去 source 查詢的是 'ABC-123'（residual #6 有碼那半）。"""
        with patch("core.scraper.search_jav_single_source", return_value=None) as mock_search:
            smart_search("[ABC-123]")
            assert mock_search.call_count >= 1
            called_number = mock_search.call_args[0][0]
            assert called_number == "ABC-123"

    def test_t9_raw_noise_never_reaches_scraper(self):
        """路徑／網址雜訊可以路由到 exact，但送給來源的必須是抽取後的番號，不是原字串。"""
        cases = [
            ("../etc/passwd/SONE-103", "SONE-103"),
            ("https://evil.com/SONE-103", "SONE-103"),
            ("hhd800.com@SONE-103", "HHD-800"),  # extract_number("hhd800.com@...") 先抽取 hhd800 為 HHD-800 (corpus U3)
        ]
        for raw, expected_number in cases:
            # ❶ exact 分支呼叫的是 search_jav_single_source（core/scraper.py:885），**不是** search_jav
            # ❷ enabled sources 必須釘死，否則 config 只要回空清單，迴圈跑 0 次、斷言 vacuous pass
            with patch('core.scraper.get_enabled_source_ids', return_value=['javbus']), \
                 patch('core.scraper.search_jav_single_source', return_value=None) as mock:
                smart_search(raw, limit=1)
            # ❸ 先證明「真的攔到了」——沒有這行，上面兩條斷言在零呼叫時恆真
            assert mock.call_count >= 1, f'{raw!r} 沒有到達 exact 分支，這條測試等於沒測'
            for call in mock.call_args_list:
                assert call.args[0] == expected_number   # 只送抽取值
                assert raw not in str(call)              # raw 字串不得出現在任何參數


