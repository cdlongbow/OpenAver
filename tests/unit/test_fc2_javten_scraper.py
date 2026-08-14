"""
test_fc2_javten_scraper.py - FC2-javten 契約守衛（TASK-118a-T13 後）

測試策略：
- 全 mock，不連網
- get_cf_transport 一律 patch 在消費端 core.scrapers.fc2_javten.get_cf_transport（BE-TEST-01）
- 不依賴站方 HTML 解析結果——只守 URL 形狀／host 白名單／regex 誤配

為什麼不收真檔（owner 2026-08-14 拍板，T8）：
javten 是第三方鏡像站，它改版時本地真檔還是舊結構——測試照樣全綠，線上卻全滅。
換句話說真檔擋不住這條來源唯一會壞的方式。而它跟 javlibrary 一樣有 CF 擋在前面
（`curl_cffi` 三種 impersonate 實測全 403），結構上也不可能做 canary。這條來源的
迴歸偵測只能靠真實使用者回報，收 3.3 MB 的真檔換不到對應的保障。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.scrapers.fc2_javten import FC2JavtenScraper


PATCH_TARGET = "core.scrapers.fc2_javten.get_cf_transport"


def make_transport(final_url: str, html: str | None = None) -> MagicMock:
    transport = MagicMock()
    transport.navigate_and_settle.return_value = final_url
    if html is not None:
        transport.fetch.return_value = html
    return transport


# 合成 HTML：僅供 SSRF 白名單 mutation 用——若白名單失效，fetch 會被呼叫且真的產出
# Video；餵 MagicMock 讓解析自己失敗會讓白名單拿掉時第一條仍綠 → 假綠。
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


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def scraper():
    with patch("core.scrapers.fc2_javten.rate_limit"):
        yield FC2JavtenScraper()


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
