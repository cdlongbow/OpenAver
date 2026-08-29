"""
test_enricher.py - core/enricher.py TDD-lite 單元測試（full mock）

涵蓋 TASK-T4.md 的 25 個邊界條件
"""

import io
import os
import pytest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import patch, MagicMock, call

from core.path_utils import to_file_uri
from tests.conftest import MOCK_FOCAL_XY


# ── helpers ──────────────────────────────────────────────────────────────────

_MISSING = object()


def _make_video(
    number="SONE-205",
    title="テストタイトル",
    original_title="テストタイトル",
    actresses=_MISSING,
    maker="SOD",
    director="テスト監督",
    series="テストシリーズ",
    label="LABEL",
    tags=_MISSING,
    sample_images=_MISSING,
    duration=120,
    cover_path="https://example.com/cover.jpg",
    release_date="2024-01-01",
    path="",
):
    from core.database import Video
    return Video(
        number=number,
        title=title,
        original_title=original_title,
        actresses=["女優A"] if actresses is _MISSING else actresses,
        maker=maker,
        director=director,
        series=series,
        label=label,
        tags=["タグ"] if tags is _MISSING else tags,
        sample_images=["https://example.com/s1.jpg", "https://example.com/s2.jpg"] if sample_images is _MISSING else sample_images,
        duration=duration,
        cover_path=cover_path,
        release_date=release_date,
        path=path,
    )


def _make_scraper_result(
    number="SONE-205",
    title="テストタイトル",
    actors=None,
    cover="https://example.com/cover.jpg",
    date="2024-01-01",
    maker="SOD",
    director="テスト監督",
    series="テストシリーズ",
    label="LABEL",
    tags=None,
    sample_images=None,
    duration=120,
    url="https://www.javbus.com/SONE-205",
):
    return {
        "number": number,
        "title": title,
        "actors": actors or ["女優A"],
        "cover": cover,
        "date": date,
        "maker": maker,
        "director": director,
        "series": series,
        "label": label,
        "tags": tags or ["タグ"],
        "sample_images": sample_images or ["https://example.com/s1.jpg", "https://example.com/s2.jpg"],
        "duration": duration,
        "url": url,
    }


FS_PATH = "/video/SONE-205.mp4"
NFO_PATH = "/video/SONE-205.nfo"
COVER_PATH = "/video/SONE-205.jpg"


# ── 1. file_path 不存在 ───────────────────────────────────────────────────────

class TestFileNotFound:
    def test_file_not_found_returns_error(self):
        """邊界條件 1: file_path 指向不存在的檔案"""
        with patch("os.path.exists", return_value=False):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path="/nonexistent/SONE-205.mp4",
                number="SONE-205",
            )
        assert result.success is False
        assert "不存在" in result.error


# ── 2. number 為空 ────────────────────────────────────────────────────────────

class TestEmptyNumber:
    def test_empty_number_returns_error(self):
        """邊界條件 2: number 為空字串"""
        with patch("os.path.exists", return_value=True):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="",
            )
        assert result.success is False
        assert "番號" in result.error


# ── 3. mode 不合法 ────────────────────────────────────────────────────────────

class TestInvalidMode:
    def test_invalid_mode_returns_error(self):
        """邊界條件 3: mode 不在合法值列表"""
        with patch("os.path.exists", return_value=True):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="invalid_mode",
            )
        assert result.success is False
        assert "mode" in result.error.lower() or "不支援" in result.error


# ── 4. fill_missing: DB 完整，不打 scraper ────────────────────────────────────

class TestFillMissingDbComplete:
    def test_db_complete_no_scraper(self):
        """邊界條件 4: DB 有完整資料 → 不打 scraper"""
        video = _make_video()
        db_result = {"SONE-205": [video]}

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "db"


# ── 4b. fill_missing: DB 有完整欄位但缺 label → 觸發 scraper ─────────────────

class TestFillMissingLabelMissing:
    def test_db_missing_label_calls_scraper(self):
        """邊界條件 4b: DB 有 title/actresses/maker/director/release_date 但缺 label → 觸發 scraper"""
        video = _make_video(label="")
        db_result = {"SONE-205": [video]}
        scraper_data = _make_scraper_result()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_called_once()
        assert result.success is True
        assert "label" in result.fields_filled


# ── 5. fill_missing: DB 有資料但缺欄位，打 scraper 補 ────────────────────────

class TestFillMissingDbMissingFields:
    def test_db_missing_fields_calls_scraper(self):
        """邊界條件 5: DB 有資料但缺 director/series → 打 scraper"""
        video = _make_video(director="", series=None)
        db_result = {"SONE-205": [video]}
        scraper_data = _make_scraper_result()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_called_once()
        assert result.success is True
        assert "director" in result.fields_filled or "series" in result.fields_filled


# ── 6. fill_missing: DB miss + NFO 存在 ──────────────────────────────────────

class TestFillMissingDbMissNfoExists:
    def test_db_miss_nfo_exists_reads_nfo(self):
        """邊界條件 6: DB miss + NFO 存在 → 讀 NFO，缺少的才打 scraper"""
        import xml.etree.ElementTree as ET

        nfo_root = ET.Element("movie")
        ET.SubElement(nfo_root, "title").text = "テストタイトル"
        ET.SubElement(nfo_root, "studio").text = "SOD"
        # 缺 director

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=_make_scraper_result()) as mock_search,
            patch("core.enricher.parse_nfo", return_value=(MagicMock(), nfo_root)),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_called_once()
        assert result.success is True


# ── 7. fill_missing: DB miss + NFO 不存在 ────────────────────────────────────

class TestFillMissingDbMissNfoMiss:
    def test_db_miss_nfo_miss_calls_scraper(self):
        """邊界條件 7: DB miss + NFO 不存在 → 打 scraper"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=_make_scraper_result()) as mock_search,
            patch("core.enricher.parse_nfo", return_value=(None, None)),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_called_once()
        assert result.success is True


# ── 8. fill_missing: scraper 找不到 ──────────────────────────────────────────

class TestFillMissingScraperNotFound:
    def test_scraper_not_found_returns_error(self):
        """邊界條件 8: search_jav 回傳 None → error"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.parse_nfo", return_value=(None, None)),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        assert result.success is False
        assert "SONE-205" in result.error or "找不到" in result.error
        # 89b-T2: not-found branch marks scrape_attempted_at (same as refresh_full).
        mock_repo.update_scrape_attempted_at.assert_called_once()
        call_args = mock_repo.update_scrape_attempted_at.call_args[0]
        assert call_args[0] == to_file_uri(FS_PATH)
        assert call_args[1] > 0
        # not-found path must not create/upsert any new row (only mark attempted).
        mock_repo.upsert.assert_not_called()


# ── 9. db_to_sidecar: DB 完整，不打 scraper ──────────────────────────────────

class TestDbToSidecarComplete:
    def test_db_complete_no_scraper(self):
        """邊界條件 9: db_to_sidecar + DB 完整 → 不打 scraper，寫 NFO/封面"""
        video = _make_video()
        db_result = {"SONE-205": [video]}

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="db_to_sidecar",
            )

        mock_search.assert_not_called()
        assert result.success is True


# ── 10. db_to_sidecar: DB miss → error ───────────────────────────────────────

class TestDbToSidecarDbMiss:
    def test_db_miss_returns_error(self):
        """邊界條件 10: db_to_sidecar + DB miss → error"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="db_to_sidecar",
            )

        assert result.success is False
        assert "SONE-205" in result.error or "DB" in result.error


# ── 11. db_to_sidecar: 封面 URL 缺失 → cover_written=False ───────────────────

class TestDbToSidecarNoCoverUrl:
    def test_no_cover_url_cover_not_written(self):
        """邊界條件 11: DB 有資料但 cover_path 為空 → cover_written=False"""
        video = _make_video(cover_path="")
        db_result = {"SONE-205": [video]}

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image") as mock_dl,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="db_to_sidecar",
                write_cover=True,
            )

        assert result.cover_written is False
        mock_dl.assert_not_called()


# ── 12. refresh_full: 強制打 scraper ─────────────────────────────────────────

class TestRefreshFullAlwaysScrape:
    def test_always_calls_scraper(self):
        """邊界條件 12: refresh_full → 強制打 scraper，忽略 DB/NFO"""
        video = _make_video()
        db_result = {"SONE-205": [video]}
        scraper_data = _make_scraper_result()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
            )

        mock_search.assert_called_once()
        assert result.success is True


# ── 13. refresh_full: scraper 失敗 ───────────────────────────────────────────

class TestRefreshFullScraperFail:
    def test_scraper_fail_returns_error(self):
        """邊界條件 13: refresh_full + scraper 失敗 → error"""
        with (
            patch("os.path.exists", return_value=True),
            # 89b-T2: must mock VideoRepository — refresh_full not-found now calls
            # repo.update_scrape_attempted_at(); without this mock it would hit the
            # real project output/openaver.db (see TASK-89b-T2 現況分析 §3).
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
            )

        assert result.success is False
        assert "SONE-205" in result.error or "找不到" in result.error
        # 89b-T2: not-found branch marks scrape_attempted_at via to_file_uri(fs_path) inline
        # (NOT the later-assigned `path_uri` var — that would NameError before this branch).
        mock_repo.update_scrape_attempted_at.assert_called_once()
        call_args = mock_repo.update_scrape_attempted_at.call_args[0]
        assert call_args[0] == to_file_uri(FS_PATH)
        assert call_args[1] > 0
        # not-found path must not create/upsert any new row (only mark attempted).
        mock_repo.upsert.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TASK-135-T4：NFO-only 欄位保留（plot/rating/url）＋ rating ÷2
# ══════════════════════════════════════════════════════════════════════════════
#
# CD-135-5：只讀三個 tag（plot/rating/website），rating 讀回時除以 2
# （寫入端 core/organizer.py 的 × 2 相消）。
# CD-135-13：判準問 scraper_data 的 key presence（映射前），不是 meta 的 truthiness
# （映射後）——`_summary: ""` 是「AI 審過了、就是要空」的合法指令，不得被 fallback
# 用既有 NFO 的舊值蓋掉。

_T4_NFO_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <plot>{plot}</plot>
  <rating>{rating}</rating>
  <website>{website}</website>
</movie>
"""


def _t4_write_nfo(nfo_path, plot="既有劇情", rating="7.0", website="http://existing.example/"):
    nfo_path.write_text(
        _T4_NFO_TEMPLATE.format(plot=plot, rating=rating, website=website),
        encoding="utf-8",
    )


class TestPreserveNfoOnlyFields:
    """DoD-1／DoD-2／DoD-4／DoD-5 ＋ 早退設計決策：直接對 `_preserve_nfo_only_fields()`
    單元測試（不透過完整 `enrich_single()`）。"""

    # ── DoD-1: key 不存在 → 讀既有 NFO（三欄各一案例，六案例矩陣的前三個）───

    def test_summary_key_missing_falls_back_to_nfo_plot(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", plot="既有劇情")
        # 刻意不帶 _summary key
        scraper_data = {"_rating": 3.5, "url": "http://ai.example/"}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["summary"] == "既有劇情"

    def test_rating_key_missing_falls_back_to_nfo_rating_divided_by_two(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", rating="7.0")
        # 刻意不帶 _rating key
        scraper_data = {"_summary": "AI 審過的劇情", "url": "http://ai.example/"}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["rating"] == 3.5

    def test_url_key_missing_falls_back_to_nfo_website(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", website="http://existing.example/")
        # 刻意不帶 url key
        scraper_data = {"_summary": "AI 審過的劇情", "_rating": 3.5}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["url"] == "http://existing.example/"

    # ── DoD-2: key 存在但值為空 → 不讀 NFO（CD-135-13，三欄各一案例，
    #    與 DoD-1 合計六個獨立案例，不能只寫三個） ─────────────────────────

    def test_summary_key_empty_string_not_overwritten(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", plot="既有劇情")
        # _summary key 存在，值為空字串 —— AI 明確要求清空，不是沒帶。
        # 刻意只帶這一個 key（_rating/url 都不帶）：三個 key 全在時
        # `_preserve_nfo_only_fields` 會在函式最前面早退，不會走到這裡要驗的
        # `if "_summary" not in scraper_data:` 那一行，等於測不到 M2 mutation。
        scraper_data = {"_summary": ""}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["summary"] == ""

    def test_rating_key_none_not_overwritten(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", rating="7.0")
        # _rating key 存在，值為 None —— AI 明確送 None，不是沒帶。
        # 同上，刻意只帶這一個 key，避免三個 key 全在觸發早退。
        scraper_data = {"_rating": None}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["rating"] is None

    def test_url_key_empty_string_not_overwritten(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", website="http://existing.example/")
        # url key 存在，值為空字串 —— AI 明確要求清空，不是沒帶。
        # 同上，刻意只帶這一個 key，避免三個 key 全在觸發早退。
        scraper_data = {"url": ""}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["url"] == ""

    # ── DoD-4: 既有 NFO 不存在 → 不炸 ──────────────────────────────────────

    def test_nfo_missing_leaves_meta_untouched_no_crash(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")  # 對應 .nfo 不存在
        scraper_data = {}  # 三個 key 全缺
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["summary"] == ""
        assert meta["rating"] is None
        assert meta["url"] == ""

    # ── DoD-5: <rating> 內容不是數字（第三方 NFO 手改壞掉）→ 不炸、留空 ────

    def test_rating_non_numeric_in_nfo_left_blank_no_crash(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo", rating="N/A")
        # 刻意不帶 _rating key，其餘兩欄都帶，隔離只驗 rating 這一格
        scraper_data = {"_summary": "x", "url": "y"}
        meta = _scraper_to_meta(scraper_data)

        _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        assert meta["rating"] is None

    # ── 設計決策：三欄全在 scraper_data → 早退，不開檔（效能，非語意合併）──

    def test_all_three_keys_present_short_circuits_without_parsing_nfo(self, tmp_path):
        from core.enricher import _preserve_nfo_only_fields, _scraper_to_meta
        fs_path = str(tmp_path / "SONE-205.mp4")
        _t4_write_nfo(tmp_path / "SONE-205.nfo")  # 存在也不該被打開
        scraper_data = {"_summary": "x", "_rating": 3.5, "url": "y"}
        meta = _scraper_to_meta(scraper_data)

        with patch("core.enricher.parse_nfo") as mock_parse:
            _preserve_nfo_only_fields(meta, scraper_data, fs_path)

        mock_parse.assert_not_called()


class TestEnrichSingleRefreshFullRatingRoundtrip:
    """DoD-3：對同一個檔案連續跑兩次 `refresh_full`（都不帶 `_rating`）→ 寫出的 NFO
    `<rating>` 兩次都是 `7.0`，不是 `14.0`（NFO 寫入端 × 2、T4 讀回端 ÷ 2 相消）。

    BE-TEST-11：兩次呼叫都必須帶 `overwrite_existing=True`——否則 `_write_nfo()` 在
    NFO 已存在時直接 `return False` 不寫檔，兩次呼叫都是 no-op，翻倍與否測不出來
    （假綠）。
    """

    def _run_refresh_full(self, tmp_path):
        video_path = tmp_path / "SONE-205.mp4"
        if not video_path.exists():
            video_path.write_bytes(b"fake video bytes")
        # 刻意不帶 _rating —— round-trip 只驗這一格；_summary/url 都帶，避免
        # 那兩欄的 fallback 干擾本測試只想驗證的 rating 行為。
        scraper_data = {
            "title": "T",
            "_summary": "AI 審過的新劇情",
            "url": "http://ai.example/",
        }

        mock_repo = MagicMock()
        mock_repo.get_by_path.return_value = None
        mock_repo.get_by_numbers.return_value = {}
        # db_path 設 :memory: —— 避免 _sync_nfo_mtime 對 MagicMock 做
        # sqlite3.connect() 在 repo root 產生 "<MagicMock ...>" 垃圾檔（見
        # TestKodiStemNaming._make_mock_repo_for 同款防護）。:memory: 下該 UPDATE
        # 因無 videos 表靜默失敗（已被 try/except 包裹），不留任何檔案。
        mock_repo.db_path = ":memory:"

        with (
            patch("core.enricher.VideoRepository", return_value=mock_repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.download_image", return_value=True),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_path),
                number="SONE-205",
                mode="refresh_full",
                write_nfo=True,
                write_cover=False,
                write_extrafanart=False,
                overwrite_existing=True,
                scraper_data=dict(scraper_data),
            )
        assert result.success is True, f"enrich_single 應成功，error={result.error}"
        assert result.nfo_written is True, "NFO 應真的被寫出（否則翻倍與否測不出來）"

    def test_rating_stable_across_two_refresh_full_runs(self, tmp_path):
        import xml.etree.ElementTree as ET

        nfo_path = tmp_path / "SONE-205.nfo"
        nfo_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<movie>\n"
            "  <rating>7.0</rating>\n"
            "</movie>\n",
            encoding="utf-8",
        )

        self._run_refresh_full(tmp_path)
        first_rating = ET.parse(str(nfo_path)).getroot().find("rating").text
        assert first_rating == "7.0", f"第一次跑完應仍是 7.0，實際：{first_rating}"

        self._run_refresh_full(tmp_path)
        second_rating = ET.parse(str(nfo_path)).getroot().find("rating").text
        assert second_rating == "7.0", (
            f"第二次跑完不應翻倍成 14.0，實際：{second_rating}"
        )


# ── 14. write_nfo=False ───────────────────────────────────────────────────────

class TestWriteNfoFalse:
    def test_write_nfo_false_skips_nfo(self):
        """邊界條件 14: write_nfo=False → 不呼叫 generate_nfo"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo") as mock_nfo,
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=False,
            )

        mock_nfo.assert_not_called()
        assert result.nfo_written is False


# ── 15. write_cover=False ─────────────────────────────────────────────────────

class TestWriteCoverFalse:
    def test_write_cover_false_skips_download(self):
        """邊界條件 15: write_cover=False → 不呼叫 download_image"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image") as mock_dl,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_cover=False,
            )

        mock_dl.assert_not_called()
        assert result.cover_written is False


# ── 16. write_extrafanart=False（預設）────────────────────────────────────────

class TestWriteExtrafanartFalse:
    def test_write_extrafanart_false_by_default(self):
        """邊界條件 16: write_extrafanart=False（預設）→ extrafanart_written=0"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_extrafanart=False,
            )

        assert result.extrafanart_written == 0


# ── 17. NFO 已存在 + overwrite_existing=False ─────────────────────────────────

class TestNfoExistsNoOverwrite:
    def test_nfo_exists_no_overwrite_skips(self):
        """邊界條件 17: NFO 已存在 + overwrite_existing=False → nfo_written=False"""
        video = _make_video()

        def exists_side_effect(path):
            if str(path).endswith(".nfo"):
                return True
            return True  # video file exists

        with (
            patch("os.path.exists", side_effect=exists_side_effect),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo") as mock_nfo,
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=False,
            )

        mock_nfo.assert_not_called()
        assert result.nfo_written is False


# ── 18. NFO 已存在 + overwrite_existing=True ─────────────────────────────────

class TestNfoExistsOverwrite:
    def test_nfo_exists_overwrite_writes(self):
        """邊界條件 18: NFO 已存在 + overwrite_existing=True → 覆寫，nfo_written=True"""
        video = _make_video()

        def exists_side_effect(path):
            return True  # both video and nfo exist

        with (
            patch("os.path.exists", side_effect=exists_side_effect),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True) as mock_nfo,
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=True,
            )

        mock_nfo.assert_called_once()
        assert result.nfo_written is True


# ── 19. 封面已存在 + overwrite_existing=False ────────────────────────────────

class TestCoverExistsNoOverwrite:
    def test_cover_exists_no_overwrite_skips(self):
        """邊界條件 19: 封面已存在 + overwrite_existing=False → cover_written=False"""
        video = _make_video()

        def exists_side_effect(path):
            return True  # both video and cover exist

        with (
            patch("os.path.exists", side_effect=exists_side_effect),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image") as mock_dl,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_cover=True,
                overwrite_existing=False,
            )

        mock_dl.assert_not_called()
        assert result.cover_written is False


# ── 20. write_extrafanart=True + sample_images 存在 ──────────────────────────

class TestExtrafanartDownloaded:
    def test_extrafanart_downloaded(self):
        """邊界條件 20: write_extrafanart=True + sample_images → 下載 extrafanart"""
        video = _make_video(sample_images=["https://example.com/s1.jpg", "https://example.com/s2.jpg"])
        db_result = {"SONE-205": [video]}

        # TASK-127c-T1 / CD-127c-1：_write_extrafanart 現在會跳過**磁碟上已存在**的
        # fanart{N}.jpg。blanket os.path.exists=True 等於宣告「劇照早就齊全」，那條路的
        # 正解是 extrafanart_written=0（另有測試釘住）。本測試要驗的是「缺的會被下載」，
        # 所以只讓 extrafanart/ 底下的目的檔回 False，其餘維持既有的 blanket True。
        def _exists_except_extrafanart(path):
            return "/extrafanart/" not in str(path)

        with (
            patch("os.path.exists", side_effect=_exists_except_extrafanart),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("os.makedirs"),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_extrafanart=True,
                overwrite_existing=True,
            )

        assert result.extrafanart_written == 2


# ── 21. write_extrafanart=True + 無 sample_images ────────────────────────────

class TestExtrafanartNoSamples:
    def test_extrafanart_no_samples(self):
        """邊界條件 21: write_extrafanart=True + 無 sample_images → extrafanart_written=0"""
        video = _make_video(sample_images=[])

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_extrafanart=True,
            )

        assert result.extrafanart_written == 0


# ── 22. NFO 路徑確實在影片同目錄 ─────────────────────────────────────────────

class TestNfoPathInSameDir:
    def test_nfo_path_in_same_dir_as_video(self):
        """邊界條件 22: generate_nfo output_path 必須在影片 parent 目錄"""
        video = _make_video()

        captured_calls = []

        def fake_generate_nfo(**kwargs):
            captured_calls.append(kwargs.get("output_path", ""))
            return True

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=fake_generate_nfo),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=True,
            )

        assert captured_calls, "generate_nfo should have been called"
        output_path = Path(captured_calls[0])
        video_dir = Path(FS_PATH).parent
        assert output_path.parent == video_dir, (
            f"NFO path {output_path} is outside video dir {video_dir}"
        )


# ── 23. organize_file / shutil.move / os.makedirs 不被呼叫 ───────────────────

class TestNoForbiddenCalls:
    def test_organize_file_not_called(self):
        """邊界條件 23: organize_file、shutil.move 不被呼叫"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("shutil.move") as mock_move,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
            )

        mock_move.assert_not_called()
        assert result.success is True

    def test_makedirs_not_called_when_extrafanart_false(self):
        """邊界條件 23b: write_extrafanart=False 正常路徑 → os.makedirs 不被呼叫"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("os.makedirs") as mock_makedirs,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_extrafanart=False,
            )

        mock_makedirs.assert_not_called()
        assert result.success is True


# ── 24. generate_nfo PermissionError ─────────────────────────────────────────

class TestNfoPermissionError:
    def test_nfo_permission_error(self):
        """邊界條件 24: generate_nfo 拋 PermissionError → success=False，提示權限"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=PermissionError("Permission denied")),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=True,
            )

        assert result.success is False
        assert "權限" in result.error or "寫入" in result.error


# ── 25. download_image 失敗 → cover_written=False，不影響 NFO ─────────────────

class TestImageDownloadFail:
    def test_image_download_fail_nfo_still_written(self):
        """邊界條件 25: download_image 失敗 → cover_written=False，nfo_written=True"""
        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=False),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                write_cover=True,
                overwrite_existing=True,
            )

        assert result.cover_written is False
        assert result.nfo_written is True
        assert result.success is True


# ── 26. F1: _db_upsert 把 path 存成 file:/// URI ────────────────────────────────

class TestDbUpsertPathIsFileUri:
    """F1: _db_upsert path 必須為 file:/// URI"""

    def test_fs_path_converted_to_file_uri(self):
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)
        mock_repo.get_by_numbers.return_value = {}

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert captured[0].path.startswith("file:///")

    def test_file_uri_input_not_double_wrapped(self):
        """已是 file:/// 的 fs_path 不應被雙重包裝（回歸測試）"""
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)
        mock_repo.get_by_numbers.return_value = {}

        # 注意：caller（enrich_single）應先 uri_to_fs_path 再傳入，
        # 但即使誤傳 URI，也不應變成 file:///file:///
        # 此處用 FS path 驗證正常 case
        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/mnt/c/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        path = captured[0].path
        assert path.startswith("file:///")
        assert "file:///file:///" not in path


# ── 26b. 89b-T2: _db_upsert 寫入 scrape_attempted_at ─────────────────────────

class TestDbUpsertScrapeAttemptedAt:
    """89b-T2: _db_upsert 成功路徑 Video 帶 scrape_attempted_at > 0（供 T3/T4 消費）"""

    def test_scrape_attempted_at_set(self):
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)
        mock_repo.get_by_numbers.return_value = {}
        mock_repo.get_by_path.return_value = None

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert captured[0].scrape_attempted_at > 0


# ── 27. F1: _db_upsert cover_path 處理 ────────────────────────────

class TestDbUpsertCoverPath:
    """F1: cover_path 不寫遠端 URL；有本地封面時寫 file:/// URI；否則保留 DB 既有值"""

    def test_remote_url_not_written(self):
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)
        mock_repo.get_by_path.return_value = None

        meta = {"title": "T", "cover_url": "https://cdn.example.com/cover.jpg",
                "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        # 不傳 local_cover_path → 不應寫遠端 URL
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert not (captured[0].cover_path or "").startswith("http")

    @patch("os.path.exists", return_value=True)
    def test_local_cover_written_as_file_uri(self, _mock_exists):
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta,
                   local_cover_path="/video/SONE-205.jpg")

        assert len(captured) == 1
        assert captured[0].cover_path.startswith("file:///")

    def test_preserves_existing_db_cover_path_by_path(self):
        """沒有新封面時用 get_by_path 精確保留同一筆紀錄的 cover_path"""
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)

        existing_video = MagicMock()
        existing_video.cover_path = to_file_uri("C:/lib/SONE-205/cover.jpg")
        mock_repo.get_by_path.return_value = existing_video

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert captured[0].cover_path == to_file_uri("C:/lib/SONE-205/cover.jpg")
        # 確認用 path URI 查詢，不是用 number
        mock_repo.get_by_path.assert_called_once()


# ── 27b. TASK-89a-T5 (CD-89a-5 / Codex C2): output_dir 保留（鏡射 TestDbUpsertCoverPath）──

class TestDbUpsertOutputDir:
    """C2 端到端回歸鎖：enricher 補完/重刮不得洗掉 producer 寫入的 output_dir。"""

    def test_c2_end_to_end_preserves_existing_output_dir(self):
        """existing.output_dir 非空（producer row）→ _db_upsert 寫入的 Video.output_dir
        必須等於原值（顯式保留，非僅依賴 T1 DB CASE-WHEN 兜底）。"""
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)

        existing_video = MagicMock()
        existing_video.output_dir = to_file_uri("/output/lib/SONE-205")
        existing_video.cover_path = ""
        existing_video.user_tags = []
        existing_video.sample_images = []
        mock_repo.get_by_path.return_value = existing_video

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert captured[0].output_dir == to_file_uri("/output/lib/SONE-205")

    def test_no_existing_row_output_dir_defaults_empty(self):
        """existing is None（首次遇到此 path）→ output_dir 傳空字串，不炸，交由 T1
        DB CASE-WHEN 兜底（行為與現況一致，不 regress）。"""
        from core.enricher import _db_upsert

        captured = []
        mock_repo = MagicMock()
        mock_repo.upsert.side_effect = lambda v: captured.append(v)
        mock_repo.get_by_path.return_value = None

        meta = {"title": "T", "actresses": [], "maker": "S", "tags": [], "release_date": ""}
        _db_upsert(mock_repo, "SONE-205", "/video/SONE-205.mp4", meta)

        assert len(captured) == 1
        assert captured[0].output_dir == ""


# ── 28. F2: has_subtitle 由 find_subtitle_files 決定 ────────────────────────────

class TestHasSubtitleDetected:
    def test_has_subtitle_true_when_srt_exists(self):
        """F2: 影片同目錄有 .srt 時，generate_nfo 應以 has_subtitle=True 呼叫"""
        video = _make_video()

        captured_calls = []

        def fake_generate_nfo(**kwargs):
            captured_calls.append(kwargs)
            return True

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=fake_generate_nfo),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=["/video/SONE-205.srt"]),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=True,
            )

        assert result.success is True
        assert captured_calls, "generate_nfo 應被呼叫"
        assert captured_calls[0].get("has_subtitle") is True, (
            "有字幕檔時 has_subtitle 應為 True"
        )

    def test_has_subtitle_false_when_no_srt(self):
        """F2: 影片同目錄無字幕時，generate_nfo 應以 has_subtitle=False 呼叫"""
        video = _make_video()

        captured_calls = []

        def fake_generate_nfo(**kwargs):
            captured_calls.append(kwargs)
            return True

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=fake_generate_nfo),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                write_nfo=True,
                overwrite_existing=True,
            )

        assert result.success is True
        assert captured_calls, "generate_nfo 應被呼叫"
        assert captured_calls[0].get("has_subtitle") is False, (
            "無字幕檔時 has_subtitle 應為 False"
        )


# ── 29. F3: series="" 應觸發 scraper ────────────────────────────────────────────

class TestMissingFieldsEmptySeries:
    def test_empty_series_string_triggers_scraper(self):
        """F3: _video_to_meta 把缺失 series 正規化為空字串，_missing_fields 應視為缺失"""
        video = _make_video(series="")  # 空字串，非 None
        db_result = {"SONE-205": [video]}
        scraper_data = _make_scraper_result(series="テストシリーズ")

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = db_result

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="fill_missing",
            )

        mock_search.assert_called_once(), "series='' 應視為缺失，觸發 scraper"
        assert result.success is True
        assert "series" in result.fields_filled


# ── T2: source / javbus_lang 參數路由 ─────────────────────────────────────────

class TestSourceParam:
    def test_source_passed_to_search_jav_refresh_full(self):
        """T2: source='javbus' 在 refresh_full mode 正確傳給 search_jav"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.search_jav", return_value=_make_scraper_result()) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.enricher.VideoRepository"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
                source="javbus",
            )
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs.get("source") == "javbus"

    def test_javbus_lang_passed_to_search_jav(self):
        """T2: javbus_lang='ja' 正確傳給 search_jav"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.search_jav", return_value=_make_scraper_result()) as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.enricher.VideoRepository"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
                javbus_lang="ja",
            )
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs.get("javbus_lang") == "ja"

    def test_invalid_source_returns_error(self):
        """T2: 無效 source 經 search_jav 攔截後回傳 None，enrich_single 回 error"""
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.VideoRepository"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
                source="invalid_xyz",
            )
        assert result.success is False
        assert result.error is not None


# ── P1: scraper_data 參數傳入時跳過 search_jav ────────────────────────────────

class TestScraperDataSkipsSearchJav:
    def test_scraper_data_skips_search_jav(self):
        """P1: 傳入 scraper_data → search_jav 不應被呼叫（refresh_full mode）"""
        provided_data = _make_scraper_result()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.enricher.VideoRepository"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=FS_PATH,
                number="SONE-205",
                mode="refresh_full",
                scraper_data=provided_data,
            )

        mock_search.assert_not_called()
        assert result.success is True


# ══════════════════════════════════════════════════════════════════════════════
# 72b-T6：_write_external_images + enrich_single external_manager 整合
# ══════════════════════════════════════════════════════════════════════════════

# ── T6-A. _write_external_images 單元測試（tmp_path 真實 JPEG）─────────────────

def _create_dummy_jpeg(path) -> None:
    """建立最小合法 JPEG（300×200 橫向圖，確保 crop_to_poster h/w < 1.0 走橫向裁切）。"""
    from PIL import Image
    img = Image.new("RGB", (300, 200), color=(128, 64, 32))
    img.save(str(path), "JPEG", quality=95)


class TestWriteExternalImages:
    """_write_external_images 契約：gate on cover_path.exists()、模式、overwrite。"""

    def test_off_mode_returns_false_false(self, tmp_path):
        """off 模式：直接 no-op 回 False/False，即使底圖存在。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "off", True)
        assert result == {"poster": False, "fanart": False}

    def test_no_cover_returns_false_false(self, tmp_path):
        """底圖不存在 → gate 落空 → False/False。"""
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", True)
        assert result == {"poster": False, "fanart": False}

    def test_jellyfin_creates_stem_poster_fanart(self, tmp_path):
        """jellyfin：產 {stem}-poster.jpg + {stem}-fanart.jpg，回傳 True/True。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", True)
        assert result == {"poster": True, "fanart": True}
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()

    def test_emby_creates_stem_poster_fanart(self, tmp_path):
        """emby：產 {stem}-poster.jpg + {stem}-fanart.jpg（等價 jellyfin/kodi），回傳 True/True。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "emby", True)
        assert result == {"poster": True, "fanart": True}
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()
        # 裸短名不存在
        assert not (tmp_path / "poster.jpg").exists()
        assert not (tmp_path / "fanart.jpg").exists()

    def test_kodi_creates_stem_poster_fanart(self, tmp_path):
        """kodi：產 {stem}-poster.jpg + {stem}-fanart.jpg（與 jellyfin 相同），回傳 True/True。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "kodi", True)
        assert result == {"poster": True, "fanart": True}
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()
        # 裸短名不存在
        assert not (tmp_path / "poster.jpg").exists()
        assert not (tmp_path / "fanart.jpg").exists()

    def test_overwrite_false_existing_skips_but_reports_true(self, tmp_path):
        """overwrite=False + 已有 poster/fanart → 跳過寫入，但回傳 True（磁碟存在）。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        poster = tmp_path / "SONE-205-poster.jpg"
        fanart = tmp_path / "SONE-205-fanart.jpg"
        poster.write_bytes(b"existing")
        fanart.write_bytes(b"existing")
        poster_mtime = poster.stat().st_mtime
        fanart_mtime = fanart.stat().st_mtime

        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", False)
        assert result == {"poster": True, "fanart": True}
        # 檔案未被覆蓋（mtime 不變）
        assert poster.stat().st_mtime == poster_mtime
        assert fanart.stat().st_mtime == fanart_mtime

    def test_overwrite_true_overwrites_existing(self, tmp_path):
        """overwrite=True → 即使已存在也重產（fanart 應比 existing dummy 大）。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        fanart = tmp_path / "SONE-205-fanart.jpg"
        fanart.write_bytes(b"tiny")  # 比真實 JPEG 小

        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", True)
        assert result["fanart"] is True
        assert fanart.stat().st_size > 4  # 覆蓋後應為真實 JPEG

    def test_unknown_manager_returns_false_false(self, tmp_path):
        """未知 external_manager 值 → 不產圖、不崩。"""
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)
        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "unknown_mode", True)
        assert result == {"poster": False, "fanart": False}

    def test_no_cover_but_stem_poster_fanart_exist_returns_true(self, tmp_path):
        """72d-P2B：無 {stem}.jpg，但 stem-poster + stem-fanart 皆存在，overwrite=False
        → {"poster": True, "fanart": True}，且兩檔內容不被修改（無 copy/crop）。"""
        # 不建立 {stem}.jpg（cover）
        poster = tmp_path / "SONE-205-poster.jpg"
        fanart = tmp_path / "SONE-205-fanart.jpg"
        poster.write_bytes(b"existing-poster")
        fanart.write_bytes(b"existing-fanart")
        poster_content = poster.read_bytes()
        fanart_content = fanart.read_bytes()

        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", False)

        assert result == {"poster": True, "fanart": True}
        # 檔案未被覆蓋（bytes 不變）
        assert poster.read_bytes() == poster_content
        assert fanart.read_bytes() == fanart_content

    def test_no_cover_stem_poster_only_partial_return(self, tmp_path):
        """72d-P2B：無 {stem}.jpg，只有 stem-poster.jpg（無 fanart），overwrite=False
        → {"poster": True, "fanart": False}。"""
        # 不建立 {stem}.jpg（cover）
        poster = tmp_path / "SONE-205-poster.jpg"
        poster.write_bytes(b"existing-poster")
        # 不建立 fanart

        from core.enricher import _write_external_images
        result = _write_external_images(str(tmp_path / "SONE-205.mp4"), "jellyfin", False)

        assert result == {"poster": True, "fanart": False}


# ── T6-B. enrich_single external_manager 整合測試（mock scraper/DB/generate_nfo）──

class TestEnrichSingleExternalManager:
    """enrich_single 整合：external_manager 穿線 + 寫序 + NFO has_poster/has_fanart。"""

    def _make_mock_repo(self):
        mock_repo = MagicMock()
        mock_repo.get_by_numbers.return_value = {"SONE-205": [_make_video()]}
        mock_repo.get_by_path.return_value = None
        return mock_repo

    def test_off_mode_no_external_images(self, tmp_path):
        """off 模式：不產 poster/fanart，generate_nfo has_poster/has_fanart=False。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="off",
            )

        assert result.success is True
        # off 模式 → 無外部圖
        assert not (tmp_path / "SONE-205-poster.jpg").exists()
        assert not (tmp_path / "SONE-205-fanart.jpg").exists()
        assert not (tmp_path / "poster.jpg").exists()
        assert not (tmp_path / "fanart.jpg").exists()
        # generate_nfo 收到的 external_manager 應為 off（或未傳，即 default off）
        if captured:
            assert captured[0].get("external_manager", "off") == "off"
            assert captured[0].get("has_poster", False) is False
            assert captured[0].get("has_fanart", False) is False

    def test_jellyfin_creates_images_nfo_has_poster_fanart(self, tmp_path):
        """jellyfin：cover 已存在 → 產 {stem}-poster/-fanart，NFO has_poster/has_fanart=True。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is True
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()
        assert captured, "generate_nfo 應被呼叫"
        assert captured[0].get("external_manager") == "jellyfin"
        assert captured[0].get("has_poster") is True
        assert captured[0].get("has_fanart") is True

    def test_kodi_creates_stem_images_nfo_has_poster_fanart(self, tmp_path):
        """kodi：產 {stem}-poster.jpg + {stem}-fanart.jpg（與 jellyfin 相同），NFO has_poster/has_fanart=True。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        assert result.success is True
        # kodi 固定 stem 命名（與 jellyfin 相同）
        assert (tmp_path / "SONE-205-poster.jpg").exists(), "kodi 應產 stem-poster.jpg"
        assert (tmp_path / "SONE-205-fanart.jpg").exists(), "kodi 應產 stem-fanart.jpg"
        assert not (tmp_path / "poster.jpg").exists(), "kodi 不應有裸 poster.jpg"
        assert not (tmp_path / "fanart.jpg").exists(), "kodi 不應有裸 fanart.jpg"
        assert captured, "generate_nfo 應被呼叫"
        assert captured[0].get("external_manager") == "kodi"
        assert captured[0].get("has_poster") is True
        assert captured[0].get("has_fanart") is True

    def test_cover_preexists_overwrite_false_still_produces_external_images(self, tmp_path):
        """落點 2：.jpg 預存 + overwrite=False → _write_cover 回 False，但底圖在磁碟 →
        _write_external_images gate cover_path.exists() → poster/fanart 仍產出；
        NFO has_poster/has_fanart=True。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=True,   # 開著，但 cover 已存在 + overwrite=False
                overwrite_existing=False,
                external_manager="jellyfin",
            )

        assert result.success is True
        # cover_written=False（gate: cover 已存在 + overwrite=False）
        assert result.cover_written is False
        # 但外部圖仍產出（gate on cover_path.exists()，不是 cover_written）
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()
        # NFO has_poster/has_fanart=True
        assert captured, "generate_nfo 應被呼叫"
        assert captured[0].get("has_poster") is True
        assert captured[0].get("has_fanart") is True

    def test_reorder_nfo_written_after_images(self, tmp_path):
        """寫序驗證：external 模式 NFO 在圖片後寫入 → generate_nfo 呼叫時 poster 已存在。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        write_order: list = []

        def fake_nfo(**kwargs):
            # 記錄呼叫時 poster 是否存在（應已存在）
            poster_exists = (tmp_path / "SONE-205-poster.jpg").exists()
            write_order.append(("nfo", poster_exists))

        original_copy2 = __import__("shutil").copy2

        def spy_copy2(src, dst):
            write_order.append(("copy2", Path(dst).name))
            return original_copy2(src, dst)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.enricher.shutil.copy2", side_effect=spy_copy2),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        # NFO 應在 copy2（fanart）之後
        nfo_calls = [i for i, (kind, _) in enumerate(write_order) if kind == "nfo"]
        copy2_calls = [i for i, (kind, _) in enumerate(write_order) if kind == "copy2"]
        assert nfo_calls, "generate_nfo 應被呼叫"
        assert copy2_calls, "shutil.copy2 (fanart) 應被呼叫"
        assert min(nfo_calls) > max(copy2_calls), (
            "NFO 應在 fanart copy2 之後寫入；實際寫序：" + str(write_order)
        )
        # 且 generate_nfo 呼叫時 poster 已存在
        _, poster_present = write_order[nfo_calls[0]]
        assert poster_present, "generate_nfo 被呼叫時 poster 應已存在"

    def test_no_cover_no_external_images(self, tmp_path):
        """無底圖：.jpg 不存在 → external images 不產出，NFO has_* False。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        # 不建立 cover.jpg

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is True
        assert not (tmp_path / "SONE-205-poster.jpg").exists()
        assert not (tmp_path / "SONE-205-fanart.jpg").exists()
        if captured:
            assert captured[0].get("has_poster", False) is False
            assert captured[0].get("has_fanart", False) is False

    def test_permission_error_nfo_external_mode(self, tmp_path):
        """PermissionError on NFO（external 模式）→ success=False，提示權限。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo()),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=PermissionError("read-only")),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is False
        assert "權限" in result.error or "寫入" in result.error

    def test_extrafanart_untouched_in_external_mode(self, tmp_path):
        """_write_extrafanart 在 external 模式仍由 write_extrafanart=False 控制（不被呼叫）。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        mock_repo = self._make_mock_repo()
        mock_repo.get_by_numbers.return_value = {"SONE-205": [_make_video(
            sample_images=["https://example.com/s1.jpg"]
        )]}

        with (
            patch("core.enricher.VideoRepository", return_value=mock_repo),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo"),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=False,
                write_cover=False,
                write_extrafanart=False,  # 預設關閉
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.extrafanart_written == 0
        assert not (tmp_path / "extrafanart").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 72c-codexP1：kodi 多片共用資料夾 stem 命名（E1/E2/E3/E4）
# ══════════════════════════════════════════════════════════════════════════════


class TestKodiStemNaming:
    """E1/E2/E3/E4：kodi 模式 stem/短名切換 + 多片不碰撞（72c-codexP1）"""

    def _make_mock_repo_for(self, number: str):
        mock_repo = MagicMock()
        mock_repo.get_by_numbers.return_value = {number: [_make_video(number=number)]}
        mock_repo.get_by_path.return_value = None
        # db_path 設 in-memory：避免 enrich nfo_mtime 更新路徑（enricher.py:525
        # get_connection(repo.db_path)）對 MagicMock 做 sqlite3.connect → 在 repo root
        # 產生 "<MagicMock ...>" 垃圾檔。:memory: 下該 UPDATE 因無 videos 表靜默失敗
        # （已被 try/except 包裹），不留任何檔案。
        mock_repo.db_path = ":memory:"
        return mock_repo

    def test_E1_kodi_two_videos_stem_named_no_collision(self, tmp_path):
        """E1：kodi + 同資料夾 2 片 → 各得 {stem}-poster.jpg/{stem}-fanart.jpg；
        無共用 poster.jpg；各 NFO <poster> 各指自己 stem。"""
        # 建立 2 個 mp4 + 各自封面
        mp4_a = tmp_path / "SONE-205.mp4"
        mp4_b = tmp_path / "MIDE-001.mp4"
        mp4_a.touch()
        mp4_b.touch()
        cover_a = tmp_path / "SONE-205.jpg"
        cover_b = tmp_path / "MIDE-001.jpg"
        _create_dummy_jpeg(cover_a)
        _create_dummy_jpeg(cover_b)

        captured_a = []
        captured_b = []

        def fake_nfo_a(**kwargs):
            captured_a.append(kwargs)

        def fake_nfo_b(**kwargs):
            captured_b.append(kwargs)

        # 處理第一片 SONE-205
        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("SONE-205")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo_a),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result_a = enrich_single(
                file_path=str(mp4_a),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        # 處理第二片 MIDE-001
        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("MIDE-001")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo_b),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result_b = enrich_single(
                file_path=str(mp4_b),
                number="MIDE-001",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        assert result_a.success is True
        assert result_b.success is True

        # E1：各得 stem 命名
        assert (tmp_path / "SONE-205-poster.jpg").exists(), "A 應產 stem poster"
        assert (tmp_path / "SONE-205-fanart.jpg").exists(), "A 應產 stem fanart"
        assert (tmp_path / "MIDE-001-poster.jpg").exists(), "B 應產 stem poster"
        assert (tmp_path / "MIDE-001-fanart.jpg").exists(), "B 應產 stem fanart"

        # E1：不存在共用短名（kodi 固定 stem 長格式）
        assert not (tmp_path / "poster.jpg").exists(), "共用 poster.jpg 不應存在"
        assert not (tmp_path / "fanart.jpg").exists(), "共用 fanart.jpg 不應存在"

        # E1：generate_nfo 均被呼叫且 external_manager='kodi'
        assert captured_a, "SONE-205 generate_nfo 應被呼叫"
        assert captured_b, "MIDE-001 generate_nfo 應被呼叫"
        assert captured_a[0].get("external_manager") == "kodi"
        assert captured_b[0].get("external_manager") == "kodi"

    def test_E2_kodi_single_video_stem_named(self, tmp_path):
        """E2：kodi + 同資料夾僅 1 片 → 仍使用 stem 命名（固定行為，與 jellyfin 相同）。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("SONE-205")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        assert result.success is True

        # E2：stem 命名（kodi 固定長格式）
        assert (tmp_path / "SONE-205-poster.jpg").exists(), "kodi 應產 {stem}-poster.jpg"
        assert (tmp_path / "SONE-205-fanart.jpg").exists(), "kodi 應產 {stem}-fanart.jpg"

        # E2：裸短名不存在
        assert not (tmp_path / "poster.jpg").exists(), "kodi 不應有裸 poster.jpg"
        assert not (tmp_path / "fanart.jpg").exists(), "kodi 不應有裸 fanart.jpg"

        # E2：generate_nfo 呼叫帶 external_manager='kodi'
        assert captured, "generate_nfo 應被呼叫"
        assert captured[0].get("external_manager") == "kodi"

    def test_E3_kodi_two_videos_overwrite_true_no_cross_contamination(self, tmp_path):
        """E3：kodi 2 片 + overwrite_existing=True → 第二片不覆蓋第一片 artwork（路徑互異）。"""
        mp4_a = tmp_path / "SONE-205.mp4"
        mp4_b = tmp_path / "MIDE-001.mp4"
        mp4_a.touch()
        mp4_b.touch()
        cover_a = tmp_path / "SONE-205.jpg"
        cover_b = tmp_path / "MIDE-001.jpg"
        _create_dummy_jpeg(cover_a)
        _create_dummy_jpeg(cover_b)

        # 處理第一片
        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("SONE-205")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo"),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=str(mp4_a),
                number="SONE-205",
                write_nfo=False,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        # 記錄第一片 artwork mtime
        poster_a = tmp_path / "SONE-205-poster.jpg"
        fanart_a = tmp_path / "SONE-205-fanart.jpg"
        assert poster_a.exists(), "E3 前置：A poster 應存在"
        mtime_a_poster = poster_a.stat().st_mtime
        mtime_a_fanart = fanart_a.stat().st_mtime

        # 處理第二片
        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("MIDE-001")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo"),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=str(mp4_b),
                number="MIDE-001",
                write_nfo=False,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        # E3：A 的 artwork 不被 B 覆蓋（路徑互異，mtime 不變）
        assert poster_a.stat().st_mtime == mtime_a_poster, "A poster 不應被 B 覆蓋"
        assert fanart_a.stat().st_mtime == mtime_a_fanart, "A fanart 不應被 B 覆蓋"
        # B 有自己的 artwork
        assert (tmp_path / "MIDE-001-poster.jpg").exists(), "B 應有自己的 poster"
        assert (tmp_path / "MIDE-001-fanart.jpg").exists(), "B 應有自己的 fanart"

    def test_E4_jellyfin_unchanged(self, tmp_path):
        """E4：jellyfin 行為不變（回歸）— stem 命名，NFO external_manager='jellyfin'。"""
        mp4_a = tmp_path / "SONE-205.mp4"
        mp4_b = tmp_path / "MIDE-001.mp4"
        mp4_a.touch()
        mp4_b.touch()
        cover_a = tmp_path / "SONE-205.jpg"
        cover_b = tmp_path / "MIDE-001.jpg"
        _create_dummy_jpeg(cover_a)
        _create_dummy_jpeg(cover_b)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        # 只測第一片（jellyfin 的 stem 命名本就 per-video，回歸即可）
        with (
            patch("core.enricher.VideoRepository", return_value=MagicMock(
                **{"get_by_numbers.return_value": {"SONE-205": [_make_video()]},
                   "get_by_path.return_value": None}
            )),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4_a),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is True
        # jellyfin：stem 命名
        assert (tmp_path / "SONE-205-poster.jpg").exists()
        assert (tmp_path / "SONE-205-fanart.jpg").exists()
        # E4：NFO external_manager='jellyfin'
        assert captured
        assert captured[0].get("external_manager") == "jellyfin"
        assert captured[0].get("has_poster") is True
        assert captured[0].get("has_fanart") is True

    def test_E4_off_unchanged(self, tmp_path):
        """E4 off：off 模式不寫 external images（回歸）。"""
        mp4 = tmp_path / "SONE-205.mp4"
        mp4.touch()
        cover = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover)

        with (
            patch("core.enricher.VideoRepository", return_value=MagicMock(
                **{"get_by_numbers.return_value": {"SONE-205": [_make_video()]},
                   "get_by_path.return_value": None}
            )),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo"),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number="SONE-205",
                write_nfo=False,
                write_cover=False,
                overwrite_existing=True,
                external_manager="off",
            )

        assert result.success is True
        # off 模式：無任何 poster/fanart
        assert not (tmp_path / "poster.jpg").exists()
        assert not (tmp_path / "fanart.jpg").exists()
        assert not (tmp_path / "SONE-205-poster.jpg").exists()
        assert not (tmp_path / "SONE-205-fanart.jpg").exists()

    def test_E5_uri_input_kodi_stem_named(self, tmp_path):
        """E5：enrich_single 接收 file:/// URI（production path）時，
        kodi → stem 命名（固定，不論 sibling video 數量）。"""
        mp4_a = tmp_path / "SONE-205.mp4"
        mp4_b = tmp_path / "MIDE-001.mp4"
        mp4_a.touch()
        mp4_b.touch()
        cover_a = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover_a)

        captured = []

        def fake_nfo(**kwargs):
            captured.append(kwargs)

        # 關鍵：file_path 用 to_file_uri 包裝成 file:/// URI（模擬 web API 傳入）
        file_uri = to_file_uri(str(mp4_a))

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("SONE-205")),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", side_effect=fake_nfo),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_uri,
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        assert result.success is True, f"enrich_single 應成功，error={result.error}"
        # URI input 下 kodi 固定 stem 命名
        assert captured, "generate_nfo 應被呼叫"
        assert captured[0].get("external_manager") == "kodi"
        # 磁碟上應有 stem 命名 artwork
        assert (tmp_path / "SONE-205-poster.jpg").exists(), "URI input 下應產 stem poster"
        assert (tmp_path / "SONE-205-fanart.jpg").exists(), "URI input 下應產 stem fanart"
        assert not (tmp_path / "poster.jpg").exists(), "URI input 下不應有共用 poster.jpg"

    def test_E6_kodi_nfo_disk_content_stem_names(self, tmp_path):
        """E6（disk 驗證）：kodi → 寫入磁碟的 NFO <poster>/<fanart>
        包含 {stem}-poster.jpg/{stem}-fanart.jpg，且不含 bare poster.jpg。
        不 mock generate_nfo — 驗證 NFO 實際寫入內容。"""
        import xml.etree.ElementTree as ET

        mp4_a = tmp_path / "SONE-205.mp4"
        mp4_b = tmp_path / "MIDE-001.mp4"
        mp4_a.touch()
        mp4_b.touch()
        cover_a = tmp_path / "SONE-205.jpg"
        _create_dummy_jpeg(cover_a)

        with (
            patch("core.enricher.VideoRepository", return_value=self._make_mock_repo_for("SONE-205")),
            patch("core.enricher.search_jav", return_value=None),
            # generate_nfo NOT mocked — 真實寫 NFO 到磁碟
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4_a),
                number="SONE-205",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="kodi",
            )

        assert result.success is True, f"enrich_single 應成功，error={result.error}"
        assert result.nfo_written is True, "NFO 應寫出"

        nfo_path = tmp_path / "SONE-205.nfo"
        assert nfo_path.exists(), "NFO 檔應存在於磁碟"

        tree = ET.parse(str(nfo_path))
        root = tree.getroot()

        poster_elem = root.find("poster")
        fanart_elem = root.find("fanart")
        assert poster_elem is not None, "NFO 應有 <poster> 標籤"
        assert fanart_elem is not None, "NFO 應有 <fanart> 標籤"

        poster_text = poster_elem.text or ""
        fanart_text = fanart_elem.text or ""

        # kodi 固定 stem 命名
        assert "SONE-205-poster" in poster_text, (
            f"NFO <poster> 應含 stem 命名（SONE-205-poster），實際：{poster_text!r}"
        )
        assert "SONE-205-fanart" in fanart_text, (
            f"NFO <fanart> 應含 stem 命名（SONE-205-fanart），實際：{fanart_text!r}"
        )
        assert poster_text.strip() != "poster.jpg", (
            "NFO <poster> 不應是 bare 'poster.jpg'"
        )
        assert fanart_text.strip() != "fanart.jpg", (
            "NFO <fanart> 不應是 bare 'fanart.jpg'"
        )


# ── TASK-91-T3: 站台 1/2/3 — uri_to_local_fs_path WSL+UNC path_mappings 反解 ──

_WSL_UNC_MAPPINGS = {"/home/user/nas": "//NAS/share"}
_WSL_UNC_URI = "file://///NAS/share/dir/movie.mp4"
_WSL_UNC_REVERSED = "/home/user/nas/dir/movie.mp4"


class TestEnrichSinglePathMappingReverse:
    """站台1（enrich_single :358）：fs_path 必須是 path_mappings 反解後的本機路徑，
    不是裸 uri_to_fs_path 產出的 UNC 字面值（mutation-sensitive）。"""

    def test_wsl_unc_mapping_reverses_fs_path(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        captured = []

        def fake_exists(p):
            captured.append(p)
            return False  # 提早以「檔案不存在」return，不需 mock 整條 pipeline

        with patch("os.path.exists", side_effect=fake_exists):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.error == "檔案不存在"
        assert captured, "os.path.exists 應被呼叫"
        assert captured[0] == _WSL_UNC_REVERSED, (
            f"fs_path 應反解為本機路徑 {_WSL_UNC_REVERSED}，實際: {captured[0]!r}"
        )

    def test_non_file_uri_fallback_passthrough_unchanged(self, monkeypatch):
        """邊界4：非 file:/// 輸入的 try/except passthrough 不可回歸。"""
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        bare_path = "just-a-bare-local-string-not-a-uri"
        captured = []

        def fake_exists(p):
            captured.append(p)
            return False

        with patch("os.path.exists", side_effect=fake_exists):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=bare_path,
                number="SONE-205",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.error == "檔案不存在"
        assert captured[0] == bare_path, (
            f"非 URI 輸入應原樣 passthrough，實際: {captured[0]!r}"
        )


class TestFetchSamplesOnlyPathMappingReverse:
    """站台2（fetch_samples_only :618）：同站台1的反解行為。"""

    def test_wsl_unc_mapping_reverses_fs_path(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        captured = []

        def fake_exists(p):
            captured.append(p)
            return False

        with patch("os.path.exists", side_effect=fake_exists):
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.error == "檔案不存在"
        assert captured, "os.path.exists 應被呼叫"
        assert captured[0] == _WSL_UNC_REVERSED, (
            f"fs_path 應反解為本機路徑 {_WSL_UNC_REVERSED}，實際: {captured[0]!r}"
        )

    def test_non_file_uri_fallback_passthrough_unchanged(self, monkeypatch):
        """邊界4：非 file:/// 輸入的 try/except passthrough 不可回歸。"""
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        bare_path = "just-a-bare-local-string-not-a-uri"
        captured = []

        def fake_exists(p):
            captured.append(p)
            return False

        with patch("os.path.exists", side_effect=fake_exists):
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(
                file_path=bare_path,
                number="SONE-205",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.error == "檔案不存在"
        assert captured[0] == bare_path, (
            f"非 URI 輸入應原樣 passthrough，實際: {captured[0]!r}"
        )


class TestResolveNfoCoverPathsMappingReverse:
    """站台3（resolve_nfo_cover_paths :667）：純函式，直接測反解後的 nfo/cover 路徑。"""

    def test_wsl_unc_mapping_reverses_paths(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        from core.enricher import resolve_nfo_cover_paths
        nfo_path, cover_path = resolve_nfo_cover_paths(
            _WSL_UNC_URI,
            path_mappings=_WSL_UNC_MAPPINGS,
        )

        assert nfo_path == "/home/user/nas/dir/movie.nfo", (
            f"nfo_path 應反解為本機路徑，實際: {nfo_path!r}"
        )
        assert cover_path == "/home/user/nas/dir/movie.jpg", (
            f"cover_path 應反解為本機路徑，實際: {cover_path!r}"
        )

    def test_non_file_uri_fallback_passthrough_unchanged(self, monkeypatch):
        """邊界4：非 file:/// 輸入的 try/except passthrough 不可回歸。"""
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        bare_path = "just-a-bare-local-string-not-a-uri"
        from core.enricher import resolve_nfo_cover_paths
        nfo_path, cover_path = resolve_nfo_cover_paths(
            bare_path,
            path_mappings=_WSL_UNC_MAPPINGS,
        )

        assert nfo_path == bare_path + ".nfo"
        assert cover_path == bare_path + ".jpg"


# ── TASK-91 Codex Finding 1: DB key 必須維持映射命名空間，不可用反解後本機路徑 ──
# 反例：若 fs_path_for_db 被誤還原為 fs_path（反解後本機路徑），DB round-trip
# （get_by_path / update_scrape_attempted_at / nfo_mtime WHERE path=?）永遠對不上
# DB 既有 row（DB 存的是映射端 UNC URI）。Mutation-sensitive：revert 該行 → 下列全 RED。

class TestEnrichSingleDbKeyMappingPreserved:
    """站台1 DB key（enrich_single）：get_by_path / update_scrape_attempted_at 必須用
    fs_path_for_db（裸 uri_to_fs_path，維持 DB 映射命名空間），不是反解後 fs_path。"""

    def test_not_found_branch_marks_scrape_attempted_at_with_mapped_key(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                mode="refresh_full",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.success is False
        mock_repo.update_scrape_attempted_at.assert_called_once()
        call_args = mock_repo.update_scrape_attempted_at.call_args[0]
        assert call_args[0] == _WSL_UNC_URI, (
            f"DB key 必須維持映射命名空間（{_WSL_UNC_URI!r}），"
            f"不可用反解後本機路徑組出的 URI，實際: {call_args[0]!r}"
        )

    def test_get_by_path_uses_mapped_db_key(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        video = _make_video()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                mode="fill_missing",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.success is True
        # v0.11.9 起 get_by_path 在 enrich_single 內被呼叫兩次：一次讀 user_tags
        # （既有行為），一次是 Codex P1 修正新增的「reason=hit 鏡射 /thumb gate」
        # DB 最終狀態重讀（core/enricher.py 尾段）。兩次都必須用映射命名空間查 DB。
        assert mock_repo.get_by_path.call_count == 2
        for call in mock_repo.get_by_path.call_args_list:
            called_uri = call[0][0]
            assert called_uri == _WSL_UNC_URI, (
                f"get_by_path 必須用映射命名空間查 DB（{_WSL_UNC_URI!r}），實際: {called_uri!r}"
            )


class TestDbUpsertCoverAndSampleUrisForwardMapped:
    """TASK-91 Finding 1 extension：新產生的 cover / extrafanart 磁碟路徑寫回 DB 前，
    必須 forward-map 回映射命名空間（cover/sample 是新產生的磁碟路徑，不是自描述輸入，
    走 to_file_uri(local_path, path_mappings) 正向 pattern，非 uri-no-reverse pattern）。"""

    def test_full_flow_cover_and_sample_uris_are_mapped(self, monkeypatch):
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        scraper_data = _make_scraper_result()

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("os.makedirs"),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}
            mock_repo.get_by_path.return_value = None
            captured = []
            mock_repo.upsert.side_effect = lambda v: captured.append(v)

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                mode="refresh_full",
                write_extrafanart=True,
                overwrite_existing=True,
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.success is True
        assert len(captured) == 1
        video = captured[0]
        assert video.path == _WSL_UNC_URI, (
            f"DB row path 必須是映射命名空間，實際: {video.path!r}"
        )
        assert video.cover_path.startswith("file://///NAS/share/dir/"), (
            f"cover_path 應 forward-map 回映射命名空間，不應殘留反解後本機路徑，實際: {video.cover_path!r}"
        )
        assert video.sample_images, "extrafanart 應有實際寫入"
        for uri in video.sample_images:
            assert uri.startswith("file://///NAS/share/dir/extrafanart/"), (
                f"sample_images 應 forward-map 回映射命名空間，實際: {uri!r}"
            )

    def test_fetch_samples_only_sample_uris_are_mapped(self, monkeypatch):
        """站台2（fetch_samples_only）：_db_upsert_samples_only 用 fs_path_for_db 當 key，
        _write_extrafanart 產生的 sample uri 亦需 forward-map。"""
        from core import path_utils
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        meta = {"sample_images": ["https://example.com/s1.jpg"], "source": "javbus"}

        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=meta),
            patch("core.enricher.download_image", return_value=True),
            patch("os.makedirs"),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            from core.enricher import fetch_samples_only
            result = fetch_samples_only(
                file_path=_WSL_UNC_URI,
                number="SONE-205",
                path_mappings=_WSL_UNC_MAPPINGS,
            )

        assert result.success is True
        mock_repo.update_sample_images.assert_called_once()
        call_args = mock_repo.update_sample_images.call_args[0]
        assert call_args[0] == _WSL_UNC_URI, (
            f"update_sample_images DB key 必須維持映射命名空間，實際: {call_args[0]!r}"
        )
        for uri in call_args[1]:
            assert uri.startswith("file://///NAS/share/dir/extrafanart/"), (
                f"sample uri 應 forward-map 回映射命名空間，實際: {uri!r}"
            )


# ── TASK-98b-T2: 重刮 focal trigger 接線 ─────────────────────────────────────

class TestEnrichFocalTrigger:
    """重刮無碼片 → maybe_submit_video_focal 被呼（wire-point 契約）。

    helper 本體 gate 於 test_focal_trigger.py 覆蓋；此處只驗 enricher 有接線、
    且傳入的 (number, maker, video_path_uri, cover_fs) 對齊 _db_upsert 的 DB key。
    """

    def _run_refresh(self, number="SIRO-1234", maker="SOD"):
        from unittest.mock import patch, MagicMock
        scraper_data = {
            "number": number,
            "title": "Test",
            "actors": [],
            "cover": "http://example.com/cover.jpg",
            "date": "2024-01-01",
            "maker": maker,
            "director": "",
            "series": "",
            "label": "",
            "tags": [],
            "sample_images": [],
            "source": "javbus",
        }
        with (
            patch("os.path.exists", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal") as mock_submit,
        ):
            mock_repo = MagicMock()
            mock_existing = MagicMock()
            mock_existing.sample_images = []
            mock_existing.user_tags = []
            mock_existing.cover_path = ""
            mock_repo.get_by_path.return_value = mock_existing
            mock_repo_cls.return_value = mock_repo

            from core.enricher import enrich_single
            enrich_single(
                file_path="/tmp/SIRO-1234.mp4",
                number=number,
                mode="refresh_full",
                write_nfo=False,
                write_cover=True,
                write_extrafanart=False,
                overwrite_existing=True,
            )
        return mock_submit

    def test_rescrape_calls_focal_trigger(self):
        mock_submit = self._run_refresh()
        mock_submit.assert_called_once()
        args = mock_submit.call_args[0]
        # (number, maker, video_path_uri, cover_fs)
        assert args[0] == "SIRO-1234"
        assert args[1] == "SOD"
        assert args[2].startswith("file:///"), f"video_path_uri 應為 file:/// URI，得 {args[2]!r}"
        assert args[3].endswith(".jpg"), f"cover_fs 應為 .jpg 封面路徑，得 {args[3]!r}"

    def test_video_path_uri_matches_db_upsert_key(self):
        """helper 收到的 video_path_uri 必等於 _db_upsert 寫入 DB 的 key（防 silent-miss）。"""
        from core.path_utils import to_file_uri, uri_to_fs_path
        mock_submit = self._run_refresh()
        args = mock_submit.call_args[0]
        expected = to_file_uri(uri_to_fs_path("/tmp/SIRO-1234.mp4"))
        assert args[2] == expected, f"video_path_uri 應 == DB key {expected!r}，得 {args[2]!r}"


class TestEnrichPreserveCropModeE2E:
    """重刮路徑 preserve-on-conflict 端到端：先設 crop_mode='default' → metadata-only
    重刮（不換封面）→ 仍 default。

    write_cover=False（99a-T1b）：這條測的是 CD-10（`_db_upsert`→`upsert()` 的
    preserve-on-conflict CASE）端到端，需與 CD-4（`core/enricher.py` 的
    `reset_focal_to_auto`，只在 cover_written=True 才觸發、無條件把 crop_mode 降回
    'auto'）隔開，否則兩個機制的職責會疊在同一斷言上、測不出各自的邊界。cover_written=True
    的情境已由 `TestEnrichFocalReset` 覆蓋。"""

    def test_rescrape_preserves_user_crop_mode(self, tmp_path, seed_crop_mode):
        from unittest.mock import patch
        from core.database import init_db, VideoRepository, Video
        from core.path_utils import to_file_uri, uri_to_fs_path

        db_file = tmp_path / "focal_preserve.db"
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / "SIRO-1234.mp4"
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        db_key = to_file_uri(uri_to_fs_path(file_path))

        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number="SIRO-1234", title="Old", maker="SOD"))
        # 使用者選了 default（非 auto）
        assert seed_crop_mode(repo, db_key, "default") is True

        scraper_data = {
            "number": "SIRO-1234", "title": "New", "actors": [],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": "SOD", "director": "", "series": "", "label": "",
            "tags": [], "sample_images": [], "source": "javbus",
        }
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal"),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=file_path, number="SIRO-1234", mode="refresh_full",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.crop_mode == "default", f"重刮不應回退 crop_mode，得 {row.crop_mode!r}"
        assert row.title == "New", "重刮應更新非 preserve 欄位（title）"


class TestEnrichFocalReset:
    """99a-T1b CD-4：重刮實際寫入新封面時同步作廢手動焦點。

    `reset_focal_to_auto` + `maybe_submit_video_focal` 必須一起被 `if cover_written:`
    包住、reset 在 submit 之前——三個 mutation 鎖：
    - hoist reset 出 `if cover_written:` → cover_written=False 也清 manual → RED
      （`test_cover_written_false_preserves_manual`）。
    - reset/submit 順序對調 → submit 呼叫當下 crop_mode 仍是 manual → RED
      （`test_cover_written_true_reset_happens_before_submit`）。
    """

    _SCRAPER_DATA = {
        "number": "PLACEHOLDER", "title": "New", "actors": [],
        "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
        "maker": "SOD", "director": "", "series": "", "label": "",
        "tags": [], "sample_images": [], "source": "javbus",
    }

    def _seed_manual(self, tmp_path, db_name, number, video_name):
        from unittest.mock import patch
        from core.database import init_db, VideoRepository, Video
        from core.path_utils import to_file_uri, uri_to_fs_path

        db_file = tmp_path / db_name
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / video_name
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        db_key = to_file_uri(uri_to_fs_path(file_path))

        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number=number, title="Old", maker="SOD"))
        assert repo.update_manual_focal(db_key, "0.3000,0.6000", '') is True
        return repo, file_path, db_key

    def test_cover_written_true_reset_happens_before_submit(self, tmp_path):
        """cover_written=True：reset 必須在 submit 之前落地——用 side_effect 在 submit
        呼叫當下讀 DB 現況，若順序對調（submit 先跑）會讀到仍是 manual 的 stale 值。"""
        from unittest.mock import patch
        repo, file_path, db_key = self._seed_manual(
            tmp_path, "focal_reset_order.db", "SIRO-2001", "SIRO-2001.mp4"
        )

        captured = {}

        def _capture_submit(number, maker, video_path_uri, cover_fs, *, cover_path_uri, db_path=None):
            row = repo.get_by_path(video_path_uri)
            captured["crop_mode_at_submit"] = row.crop_mode
            captured["auto_focal_at_submit"] = row.auto_focal

        scraper_data = dict(self._SCRAPER_DATA, number="SIRO-2001")
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal", side_effect=_capture_submit),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=file_path, number="SIRO-2001", mode="refresh_full",
                write_nfo=False, write_cover=True, write_extrafanart=False,
                overwrite_existing=True,
            )

        assert captured, "cover_written=True 時 maybe_submit_video_focal 必須被呼叫"
        assert captured["crop_mode_at_submit"] == "auto", "reset 必須在 submit 之前落地"
        assert captured["auto_focal_at_submit"] == ""

        row = repo.get_by_path(db_key)
        assert row.crop_mode == "auto"
        assert row.auto_focal == ""

    def test_cover_written_false_preserves_manual(self, tmp_path):
        """cover_written=False（write_cover=False，只重寫 NFO、未覆蓋既有封面）→ 完全
        不進 reset/submit 分支，manual 原樣保留。"""
        from unittest.mock import patch
        repo, file_path, db_key = self._seed_manual(
            tmp_path, "focal_reset_cover_false.db", "SIRO-2002", "SIRO-2002.mp4"
        )

        scraper_data = dict(self._SCRAPER_DATA, number="SIRO-2002")
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=True),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal") as mock_submit,
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=file_path, number="SIRO-2002", mode="refresh_full",
                write_nfo=False, write_cover=False, write_extrafanart=False,
                overwrite_existing=True,
            )

        mock_submit.assert_not_called()
        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.crop_mode == "manual", "沒換圖，manual 必須原樣保留"
        assert row.auto_focal == "0.3000,0.6000"


# ── TASK-113b-T1：S3/S4 nfo_mtime TOCTOU 例外對齊 ────────────────────────────

class TestNfoMtimeS3S4ExceptionAlignment:
    """S3（`:527-528`，走刮削路徑寫 DB 時的 nfo_mtime stat）原本裸 `.stat()`，
    TOCTOU 視窗內 NFO 消失會讓整個 enrich_single 直接炸掉；S4（`:549-565`，
    fill-missing 路徑的獨立 nfo_mtime UPDATE）已有 `except Exception`，但範圍過寬
    （把 stat 與 DB 連線/寫入的失敗混在一起）。

    TASK-113b-T1：S3 的 `.stat()` 失敗映射為 `0.0`（沿用既有「NFO 不存在」語意，
    仍照樣呼叫 `_db_upsert`）；S4 的 stat 失敗整段跳過 UPDATE（不得折成 `0.0`
    再寫，DB 段 `except Exception` 的範圍不變）。兩處都要記 warning。

    裁決 1（Opus Step 2）：測試 1／7 的故障注入須 class 級同時 patch `Path.exists`
    （目標 `.nfo` 路徑回 True）與 `Path.stat`（目標路徑拋 `OSError`），非目標路徑
    一律委派原始方法——`Path.exists()` 內部就是呼叫 `self.stat()`，只 patch
    `Path.stat` 會讓 `.exists()` 連帶回 False（ENOENT 類）或重拋（EACCES 類），
    兩者都測不到被測分支；`Path` 有 `__slots__`，只能 class 級 patch。
    裁決 2：測試 3 用 `patch("core.enricher._db_upsert", wraps=...)` 斷言 S3 傳入的
    `nfo_mtime` kwarg（而非只看最終 DB 值——S4 是 S3 的 fill-missing 補網，只驗
    最終值測不出「S3 stat 提前」這類 mutation）。
    裁決 3：測試 4／6／7 的 S4 分支用「seed 一筆完整 DB row」建立（`path`/`number`
    對上、`_missing_fields` 八欄全非空），不用「完整 baseline NFO」——DB row 一旦
    存在，`:409` 的 `get_by_numbers` 會先命中，NFO 內容根本不會被讀到；且只有
    DB row 存在，S4 的 `UPDATE ... WHERE path = ?` 才有列可打。
    """

    _COMPLETE_KWARGS = dict(
        title="Old Title", original_title="Old Title",
        actresses=["女優A"], maker="SOD", director="監督A",
        series="シリーズA", label="LABEL", tags=["タグ"],
        release_date="2024-01-01", duration=120,
        cover_path="https://example.com/cover.jpg",
    )

    def _seed_env(self, tmp_path, db_name, number, video_name):
        """建立真 sqlite DB 檔（非 :memory:，理由見 TASK-113b-T1.md「現況分析 C」）
        + repo + 一支真實影片檔，回傳 (repo, file_path, nfo_file, db_key)。"""
        from core.database import init_db, VideoRepository
        from core.path_utils import to_file_uri, uri_to_fs_path

        db_file = tmp_path / db_name
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / video_name
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        nfo_file = video_file.with_suffix(".nfo")
        db_key = to_file_uri(uri_to_fs_path(file_path))
        return repo, file_path, nfo_file, db_key

    def _seed_complete_row(self, repo, db_key, number, nfo_mtime):
        """seed 一筆完整（`_missing_fields` 八欄全非空）DB row，`nfo_mtime` 用 raw
        UPDATE 顯式覆寫（`Video` dataclass 預設 0.0，upsert() 走一般路徑寫不出
        NULL；比照 conftest.seed_crop_mode 手法直接開連線 UPDATE）。
        BE-ENV-02：seed 一個不可能相等的舊值（如 12345.0）取代 time.sleep 撐 mtime 差異。
        """
        from core.database import Video, get_connection

        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number=number, **self._COMPLETE_KWARGS))

        conn = get_connection(repo.db_path)
        try:
            conn.execute(
                "UPDATE videos SET nfo_mtime = ? WHERE path = ?",
                (nfo_mtime, db_key),
            )
            conn.commit()
        finally:
            conn.close()

    def _toctou_context(self, target_path_str):
        """class 級 patch `Path.exists`（目標路徑回 True）＋ `Path.stat`（目標路徑
        拋 `OSError`），非目標路徑一律委派原始方法（裁決 1）。回傳可直接 `with` 的
        `ExitStack`。"""
        from contextlib import ExitStack

        orig_exists = Path.exists
        orig_stat = Path.stat

        def fake_exists(self_, *a, **kw):
            if str(self_) == target_path_str:
                return True
            return orig_exists(self_, *a, **kw)

        def fake_stat(self_, *a, **kw):
            if str(self_) == target_path_str:
                # 訊息文字刻意不含 "stat" 字面（避免洩漏進 caplog 的 "stat" 關鍵字
                # 斷言，讓斷言只認生產碼 warning 訊息本身有沒有講 "stat"，不是認
                # 例外字串本身）。
                raise OSError("injected TOCTOU disappearance (test)")
            return orig_stat(self_, *a, **kw)

        stack = ExitStack()
        stack.enter_context(patch("pathlib.Path.exists", new=fake_exists))
        stack.enter_context(patch("pathlib.Path.stat", new=fake_stat))
        return stack

    # ── 測試 1（plan #1）：NFO「存在」但 stat() 拋 OSError → S3（走刮削）────────

    def test_1_s3_stat_oserror_maps_to_zero_and_warns(self, tmp_path, caplog):
        import logging as _logging

        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s3_stat_error.db", "SIRO-3001", "SIRO-3001.mp4"
        )
        target = str(nfo_file)

        scraper_data = {
            "number": "SIRO-3001", "title": "New", "actors": ["女優B"],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": "SOD", "director": "監督B", "series": "シリーズB", "label": "LABEL",
            "tags": ["タグ"], "sample_images": [], "source": "javbus",
        }
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
            self._toctou_context(target),
            caplog.at_level(_logging.WARNING, logger="OpenAver.core.enricher"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3001", mode="fill_missing",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_called_once()
        assert result.success is True

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime == 0.0, f"stat 失敗應映射為 0.0，得 {row.nfo_mtime!r}"
        # 用 "stat" 關鍵字而非鬆散的 "nfo_mtime" OR 判斷：S4 既有的 DB 失敗 warning
        # （"nfo_mtime 更新失敗 (%s): %s"）也含 "nfo_mtime" 子字串，鬆散斷言在測試 7
        # 會對未修的舊碼假綠（見測試 7 同一理由的註解）。
        assert any("stat" in r.message for r in caplog.records), "S3 stat 失敗必須記 warning"

    # ── 測試 3（plan #3）：起初無 .nfo → enrich 真寫出 NFO → S3 傳給 _db_upsert 的
    # nfo_mtime 等於新檔 st_mtime（裁決 2：斷言傳入值，不只看最終 DB 值）────────

    def test_3_s3_passes_new_nfo_stmtime_to_db_upsert(self, tmp_path):
        from core.enricher import _db_upsert as _orig_db_upsert

        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s3_real_write.db", "SIRO-3003", "SIRO-3003.mp4"
        )
        assert not nfo_file.exists(), "測試 3 前提：一開始不應有 .nfo 檔"

        scraper_data = {
            "number": "SIRO-3003", "title": "New", "actors": ["女優C"],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": "SOD", "director": "監督C", "series": "シリーズC", "label": "LABEL",
            "tags": ["タグ"], "sample_images": [], "source": "javbus",
        }
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.enricher._db_upsert", wraps=_orig_db_upsert) as mock_db_upsert,
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3003", mode="fill_missing",
                write_nfo=True, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_called_once()
        assert result.success is True
        assert nfo_file.exists(), "測試 3 前提：enrich 過程要真的寫出 NFO（不 mock generate_nfo）"
        real_mtime = nfo_file.stat().st_mtime

        mock_db_upsert.assert_called_once()
        assert mock_db_upsert.call_args.kwargs["nfo_mtime"] == real_mtime, (
            "S3 傳給 _db_upsert 的 nfo_mtime 必須等於新寫出 .nfo 檔的 st_mtime"
        )
        assert mock_db_upsert.call_args.kwargs["nfo_mtime"] != 0.0

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime == real_mtime

    # ── 測試 4（plan #4）：NFO 存在且 DB nfo_mtime 為 NULL → S4 補值（回歸釘選）──

    def test_4_s4_fills_null_nfo_mtime(self, tmp_path):
        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s4_fill_null.db", "SIRO-3004", "SIRO-3004.mp4"
        )
        self._seed_complete_row(repo, db_key, "SIRO-3004", nfo_mtime=None)
        nfo_file.write_bytes(b"<movie></movie>")

        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3004", mode="fill_missing",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "db", "測試 4 前提：完整 DB row，不應落到刮削分支"

        expected_mtime = nfo_file.stat().st_mtime
        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime == expected_mtime
        assert row.nfo_mtime not in (0, 0.0, None)

    # ── 測試 5（plan #5）：NFO 存在且 DB 已有非 0 值 + 走刮削路徑 → S3 無條件覆寫
    # （回歸釘選；BE-ENV-02：seed 12345.0 不可能相等的舊值）───────────────────

    def test_5_s3_unconditionally_overwrites_existing_value(self, tmp_path):
        from core.database import Video, get_connection

        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s3_overwrite.db", "SIRO-3005", "SIRO-3005.mp4"
        )
        # 缺 director 欄位觸發刮削（不是裁決 3 的「完整 DB row」場景——這支測試要
        # 走 S3，不是 S4）
        incomplete_kwargs = dict(self._COMPLETE_KWARGS)
        incomplete_kwargs["director"] = ""
        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number="SIRO-3005", **incomplete_kwargs))
        conn = get_connection(repo.db_path)
        try:
            conn.execute("UPDATE videos SET nfo_mtime = ? WHERE path = ?", (12345.0, db_key))
            conn.commit()
        finally:
            conn.close()

        scraper_data = {
            "number": "SIRO-3005", "title": "New", "actors": ["女優D"],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": "SOD", "director": "監督D", "series": "シリーズD", "label": "LABEL",
            "tags": ["タグ"], "sample_images": [], "source": "javbus",
        }
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3005", mode="fill_missing",
                write_nfo=True, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_called_once()
        assert result.success is True
        assert nfo_file.exists()
        real_mtime = nfo_file.stat().st_mtime

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime == real_mtime
        assert row.nfo_mtime != 12345.0, "S3 無條件覆寫語意不變，12345.0 不應殘留"

    # ── 測試 6（plan #6）：NFO 存在且 DB 已有非 0 值 + 不走刮削 → S4 guard 擋下
    # （回歸釘選）──────────────────────────────────────────────────────────────

    def test_6_s4_guard_skips_nonzero_existing_value(self, tmp_path):
        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s4_guard_skip.db", "SIRO-3006", "SIRO-3006.mp4"
        )
        self._seed_complete_row(repo, db_key, "SIRO-3006", nfo_mtime=12345.0)
        nfo_file.write_bytes(b"<movie></movie>")

        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3006", mode="fill_missing",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "db", "測試 6 前提：完整 DB row，不應落到刮削分支"

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime == 12345.0, "非 0 舊值不應被 fill-missing guard 覆寫"

    # ── 測試 7（plan #7）：不走刮削 + DB nfo_mtime 為 NULL + stat() 拋 OSError →
    # S4 整段跳過（不得折成 0.0）────────────────────────────────────────────────

    def test_7_s4_stat_oserror_does_not_fold_null_to_zero(self, tmp_path, caplog):
        import logging as _logging

        repo, file_path, nfo_file, db_key = self._seed_env(
            tmp_path, "s4_stat_error.db", "SIRO-3007", "SIRO-3007.mp4"
        )
        self._seed_complete_row(repo, db_key, "SIRO-3007", nfo_mtime=None)
        target = str(nfo_file)

        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav") as mock_search,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
            self._toctou_context(target),
            caplog.at_level(_logging.WARNING, logger="OpenAver.core.enricher"),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number="SIRO-3007", mode="fill_missing",
                write_nfo=False, write_cover=False, write_extrafanart=False,
            )

        mock_search.assert_not_called()
        assert result.success is True

        row = repo.get_by_path(db_key)
        assert row is not None
        assert row.nfo_mtime is None, (
            f"stat 失敗必須整段跳過 UPDATE，NULL 不可被折成 0.0，得 {row.nfo_mtime!r}"
        )
        # 用 "stat" 關鍵字而非鬆散的 "nfo_mtime" OR 判斷：未修的舊碼 S4 用同一個
        # except Exception 吞掉 stat 失敗，warning 文字是既有的 DB 失敗訊息
        # （"nfo_mtime 更新失敗 (%s): %s"，同樣含 "nfo_mtime" 子字串但不含 "stat"）——
        # 只斷言 "nfo_mtime" 會在舊碼上也命中，測不出 T1 把 stat 失敗獨立成專屬
        # warning 這件事（NULL 不折成 0.0 這件事本身舊碼「碰巧」已經正確，S4 這裡
        # 是「把 stat 失敗來源與 DB 失敗來源分開處理」的例外面對齊，不是行為修復；
        # 用 "stat" 關鍵字鎖住「有沒有專屬 stat warning」才是這支測試真正在守的事）。
        assert any("stat" in r.message for r in caplog.records), "S4 stat 失敗必須記 warning"


# ── 99b-T2 DoD ④: caller #4（enricher）namespace 真 DB 鎖 ───────────────────

class TestEnrichFocalCoverPathUriNamespace:
    """cover_path_uri 傳給 maybe_submit_video_focal 的值必須實際等於 _db_upsert
    剛寫入 DB 的 cover_path（同一運算式 to_file_uri(local_cover, path_mappings)
    作用在同一變數，CD-99b-5「低風險」評級由 code identity 保證，仍須真 DB 鎖驗證，
    非只憑「程式碼看起來一樣」免驗）。

    download_image 的 side_effect 必須真的把檔案寫到 local_cover 路徑——
    `_db_upsert` 的 `cover_uri` 計算是 `if local_cover_path and
    os.path.exists(local_cover_path)`（:624），若 mock 只回傳 True 不寫實體檔，
    `_db_upsert` 會落 else 分支保留 DB 既有 cover_path（此處為空字串），造成假陽性
    ——測試看起來測了「同源」，實際上驗的是兩個空字串巧合相等。
    """

    def _write_fake_cover(self, url, path):
        from pathlib import Path
        Path(path).write_bytes(b"x")
        return True

    def test_cover_path_uri_matches_db_cover_path_with_nonempty_mappings(self, tmp_path):
        """DoD ④ 核心：cover_path_uri == DB 剛寫入的 cover_path，commit 命中非 0 列。
        mutation：故意傳反解後的 FS path 當 cover_path_uri → 真 DB 下 update_auto_focal
        影響 0 列 → RED（見 test_cover_path_uri_reversed_fs_path_causes_commit_miss）。
        WSL 綠≠CI 綠：mapping 實際轉換的斷言 gate 進 if CURRENT_ENV == 'wsl'。"""
        from unittest.mock import patch
        from core.database import init_db, VideoRepository, Video
        from core.path_utils import CURRENT_ENV, to_file_uri, uri_to_fs_path

        db_file = tmp_path / "focal_cd99b_enricher_namespace.db"
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / "SIRO-3001.mp4"
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        db_key = to_file_uri(uri_to_fs_path(file_path))

        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number="SIRO-3001", title="Old", maker="SOD"))

        # 非空 path_mappings（WSL 環境下對 to_file_uri 有實際轉換效果，gotchas-backend #11）
        path_mappings = {str(tmp_path): "Z:/lib"}

        scraper_data = dict(TestEnrichFocalReset._SCRAPER_DATA, number="SIRO-3001")
        captured = {}

        def _capture_submit(number, maker, video_path_uri, cover_fs, *, cover_path_uri, db_path=None):
            captured["cover_path_uri"] = cover_path_uri

        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", side_effect=self._write_fake_cover),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal", side_effect=_capture_submit),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=file_path, number="SIRO-3001", mode="refresh_full",
                write_nfo=False, write_cover=True, write_extrafanart=False,
                overwrite_existing=True, path_mappings=path_mappings,
            )

        assert captured, "cover_written=True 時 maybe_submit_video_focal 必須被呼叫"
        row = repo.get_by_path(db_key)
        assert row is not None

        if CURRENT_ENV == 'wsl':
            # WSL 環境：確認 mapping 真的生效（非 trivial identity）
            assert captured["cover_path_uri"] != to_file_uri(str(video_file.with_suffix(".jpg")), {}), \
                "path_mappings 應實際轉換 URI，否則非有效非空情境"

        # 平台無關核心契約：cover_path_uri 實際等於 DB 剛寫入的 cover_path（同源）
        assert captured["cover_path_uri"] == row.cover_path, (
            f"cover_path_uri({captured['cover_path_uri']!r}) 應等於 DB cover_path"
            f"({row.cover_path!r})，否則 namespace 對不上，commit 會 silent-miss"
        )

        # commit 命中非 0 列（真 DB mutation 驗證核心契約）
        assert repo.update_auto_focal(db_key, "0.5,0.5", captured["cover_path_uri"]) is True

    def test_cover_path_uri_reversed_fs_path_causes_commit_miss(self, tmp_path):
        """namespace 守衛效力自證：若誤傳反解後的 FS path（而非 DB-key URI）當
        expected_cover_path，真 DB 下 update_auto_focal 必須影響 0 列。"""
        from unittest.mock import patch
        from core.database import init_db, VideoRepository, Video
        from core.path_utils import to_file_uri, uri_to_fs_path, uri_to_local_fs_path

        db_file = tmp_path / "focal_cd99b_enricher_namespace_mutation.db"
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        video_file = tmp_path / "SIRO-3002.mp4"
        video_file.write_bytes(b"x")
        file_path = str(video_file)
        db_key = to_file_uri(uri_to_fs_path(file_path))

        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.upsert(Video(path=db_key, number="SIRO-3002", title="Old", maker="SOD"))

        path_mappings = {str(tmp_path): "Z:/lib"}
        scraper_data = dict(TestEnrichFocalReset._SCRAPER_DATA, number="SIRO-3002")
        captured = {}

        def _capture_submit(number, maker, video_path_uri, cover_fs, *, cover_path_uri, db_path=None):
            captured["cover_path_uri"] = cover_path_uri

        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", side_effect=self._write_fake_cover),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.focal_trigger.maybe_submit_video_focal", side_effect=_capture_submit),
            patch("core.similar.ranker_cache.SimilarRankerCache"),
        ):
            from core.enricher import enrich_single
            enrich_single(
                file_path=file_path, number="SIRO-3002", mode="refresh_full",
                write_nfo=False, write_cover=True, write_extrafanart=False,
                overwrite_existing=True, path_mappings=path_mappings,
            )

        # 故意用反解後的 FS path 當 expected（模擬「誤傳」的 mutation）
        wrong_expected = uri_to_local_fs_path(captured["cover_path_uri"], path_mappings)
        assert wrong_expected != captured["cover_path_uri"], (
            "測試前提：反解後的 FS path 必須與 DB-key URI 不同字串，否則此 mutation "
            "測試無意義（若這條 assert 失敗，代表本機環境的 to_file_uri/uri_to_local_fs_path "
            "在此路徑下是 no-op，需換一組會實際轉換的 path_mappings）"
        )
        assert repo.update_auto_focal(db_key, "0.6,0.6", wrong_expected) is False


# ============ 站2接線測試 (TASK-101a-T2 DoD①④) ============

_T2_FOCAL_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "actress_photos"


def _t2_write_face_cover(cover_path):
    src = _T2_FOCAL_FIXTURES_DIR / "wide_offcenter_face.jpg"
    Path(cover_path).write_bytes(src.read_bytes())


def _t2_oracle_poster_bytes(focal_xy):
    """獨立 oracle：不經過 crop_to_poster / _write_external_images / enrich_single，
    直接呼叫底層 primitive 算出「應該要平移到焦點」的期望 bytes。不可用「呼叫同一站
    流程兩次自我比對」（gotchas-backend.md #9，101a-T1 已踩過）。

    TASK-102c-T1：改吃 focal_xy 參數，不再自己呼叫真 detect_focal——呼叫端須確保
    patch `core.organizer.detect_focal` 用同一個值，否則 production 端與 oracle 端
    會對不上。
    """
    from core.organizer import _poster_window_ratio
    from core.focal import crop_image_position
    from PIL import Image

    fixture_path = _T2_FOCAL_FIXTURES_DIR / "wide_offcenter_face.jpg"
    with Image.open(fixture_path) as img:
        w, h = img.size
    r_window = _poster_window_ratio(w, h)
    assert r_window is not None
    focal = focal_xy
    with Image.open(fixture_path) as img:
        expected_cropped = crop_image_position(img.convert("RGB"), r_window, focal[0])
    buf = io.BytesIO()
    expected_cropped.save(buf, "JPEG", quality=95, subsampling=0)
    return buf.getvalue()


class TestEnrichSingleStationWiring:
    """DoD①：站2（core/enricher.py enrich_single → _write_external_images →
    crop_to_poster）接線——真跑 enrich_single()（external_manager='jellyfin'），
    不 mock crop_to_poster / _write_external_images 本身（唯一沒有既有 patch 範本
    的一站，見 plan §C-4）。fixture A（番號驅動）/ B（maker-only 驅動）各一次，
    poster bytes 對獨立 oracle。
    """

    _FIXTURE_A = {"number": "FC2-1234567", "maker": "S1 NO.1 STYLE"}
    _FIXTURE_B = {"number": "SSIS-001", "maker": "10musume"}

    def _run_station2(self, tmp_path, tag, fixture):
        mp4 = tmp_path / f"{fixture['number']}_{tag}.mp4"
        mp4.touch()
        cover = mp4.with_suffix(".jpg")
        _t2_write_face_cover(cover)

        mock_repo = MagicMock()
        mock_repo.get_by_numbers.return_value = {
            fixture["number"]: [_make_video(number=fixture["number"], maker=fixture["maker"])]
        }
        mock_repo.get_by_path.return_value = None

        with (
            patch("core.enricher.VideoRepository", return_value=mock_repo),
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", return_value=False),
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("core.organizer.detect_focal", return_value=MOCK_FOCAL_XY),
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(mp4),
                number=fixture["number"],
                mode="db_to_sidecar",
                write_nfo=True,
                write_cover=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is True, f"enrich_single 失敗: {result.error}"
        poster_path = mp4.with_name(mp4.stem + "-poster.jpg")
        assert poster_path.exists(), "station2 應產生 poster"
        expected = _t2_oracle_poster_bytes(MOCK_FOCAL_XY)
        assert poster_path.read_bytes() == expected, "station2 poster 應對準焦點（獨立 oracle 比對）"

    def test_station2_fixture_a(self, tmp_path):
        self._run_station2(tmp_path, "a", self._FIXTURE_A)

    def test_station2_fixture_b(self, tmp_path):
        self._run_station2(tmp_path, "b", self._FIXTURE_B)


# ══════════════════════════════════════════════════════════════════════════════
# 112b-T5：真理表 Table 1 #2/#3/#4/#4b/#5/#6 直接鎖 ＋ ⑤⑥⑦ 專屬守衛 ＋ AC5/AC6/AC8
#
# 對齊 feature/112-cover-canonical-position/TASK-112b-T5.md。fixture 三條件
# （task card §C／Opus 追加要求 #2，形狀照抄
# tests/unit/test_cover_canonical_contract.py:1016-1033 的 `_seed_bare_tracked_row`
# ——讀它、照著寫，**不 import**，該檔案頭明文「本檔案私有」）：
#   1. DB 種一筆 tracked row（key 存在，`cover_path` 依情境需要顯式帶入，見各
#      測試 docstring）
#   2. 留白 `_FILL_MISSING_REQUIRED` 欄位 → `_missing_fields` 非空 →
#      `search_jav` 真的被呼叫 → `source_used` 落在 scraper 值 → `_db_upsert`
#      閘門為 True（不留白會讓 DB 斷言變成零訊號的空頭支票，本卡 §A-2 追出的
#      `source_used` 陷阱，比 `BE-DATA-07` 更上游）
#   3. `search_jav` mock 回非空 meta（含 cover URL）
# 每一支 DB 測試額外斷言 `ctx.mock_search.called`（Opus 追加要求 #3：fixture
# 沒設對就炸，不是靜默恆真）。
# ══════════════════════════════════════════════════════════════════════════════

def _t5_write_jpeg(path, size=(300, 200), color=(128, 64, 32)) -> None:
    """真 JPEG（PIL）。假 bytes（`b"fake"`）會讓 crop_to_poster 靜默回 False，
    poster 斷言測不到東西（§E 假綠風險 #1）。"""
    from PIL import Image
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(str(path), "JPEG", quality=95)


def _t5_jpeg_bytes(size=(300, 200), color=(200, 100, 50)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _t5_download_image_side_effect(content: bytes):
    """供 `patch("core.enricher.download_image", side_effect=...)`：真的把
    bytes 寫進 save_path 並回 True，讓後續 crop_to_poster／位元組斷言吃得到
    真實內容。**patch target 必須是 `core.enricher.download_image`**（值匯入
    到 enricher 模組命名空間，patch `core.organizer.download_image` 對它無效，
    §E 假綠風險 #4）。"""
    def _side_effect(url, save_path, referer=""):
        Path(save_path).write_bytes(content)
        return True
    return _side_effect


def _t5_read_nfo_tags(nfo_path) -> dict:
    from xml.etree import ElementTree as ET
    root = ET.parse(str(nfo_path)).getroot()
    return {
        "poster": root.findtext("poster") or "",
        "thumb": root.findtext("thumb") or "",
        "fanart": root.findtext("fanart") or "",
    }


def _t5_assert_nfo_tags_exist(nfo_path, expect_exists: dict) -> dict:
    """讀 NFO 三個 tag，逐一斷言其指向的檔案在 NFO 所在目錄下是否存在
    （只驗『指得到』不驗『字面值』的呼叫端另外自行比對字面值，§E 假綠風險 #3：
    只驗存在不驗字面值/只驗字面值不驗存在都不夠）。"""
    tags = _t5_read_nfo_tags(nfo_path)
    nfo_dir = Path(nfo_path).parent
    for key, expected in expect_exists.items():
        target = nfo_dir / tags[key]
        actual = target.exists()
        assert actual == expected, (
            f"NFO <{key}> = {tags[key]!r}（{target}），exists()={actual}，預期 {expected}"
        )
    return tags


def _t5_scraper_data(number):
    return {
        "number": number, "title": "T5 Scraper Title", "actors": ["T5 Actress"],
        "cover": "http://example.com/t5-cover.jpg", "date": "2024-05-01",
        "maker": "T5Maker", "director": "T5 Dir", "series": "T5 Series",
        "label": "T5Lab", "tags": ["t5tag"], "sample_images": [],
        "source": "javbus",
    }


def _t5_seed_tracked_row(repo, db_key, number, cover_path=""):
    """DB 已追蹤此片（key 存在）——**不是**「DB 裡沒有這片」。`_merge_meta`
    的 cover_url 合併判斷（`core/enricher.py:146`，`merged.get("cover_url")
    == ""`）在 key 不存在時恆假，會讓 scraper 的封面 URL 永遠合併不進去
    （`BE-DATA-07`）。其餘 `_FILL_MISSING_REQUIRED` 欄位（title/actresses/
    maker/director/series/label/tags/release_date）全部靠 `Video` dataclass
    預設值留白 → `_missing_fields` 保證非空 → `search_jav` 保證被呼叫 →
    `source_used` 落在 scraper 值 → `_db_upsert` 閘門為 True（Opus 追加
    要求 #2）。`cover_path` 依情境需要顯式帶入：留空＝DB 尚未追蹤任何既有
    封面（沿用 test_cover_canonical_contract.py B-jf-4 的理由：避免磁碟上
    孤兒檔案的 URI 干擾 cover_url 合併判斷）；帶入既有檔案的 URI＝這片已被
    追蹤過同一張封面（用於「DB cover_path 不變」的非平凡驗證，見各測試
    docstring）。"""
    from core.database import Video
    repo.upsert(Video(path=db_key, number=number, cover_path=cover_path))


def _t5_run(tmp_path, db_name, *, number, external_manager, video_name=None,
            overwrite_existing=False, pre_stage=None, download_content=None,
            capture=None):
    """T5 共用 fixture 骨架：真 DB + patch `VideoRepository` 綁 tmp db
    （`get_db_path()` 硬編碼 repo-root、不讀 config ⇒ `temp_config_path` 對它
    無效）+ 真 `search_jav` mock（非空 meta）+ patch `core.enricher.download_image`
    真的落地寫檔（不需要另外 mock `requests.get`：`crop_to_poster` 純讀本地
    檔案，沒有網路呼叫，見 task card §B 讀碼）。"""
    from core.database import init_db, VideoRepository
    from core.path_utils import to_file_uri as _to_file_uri, uri_to_fs_path

    if capture is None:
        capture = {}

    video_dir = tmp_path / f"{db_name}_video"
    video_dir.mkdir()
    video_file = video_dir / (video_name or f"{number}.mp4")
    video_file.write_bytes(b"video-bytes")
    file_path = str(video_file)
    db_key = _to_file_uri(uri_to_fs_path(file_path))

    db_file = tmp_path / f"{db_name}.db"
    init_db(db_file)
    repo = VideoRepository(db_path=db_file)

    if pre_stage is not None:
        pre_stage(repo, video_dir, db_key, number, capture)

    scraper_data = _t5_scraper_data(number)
    content = download_content if download_content is not None else _t5_jpeg_bytes()
    with (
        patch("core.enricher.VideoRepository", return_value=repo),
        patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
        patch("core.enricher.download_image",
              side_effect=_t5_download_image_side_effect(content)) as mock_download,
    ):
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=file_path, number=number, mode="fill_missing",
            write_nfo=True, write_cover=True, write_extrafanart=False,
            overwrite_existing=overwrite_existing, external_manager=external_manager,
        )
    return SimpleNamespace(
        result=result, repo=repo, db_key=db_key, video_dir=video_dir,
        video_file=video_file, mock_search=mock_search, mock_download=mock_download,
        capture=capture,
    )


class TestTable1Row2ExistingFullPreservedAC6:
    """真理表 Table 1 #2（AC8 + AC1b-1）＋ AC6：jellyfin + 既有 `{stem}.jpg`
    完整（含衍生圖）+ ovw=False → `download_image` 零呼叫、DB cover_path 與
    crop_mode/auto_focal 操作前後完全相同；既有封面 bytes/mtime 完全不變
    （AC6，`BE-TEST-10`：基準值在操作**之前**取得）。"""

    def test_preserve_no_download_db_and_focal_unchanged(self, tmp_path, seed_crop_mode):
        number = "T5ROW2-001"

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _t5_write_jpeg(cover, color=(11, 12, 13))
            _t5_write_jpeg(video_dir / f"{stem}-poster.jpg", color=(21, 22, 23))
            _t5_write_jpeg(video_dir / f"{stem}-fanart.jpg", color=(31, 32, 33))
            cover_uri = to_file_uri(str(cover))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=cover_uri)
            assert seed_crop_mode(repo, db_key, "manual") is True
            capture["cover_uri"] = cover_uri
            capture["before_bytes"] = cover.read_bytes()
            capture["before_mtime"] = cover.stat().st_mtime

        ctx = _t5_run(tmp_path, "t5_row2", external_manager="jellyfin", number=number,
                       pre_stage=_stage)
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"

        ctx.mock_download.assert_not_called()  # AC8：preserve 命中 → 零下載

        # AC6：既有封面 bytes/mtime 操作前後完全相同（基準值在操作之前取得）
        assert cover.read_bytes() == ctx.capture["before_bytes"]
        assert cover.stat().st_mtime == ctx.capture["before_mtime"]

        # 衍生圖 gate 是磁碟真相，既有衍生圖原樣算數（不重生）
        assert poster.exists() and fanart.exists()

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        # <thumb> 改用既有 fanart_tag 變數（CD-112-5，core/organizer.py:755），
        # has_fanart=True 時字面值恆為 {stem}-fanart.jpg——與「正典封面仍是
        # {stem}.jpg」正交，不是「thumb 沿用 canonical cover 位置」（實測更正
        # task card §D 表格原先「== {stem}.jpg」的預測，見 T5 §F 記錄）。
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == ctx.capture["cover_uri"], "DB cover_path 操作前後完全相同"  # 真理表 Table 1 #2
        assert row.crop_mode == "manual", "AC1b-1：crop_mode 操作前後完全相同"
        assert row.auto_focal == ""


class TestTable1Row3ExistingMissingDerivativesBackfilled:
    """真理表 Table 1 #3（AC1b-1 衍生圖邊界）：jellyfin + 既有 `{stem}.jpg`
    但**缺衍生圖** + ovw=False → cover 本身仍 preserve（零下載），但衍生圖
    gate 是磁碟真相（`cover_path.exists()`，`core/enricher.py:280-303`），
    與 preserve 無關 → **會補**。這格證明 AC1b-1 的承諾是「不動正典封面」
    而不是「不寫任何檔」。"""

    def test_derivatives_backfilled_cover_preserved(self, tmp_path, seed_crop_mode):
        number = "T5ROW3-001"

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _t5_write_jpeg(cover, color=(41, 42, 43))
            cover_uri = to_file_uri(str(cover))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=cover_uri)
            assert seed_crop_mode(repo, db_key, "manual") is True
            capture["cover_uri"] = cover_uri
            capture["before_bytes"] = cover.read_bytes()

        ctx = _t5_run(tmp_path, "t5_row3", external_manager="jellyfin", number=number,
                       pre_stage=_stage)
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"

        ctx.mock_download.assert_not_called()  # cover 本身仍走 preserve
        assert cover.read_bytes() == ctx.capture["before_bytes"]
        assert poster.exists() and fanart.exists(), "衍生圖 gate 看磁碟 cover_path.exists()，會補"  # 真理表 Table 1 #3

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        # <thumb> = fanart_tag（CD-112-5），has_fanart=True → 恆 {stem}-fanart.jpg
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == ctx.capture["cover_uri"], "DB cover_path 不變"
        assert row.crop_mode == "manual", "焦點不清"
        assert row.auto_focal == ""


class TestTable1Row4ExistingFanartOnlyNotOverwritten:
    """真理表 Table 1 #4（差異最大格）：jellyfin + 既有 `{stem}-fanart.jpg`
    （**無**同名 `.jpg`）+ ovw=False → `resolve_cover_target` 第②步認得
    fanart 候選 → 不下載、不寫第二份底圖、DB 不變、焦點不清、三 tag 皆指
    得到。**T3 之前這裡會下載出第二份 `{stem}.jpg`**（改動前後差異最大的
    一格，見 task card §B「#4」）。

    DB `cover_path` 刻意留空（不指向這張磁碟上既有的孤兒 fanart）——理由
    照抄 `test_cover_canonical_contract.py::test_B_jf_4_...` 的 docstring：
    避免其 URI 干擾 `_merge_meta` 的 cover_url 合併判斷。"""

    def test_fanart_layout_preserved_no_second_cover(self, tmp_path, seed_crop_mode):
        number = "T5ROW4-001"

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            fanart = video_dir / f"{stem}-fanart.jpg"
            _t5_write_jpeg(fanart, color=(51, 52, 53))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path="")
            assert seed_crop_mode(repo, db_key, "manual") is True
            capture["before_bytes"] = fanart.read_bytes()

        ctx = _t5_run(tmp_path, "t5_row4", external_manager="jellyfin", number=number,
                       pre_stage=_stage)
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"

        ctx.mock_download.assert_not_called()  # 真理表 Table 1 #4：preserve 命中，① 是→否
        assert not cover.exists(), "不應多寫出第二份 {stem}.jpg 底圖"
        assert fanart.read_bytes() == ctx.capture["before_bytes"], "既有 fanart 不被觸碰"
        assert poster.exists(), "衍生圖 gate 是磁碟真相，poster 仍會補（沿用既有 fanart 當來源）"

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == "", "DB cover_path 不變"
        assert row.crop_mode == "manual", "cover_written=False → 不清焦點"
        assert row.auto_focal == ""


class TestTable1Row4bExistingFanartOnlyOverwritten:
    """真理表 Table 1 #4b（PR1 期間補入）：jellyfin + 既有 `{stem}-fanart.jpg`
    + **ovw=True**（齒輪重刮）→ 封面覆寫回 `-fanart.jpg`（`resolve_cover_target`
    第②步命中仍是同一個檔）、fanart 走 ⑥ preflight 同檔保護
    （`same_target_verdict` 的 `src == dst` 字串相等短路）→ `fanart_ok=True`，
    NFO 兩 tag 指得到。

    DB `cover_path` 這格的「不變」是**重算後剛好相同**，不是「保留舊值」
    （task card §B「#4b」）——fixture 因此把 DB 既有值刻意設成與「重算後的值」
    相同（模擬這片已被追蹤過同一張封面），才能驗到「不變」而不是巧合。

    crop_mode 被重置為 `auto`——**鎖的是改動前就有的行為（CD-112-14），不是
    112 的承諾**（R8，Opus 追加要求 #5）：`cover_written=True` 時
    `schedule_focal_after_cover_write` 無條件觸發，本 branch 一行都沒改這條
    規則。測試方法名稱刻意不用 `preserves_focal` 這種會被誤讀成承諾的字眼。
    """

    def test_overwrite_true_rewrites_same_fanart_legacy_focal_reset_cd_112_14(
        self, tmp_path, seed_crop_mode
    ):
        number = "T5ROW4B-001"
        old_content = (61, 62, 63)
        new_content = (200, 201, 202)

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            fanart = video_dir / f"{stem}-fanart.jpg"
            _t5_write_jpeg(fanart, color=old_content)
            cover_uri = to_file_uri(str(fanart))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=cover_uri)
            assert seed_crop_mode(repo, db_key, "manual") is True
            capture["cover_uri"] = cover_uri

        ctx = _t5_run(tmp_path, "t5_row4b", external_manager="jellyfin", number=number,
                       overwrite_existing=True, pre_stage=_stage,
                       download_content=_t5_jpeg_bytes(color=new_content))
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        cover = ctx.video_dir / f"{stem}.jpg"

        ctx.mock_download.assert_called_once()  # ovw=True → 不 preserve → 真的覆寫，① 恆是
        assert not cover.exists(), "正典仍是 fanart，不應多出同名 .jpg"
        assert fanart.read_bytes() == _t5_jpeg_bytes(color=new_content), "覆寫成新下載內容"

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == ctx.capture["cover_uri"], (
            "DB cover_path 值不變——重算後剛好相同，不是保留舊值（見 task card §B「#4b」）"
        )  # 真理表 Table 1 #4b
        assert row.crop_mode == "auto", (
            "cover_written=True → 無條件 reset。這是改動前就有的行為（CD-112-14），"
            "不是 112 的承諾（R8）"
        )
        assert row.auto_focal == ""


class TestTable1Row5ExistingFullOverwritten:
    """真理表 Table 1 #5（AC1b-2 核心）：jellyfin + 既有 `{stem}.jpg` +
    **ovw=True** → 覆寫回同一個檔名、DB cover_path 字面值不變（重算後相同）、
    crop_mode 被重置。**焦點重置鎖的是改動前就有的行為（CD-112-14），不是
    112 的承諾**（R8，Opus 追加要求 #5）——測試方法名稱刻意不用
    `preserves_focal` 這種會被誤讀成承諾的字眼。"""

    def test_overwrite_true_rewrites_same_name_legacy_focal_reset_cd_112_14(
        self, tmp_path, seed_crop_mode
    ):
        number = "T5ROW5-001"
        old_content = (71, 72, 73)
        new_content = (210, 211, 212)

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _t5_write_jpeg(cover, color=old_content)
            cover_uri = to_file_uri(str(cover))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=cover_uri)
            assert seed_crop_mode(repo, db_key, "manual") is True
            capture["cover_uri"] = cover_uri

        ctx = _t5_run(tmp_path, "t5_row5", external_manager="jellyfin", number=number,
                       overwrite_existing=True, pre_stage=_stage,
                       download_content=_t5_jpeg_bytes(color=new_content))
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"

        ctx.mock_download.assert_called_once()
        assert cover.read_bytes() == _t5_jpeg_bytes(color=new_content), "覆寫回同一個檔名，內容是新下載的圖"  # 真理表 Table 1 #5

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        # <thumb> = fanart_tag（CD-112-5），has_fanart=True → 恆 {stem}-fanart.jpg
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == ctx.capture["cover_uri"], "DB cover_path 字面值不變（同一路徑）"
        assert row.crop_mode == "auto", (
            "cover_written=True → 無條件 reset（既有行為，非 112 承諾，R8）"
        )
        assert row.auto_focal == ""


class TestTable1Row6RangeOutExtensionStillDownloads:
    """真理表 Table 1 #6（認定範圍外）：jellyfin + 既有 `{stem}.png` +
    ovw=False → preserve 判斷只探 `.jpg` 家族（CD-112-3b）→ `.png` 不算
    「已有封面」→ 下載，但落在 `-fanart.jpg`（不是 `{stem}.jpg`）。**「是否
    重新產生」不變、「產到哪」變**（plan-112b.md §3.3 第一條，不得寫成逐
    位元組相同）。"""

    def test_png_not_recognized_downloads_to_fanart(self, tmp_path, seed_crop_mode):
        number = "T5ROW6-001"
        new_content = (220, 221, 222)

        def _stage(repo, video_dir, db_key, number_, capture):
            stem = number_
            cover_png = video_dir / f"{stem}.png"
            _t5_write_jpeg(cover_png, color=(81, 82, 83))
            cover_uri = to_file_uri(str(cover_png))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=cover_uri)
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = _t5_run(tmp_path, "t5_row6", external_manager="jellyfin", number=number,
                       pre_stage=_stage, download_content=_t5_jpeg_bytes(color=new_content))
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行 → 下面的 DB 斷言恆空"
        )

        stem = ctx.video_file.stem
        cover_png = ctx.video_dir / f"{stem}.png"
        cover_jpg = ctx.video_dir / f"{stem}.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"

        ctx.mock_download.assert_called_once()  # 真理表 Table 1 #6：① 下載=是
        assert not cover_jpg.exists(), "canonical 是 -fanart.jpg，不是 {stem}.jpg"
        assert fanart.exists(), "② 位置=-fanart"
        assert fanart.read_bytes() == _t5_jpeg_bytes(color=new_content)
        assert cover_png.exists(), ".png 原檔不被清理"

        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"

        row = ctx.repo.get_by_path(ctx.db_key)
        expected_cover_uri = to_file_uri(str(fanart))
        assert row.cover_path == expected_cover_uri, "③ 記帳=改變（指向新的 -fanart.jpg）"
        assert row.crop_mode == "auto", "④ 焦點重置"


class TestWriteExternalImagesStemDerivationDirectLock:
    """CD-112b-3 直接鎖：`_write_external_images` 用**影片 stem**組
    poster/fanart 路徑，不從 `cover_path` 反向推導。

    **fixture 必須讓 `resolve_cover_target` 走第①步（同名候選命中），不是
    第③步（flavour 新建）**——這是本卡 Opus 回合追出的精確邊界（`BE-TEST-11`
    在本卡的第五次命中）：`cover_base_stem` 與 `Path(fs_path).with_suffix("")`
    兩種推導方式**只在第①步命中時分歧**。若磁碟全空、resolve 走第③步新建
    fanart 候選（`base_stem + "-fanart.jpg"`），`cover_base_stem` 反推該值時
    剝一次 `-fanart` 尾碼**剛好還原回 `base_stem`**，與 fs 路徑推導結果逐字
    相同——此時兩種推導方式數學上等價，mutation 測不出分歧（已實測驗證，
    見下方 class docstring 的 mutation 記錄）。

    真正會分歧的情境（CD-112b-3 原文 plan-112b.md §2.5 唯一舉的例子）：
    影片檔名 `my-fanart.mp4` **且磁碟上已有同名封面 `my-fanart.jpg`**
    （非空、first-time-generation）→ `resolve_cover_target` 第①步命中，回傳
    `.../my-fanart.jpg`；`cover_base_stem(".../my-fanart.jpg")` 剝 `.jpg` →
    `my-fanart` → 剝一次尾端 `-fanart` → **誤剝成 `my`**（把檔名本身自帶的
    `-fanart` 尾碼當成後綴標記剝掉），而 `Path(fs_path).with_suffix("")`
    正確給出 `my-fanart`。**只有這個情境的 fixture 才踩得到 CD-112b-3 否決
    `cover_base_stem` 的理由**，本卡因此把既有 fixture（磁碟全空、走第③步）
    改成「既有同名封面存在、走第①步」。

    正確作法（無論磁碟空或有同名封面）衍生圖仍落在
    `my-fanart-poster.jpg` / `my-fanart-fanart.jpg`（＝改動前行為，不是
    `my-poster.jpg`）。"""

    def test_video_named_like_fanart_suffix_no_double_suffix(self, tmp_path):
        number = "MYFAN-001"

        def _stage(repo, video_dir, db_key, number_, capture):
            # 既有同名封面 my-fanart.jpg（真 JPEG，非 b"fake"）→ 逼
            # resolve_cover_target 走第①步命中，才能讓 cover_base_stem 與
            # fs-derived base_stem 兩種推導方式產生分歧（見 class docstring）。
            cover = video_dir / "my-fanart.jpg"
            _t5_write_jpeg(cover, color=(101, 102, 103))
            _t5_seed_tracked_row(repo, db_key, number_, cover_path=to_file_uri(str(cover)))

        ctx = _t5_run(tmp_path, "t5_cd112b3", external_manager="jellyfin", number=number,
                      video_name="my-fanart.mp4", pre_stage=_stage)
        assert ctx.mock_search.called, (
            "fixture 沒逼出 search_jav → _db_upsert 不會執行"
        )

        video_dir = ctx.video_dir
        # resolve_cover_target 第①步命中同名 → canonical 仍是 my-fanart.jpg
        # （preserve 命中，零下載）；⑤ 鎖的是「poster/fanart 路徑用 fs stem
        # 直接組」，與 canonical 本身是不是 fanart 佈局正交。
        cover = video_dir / "my-fanart.jpg"
        fanart = video_dir / "my-fanart-fanart.jpg"
        poster = video_dir / "my-fanart-poster.jpg"
        # cover_base_stem(".../my-fanart.jpg") 誤剝成 ".../my"（見 class
        # docstring）→ 若走反向推導，poster 會落在錯誤的 "my-poster.jpg"，
        # fanart_path 則會與 cover_path 字串相等（"my-fanart.jpg"）觸發同檔
        # 短路而完全不產生 my-fanart-fanart.jpg。
        bogus_poster = video_dir / "my-poster.jpg"

        assert cover.exists(), "既有同名封面 preserve 命中，canonical 不變"
        ctx.mock_download.assert_not_called()
        assert fanart.exists(), "衍生 fanart 落在 my-fanart-fanart.jpg（fs stem 直接組）"
        assert poster.exists(), "衍生 poster 落在 my-fanart-poster.jpg（fs stem 直接組）"
        assert not bogus_poster.exists(), (
            "不得走 cover_base_stem 反向推導誤剝成 my → my-poster.jpg"
        )

        nfo = video_dir / "my-fanart.nfo"
        tags = _t5_assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == "my-fanart-poster.jpg"
        assert tags["thumb"] == "my-fanart-fanart.jpg"
        assert tags["fanart"] == "my-fanart-fanart.jpg"


class TestEnricherAC5ByteLock:
    """AC5（enricher 路徑）：媒體伺服器產生的 `-fanart.jpg`，內容與同情境
    off 模式產生的同名封面逐位元組一致（首次產生，Table 1 #1 情境，取基準法
    參考 T4 的做法：同一份 mock 下載內容分別跑 off／jellyfin 兩次，比對落地
    檔案的 bytes）。"""

    def test_jellyfin_fanart_bytes_match_off_mode_cover_bytes(self, tmp_path):
        content = _t5_jpeg_bytes(color=(9, 8, 7))

        def _stage(repo, video_dir, db_key, number_, capture):
            _t5_seed_tracked_row(repo, db_key, number_, cover_path="")

        off_ctx = _t5_run(tmp_path, "t5_ac5_off", external_manager="off",
                           number="AC5OFF-001", pre_stage=_stage, download_content=content)
        jf_ctx = _t5_run(tmp_path, "t5_ac5_jf", external_manager="jellyfin",
                          number="AC5JF-001", pre_stage=_stage, download_content=content)

        assert off_ctx.mock_search.called and jf_ctx.mock_search.called

        off_cover = off_ctx.video_dir / f"{off_ctx.video_file.stem}.jpg"
        jf_fanart = jf_ctx.video_dir / f"{jf_ctx.video_file.stem}-fanart.jpg"
        assert off_cover.exists() and jf_fanart.exists()
        assert jf_fanart.read_bytes() == off_cover.read_bytes() == content


class TestWriteExternalImagesPreflightSamefileGuard:
    """⑥⑦ 專屬守衛（Opus 追加要求 #1）：`same_target_verdict` 對未知
    `OSError` 的 fail-closed 承諾——preflight 真正承重的是 `os.path.samefile`
    拋出未知例外那一格，**不是** `src == dst` 的字串相等短路（那格從不呼叫
    `os.path.samefile`，本卡實測 `core/cover_layout.py:257-258` 的
    `if src == dst: return True, True` 在呼叫 `os.path.samefile` 之前就
    已短路）。監控 `os.path.samefile` 拋錯：

    - **fanart（⑥）**：`cover_path == fanart_path`（字串相等，#4b 常態
      路徑）→ unmutated code 完全不受 monkeypatch 影響（string-equal 短路），
      維持安全；mutation 拿掉 preflight 三行後，`shutil.copy2` 內部
      `shutil._samefile()` 才會真的呼叫 `os.path.samefile` → patch 生效 →
      誤判「不同檔」→ `copyfile` 用 `'wb'` 開啟同一個檔案 → 截斷（T3 §D
      實測 7427→0 bytes 仍報成功）。
    - **poster（⑦）**：`poster_path` 字串永不等於 `cover_path`，
      `same_target_verdict` 一定會呼叫 `os.path.samefile` → patch 直接命中
      未知 `OSError` 分支 → `(True, False)` → fail-closed，`poster_ok`
      老實回 `False`（**unmutated code 即可驗到**，不需要靠 mutation）。
    """

    def test_samefile_oserror_fails_closed_no_corruption(self, tmp_path, monkeypatch):
        video = tmp_path / "T5PF-001.mp4"
        video.write_bytes(b"video")
        stem = str(video.with_suffix(""))
        fanart = Path(stem + "-fanart.jpg")
        _t5_write_jpeg(fanart, color=(9, 9, 9))
        before_bytes = fanart.read_bytes()
        poster = Path(stem + "-poster.jpg")

        def _raise(a, b):
            raise OSError("boom（模擬權限被拒／網路磁碟逾時）")

        monkeypatch.setattr(os.path, "samefile", _raise)

        from core.enricher import _write_external_images
        result = _write_external_images(
            str(video), "jellyfin", True, number="T5PF-001", maker="TestMaker",
        )

        assert fanart.read_bytes() == before_bytes, (
            "-fanart.jpg 的 bytes 不得被清空/改動（基準值在操作之前取得，BE-TEST-10）"
        )
        # fanart：cover_path == fanart_path（字串相等）→ same_target_verdict 在
        # 呼叫 os.path.samefile 之前就已 `src == dst` 短路回 (True, True)，
        # 完全不受本測試的 monkeypatch 影響——unmutated code 正確回 True（安全，
        # 沒有觸碰檔案）。這正是本卡實測更正 Opus 追加要求 #1 原始描述的地方：
        # 真正被 samefile 拋錯打中的是 poster 那一側，不是 fanart。
        assert result["fanart"] is True, "字串相等短路，不受 samefile patch 影響（unmutated 安全）"
        assert result["poster"] is False, (
            "poster_path 字串永不等於 cover_path，samefile 拋錯 → fail-closed，"
            "certain=False，不得宣稱成功"
        )
        assert not poster.exists(), "fail-closed 不動作，不應寫出 poster"


class TestResolveNfoCoverPathsFlavourCoverage:
    """TASK-112b-T6b DoD-2（PR1 residual 的關閉）：`resolve_nfo_cover_paths`
    （`core/enricher.py:730`）在 T3 翻面後改呼叫**真實** `resolve_cover_target`
    三步規則，不再是 stub。既有 `TestResolveNfoCoverPathsMappingReverse`
    （`:2185`，2 支）只鎖路徑映射反解、**不變化 `external_manager`**，翻面後
    對「flavour 是否正確接線」零鑑別力（plan-112b.md §8.1 第 2 點具名
    residual）。

    同一個 `file_path` × `{off, jellyfin, emby, kodi, 非法值}` ×
    `{磁碟上無圖(neither), 只有同名(same_name_only), 只有 fanart(fanart_only)}`
    共 15 格，逐格斷言 `cover_path`；`nfo_path` 那一半只用
    `with_suffix('.nfo')`，與 flavour 完全正交——這條反向鎖（Opus 追加要求
    #3 / plan §8.3 DoD-2）與 15 格一起跑，也另外用一支獨立測試把它單獨列出來。

    白名單語意沿用 `core.config.STEM_IMAGE_MODES = ('jellyfin', 'emby',
    'kodi')`（`BE-CONFIG-03`），不自建字面值清單去判斷「新建時要不要走
    fanart」——`_FLAVOURS` 只是本測試挑的樣本，不是白名單本身。
    """

    _FLAVOURS = ["off", "jellyfin", "emby", "kodi", "plex"]  # "plex"＝非法值（不在白名單）
    _DISK_STATES = ["neither", "same_name_only", "fanart_only"]

    def _make_disk(self, video_path, state):
        """依 state 在 video_path 同層造出對應候選檔案，回傳 (same, fanart) 兩個 Path。"""
        same = video_path.with_suffix(".jpg")
        fanart = Path(str(video_path.with_suffix("")) + "-fanart.jpg")
        if state == "same_name_only":
            same.write_bytes(b"SAME-COVER")
        elif state == "fanart_only":
            fanart.write_bytes(b"FANART-COVER")
        return same, fanart

    @pytest.mark.parametrize("external_manager", _FLAVOURS)
    @pytest.mark.parametrize("disk_state", _DISK_STATES)
    def test_15_cells_cover_path_flavour_coverage(self, tmp_path, external_manager, disk_state):
        from core.config import STEM_IMAGE_MODES
        from core.enricher import resolve_nfo_cover_paths

        video_path = tmp_path / "SONE-205.mp4"
        video_path.write_bytes(b"FAKE-VIDEO")
        same, fanart = self._make_disk(video_path, disk_state)

        nfo_path, cover_path = resolve_nfo_cover_paths(
            str(video_path), None, external_manager
        )

        # 反向鎖（Opus 追加要求 #3）：nfo_path 只依 file_path 決定，與
        # external_manager 完全正交——15 格逐格都要驗這條，不能只驗一次。
        assert nfo_path == str(video_path.with_suffix(".nfo")), (
            f"nfo_path 不得受 flavour（{external_manager!r}）影響，"
            f"實際: {nfo_path!r}"
        )

        if disk_state == "same_name_only":
            expected_cover = str(same)
        elif disk_state == "fanart_only":
            expected_cover = str(fanart)
        else:  # "neither"：磁碟兩候選皆無 → 依 flavour 新建，白名單 fail-closed
            expected_cover = (
                str(fanart) if external_manager in STEM_IMAGE_MODES else str(same)
            )
        assert cover_path == expected_cover, (
            f"flavour={external_manager!r} disk_state={disk_state!r} 預期 "
            f"cover_path={expected_cover!r}，實際={cover_path!r}"
        )

    def test_nfo_path_unaffected_by_flavour_reverse_lock(self, tmp_path):
        """反向鎖獨立測試（Opus 追加要求 #3 / plan §8.3 DoD-2 明列「不能少」）：
        同一 file_path、同一磁碟狀態，nfo_path 在全部 5 種 flavour 下逐字相同
        ——它是「flavour 只影響封面那一半」的唯一機械證據。少了它，
        `resolve_nfo_cover_paths` 的另一半就沒有任何東西擋住未來有人把
        flavour 也接進 nfo_path 的推導。"""
        from core.enricher import resolve_nfo_cover_paths

        video_path = tmp_path / "SONE-205.mp4"
        video_path.write_bytes(b"FAKE-VIDEO")
        self._make_disk(video_path, "fanart_only")

        nfo_paths = {
            flavour: resolve_nfo_cover_paths(str(video_path), None, flavour)[0]
            for flavour in self._FLAVOURS
        }
        assert len(set(nfo_paths.values())) == 1, (
            f"nfo_path 必須在所有 flavour 下逐字相同，實際: {nfo_paths}"
        )
        assert next(iter(nfo_paths.values())) == str(video_path.with_suffix(".nfo"))


# ══════════════════════════════════════════════════════════════════════════════
# TASK-126-T4b：preview_* 管線接通 enricher（caller 層級）
# ══════════════════════════════════════════════════════════════════════════════

import hashlib
import requests


_T4B_BIG = b"P" * 1001
_T4B_PROXY = b"F" * 1001


def _t4b_ok(content=_T4B_BIG):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    return resp


class _T4bFailedHostsMixin:
    @pytest.fixture(autouse=True)
    def _clear_failed_hosts(self):
        import core.organizer as org
        with org._failed_hosts_lock:
            org._failed_hosts.clear()
        yield
        with org._failed_hosts_lock:
            org._failed_hosts.clear()


def _t4b_scraper(**overrides):
    data = {
        "number": "SONE-205",
        "title": "テストタイトル",
        "actors": ["女優A"],
        "cover": "https://cdn.example/cover.jpg",
        "preview_cover_url": "https://mt.example/v1/images/?url=cover",
        "date": "2024-01-01",
        "maker": "SOD",
        "director": "監督",
        "series": "シリーズ",
        "label": "LABEL",
        "tags": ["タグ"],
        "sample_images": [
            "https://cdn.example/s1.jpg",
            "https://cdn.example/s2.jpg",
        ],
        "preview_sample_images": [
            "https://mt.example/v1/images/?url=s1",
            "https://mt.example/v1/images/?url=s2",
        ],
        "duration": 120,
        "url": "https://example.com/SONE-205",
        "source": "metatube:MGS",
    }
    data.update(overrides)
    return data


class TestT4bEnrichCallerFallback(_T4bFailedHostsMixin):
    """邊界 1：enrich_single 入口，原址 ConnectTimeout → 代理成功存檔。"""

    def test_enrich_single_connect_timeout_uses_preview_fallback(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper()

        def fake_get(url, **kwargs):
            if "cdn.example" in url:
                raise requests.exceptions.ConnectTimeout("connect timed out")
            return _t4b_ok(_T4B_PROXY)

        with (
            patch("core.organizer.requests.get", side_effect=fake_get),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=True,
                write_extrafanart=True,
                overwrite_existing=True,
            )

        assert result.success is True
        assert result.cover_written is True
        cover = tmp_path / "SONE-205.jpg"
        assert cover.exists()
        assert cover.read_bytes() == _T4B_PROXY
        ef = tmp_path / "extrafanart"
        assert (ef / "fanart1.jpg").read_bytes() == _T4B_PROXY
        assert (ef / "fanart2.jpg").read_bytes() == _T4B_PROXY


class TestT4bEnrichExternalManagerBranch(_T4bFailedHostsMixin):
    """SA-pre-6 缺口：`external_manager != "off"` 的那個 _write_cover 呼叫點沒被驗過。

    T4b 系列全部走 `external_manager` 預設值 "off"，只打到 enricher.py:610 那個
    call site；:558 那條（Jellyfin / Emby / Kodi 使用者走的路）的
    `preview_cover_url=` wiring 是「有寫但沒人驗過真的會退代理」。

    使用者流程：使用者的外部管理器設成 Jellyfin、按「補齊資料」→ 封面原址連不到 →
    這條 wiring 若被改壞，封面就抓不到，而測試全綠不會有人發現。
    """

    def test_external_manager_branch_uses_preview_fallback(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper()

        def fake_get(url, **kwargs):
            if "cdn.example" in url:
                raise requests.exceptions.ConnectTimeout("connect timed out")
            return _t4b_ok(_T4B_PROXY)

        with (
            patch("core.organizer.requests.get", side_effect=fake_get),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=True,
                write_extrafanart=False,
                overwrite_existing=True,
                external_manager="jellyfin",
            )

        assert result.success is True
        assert result.cover_written is True, (
            "external_manager 分支的 _write_cover 沒有把 preview_cover_url 傳下去"
        )
        # jellyfin flavour 下封面落點不是 <stem>.jpg（走 stem 長格式 -poster/-fanart），
        # 所以掃「實際寫出了哪些 .jpg」而不是猜檔名。原址是 ConnectTimeout，
        # 磁碟上只可能出現代理副本的位元組——這正是本測試要鎖的東西。
        written = sorted(f.name for f in tmp_path.iterdir() if f.suffix == ".jpg")
        assert written, f"jellyfin 分支沒有寫出任何圖片：{sorted(p.name for p in tmp_path.iterdir())}"
        assert all(
            (tmp_path / name).read_bytes() == _T4B_PROXY for name in written
        ), f"寫出的圖片不是代理副本（原址是 ConnectTimeout，只可能來自代理）：{written}"


class TestT4bEnrichMixedSource(_T4bFailedHostsMixin):
    """邊界 5 / CD-126-10：source=javbus 但 preview 非空 → fallback 仍傳入。"""

    def test_mixed_source_javbus_still_passes_fallback_url(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper(source="javbus")

        with (
            patch("core.enricher.download_image", return_value=True) as mock_dl,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("os.makedirs"),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=True,
                write_extrafanart=True,
                overwrite_existing=True,
            )

        assert result.success is True
        fallbacks = [
            c.kwargs.get("fallback_url", "")
            for c in mock_dl.call_args_list
            if c.kwargs.get("fallback_url")
        ]
        assert "https://mt.example/v1/images/?url=cover" in fallbacks
        assert "https://mt.example/v1/images/?url=s1" in fallbacks
        assert "https://mt.example/v1/images/?url=s2" in fallbacks


class TestT4bEnrichAc4cHash(_T4bFailedHostsMixin):
    """邊界 6 / AC-4c：原址可達時存檔 hash 等於直連位元組，不是代理副本。"""

    def test_enrich_single_primary_reachable_keeps_direct_bytes(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper()
        primary_bytes = b"DIRECT-BYTES" + (b"A" * 1000)
        proxy_bytes = b"PROXY-BYTES" + (b"B" * 1000)

        def fake_get(url, **kwargs):
            if "cdn.example" in url:
                return _t4b_ok(primary_bytes)
            return _t4b_ok(proxy_bytes)

        with (
            patch("core.organizer.requests.get", side_effect=fake_get),
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=True,
                write_extrafanart=False,
                overwrite_existing=True,
            )

        assert result.success is True
        cover = tmp_path / "SONE-205.jpg"
        assert cover.exists()
        assert hashlib.sha256(cover.read_bytes()).digest() == hashlib.sha256(primary_bytes).digest()
        assert cover.read_bytes() != proxy_bytes


class TestT4bEnrichPreviewShorter(_T4bFailedHostsMixin):
    """邊界 8：preview 比 sample 短 → 缺格當 ''，不得截斷下載張數。"""

    def test_short_preview_does_not_truncate_downloads(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper(
            sample_images=[
                "https://cdn.example/s1.jpg",
                "https://cdn.example/s2.jpg",
                "https://cdn.example/s3.jpg",
            ],
            preview_sample_images=["https://mt.example/v1/images/?url=s1"],
        )

        with (
            patch("core.enricher.download_image", return_value=True) as mock_dl,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("os.makedirs"),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=False,
                write_extrafanart=True,
                overwrite_existing=True,
            )

        sample_calls = [
            c for c in mock_dl.call_args_list
            if c.args and "cdn.example/s" in str(c.args[0])
        ]
        assert len(sample_calls) == 3
        assert sample_calls[0].kwargs.get("fallback_url") == "https://mt.example/v1/images/?url=s1"
        assert sample_calls[1].kwargs.get("fallback_url", "") == ""
        assert sample_calls[2].kwargs.get("fallback_url", "") == ""


class TestT4bEnrichNonMetatube(_T4bFailedHostsMixin):
    """邊界 9 / AC-5：preview 全空 → 不傳 fallback_url，行為與 branch 前相同。"""

    def test_empty_preview_omits_fallback_url_kwarg(self, tmp_path):
        video = tmp_path / "SONE-205.mp4"
        video.write_bytes(b"fake-video")
        scraper = _t4b_scraper(
            preview_cover_url="",
            preview_sample_images=["", ""],
            source="javbus",
        )

        with (
            patch("core.enricher.download_image", return_value=True) as mock_dl,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.find_subtitle_files", return_value=[]),
            patch("os.makedirs"),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import enrich_single
            enrich_single(
                file_path=str(video),
                number="SONE-205",
                mode="refresh_full",
                scraper_data=scraper,
                write_nfo=False,
                write_cover=True,
                write_extrafanart=True,
                overwrite_existing=True,
            )

        for c in mock_dl.call_args_list:
            assert "fallback_url" not in c.kwargs
            assert len(c.args) <= 2 or (len(c.args) >= 4 and c.args[3] == "")


class TestT4bMergeMetaPreviewPair:
    """邊界 10：_merge_meta 的 if 與 elif 兩條路都搬 preview。"""

    def test_merge_meta_if_branch_moves_preview_samples(self):
        from core.enricher import _merge_meta
        base = {"cover_url": "http://a/c.jpg", "sample_images": None}
        supplement = {
            "cover_url": "http://b/c.jpg",
            "preview_cover_url": "http://proxy/c",
            "sample_images": ["http://b/s1.jpg"],
            "preview_sample_images": ["http://proxy/s1"],
        }
        merged, _ = _merge_meta(base, supplement)
        assert merged["sample_images"] == ["http://b/s1.jpg"]
        assert merged["preview_sample_images"] == ["http://proxy/s1"]

    def test_merge_meta_elif_branch_moves_preview_samples(self):
        from core.enricher import _merge_meta
        base = {"cover_url": "", "sample_images": []}
        supplement = {
            "cover_url": "http://b/c.jpg",
            "preview_cover_url": "http://proxy/c",
            "sample_images": ["http://b/s1.jpg"],
            "preview_sample_images": ["http://proxy/s1"],
        }
        merged, _ = _merge_meta(base, supplement)
        assert merged["cover_url"] == "http://b/c.jpg"
        assert merged["preview_cover_url"] == "http://proxy/c"
        assert merged["sample_images"] == ["http://b/s1.jpg"]
        assert merged["preview_sample_images"] == ["http://proxy/s1"]


class TestT4bNfoToMetaPreviewKeys:
    """邊界 11：_nfo_to_meta / _video_to_meta 兩鍵存在且為空。"""

    def test_nfo_to_meta_has_empty_preview_keys(self):
        import xml.etree.ElementTree as ET
        from core.enricher import _nfo_to_meta
        root = ET.fromstring("<movie><title>T</title></movie>")
        meta = _nfo_to_meta(root)
        assert meta["preview_cover_url"] == ""
        assert meta["preview_sample_images"] == []

    def test_video_to_meta_has_empty_preview_keys(self):
        from core.enricher import _video_to_meta
        meta = _video_to_meta(_make_video())
        assert meta["preview_cover_url"] == ""
        assert meta["preview_sample_images"] == []

    def test_scraper_to_meta_carries_preview_keys(self):
        from core.enricher import _scraper_to_meta
        meta = _scraper_to_meta(_t4b_scraper())
        assert meta["preview_cover_url"] == "https://mt.example/v1/images/?url=cover"
        assert meta["preview_sample_images"] == [
            "https://mt.example/v1/images/?url=s1",
            "https://mt.example/v1/images/?url=s2",
        ]


# ============ TASK-126-T4b review MAJOR-1：fetch_samples_only 這條下載路徑 ============
#
# spec §3.2 末條要求「**每條下載路徑**都要有 caller 層級的驗證」，不是「四個入口函式」。
# T4b 的初版只守住 enrich_single，**fetch_samples_only（片庫頁按「補劇照」走的正是這條）
# 完全沒有測試碰到**——review 在沙盒把那行 wiring 拔掉，127 條照樣全綠。

class TestT4bFetchSamplesOnlyFallback(_T4bFailedHostsMixin):

    def test_fetch_samples_only_uses_preview_fallback(self, tmp_path):
        """被牆的使用者按「補劇照」→ 原址 ConnectTimeout → 代理接手，劇照落地。"""
        import requests as _rq
        fs = tmp_path / "ABC-999.mp4"
        fs.write_bytes(b"v" * 100)
        meta = {
            "number": "ABC-999",
            "sample_images": ["https://cdn.blocked/s1.jpg", "https://cdn.blocked/s2.jpg"],
            "preview_sample_images": [
                "http://mt.example/v1/images/primary/MGS/ABC-999?url=s1",
                "http://mt.example/v1/images/primary/MGS/ABC-999?url=s2",
            ],
        }

        def _side(url, **kwargs):
            if "mt.example" in url:
                return _t4b_ok(b"PROXY" + b"\x00" * 2000)
            raise _rq.exceptions.ConnectTimeout("blocked")

        with (
            patch("core.enricher.search_jav", return_value=meta),
            patch("core.organizer.requests.get", side_effect=_side),
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher._db_upsert_samples_only"),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(str(fs), "ABC-999")

        assert result.extrafanart_written == 2, (
            "兩張劇照都應該經由代理落地——這條 wiring 若被帶壞，使用者按「補劇照」"
            "會拿到 0 張且沒有任何錯誤訊息"
        )
        written = sorted((tmp_path / "extrafanart").glob("fanart*.jpg"))
        assert len(written) == 2
        for p in written:
            assert p.read_bytes().startswith(b"PROXY")

    def test_fetch_samples_only_without_preview_keeps_todays_behaviour(self, tmp_path):
        """AC-5：沒有 preview → 原址失敗即失敗，且不得出現 fallback_url kwarg。"""
        import requests as _rq
        fs = tmp_path / "ABC-998.mp4"
        fs.write_bytes(b"v" * 100)
        meta = {
            "number": "ABC-998",
            "sample_images": ["https://cdn.blocked/s1.jpg"],
            "preview_sample_images": [],
        }

        def _side(url, **kwargs):
            raise _rq.exceptions.ConnectTimeout("blocked")

        with (
            patch("core.enricher.search_jav", return_value=meta),
            patch("core.organizer.requests.get", side_effect=_side) as mg,
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher._db_upsert_samples_only"),
        ):
            mock_repo_cls.return_value = MagicMock()
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(str(fs), "ABC-998")

        assert result.extrafanart_written == 0
        assert mg.call_count == 1, "不得有第二次嘗試"
        assert "fallback_url" not in mg.call_args.kwargs
