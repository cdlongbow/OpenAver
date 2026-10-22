"""test_javbus_entity_list.py — JavBus 實體清單＋守衛 belongs＋宣告能力（TASK-175c-T4，plan CD-175c-4）。

兩層：
- scraper 層：真 requests.Session ＋ 類別層 HTTPAdapter.send 罐頭（量實際 URL／Cookie），或對 `_parse_detail_page`
  餵內嵌合成 HTML。
- relay 層：真 registry ＋ 真 JavBusProvider ＋ 假後備 provider，只 patch 傳輸方法名
  （search_stars／fetch_entity_link／get_entries_from_entity／search），不 patch resolve／list_entity／enrich
  （那會跳過本 task 要驗的接線）。

HTML／Video 全為檔內合成，不收站方存檔；零活站請求。
"""
from __future__ import annotations

import concurrent.futures as cf
import io
import time
from unittest.mock import MagicMock, patch

import pytest
import requests
from bs4 import BeautifulSoup
from requests.structures import CaseInsensitiveDict

import core.scraper as scraper_mod
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.javbus import FIELD_LABELS, JavBusScraper, ListCard, StarCard
from core.scrapers.models import Actress, Video
from core.search_providers import registry, relay
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import Enriched, EntityRef, Kind, Window, WorkItem

BASE = "https://www.javbus.com"


# ================================================================ build_card 特徵向量（邊界條件 5）
# 期望 dict 是在 core/scraper.py 未改動（HEAD）時由 search_jav 算出、字面貼回的常數；抽出 build_card 前後都必須相等。
# 〔使用者按「補齊」或搜番號 → 若抽出後卡片多／少一個鍵或補錯片商，書籤／NFO／片庫逐欄吃到的資料就悄悄變了〕
def _vec_video_with_maker() -> Video:
    return Video(
        number="SSIS-001", title="Maker Present", actresses=[Actress(name="Alice"), Actress(name="Bob")],
        date="2026-01-02", maker="MakerA", cover_url="https://img.example/c.jpg", tags=["t1", "t2"],
        source="javbus", detail_url="https://www.javbus.com/ja/SSIS-001", director="Dir", duration=120,
        label="Lab", series="Ser", sample_images=["https://img.example/s1.jpg"],
        entity_ids={"actors": ["2xi", "w5a"], "director": ["o7"], "series": ["fg8"], "label": ["9x"]},
    )


def _vec_video_maker_from_prefix() -> Video:
    return Video(number="ABC-123", title="No Maker Known Prefix", date="2026-02-03", source="javbus",
                 detail_url="https://www.javbus.com/ja/ABC-123", entity_ids={"actors": ["zz1"]})


def _vec_video_summary_rating() -> Video:
    return Video(number="SSIS-002", title="With Summary", maker="MakerB", source="javbus",
                 summary="the plot", rating=4.5, votes=12, preview_cover_url="https://img.example/p.jpg")


def _vec_video_unknown_prefix() -> Video:
    return Video(number="ZZZ-999", title="Unknown Prefix", source="javbus")


VECTOR_CASES = [
    (_vec_video_with_maker, "SSIS-001"),
    (_vec_video_maker_from_prefix, "ABC-123"),
    (_vec_video_summary_rating, "SSIS-002"),
    (_vec_video_unknown_prefix, "ZZZ-999"),
]


def _fixed_maker_by_prefix(number):
    return "PrefixMaker" if number.upper().startswith("ABC-") else ""


@pytest.fixture
def card_env(monkeypatch):
    """build_card／search_jav 尾段的外部輸入固定下來：前綴對照表與片商正名表不吃真檔。"""
    monkeypatch.setattr("core.scraper.get_maker_by_prefix", _fixed_maker_by_prefix)
    monkeypatch.setattr("core.maker_mapping.load_name_mapping", lambda: {"MakerA": "MakerA-Normalized"})


def _search_jav_card(make_video, number):
    with patch.object(scraper_mod.JavBusScraper, "search", return_value=make_video()):
        return scraper_mod.search_jav(number, "javbus", javbus_lang="ja")


EXPECTED_VECTORS = {
    # 在 core/scraper.py 未改動時由 search_jav 輸出字面貼回（含 entity_ids 非空的那組：不得多出任何鍵）
    "SSIS-001": {
        'number': 'SSIS-001', 'title': 'Maker Present', 'actors': ['Alice', 'Bob'], 'date': '2026-01-02',
        'maker': 'MakerA-Normalized', 'cover': 'https://img.example/c.jpg', 'preview_cover_url': '',
        'tags': ['t1', 't2'], 'source': 'javbus', 'url': 'https://www.javbus.com/ja/SSIS-001',
        'director': 'Dir', 'duration': 120, 'label': 'Lab', 'series': 'Ser',
        'sample_images': ['https://img.example/s1.jpg'], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
    "ABC-123": {
        'number': 'ABC-123', 'title': 'No Maker Known Prefix', 'actors': [], 'date': '2026-02-03',
        'maker': 'PrefixMaker', 'cover': '', 'preview_cover_url': '', 'tags': [], 'source': 'javbus',
        'url': 'https://www.javbus.com/ja/ABC-123', 'director': '', 'duration': None, 'label': '', 'series': '',
        'sample_images': [], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
    "SSIS-002": {
        'number': 'SSIS-002', 'title': 'With Summary', 'actors': [], 'date': '', 'maker': 'MakerB', 'cover': '',
        'preview_cover_url': 'https://img.example/p.jpg', 'tags': [], 'source': 'javbus', 'url': '',
        'director': '', 'duration': None, 'label': '', 'series': '', 'sample_images': [],
        'preview_sample_images': [],
        '_source': 'javbus', '_summary': 'the plot', '_rating': 4.5,
    },
    "ZZZ-999": {
        'number': 'ZZZ-999', 'title': 'Unknown Prefix', 'actors': [], 'date': '', 'maker': '', 'cover': '',
        'preview_cover_url': '', 'tags': [], 'source': 'javbus', 'url': '', 'director': '', 'duration': None,
        'label': '', 'series': '', 'sample_images': [], 'preview_sample_images': [],
        '_source': 'javbus', '_summary': '', '_rating': None,
    },
}


@pytest.mark.parametrize("make_video,number", VECTOR_CASES, ids=[n for _, n in VECTOR_CASES])
def test_search_jav_card_vector_is_bit_for_bit(card_env, make_video, number):
    """特徵測試（改前綠、抽出後仍綠）：整個 dict 逐位元比對，不是鍵子集；涵蓋 to_legacy_dict 不輸出 entity_ids。"""
    assert _search_jav_card(make_video, number) == EXPECTED_VECTORS[number]


def test_build_card_matches_search_jav_vector(card_env):
    """抽出的 build_card 對同一組 Video 產出與 HEAD 的 search_jav 完全相同的 dict（RED：抽出前不存在）。"""
    from core.scraper import build_card

    for make_video, number in VECTOR_CASES:
        assert build_card(make_video(), number) == EXPECTED_VECTORS[number]


# ================================================================ 合成 HTML
def _list_card(number, title="T", cover="/pics/thumb/x.jpg", date="2026-01-02"):
    return (
        f'<div class="item"><a class="movie-box" href="{BASE}/ja/{number}">'
        f'<div class="photo-frame"><img src="{cover}" title="{title}"></div>'
        f'<div class="photo-info"><span>{title}<br><date>{number}</date> / <date>{date}</date></span></div>'
        f"</a></div>"
    )


def _entity_html(cards):
    return ('<html><body><div id="waterfall">' + "".join(cards) + "</div></body></html>").encode()


NO_WATERFALL = b"<html><body><p>nothing to see</p></body></html>"
EMPTY_WATERFALL = b'<html><body><div id="waterfall"></div></body></html>'


def _numbered(first, last, **kw):
    return [_list_card(f"AAA-{i:03d}", **kw) for i in range(first, last + 1)]


def _detail_html(actors=(), *, director=None, series=None, label=None, outside=(), prefix=f"{BASE}/ja", labels=None):
    """真頁形狀：info 內女優連結出現三次（star-box 的 img 連結、star-name、尾端 genre span），
    info 之外另有 avatar-waterfall 一份。actors＝[(代號, 連結文字)…]；director／series／label＝(代號, 文字)。"""
    lb = FIELD_LABELS["ja"] if labels is None else labels

    def link(seg, code, text):
        return f'<a href="{prefix}/{seg}/{code}">{text}</a>'

    def single(field, seg, value):
        return f'<p><span class="header">{lb[field]}:</span> {link(seg, *value)}</p>' if value else ""

    boxes = "".join(
        f'<li><div class="star-box">{link("star", code, "")}<div class="star-name">{link("star", code, text)}</div></div></li>'
        for code, text in actors)
    tail = "".join(f'<span class="genre">{link("star", code, text)}</span>' for code, text in actors)
    info = (
        f'<p><span class="header">{lb["number"]}:</span> <span>SSIS-001</span></p>'
        f'<p><span class="header">{lb["date"]}:</span> 2026-01-02</p>'
        f'<p><span class="header">{lb["duration"]}:</span> 120</p>'
        + single("director", "director", director)
        + single("maker", "studio", ("7q", "Maker"))
        + single("label", "label", label)
        + single("series", "series", series)
        + f'<p class="header">{lb["tags"]}:</p>'
        + f'<p><span class="genre"><label>{link("genre", "e", "Genre1")}</label></span></p>'
        + f'<p class="star-show"><span class="glyphicon glyphicon-info-sign"></span>{lb["actresses"]}:</p>'
        + f"<ul>{boxes}</ul><p>{tail}</p>"
    )
    outer = "".join(
        f'<div class="star-div"><div class="avatar-waterfall">{link("star", code, "Outsider")}</div></div>'
        for code in outside)
    return (
        '<html><body><div class="container"><h3>SSIS-001 Title</h3>'
        '<div class="row movie"><div class="col-md-9 screencap">'
        '<a class="bigImage" href="/pics/cover/x_b.jpg"><img src="/pics/thumb/x.jpg" title="Title"></a></div>'
        f'<div class="col-md-3 info">{info}</div></div>{outer}</div></body></html>'
    )


# ================================================================ 傳輸替身
class Canned:
    """類別層 HTTPAdapter.send 罐頭（照 test_javbus_list_transport.Canned）：依 URL 回 (status, body) 或丟例外。"""

    def __init__(self):
        self.seen = []  # (url, [existmag 值…])
        self.routes = {}
        self.default = (404, b"")

    def reply(self, url, status, body=b""):
        self.routes[url] = (status, body)

    def reply_all(self, status, body=b""):
        self.default = (status, body)

    def raise_all(self, exc):
        self.default = exc

    @property
    def urls(self):
        return [u for u, _ in self.seen]

    @property
    def existmag(self):
        return [v for _, v in self.seen]


def _existmag_values(cookie_header):
    """Cookie 標頭中每個 existmag 的值（不是 `"existmag=all" in header`：mag; all 並存也會過）。"""
    return [p.split("=", 1)[1] for p in (cookie_header or "").split("; ") if p.startswith("existmag=")]


@pytest.fixture
def canned(monkeypatch):
    c = Canned()

    def fake_send(self, request, **kw):
        c.seen.append((request.url, _existmag_values(request.headers.get("Cookie"))))
        out = c.routes.get(request.url, c.default)
        if isinstance(out, BaseException):
            raise out
        r = requests.Response()
        r.status_code, body = out
        r.headers = CaseInsensitiveDict({})
        r.raw = io.BytesIO(body)
        r.url = request.url
        r.request = request
        return r

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return c


def _site_sets_mag(scraper):
    """站方每個回應都 Set-Cookie: existmag=mag；罐頭 Response 進不了 jar，所以手動預塞同格 cookie。"""
    scraper._session.cookies.set("existmag", "mag", domain="www.javbus.com", path="/")


class SyncExecutor:
    def __init__(self, max_workers=None, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        fut = cf.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """pipeline 每部詳情後 sleep REQUEST_DELAY、詳情解析 rate_limit 也 sleep：全換掉；執行緒池換成同步（完成順序＝提交順序）。
    UI 語言固定 zh-tw：實體清單必須仍走 /ja，實體路徑詳情必須走 UI 語系。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr("core.scraper.get_javbus_lang", lambda: "zh-tw")


class Other:
    """後備 provider（假 DMM）：run 回預設 cards 並記錄呼叫的 kind。"""

    capabilities = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE})

    def __init__(self, pid, cards=(), discovery=False):
        self.id = pid
        self.supports_discovery = discovery
        self.fallback_streaming = True
        self.cards = list(cards)
        self.run_calls = []

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append(kind)
        return list(self.cards)


@pytest.fixture
def chain(monkeypatch):
    """真 registry 的 javbus ＋ 假 dmm；順序與開關 patch core.scraper.*（BE-TEST-01／02）。"""
    def setup(*, dmm_cards=(), discovery=False, order=("javbus", "dmm")):
        dmm = Other("dmm", dmm_cards, discovery)
        monkeypatch.setitem(registry._REGISTRY, "dmm", lambda: dmm)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in order)
        return dmm

    return setup


class Site:
    """relay 層的傳輸邊界：只換 JavBusScraper 的方法名（類別層）。provider（resolve／list_entity／enrich）一律用真的。"""

    def __init__(self):
        self.star_cards = []  # search_stars 回傳
        self.links = {}  # segment -> (id, 連結文字)；缺 → None
        self.pages = {}  # (entity_id, page) -> list[ListCard] | 例外
        self.videos = {}  # number -> Video | 例外 | None
        self.stars_calls = []
        self.link_calls = []
        self.entries_calls = []  # (entity_id, page)
        self.search_calls = []  # (scraper.lang, number)
        self.keyword_calls = []  # get_ids_from_search 的 keyword（梯子被跳過時 KEYWORD 才會走到這裡）

    def install(self, monkeypatch, *, entries=True):
        site = self

        def search_stars(scraper, name):
            site.stars_calls.append(name)
            return list(site.star_cards)

        def fetch_entity_link(scraper, name, segment):
            site.link_calls.append((name, segment))
            return site.links.get(segment)

        def get_entries(scraper, entity_id, page=1):
            site.entries_calls.append((entity_id, page))
            out = site.pages.get((entity_id, page), [])
            if isinstance(out, BaseException):
                raise out
            return list(out)

        def search(scraper, number):
            site.search_calls.append((scraper.lang, number))
            out = site.videos.get(number)
            if isinstance(out, BaseException):
                raise out
            return out

        def get_ids_from_search(scraper, keyword, page=1, search_type=0):
            site.keyword_calls.append(keyword)
            return []

        patches = [("search_stars", search_stars), ("fetch_entity_link", fetch_entity_link), ("search", search),
                   ("get_ids_from_search", get_ids_from_search)]
        if entries:
            patches.append(("get_entries_from_entity", get_entries))
        for name, fn in patches:
            monkeypatch.setattr(JavBusScraper, name, fn)  # raising=True：命名錯誤會直接 AttributeError


@pytest.fixture
def site(monkeypatch):
    s = Site()
    s.install(monkeypatch)
    return s


@pytest.fixture
def site_wire_entries(monkeypatch):
    """同 site，但不換 get_entries_from_entity：實體頁走真方法＋罐頭傳輸（量 HTTP 狀態碼的分類）。"""
    s = Site()
    s.install(monkeypatch, entries=False)
    return s


@pytest.fixture
def spies():
    """provider 方法的包裝式 spy（呼叫真函式）：量 call_count，並記錄 enrich 的回傳（量 belongs）。
    梯子的 `except Exception` 會把 enrich／list_entity 內的任何錯誤也吞成 []，所以只看回傳值會假綠。"""
    class Spies:
        enrich_returns: list

    s = Spies()
    s.enrich_returns = []
    orig_enrich = JavBusProvider.enrich

    def enrich_spy(self, item, ref):
        out = orig_enrich(self, item, ref)
        s.enrich_returns.append(out)
        return out

    with patch.object(JavBusProvider, "enrich", autospec=True, side_effect=enrich_spy) as enrich, \
            patch.object(JavBusProvider, "run", autospec=True, side_effect=JavBusProvider.run) as run, \
            patch.object(JavBusProvider, "resolve", autospec=True, side_effect=JavBusProvider.resolve) as resolve, \
            patch.object(JavBusProvider, "list_entity", autospec=True, side_effect=JavBusProvider.list_entity) as lst:
        s.enrich, s.run, s.resolve, s.list_entity = enrich, run, resolve, lst
        yield s


W = Window(0, 20)
NAME = "Alice"
# 站方順序：番號不遞增、日期遞減（反序、依日期升冪、依番號排序三種變異都會改變結果）
SITE_ORDER = [("AAA-002", "2026-03-01"), ("AAA-003", "2026-02-01"), ("AAA-001", "2026-01-01"),
              ("AAA-005", "2025-12-01"), ("AAA-004", "2025-11-01")]
SITE_NUMBERS = [n for n, _ in SITE_ORDER]

# (segment 或 None=女優, ref.id, entity_ids 的鍵)：四個 kind 各取對鍵；uncensored 女優取最後一段 23f
ENTITIES = [
    pytest.param(None, "star/okq", "actors", id="actor"),
    pytest.param(None, "uncensored/star/23f", "actors", id="actor-uncensored"),
    pytest.param("series", "series/rvz", "series", id="series"),
    pytest.param("director", "director/36a", "director", id="director"),
    pytest.param("label", "label/9x", "label", id="label"),
]


def _video(number, **entity_ids):
    return Video(number=number, title=f"Title {number}", maker="M", date="2026-01-01", source="javbus",
                 entity_ids=entity_ids)


def _item(number):
    return WorkItem(number, "", "", "", None, "javbus", ref=number)


def _arrange(site, segment, ref_id, key, members, order=SITE_ORDER):
    """梯子能解析出 ref，實體頁回 order 的清單；members[i]＝第 i 部詳情的連結代號是否含該 ref。"""
    code = ref_id.rsplit("/", 1)[-1]
    if segment is None:
        site.star_cards = [StarCard(ref_id, NAME, ref_id.startswith("uncensored/"))]
    else:
        site.links = {segment: (ref_id, NAME)}
    site.pages[(ref_id, 1)] = [ListCard(n, f"T-{n}", f"/pics/thumb/{n}.jpg", d) for n, d in order]
    for (number, _), member in zip(order, members, strict=False):
        site.videos[number] = _video(number, **{key: [code, "x9"] if member else ["zzz"]})


# ================================================================ 邊界條件 1：守衛（relay 入口）
@pytest.mark.parametrize("segment,ref_id,key", ENTITIES)
def test_belonging_listing_returns_cards_with_one_seed_in_site_order(chain, site, spies, segment, ref_id, key):
    """〔使用者在 JavBus 排第一打女優／系列／導演／label 名 → 守衛若恆答不了（belongs 為「不適用」），
    JavBus 的實體清單每次都被跳過，使用者只看到標題關鍵字結果而不是完整片單，沒有任何錯誤提示〕"""
    dmm = chain(dmm_cards=[{"number": "D-1"}])
    _arrange(site, segment, ref_id, key, [True] * 5)
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    calls = [c.args for c in seeds.call_args_list]
    assert [slot for slot, _ in calls].count(-1) == 1  # seed 恰 1 次
    assert calls[0] == (-1, SITE_NUMBERS)
    assert [(slot, card["number"]) for slot, card in calls[1:]] == list(enumerate(SITE_NUMBERS))
    assert [c["number"] for c in out] == SITE_NUMBERS
    assert {c["_source"] for c in out} == {"javbus"}
    assert site.entries_calls == [(ref_id, 1)]
    assert [r.belongs for r in spies.enrich_returns[:3]] == [True, True, True]
    assert dmm.run_calls == [] and spies.run.call_count == 0 and site.keyword_calls == []  # 該家答了，不再問 KEYWORD／後面


@pytest.mark.parametrize("segment,ref_id,key", ENTITIES)
def test_foreign_listing_is_rejected_and_next_provider_asked(chain, site, spies, segment, ref_id, key):
    """〔使用者在 JavBus 排第一打女優名、名稱解析選到同名別人或站方回了別份清單 → 守衛若恆放行，
    整頁別人的片被當成她的作品端出、後面的家根本沒被問，畫面看起來完全正常〕"""
    dmm = chain(dmm_cards=[{"number": "D-1", "title": "from dmm"}])
    _arrange(site, segment, ref_id, key, [False] * 5)
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    assert out == [{"number": "D-1", "title": "from dmm"}]
    assert seeds.call_count == 0  # seed 0 次
    assert site.entries_calls == [(ref_id, 1)]  # 清單真的被取過（不是梯子根本沒進來）
    # 梯子吞一切例外：[] 也可能是 enrich 內部出錯。必須量到 3 次守衛詳情、且每次都明確回 belongs is False
    assert spies.enrich.call_count == 3
    assert [r.belongs for r in spies.enrich_returns] == [False, False, False]
    assert spies.run.call_count == 0 and site.keyword_calls == []  # 命中實體的那家不再問 KEYWORD
    assert dmm.run_calls == [Kind.KEYWORD]  # 下一家被問到了


def test_listing_order_is_site_order_for_seed_and_cards(chain, site):
    """〔使用者打女優名 → 清單被重排（反序或依日期升冪）時，最新作不在最上面、骨架順序與站方新→舊不同；筆數全對所以看不出錯〕
    I-J3：seed 的番號清單順序＝list_entity 回傳順序＝各 slot 卡片順序＝回傳陣列順序。"""
    chain()
    _arrange(site, None, "star/okq", "actors", [True] * 5)
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    calls = [c.args for c in seeds.call_args_list]
    assert calls, "梯子沒進場：seed 一次都沒送"
    assert calls[0] == (-1, SITE_NUMBERS)  # 骨架＝站方順序
    assert [card["number"] for slot, card in calls[1:]] == SITE_NUMBERS  # slot 0..4 依序
    assert [slot for slot, _ in calls[1:]] == list(range(5))
    assert [c["number"] for c in out] == SITE_NUMBERS
    assert SITE_NUMBERS != sorted(SITE_NUMBERS) and [d for _, d in SITE_ORDER] == sorted((d for _, d in SITE_ORDER), reverse=True)


def test_bracketed_actress_link_text_with_same_code_belongs(canned, monkeypatch):
    """〔詳情頁的女優連結文字是括號形 `朝日奈るみな（芽森しずく）` → 名稱比對會誤殺；連結代號相同就必須算屬於〕
    走真 search()／_parse_detail_page（罐頭傳輸），不經 Site 替身。"""
    labels = FIELD_LABELS["zh-tw"]
    html = _detail_html([("okq", "朝日奈るみな（芽森しずく）")], labels=labels, prefix=BASE)
    canned.reply(f"{BASE}/AAA-001", 200, html.encode())  # zh-tw 無語系前綴
    out = JavBusProvider().enrich(_item("AAA-001"), EntityRef(Kind.ACTOR, "star/okq", NAME))
    assert out.belongs is True and out.card["number"] == "AAA-001"
    foreign = JavBusProvider().enrich(_item("AAA-001"), EntityRef(Kind.ACTOR, "star/other", NAME))
    assert foreign.belongs is False
    assert canned.urls == [f"{BASE}/AAA-001", f"{BASE}/AAA-001"]


@pytest.mark.parametrize("kind,ref_id,key", [
    (Kind.ACTOR, "star/okq", "actors"), (Kind.ACTOR, "uncensored/star/23f", "actors"),
    (Kind.DIRECTOR, "director/36a", "director"), (Kind.SERIES, "series/rvz", "series"),
    (Kind.LABEL, "label/9x", "label"),
])
def test_belongs_reads_the_matching_key_of_the_ref_kind(site, kind, ref_id, key):
    """〔四個 kind 各取對鍵：導演代號剛好等於某女優代號時，不能因為讀錯鍵而把別人的片當成她的〕"""
    code = ref_id.rsplit("/", 1)[-1]
    ref = EntityRef(kind, ref_id, NAME)
    provider = JavBusProvider()
    others = [k for k in ("actors", "director", "series", "label") if k != key]
    site.videos["AAA-001"] = _video("AAA-001", **{key: ["x1", code]})
    site.videos["AAA-002"] = _video("AAA-002", **{k: [code] for k in others})  # 代號出現在「別的鍵」
    site.videos["AAA-003"] = _video("AAA-003")  # 缺所有鍵
    site.videos["AAA-004"] = _video("AAA-004", **{key: ["x1"]})  # 有該鍵但不含
    got = {n: provider.enrich(_item(n), ref).belongs for n in ("AAA-001", "AAA-002", "AAA-003", "AAA-004")}
    assert got == {"AAA-001": True, "AAA-002": False, "AAA-003": False, "AAA-004": False}
    assert all(v is not None for v in got.values())  # 缺 kind 是 False，不是 None


@pytest.mark.parametrize("exc", [
    SourceBlocked("403"), SourceUnreachable("unreadable"), requests.Timeout("t"), requests.ConnectionError("c"),
], ids=["blocked", "unreachable", "timeout", "connection"])
def test_entity_page_failure_goes_to_next_provider_not_empty_listing(chain, site, spies, exc):
    """〔JavBus 暫時擋下或連不上 → 若被當空頁，使用者以為這位女優沒有作品；必須改問下一家〕"""
    dmm = chain(dmm_cards=[{"number": "D-1"}])
    _arrange(site, None, "star/okq", "actors", [True] * 5)
    site.pages[("star/okq", 1)] = exc
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    assert out == [{"number": "D-1"}]
    assert site.entries_calls == [("star/okq", 1)]
    assert seeds.call_count == 0 and spies.enrich.call_count == 0
    assert dmm.run_calls == [Kind.KEYWORD]


def test_blocked_entity_page_through_transport_moves_to_next_provider(chain, site_wire_entries, canned, spies):
    """同上，但走真傳輸：實體頁 HTTP 狀態碼經 get_entries_from_entity → list_entity → 梯子 → relay 換下一家。"""
    site = site_wire_entries
    dmm = chain(dmm_cards=[{"number": "D-1"}])
    _arrange(site, None, "star/okq", "actors", [True] * 3, SITE_ORDER[:3])
    for status in (403, 429, 503):
        canned.seen.clear()
        canned.reply_all(status)
        assert relay.search_by_intent("actress", NAME, W) == [{"number": "D-1"}]
        assert canned.urls == [f"{BASE}/ja/star/okq"]
    canned.reply_all(200, NO_WATERFALL)  # 200 但看不懂 → 同樣換下一家
    assert relay.search_by_intent("actress", NAME, W) == [{"number": "D-1"}]
    assert dmm.run_calls == [Kind.KEYWORD] * 4 and spies.enrich.call_count == 0


def test_discovery_only_never_resolves_or_lists_entities(chain, site, spies):
    """I-J4：〔探索模式（只看番號不補詳情）下梯子不得進場：resolve／list_entity 與所有傳輸呼叫數 0〕
    量 spy 的 call_count（BE-TEST-46），不用 side_effect=AssertionError（會被梯子的 except 吞掉）。"""
    dmm = chain(dmm_cards=[{"number": "D-1"}], discovery=True)
    _arrange(site, None, "star/okq", "actors", [True] * 5)
    relay.search_by_intent("actress", NAME, W, discovery_only=True)
    assert spies.resolve.call_count == 0 and spies.list_entity.call_count == 0 and spies.enrich.call_count == 0
    assert site.stars_calls == [] and site.link_calls == [] and site.entries_calls == [] and site.search_calls == []
    assert spies.run.call_count == 1 and dmm.run_calls == [Kind.KEYWORD]  # 只走 KEYWORD 的舊路徑
    # 對照組：同樣的資料、非探索模式 → 梯子確實會進場（證明上面的 0 不是因為資料沒備好）
    out = relay.search_by_intent("actress", NAME, W)
    assert spies.resolve.call_count == 1 and spies.list_entity.call_count == 1
    assert [c["number"] for c in out] == SITE_NUMBERS


# ================================================================ 邊界條件 2／3：實體頁取頁（scraper 與 provider）
@pytest.mark.parametrize("entity_id", ["star/okq", "uncensored/star/23f", "series/rvz", "director/36a", "label/9x"])
def test_entity_page_urls_are_ja_prefixed_with_page_suffix(canned, entity_id):
    """URL＝<BASE>/<語系前綴>/<entity_id>，第 N≥2 頁尾綴 /<N>；實體 scraper 固定 /ja。"""
    canned.reply_all(200, _entity_html(_numbered(1, 3)))
    scraper = JavBusScraper(lang="ja")
    cards = scraper.get_entries_from_entity(entity_id)
    scraper.get_entries_from_entity(entity_id, 2)
    scraper.get_entries_from_entity(entity_id, page=8)
    assert [c.number for c in cards] == ["AAA-001", "AAA-002", "AAA-003"]
    assert canned.urls == [f"{BASE}/ja/{entity_id}", f"{BASE}/ja/{entity_id}/2", f"{BASE}/ja/{entity_id}/8"]


def test_entity_page_get_overrides_site_set_existmag_cookie(canned):
    """〔使用者看某女優的完整作品 → 實體頁若沒帶 existmag=all，近期無磁鏈新片悄悄缺席（195 部 vs 417 部），畫面看起來完全正常〕
    I-J1 的實體頁半：先預塞站方的 existmag=mag，再連打兩頁；Cookie 標頭恰一個 existmag 且值為 all。"""
    canned.reply_all(200, _entity_html(_numbered(1, 3)))
    scraper = JavBusScraper(lang="ja")
    for page in (1, 2):
        _site_sets_mag(scraper)
        scraper.get_entries_from_entity("star/okq", page)
    assert canned.existmag == [["all"], ["all"]]


@pytest.mark.parametrize("entity_id", ["star/okq", "uncensored/star/23f"])
def test_list_entity_window_spans_two_pages_ja_prefix_even_when_ui_is_zh_tw(canned, entity_id):
    """〔UI 設繁中時實體清單仍必須取 /ja 頁（名稱與代號都以日文站為準）；Window(25,20) 跨第 1、2 頁〕
    封面相對路徑補成絕對網址、actors=None（要靠 enrich 補）、has_next 看原頁筆數。"""
    canned.reply(f"{BASE}/ja/{entity_id}", 200, _entity_html(_numbered(1, 30)))
    canned.reply(f"{BASE}/ja/{entity_id}/2", 200, _entity_html(
        _numbered(31, 49) + [_list_card("AAA-050", cover="https://img.example/abs.jpg")]))
    page = JavBusProvider().list_entity(EntityRef(Kind.ACTOR, entity_id, NAME), Window(25, 20))
    assert canned.urls == [f"{BASE}/ja/{entity_id}", f"{BASE}/ja/{entity_id}/2"]
    assert [i.number for i in page.items] == [f"AAA-{n:03d}" for n in range(26, 46)]
    first = page.items[0]
    assert (first.cover_url, first.actors, first.ref, first.date, first.source, first.title) == (
        f"{BASE}/pics/thumb/x.jpg", None, "AAA-026", "2026-01-02", "javbus", "T")
    assert page.has_next is True  # 第 2 頁還有 50 筆 > 25+20
    tail = JavBusProvider().list_entity(EntityRef(Kind.ACTOR, entity_id, NAME), Window(45, 20))
    assert [i.cover_url for i in tail.items][-1] == "https://img.example/abs.jpg"  # 已是絕對網址的不再加前綴


def test_list_entity_short_page_has_no_next_and_missing_cover_stays_empty(canned):
    canned.reply_all(200, _entity_html([_list_card("AAA-001", cover=""), _list_card("AAA-002")]))
    page = JavBusProvider().list_entity(EntityRef(Kind.ACTOR, "star/okq", NAME), Window(0, 20))
    assert [i.cover_url for i in page.items] == ["", f"{BASE}/pics/thumb/x.jpg"]
    assert page.has_next is False and len(canned.seen) == 1  # 不滿 30 ＝末頁，不再取下一頁


def test_entity_page_404_is_an_empty_end_page(canned):
    """〔實體頁頁碼超界（404）＝尾端，不是錯誤〕"""
    canned.reply_all(404)
    assert JavBusScraper(lang="ja").get_entries_from_entity("star/okq", 9) == []
    page = JavBusProvider().list_entity(EntityRef(Kind.ACTOR, "star/okq", NAME), Window(0, 20))
    assert page.items == [] and page.has_next is False


@pytest.mark.parametrize("status", [403, 429, 503])
def test_entity_page_blocked_status_raises_source_blocked(canned, status):
    """〔被擋不得變成「沒有作品」〕"""
    canned.reply_all(status)
    with pytest.raises(SourceBlocked):
        JavBusScraper(lang="ja").get_entries_from_entity("star/okq")
    with pytest.raises(SourceBlocked):
        JavBusProvider().list_entity(EntityRef(Kind.ACTOR, "star/okq", NAME), Window(0, 20))


def test_entity_page_unreadable_200_raises_source_unreachable(canned):
    canned.reply_all(200, NO_WATERFALL)
    with pytest.raises(SourceUnreachable):
        JavBusScraper(lang="ja").get_entries_from_entity("star/okq")


def test_entity_page_200_with_empty_waterfall_is_empty_not_error(canned):
    canned.reply_all(200, EMPTY_WATERFALL)
    assert JavBusScraper(lang="ja").get_entries_from_entity("star/okq") == []


@pytest.mark.parametrize("exc", [requests.Timeout("t"), requests.ConnectionError("c")], ids=["timeout", "connection"])
def test_entity_page_transport_exception_raises_source_unreachable(canned, exc):
    canned.raise_all(exc)
    with pytest.raises(SourceUnreachable):
        JavBusScraper(lang="ja").get_entries_from_entity("star/okq")


# ================================================================ 邊界條件 4：entity_ids 解析
def _entity_ids(html, lang="ja"):
    video = JavBusScraper(lang=lang)._parse_detail_page(BeautifulSoup(html, "html.parser"), "SSIS-001", "u")
    return video.entity_ids


def test_entity_ids_dedup_ordered_per_kind_and_info_only():
    """〔解析漏掉某 kind、漏去重或把 info 之外別人的連結算進來 → 守衛誤殺（JavBus 整家被跳過）或誤放行（別人的片混進她的清單）〕
    同一代號在 info 內出現三次要去重保序；avatar-waterfall（info 之外）的別人連結不進；片商／類別連結不進。"""
    html = _detail_html(
        [("2xi", "Alice"), ("w5a", "Bob"), ("2xi", "Alice again")],
        director=("o7", "Dir"), series=("fg8", "Ser"), label=("9x", "Lab"), outside=("outsider1", "2xi"))
    assert _entity_ids(html) == {"actors": ["2xi", "w5a"], "director": ["o7"], "series": ["fg8"], "label": ["9x"]}


@pytest.mark.parametrize("prefix", [f"{BASE}/ja", f"{BASE}/en", BASE, "/ja", "", "/en"],
                         ids=["abs-ja", "abs-en", "abs-none", "rel-ja", "rel-none", "rel-en"])
def test_entity_ids_accept_every_language_prefix_form(prefix):
    html = _detail_html([("2xi", "Alice")], director=("o7", "Dir"), series=("fg8", "Ser"), label=("9x", "Lab"),
                        prefix=prefix)
    assert _entity_ids(html) == {"actors": ["2xi"], "director": ["o7"], "series": ["fg8"], "label": ["9x"]}


def test_entity_ids_recognise_uncensored_star_links_by_their_last_segment():
    html = _detail_html([("23f", "Mika")], prefix=f"{BASE}/ja/uncensored")
    assert _entity_ids(html) == {"actors": ["23f"]}


# ================================================================ 邊界條件 5：舊路徑逐位元不變／實體路徑 enrich
def test_capabilities_are_exactly_the_eight_kinds():
    assert JavBusProvider.capabilities == frozenset({
        Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD})
    assert JavBusProvider.supports_discovery is True
    assert JavBusProvider.fallback_streaming is False  # 補完詳情後依日期重排 ⇒ 串流順序≠最終順序（BE-DATA-20）


def test_entity_enrich_uses_ui_language_scraper(site):
    """〔使用者 UI 設繁中、在 JavBus 排第一打女優 → 實體路徑若固定抓 /ja 詳情頁，卡片標籤變日文、
    加入書籤後書籤標籤被寫成日文（違反 spec §4）〕UI 語系由 core.scraper.get_javbus_lang 決定（autouse 固定 zh-tw）。"""
    site.videos["AAA-001"] = _video("AAA-001", actors=["okq"])
    out = JavBusProvider().enrich(_item("AAA-001"), EntityRef(Kind.ACTOR, "star/okq", NAME))
    assert site.search_calls == [("zh-tw", "AAA-001")]
    assert out.belongs is True and out.card["number"] == "AAA-001" and out.card["_source"] == "javbus"


def test_entity_enrich_builds_the_card_from_the_original_video_and_normalized_number(site):
    """belongs 由原 video 算；build_card 與 search 用同一個正規化後的番號。"""
    site.videos["AAA-001"] = _video("AAA-001", actors=["okq"])
    with patch("core.scraper.build_card", wraps=scraper_mod.build_card) as bc:
        out = JavBusProvider().enrich(_item("aaa-001"), EntityRef(Kind.ACTOR, "star/okq", NAME))
    assert site.search_calls == [("zh-tw", "AAA-001")]
    assert bc.call_count == 1 and bc.call_args.args == (site.videos["AAA-001"], "AAA-001")
    assert out.belongs is True


@pytest.mark.parametrize("outcome", [
    SourceBlocked("b"), SourceUnreachable("u"), TimeoutError("t"), ValueError("bad number"), None,
    Video(number="AAA-001", title=""),
], ids=["blocked", "unreachable", "timeout", "bad-number", "no-video", "no-title"])
def test_entity_enrich_failure_or_no_title_is_card_none(site, outcome):
    """詳情失敗／無 title → Enriched(card=None)；例外與舊路徑同寬（吞掉記 log）。〔該部在清單裡降級顯示，不整批失敗〕"""
    site.videos["AAA-001"] = outcome
    out = JavBusProvider().enrich(_item("AAA-001"), EntityRef(Kind.ACTOR, "star/okq", NAME))
    assert out == Enriched(card=None)


@pytest.mark.parametrize("ref", [None, EntityRef(Kind.CODE, "SSIS", "SSIS"), EntityRef(Kind.PARTIAL, "SSIS-0", "x")],
                         ids=["none", "code", "partial"])
def test_enrich_without_entity_ref_is_the_unchanged_search_path(site, ref):
    """ref is None（及 CODE／PARTIAL）＝逐位元不變：仍是 core.scraper.search_jav(number, 'javbus')、belongs=None；
    兩條路徑互不串（實體路徑的 scraper.search 呼叫數 0）。"""
    card = {"number": "SSIS-001", "title": "T", "actors": []}
    with patch("core.scraper.search_jav", return_value=card) as sj:
        out = JavBusProvider().enrich(_item("SSIS-001"), ref)
    assert sj.call_count == 1 and sj.call_args.args == ("SSIS-001", "javbus") and sj.call_args.kwargs == {}
    assert out == Enriched(card=card, belongs=None)
    assert site.search_calls == []
    with patch("core.scraper.search_jav", return_value=None):
        assert JavBusProvider().enrich(_item("SSIS-001"), ref) == Enriched(card=None)
