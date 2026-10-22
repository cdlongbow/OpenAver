"""
T-c2 Tests — B2 標題疊加修復（FIX A + FIX B）
測試 core/organizer.py 的 _extracted_has_organize_junk()、_strip_num_prefixes()
以及 organize_file() / generate_nfo() 的標題決定流程。

邊界 case 1-22 對應 TASK-72c-T-c2.md。
"""
import os
import xml.etree.ElementTree as ET
from pathlib import Path


from core.organizer import (
    _extracted_has_organize_junk,
    _strip_num_prefixes,
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


# ===========================================================================
# Section B — _extracted_has_organize_junk 負向（回 False）
# Case 6-9
# ===========================================================================


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


    def test_case20_boundary_no_false_positive(self):
        """Case 20: ABC-123 不誤砍 ABC-1234 開頭的標題（後接數字 '4' → 不命中）"""
        s = "ABC-1234 某標題"
        result = _strip_num_prefixes(s, "ABC-123")
        assert result == "ABC-1234 某標題", f"不應改變：{result!r}"


class TestOrganizeFileFIXB:
    """organize_file() FIX B：標題決定段去前綴，檔名不含雙重番號"""


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


# ===========================================================================
# Section E — 退化邊界 case
# Case 23
# ===========================================================================

