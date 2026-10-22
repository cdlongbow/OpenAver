"""
tests/integration/test_rescrape_javlib.py

/api/rescrape/preview (javlibrary 分支) + /api/enrich-single (detail_url 分支)
整合測試（FastAPI TestClient round-trip）。

patch target 一律為使用端：
  - web.routers.scraper.search_javlib_versions
  - web.routers.scraper.fetch_javlib_by_detail_url
  - web.routers.scraper.enrich_single
  - web.routers.scraper.get_cf_transport
（CD-86-12 / gotchas-backend §1）
"""
from unittest.mock import patch, MagicMock
import pytest

# TASK-141a-T5：本檔測的兩支端點（generate_avlist / enrich_single_endpoint）收尾會
# 無條件呼叫 reconcile_wishlist()，它用無參數 repo ⇒ 解析到真實 DB。逐檔明示 opt-in
# 隔離（fixture 定義見 tests/conftest.py，刻意不做成 autouse——見該處說明）。
pytestmark = pytest.mark.usefixtures("isolate_reconcile_db")


# ── helpers ──────────────────────────────────────────────────────────────────

def _ok_enrich_result(**kwargs):
    """建立成功的 EnrichResult（dataclass）作為 mock 回傳值。
    endpoint 用 asdict(result)，必須是真實 dataclass 才能序列化。
    """
    from core.enricher import EnrichResult
    defaults = dict(
        success=True,
        nfo_written=True,
        cover_written=True,
        extrafanart_written=0,
        fields_filled=[],
        source_used="javlibrary",
        error=None,
    )
    defaults.update(kwargs)
    return EnrichResult(**defaults)


# ── /api/rescrape/preview javlibrary 分支 ────────────────────────────────────

class TestRescrapePreviewJavlib:
    def test_preview_javlib_multi_returns_candidates(self, client):
        """
        source=javlibrary，search_javlib_versions 回 2 dict
        → resp 含 "candidates"（len 2），頂層無 "number" key（確認不是單筆 shape）。
        """
        two_dicts = [
            {"number": "MIDV-010", "url": ".../javme3bu7e.html", "title": "新片", "date": "2021-12-07"},
            {"number": "MIDV-010", "url": ".../javlidaori.html", "title": "舊片", "date": "2009-12-01"},
        ]
        with patch('web.routers.scraper.search_javlib_versions', return_value=two_dicts):
            resp = client.post("/api/rescrape/preview", json={
                "number": "MIDV-010", "source": "javlibrary",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "candidates" in data
        assert len(data["candidates"]) == 2
        assert "number" not in data  # 確認非單筆 shape

    def test_preview_javlib_single_backcompat(self, client):
        """
        source=javlibrary，search_javlib_versions 回 1 dict
        → resp 是單筆 shape（含 success + 欄位），無 candidates key（向下相容）。
        """
        one_dict = {"number": "MIDV-010", "url": ".../javme3bu7e.html", "title": "新片"}
        with patch('web.routers.scraper.search_javlib_versions', return_value=[one_dict]):
            resp = client.post("/api/rescrape/preview", json={
                "number": "MIDV-010", "source": "javlibrary",
            })

        data = resp.json()
        assert data["success"] is True
        assert "candidates" not in data
        assert data.get("number") == "MIDV-010"


# ── /api/enrich-single detail_url 分支 ───────────────────────────────────────

class TestEnrichSingleDetailUrl:
    def test_enrich_single_javlib_detail_url(self, client):
        """
        source=javlibrary + detail_url 存在：
          fetch_javlib_by_detail_url 被呼叫
          → to_legacy_dict() 當 scraper_data 傳給 enrich_single
          → enrich_single 收到 scraper_data（非 None）。
        """
        from core.scrapers.models import Video

        fake_video = MagicMock(spec=Video)
        fake_video.to_legacy_dict.return_value = {
            "number": "MIDV-010",
            "url": ".../javme3bu7e.html",
            "title": "新片",
        }
        # P2：detail_url 路徑須補回 to_legacy_dict 省略的 _rating/_summary carrier
        fake_video.rating = 4.5
        fake_video.summary = "簡介內容"

        with patch('web.routers.scraper.fetch_javlib_by_detail_url',
                   return_value=fake_video) as mock_fetch, \
             patch('web.routers.scraper.enrich_single',
                   return_value=_ok_enrich_result()) as mock_enrich:
            resp = client.post("/api/enrich-single", json={
                "file_path": "file:///fake/MIDV-010.mp4",
                "number": "MIDV-010",
                "source": "javlibrary",
                "detail_url": "https://www.javlibrary.com/ja/javme3bu7e.html",
                "mode": "refresh_full",
                "overwrite_existing": True,
            })

        mock_fetch.assert_called_once_with(
            "https://www.javlibrary.com/ja/javme3bu7e.html", "MIDV-010"
        )
        call_kwargs = mock_enrich.call_args.kwargs
        scraper_data = call_kwargs.get("scraper_data")
        # scraper_data 為選定版本 to_legacy_dict() + 補回的內部 NFO carrier
        assert scraper_data is not None
        assert scraper_data["number"] == "MIDV-010"
        # P2 mutation guard：_rating/_summary carrier 須補回且值取自 video（否則 NFO 評分掉）
        assert scraper_data["_rating"] == 4.5
        assert scraper_data["_summary"] == "簡介內容"

    def test_enrich_single_rejects_non_javlibrary_detail_url(self, client):
        """
        P3 SSRF guard：source=javlibrary 但 detail_url 非 javlibrary origin
        （內網 metadata endpoint / 任意外站 / prefix 繞過）→ success False，
        且 fetch_javlib_by_detail_url 完全不被呼叫。
        """
        malicious_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.com/x.html",
            "https://www.javlibrary.com.evil.com/ja/x.html",  # prefix 繞過
            "http://www.javlibrary.com/ja/x.html",            # scheme 不符
        ]
        for bad_url in malicious_urls:
            with patch('web.routers.scraper.fetch_javlib_by_detail_url') as mock_fetch, \
                 patch('web.routers.scraper.enrich_single',
                       return_value=_ok_enrich_result()) as mock_enrich:
                resp = client.post("/api/enrich-single", json={
                    "file_path": "file:///fake/MIDV-010.mp4",
                    "number": "MIDV-010",
                    "source": "javlibrary",
                    "detail_url": bad_url,
                    "mode": "refresh_full",
                    "overwrite_existing": True,
                })
                assert resp.status_code == 200
                assert resp.json()["success"] is False, f"應拒絕 {bad_url}"
                mock_fetch.assert_not_called()  # 惡意 URL 絕不進 fetch
                mock_enrich.assert_not_called()


# ── TASK-118a-T4：fc-javten CF 接線（preview / enrich-single / readonly） ──

class TestRescrapePreviewFcJavtenCf:
    def test_preview_fc_javten_cf_needed_carries_cf_source(self, client):
        """CD-118a-7：fc-javten 觸發 CF → cf_needed + cf_source='fc-javten'，begin_solve 用 JAVTEN_ORIGIN。"""
        from core.cf_transport import CfChallengeRequired
        from core.scrapers.fc2_javten import JAVTEN_ORIGIN

        mock_t = MagicMock()
        with patch(
            'web.routers.scraper.search_jav_single_source',
            side_effect=CfChallengeRequired("test"),
        ), patch('web.routers.scraper.get_cf_transport', return_value=mock_t):
            resp = client.post("/api/rescrape/preview", json={
                "number": "FC2-PPV-1234567", "source": "fc-javten",
            })

        data = resp.json()
        assert resp.status_code == 200
        assert data["success"] is False
        assert data.get("cf_needed") is True
        assert data.get("cf_source") == "fc-javten"
        mock_t.begin_solve.assert_called_once_with(JAVTEN_ORIGIN, "fc-javten")


# ── capabilities 全檔守衛 ─────────────────────────────────────────────────────

