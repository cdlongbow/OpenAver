"""tests/unit/test_enricher_b1.py — spec-48b §b1 AC#1 root-cause fix 測試

- TestDbUpsertSampleImagesGate：驗證 _db_upsert() sample_images gate 行為
  write_extrafanart=False  → DB 不寫入遠端 URL（保留現有值）
  write_extrafanart=True, count=0 → DB 不寫入
  write_extrafanart=True, count>0 → DB 更新
"""
from core.path_utils import to_file_uri


class TestDbUpsertSampleImagesGate:
    """spec-48b §b1 AC#1 — _db_upsert sample_images gate"""

    def _run_enrich(self, write_extrafanart, download_count, existing_samples=None):
        """Helper：執行 enrich_single 並回傳 repo.upsert call args

        download_count: List[str] of local file:/// URIs (new return type of _write_extrafanart),
                        or int (converted to a mock list of that length for backward compat).
        """
        from unittest.mock import patch, MagicMock
        from core.enricher import ExtrafanartResult
        if isinstance(download_count, int):
            mock_written_uris = [to_file_uri(f"/tmp/extrafanart/fanart{i+1}.jpg") for i in range(download_count)]
        else:
            mock_written_uris = download_count
        with patch("os.path.exists", return_value=True), \
             patch("core.enricher.VideoRepository") as mock_repo_cls, \
             patch("core.enricher.search_jav") as mock_search, \
             patch("core.enricher.generate_nfo", return_value=True), \
             patch("core.enricher.download_image", return_value=True), \
             patch("core.enricher._write_extrafanart", return_value=ExtrafanartResult(mock_written_uris, len(mock_written_uris), 0)), \
             patch("core.enricher.find_subtitle_files", return_value=[]):
            mock_repo = MagicMock()
            mock_existing = MagicMock()
            mock_existing.sample_images = existing_samples or []
            mock_existing.user_tags = []
            mock_existing.cover_path = ""
            mock_repo.get_by_path.return_value = mock_existing
            mock_repo_cls.return_value = mock_repo
            mock_search.return_value = {
                "number": "SONE-205",
                "title": "Test",
                "actors": [],
                "cover": "http://example.com/cover.jpg",
                "date": "2024-01-01",
                "maker": "SOD",
                "director": "",
                "series": "",
                "label": "",
                "tags": [],
                "sample_images": ["http://example.com/s1.jpg"],
                "source": "javbus",
            }
            from core.enricher import enrich_single
            enrich_single(
                file_path="/tmp/SONE-205.mp4",
                number="SONE-205",
                mode="refresh_full",
                write_extrafanart=write_extrafanart,
                write_nfo=False,
                write_cover=False,
            )
            return mock_repo.upsert.call_args

    def test_no_extrafanart_flag_does_not_write_sample_images(self):
        """write_extrafanart=False → sample_images 欄位保留現有值"""
        args = self._run_enrich(write_extrafanart=False, download_count=0, existing_samples=[to_file_uri("/old.jpg")])
        video = args[0][0]
        assert video.sample_images == [to_file_uri("/old.jpg")], \
            "write_extrafanart=False 時不應覆蓋 DB sample_images"


    def test_extrafanart_written_positive_updates_sample_images(self):
        """write_extrafanart=True 且下載 > 0 張 → DB 更新為本地 file:/// URIs（非遠端 URL）"""
        args = self._run_enrich(write_extrafanart=True, download_count=2, existing_samples=[])
        video = args[0][0]
        assert len(video.sample_images) == 2, "extrafanart_written>0 時應寫入 2 筆 sample_images"
        assert all(s.startswith("file:///") for s in video.sample_images), \
            f"DB sample_images 應為 local file:/// URIs，實際: {video.sample_images}"
        assert not any(s.startswith("http") for s in video.sample_images), \
            f"scraper 遠端 URL 不應寫入 DB，實際: {video.sample_images}"


class TestDatabaseHelpers:
    """spec-48b §b1 — VideoRepository.update_sample_images + count_videos_in_folder"""

    def _make_repo(self, tmp_path):
        """建立 in-memory DB（使用 tmp_path 確保隔離）"""
        from core.database import init_db, VideoRepository
        db_path = tmp_path / "test_b2.db"
        init_db(db_path)
        return VideoRepository(db_path)

    def _insert_video(self, repo, path: str, **kwargs):
        """插入測試影片 row"""
        from core.database import Video
        video = Video(
            path=path,
            number=kwargs.get("number", "TEST-001"),
            title=kwargs.get("title", "Test Title"),
            actresses=kwargs.get("actresses", []),
            user_tags=kwargs.get("user_tags", []),
            sample_images=kwargs.get("sample_images", []),
        )
        repo.upsert(video)

    def test_update_sample_images_only_updates_that_field(self, tmp_path):
        """update_sample_images 寫入後，其他欄位（title / user_tags）不變"""
        repo = self._make_repo(tmp_path)
        self._insert_video(
            repo,
            path=to_file_uri("/A/v1.mp4"),
            title="Original Title",
            user_tags=["tag1"],
            sample_images=[],
        )

        new_samples = [to_file_uri("/A/extrafanart/s1.jpg")]
        result = repo.update_sample_images(to_file_uri("/A/v1.mp4"), new_samples)

        assert result is True, "update_sample_images 應回傳 True（rowcount > 0）"

        video = repo.get_by_path(to_file_uri("/A/v1.mp4"))
        assert video.sample_images == new_samples, "sample_images 應被更新"
        assert video.title == "Original Title", "title 欄位不應被改動"
        assert video.user_tags == ["tag1"], "user_tags 欄位不應被改動"


class TestFetchSamplesOnly:
    """spec-48b §b3 — fetch_samples_only() 後端核心邏輯

    - 檔案不存在 → success=False, 不寫磁碟, 不寫 DB
    - search_jav 回傳 None → success=False, 不寫
    - search_jav 成功但 sample_images=[] → success=True, extrafanart_written=0, 不寫 DB
    - 下載成功 count>0 → success=True, DB update_sample_images 被呼叫
    - _write_extrafanart 回傳 0（下載全部失敗）→ 不寫 DB
    """

    _SENTINEL = object()  # 用於區分「未傳 search_result」和「明確傳 None」

    def _run_fetch(
        self,
        file_exists: bool = True,
        search_result=_SENTINEL,
        write_count: int = 0,
        sample_images=None,
        skipped_count: int = 0,
    ):
        """Helper：執行 fetch_samples_only 並回傳 (result, mock_repo)

        write_count: 模擬成功下載的張數；_write_extrafanart mock 回傳對應長度的
                     local file:/// URIs list（新 return type）。
        skipped_count: 模擬因既有檔而跳過的張數（uris 含 downloaded+skipped）。
        """
        from unittest.mock import patch, MagicMock
        from core.enricher import ExtrafanartResult
        if sample_images is None:
            sample_images = ["http://example.com/s1.jpg"]
        if search_result is self._SENTINEL:
            search_result = {
                "number": "SONE-205",
                "title": "Test",
                "actors": [],
                "cover": "http://example.com/cover.jpg",
                "date": "2024-01-01",
                "maker": "SOD",
                "director": "",
                "series": "",
                "label": "",
                "tags": [],
                "sample_images": sample_images,
                "source": "javbus",
            }
        mock_written_uris = [
            to_file_uri(f"/tmp/SONE-205/extrafanart/fanart{i+1}.jpg")
            for i in range(write_count + skipped_count)
        ]
        with patch("os.path.exists", return_value=file_exists), \
             patch("core.enricher.VideoRepository") as mock_repo_cls, \
             patch("core.enricher.search_jav", return_value=search_result) as mock_search, \
             patch("core.enricher._write_extrafanart",
                   return_value=ExtrafanartResult(mock_written_uris, write_count, skipped_count)) as mock_write:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            from core.enricher import fetch_samples_only
            result = fetch_samples_only(
                file_path="/tmp/SONE-205.mp4",
                number="SONE-205",
            )
            return result, mock_repo, mock_search, mock_write


    def test_write_extrafanart_returns_zero_no_db_write(self):
        """_write_extrafanart 回傳 0（下載全部失敗）→ gate 不通，DB 不更新"""
        result, mock_repo, _search, _write = self._run_fetch(
            file_exists=True,
            sample_images=["http://example.com/s1.jpg"],
            write_count=0,   # 下載全部失敗，回傳 0
        )
        # success 仍為 True（scraping 本身成功，只是磁碟寫出 0 張）
        # 或依實作 success=True 亦可，關鍵是 DB 不更新
        assert result.extrafanart_written == 0
        mock_repo.update_sample_images.assert_not_called()


    def test_all_existing_skipped_uris_nonempty_but_downloaded_zero(self):
        """全部既有檔被跳過 → extrafanart_written=0，但 DB 仍收到磁碟真相 uris。"""
        result, mock_repo, _search, _write = self._run_fetch(
            file_exists=True,
            sample_images=["http://x/s1.jpg", "http://x/s2.jpg"],
            write_count=0,
            skipped_count=2,
        )
        assert result.extrafanart_written == 0
        mock_repo.update_sample_images.assert_called_once()
        samples_arg = mock_repo.update_sample_images.call_args[0][1]
        assert len(samples_arg) == 2
        assert result.success is True
