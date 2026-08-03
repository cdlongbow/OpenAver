"""
test_heyzo_scraper.py - HEYZO 爬蟲單元測試（TASK-36-T9, TASK-93-T5, TASK-111-T7）

測試策略：
- 全 mock，不連網
- Mock scraper._session.get 回傳 inline HTML + JSON-LD fixture，
  或真實抓回的頁面 fixture（tests/fixtures/scrapers/heyzo_*.html）
- rate_limit 也 mock 掉（避免 sleep）

TASK-111-T7：站方英文頁把 JSON-LD 從靜態輸出改成 JS 執行期動態組裝
（`var person` / `var aggregateRating` / `var movie_obj`），且女優/發行日
改吃 HTML table 而非 JSON-LD。真實抓回的兩份 fixture：
- heyzo_0783.html：一般片，Series/Type/Actress(es)/Released 完整
- heyzo_3924.html：新片邊界，無 Series/Type（改 Provider 列）、
  Released 為日期區間、rating 0.0/0
"""

import json
import os

import pytest
import requests
from unittest.mock import patch, MagicMock


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "scrapers"
)


def load_fixture_text(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


HEYZO_0783_TEXT = load_fixture_text("heyzo_0783.html")
HEYZO_3924_TEXT = load_fixture_text("heyzo_3924.html")


# ============================================================
# Fixture surgery helpers（以真 fixture 為底做針對性字串裁切/置換，
# 依專案記憶 feedback_scraper_real_fixtures.md，不手搭合成 HTML）
# ============================================================

def _remove_js_movie_block(html_text: str) -> str:
    """移除 var person / var aggregateRating / var movie_obj 整段宣告，
    模擬「JS blob 完全缺失」（邊界條件 1）。"""
    start_marker = "\tvar person = {"
    end_marker = 'window.addEventListener("load", create_schemaorg, false);\n})();'
    start = html_text.index(start_marker)
    end = html_text.index(end_marker) + len(end_marker)
    return html_text[:start] + html_text[end:]


def _remove_person_var(html_text: str) -> str:
    """只移除 var person 宣告，movie_obj 仍引用 "actor":person（邊界條件 3）。"""
    start = html_text.index("\tvar person = {")
    end = html_text.index("\tvar aggregateRating = {")
    return html_text[:start] + html_text[end:]


def _remove_aggregate_rating_var(html_text: str) -> str:
    """只移除 var aggregateRating 宣告，movie_obj 仍引用
    "aggregateRating":aggregateRating（邊界條件 4）。"""
    start = html_text.index("\tvar aggregateRating = {")
    end = html_text.index("\tvar script = document.createElement")
    return html_text[:start] + html_text[end:]


def _corrupt_movie_obj_json(html_text: str) -> str:
    """movie_obj 的 brace 仍配對，但把 "name" 的值拿掉引號，讓 json.loads 壞掉
    （邊界條件 2：brace 配對後 JSON 壞掉）。"""
    old = "\"name\": \"Sex Heaven-Beautiful Girl's Gorgeous Skin-\","
    new = "\"name\": Sex Heaven-Beautiful Girl's Gorgeous Skin-,"
    assert old in html_text, "corruption marker not found in fixture"
    return html_text.replace(old, new, 1)


def _remove_table_row(html_text: str, needle: str) -> str:
    """移除含 needle 文字的整個 <tr>...</tr>（邊界條件 5：女優列缺失）。"""
    idx = html_text.index(needle)
    start = html_text.rindex("<tr>", 0, idx)
    end = html_text.index("</tr>", idx) + len("</tr>")
    return html_text[:start] + html_text[end:]


def _duplicate_actress_anchor(html_text: str) -> str:
    """在女優 td 內複製第二個 <a>，模擬多女優片（邊界條件 6）。"""
    old = '<a href="/listpages/actor_431_1.html?sort=pop" title="">Miku Ohashi</a>'
    assert html_text.count(old) == 1
    new = old + ' <a href="/listpages/actor_999_1.html?sort=pop" title="">Second Actress</a>'
    return html_text.replace(old, new, 1)


def _blank_series_placeholder(html_text: str) -> str:
    """把 0783 fixture 中被 <a> 包住的 Series 值換成純文字 "-----" placeholder
    （模擬「無 <a> 的純文字 placeholder」邊界，Opus 裁決追加）。"""
    old = '<a href="/listpages/series_188_1.html">Sex Heaven</a>'
    assert html_text.count(old) == 1
    return html_text.replace(old, "-----", 1)


def _set_released_cell(html_text: str, new_inner: str) -> str:
    """把 Released 列的值 td 內容整個換掉（邊界條件 7/16）。"""
    label = "<td>Released</td>"
    assert html_text.count(label) == 1
    idx = html_text.index(label)
    td_start = html_text.index("<td>", idx + len(label))
    td_end = html_text.index("</td>", td_start)
    return html_text[:td_start] + f"<td>{new_inner}</td>" + html_text[td_end + len("</td>"):]


# ============================================================
# Helpers
# ============================================================

def make_response(content, status_code: int = 200) -> MagicMock:
    if isinstance(content, str):
        content = content.encode("utf-8")
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = content.decode("utf-8", errors="replace")
    resp.url = "https://en.heyzo.com/moviepages/0783/index.html"
    return resp


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def scraper():
    from core.scrapers.heyzo import HEYZOScraper
    with patch("core.scrapers.heyzo.rate_limit"):
        s = HEYZOScraper()
        yield s


# ============================================================
# JSON-LD base (embedded in HTML) — used by legacy synthetic-fixture
# tests below that exercise Path A (static ld+json) directly.
# ============================================================

BASE_JSON_LD = {
    "@context": "http://schema.org",
    "@type": "Movie",
    "name": "テストタイトル",
    "dateCreated": "2023-01-17T00:00:00+09:00",
    "image": "//www.heyzo.com/contents/3000/0783/images/player_thumbnail.jpg",
    "actor": {"@type": "Person", "name": "Test Actress"},
    "aggregateRating": {"ratingValue": "4.2", "reviewCount": "100"},
}


def make_html(json_ld: dict, table_extra: str = "", gallery_html: str = "") -> bytes:
    """Build an en.heyzo.com-like HTML page with static JSON-LD (Path A) and
    optional table rows.

    Reflects legacy HEYZO DOM: table.movieInfo uses <td><td> pairs (no <th>).
    Duration lives in table.downloads, not table.movieInfo.
    """
    json_str = json.dumps(json_ld)
    html = f"""\
<html><head>
<meta charset="utf-8">
<script type="application/ld+json">{json_str}</script>
</head><body>
<table class="movieInfo">
  <tbody>
    <tr><td>Series</td><td>テストシリーズ</td></tr>
    <tr><td>Type</td><td><a href="/type/1">美乳</a></td></tr>
  </tbody>
</table>
{table_extra}
{gallery_html}
</body></html>
"""
    return html.encode("utf-8")


GALLERY_HTML = """\
<script>var dir_gallery = "/contents/3000/0783/gallery/";</script>
<div class="sample-images yoxview">
  <h1>Gallery</h1>
  <script>document.write('<img src="'+dir_gallery+'thumbnail_001.jpg">');</script>
  <script>document.write('<img src="'+dir_gallery+'thumbnail_002.jpg">');</script>
</div>
"""

DURATION_JS = """\
<script>
heyzo.duration = function(){
  var o = Object();
  o = {"full":"01:07:57","1":"00:19:33"};
  return o;
};
</script>
"""

INVALID_DURATION_JS = """\
<script>
heyzo.duration = function(){
  var o = Object();
  o = {"full":"--:--:--"};
  return o;
};
</script>
"""

FULL_FIELDS_CONTENT = make_html(
    BASE_JSON_LD,
    table_extra=DURATION_JS,
    gallery_html=GALLERY_HTML,
)

NO_DURATION_CONTENT = make_html(
    BASE_JSON_LD,
    table_extra='',
    gallery_html=GALLERY_HTML,
)

INVALID_DURATION_CONTENT = make_html(
    BASE_JSON_LD,
    table_extra=INVALID_DURATION_JS,
    gallery_html=GALLERY_HTML,
)

NO_SERIES_CONTENT = make_html(
    BASE_JSON_LD,
    table_extra=DURATION_JS,
    gallery_html=GALLERY_HTML,
).replace("テストシリーズ".encode("utf-8"), b"-----")

NO_GALLERY_CONTENT = make_html(
    BASE_JSON_LD,
    table_extra=DURATION_JS,
    gallery_html="",
)


class TestFullFields:
    """happy path (Path A / static ld+json): series, duration, sample_images all correct"""

    def test_series(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(FULL_FIELDS_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.series == "テストシリーズ"

    def test_duration_hhmm_ss_to_minutes(self, scraper):
        """01:07:57 → 67 分鐘（1*60 + 7）"""
        scraper._session.get = MagicMock(return_value=make_response(FULL_FIELDS_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.duration == 67
        assert isinstance(video.duration, int)

    def test_sample_images_absolute_url(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(FULL_FIELDS_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert len(video.sample_images) == 2
        for url in video.sample_images:
            assert url.startswith("https://")


class TestNoDuration:
    """Duration 欄位缺失 → duration=None"""

    def test_duration_none(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(NO_DURATION_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.duration is None


class TestInvalidDuration:
    """Duration 格式異常（--:--:--）→ duration=None"""

    def test_invalid_duration_none(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(INVALID_DURATION_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.duration is None


class TestNoGallery:
    """無 gallery → sample_images=[]"""

    def test_no_gallery_empty_list(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(NO_GALLERY_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.sample_images == []


class TestNoSeries:
    """Series 欄位顯示 '-----' placeholder → series 應為空字串"""

    def test_series_placeholder_is_empty(self, scraper):
        scraper._session.get = MagicMock(return_value=make_response(NO_SERIES_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.series == ""


class TestSeriesRealFixtureBoundaries:
    """Opus 裁決追加：真站頁面把 Series 值包在 <a> 裡（同一次站方改版的同根因），
    現行 XPath 只讀直接 text node 會漏接，抽出全空字串。"""

    def test_series_wrapped_in_anchor_extracted(self, scraper):
        """heyzo_0783.html：Series 值被 <a>Sex Heaven</a> 包住 → series == 'Sex Heaven'"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_0783_TEXT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.series == "Sex Heaven"

    def test_series_plain_text_placeholder_still_empty(self, scraper):
        """真 fixture 為底，把 <a>Sex Heaven</a> 換成純文字 "-----" placeholder，
        確認新寫法對「無 <a> 的純文字 placeholder」也成立 → series == ''"""
        html_text = _blank_series_placeholder(HEYZO_0783_TEXT)
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.series == ""

    def test_series_no_row_in_new_film_fixture_is_empty(self, scraper):
        """heyzo_3924.html：根本沒有 Series 列 → series == ''，不 raise"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_3924_TEXT))
        video = scraper.search("HEYZO-3924")
        assert video is not None
        assert video.series == ""


# ============================================================
# Summary (JSON-LD description) — TASK-93-T5
# ============================================================

SUMMARY_JSON_LD = {**BASE_JSON_LD, "description": "テスト説明文"}
SUMMARY_CONTENT = make_html(SUMMARY_JSON_LD, table_extra=DURATION_JS, gallery_html=GALLERY_HTML)

NULL_SUMMARY_JSON_LD = {**BASE_JSON_LD, "description": None}
NULL_SUMMARY_CONTENT = make_html(NULL_SUMMARY_JSON_LD, table_extra=DURATION_JS, gallery_html=GALLERY_HTML)


class TestSummary:
    """JSON-LD description → video.summary"""

    def test_summary_from_description(self, scraper):
        """JSON-LD 含 description → summary 為原文"""
        scraper._session.get = MagicMock(return_value=make_response(SUMMARY_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.summary == "テスト説明文"

    def test_summary_empty_when_no_description(self, scraper):
        """JSON-LD 無 description → summary == ''，不 raise"""
        scraper._session.get = MagicMock(return_value=make_response(FULL_FIELDS_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.summary == ""

    def test_summary_null_description(self, scraper):
        """JSON-LD description=null → video returned with summary==''.

        Regression (P2-2): `.get('description', '')` returns None on JSON null →
        Video(summary=None) raises ValidationError → whole HEYZO source dropped.
        The `or ''` fix keeps the source alive.
        """
        scraper._session.get = MagicMock(return_value=make_response(NULL_SUMMARY_CONTENT))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.summary == ""


# ============================================================
# Mock Data (from test_new_scrapers.py) — 純邏輯 / table 邏輯測試，不受
# TASK-111-T7 影響（見 TASK card「現況分析」）
# ============================================================

HEYZO_EN_HTML = b"""
<html>
<head>
<script type="application/ld+json">
{
    "@type": "Movie",
    "name": "Slim Beauty's Seduction",
    "actor": {"@type": "Person", "name": "Airi Mashiro"},
    "dateCreated": "2015-01-17T00:00:00+09:00",
    "image": "//en.heyzo.com/contents/3000/0783/images/player_thumbnail_450.jpg",
    "aggregateRating": {"ratingValue": "4.22", "reviewCount": "56"}
}
</script>
</head>
<body>
<table class="movieInfo">
<tr><td>Series</td><td>Premium Collection</td></tr>
<tr><td>Type</td><td><a>Cute</a> <a>Slender</a></td></tr>
</table>
</body>
</html>
"""


def _make_mock_resp(status_code=200, json_data=None, content=None):
    """Build a MagicMock that mimics requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json = lambda: json_data
    if content is not None:
        mock_resp.content = content
    return mock_resp


class TestHEYZOIntegration:
    """HEYZO scraper tests (merged from test_new_scrapers.py)"""

    @pytest.fixture
    def scraper(self):
        from core.scrapers.heyzo import HEYZOScraper
        return HEYZOScraper()

    def test_heyzo_success(self, scraper):
        """HEYZO-0783 搜尋成功（真實 fixture，走 Path B JS 動態組裝 fallback，
        女優/發行日改吃 table）。"""
        mock_resp = _make_mock_resp(status_code=200, content=HEYZO_0783_TEXT.encode("utf-8"))

        with patch.object(scraper._session, 'get', return_value=mock_resp):
            with patch('core.scrapers.heyzo.rate_limit'):
                video = scraper.search("HEYZO-0783")

        assert video is not None
        assert video.number == "HEYZO-0783"
        assert video.title == "Sex Heaven-Beautiful Girl's Gorgeous Skin-"
        assert len(video.actresses) == 1
        assert video.actresses[0].name == "Miku Ohashi"
        assert video.date == "2015-01-17"
        assert video.source == "heyzo"
        assert video.maker == "HEYZO"
        assert video.rating == 4.7
        assert video.votes == 33
        assert video.duration == 62
        assert video.cover_url == "https://en.heyzo.com/contents/3000/0783/images/player_thumbnail_en.jpg"

    def test_heyzo_strip_prefix(self, scraper):
        """_extract_heyzo_num 正確提取數字 ID（純邏輯，不需 mock）"""
        assert scraper._extract_heyzo_num("HEYZO-0783") == "0783"
        assert scraper._extract_heyzo_num("heyzo-1031") == "1031"
        assert scraper._extract_heyzo_num("0783") == "0783"
        assert scraper._extract_heyzo_num("INVALID") is None

    def test_heyzo_table_tags(self, scraper):
        """_extract_table_data 從 HTML table 提取 series 和 tags"""
        result = scraper._extract_table_data(HEYZO_EN_HTML)
        assert result['series'] == "Premium Collection"
        assert result['tags'] == ["Cute", "Slender"]

    def test_heyzo_not_found(self, scraper):
        """404 回應時 search 回傳 None"""
        mock_resp = _make_mock_resp(status_code=404)

        with patch.object(scraper._session, 'get', return_value=mock_resp):
            video = scraper.search("HEYZO-9999")

        assert video is None


# ============================================================
# TASK-111-T7: 站方 JSON-LD 改為 JS 執行期組裝 — 本 task 特有邊界（16 條）
# ============================================================

class TestJSFallbackBoundaries:
    """Path B（JS 動態組裝）相關的 fallback / 壞資料邊界"""

    def test_js_blob_missing_returns_none(self, scraper):
        """邊界 1：既無靜態 ld+json、也無 var movie_obj → search() 回 None，不 raise"""
        html_text = _remove_js_movie_block(HEYZO_0783_TEXT)
        assert "var movie_obj" not in html_text
        assert 'type="application/ld+json"' not in html_text
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is None

    def test_js_extract_movie_object_blob_missing_returns_none_directly(self, scraper):
        """_extract_js_movie_object 對缺 blob 的原始文字直接回 None"""
        html_text = _remove_js_movie_block(HEYZO_0783_TEXT)
        assert scraper._extract_js_movie_object(html_text) is None

    def test_movie_obj_malformed_json_returns_none(self, scraper):
        """邊界 2：movie_obj brace 配對成功但 JSON 壞掉 → 回 None，不 raise、
        不讓例外往外傳到 search() 頂層 except 之外"""
        html_text = _corrupt_movie_obj_json(HEYZO_0783_TEXT)
        # brace-matching 本身仍應成功找到區塊（只是 json.loads 失敗）
        block = scraper._extract_js_var_block(html_text, "movie_obj")
        assert block is not None
        assert scraper._extract_js_movie_object(html_text) is None

        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is None

    def test_person_var_missing_falls_back_to_empty_dict(self, scraper):
        """邊界 3：person 變數缺失 → 用 {} 頂替，movie_obj 仍可解析成功；
        因為 actress 已改吃 table，這個情境不影響最終 video.actresses"""
        html_text = _remove_person_var(HEYZO_0783_TEXT)
        assert "var person" not in html_text

        data = scraper._extract_js_movie_object(html_text)
        assert data is not None
        assert data.get("actor") == {}

        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert len(video.actresses) == 1
        assert video.actresses[0].name == "Miku Ohashi"

    def test_aggregate_rating_var_missing_rating_and_votes_none(self, scraper):
        """邊界 4：aggregateRating 變數缺失 → 用 {} 頂替，rating/votes 皆為 None，不 raise"""
        html_text = _remove_aggregate_rating_var(HEYZO_0783_TEXT)
        assert "var aggregateRating" not in html_text

        data = scraper._extract_js_movie_object(html_text)
        assert data is not None
        assert data.get("aggregateRating") == {}

        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.rating is None
        assert video.votes is None


class TestActressTableBoundaries:
    """女優改吃 table 的相關邊界"""

    def test_actress_row_missing_returns_empty_list(self, scraper):
        """邊界 5：無 Actress(es) 列 → video.actresses == []，不 raise"""
        html_text = _remove_table_row(HEYZO_0783_TEXT, "Actress(es)")
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.actresses == []

    def test_actress_row_multiple_anchors(self, scraper):
        """邊界 6：女優 table 列有多個 <a> → video.actresses 長度 == <a> 數，皆非空字串"""
        html_text = _duplicate_actress_anchor(HEYZO_0783_TEXT)
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert len(video.actresses) == 2
        names = [a.name for a in video.actresses]
        assert "Miku Ohashi" in names
        assert "Second Actress" in names
        assert all(n for n in names)


class TestReleasedDateBoundaries:
    """發行日改吃 table 的相關邊界"""

    def test_coming_soon_date_is_empty(self, scraper):
        """邊界 7：Released == "Coming Soon !!" → video.date == ''，不 raise，
        且 video 仍非 None（title/cover 齊全）"""
        html_text = _set_released_cell(HEYZO_3924_TEXT, "Coming Soon !!")
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-3924")
        assert video is not None
        assert video.date == ""
        assert video.title != ""
        assert video.cover_url != ""

    def test_date_range_takes_start_date(self, scraper):
        """邊界 8：Released 為日期區間「2026-07-30　～　2026-08-05」→ 取起始日"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_3924_TEXT))
        video = scraper.search("HEYZO-3924")
        assert video is not None
        assert video.date == "2026-07-30"

    def test_released_blank_cell_is_empty(self, scraper):
        """邊界 16：Released 列存在但內容為空/只有空白 → date == ''，不 raise"""
        html_text = _set_released_cell(HEYZO_0783_TEXT, "   ")
        scraper._session.get = MagicMock(return_value=make_response(html_text))
        video = scraper.search("HEYZO-0783")
        assert video is not None
        assert video.date == ""


class TestNewFilmPageBoundaries:
    """新片頁面（無 Series/Type，改 Provider 列）與 rating 0.0/0 邊界"""

    def test_no_series_type_row_still_parses(self, scraper):
        """邊界 9：新片頁面沒有 Series/Type 列（改 Provider 列）
        → video.series == ''、video.tags == []，不 raise"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_3924_TEXT))
        video = scraper.search("HEYZO-3924")
        assert video is not None
        assert video.series == ""
        assert video.tags == []

    def test_rating_zero_and_votes_zero_not_none(self, scraper):
        """邊界 11：rating/votes 為 "0.0"/"0"（新片尚無評分）
        → video.rating == 0.0、video.votes == 0，不是 None"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_3924_TEXT))
        video = scraper.search("HEYZO-3924")
        assert video is not None
        assert video.rating == 0.0
        assert video.rating is not None
        assert video.votes == 0
        assert video.votes is not None


class TestTimeoutBoundary:
    """邊界 12：timeout 仍要 raise TimeoutError（canary 靠此判斷 skip vs fail）"""

    def test_timeout_raises_timeout_error(self, scraper):
        scraper._session.get = MagicMock(side_effect=requests.Timeout("boom"))
        with pytest.raises(TimeoutError):
            scraper.search("HEYZO-0783")


class TestDiagnosticLogging:
    """邊界 14：兩條路徑皆失敗時有 warning 級 log（BE-SCRAPER-04 明示要求）"""

    def test_both_paths_fail_logs_warning(self, scraper, caplog):
        html_text = _remove_js_movie_block(HEYZO_0783_TEXT)
        scraper._session.get = MagicMock(return_value=make_response(html_text))

        with caplog.at_level("DEBUG"):
            video = scraper.search("HEYZO-0783")

        assert video is None
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "0783" in warning_records[0].message

    def test_path_a_fails_path_b_used_has_debug_log(self, scraper, caplog):
        """健康路徑（HEYZO_0783_TEXT 本身無靜態 ld+json）應留下「嘗試 Path B」的 debug log"""
        scraper._session.get = MagicMock(return_value=make_response(HEYZO_0783_TEXT))

        with caplog.at_level("DEBUG"):
            video = scraper.search("HEYZO-0783")

        assert video is not None
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert any("fallback" in r.message for r in debug_records)


class TestTableDataExceptionSafety:
    """邊界 15：_extract_table_data 的 result 初始化必須含新 key（actresses/date），
    解析中途拋例外時呼叫端不應 KeyError"""

    def test_table_parse_exception_returns_full_key_dict(self, scraper):
        with patch("core.scrapers.heyzo.etree.fromstring", side_effect=Exception("boom")):
            result = scraper._extract_table_data(b"<html></html>")

        assert result == {
            'series': '',
            'tags': [],
            'duration': None,
            'sample_images': [],
            'actresses': [],
            'date': '',
        }
