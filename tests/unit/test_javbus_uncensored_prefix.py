"""test_javbus_uncensored_prefix.py — JavBus 無碼前綴重試＋四個取頁入口收斂（TASK-175c-T5，plan CD-175c-5）。

邊界條件 1／3／4 走「真 JavBusScraper（真 requests.Session）＋類別層 HTTPAdapter.send 罐頭」，
斷言實際送出的完整 URL 序列（不 patch get_ids_from_search）；罐頭依「完整 URL」路由，沒登記的回 404
（＝站方的「沒有」）。一般 URL `…/search/HEYZO&type=1` 是無碼 URL `…/uncensored/search/HEYZO&type=1`
的子字串，所以不能用子字串路由。邊界條件 5 用類別層腳本化 get_ids_from_search。
HTML 全為檔內合成，不收站方存檔；零活站請求。relay 讀的語系 patch 在使用端（core.scraper.*，BE-TEST-01）。
"""
import io

import pytest
import requests
from requests.structures import CaseInsensitiveDict

import core.scraper as scraper_mod
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.javbus import JavBusScraper
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import EntityRef, Kind, Window

BASE = "https://www.javbus.com"
LANG_PREFIX = {"ja": "/ja", "zh-tw": ""}
NO_WATERFALL = b"<html><body><p>nothing to see</p></body></html>"


# ---------------------------------------------------------------- 合成 HTML
def _card(number):
    return (
        f'<div class="item"><a class="movie-box" href="{BASE}/{number}">'
        f'<div class="photo-frame"><img src="/pics/thumb/x.jpg" title="T"></div>'
        f'<div class="photo-info"><span>T<br><date>{number}</date> / <date>2026-01-02</date></span></div>'
        f'</a></div>'
    )


def _list_html(numbers):
    return ('<html><body><div id="waterfall">' + "".join(_card(n) for n in numbers) + "</div></body></html>").encode()


def _nums(prefix, start, count):
    return [f"{prefix}-{i:04d}" for i in range(start, start + count)]


def normal_url(kw, page=1, lang="zh-tw"):
    return f"{BASE}{LANG_PREFIX[lang]}/search/{kw}" + (f"/{page}" if page > 1 else "") + "&type=1"


def unc_url(kw, page=1, lang="zh-tw"):
    return f"{BASE}{LANG_PREFIX[lang]}/uncensored/search/{kw}" + (f"/{page}" if page > 1 else "") + "&type=1"


def kw_url(kw, page=1, lang="zh-tw"):
    return f"{BASE}{LANG_PREFIX[lang]}/search/{kw}" + (f"/{page}" if page > 1 else "")


# ---------------------------------------------------------------- 罐頭傳輸（依完整 URL 路由）
def _existmag_values(cookie_header):
    return [p.split("=", 1)[1] for p in (cookie_header or "").split("; ") if p.startswith("existmag=")]


class Net:
    def __init__(self):
        self.routes = {}  # 完整 URL → (status, body) 或例外
        self.seen = []  # (url, [existmag 值…])

    def listing(self, url, numbers):
        self.routes[url] = (200, _list_html(numbers))

    def status(self, url, status, body=b"x"):
        self.routes[url] = (status, body)

    def fail(self, url, exc):
        self.routes[url] = exc

    @property
    def urls(self):
        return [u for u, _ in self.seen]

    @property
    def existmag(self):
        return [v for _, v in self.seen]


@pytest.fixture
def env(monkeypatch):
    """語系預設 zh-tw；search_jav 回合成詳情（patch 使用端）。"""
    monkeypatch.setattr(scraper_mod, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scraper_mod, "search_jav",
        lambda number, source: {"number": number, "title": f"t {number}", "date": "2026-01-02"},
    )
    return monkeypatch


@pytest.fixture
def net(env):
    n = Net()

    def fake_send(self, request, **kw):
        n.seen.append((request.url, _existmag_values(request.headers.get("Cookie"))))
        out = n.routes.get(request.url, (404, b"not found"))
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

    env.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return n


def _set_lang(env, lang):
    env.setattr(scraper_mod, "get_javbus_lang", lambda: lang)


# ---------------------------------------------------------------- 四個入口（同一個呼叫形狀）
def _code_ref(prefix):
    return EntityRef(Kind.CODE, prefix, prefix)


class Run:
    """run_prefix／run_keyword 的結果：numbers（discovery_only 的清單）＋事件序列。"""

    def __init__(self, numbers, events):
        self.numbers = numbers
        self.events = events


def run_prefix(prefix, w, *, discovery_only=True):
    events = []
    out = JavBusProvider().run_prefix(prefix, w.limit, w.offset, lambda s, g: events.append((s, g)), None, discovery_only)
    return Run([c["number"] for c in out], events)


def run_keyword(name, w, *, discovery_only=True):
    events = []
    out = JavBusProvider().run_keyword(name, w.limit, w.offset, lambda s, g: events.append((s, g)), None, discovery_only)
    return Run([c["number"] for c in out], events)


def list_code(prefix, w):
    return [i.number for i in JavBusProvider().list_entity(_code_ref(prefix), w).items]


def search_keyword(name, w):
    return [i.number for i in JavBusProvider().search_keyword(name, w).items]


CODE_ENTRIES = {
    "run_prefix": lambda kw, w: run_prefix(kw, w).numbers,
    "list_entity": list_code,
}


# ================================================================ 邊界條件 1：無碼重試
# 使用者在搜尋框打 HEYZO 這類無碼前綴 → 一般搜尋 404，沒有改問無碼區就永遠顯示「查無」，
# 使用者以為站上沒有這個片商的片，其實有三千多部
@pytest.mark.parametrize("lang", ["ja", "zh-tw"])
def test_prefix_with_no_ids_in_window_retries_uncensored_section(net, env, lang):
    _set_lang(env, lang)
    heyzo = _nums("HEYZO", 1, 3)
    net.listing(unc_url("HEYZO", lang=lang), heyzo)

    events = []
    cards = JavBusProvider().run_prefix("HEYZO", 20, 0, lambda s, g: events.append((s, g)), None, False)

    assert sorted(c["number"] for c in cards) == heyzo
    assert net.urls[:2] == [normal_url("HEYZO", lang=lang), unc_url("HEYZO", lang=lang)]
    assert all("/uncensored/" in u for u in net.urls[1:])
    assert events[0] == ("javbus", "searching")
    assert ("javbus", "found:3") in events
    assert events[-1] == ("done", "found:3")
    assert net.existmag[1] == ["all"]  # 無碼區的請求同樣帶 existmag=all


@pytest.mark.parametrize("lang", ["ja", "zh-tw"])
def test_list_entity_code_retries_uncensored_section(net, env, lang):
    _set_lang(env, lang)
    heyzo = _nums("HEYZO", 1, 3)
    net.listing(unc_url("HEYZO", lang=lang), heyzo)

    page = JavBusProvider().list_entity(_code_ref("HEYZO"), Window(0, 20))

    assert [i.number for i in page.items] == heyzo
    assert net.urls[:2] == [normal_url("HEYZO", lang=lang), unc_url("HEYZO", lang=lang)]
    assert all("/uncensored/" in u for u in net.urls[1:])
    assert net.existmag[1] == ["all"]


@pytest.mark.parametrize("entry", ["run_prefix", "list_entity"])
def test_uncensored_retry_keeps_plus_rule(net, entry):
    """空白 → `+`（不是 %20）的規則在無碼區沿用：HEY ZO → HEY+ZO。"""
    net.listing(unc_url("HEY+ZO"), _nums("HEYZO", 1, 3))

    assert CODE_ENTRIES[entry]("HEY ZO", Window(0, 20)) == _nums("HEYZO", 1, 3)
    assert net.urls[:2] == [normal_url("HEY+ZO"), unc_url("HEY+ZO")]
    assert not any("%20" in u or " " in u for u in net.urls)


@pytest.mark.parametrize("lang,seg", [("ja", "/ja"), ("zh-tw", "")])
def test_get_ids_from_search_uncensored_url_shape(net, lang, seg):
    """`/uncensored` 接在語系前綴之後、`/search/` 之前；頁碼與 &type= 尾綴順序不變。"""
    net.listing(f"{BASE}{seg}/uncensored/search/HEY+ZO/2&type=1", _nums("HEYZO", 1, 2))

    ids = JavBusScraper(lang=lang).get_ids_from_search("HEY ZO", page=2, search_type=1, uncensored=True)

    assert ids == _nums("HEYZO", 1, 2)
    assert net.urls == [f"{BASE}{seg}/uncensored/search/HEY+ZO/2&type=1"]
    assert net.existmag == [["all"]]


def test_get_ids_from_search_default_url_is_unchanged(net):
    JavBusScraper(lang="ja").get_ids_from_search("HEYZO", page=2, search_type=1)
    JavBusScraper(lang="ja").get_ids_from_search("HEYZO", page=1)
    assert net.urls == [f"{BASE}/ja/search/HEYZO/2&type=1", f"{BASE}/ja/search/HEYZO"]


# ================================================================ 邊界條件 2：有結果不問無碼
# 使用者打 MIDV 這類有碼前綴（每次搜尋、每次載入更多）→ 一般有結果也照問無碼區，每次多打一個請求到 JavBus，
# 請求量翻倍、被擋風險上升（IP 信譽），畫面上看不出來
HIT_SCENARIOS = {
    "first_page": (Window(0, 20), {1: _nums("MIDV", 1, 5)}),
    "offset_inside_page": (Window(10, 5), {1: _nums("MIDV", 1, 30)}),
    "cross_page": (Window(25, 10), {1: _nums("MIDV", 1, 30), 2: _nums("MIDV", 31, 12)}),
    "second_page_404": (Window(0, 40), {1: _nums("MIDV", 1, 30)}),
    "slice_empty_but_page_has_ids": (Window(40, 20), {1: _nums("MIDV", 1, 30), 2: _nums("MIDV", 31, 12)}),
}


@pytest.mark.parametrize("scenario", list(HIT_SCENARIOS))
@pytest.mark.parametrize("entry", ["run_prefix", "list_entity"])
def test_normal_hit_never_asks_uncensored_section(net, entry, scenario):
    w, pages = HIT_SCENARIOS[scenario]
    all_ids = [n for p in sorted(pages) for n in pages[p]]
    for p, ids in pages.items():
        net.listing(normal_url("MIDV", p), ids)
    for p in (1, 2, 3):  # 無碼區若被問到會回「不同於一般」的番號，結果一變就抓得到
        net.listing(unc_url("MIDV", p), _nums("OOPS", 1, 30))

    got = CODE_ENTRIES[entry]("MIDV", w)

    assert got == all_ids[w.offset:w.offset + w.limit]
    assert not any(n.startswith("OOPS") for n in got)
    assert not any("/uncensored/" in u for u in net.urls)


def test_normal_path_get_ids_calls_carry_no_uncensored_kwarg(env):
    """一般路徑不得顯式傳 uncensored=False（離線 golden 的 calls 型別敏感）；只有重試傳 uncensored=True。"""
    calls = []

    def recorder(self, *args, **kwargs):
        calls.append((args, kwargs))
        return _nums("MIDV", 1, 30) if args[0] == "MIDV" and "uncensored" not in kwargs and kwargs.get("page") == 1 else []

    env.setattr(JavBusScraper, "get_ids_from_search", recorder)

    run_prefix("MIDV", Window(0, 20))
    list_code("MIDV", Window(0, 20))
    run_keyword("MIDV", Window(0, 20))
    search_keyword("MIDV", Window(0, 20))
    assert calls == [(("MIDV",), {"page": 1, "search_type": 1})] * 2 + [(("MIDV",), {"page": 1})] * 2

    calls.clear()
    run_prefix("HEYZO", Window(0, 20))  # 一般整段無 id → 重試
    assert calls == [
        (("HEYZO",), {"page": 1, "search_type": 1}),
        (("HEYZO",), {"page": 1, "search_type": 1, "uncensored": True}),
    ]


@pytest.mark.parametrize("entry", ["run_keyword", "search_keyword"])
def test_keyword_entries_never_ask_uncensored_section(net, entry):
    """關鍵字兩入口不重試：一般 404 就是尾端，恰 1 個請求。"""
    net.listing(f"{BASE}/uncensored/search/HEYZO&type=1", _nums("HEYZO", 1, 3))
    net.listing(f"{BASE}/uncensored/search/HEYZO", _nums("HEYZO", 1, 3))

    got = {"run_keyword": lambda: run_keyword("HEYZO", Window(0, 20)).numbers,
           "search_keyword": lambda: search_keyword("HEYZO", Window(0, 20))}[entry]()

    assert got == []
    assert net.urls == [kw_url("HEYZO")]


# ================================================================ 邊界條件 3：載入更多
# 使用者在 HEYZO 結果按「載入更多」→ 無碼區若永遠取第一頁，第二批又是第一批的片，畫面重複、
# 永遠看不到後面的片，而筆數看起來沒少
@pytest.mark.parametrize("lang", ["ja", "zh-tw"])
@pytest.mark.parametrize("entry", ["run_prefix", "list_entity"])
def test_load_more_retry_uses_the_same_window_page(net, env, entry, lang):
    _set_lang(env, lang)
    first_batch, second_batch = _nums("HEYZO", 1, 30), _nums("HEYZO", 31, 5)
    net.listing(unc_url("HEYZO", 1, lang), first_batch)
    net.listing(unc_url("HEYZO", 2, lang), second_batch)

    got = CODE_ENTRIES[entry]("HEYZO", Window(30, 20))

    assert got == second_batch
    assert net.urls[:2] == [normal_url("HEYZO", 2, lang), unc_url("HEYZO", 2, lang)]
    assert all("/uncensored/" in u for u in net.urls[1:])


# ================================================================ 邊界條件 4：被擋不是查無
# 站方暫擋時 403 若被當成「沒有」而去撞無碼區 → 使用者看到「查無」而不是換下一家，且對正在擋的站多送一個請求
BLOCKED_VARIANTS = {
    "403": (lambda net, url: net.status(url, 403, b"blocked"), SourceBlocked),
    "429": (lambda net, url: net.status(url, 429, b"slow down"), SourceBlocked),
    "503": (lambda net, url: net.status(url, 503, b"busy"), SourceBlocked),
    "200_no_waterfall": (lambda net, url: net.status(url, 200, NO_WATERFALL), SourceUnreachable),
    "timeout": (lambda net, url: net.fail(url, requests.Timeout("slow")), TimeoutError),
    "connection_error": (lambda net, url: net.fail(url, requests.ConnectionError("down")), TimeoutError),
}


def _expect_error(entry, expected, w=Window(0, 20)):
    """把一個入口的結果轉成 (回傳 or 例外型別, 事件)；list_entity 往外丟、run_prefix 吞掉回 []。"""
    if entry == "list_entity":
        with pytest.raises(Exception) as ei:
            list_code("HEYZO", w)
        assert type(ei.value) is expected
        return None
    r = run_prefix("HEYZO", w)
    assert r.numbers == []
    return r.events


@pytest.mark.parametrize("variant", list(BLOCKED_VARIANTS))
@pytest.mark.parametrize("entry", ["run_prefix", "list_entity"])
def test_blocked_normal_request_never_falls_through_to_uncensored(net, entry, variant):
    arm, expected = BLOCKED_VARIANTS[variant]
    arm(net, normal_url("HEYZO"))
    net.listing(unc_url("HEYZO"), _nums("OOPS", 1, 3))  # 無碼區若被問到會回有效清單：被擋時一個請求都不該送去

    events = _expect_error(entry, expected)

    assert net.urls == [normal_url("HEYZO")]
    if entry == "run_prefix":
        assert events == [("javbus", "searching"), ("done", "found:0")]


@pytest.mark.parametrize("variant", ["403", "429", "503", "200_no_waterfall", "timeout", "connection_error"])
@pytest.mark.parametrize("entry", ["run_prefix", "list_entity"])
def test_uncensored_section_blocked_is_not_a_miss(net, entry, variant):
    """一般 404（站方的「沒有」）＋無碼區被擋 → 與被擋同一個結局，不是「查無」。"""
    arm, expected = BLOCKED_VARIANTS[variant]
    arm(net, unc_url("HEYZO"))

    events = _expect_error(entry, expected)

    assert net.urls == [normal_url("HEYZO"), unc_url("HEYZO")]
    if entry == "run_prefix":
        assert events == [("javbus", "searching"), ("done", "found:0")]


def test_both_sections_404_is_a_real_miss(net):
    r = run_prefix("HEYZO", Window(0, 20))
    assert r.numbers == []
    assert r.events == [("javbus", "searching"), ("javbus", "found:0")]
    assert net.urls == [normal_url("HEYZO"), unc_url("HEYZO")]

    net.seen.clear()
    assert JavBusProvider().list_entity(_code_ref("HEYZO"), Window(0, 20)).items == []
    assert net.urls == [normal_url("HEYZO"), unc_url("HEYZO")]


# ================================================================ 邊界條件 5：四入口一致
PAGE1, PAGE2 = _nums("MIDV", 1, 30), _nums("MIDV", 31, 12)
ALL_IDS = PAGE1 + PAGE2
WINDOWS = [Window(0, 20), Window(20, 20), Window(30, 20), Window(40, 20), Window(60, 20)]


@pytest.fixture
def scripted(env):
    """類別層腳本化清單：頁 1＝30 筆、頁 2＝12 筆、頁 3 起空；無碼區一律空。"""
    def get_ids(self, keyword, page=1, search_type=0, uncensored=False):
        if uncensored:
            return []
        return list({1: PAGE1, 2: PAGE2}.get(page, []))

    env.setattr(JavBusScraper, "get_ids_from_search", get_ids)
    return env


def _entries(w):
    return {
        "run_prefix": run_prefix("MIDV", w).numbers,
        "list_entity": list_code("MIDV", w),
        "run_keyword": run_keyword("MIDV", w).numbers,
        "search_keyword": search_keyword("MIDV", w),
    }


# 使用者搜關鍵字後按「載入更多」→ run_keyword 若自己算視窗而不與共用取頁一致，第二批變成第一批的片，
# 畫面重複而筆數看起來正常
@pytest.mark.parametrize("w", WINDOWS, ids=lambda w: f"offset{w.offset}_limit{w.limit}")
def test_four_entries_slice_the_same_window(scripted, w):
    expected = ALL_IDS[w.offset:w.offset + w.limit]
    assert _entries(w) == {k: expected for k in ("run_prefix", "list_entity", "run_keyword", "search_keyword")}


def test_four_entries_agree_when_blocked(env):
    """兩層契約：list_entity／search_keyword 往外丟 SourceBlocked；run_prefix／run_keyword 吞掉回 []。"""
    def blocked(self, keyword, page=1, search_type=0, uncensored=False):
        raise SourceBlocked("HTTP 403")

    env.setattr(JavBusScraper, "get_ids_from_search", blocked)

    for call in (lambda: list_code("MIDV", Window(0, 20)), lambda: search_keyword("MIDV", Window(0, 20))):
        with pytest.raises(Exception) as ei:
            call()
        assert type(ei.value) is SourceBlocked
    assert run_prefix("MIDV", Window(0, 20)).numbers == []
    assert run_keyword("MIDV", Window(0, 20)).numbers == []
