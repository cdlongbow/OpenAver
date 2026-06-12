"""
T-c2 Tests — B2 標題疊加修復（FIX A + FIX B）
測試 core/organizer.py 的 _extracted_has_organize_junk()、_strip_num_prefixes()
以及 organize_file() / generate_nfo() 的標題決定流程。

邊界 case 1-22 對應 TASK-72c-T-c2.md。
"""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.organizer import (
    _extracted_has_organize_junk,
    _strip_num_prefixes,
    generate_nfo,
    organize_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, suffix_keywords=None, *, create_nfo: bool = False) -> dict:
    """Build a minimal test config dict."""
    if suffix_keywords is None:
        suffix_keywords = ["-cd1", "-cd2", "-4k", "-uc"]
    cfg = {
        "create_folder": False,
        "filename_format": "[{num}][{maker}] {title}{suffix}",
        "download_cover": False,
        "cover_filename": "poster.jpg",
        "create_nfo": create_nfo,
        "max_title_length": 50,
        "max_filename_length": 120,
        "suffix_keywords": suffix_keywords,
    }
    return cfg


def _make_metadata(number: str = "ABC-123", title: str = "原始標題", maker: str = "") -> dict:
    return {
        "number": number,
        "title": title,
        "actors": [],
        "tags": [],
        "maker": maker,
        "date": "2024-01-15",
        "cover": "",
        "url": "",
    }


def _run_organize(tmp_path: Path, filename: str, metadata: dict, config: dict) -> dict:
    """Create a dummy video file and call organize_file; return result."""
    src = tmp_path / filename
    src.write_bytes(b"dummy")
    return organize_file(str(src), metadata, config)


def _read_nfo_title(nfo_path: str) -> str:
    """Parse NFO and return the <title> text."""
    tree = ET.parse(nfo_path)
    root = tree.getroot()
    title_el = root.find("title")
    return title_el.text if title_el is not None else ""


# ===========================================================================
# Section A — _extracted_has_organize_junk 正向（回 True）
# Case 1-5
# ===========================================================================

class TestExtractedHasOrganizeJunkPositive:
    """_extracted_has_organize_junk → True（應丟棄 extracted）"""

    def test_case1_date_token(self):
        """Case 1: 日期 token 命中 → True"""
        extracted = "2023-05-01 中文標題"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, {}) is True

    def test_case1_date_dot_format(self):
        """Case 1 (variant): 日期用 '.' 格式 → True"""
        extracted = "2023.05.01 中文標題"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, {}) is True

    def test_case2_maker_residue(self):
        """Case 2: maker 殘留 → True"""
        metadata = {"maker": "廠商"}
        extracted = "廠商 中文標題"
        assert _extracted_has_organize_junk(extracted, "ABC-123", metadata, {}) is True

    def test_case3_suffix_token_4k(self):
        """Case 3: suffix token '-4k' 命中 → True"""
        config = {"suffix_keywords": ["-4k"]}
        extracted = "中文標題-4k"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is True

    def test_case4_suffix_token_uc(self):
        """Case 4: suffix token '-uc' 命中 → True"""
        config = {"suffix_keywords": ["-uc"]}
        extracted = "中文標題-uc"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is True

    def test_case5_maker_case_insensitive(self):
        """Case 5: maker 大小寫不敏感 → True"""
        metadata = {"maker": "MAKER"}
        extracted = "maker 中文標題"
        assert _extracted_has_organize_junk(extracted, "ABC-123", metadata, {}) is True

    def test_suffix_token_boundary_followed_by_separator(self):
        """suffix token 後跟 '-' 分隔符仍命中"""
        config = {"suffix_keywords": ["-4k"]}
        extracted = "中文標題-4k-extra"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is True

    def test_suffix_token_at_end(self):
        """suffix token 緊貼字串末尾 → True"""
        config = {"suffix_keywords": ["-4k"]}
        extracted = "中文標題-4k"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is True


# ===========================================================================
# Section B — _extracted_has_organize_junk 負向（回 False）
# Case 6-9
# ===========================================================================

class TestExtractedHasOrganizeJunkNegative:
    """_extracted_has_organize_junk → False（照用 extracted）"""

    def test_case6_clean_chinese_title(self):
        """Case 6: 乾淨中文標題，空 maker，無日期，無 suffix → False"""
        assert _extracted_has_organize_junk("中文標題", "ABC-123", {}, {}) is False

    def test_case7_empty_maker(self):
        """Case 7: maker 為空字串，不可命中 → False"""
        metadata = {"maker": ""}
        assert _extracted_has_organize_junk("中文標題", "ABC-123", metadata, {}) is False

    def test_case7_maker_none(self):
        """Case 7 variant: maker 為 None → False"""
        metadata = {"maker": None}
        assert _extracted_has_organize_junk("中文標題", "ABC-123", metadata, {}) is False

    def test_case8_standalone_4k_not_killed(self):
        """Case 8 (B-1): standalone '4K'（無前導 '-'）不命中帶 dash 的 '-4k' → False
        確認生下載檔 'ABC-123 中文標題 4K.mp4' 的提取結果不被誤殺。"""
        config = {"suffix_keywords": ["-4k"]}
        extracted = "中文標題 4K"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is False

    def test_case9_cleaned_number_prefixed_raw_download(self):
        """Case 9: 番號前置生下載檔經 extract_chinese_title 剝掉番號後的乾淨結果 → False"""
        # 模擬 'ABC-123 中文標題.mp4' 提取後已剝番號回 '中文標題'
        extracted = "中文標題"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, {}) is False

    def test_maker_missing_from_metadata(self):
        """metadata 完全沒有 maker 鍵 → False（不 KeyError）"""
        assert _extracted_has_organize_junk("中文標題", "ABC-123", {}, {}) is False

    def test_empty_suffix_keywords(self):
        """suffix_keywords 空列表 → False"""
        config = {"suffix_keywords": []}
        assert _extracted_has_organize_junk("中文標題-4k", "ABC-123", {}, config) is False

    def test_standalone_uc_not_killed(self):
        """'uc' 裸詞（無前導 '-'）不命中 '-uc' → False"""
        config = {"suffix_keywords": ["-uc"]}
        extracted = "中文標題 uc 版"
        assert _extracted_has_organize_junk(extracted, "ABC-123", {}, config) is False


# ===========================================================================
# Section C — 決定性 case（organize_file 標題決定流程）
# Case 10-12
# ===========================================================================

class TestOrganizeFileTitleDecision:
    """organize_file() FIX A 標題決定流程決定性 case"""

    def test_case10_decisive_raw_download_survives(self, tmp_path):
        """Case 10: 決定性 (1) — ABC-123 中文標題.mp4（番號前置，無 junk）
        → extracted_title 搶救存活，title_source == 'extracted'"""
        config = _make_config(tmp_path)
        metadata = _make_metadata(number="ABC-123", title="原始日文標題", maker="")
        result = _run_organize(tmp_path, "ABC-123 中文標題.mp4", metadata, config)

        assert result["success"] is True, f"organize 失敗: {result.get('error')}"
        assert result.get("title_source") == "extracted", (
            f"預期 'extracted'，實際 {result.get('title_source')!r}"
        )
        # 新檔名必須含中文標題
        new_name = Path(result["new_filename"]).name
        assert "中文標題" in new_name, f"中文標題未出現在檔名: {new_name}"

    def test_case11_standalone_4k_raw_download_survives(self, tmp_path):
        """Case 11: 決定性 (1b) (B-1) — ABC-123 中文標題 4K.mp4（含 standalone 4K，非 '-4k' suffix）
        → junk-validation 不命中，title_source == 'extracted'，搶救存活"""
        config = _make_config(tmp_path, suffix_keywords=["-4k", "-uc"])
        metadata = _make_metadata(number="ABC-123", title="原始日文標題", maker="")
        result = _run_organize(tmp_path, "ABC-123 中文標題 4K.mp4", metadata, config)

        assert result["success"] is True, f"organize 失敗: {result.get('error')}"
        assert result.get("title_source") == "extracted", (
            f"預期 'extracted'（4K standalone 不應被誤殺），實際 {result.get('title_source')!r}"
        )
        new_name = Path(result["new_filename"]).name
        assert "中文標題" in new_name, f"中文標題未出現在檔名: {new_name}"

    def test_case12_de_stack_spec_shape(self, tmp_path):
        """Case 12: 決定性 (2) — spec 回報形狀：日期-廠商-番號-中文標題-4k.mp4
        → junk 命中（日期或 maker 或 suffix）→ extracted_title=None
        → title_source 非 'extracted'，輸出 title 不疊加"""
        config = _make_config(tmp_path, suffix_keywords=["-4k"])
        # maker 設定為「廠商」，同時存在於提取結果
        metadata = _make_metadata(number="ABC-123", title="原始日文標題", maker="廠商")
        result = _run_organize(
            tmp_path,
            "2023-05-01-廠商-ABC-123-中文標題-4k.mp4",
            metadata,
            config,
        )

        assert result["success"] is True, f"organize 失敗: {result.get('error')}"
        assert result.get("title_source") != "extracted", (
            f"預期非 'extracted'（junk 應命中），實際 {result.get('title_source')!r}"
        )
        # 輸出 title 不應含 organize artifact（日期）
        new_name = Path(result["new_filename"]).name
        assert "2023-05-01" not in new_name, f"日期 artifact 仍殘留在檔名: {new_name}"


# ===========================================================================
# Section D — FIX B 邊界（_strip_num_prefixes + organize_file 組裝層）
# Case 13-22
# ===========================================================================

class TestStripNumPrefixes:
    """_strip_num_prefixes() 純函式 unit tests"""

    def test_case19_fc2_ppv_special_number(self):
        """Case 19: FC2-PPV-123 特殊番號，re.escape 正確處理 '-' → 剝除成功"""
        s = "[FC2-PPV-123]Title"
        result = _strip_num_prefixes(s, "FC2-PPV-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"

    def test_case20_boundary_no_false_positive(self):
        """Case 20: ABC-123 不誤砍 ABC-1234 開頭的標題（後接數字 '4' → 不命中）"""
        s = "ABC-1234 某標題"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "ABC-1234 某標題", f"不應改變：{result!r}"

    def test_case21_no_over_strip_clean_title(self):
        """Case 21: 標題本體不以番號開頭 → 迴圈立即停，標題完整保留"""
        s = "中文標題"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "中文標題", f"不應改變：{result!r}"

    def test_bracket_prefix_stripped(self):
        """bracket 形式 [ABC-123] 前綴被剝除"""
        s = "[ABC-123]Title"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"

    def test_bare_prefix_stripped(self):
        """裸 number 前綴（後跟空格）被剝除"""
        s = "ABC-123 Title"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"

    def test_double_stack_stripped_to_fixpoint(self):
        """[ABC-123][ABC-123]Title → 迴圈剝盡 → 'Title'"""
        s = "[ABC-123][ABC-123]Title"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"

    def test_triple_stack_stripped_to_fixpoint(self):
        """[ABC-123][ABC-123][ABC-123]Title → 迴圈剝盡 → 'Title'"""
        s = "[ABC-123][ABC-123][ABC-123]Title"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"

    def test_no_prefix_empty_string(self):
        """空字串 → 空字串（不 crash）"""
        assert _strip_num_prefixes("", "ABC-123") == ""

    def test_case_insensitive(self):
        """大小寫不敏感：abc-123 前綴應被剝除（number=ABC-123）"""
        s = "abc-123 Title"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "Title", f"預期 'Title'，實際 {result!r}"


class TestOrganizeFileFIXB:
    """organize_file() FIX B：標題決定段去前綴，檔名不含雙重番號"""

    def test_case13_metadata_title_with_prefix_no_bleed(self, tmp_path):
        """Case 13: metadata['title']='[IPTD-434]Rioの毎日カーニバル'
        → format_data['title']（即檔名 title slot）不含 '[IPTD-434]'
        → new_filename 不出現雙重 'IPTD-434'"""
        config = _make_config(tmp_path)
        metadata = {
            "number": "IPTD-434",
            "title": "[IPTD-434]Rioの毎日カーニバル",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2010-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "IPTD-434.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True, f"organize 失敗: {result.get('error')}"
        new_name = Path(result["new_filename"]).name

        # '[IPTD-434]' 在 title slot 中不應出現（FIX B 應剝除）
        # 期望：檔名只有一個 IPTD-434 段（來自 {num} slot）
        count = new_name.lower().count("iptd-434")
        assert count == 1, (
            f"new_filename 中 'IPTD-434' 出現 {count} 次（應為 1）: {new_name}"
        )

    def test_case14_double_stack_full_pipeline(self, tmp_path):
        """Case 14: metadata['title']='[ABC-123][ABC-123]Title'
        → format_data['title'] 本體 = 'Title'（無 [ABC-123] 前綴）
        → new_filename 含單一 [ABC-123] 段（來自 {num} slot）
        → NFO <title> == '[ABC-123]Title'（單一前綴，非裸 Title，非雙前綴）"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "ABC-123",
            "title": "[ABC-123][ABC-123]Title",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "ABC-123.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True, f"organize 失敗: {result.get('error')}"
        new_name = Path(result["new_filename"]).name

        # 檔名中 ABC-123 只出現一次
        count = new_name.lower().count("abc-123")
        assert count == 1, (
            f"new_filename 中 'ABC-123' 出現 {count} 次（應為 1）: {new_name}"
        )

        # NFO <title> 應 == '[ABC-123]Title'
        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[ABC-123]Title", (
            f"NFO <title> 預期 '[ABC-123]Title'，實際 {nfo_title!r}"
        )

    def test_case15_triple_stack_full_pipeline(self, tmp_path):
        """Case 15: metadata['title']='[ABC-123][ABC-123][ABC-123]Title'
        → 迴圈剝盡至本體 'Title'
        → NFO <title> == '[ABC-123]Title'（單一前綴）"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "ABC-123",
            "title": "[ABC-123][ABC-123][ABC-123]Title",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "ABC-123-triple.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True
        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[ABC-123]Title", (
            f"NFO <title> 預期 '[ABC-123]Title'，實際 {nfo_title!r}"
        )

        new_name = Path(result["new_filename"]).name
        count = new_name.lower().count("abc-123")
        assert count == 1, f"new_filename 中 'ABC-123' 出現 {count} 次: {new_name}"


class TestOrganizeFileDisplayTitle:
    """organize_file() → generate_nfo() display_title belt-and-suspenders"""

    def test_case16_display_title_single_prefix_from_prefixed_title(self, tmp_path):
        """Case 16: title 勝出後含 [ABC-123]，belt L545 去前綴後 display_title = '[ABC-123]body'（單一）"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "ABC-123",
            "title": "[ABC-123]純標題",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "ABC-123.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True
        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[ABC-123]純標題", (
            f"NFO <title> 預期 '[ABC-123]純標題'，實際 {nfo_title!r}"
        )

    def test_case17_display_title_no_prefix_is_noop(self, tmp_path):
        """Case 17: title = '純標題'（不帶前綴），belt 無命中 → display_title = '[ABC-123]純標題'（正常）"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "ABC-123",
            "title": "純標題",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "ABC-123-noop.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True
        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[ABC-123]純標題", (
            f"NFO <title> 預期 '[ABC-123]純標題'，實際 {nfo_title!r}"
        )

    def test_case22_enrich_no_regression_generate_nfo_direct(self, tmp_path):
        """Case 22: generate_nfo 直接呼叫，title 無前綴 → belt 為 no-op → display_title byte-identical
        (CD-c9: B2 不擴及 enrich，無前綴 title 不改語義)"""
        nfo_path = str(tmp_path / "ABC-123.nfo")
        generate_nfo(
            number="ABC-123",
            title="純標題",
            original_title="オリジナルタイトル",
            output_path=nfo_path,
        )
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[ABC-123]純標題", (
            f"enrich 路徑 NFO <title> 預期 '[ABC-123]純標題'，實際 {nfo_title!r}"
        )


class TestOrganizeFileTitleFallback:
    """Case 18: title 空 → fallback original_title 也去前綴"""

    def test_case18_empty_title_fallback_original_title_stripped(self, tmp_path):
        """Case 18: metadata title 空，original_title 帶前綴 → display_title 單一前綴"""
        config = _make_config(tmp_path, create_nfo=True)
        # title 設為空，但 generate_nfo 的 original_title 帶前綴
        # 我們直接用 generate_nfo 模擬 enrich 路徑帶前綴的 original_title
        nfo_path = str(tmp_path / "ABC-123-fallback.nfo")
        generate_nfo(
            number="ABC-123",
            title="",                           # title 空
            original_title="[ABC-123]日文原標題",  # original_title 帶前綴
            output_path=nfo_path,
        )
        nfo_title = _read_nfo_title(nfo_path)
        # belt: _t = title or original_title = "[ABC-123]日文原標題"
        # _strip_num_prefixes → "日文原標題"
        # display_title = "[ABC-123]日文原標題"（單一前綴）
        assert nfo_title == "[ABC-123]日文原標題", (
            f"NFO <title> 預期 '[ABC-123]日文原標題'（title 空時用 original_title 剝前綴），實際 {nfo_title!r}"
        )

    def test_fc2_ppv_organize_file(self, tmp_path):
        """Case 19 variant: FC2-PPV-123 番號透過 organize_file → 前綴正確剝除，不誤剝"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "FC2-PPV-123",
            "title": "[FC2-PPV-123]FC2 標題",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "FC2-PPV-123.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        assert result["success"] is True
        new_name = Path(result["new_filename"]).name
        # FC2-PPV-123 在檔名中只應出現一次（來自 {num} slot）
        count = new_name.lower().count("fc2-ppv-123")
        assert count == 1, f"new_filename 中 'FC2-PPV-123' 出現 {count} 次: {new_name}"

        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title == "[FC2-PPV-123]FC2 標題", (
            f"NFO <title> 預期 '[FC2-PPV-123]FC2 標題'，實際 {nfo_title!r}"
        )


# ===========================================================================
# Section E — 退化邊界 case
# Case 23
# ===========================================================================

class TestOrganizeFileDegenerateEdge:
    """退化邊界 case：title 本身即番號前綴，無本體"""

    def test_case23_title_is_bare_prefix_only(self, tmp_path):
        """Case 23: metadata['title'] == '[ABC-123]'（title 本身即裸前綴，無本體）
        → _strip_num_prefixes('[ABC-123]', 'ABC-123') 回傳 ''
        → organize_file 不 crash
        → new_filename 中 'abc-123' 只出現一次（來自 {num} slot，title slot 為空）
        → NFO <title> 不雙疊前綴"""
        config = _make_config(tmp_path, create_nfo=True)
        metadata = {
            "number": "ABC-123",
            "title": "[ABC-123]",
            "actors": [],
            "tags": [],
            "maker": "",
            "date": "2024-01-01",
            "cover": "",
            "url": "",
        }
        src = tmp_path / "ABC-123-bare.mp4"
        src.write_bytes(b"dummy")
        result = organize_file(str(src), metadata, config)

        # (a) must not crash
        assert result["success"] is True, f"organize 失敗: {result.get('error')}"

        # (b) new_filename contains [ABC-123] exactly once
        new_name = Path(result["new_filename"]).name
        count = new_name.lower().count("[abc-123]")
        assert count == 1, (
            f"new_filename 中 '[ABC-123]' 出現 {count} 次（應為 1）: {new_name}"
        )

        # (c) NFO <title> does not double the prefix
        nfo_path = result.get("nfo_path")
        assert nfo_path and os.path.exists(nfo_path), "NFO 未生成"
        nfo_title = _read_nfo_title(nfo_path)
        assert nfo_title.lower().count("[abc-123]") == 1, (
            f"NFO <title> 中 '[ABC-123]' 出現不只一次: {nfo_title!r}"
        )
