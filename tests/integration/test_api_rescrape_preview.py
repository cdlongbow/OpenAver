"""
test_api_rescrape_preview.py - POST /api/rescrape/preview 端點整合測試

預覽端點只搜不寫，復用 B1 搜尋路徑（auto → search_jav，具體源 → search_jav_single_source）。
使用 FastAPI TestClient + mocker，mock core 層搜尋函數。
"""



def _scraper_dict(**kw):
    """建立成功的 scraper 回傳 dict（mirror to_legacy_dict shape，CD-62-3 key 命名）。"""
    d = dict(
        number="SONE-205",
        title="Test Title",
        maker="Test Maker",
        date="2024-01-01",
        cover="https://example.com/cover.jpg",
        tags=["tag1"],
        source="javbus",
        url="https://example.com/SONE-205",
        director="",
        duration=120,
        label="",
        series="",
        sample_images=[],
        actors=["Actor A"],
        _source="javbus",
    )
    d.update(kw)
    return d


class TestRescrapePreviewEndpoint:
    def test_preview_specific_source_calls_single_source(self, client, mocker):
        """具體來源 → 呼叫 search_jav_single_source(number, source)，回 dict + success:True。"""
        mock_single = mocker.patch(
            "web.routers.scraper.search_jav_single_source",
            return_value=_scraper_dict(),
        )

        response = client.post("/api/rescrape/preview", json={
            "number": "SONE-205",
            "source": "javdb",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["title"] == "Test Title"
        assert mock_single.called
        args = mock_single.call_args.args
        # (number, source) — number/source 在 args 前兩位
        assert args[0] == "SONE-205"
        assert args[1] == "javdb"


    def test_preview_auto_calls_search_jav(self, client, mocker):
        """source=auto → 呼叫 search_jav，source='auto' + proxy/primary 從 config。"""
        mock_auto = mocker.patch(
            "web.routers.scraper.search_jav",
            return_value=_scraper_dict(),
        )

        response = client.post("/api/rescrape/preview", json={
            "number": "SONE-205",
            "source": "auto",
        })

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert mock_auto.called
        kwargs = mock_auto.call_args.kwargs
        assert kwargs.get("source") == "auto"


