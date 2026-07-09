"""
test_enricher_reason.py - TASK-94-T1: EnrichResult.reason 欄位 + enrich_single 各 return 點映射

覆蓋 CD-94-2 reason 映射表：
  - error: 缺番號 / mode 非法 / 檔案不存在 / NFO PermissionError（外部管理器 + off 模式）
  - not_found: refresh_full / db_to_sidecar / fill_missing 三處查無
  - hit / no_cover: 成功路徑依「cover.jpg 磁碟真相」分流（嚴禁用 cover_written 判）

Codex P1 回歸鎖：nfo_written=True, cover_written=False，但磁碟上 cover.jpg 本就存在
（因為 _write_cover 在 overwrite_existing=False 時對已存在檔案 skip）→ reason 必須是
'hit'，不是 'no_cover'。
"""

from unittest.mock import MagicMock, patch

from core.database import Video


def _make_video(
    number="SONE-205",
    title="テストタイトル",
    original_title="テストタイトル",
    actresses=None,
    maker="SOD",
    director="テスト監督",
    series="テストシリーズ",
    label="LABEL",
    tags=None,
    sample_images=None,
    duration=120,
    cover_path="https://example.com/cover.jpg",
    release_date="2024-01-01",
):
    return Video(
        number=number,
        title=title,
        original_title=original_title,
        actresses=actresses if actresses is not None else ["女優A"],
        maker=maker,
        director=director,
        series=series,
        label=label,
        tags=tags if tags is not None else ["タグ"],
        sample_images=sample_images if sample_images is not None else [],
        duration=duration,
        cover_path=cover_path,
        release_date=release_date,
    )


def _make_scraper_result(number="SONE-205"):
    return {
        "number": number,
        "title": "テストタイトル",
        "actors": ["女優A"],
        "cover": "https://example.com/cover.jpg",
        "date": "2024-01-01",
        "maker": "SOD",
        "director": "テスト監督",
        "series": "テストシリーズ",
        "label": "LABEL",
        "tags": ["タグ"],
        "sample_images": [],
        "duration": 120,
        "url": "https://www.javbus.com/SONE-205",
    }


# ── error 分支 ─────────────────────────────────────────────────────────────


class TestReasonErrorBranches:
    def test_missing_number_reason_error(self):
        with patch("os.path.exists", return_value=True):
            from core.enricher import enrich_single
            result = enrich_single(file_path="/video/x.mp4", number="")
        assert result.success is False
        assert result.reason == "error"

    def test_invalid_mode_reason_error(self):
        with patch("os.path.exists", return_value=True):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path="/video/x.mp4", number="SONE-205", mode="bogus_mode"
            )
        assert result.success is False
        assert result.reason == "error"

    def test_file_not_found_reason_error(self):
        with patch("os.path.exists", return_value=False):
            from core.enricher import enrich_single
            result = enrich_single(file_path="/nonexistent/x.mp4", number="SONE-205")
        assert result.success is False
        assert result.reason == "error"

    def test_external_manager_nfo_permission_error_reason(self, tmp_path):
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        video = _make_video()

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=PermissionError("denied")),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                external_manager="jellyfin",
                overwrite_existing=True,
            )

        assert result.success is False
        assert result.reason == "error"

    def test_off_mode_nfo_permission_error_reason(self, tmp_path):
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        video = _make_video()

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", side_effect=PermissionError("denied")),
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                external_manager="off",
                overwrite_existing=True,
            )

        assert result.success is False
        assert result.reason == "error"


# ── not_found 分支（三站台）───────────────────────────────────────────────


class TestReasonNotFoundBranches:
    def test_refresh_full_not_found_reason(self, tmp_path):
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file), number="SONE-205", mode="refresh_full"
            )

        assert result.success is False
        assert result.reason == "not_found"

    def test_db_to_sidecar_not_found_reason(self, tmp_path):
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")

        with patch("core.enricher.VideoRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file), number="SONE-205", mode="db_to_sidecar"
            )

        assert result.success is False
        assert result.reason == "not_found"

    def test_fill_missing_not_found_reason(self, tmp_path):
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None),
            patch("core.enricher.parse_nfo", return_value=(None, None)),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {}

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file), number="SONE-205", mode="fill_missing"
            )

        assert result.success is False
        assert result.reason == "not_found"


# ── 成功路徑：hit / no_cover 依磁碟真相分流 ──────────────────────────────


class TestReasonSuccessBranches:
    def test_fresh_cover_download_reason_hit(self, tmp_path):
        """有下載 + 磁碟真的寫出檔案 → hit。"""
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        cover_path = tmp_path / "SONE-205.jpg"
        video = _make_video(cover_path="https://example.com/cover.jpg")

        def fake_download(url, path):
            # 模擬真正把封面寫到磁碟
            with open(path, "wb") as f:
                f.write(b"jpegdata")
            return True

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image", side_effect=fake_download),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                overwrite_existing=True,
            )

        assert result.success is True
        assert result.cover_written is True
        assert cover_path.exists()
        assert result.reason == "hit"

    def test_no_cover_url_and_no_disk_file_reason_no_cover(self, tmp_path):
        """沒下載（無 cover_url）+ 磁碟無檔 → no_cover。"""
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        video = _make_video(cover_path="")  # 無 cover_url

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            patch("core.enricher.download_image") as mock_dl,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                overwrite_existing=True,
            )

        assert result.success is True
        assert result.cover_written is False
        mock_dl.assert_not_called()
        assert result.reason == "no_cover"

    def test_download_declared_true_but_file_missing_reason_no_cover(self, tmp_path):
        """cover_written=True（download_image 宣告成功）但磁碟實際上沒有檔案
        （極罕見）→ 磁碟真相優先，仍是 no_cover。"""
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        video = _make_video(cover_path="https://example.com/cover.jpg")

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True),
            # download_image 宣告 True，但不真的寫檔
            patch("core.enricher.download_image", return_value=True),
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                overwrite_existing=True,
            )

        assert result.success is True
        assert result.cover_written is True  # 宣告值
        assert not (tmp_path / "SONE-205.jpg").exists()  # 磁碟真相：無檔
        assert result.reason == "no_cover"  # 磁碟真相覆蓋宣告值

    def test_codex_p1_regression_lock_nfo_only_cover_already_exists_is_hit(self, tmp_path):
        """Codex P1 回歸鎖：本輪只補 NFO（nfo_written=True），封面本就存在磁碟
        （cover_written=False 是因為 _write_cover 對既存檔案 skip，不是因為沒有封面）
        → reason 必須是 'hit'，絕不能是 'no_cover'。

        這條測試若實作用 `cover_written` 來判斷 reason 就會 FAIL（因為
        cover_written 是 False）；只有用 os.path.exists(cover.jpg) 磁碟真相
        判斷才會 PASS。
        """
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")
        cover_path = tmp_path / "SONE-205.jpg"
        cover_path.write_bytes(b"existing-cover")  # 封面本就在磁碟上
        video = _make_video(cover_path="https://example.com/cover.jpg")

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.generate_nfo", return_value=True) as mock_nfo,
            patch("core.enricher.download_image") as mock_dl,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_numbers.return_value = {"SONE-205": [video]}
            mock_repo.get_by_path.return_value = None

            from core.enricher import enrich_single
            result = enrich_single(
                file_path=str(video_file),
                number="SONE-205",
                mode="db_to_sidecar",
                overwrite_existing=False,  # NFO 不存在會寫；cover 已存在則 skip
            )

        # NFO 本來不存在 → 這輪會寫
        mock_nfo.assert_called_once()
        assert result.nfo_written is True
        # cover 本就存在磁碟 + overwrite_existing=False → _write_cover skip，不下載
        mock_dl.assert_not_called()
        assert result.cover_written is False
        # 磁碟上封面確實還在
        assert cover_path.exists()
        # 回歸鎖核心斷言
        assert result.reason == "hit"


# ── fetch_samples_only 不 crash（default reason）─────────────────────────


class TestFetchSamplesOnlyReasonDefault:
    def test_fetch_samples_only_result_has_default_reason(self, tmp_path):
        """fetch_samples_only 未顯式帶 reason → EnrichResult default (None)，不 crash。"""
        video_file = tmp_path / "SONE-205.mp4"
        video_file.write_bytes(b"x")

        with (
            patch("core.enricher.search_jav", return_value=None),
        ):
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(file_path=str(video_file), number="SONE-205")

        assert result.success is False
        assert result.reason is None
        from dataclasses import asdict
        d = asdict(result)  # 不應 crash
        assert d["reason"] is None
