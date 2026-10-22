"""tests/integration/test_scrape_single_source_routing.py — scrape-single 來源分流契約（TASK-147d-T1）。

CD-147d-7：無 metadata 時依 is_number_format 守門分流 smart_search / search_jav。
"""


# CD-147d-2 列出的 27 個 CASES（I-147d-1）
_INVARIANT_CASES = [
    "SONE-205",
    "sone-205",
    " SONE-205 ",
    "SONE-103-UC",
    "SONE-103_UC",
    "200GANA-3360",
    "259LUXU-1234",
    "7IPZ-154",
    "FC2-PPV-1234567",
    "FC2-1234567",
    "HEYZO-1234",
    "T28-103",
    "3DSVR-1774",
    "34ID-017",
    "MIDA-649",
    "n1234",
    "ABP-123-C",
    "ABC-123.mp4",
    "[ABC-123] title",
    "1pondo-123456_001",
    "carib-123456-789",
    "fc2 12",
    "深田えいみ",
    "2024",
    "IPZZ-03",
    "SONE",
    "",
]

_REAL_FILENAMES = [
    "ABP-123-C.mp4",
    "[JavBus] SSIS-001 中文字幕.mp4",
    "hhd800.com@MIDA-649.mp4",
    "IPZZ-859 4K.mp4",
    "FC2-PPV-1234567.mp4",
    "carib-123456-789.mp4",
]


class TestScrapeSingleSourceRouting:
    """端點 mock-and-assert-call：合法番號走 smart_search、非法格式走 search_jav。"""


    def test_uncensored_mode_passed_through_to_smart_search(self, client, mocker):
        """邊界 5：is_uncensored_mode_effective 回 True → smart_search 收到 True。"""
        mocker.patch(
            "web.routers.scraper.is_uncensored_mode_effective",
            return_value=True,
        )
        mock_smart = mocker.patch(
            "web.routers.scraper.smart_search",
            return_value=[{"number": "SONE-205", "title": "Test"}],
        )
        mocker.patch("web.routers.scraper.search_jav")
        mocker.patch(
            "web.routers.scraper.organize_file",
            return_value={"duplicate": True, "duplicate_target": "x.mp4"},
        )

        resp = client.post(
            "/api/scrape-single",
            json={"file_path": "/dummy/SONE-205.mp4", "number": "SONE-205"},
        )
        assert resp.status_code == 200
        mock_smart.assert_called_once()
        assert mock_smart.call_args.kwargs.get("uncensored_mode") is True


