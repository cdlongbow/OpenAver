"""test_javbus_list_transport.py — JavBus 清單傳輸層（TASK-175c-T2，plan CD-175c-2）。

傳輸一律用「真的 requests.Session ＋ 類別層 HTTPAdapter.send 罐頭」：量得到實際送出的
Cookie 標頭與 request.url，不 patch get_ids_from_search／get_ids_from_studio（那會整段跳過傳輸）。
HTML 全為檔內合成，不收站方存檔；零活站請求。
"""
import datetime
import io
from urllib.parse import quote

import pytest
import requests
from bs4 import BeautifulSoup
from requests.structures import CaseInsensitiveDict

import core.scrapers.javbus as jb
from core.database import init_db
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.javbus import JavBusScraper
from core.search_providers.javbus import JavBusProvider

STUDIO = ("censored", "7q")
TODAY = datetime.date(2026, 10, 22)
MAKER_KEY = "sod create"
MAKER_LABEL = "SOD Create"


# ---------------------------------------------------------------- 合成 HTML
def _card(number, title="T", cover="/pics/thumb/x.jpg", date="2026-01-02"):
    return (
        f'<div class="item"><a class="movie-box" href="https://www.javbus.com/{number}">'
        f'<div class="photo-frame"><img src="{cover}" title="{title}"></div>'
        f'<div class="photo-info"><span>{title}<br><date>{number}</date> / <date>{date}</date></span></div>'
        f'</a></div>'
    )


def _list_html(numbers):
    return '<html><body><div id="waterfall">' + "".join(_card(n) for n in numbers) + "</div></body></html>"


EMPTY_WATERFALL = b'<html><body><div id="waterfall"></div></body></html>'
NO_WATERFALL = b"<html><body><p>nothing to see</p></body></html>"
OK_LIST = _list_html([f"ABC-{i:03d}" for i in range(1, 4)]).encode()


# ---------------------------------------------------------------- 罐頭傳輸
def _existmag_values(cookie_header):
    """Cookie 標頭中每個 existmag 的值（不是 `"existmag=all" in header`：mag; all 並存也會過）。"""
    return [p.split("=", 1)[1] for p in (cookie_header or "").split("; ") if p.startswith("existmag=")]


class Canned:
    def __init__(self):
        self.seen = []  # (url, [existmag 值…])
        self.out = (200, OK_LIST)

    def respond(self, status, body=b""):
        self.out = (status, body)

    def raise_(self, exc):
        self.out = exc

    @property
    def urls(self):
        return [u for u, _ in self.seen]

    @property
    def existmag(self):
        return [v for _, v in self.seen]


@pytest.fixture
def canned(monkeypatch):
    c = Canned()

    def fake_send(self, request, **kw):
        c.seen.append((request.url, _existmag_values(request.headers.get("Cookie"))))
        if isinstance(c.out, BaseException):
            raise c.out
        status, body = c.out
        r = requests.Response()
        r.status_code = status
        r.headers = CaseInsensitiveDict({})
        r.raw = io.BytesIO(body)
        r.url = request.url
        r.request = request
        return r

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return c


def _site_sets_mag(scraper):
    """站方每個回應都 Set-Cookie: existmag=mag；罐頭 Response 進不了 jar，所以這裡手動預塞同格 cookie。"""
    scraper._session.cookies.set("existmag", "mag", domain="www.javbus.com", path="/")


def _enc(plus_joined):
    """期望的 URL 路徑片段：非 ASCII 百分號編碼、`+` 保留（不 unquote_plus 比對：會把 + 與空白混為一談）。"""
    return "+".join(quote(w) for w in plus_joined.split("+"))


# ================================================================ 邊界條件 1：existmag
def test_list_get_overrides_site_set_existmag_cookie(canned):
    scraper = JavBusScraper()
    for call in (
        lambda: scraper.get_ids_from_search("abc"),
        lambda: scraper.get_ids_from_studio(STUDIO),
        lambda: scraper.get_ids_from_search("abc", page=2),
    ):
        _site_sets_mag(scraper)
        call()
    assert canned.existmag == [["all"], ["all"], ["all"]]


def test_fresh_session_first_list_request_carries_existmag_all(canned):
    JavBusScraper().get_ids_from_search("abc")
    assert canned.existmag == [["all"]]


# ================================================================ 邊界條件 2：空白 → +
@pytest.mark.parametrize("keyword,joined", [
    ("三上 悠亜", "三上+悠亜"),
    ("三上　悠亜", "三上+悠亜"),
    ("a  b", "a+b"),
    ("a 　\t b", "a+b"),
    (" a b ", "a+b"),
    ("　a b　", "a+b"),
])
def test_search_url_joins_whitespace_with_plus(canned, keyword, joined):
    JavBusScraper().get_ids_from_search(keyword)
    assert canned.urls == ["https://www.javbus.com/search/" + _enc(joined)]
    url = canned.urls[0]
    assert "%20" not in url and " " not in url
    assert not url.endswith("+") and "/search/+" not in url


@pytest.mark.parametrize("page,search_type,suffix", [
    (1, 0, ""),
    (2, 0, "/2"),
    (1, 1, "&type=1"),
    (2, 1, "/2&type=1"),
])
def test_search_url_suffix_order_unchanged(canned, page, search_type, suffix):
    JavBusScraper().get_ids_from_search("a b", page=page, search_type=search_type)
    assert canned.urls == ["https://www.javbus.com/search/a+b" + suffix]


def test_search_url_keeps_language_prefix(canned):
    JavBusScraper(lang="ja").get_ids_from_search("a b", page=2, search_type=1)
    assert canned.urls == ["https://www.javbus.com/ja/search/a+b/2&type=1"]


# ================================================================ 邊界條件 3：分類
@pytest.mark.parametrize("status", [403, 429, 503])
def test_search_blocked_status_raises_source_blocked(canned, status):
    canned.respond(status, b"blocked")
    with pytest.raises(RuntimeError) as ei:
        JavBusScraper().get_ids_from_search("abc")
    assert type(ei.value) is SourceBlocked


def _list_call(kind):
    return {
        "search": lambda s: s.get_ids_from_search("abc"),
        "studio": lambda s: s.get_ids_from_studio(STUDIO),
    }[kind]


@pytest.mark.parametrize("kind", ["search", "studio"])
def test_404_is_end_of_list(canned, kind):
    canned.respond(404, b"not found")
    assert _list_call(kind)(JavBusScraper()) == []


@pytest.mark.parametrize("kind", ["search", "studio"])
def test_200_waterfall_with_zero_cards_is_empty_list(canned, kind):
    canned.respond(200, EMPTY_WATERFALL)
    assert _list_call(kind)(JavBusScraper()) == []


@pytest.mark.parametrize("kind", ["search", "studio"])
def test_200_without_waterfall_raises_source_unreachable(canned, kind):
    canned.respond(200, NO_WATERFALL)
    with pytest.raises(RuntimeError) as ei:
        _list_call(kind)(JavBusScraper())
    assert type(ei.value) is SourceUnreachable


@pytest.mark.parametrize("exc", [
    requests.Timeout("t"), requests.ConnectionError("c"), requests.exceptions.ConnectTimeout("ct"),
    requests.exceptions.ReadTimeout("rt"),
])
def test_search_timeout_and_connection_error_become_timeout_error(canned, exc):
    canned.raise_(exc)
    with pytest.raises(TimeoutError):
        JavBusScraper().get_ids_from_search("abc")


# ================================================================ 邊界條件 4：R5／R7
@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    init_db(db)
    monkeypatch.setattr("core.maker_mapping.load_prefix_mapping", lambda: {
        "STARS": MAKER_LABEL, "SOD": MAKER_LABEL, "SDDE": MAKER_LABEL, "SDMU": MAKER_LABEL, "ABP": "Prestige"})
    monkeypatch.setattr("core.scraper.MAX_WORKERS", 1)
    monkeypatch.setattr("core.scraper.REQUEST_DELAY", 0)
    return db


def test_run_maker_probe_blocked_is_maker_unreachable_with_single_request(canned, probe_env):
    canned.respond(403, b"blocked")
    out = JavBusProvider().run_maker(
        MAKER_KEY, MAKER_LABEL, [MAKER_LABEL], 0, titles=[], today=TODAY, db_path=probe_env, limit=20)
    assert out.error_code == "maker_unreachable"
    assert len(canned.seen) == 1


@pytest.mark.parametrize("status,body", [(403, b"blocked"), (429, b"slow down"), (200, NO_WATERFALL)])
def test_search_by_keyword_never_raises_on_blocked_or_unreadable(canned, status, body):
    canned.respond(status, body)
    assert JavBusScraper().search_by_keyword("x") == []
    assert len(canned.seen) == 1


# ================================================================ 邊界條件 5：ListCard 單一 parser
THREE_CARDS = """
<html><body><div id="waterfall">
  <div class="item"><a class="movie-box" href="https://www.javbus.com/ABC-001">
    <div class="photo-frame"><img src="/pics/thumb/a.jpg" title="Title One"></div>
    <div class="photo-info"><span>Title One<br><date>ABC-001</date> / <date>2026-01-02</date></span></div></a></div>
  <div class="item"><a class="movie-box" href="https://www.javbus.com/XYZ-002/">
    <div class="photo-frame"><img src="/pics/thumb/b.jpg" title="Title Two"></div>
    <div class="photo-info"><span>Title Two</span></div></a></div>
  <div class="item"><a class="movie-box" href="https://www.javbus.com/DEF-003">
    <div class="photo-frame"><img src="/pics/thumb/c.jpg"></div>
    <div class="photo-info"><span><date>DEF-003</date> / <date>2026-03-04</date></span></div></a></div>
</div></body></html>
"""


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def test_parse_list_cards_reads_number_title_cover_date():
    cards = JavBusScraper()._parse_list_cards(_soup(THREE_CARDS))
    assert cards == [
        jb.ListCard("ABC-001", "Title One", "/pics/thumb/a.jpg", "2026-01-02"),  # 雙 <date>
        jb.ListCard("XYZ-002", "Title Two", "/pics/thumb/b.jpg", ""),            # 缺 <date>：番號靠 href、無日期
        jb.ListCard("DEF-003", "", "/pics/thumb/c.jpg", "2026-03-04"),           # 缺 img[title]
    ]


def _legacy_parse_search_ids(soup):
    """改前的 _parse_search_ids（逐字語意），作為薄包裝輸出相同的 oracle。"""
    ids = []
    waterfall = soup.find(id="waterfall")
    if not waterfall:
        return []
    for card in waterfall.find_all("a", class_="movie-box"):
        dates = card.find_all("date")
        if dates:
            number = dates[0].get_text(strip=True)
            if number:
                ids.append(number)
        else:
            href = card.get("href", "")
            if href:
                number = href.rstrip("/").split("/")[-1]
                if number:
                    ids.append(number)
    return ids


EQUIVALENCE_CASES = {
    "three_cards": THREE_CARDS,
    "no_waterfall": "<html><body><a class='movie-box' href='/A-1'><date>A-1</date></a></body></html>",
    "empty_waterfall": '<div id="waterfall"></div>',
    # 有 <date> 但番號為空：丟棄，且不退 href
    "empty_first_date": '<div id="waterfall"><a class="movie-box" href="/A-1"><date> </date><date>2026-01-01</date></a></div>',
    # 無 <date>：退 href 最後一段；href 空或只有斜線則丟棄
    "href_fallback": ('<div id="waterfall"><a class="movie-box" href="/ja/A-1/"></a>'
                      '<a class="movie-box" href=""></a><a class="movie-box"></a>'
                      '<a class="movie-box" href="/"></a><a class="movie-box" href="B-2"></a></div>'),
    "mixed_order": ('<div id="waterfall"><a class="movie-box" href="/X-1"><date>Y-9</date></a>'
                    '<a class="movie-box" href="/Z-3"></a><a class="other" href="/Q-1"><date>Q-1</date></a></div>'),
    "date_with_inner_whitespace": '<div id="waterfall"><a class="movie-box" href="/A"><date>\n AB-12 \n</date></a></div>',
}


@pytest.mark.parametrize("name", sorted(EQUIVALENCE_CASES))
def test_parse_search_ids_matches_legacy_output_itemwise(name):
    scraper = JavBusScraper()
    html = EQUIVALENCE_CASES[name]
    assert scraper._parse_search_ids(_soup(html)) == _legacy_parse_search_ids(_soup(html))
    assert scraper._parse_search_ids(_soup(html)) == [c.number for c in scraper._parse_list_cards(_soup(html))]
