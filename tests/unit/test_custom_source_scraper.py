"""CustomScraper：ScrapeResult 到 Video 的對應、例外映射、host 限制（全離線）。"""

import pytest

from core.custom_source import schema
from core.custom_source.extract import parse_html
from core.custom_source.interpret import ScrapedItem, ScrapeResult
from core.custom_source.scraper import CustomScraper
from core.proxy_policy import ProxySettings
from core.scrapers.errors import SourceBlocked
from core.scrapers.models import ScraperConfig
from tests.unit._custom_source_fake import FakeTransport, page
from tests.unit._custom_source_pages import FIXTURE_DIR, PAGES

SID = "custom:t"
SOG = "https://single-og.example/sone-205"
S = "T"
FIELDS = {
    "title": S, "maker": "M", "director": "D", "label": "L", "series": "R", "summary": "Y",
    "date": "2000-01-02", "actors": ["A1", "", "A2"], "cover": "https://x.example/c.jpg",
    "tags": ["g1", "g2"], "sample_images": ["https://x.example/1.jpg"], "duration": 90,
}


@pytest.fixture(autouse=True)
def _no_real_dns_or_sleep(monkeypatch):
    monkeypatch.setattr("core.public_target.resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("core.custom_source.fetch.rate_limit", lambda delay=0: None)


def _cfg():
    return ScraperConfig(proxy_settings=ProxySettings())


def _spec(name="single-og"):
    return schema.load_file(FIXTURE_DIR / f"{name}.yaml")


def _txt(name):
    return PAGES[name]


def _scraper(name="single-og"):
    return CustomScraper(_spec(name), SID, _cfg())


def _item(url="https://s.example/a", **extra):
    return ScrapedItem(url, dict(FIELDS, **extra))


def _fake_scrape(monkeypatch, result, target="scrape"):
    seen = []

    def fake(*args, **kwargs):
        seen.append(args)
        return result

    monkeypatch.setattr(f"core.custom_source.scraper.{target}", fake)
    return seen


def _wire(monkeypatch, routes):
    transport = FakeTransport(routes)
    monkeypatch.setattr("core.custom_source.interpret.make_transport", lambda *a, **k: transport)
    return transport


def _err(reason, status=None):
    return ScrapeResult("error", reason=reason, http_status=status)


def test_fields_map_to_video(monkeypatch):
    seen = _fake_scrape(monkeypatch, ScrapeResult("ok", items=(_item(),)))
    sc = _scraper()
    video = sc.search("sone205")
    assert seen[0][2] is sc.config
    assert video.number == "SONE-205" and video.source == SID
    assert video.detail_url == "https://s.example/a"
    assert [a.name for a in video.actresses] == ["A1", "A2"]
    for name, key in [("title", "title"), ("maker", "maker"), ("director", "director"), ("label", "label"),
                      ("series", "series"), ("summary", "summary"), ("date", "date"), ("cover_url", "cover")]:
        assert getattr(video, name) == FIELDS[key]
    assert video.tags == FIELDS["tags"] and video.sample_images == FIELDS["sample_images"]
    assert video.duration == FIELDS["duration"]


@pytest.mark.parametrize("status, exc", [
    (403, SourceBlocked),
    (500, RuntimeError),
])
def test_http_status_maps_to_typed_exception(monkeypatch, status, exc):
    _fake_scrape(monkeypatch, _err("http_status", status))
    with pytest.raises(RuntimeError) as ei:
        _scraper().search("SONE-205")
    assert type(ei.value) is exc and str(ei.value) == f"{SID}: http_status"


def test_end_to_end_not_found_and_unexpected_extract(monkeypatch):
    _wire(monkeypatch, {"https://single-og.example/zzzz-999": page("", 404), SOG: page(_txt("single-og"))})
    sc = _scraper()
    assert sc.search("ZZZZ-999") is None and sc.search_all_versions("ZZZZ-999") == []

    def boom(*args, **kwargs):
        raise ValueError("canary")

    monkeypatch.setattr("core.custom_source.interpret.extract_fields", boom)
    with pytest.raises(RuntimeError) as ei:
        sc.search("SONE-205")
    assert type(ei.value) is RuntimeError and "canary" not in str(ei.value)


def test_end_to_end_two_step_versions_newest_first(monkeypatch):
    base = "https://two-step.example/search/"
    hrefs = [a["href"] for a in parse_html(_txt("two-step-search")).select("h3.entry-title a")]
    older, newer = hrefs
    _wire(monkeypatch, {base + "SONE-205": page(_txt("two-step-search")),
                        older: page(_txt("two-step-detail-a")), newer: page(_txt("two-step-detail-b"))})
    sc = CustomScraper(_spec("two-step"), "custom:two-step", _cfg())
    videos = sc.search_all_versions("SONE-205")
    assert len(videos) == 2 and [v.date for v in videos] == sorted((v.date for v in videos), reverse=True)
    assert {v.source for v in videos} == {"custom:two-step"}
    assert sc.search("SONE-205").detail_url == videos[0].detail_url


@pytest.mark.parametrize("url", [
    "https://other.example/video/x/",
])
def test_fetch_by_detail_url_rejects_foreign_host(monkeypatch, url):
    transport = _wire(monkeypatch, {})
    with pytest.raises(RuntimeError) as ei:
        _scraper("candidates").fetch_by_detail_url(url, "SONE-205")
    assert type(ei.value) is RuntimeError and str(ei.value) == f"{SID}: blocked_target"
    assert transport.calls == []


