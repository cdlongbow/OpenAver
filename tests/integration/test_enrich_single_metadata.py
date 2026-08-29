"""
test_enrich_single_metadata.py - POST /api/enrich-single 帶 metadata 之整合測試

覆蓋：
- DoD-1 (AC-1): 零查詢，search_jav 零呼叫，NFO 與 DB 寫入
- DoD-2 (CD-135-1 / M1): 模式閘（非唯讀與唯讀檔案各一案例，fill_missing / db_to_sidecar 均 400）
- DoD-3 (CD-135-2): 未知欄位 400 且 detail 含 key 名
- DoD-4 (AC-4): tags/actors/duration 型別錯誤 400 且指名欄位
- DoD-5 (CD-135-3 / M3): 忽略清單放行 ＋ 回應 source_used == "javdb"
- DoD-7 (CD-135-11): metadata ＋ javlibrary ＋ detail_url 互斥 400
- DoD-8 (CD-135-12 item 1b/3): 唯讀路徑門口檢查（ingest 400、rescrape 缺 number/title/number 為 int 400）
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

from core.enricher import EnrichResult


def _owning_stub(path="/tmp/ro_src", output_root="/out/ro_src-abcdef", output_uri="file:///out/ro_src-abcdef"):
    """`resolve_owning_output_root` 的成功回傳 stub：(source, output_root, output_uri)。"""
    source = MagicMock()
    source.path = path
    return (source, output_root, output_uri)


def _ok_result(**kwargs):
    """建立成功的 EnrichResult"""
    defaults = dict(
        success=True,
        nfo_written=True,
        cover_written=True,
        extrafanart_written=0,
        fields_filled=[],
        source_used="javdb",
        error=None,
    )
    defaults.update(kwargs)
    return EnrichResult(**defaults)


class TestEnrichSingleMetadataIntegration:
    """POST /api/enrich-single 帶 metadata 之整合測試"""

    def test_ac1_zero_query_and_returns_200(self, client, mocker):
        """DoD-1 (AC-1): POST /api/enrich-single 帶合法 metadata ＋ mode=refresh_full → 200，
        且 search_jav 零呼叫；enrich_single 接收到清洗後的 metadata 作為 scraper_data。
        （本測試只驗證端點到 enrich_single 邊界傳遞，DoD-1 的真實落地由 test_ac1_e2e_full_enrich_writes_nfo_and_db 負責）
        """
        mock_search = mocker.patch("core.enricher.search_jav")
        mock_enrich = mocker.patch(
            "web.routers.scraper.enrich_single",
            return_value=_ok_result(source_used="javdb")
        )
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        req_payload = {
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "title": "AI 審核後標題",
                "actors": ["演員A"],
                "tags": ["標籤1"],
                "source": "javdb",
            },
        }

        response = client.post("/api/enrich-single", json=req_payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # 斷言 search_jav 零呼叫
        mock_search.assert_not_called()

        # 斷言 enrich_single 接收到 scraper_data
        assert mock_enrich.call_count == 1
        _, kwargs = mock_enrich.call_args
        assert kwargs["scraper_data"] is not None
        assert kwargs["scraper_data"]["title"] == "AI 審核後標題"
        assert kwargs["scraper_data"]["actors"] == ["演員A"]
        assert kwargs["scraper_data"]["source"] == "javdb"

    def test_ac1_e2e_full_enrich_writes_nfo_and_db(self, client, mocker, tmp_path):
        """DoD-1 (AC-1): 端到端真實 enrich 流程 — 帶合法 metadata ＋ mode=refresh_full，
        不 mock enrich_single，斷言三向：
        1. HTTP 200 且 success is True；
        2. 真的 NFO 檔案被寫出，XML 欄位（title/originaltitle/actors/tags/studio/director/label）逐字符合；
        3. search_jav 零呼叫，DB VideoRepository upsert 收到欄位值等於 metadata 給的值。
        """
        number = "ABC-123"
        mp4_path = tmp_path / f"{number}.mp4"
        mp4_path.write_bytes(b"\x00" * 16)

        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)
        mock_search = mocker.patch("core.enricher.search_jav")
        mock_download = mocker.patch("core.enricher.download_image", return_value=True)

        mock_repo_cls = mocker.patch("core.enricher.VideoRepository")
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.db_path = ":memory:"
        mock_repo.get_by_path.return_value = None
        mock_repo.get_by_numbers.return_value = {}

        req_payload = {
            "file_path": str(mp4_path),
            "number": number,
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "title": "AI 審核後標題",
                "original_title": "AI 審核後原標題",
                "actors": ["演員A", "演員B"],
                "tags": ["標籤1", "標籤2"],
                "maker": "片商A",
                "director": "導演A",
                "series": "系列A",
                "label": "廠牌A",
                "date": "2024-05-01",
                "duration": 120,
                "source": "javdb",
            },
        }

        response = client.post("/api/enrich-single", json=req_payload)

        # 斷言 1: HTTP 200 且 success is True
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_used"] == "javdb"

        # 斷言 2: 真的 NFO 檔案被寫出，解析 XML 比對欄位
        nfo_path = tmp_path / f"{number}.nfo"
        assert nfo_path.exists(), "NFO 檔案應被真實寫出"
        root = ET.fromstring(nfo_path.read_text(encoding="utf-8"))
        assert root.findtext("title") == f"[{number}]AI 審核後標題"
        assert root.findtext("originaltitle") == "AI 審核後原標題"
        assert root.findtext("studio") == "片商A"
        assert root.findtext("director") == "導演A"
        assert root.findtext("label") == "廠牌A"

        actor_names = [a.findtext("name") for a in root.findall("actor")]
        assert actor_names == ["演員A", "演員B"]

        nfo_tags = [t.text for t in root.findall("tag")]
        assert "標籤1" in nfo_tags
        assert "標籤2" in nfo_tags

        # 斷言 3: search_jav 零呼叫；DB upsert 收到欄位值等於 metadata
        mock_search.assert_not_called()
        mock_download.assert_not_called()

        assert mock_repo.upsert.call_count == 1
        saved_video = mock_repo.upsert.call_args[0][0]
        assert saved_video.title == "AI 審核後標題"
        assert saved_video.original_title == "AI 審核後原標題"
        assert saved_video.actresses == ["演員A", "演員B"]
        assert "標籤1" in saved_video.tags
        assert "標籤2" in saved_video.tags
        assert saved_video.maker == "片商A"
        assert saved_video.director == "導演A"
        assert saved_video.series == "系列A"
        assert saved_video.label == "廠牌A"
        assert saved_video.release_date == "2024-05-01"
        assert saved_video.duration == 120

    def test_mode_gate_non_readonly_fill_missing_raises_400(self, client, mocker):
        """DoD-2 (CD-135-1 / M1): 非唯讀路徑 ＋ 帶 metadata ＋ mode=fill_missing → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        response = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "fill_missing",
            "metadata": {"title": "標題"},
        })

        assert response.status_code == 400
        assert "metadata 只在 mode=refresh_full 時合法" in response.json()["detail"]

    def test_mode_gate_non_readonly_db_to_sidecar_raises_400(self, client, mocker):
        """DoD-2 (CD-135-1): 非唯讀路徑 ＋ 帶 metadata ＋ mode=db_to_sidecar → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        response = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "db_to_sidecar",
            "metadata": {"title": "標題"},
        })

        assert response.status_code == 400
        assert "metadata 只在 mode=refresh_full 時合法" in response.json()["detail"]

    def test_mode_gate_readonly_fill_missing_raises_400(self, client, mocker):
        """DoD-2 (CD-135-1 / CD-135-12): 唯讀來源 ＋ 帶 metadata ＋ mode=fill_missing → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "fill_missing",
            "readonly_action": "rescrape",
            "metadata": {"number": "ABC-123", "title": "標題"},
        })

        assert response.status_code == 400
        assert "metadata 只在 mode=refresh_full 時合法" in response.json()["detail"]

    def test_mode_gate_readonly_db_to_sidecar_raises_400(self, client, mocker):
        """DoD-2 (CD-135-1 / CD-135-12): 唯讀來源 ＋ 帶 metadata ＋ mode=db_to_sidecar → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "db_to_sidecar",
            "readonly_action": "rescrape",
            "metadata": {"number": "ABC-123", "title": "標題"},
        })

        assert response.status_code == 400
        assert "metadata 只在 mode=refresh_full 時合法" in response.json()["detail"]

    def test_unknown_field_returns_400(self, client, mocker):
        """DoD-3 (CD-135-2): metadata 含未知 key（例 titl）→ 400 且 detail 字串內含該 key 名"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        response = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "metadata": {"titl": "錯字標題"},
        })

        assert response.status_code == 400
        assert "titl" in response.json()["detail"]

    def test_type_validation_returns_400(self, client, mocker):
        """DoD-4 (AC-4): tags 傳字串、actors 傳字串、duration 傳 '120' → 各自 400 且指名該欄位"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        # tags as string
        resp1 = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "metadata": {"tags": "tag1,tag2"},
        })
        assert resp1.status_code == 400
        assert "tags" in resp1.json()["detail"]

        # actors as string
        resp2 = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "metadata": {"actors": "三上悠亞"},
        })
        assert resp2.status_code == 400
        assert "actors" in resp2.json()["detail"]

        # duration as string
        resp3 = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "metadata": {"duration": "120"},
        })
        assert resp3.status_code == 400
        assert "duration" in resp3.json()["detail"]

    def test_source_sink_reports_source_used(self, client, mocker):
        """DoD-5 (CD-135-3 / M3): 帶 metadata 含 source: 'javdb' → 200 且回應 source_used == 'javdb'"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        # Mock enrich_single: 回傳 source_used 來自 scraper_data['source']
        def mock_enrich_impl(**kwargs):
            s_data = kwargs.get("scraper_data") or {}
            source_used = s_data.get("source", "scraper") or "scraper"
            return _ok_result(source_used=source_used)

        mocker.patch("web.routers.scraper.enrich_single", side_effect=mock_enrich_impl)

        response = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "title": "標題",
                "source": "javdb",
                "number": "ABC-123",
                "mode": "refresh_full",
                "success": True,
                "total": 1,
            },
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_used"] == "javdb"

    def test_mutual_exclusion_metadata_and_javlib_detail_url_raises_400(self, client, mocker):
        """DoD-7 (CD-135-11): 帶 metadata ＋ source=javlibrary ＋ detail_url → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=None)

        response = client.post("/api/enrich-single", json={
            "file_path": "/video/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "source": "javlibrary",
            "detail_url": "https://www.javlibrary.com/ja/?v=javli12345",
            "metadata": {"title": "標題"},
        })

        assert response.status_code == 400
        assert "metadata 與 javlibrary 明細網址（detail_url）不可同時提供" in response.json()["detail"]

    def test_readonly_ingest_with_metadata_raises_400(self, client, mocker):
        """DoD-8 (CD-135-12 item 1b): 唯讀來源檔案 ＋ metadata ＋ readonly_action 為 ingest（或未帶）→ 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        # 未帶 readonly_action（預設 ingest）
        resp1 = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "metadata": {"number": "ABC-123", "title": "標題"},
        })
        assert resp1.status_code == 400
        assert "唯讀來源：metadata 只在 rescrape（重刮）意圖下生效" in resp1.json()["detail"]

        # 明確 readonly_action="ingest"
        resp2 = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "readonly_action": "ingest",
            "metadata": {"number": "ABC-123", "title": "標題"},
        })
        assert resp2.status_code == 400
        assert "唯讀來源：metadata 只在 rescrape（重刮）意圖下生效" in resp2.json()["detail"]

    def test_readonly_rescrape_missing_number_or_title_raises_400(self, client, mocker):
        """DoD-8 (CD-135-12 item 3): 唯讀 ＋ rescrape 但 metadata 缺 number 或缺 title → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        # 缺 number
        resp1 = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"title": "標題"},
        })
        assert resp1.status_code == 400
        assert "唯讀來源重刮：metadata 缺 number" in resp1.json()["detail"]

        # 缺 title
        resp2 = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "ABC-123"},
        })
        assert resp2.status_code == 400
        assert "唯讀來源重刮：metadata 缺 title" in resp2.json()["detail"]

    def test_readonly_rescrape_number_as_int_raises_400(self, client, mocker):
        """DoD-8 (CD-135-12 / Codex round 2 P2-1): 唯讀 ＋ rescrape 但 metadata['number'] 為 int → 400"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/ro/ABC-123.mp4",
            "number": "ABC-123",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": 123, "title": "標題"},
        })
        assert response.status_code == 400
        assert "唯讀來源重刮：metadata.number 型別錯誤，必須是字串" in response.json()["detail"]
