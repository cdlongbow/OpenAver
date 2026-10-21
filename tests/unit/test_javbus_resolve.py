"""test_javbus_resolve.py — JavBus 名稱→實體 resolve（TASK-175c-T3，plan CD-175c-3／CD-175c-9）。

兩層：
- scraper 層（`search_stars`／`fetch_entity_link`）：真 requests.Session ＋ 類別層 HTTPAdapter.send 罐頭，
  量得到實際送出的 URL 與請求數；不 patch `_session.get`。
- provider 層（`JavBusProvider.resolve`）：對兩個傳輸邊界方法名掛計數替身（不用 create=True）；
  另有幾案走罐頭端到端量 HTTP 請求預算與 `/ja/` 前綴。

HTML 全為檔內合成（形狀依 findings-javbus 與 175c-T3 活站探針紀錄），不收站方存檔；零活站請求。
快取清除靠 tests/conftest.py 的 autouse fixture（CD-175c-11），本檔不另設。
"""
import io
from contextlib import contextmanager
from urllib.parse import quote
from unittest.mock import patch

import pytest
import requests
from requests.structures import CaseInsensitiveDict

import core.search_providers.javbus as jbp
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.javbus import JavBusScraper, StarCard
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import EntityRef, Kind

BASE = "https://www.javbus.com/ja"


# ---------------------------------------------------------------- 合成 HTML
def _star_card(star_id, name, *, uncensored=False, href=None, with_title=True):
    seg = "uncensored/star" if uncensored else "star"
    href = href if href is not None else f"{BASE}/{seg}/{star_id}"
    title = f' title="{name}"' if with_title else ""
    button = "無修正" if uncensored else "修正"
    return (
        f'<div class="item"><a class="avatar-box text-center" href="{href}">'
        f'<div class="photo-frame"><img src="/pics/actress/{star_id}_a.jpg"{title}></div>'
        f'<div class="photo-info"><span class="mleft">{name}<button class="btn btn-xs">{button}</button></span></div>'
        f"</a></div>"
    )


def _star_page(*cards):
    return ('<html><body><div id="waterfall">' + "".join(cards) + "</div></body></html>").encode()


def _movie_card(number, title="T"):
    return (
        f'<div class="item"><a class="movie-box" href="{BASE}/{number}">'
        f'<div class="photo-frame"><img src="/pics/thumb/x.jpg" title="{title}"></div>'
        f'<div class="photo-info"><span>{title}<br><date>{number}</date> / <date>2026-01-02</date></span></div>'
        f"</a></div>"
    )


def _list_page(*numbers):
    return ('<html><body><div id="waterfall">' + "".join(_movie_card(n) for n in numbers) + "</div></body></html>").encode()


def _detail_page(*links, extra=True):
    """links＝(segment, id, 連結文字)…；extra 另放 studio／genre／star 連結當雜訊（站方詳情頁本來就有）。"""
    anchors = "".join(f'<a href="{BASE}/{seg}/{id_}">{text}</a>' for seg, id_, text in links)
    noise = (
        f'<a href="{BASE}/studio/7q">エスワン ナンバーワンスタイル</a>'
        f'<a href="{BASE}/genre/e">巨乳</a><a href="{BASE}/star/82q">奥田咲</a>'
    ) if extra else ""
    return f'<html><body><div class="col-md-3 info"><p>{anchors}{noise}</p></div></body></html>'.encode()


EMPTY_WATERFALL = b'<html><body><div id="waterfall"></div></body></html>'
NO_WATERFALL = b"<html><body><p>nothing to see</p></body></html>"
NO_INFO = b"<html><body><div id='x'>detail without info block</div></body></html>"


def _enc(plus_joined):
    """期望 URL 路徑片段：非 ASCII 百分號編碼、`+` 保留（不 unquote_plus 比對：會把 `+` 與空白混為一談）。"""
    return "+".join(quote(w) for w in plus_joined.split("+"))


def _search_url(plus_joined, type_=None):
    return f"{BASE}/search/{_enc(plus_joined)}" + (f"&type={type_}" if type_ else "")


def _star_url(plus_joined):
    return f"{BASE}/searchstar/{_enc(plus_joined)}"


def _detail_url(number):
    return f"{BASE}/{number}"


# ---------------------------------------------------------------- 罐頭傳輸（依 URL 回不同頁並記錄請求順序）
class Site:
    def __init__(self):
        self.routes = {}  # url -> (status, body) | BaseException
        self.default = (404, b"not found")  # 沒設路由的 URL＝站方「查無」
        self.seen = []  # (url, [existmag 值…])

    def set(self, url, status=200, body=b""):
        self.routes[url] = (status, body)

    def fail(self, url, exc):
        self.routes[url] = exc

    @property
    def urls(self):
        return [u for u, _ in self.seen]

    @property
    def existmag(self):
        return [v for _, v in self.seen]


def _existmag_values(cookie_header):
    return [p.split("=", 1)[1] for p in (cookie_header or "").split("; ") if p.startswith("existmag=")]


@pytest.fixture
def site(monkeypatch):
    s = Site()

    def fake_send(self, request, **kw):
        s.seen.append((request.url, _existmag_values(request.headers.get("Cookie"))))
        out = s.routes.get(request.url, s.default)
        if isinstance(out, BaseException):
            raise out
        status, body = out
        r = requests.Response()
        r.status_code = status
        r.headers = CaseInsensitiveDict({})
        r.raw = io.BytesIO(body)
        r.url = request.url
        r.request = request
        return r

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return s


def _ja():
    return JavBusScraper(lang="ja")


# ================================================================ 邊界條件 5：search_stars 傳輸層
@pytest.mark.parametrize("name,joined", [
    ("三上 悠亜", "三上+悠亜"),
    ("三上　悠亜", "三上+悠亜"),
    ("a  b", "a+b"),
    (" a b ", "a+b"),
    ("三上悠亜", "三上悠亜"),
])
def test_searchstar_url_joins_whitespace_with_plus(site, name, joined):
    # 使用者打「三上 悠亜」→ 若 searchstar 用 %20，站方回 403，被當成查無就認不出她
    _ja().search_stars(name)
    assert site.urls == [_star_url(joined)]
    assert "%20" not in site.urls[0] and " " not in site.urls[0]


def test_searchstar_does_not_set_existmag_cookie(site):
    # searchstar 不是「作品清單」，T2 的 existmag 只作用在清單 GET
    _ja().search_stars("三上悠亜")
    assert site.existmag == [[]]


def test_search_stars_parses_cards(site):
    site.set(_star_url("美咲愛"), 200, _star_page(
        _star_card("23f", "美咲愛", uncensored=True),
        _star_card("2f8", "Ai Misaki", uncensored=True),
        _star_card("36h", "美咲愛"),
        _star_card("zz1", "美咲愛華"),
    ))
    cards = _ja().search_stars("美咲愛")
    assert cards == [
        StarCard("uncensored/star/23f", "美咲愛", True),
        StarCard("uncensored/star/2f8", "Ai Misaki", True),
        StarCard("star/36h", "美咲愛", False),
        StarCard("star/zz1", "美咲愛華", False),
    ]


def test_search_stars_accepts_relative_and_language_prefixed_hrefs(site):
    site.set(_star_url("甲"), 200, _star_page(
        _star_card("a1", "甲", href="/ja/star/a1"),
        _star_card("a2", "甲", href="/star/a2"),
        _star_card("a3", "甲", href="https://www.javbus.com/uncensored/star/a3"),
        _star_card("a4", "甲", href="/ja/uncensored/star/a4"),
    ))
    assert [c.id for c in _ja().search_stars("甲")] == ["star/a1", "star/a2", "uncensored/star/a3", "uncensored/star/a4"]


def test_search_stars_drops_cards_without_name_or_without_star_id(site):
    site.set(_star_url("甲"), 200, _star_page(
        _star_card("a1", "甲"),
        _star_card("a2", "甲", with_title=False),                   # 缺名稱
        _star_card("a3", "甲", href=f"{BASE}/genre/e"),              # href 不是女優頁
        _star_card("a4", "甲", href=""),                             # 缺 id
        _star_card("a5", "   "),                                     # 名稱只有空白
        '<div class="item"><a class="movie-box" href="/ja/star/zz9"><img title="甲"></a></div>',  # 不是 avatar-box
    ))
    assert [c.id for c in _ja().search_stars("甲")] == ["star/a1"]


@pytest.mark.parametrize("status", [403, 429, 503])
def test_search_stars_blocked_status_raises_source_blocked(site, status):
    # 站方暫擋 → 若被當查無，使用者以為這個人不存在
    site.set(_star_url("甲"), status, b"blocked")
    with pytest.raises(RuntimeError) as ei:
        _ja().search_stars("甲")
    assert type(ei.value) is SourceBlocked


def test_search_stars_404_is_empty_list(site):
    site.set(_star_url("甲"), 404, b"No Result Found")
    assert _ja().search_stars("甲") == []


def test_search_stars_200_waterfall_zero_cards_is_empty_list(site):
    site.set(_star_url("甲"), 200, EMPTY_WATERFALL)
    assert _ja().search_stars("甲") == []


@pytest.mark.parametrize("body", [NO_WATERFALL, b""])
def test_search_stars_200_unreadable_raises_source_unreachable(site, body):
    site.set(_star_url("甲"), 200, body)
    with pytest.raises(RuntimeError) as ei:
        _ja().search_stars("甲")
    assert type(ei.value) is SourceUnreachable


@pytest.mark.parametrize("exc", [requests.Timeout("t"), requests.ConnectionError("c")])
def test_search_stars_request_errors_propagate_unchanged(site, exc):
    site.fail(_star_url("甲"), exc)
    with pytest.raises(requests.RequestException) as ei:
        _ja().search_stars("甲")
    assert ei.value is exc


# ================================================================ 邊界條件 2：fetch_entity_link（canned 三段）
SEG_TYPE = [("series", None), ("director", 2), ("label", 4)]


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_search_url_type_suffix(site, segment, type_):
    # series 是一般搜尋（type=5 對系列名實測全 404，G1 負例）；director 2、label 4
    assert _ja().fetch_entity_link("PLATINUM SOAP", segment) is None
    assert site.urls == [_search_url("PLATINUM+SOAP", type_)]
    assert ("&type=" in site.urls[0]) == (type_ is not None)


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_no_card_404_is_none_with_one_request(site, segment, type_):
    # 使用者打泛詞 → 站方查無，只花 1 個請求就放行
    site.set(_search_url("苺", type_), 404, b"No Result Found")
    assert _ja().fetch_entity_link("苺", segment) is None
    assert len(site.urls) == 1


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_200_zero_cards_is_none_with_one_request(site, segment, type_):
    site.set(_search_url("苺", type_), 200, EMPTY_WATERFALL)
    assert _ja().fetch_entity_link("苺", segment) is None
    assert len(site.urls) == 1


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_substring_link_text_rejected_after_two_requests(site, segment, type_):
    # 使用者打「苺」→ 若導演「苺原」被當成他，清單變成苺原的 569 部而不是標題含「苺」的片
    # 第二張卡的片剛好連到「苺」本人：只看第一張卡，所以仍是 None，且不為第二張卡多發請求
    site.set(_search_url("苺", type_), 200, _list_page("AAA-001", "BBB-002"))
    site.set(_detail_url("AAA-001"), 200, _detail_page((segment, "x1", "苺原")))
    site.set(_detail_url("BBB-002"), 200, _detail_page((segment, "x2", "苺")))
    assert _ja().fetch_entity_link("苺", segment) is None
    assert site.urls == [_search_url("苺", type_), _detail_url("AAA-001")]


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_longer_name_with_same_prefix_rejected(site, segment, type_):
    # 使用者打系列名 → 若最新命中的片屬另一個名稱含該字的系列、卻不比對連結文字就收，清單端出別的系列的片
    site.set(_search_url("PLATINUM+SOAP", type_), 200, _list_page("AAA-001"))
    site.set(_detail_url("AAA-001"), 200, _detail_page((segment, "x9", "PLATINUM SOAP 2")))
    assert _ja().fetch_entity_link("PLATINUM SOAP", segment) is None
    assert len(site.urls) == 2


@pytest.mark.parametrize("segment,type_,id_,text,typed", [
    ("series", None, "rvz", "PLATINUM SOAP", "PLATINUM SOAP"),
    ("director", 2, "36a", "大崎広浩治", "大崎広浩治"),
    ("label", 4, "9x", "S1 NO.1 STYLE", "S1 NO.1 STYLE"),
    ("label", 4, "9x", "S1 NO.1 STYLE", "s1no.1style"),       # fold 後相等；回傳的是站上的原文，不是使用者打的
    ("series", None, "rvz", "PLATINUM SOAP", "platinum　soap"),
])
def test_entity_link_equal_link_text_returns_id_and_site_text(site, segment, type_, id_, text, typed):
    plus = "+".join(typed.split())
    site.set(_search_url(plus, type_), 200, _list_page("SSIS-197", "SSIS-090"))
    site.set(_detail_url("SSIS-197"), 200, _detail_page((segment, id_, text)))
    assert _ja().fetch_entity_link(typed, segment) == (f"{segment}/{id_}", text)
    assert site.urls == [_search_url(plus, type_), _detail_url("SSIS-197")]


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_takes_only_the_asked_kind_of_link(site, segment, type_):
    # 詳情頁同時有 series／director／label 連結，且文字都等於輸入：只取所問的那一種
    site.set(_search_url("X", type_), 200, _list_page("AAA-001"))
    site.set(_detail_url("AAA-001"), 200, _detail_page(
        ("director", "d1", "X"), ("label", "l1", "X"), ("series", "s1", "X")))
    expected = {"series": "series/s1", "director": "director/d1", "label": "label/l1"}[segment]
    assert _ja().fetch_entity_link("X", segment) == (expected, "X")


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_other_kind_link_with_matching_text_is_not_enough(site, segment, type_):
    others = [s for s, _ in SEG_TYPE if s != segment]
    site.set(_search_url("X", type_), 200, _list_page("AAA-001"))
    site.set(_detail_url("AAA-001"), 200, _detail_page(*[(s, "o1", "X") for s in others]))
    assert _ja().fetch_entity_link("X", segment) is None


@pytest.mark.parametrize("href", [
    f"{BASE}/series/rvz", "/ja/series/rvz", "/series/rvz", "https://www.javbus.com/series/rvz",
])
def test_entity_link_accepts_absolute_relative_and_unprefixed_hrefs(site, href):
    site.set(_search_url("PLATINUM+SOAP"), 200, _list_page("SSIS-197"))
    site.set(_detail_url("SSIS-197"), 200,
             f'<html><body><div class="col-md-3 info"><a href="{href}">PLATINUM SOAP</a></div></body></html>'.encode())
    assert _ja().fetch_entity_link("PLATINUM SOAP", "series") == ("series/rvz", "PLATINUM SOAP")


def test_entity_link_empty_name_is_none_without_request(site):
    assert _ja().fetch_entity_link("", "series") is None
    assert _ja().fetch_entity_link("・ - _", "label") is None
    assert site.urls == []


def test_entity_link_unknown_segment_is_programming_error(site):
    with pytest.raises(ValueError):
        _ja().fetch_entity_link("X", "studio")
    assert site.urls == []


# ---- 傳輸層分類（邊界條件 5）：搜尋段、詳情段各一格
@pytest.mark.parametrize("segment,type_", SEG_TYPE)
@pytest.mark.parametrize("status", [403, 429, 503])
def test_entity_link_search_stage_blocked_raises_source_blocked(site, segment, type_, status):
    site.set(_search_url("X", type_), status, b"blocked")
    with pytest.raises(RuntimeError) as ei:
        _ja().fetch_entity_link("X", segment)
    assert type(ei.value) is SourceBlocked


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
@pytest.mark.parametrize("body", [NO_WATERFALL, b""])
def test_entity_link_search_stage_unreadable_raises_source_unreachable(site, segment, type_, body):
    site.set(_search_url("X", type_), 200, body)
    with pytest.raises(RuntimeError) as ei:
        _ja().fetch_entity_link("X", segment)
    assert type(ei.value) is SourceUnreachable


def _with_card(site, segment, type_):
    site.set(_search_url("X", type_), 200, _list_page("AAA-001"))


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
@pytest.mark.parametrize("status", [403, 429, 503])
def test_entity_link_detail_stage_blocked_raises_source_blocked(site, segment, type_, status):
    _with_card(site, segment, type_)
    site.set(_detail_url("AAA-001"), status, b"blocked")
    with pytest.raises(RuntimeError) as ei:
        _ja().fetch_entity_link("X", segment)
    assert type(ei.value) is SourceBlocked


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_detail_stage_404_is_none(site, segment, type_):
    _with_card(site, segment, type_)
    site.set(_detail_url("AAA-001"), 404, b"not found")
    assert _ja().fetch_entity_link("X", segment) is None


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
@pytest.mark.parametrize("body", [NO_INFO, b"", NO_WATERFALL])
def test_entity_link_detail_stage_without_info_block_raises_source_unreachable(site, segment, type_, body):
    _with_card(site, segment, type_)
    site.set(_detail_url("AAA-001"), 200, body)
    with pytest.raises(RuntimeError) as ei:
        _ja().fetch_entity_link("X", segment)
    assert type(ei.value) is SourceUnreachable


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
def test_entity_link_detail_with_info_but_no_such_link_is_none(site, segment, type_):
    # 這部片本來就沒有系列／導演／label 連結：確定不屬於，不是看不懂
    _with_card(site, segment, type_)
    site.set(_detail_url("AAA-001"), 200, _detail_page())
    assert _ja().fetch_entity_link("X", segment) is None


@pytest.mark.parametrize("segment,type_", SEG_TYPE)
@pytest.mark.parametrize("exc", [requests.Timeout("t"), requests.ConnectionError("c")])
def test_entity_link_request_errors_are_never_swallowed_into_none(site, segment, type_, exc):
    # 搜尋段沿用 T2 的 get_ids_from_search（Timeout／ConnectionError→TimeoutError）；詳情段原樣往外丟
    site.fail(_search_url("X", type_), exc)
    with pytest.raises((TimeoutError, requests.RequestException)):
        _ja().fetch_entity_link("X", segment)
    site.routes.clear()
    _with_card(site, segment, type_)
    site.fail(_detail_url("AAA-001"), exc)
    with pytest.raises(requests.RequestException) as ei:
        _ja().fetch_entity_link("X", segment)
    assert ei.value is exc


# ================================================================ provider 層：兩個傳輸方法名掛計數替身
class FakeBoundary:
    """依 (名稱) 回合成候選／連結並記錄呼叫；total＝兩個傳輸方法名的總呼叫數。"""

    def __init__(self, stars=None, links=None):
        self.stars = stars or {}      # name -> list[StarCard]
        self.links = links or {}      # (name, segment) -> (id, text) | None
        self.star_calls = []
        self.link_calls = []
        self.to_raise = None          # 下一次呼叫要丟的例外（丟一次就清掉）
        self.get_ids_calls = []

    @property
    def total(self):
        return len(self.star_calls) + len(self.link_calls)

    def _maybe_raise(self):
        if self.to_raise is not None:
            exc, self.to_raise = self.to_raise, None
            raise exc

    def search_stars(self, scraper, name):
        self.star_calls.append(name)
        self._maybe_raise()
        return list(self.stars.get(name, []))

    def fetch_entity_link(self, scraper, name, segment):
        self.link_calls.append((name, segment))
        self._maybe_raise()
        return self.links.get((name, segment))

    def get_ids_from_search(self, scraper, *a, **k):
        self.get_ids_calls.append((a, k))
        return []


@contextmanager
def _boundary(fake):
    with patch.object(JavBusScraper, "search_stars", lambda s, name: fake.search_stars(s, name)), \
         patch.object(JavBusScraper, "fetch_entity_link", lambda s, name, seg: fake.fetch_entity_link(s, name, seg)), \
         patch.object(JavBusScraper, "get_ids_from_search", lambda s, *a, **k: fake.get_ids_from_search(s, *a, **k)):
        yield fake


@pytest.fixture
def fake():
    f = FakeBoundary()
    with _boundary(f):
        yield f


def _resolve(kind, name):
    return JavBusProvider().resolve(kind, name)


# ---------------------------------------------------------------- 邊界條件 1：ACTOR
MIKAMI_PAGE = [
    StarCard("star/okq", "三上悠亜", False),
    StarCard("star/m2", "三上里穂", False),
    StarCard("star/m3", "三上江里", False),
]


@pytest.mark.parametrize("typed", ["三上悠亜", "三上 悠亜", "三上　悠亜", " 三上悠亜 ", "三上悠亜　"])
def test_actor_exact_name_accepted_including_space_variants(fake, typed):
    fake.stars = {typed: MIKAMI_PAGE}
    assert _resolve(Kind.ACTOR, typed) == EntityRef(Kind.ACTOR, "star/okq", "三上悠亜")


# 使用者在 JavBus 排第一時打「三上」想搜標題含「三上」的片 → 站方回的子字串候選（三上悠亜…）若被當同名女優，
# 只看到某一位的作品、關鍵字結果被吃掉，畫面看起來完全正常
@pytest.mark.parametrize("cards,expected", [
    pytest.param(MIKAMI_PAGE, None, id="all-substring-candidates"),
    pytest.param(MIKAMI_PAGE + [StarCard("star/exact", "三上", False)],
                 EntityRef(Kind.ACTOR, "star/exact", "三上"), id="exact-after-substring-candidates"),
    pytest.param([StarCard("star/okq", "三上悠亜", False), StarCard("star/exact", "三上", False),
                  StarCard("star/m2", "三上里穂", False)],
                 EntityRef(Kind.ACTOR, "star/exact", "三上"), id="exact-in-the-middle"),
])
def test_actor_substring_candidate_rejected(fake, cards, expected):
    fake.stars = {"三上": cards}
    assert _resolve(Kind.ACTOR, "三上") == expected


def test_actor_input_longer_than_candidate_name_is_rejected(fake):
    # 反方向的子字串：輸入比候選長，也不是同一個人
    fake.stars = {"三上悠亜子": [StarCard("star/okq", "三上悠亜", False)]}
    assert _resolve(Kind.ACTOR, "三上悠亜子") is None


# 使用者打「美咲愛」→ 站方頁面把同名無碼記錄排在有碼前，若取頁面順序第一就列出無碼那 14 部，片庫主體的有碼作品整批缺席
def test_actor_same_name_prefers_censored_record(fake):
    fake.stars = {"美咲愛": [
        StarCard("uncensored/star/23f", "美咲愛", True),   # 頁面順序：無碼在前
        StarCard("star/zz1", "美咲愛華", False),
        StarCard("uncensored/star/2f8", "Ai Misaki", True),
        StarCard("star/zz2", "美咲愛瑠", False),
        StarCard("star/36h", "美咲愛", False),             # 有碼在後
    ]}
    assert _resolve(Kind.ACTOR, "美咲愛") == EntityRef(Kind.ACTOR, "star/36h", "美咲愛")


def test_actor_only_uncensored_same_name_takes_uncensored(fake):
    fake.stars = {"美咲愛": [StarCard("star/zz1", "美咲愛華", False), StarCard("uncensored/star/23f", "美咲愛", True)]}
    assert _resolve(Kind.ACTOR, "美咲愛") == EntityRef(Kind.ACTOR, "uncensored/star/23f", "美咲愛")


def test_actor_several_censored_same_name_takes_first_in_page_order(fake):
    fake.stars = {"甲": [StarCard("star/b2", "甲", False), StarCard("star/a1", "甲", False)]}
    assert _resolve(Kind.ACTOR, "甲").id == "star/b2"


def test_actor_no_candidates_is_none(fake):
    assert _resolve(Kind.ACTOR, "甲") is None
    assert fake.star_calls == ["甲"]


# ---------------------------------------------------------------- 邊界條件 2（provider 層）
@pytest.mark.parametrize("kind,segment", [(Kind.SERIES, "series"), (Kind.DIRECTOR, "director"), (Kind.LABEL, "label")])
def test_entity_kinds_call_fetch_entity_link_with_their_segment(fake, kind, segment):
    fake.links = {("X", segment): (f"{segment}/abc", "X 原文")}
    assert _resolve(kind, "X") == EntityRef(kind, f"{segment}/abc", "X 原文")
    assert fake.link_calls == [("X", segment)]
    assert fake.star_calls == []


@pytest.mark.parametrize("kind", [Kind.SERIES, Kind.DIRECTOR, Kind.LABEL])
def test_entity_kinds_none_stays_none(fake, kind):
    assert _resolve(kind, "X") is None


def test_provider_never_searches_entities_through_get_ids_from_search(fake):
    # 離線錄製器與 T10 合約載體只掛 search_stars／fetch_entity_link；繞去一般搜尋會被錄成 KEYWORD 的 calls
    fake.links = {("X", "series"): ("series/abc", "X")}
    for kind in (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL):
        _resolve(kind, "X")
    assert fake.get_ids_calls == []


# ---------------------------------------------------------------- 邊界條件 3：快取
ALL_KINDS = [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL]


def _hit(fake, kind, name):
    if kind is Kind.ACTOR:
        fake.stars[name] = [StarCard("star/okq", name, False)]
        return EntityRef(Kind.ACTOR, "star/okq", name)
    segment = {Kind.SERIES: "series", Kind.DIRECTOR: "director", Kind.LABEL: "label"}[kind]
    fake.links[(name, segment)] = (f"{segment}/abc", name)
    return EntityRef(kind, f"{segment}/abc", name)


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("outcome", ["hit", "miss"])
def test_second_resolve_of_same_name_sends_no_request(fake, kind, outcome):
    name = "PLATINUM SOAP"
    expected = _hit(fake, kind, name) if outcome == "hit" else None
    assert _resolve(kind, name) == expected
    first = fake.total
    assert first > 0                                   # 第一次一定有發請求，否則「第二次 0」恆真
    assert _resolve(kind, name) == expected
    assert _resolve(kind, "platinum　soap") == expected   # 折疊後同一格
    assert fake.total == first


def test_name_variants_share_one_cache_cell(fake):
    fake.stars = {"三上悠亜": MIKAMI_PAGE, "三上 悠亜": MIKAMI_PAGE}
    first = _resolve(Kind.ACTOR, "三上悠亜")
    assert fake.total == 1
    assert _resolve(Kind.ACTOR, "三上 悠亜") == first
    assert _resolve(Kind.ACTOR, "三上　悠亜") == first
    assert fake.total == 1


# 使用者打系列名（例 PLATINUM SOAP）→ 梯子先問女優（查無，記入快取）再問系列；若快取鍵沒分 kind，
# 系列永遠讀到剛記的「查無」，使用者只看到標題含該字的片而不是系列清單
def test_resolve_cache_is_keyed_by_kind(fake):
    fake.links = {("PLATINUM SOAP", "series"): ("series/rvz", "PLATINUM SOAP")}
    assert _resolve(Kind.ACTOR, "PLATINUM SOAP") is None                       # 女優：確定查無，入快取
    assert _resolve(Kind.SERIES, "PLATINUM SOAP") == EntityRef(Kind.SERIES, "series/rvz", "PLATINUM SOAP")
    assert _resolve(Kind.DIRECTOR, "PLATINUM SOAP") is None
    assert _resolve(Kind.LABEL, "PLATINUM SOAP") is None
    assert fake.star_calls == ["PLATINUM SOAP"]
    assert fake.link_calls == [("PLATINUM SOAP", "series"), ("PLATINUM SOAP", "director"), ("PLATINUM SOAP", "label")]


def test_resolve_cache_hit_in_one_kind_does_not_leak_into_another(fake):
    fake.links = {("X", "series"): ("series/abc", "X")}
    assert _resolve(Kind.SERIES, "X") == EntityRef(Kind.SERIES, "series/abc", "X")
    assert _resolve(Kind.LABEL, "X") is None
    assert _resolve(Kind.SERIES, "X") == EntityRef(Kind.SERIES, "series/abc", "X")
    assert fake.link_calls == [("X", "series"), ("X", "label")]


def test_cache_over_limit_is_cleared_as_a_whole(fake, monkeypatch):
    monkeypatch.setattr(jbp, "_RESOLVE_CACHE_MAX", 2)
    for name in ("a", "b"):
        _resolve(Kind.SERIES, name)
    _resolve(Kind.SERIES, "c")                         # 第三格滿了 → 整張清空後只剩 c
    n = fake.total
    _resolve(Kind.SERIES, "c")
    assert fake.total == n                             # c 還在
    _resolve(Kind.SERIES, "a")
    assert fake.total == n + 1                         # a 已被清掉，重新查


# 例外原樣往外丟、不入快取（BE-PY-03）；是多行不變式，不靠單行 mutation
@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("exc", [
    SourceBlocked("blocked"), SourceUnreachable("unreadable"), requests.Timeout("t"), requests.ConnectionError("c"),
], ids=["SourceBlocked", "SourceUnreachable", "Timeout", "ConnectionError"])
def test_exception_not_cached_and_propagates(fake, kind, exc):
    expected = _hit(fake, kind, "甲")
    fake.to_raise = exc
    with pytest.raises(type(exc)) as ei:
        _resolve(kind, "甲")
    assert ei.value is exc
    assert fake.total == 1
    # 站方恢復後同一個字再問：必須再發請求並拿到真結果（不是被記成「查無」）
    assert _resolve(kind, "甲") == expected
    assert fake.total == 2
    assert _resolve(kind, "甲") == expected
    assert fake.total == 2


# ---------------------------------------------------------------- 邊界條件 4：不處理的 kind
@pytest.mark.parametrize("kind", [Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD])
def test_unhandled_kinds_return_none_without_any_request(fake, kind):
    assert _resolve(kind, "S1") is None
    assert fake.total == 0 and fake.get_ids_calls == []


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("blank", ["", "   ", "　", "・", " ・-_ "])
def test_blank_input_returns_none_without_any_request(fake, kind, blank):
    assert _resolve(kind, blank) is None
    assert fake.total == 0


def test_capabilities_unchanged_in_this_task():
    assert JavBusProvider.capabilities == frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE, Kind.MAKER})


@pytest.mark.parametrize("kind", [Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD])
def test_unhandled_kinds_send_no_http_request(site, kind):
    assert _resolve(kind, "S1") is None
    assert site.urls == []


# ================================================================ 端到端（罐頭傳輸）：請求預算與 /ja/ 前綴
def _ladder(name):
    return [_resolve(k, name) for k in ALL_KINDS]


def test_cold_non_entity_word_costs_four_requests_then_zero(site):
    # 使用者打「温泉」：站方四處都查無 → 4 個請求（searchstar／一般搜尋／type=2／type=4），之後同字 0 個
    assert _ladder("温泉") == [None, None, None, None]
    assert site.urls == [_star_url("温泉"), _search_url("温泉"), _search_url("温泉", 2), _search_url("温泉", 4)]
    assert _ladder("温泉") == [None, None, None, None]
    assert len(site.urls) == 4


def test_common_word_with_series_card_but_wrong_link_costs_five_requests(site):
    # 常見字：一般搜尋有卡（第一張卡的系列不是它）→ SERIES 2 個；其餘四處查無 → 共 5
    site.set(_search_url("巨乳"), 200, _list_page("AAA-001"))
    site.set(_detail_url("AAA-001"), 200, _detail_page(("series", "x1", "巨乳もの")))
    assert _ladder("巨乳") == [None, None, None, None]
    assert len(site.urls) == 5
    _ladder("巨乳")
    assert len(site.urls) == 5


def test_worst_case_costs_seven_requests(site):
    # searchstar 有卡但沒有同名；三段搜尋都有卡但連結文字都不符 → 1 + 2 + 2 + 2 = 7
    site.set(_star_url("苺"), 200, _star_page(_star_card("a1", "苺花")))
    for type_, seg in ((None, "series"), (2, "director"), (4, "label")):
        site.set(_search_url("苺", type_), 200, _list_page(f"AAA-{seg}"))
        site.set(_detail_url(f"AAA-{seg}"), 200, _detail_page((seg, "x1", "苺原")))
    assert _ladder("苺") == [None, None, None, None]
    assert len(site.urls) == 7
    _ladder("苺")
    assert len(site.urls) == 7


def test_end_to_end_hits_with_canned_transport(site):
    site.set(_star_url("三上+悠亜"), 200, _star_page(*[_star_card(c.id.split("/")[-1], c.name) for c in MIKAMI_PAGE]))
    site.set(_search_url("PLATINUM+SOAP"), 200, _list_page("SSIS-197"))
    site.set(_detail_url("SSIS-197"), 200, _detail_page(("series", "rvz", "PLATINUM SOAP"), ("label", "9x", "S1 NO.1 STYLE")))
    assert _resolve(Kind.ACTOR, "三上 悠亜") == EntityRef(Kind.ACTOR, "star/okq", "三上悠亜")
    assert _resolve(Kind.SERIES, "PLATINUM SOAP") == EntityRef(Kind.SERIES, "series/rvz", "PLATINUM SOAP")


# 使用者 UI 設繁中 → 若 resolve 改打繁中站，站上名稱是繁中字形，比對全落空，女優／系列永遠認不出而畫面照常回關鍵字結果，看起來沒壞
@pytest.mark.parametrize("ui_lang", ["zh-tw", "en", "ja"])
def test_resolve_requests_always_use_ja_prefix_regardless_of_ui_language(site, ui_lang):
    site.set(_star_url("三上悠亜"), 200, _star_page(_star_card("okq", "三上悠亜")))
    site.set(_search_url("PLATINUM+SOAP"), 200, _list_page("SSIS-197"))
    site.set(_detail_url("SSIS-197"), 200, _detail_page(("series", "rvz", "PLATINUM SOAP")))
    with patch("core.scraper.get_javbus_lang", return_value=ui_lang):
        assert _resolve(Kind.ACTOR, "三上悠亜").id == "star/okq"
        assert _resolve(Kind.SERIES, "PLATINUM SOAP").id == "series/rvz"
        _resolve(Kind.DIRECTOR, "PLATINUM SOAP")
        _resolve(Kind.LABEL, "PLATINUM SOAP")
    assert len(site.urls) == 5                      # ACTOR 1 + SERIES 2（搜尋＋詳情）+ DIRECTOR 1 + LABEL 1
    assert all(u.startswith("https://www.javbus.com/ja/") for u in site.urls), site.urls


@pytest.mark.parametrize("exc", [
    SourceBlocked("b"), SourceUnreachable("u"),
], ids=["blocked", "unreachable"])
def test_end_to_end_blocked_site_is_exception_not_none(site, exc):
    status = 403 if isinstance(exc, SourceBlocked) else 200
    body = b"blocked" if status == 403 else NO_WATERFALL
    site.set(_star_url("甲"), status, body)
    with pytest.raises(type(exc)):
        _resolve(Kind.ACTOR, "甲")
    site.routes.clear()
    assert _resolve(Kind.ACTOR, "甲") is None           # 站方恢復後同字會再問（上一次沒入快取）
    assert len(site.urls) == 2
