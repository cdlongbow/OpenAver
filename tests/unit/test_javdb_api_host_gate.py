"""CD-132b-7：javdb API 回的圖片 host 必須已登記於 image_host_policy。

未登記 → fetch_video 丟 ValueError → search() 降級 HTML。
測試不得發出真實網路請求。
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from core.scrapers import javdb, javdb_api
from core.scrapers.models import Video


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _raise(*_a, **_k):
        raise AssertionError("Network access attempted in pure unit test!")

    import requests

    monkeypatch.setattr(requests, "get", _raise)
    monkeypatch.setattr(requests, "post", _raise)
    if javdb.CURL_CFFI_AVAILABLE and hasattr(javdb, "curl_requests"):
        monkeypatch.setattr(javdb.curl_requests, "get", _raise)
        monkeypatch.setattr(javdb.curl_requests, "post", _raise)


def _detail_with_cover(cover_url: str, samples: list[str] | None = None) -> dict:
    return {
        "id": "abc123",
        "title": "Test Title",
        "cover_url": cover_url,
        "preview_images": [
            {"large_url": u} for u in (samples or [])
        ],
        "actors": [],
        "tags": [],
        "release_date": "2024-01-01",
        "maker_name": "TEST",
        "director_name": "",
        "publisher_name": "",
        "series_name": "",
        "duration": 120,
        "score": "4.5",
        "reviews_count": 10,
    }


class TestUnregisteredHost:
    def test_unregistered_cover_host_raises(self, monkeypatch):
        """mutation api-host-gate-degrades：拿掉閘 → 本支必須紅。"""
        monkeypatch.setattr(
            javdb_api,
            "api_search",
            lambda _kw: [{"id": "abc123", "number": "SSIS-001"}],
        )
        monkeypatch.setattr(
            javdb_api,
            "api_movie_detail",
            lambda _id: _detail_with_cover("https://unregistered-cdn.example/c.jpg"),
        )

        with pytest.raises(ValueError, match="unregistered-cdn.example"):
            javdb_api.fetch_video("SSIS-001")

    def test_unregistered_sample_host_raises(self, monkeypatch):
        monkeypatch.setattr(
            javdb_api,
            "api_search",
            lambda _kw: [{"id": "abc123", "number": "SSIS-001"}],
        )
        monkeypatch.setattr(
            javdb_api,
            "api_movie_detail",
            lambda _id: _detail_with_cover(
                "https://tp.spfcas.com/covers/ok.jpg",
                samples=["https://evil-sample.example/s1.jpg"],
            ),
        )

        with pytest.raises(ValueError, match="evil-sample.example"):
            javdb_api.fetch_video("SSIS-001")

    def test_empty_cover_url_ok(self, monkeypatch):
        monkeypatch.setattr(
            javdb_api,
            "api_search",
            lambda _kw: [{"id": "abc123", "number": "SSIS-001"}],
        )
        monkeypatch.setattr(
            javdb_api,
            "api_movie_detail",
            lambda _id: _detail_with_cover(""),
        )

        video = javdb_api.fetch_video("SSIS-001")
        assert video is not None
        assert video.cover_url == ""

    def test_registered_codec_host_ok(self, monkeypatch):
        monkeypatch.setattr(
            javdb_api,
            "api_search",
            lambda _kw: [{"id": "abc123", "number": "SSIS-001"}],
        )
        monkeypatch.setattr(
            javdb_api,
            "api_movie_detail",
            lambda _id: _detail_with_cover(
                "https://tp.spfcas.com/rhe/covers/p9/ok.jpg",
                samples=["https://tp.spfcas.com/rhe/samples/1.jpg"],
            ),
        )

        video = javdb_api.fetch_video("SSIS-001")
        assert video is not None
        assert "tp.spfcas.com" in video.cover_url


class TestSearchDegradesOnUnregisteredHost:
    def test_search_falls_back_to_html(self, monkeypatch, caplog):
        html_video = Video(
            number="SSIS-001",
            title="FROM_HTML",
            source="javdb",
            detail_url="https://javdb.com/v/html123",
            cover_url="https://c0.jdbstatic.com/covers/html.jpg",
        )
        scraper = javdb.JavDBScraper()
        monkeypatch.setattr("core.scrapers.javdb.rate_limit", MagicMock())
        monkeypatch.setattr(
            scraper,
            "search_via_api",
            MagicMock(
                side_effect=ValueError(
                    "javdb: 圖片 host 未登記於 image_host_policy: evil.example"
                )
            ),
        )
        monkeypatch.setattr(
            scraper, "search_via_html", MagicMock(return_value=html_video)
        )

        with caplog.at_level(logging.WARNING):
            result = scraper.search("SSIS-001")

        assert result is not None
        assert result.title == "FROM_HTML"
        assert any(
            "API 降級 → HTML" in r.message and "evil.example" in r.message
            for r in caplog.records
        )
