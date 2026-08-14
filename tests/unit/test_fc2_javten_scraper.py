"""
test_fc2_javten_scraper.py - FC2-javten 爬蟲單元測試（TASK-118a-T3）

測試策略：
- 全 mock，不連網
- get_cf_transport 一律 patch 在消費端 core.scrapers.fc2_javten.get_cf_transport（BE-TEST-01）
- HTML 一律用檔內合成（inline），**不收 javten 真檔**

為什麼不收真檔（owner 2026-08-14 拍板，T8）：
javten 是第三方鏡像站，它改版時本地真檔還是舊結構——測試照樣全綠，線上卻全滅。
換句話說真檔擋不住這條來源唯一會壞的方式。而它跟 javlibrary 一樣有 CF 擋在前面
（`curl_cffi` 三種 impersonate 實測全 403），結構上也不可能做 canary。這條來源的
迴歸偵測只能靠真實使用者回報，收 3.3 MB 的真檔換不到對應的保障。

代價（已知且接受）：AC-2.2（三顆已下架片逐欄位）與 AC-2.3（日文原詞 vs /tw/ 機翻）
的解析驗證就此失去。**不得改用合成 HTML 補回這兩支**——合成 HTML 會抹平空佔位與
null，那是假綠（v0.11.8 的教訓）。要嘛真檔要嘛沒有。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from lxml import etree

from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.scrapers.fc2_javten import FC2JavtenScraper, strip_lang_segment


PATCH_TARGET = "core.scrapers.fc2_javten.get_cf_transport"

# javten 對 FC2-PPV-4914771 的 hreflang="ja" canonical（無語言段、帶 slug）。
# 抄自真站頁面，當「一個形狀正確的落地 URL」用。
CANONICAL_JA_4914771 = (
    "https://javten.com/video/2100971/id4914771/"
    "%E3%80%90%E9%97%87%E3%83%90%E3%82%A4%E3%83%88%E3%83%BBU20%E3%80%91"
    "%E5%88%B6%E6%9C%8D18%E6%AD%B3%E3%82%92%E5%87%BA%E4%BC%9A%E3%81%84"
    "%EF%BD%B1%EF%BE%8C%EF%BE%9F%EF%BE%98%E3%81%A7%E9%87%A3%E3%81%A3%E3%81%A6"
    "%E3%81%BF%E3%81%9F%E3%80%824%2F12"
)


def parse_inline(html: str):
    return etree.fromstring(html.encode("utf-8"), etree.HTMLParser())


def make_transport(final_url: str, html: str | None = None) -> MagicMock:
    transport = MagicMock()
    transport.navigate_and_settle.return_value = final_url
    if html is not None:
        transport.fetch.return_value = html
    return transport


# ============================================================
# HTML Fixtures（僅供直接單測 _get_*() 的防禦分支，E-1）
# ============================================================

FULL_FIELDS_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<div style="padding: 0">
  <a href="//pics.example.com/gallery/001.jpg"><img src="//pics.example.com/gallery/001s.jpg"></a>
  <a href="//pics.example.com/gallery/002.jpg"><img src="//pics.example.com/gallery/002s.jpg"></a>
</div>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
</body></html>
"""

NO_GALLERY_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
</body></html>
"""

OUTLINE_RATING_HTML = """\
<html><head><meta charset="utf-8"></head><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<div class="col des">これはFC2の説明文です。</div>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
<script type="application/ld+json">{"@type":"Movie","aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5","bestRating":"5"}}</script>
</body></html>
"""

GRAPH_RATING_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<div class="col des">グラフ形式の説明文。</div>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
<script type="application/ld+json">[{"@type":"WebSite"},{"@type":"Movie","aggregateRating":{"@type":"AggregateRating","ratingValue":3.0,"bestRating":"5"}}]</script>
</body></html>
"""

GRAPH_DICT_RATING_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<div class="col des">グラフ dict 形式の説明文。</div>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},{"@type":"Movie","aggregateRating":{"@type":"AggregateRating","ratingValue":"3.8","bestRating":"5"}}]}</script>
</body></html>
"""

BROKEN_JSONLD_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
<script type="application/ld+json">{ this is not valid json </script>
</body></html>
"""

NO_AGGREGATE_JSONLD_HTML = """\
<html><body>
<h1>FC2-1723984</h1>
<h1>テストタイトル</h1>
<div class="col-8">テスト賣家</div>
<a data-fancybox="gallery" href="//pics.example.com/cover.jpg">
  <img src="//pics.example.com/thumb.jpg">
</a>
<p class="card-text">
  <a href="/tag/amateur">アマチュア</a>
</p>
<script type="application/ld+json">{"@type":"Movie","name":"タイトル"}</script>
</body></html>
"""


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def scraper():
    with patch("core.scrapers.fc2_javten.rate_limit"):
        yield FC2JavtenScraper()


# ============================================================
# CD-118a-19：strip_lang_segment（模組級，E-3）
# ============================================================

def test_strip_lang_segment_removes_tw():
    """CD-118a-19：剝 /tw|/en|/ko/；無語言段是 identity。"""
    base = "https://javten.com/video/2100971/id4914771/xxx"
    assert strip_lang_segment(
        "https://javten.com/tw/video/2100971/id4914771/xxx"
    ) == base
    assert strip_lang_segment(
        "https://javten.com/en/video/2100971/id4914771/xxx"
    ) == base
    assert strip_lang_segment(
        "https://javten.com/ko/video/2100971/id4914771/xxx"
    ) == base
    assert strip_lang_segment(base) == base


# ============================================================
# AC-2.3 的可保留部分：search() 一定要剝掉語言段才 fetch
# ============================================================
#
# 原本的 AC-2.3 是「落地 /tw/ → 標籤仍是日文原詞」，靠同一顆片的日文／繁中兩份真檔
# 對照證明（真檔已隨 T8 移除，那半邊確定失去）。
#
# 但可證偽的核心不在 HTML，而在**傳給 fetch 的那個 URL**：search() 若直接 fetch(final)
# 而不是 fetch(strip_lang_segment(final))，使用者拿到的標籤就是 javten 的機翻中文
# （實測「ハメ撮り」→「奇聞趣事」），整批寫進他的 NFO 與資料庫。
# 這條斷言只看呼叫參數，不看解析結果，所以用合成 HTML 一樣紅得對。

def test_search_strips_lang_segment_before_fetch(scraper):
    """落地在 /tw/ → 必須 fetch 無語言段的 URL，detail_url 也記無語言段的那個。

    mutation：search() 改成 `transport.fetch(final, ...)` → 本支轉紅。
    """
    ja_url = CANONICAL_JA_4914771
    tw_url = ja_url.replace("https://javten.com/", "https://javten.com/tw/")

    transport = make_transport(tw_url, FULL_FIELDS_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        video = scraper.search("FC2-PPV-4914771")

    assert video is not None
    fetched_url = transport.fetch.call_args[0][0]
    assert fetched_url == ja_url
    assert "/tw/" not in fetched_url
    assert video.detail_url == ja_url


# ============================================================
# CD-118a-19：查無此片＝最終 URL 形狀
# ============================================================

def test_search_notfound_returns_none(scraper):
    """CD-118a-19：仍停在 /search?kw= → None，且不得呼叫 fetch。"""
    transport = make_transport("https://javten.com/search?kw=9999999")
    with patch(PATCH_TARGET, return_value=transport):
        result = scraper.search("FC2-PPV-9999999")
    assert result is None
    transport.fetch.assert_not_called()


def test_match_predicate_escapes_regex_metachars(scraper):
    """CD-118a-19 的判準要同時擋掉「拿到別片」。

    `_normalize_fc2_number()` **不保證回傳純數字**（實測 'garbage' → 'GARBAGE'），所以番號
    裡的 regex metachar 會原樣進到 pattern。沒有 re.escape 的話 `1.*` 會匹配到任何一片的
    落地 URL —— 使用者打了一個畸形番號，javten 的搜尋 302 到某一片，我們就把**別片**的
    標題／封面／標籤寫進他的 NFO 與 DB，而番號欄位寫著那串畸形字。

    這個輸入一點都不牽強：檔名 `FC2-PPV-493811.mp4` 的副檔名邊界就會產生尾隨的點。
    `493811.` 沒有 escape 時，`.` 匹配任意字元 → 命中 `id4938117`（**另一顆真實存在的片**）。

    mutation：把 `re.escape(digits)` 改回 `digits` → 本測試轉紅。
    """
    # 落地在 4938117 這顆片；使用者要的是 493811x，兩者不是同一片
    transport = make_transport("https://javten.com/video/12345/id4938117/slug")
    with patch(PATCH_TARGET, return_value=transport):
        result = scraper.search("FC2-PPV-493811.")
    assert result is None, "含 regex metachar 的番號不得誤配到別片的落地 URL"
    transport.fetch.assert_not_called()


# ============================================================
# T6-P3-2：落地 URL 的 host／scheme 白名單（SSRF defense-in-depth）
# ============================================================
#
# T6/F-1 之前，navigate_and_settle() 回的是 `get_current_url() or url`，在 WebView2 上
# 那個值不跟轉址，等於**意外地**把 host 鎖死在我們請求的 javten URL 上。F-1 改讀
# location.href 之後才真的會跟著轉址走 —— 也就是說信任面是這次改動放開的。
#
# INV-1 的 origin gate 擋不住這條：它比對「記錄的 origin」與「要 fetch 的 origin」，
# 而兩者都源自同一個落地 URL，by construction 必然相等。它防的是內部狀態走鐘，
# 不是「這個 host 該不該信」。
#
# 使用者流程：javten（第三方鏡像站，本來就不可信）某天把搜尋轉址到別的 host →
# 我們拿那個 host 的頁面當成影片資料 → 標題／封面／標籤／劇照網址寫進他的 NFO 與
# 資料庫，而他看不出來，只能整批重刮。
#
# 本專案已為 javlibrary 做過同一道檢查（`web/routers/scraper.py` 的
# `_is_javlibrary_url()`，註解明寫要擋 `evil.com` 與 `www.javlibrary.com.evil.com`
# 這類 prefix 繞過），這裡是補上 fc-javten 的對等檢查，寫法沿用同一個 urlparse 慣例。

@pytest.mark.parametrize("landed, why", [
    ("https://evil.com/video/12345/id4914771/slug", "完全不同的 host"),
    ("https://javten.com.evil.com/video/12345/id4914771/slug", "prefix 繞過（不得用 startswith 比對）"),
    ("https://evil.com/?x=https://javten.com/video/12345/id4914771/", "把合法 URL 塞進 query（regex 未錨定）"),
    ("http://javten.com/video/12345/id4914771/slug", "降級成明文 http"),
])
def test_search_rejects_landing_outside_javten(scraper, landed, why):
    """落地 URL 不是 https + javten.com/www.javten.com → 回 None，且**不得**呼叫 fetch。

    mutation：把 host/scheme 檢查拿掉 → 這四個案例全部轉紅（fetch 會被呼叫）。
    """
    # 餵一份**解析得動**的 HTML：若白名單失效，fetch 會被呼叫且真的產出 Video → 兩條斷言
    # 都紅。若餵 MagicMock 讓解析自己失敗，白名單拿掉時第一條仍會綠 → 假綠。
    transport = make_transport(landed, FULL_FIELDS_HTML)
    with patch(PATCH_TARGET, return_value=transport):
        result = scraper.search("FC2-PPV-4914771")
    assert result is None, f"{why}：不得被當成命中"
    assert not transport.fetch.called, f"{why}：不得對非 javten 的 origin 發出 fetch"


def test_search_still_accepts_www_subdomain(scraper):
    """www.javten.com 是真實存在的合法落點（transport 層的 cross-origin 轉址測試就在用它），
    白名單不得把它一起擋掉——否則站方哪天換 host，使用者整條來源就失效。"""
    transport = make_transport(
        "https://www.javten.com/video/2100971/id4914771/slug",
        FULL_FIELDS_HTML,
    )
    with patch(PATCH_TARGET, return_value=transport):
        result = scraper.search("FC2-PPV-4914771")
    assert result is not None, "www 子網域必須仍算命中"
    transport.fetch.assert_called_once()


# ============================================================
# CD-118a-13 ①：CF 兩個例外原樣往外拋
# ============================================================

def test_cf_challenge_required_propagates_unmodified(scraper):
    """CD-118a-13①：navigate_and_settle / fetch 拋 CfChallengeRequired → 原樣拋出。"""
    transport = MagicMock()
    transport.navigate_and_settle.side_effect = CfChallengeRequired("challenge")
    with patch(PATCH_TARGET, return_value=transport):
        with pytest.raises(CfChallengeRequired):
            scraper.search("FC2-PPV-4914771")
    transport.fetch.assert_not_called()

    transport = MagicMock()
    transport.navigate_and_settle.return_value = CANONICAL_JA_4914771
    transport.fetch.side_effect = CfChallengeRequired("challenge on fetch")
    with patch(PATCH_TARGET, return_value=transport):
        with pytest.raises(CfChallengeRequired):
            scraper.search("FC2-PPV-4914771")


def test_cf_transport_unavailable_propagates_unmodified(scraper):
    """CD-118a-13①：get_cf_transport() is None → 拋 CfTransportUnavailable，不是 None。"""
    with patch(PATCH_TARGET, return_value=None):
        with pytest.raises(CfTransportUnavailable):
            scraper.search("FC2-PPV-4914771")


# ============================================================
# CD-118a-13 ②：非 CF 失敗 → logger.debug + None
# ============================================================

@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        RuntimeError("JS fetch error: failed"),
        ValueError("bogus"),
    ],
    ids=["timeout", "js-fetch", "value"],
)
def test_non_cf_failure_returns_none_silently(scraper, exc):
    """CD-118a-13②：非 CF 例外 → search() 回 None，不新增例外型別。"""
    transport = MagicMock()
    transport.navigate_and_settle.side_effect = exc
    with patch(PATCH_TARGET, return_value=transport):
        result = scraper.search("FC2-PPV-4914771")
    assert result is None


# ============================================================
# 既有 11 支選擇器防禦測試（E-1：直接單測 _get_*()，不經 transport）
# ============================================================

class TestFullFields:
    """happy path: extrafanart 有 URL（list[str]）"""

    def test_sample_images_present(self, scraper):
        # inline HTML：真站頁面全是完整成功頁；本支測 _get_extrafanart 在 gallery 存在時的回傳形狀，不經 transport。
        result = scraper._get_extrafanart(parse_inline(FULL_FIELDS_HTML))
        assert len(result) == 2

    def test_sample_images_absolute_url(self, scraper):
        # inline HTML：真站頁面不覆蓋「// 相對協定」這條選擇器邊界，不經 transport。
        result = scraper._get_extrafanart(parse_inline(FULL_FIELDS_HTML))
        for url in result:
            assert url.startswith("https://")


class TestNoGallery:
    """無 extrafanart → 空 list"""

    def test_no_extrafanart_empty_list(self, scraper):
        # inline HTML：真站結構性沒有「無劇照」頁，本支測 gallery 缺席時的防禦回傳，不經 transport。
        assert scraper._get_extrafanart(parse_inline(NO_GALLERY_HTML)) == []


class TestOutline:
    """簡介選擇器（col des）"""

    def test_summary_present(self, scraper):
        # inline HTML：測 _get_outline 在 col des 存在時的純函式回傳，不經 transport。
        assert scraper._get_outline(parse_inline(OUTLINE_RATING_HTML)) == "これはFC2の説明文です。"

    def test_summary_empty_when_no_col_des(self, scraper):
        # inline HTML：真站頁面皆有簡介；本支測 col des 缺席時回空字串，不經 transport。
        assert scraper._get_outline(parse_inline(FULL_FIELDS_HTML)) == ""


class TestRating:
    """評分解析（JSON-LD aggregateRating.ratingValue）"""

    def test_rating_from_dict_jsonld(self, scraper):
        # inline HTML：測 _get_rating 的 dict 形 JSON-LD，真站頁面不覆蓋此包法，不經 transport。
        assert scraper._get_rating(parse_inline(OUTLINE_RATING_HTML)) == 4.5

    def test_rating_from_graph_list_jsonld(self, scraper):
        # inline HTML：測頂層 list JSON-LD，真站頁面不覆蓋此包法，不經 transport。
        assert scraper._get_rating(parse_inline(GRAPH_RATING_HTML)) == 3.0

    def test_rating_from_graph_dict_jsonld(self, scraper):
        # inline HTML：測 {"@graph": [...]} 包裹，真站頁面不覆蓋此包法，不經 transport。
        assert scraper._get_rating(parse_inline(GRAPH_DICT_RATING_HTML)) == 3.8

    def test_rating_none_when_no_jsonld(self, scraper):
        # inline HTML：真站頁面皆有 JSON-LD；本支測缺 script 時回 None，不經 transport。
        assert scraper._get_rating(parse_inline(FULL_FIELDS_HTML)) is None

    def test_rating_none_when_broken_jsonld(self, scraper):
        # inline HTML：真站頁面 JSON-LD 皆合法；本支測 decode 失敗走 except，不經 transport。
        assert scraper._get_rating(parse_inline(BROKEN_JSONLD_HTML)) is None

    def test_rating_none_when_no_aggregate(self, scraper):
        # inline HTML：真站頁面皆有 aggregateRating；本支測缺該鍵時回 None，不經 transport。
        assert scraper._get_rating(parse_inline(NO_AGGREGATE_JSONLD_HTML)) is None
