"""test_dmm_run_maker.py — DMM 片商最新作品 run_maker＋宣告 MAKER 能力（TASK-175c-T9，plan CD-175c-8／-6(B)／-11／-12）。

傳輸邊界只有三個方法名（類別層）：`DMMScraper.list_contents`／`fetch_facts`／`_fetch_by_id`；JavBus 一律
`patch.object(JavBusProvider, "run_maker", autospec=True)` 並量 `call_count`（BE-TEST-46）。真 `DMMProvider`＋真
`_resolve_maker`／`list_entity`／`enrich`（不套名稱→實體查詢的隔離 fixture——這裡要真的跑片商解析）。
`relay.search_maker` 對 `run_maker` 的任何例外一律 `except Exception → maker_unreachable` 並換下一家，
所以接力層案同時斷言 DMM 傳輸替身「被以正確引數呼叫過」（probe 的 queryWord、清單的 makerIds 篩選、facts），
只看「JavBus 被問了／沒被問」會假綠。

替身依參數回不同資料並記錄每次呼叫（BE-TEST-23）：`filter is None` 的 `list_contents`＝probe（名字→片商），
帶 `makerIds` 的＝清單。合成資料全為檔內字面（形狀依 plan 活站紀錄，不宣稱是站方真值），不收站方 JSON；零活站請求
（BE-TEST-43）。官方番號的期望值一律是字面常數，不用 `_content_id_to_number` 現算（同源恆真）。
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import time
from unittest.mock import patch

import pytest
import requests

from core.database import init_db, maker_javbus_map
from core.maker_names import maker_spellings
from core.proxy_policy import ProxySettings
from core.scrapers.dmm import DMMScraper, Facts, ListResult
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.models import ScraperConfig, Video
from core.search_providers import pipeline, relay
from core.search_providers.dmm import DMMProvider
from core.search_providers.javbus import JavBusProvider
from core.search_providers.types import EntityRef, Kind, MakerSearchResult

TODAY = "2026-10-21"


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
    """pipeline 每部詳情後 sleep、DMM 詳情解析 rate_limit 也 sleep：全換掉；執行緒池換成同步（完成順序＝提交順序）。
    `_MAKER_ANSWERERS` 是行程內 LRU（載入更多固定問誰），每個測試前後清，不依賴執行順序。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)
    relay._reset_maker_answerers()
    yield
    relay._reset_maker_answerers()


# ---------------------------------------------------------------- 合成資料
LABEL = "S1"
DMM_NAME = "エスワン ナンバーワンスタイル"  # DMM 站上的片商名；S1 的拼法集合內才有，label 本身不等於它
SPELLINGS = ["S1", DMM_NAME]
MAKER_ID = "3152"
FILTER = {"makerIds": {"ids": [{"id": MAKER_ID}], "op": "OR"}}

# (content_id, facts.makerContentId)：站方順序，番號既不遞增也不遞減（依番號排序／反序兩種變異都會改變結果）；
# 第二筆的官方值與 cid 推導值不同（h_ 開頭），證明列表階段的番號取自 fetch_facts。
LISTING = [("sone00206", "SONE-206"), ("h_1234sone00210", "SONE-210"), ("sone00205", "SONE-205")]
OFFICIAL_ORDER = ["SONE-206", "SONE-210", "SONE-205"]


def _row(cid, *, maker=(MAKER_ID, DMM_NAME)):
    return {
        "id": cid,
        "title": f"title {cid}",
        "packageImage": {"largeUrl": f"https://img.invalid/{cid}.jpg"},
        "actresses": [{"id": "1", "name": "女優"}],
        "maker": {"id": maker[0], "name": maker[1]},
    }


def _probe_rows(word_maker=(MAKER_ID, DMM_NAME)):
    """probe 一個詞撈回的列：多數是目標片商，夾兩筆雜牌（共演／標題碰巧含該字）。"""
    return [_row("probe00001", maker=word_maker), _row("noise00001", maker=("9", "雜牌")),
            _row("probe00002", maker=word_maker)]


class Site:
    """DMM 的傳輸邊界（類別層替身）＋共用事件 log（probe／list／facts／seed／item／detail 的先後）。"""

    def __init__(self):
        self.log = []
        self.by_word = {}  # probe: query_word -> ListResult
        self.by_maker = {}  # 清單: (filter 鍵, id) -> ListResult
        self.facts = {}  # content_id -> Facts；沒登記＝alias 缺漏
        self.probe_calls = []  # {"query_word", "limit", "offset"}
        self.list_calls = []  # {"filter", "limit", "offset"}
        self.facts_calls = []  # tuple(content_ids)
        self.detail_calls = []  # content_id
        self.seeds = []  # seed 的 slots（番號清單）
        self.statuses = []

    def install(self, monkeypatch):
        site = self

        def list_contents(scraper, query_word=None, filter=None, *, limit, offset):
            if filter is None:
                site.log.append("probe")
                site.probe_calls.append({"query_word": query_word, "limit": limit, "offset": offset})
                found = site.by_word.get(query_word)
            else:
                site.log.append("list")
                site.list_calls.append({"filter": filter, "limit": limit, "offset": offset})
                key, spec = next(iter(filter.items()))
                found = site.by_maker.get((key, spec["ids"][0]["id"]))
            if found is None:
                return ListResult([], 0, False)
            return ListResult(copy.deepcopy(found.rows), found.total, found.has_next)

        def fetch_facts(scraper, content_ids):
            ids = tuple(content_ids)
            site.log.append("facts")
            site.facts_calls.append(ids)
            return {cid: site.facts[cid] for cid in ids if cid in site.facts}

        def fetch_by_id(scraper, content_id):
            site.log.append("detail")
            site.detail_calls.append(content_id)
            fact = site.facts.get(content_id)
            number = fact.maker_content_id if fact is not None else f"DETAIL-{content_id}"
            return Video(number=number, title=f"full {content_id}", source="dmm")

        monkeypatch.setattr(DMMScraper, "list_contents", list_contents)  # raising=True：命名錯誤會直接 AttributeError
        monkeypatch.setattr(DMMScraper, "fetch_facts", fetch_facts)
        monkeypatch.setattr(DMMScraper, "_fetch_by_id", fetch_by_id)

    def result_callback(self, slot, data):
        if slot == -1:
            self.log.append("seed")
            self.seeds.append(list(data))
        else:
            self.log.append("item")

    def status_callback(self, source, status):
        self.statuses.append((source, status))


@pytest.fixture
def site(monkeypatch):
    s = Site()
    s.install(monkeypatch)
    return s


def _world(site, listing=LISTING, *, has_next=True, total=999, rows=None):
    """登記『S1 → 3152 → 清單』：probe 回目標片商＋雜牌；清單的列其 maker.id 與 probe 命中的 id 相同
    （守衛的 belongs 為 True，順序案才會因『seed 延後』而紅，不會因『空結果』而紅）。"""
    site.by_word["S1"] = ListResult(_probe_rows(), 3, False)
    rows = [_row(cid) for cid, _ in listing] if rows is None else rows
    site.by_maker[("makerIds", MAKER_ID)] = ListResult(rows, total, has_next)
    for cid, official in listing:
        site.facts[cid] = Facts(official, None, None, [])


def _provider():
    return DMMProvider(DMMScraper(ScraperConfig(proxy_settings=ProxySettings(url=""))))


@pytest.fixture
def chain(monkeypatch):
    """鏈順序與開關 patch 使用端 core.scraper.*（BE-TEST-01／02）；真 registry，DMM 為真 provider。"""
    def setup(order):
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in order)

    return setup


@pytest.fixture
def bus():
    with patch.object(JavBusProvider, "run_maker", autospec=True) as m:
        m.return_value = MakerSearchResult([], False, "maker_no_sample")
        yield m


def _search(site, offset=0, *, label=LABEL, key="s1", spellings=SPELLINGS, **kw):
    return relay.search_maker(
        key, label, spellings, offset, titles=[], today=TODAY,
        status_callback=site.status_callback, result_callback=site.result_callback, **kw,
    )


# ================================================================ 1. 接力層回答與重評場景（relay.search_maker 入口）
def test_javbus_no_sample_then_dmm_answers(site, chain, bus):
    """〔使用者關掉 JavDB、JavBus 又沒有該片商的樣本時點 S1 膠囊 → 若 DMM 沒宣告 MAKER 或沒接上，
    膠囊點下去只得「沒有樣本」而 DMM 明明有；R-T8d-1 對 DMM 認得的片商消失〕"""
    chain(["javbus", "dmm"])
    _world(site)
    out = _search(site)
    assert out.error_code is None
    assert [c["number"] for c in out.results] == OFFICIAL_ORDER
    assert {c["_source"] for c in out.results} == {"dmm"}
    assert out.has_more is True  # 取自罐頭的 hasNext，不是筆數
    assert bus.call_count == 1  # JavBus 先被問、換家
    # relay 會把 run_maker 內的任何例外吞成 maker_unreachable：傳輸替身必須真的被以正確引數呼叫過
    assert [c["query_word"] for c in site.probe_calls] == ["S1"]  # probe 命中即停（第一個拼法就中）
    assert [c["filter"] for c in site.list_calls] == [FILTER]
    assert len(site.facts_calls) == 1
    assert site.log.count("seed") == 1  # 呼叫端 result_callback 收到 slot==-1 恰 1 次（JavBus 替身沒送）
    # 載入更多固定問第一頁回答的那一家（DMM），不再問 JavBus
    more = _search(site, 30)
    assert bus.call_count == 1
    assert more.results and more.error_code is None
    assert site.list_calls[-1]["offset"] == 30


def test_only_dmm_chain_sod_stays_not_found(site, chain, bus):
    """〔只開 DMM 打 SOD → 查無是已接受的殘留 8（R-T13b-1 維持；DMM 的片商叫 SODクリエイト，BE-DATA-21 禁補別名）。
    這格把它釘成可證偽的維持：哪天有人補了別名，這案轉紅是對的——提示要重新裁決，不是測試壞〕"""
    chain(["dmm"])
    assert maker_spellings("SOD") == ["SOD"]  # 前提：對照表沒把 SOD 併到 SOD Create
    site.by_word["SOD"] = ListResult(_probe_rows(("45276", "SODクリエイト")), 3, False)
    out = _search(site, label="SOD", key="sod", spellings=maker_spellings("SOD"))
    assert out.error_code == "maker_not_found" and out.results == []
    assert [c["query_word"] for c in site.probe_calls] == ["SOD"]  # 傳輸只有 1 次 probe
    assert site.list_calls == [] and site.facts_calls == [] and site.detail_calls == []
    assert bus.call_count == 0


def test_default_order_dmm_answers_javbus_not_asked(site, chain, bus):
    """〔DMM 排第一（預設順序）且答得出來時，JavBus 一次都不用被問〕"""
    chain(["dmm", "javbus"])
    _world(site)
    out = _search(site)
    assert [c["number"] for c in out.results] == OFFICIAL_ORDER and out.error_code is None
    assert bus.call_count == 0


# ================================================================ 2. 錯誤碼與例外（直接呼叫 run_maker）
def test_unrecognised_maker_is_not_found(site):
    """〔使用者點到 DMM 與其他家都不認得的片商 → 本該顯示「找不到這家片商」並收起該膠囊；碼被換成「連不上」後
    膠囊不收，使用者反覆點同一顆、每次白等一輪探測，接力彙整還會把別家的「沒有樣本」蓋成「連不上」〕"""
    site.by_word["S1"] = ListResult([_row("noise00001", maker=("9", "雜牌"))], 1, False)  # 只有別的片商
    out = _provider().run_maker("s1", LABEL, SPELLINGS, 0)
    assert out == MakerSearchResult([], False, "maker_not_found")
    assert site.probe_calls and site.list_calls == [] and site.facts_calls == []


EXCEPTIONS = [
    SourceBlocked("403"),
    SourceUnreachable("down"),
    requests.Timeout("timeout"),
    requests.exceptions.ConnectionError("refused"),
    ConnectionError("reset"),
]


@pytest.mark.parametrize("stage", ["resolve", "list"])
@pytest.mark.parametrize("exc", EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_resolve_or_list_failure_is_unreachable_not_not_found(monkeypatch, stage, exc):
    """〔使用者點片商膠囊時 DMM 暫時擋住（403）→ 本該是「連不上」且膠囊保留；碼被換成「查無」後出現片商錯誤頁並把
    膠囊收起，使用者以為 DMM 沒有這家片商，本次工作階段再也點不到〕。except 寬度是契約（BE-TEST-33）：
    resolve 階段與 list 階段各注入。"""
    def boom(*a, **kw):
        raise exc

    ref = EntityRef(Kind.MAKER, MAKER_ID, DMM_NAME)
    if stage == "resolve":
        monkeypatch.setattr(DMMProvider, "_resolve_maker", boom)
    else:
        monkeypatch.setattr(DMMProvider, "_resolve_maker", lambda self, names: ref)
        monkeypatch.setattr(DMMProvider, "list_entity", boom)
    out = DMMProvider().run_maker("s1", LABEL, SPELLINGS, 0)
    assert out == MakerSearchResult([], False, "maker_unreachable")


class _Tripwire(BaseException):
    """模擬 OutboundConnectionViolation（BaseException 子類：except Exception 吞不到）。"""


@pytest.mark.parametrize("stage", ["resolve", "list"])
def test_base_exception_passes_through(monkeypatch, stage):
    def boom(*a, **kw):
        raise _Tripwire()

    if stage == "resolve":
        monkeypatch.setattr(DMMProvider, "_resolve_maker", boom)
    else:
        monkeypatch.setattr(DMMProvider, "_resolve_maker", lambda self, names: EntityRef(Kind.MAKER, MAKER_ID, DMM_NAME))
        monkeypatch.setattr(DMMProvider, "list_entity", boom)
    with pytest.raises(_Tripwire):
        DMMProvider().run_maker("s1", LABEL, SPELLINGS, 0)


def test_empty_listing_is_maker_empty_without_seed(site):
    """〔片商認得、清單卻是空（站方 0 筆）→ 終點「沒有更多」，不能送一個空 seed 讓骨架格閃一下〕"""
    site.by_word["S1"] = ListResult(_probe_rows(), 3, False)  # 清單沒登記 ⇒ 空
    with patch("core.search_providers.dmm.run_window", wraps=pipeline.run_window) as rw:
        out = _provider().run_maker("s1", LABEL, SPELLINGS, 0, result_callback=site.result_callback)
    assert out == MakerSearchResult([], False, "maker_empty")
    assert rw.call_count == 0 and site.log.count("seed") == 0  # seed 0 次
    assert len(site.list_calls) == 1 and site.facts_calls == [] and site.detail_calls == []


# ================================================================ 3. 視窗、串流與順序
def test_default_window_is_thirty_and_offset_is_native(site):
    """〔使用者點片商膠囊後按「載入更多」（前端以 offset=30 取第二頁、不帶 limit）→ 預設視窗若只有 20，第 21–30 部
    永遠不會出現，每一頁都靜默漏掉 10 部，畫面看起來完全正常〕。DMM 為 offset 原生：不要求 30 的倍數。"""
    _world(site)
    provider = _provider()
    provider.run_maker("s1", LABEL, SPELLINGS, 0)
    provider.run_maker("s1", LABEL, SPELLINGS, 40, limit=20)
    provider.run_maker("s1", LABEL, SPELLINGS, 45)
    assert [(c["limit"], c["offset"]) for c in site.list_calls] == [(30, 0), (20, 40), (30, 45)]
    assert all(c["filter"] == FILTER for c in site.list_calls)


def _numbered(n, *, missing_id_at=None):
    """n 列 rows＋facts；missing_id_at 那一列缺 id（T8 的頁面組裝會略過它）。"""
    listing = [(f"sone{i:05d}", f"SONE-{i:03d}") for i in range(500, 500 - n, -1)]
    rows = [_row("" if i == missing_id_at else cid) for i, (cid, _) in enumerate(listing)]
    return listing, rows


@pytest.mark.parametrize(
    "missing_id_at,has_next,cards,expected",
    [
        (None, False, 30, False),  # 最後一頁剛好 30 部、站方說沒了
        (7, True, 29, True),  # 一列缺 id 被略過、剩 29 張，站方說還有下一頁
    ],
    ids=["full-page-no-next", "short-page-has-next"],
)
def test_has_more_follows_page_info_not_row_count(site, missing_id_at, has_next, cards, expected):
    """〔使用者翻某片商的清單 → 某頁有一列缺 id 被略過、剩 29 張而站方說還有下一頁，「載入更多」若用筆數猜就消失，
    後面的片永遠看不到；最後一頁剛好 30 部則多一顆按了什麼都沒有的按鈕〕（BE-TEST-23：真假兩極都要出現）"""
    listing, rows = _numbered(30, missing_id_at=missing_id_at)
    _world(site, listing, has_next=has_next, rows=rows)
    out = _provider().run_maker("s1", LABEL, SPELLINGS, 0)
    assert out.error_code is None and len(out.results) == cards
    assert out.has_more is expected


def test_seed_precedes_every_detail_request(site):
    """〔使用者在預設順序（DMM 排第一）點片商膠囊 → 開了守衛，骨架格要等前 3 部詳情抓完（約 2 秒空白）才出現；
    DMM 的片商 ID 清單本來就精確，守衛換不到任何保護〕。事件順序：list → facts → seed → 第一個 detail。"""
    _world(site)
    out = _provider().run_maker("s1", LABEL, SPELLINGS, 0, result_callback=site.result_callback)
    assert out.results  # 路徑真的跑完（belongs 為 True，守衛若開著也會通過，所以紅只會是『seed 延後』）
    log = site.log
    assert log.count("seed") == 1 and log.count("detail") == len(LISTING)
    assert log.index("list") < log.index("facts") < log.index("seed")
    assert log.index("seed") < log.index("detail")  # seed 先於『任何』_fetch_by_id
    assert site.seeds == [OFFICIAL_ORDER]  # seed 的骨架番號是 fetch_facts 的官方值


def test_happy_path_cards_carry_dmm_source_and_one_seed(site):
    """happy-path：回卡非空、error_code 為 None、每張卡 _source=dmm、seed 恰 1 次。
    （手動 mutation (b)：守衛開著且 belongs 恆 None → 回空卡，這案必須轉紅；M2 單獨套時它仍綠。）"""
    _world(site)
    out = _provider().run_maker("s1", LABEL, SPELLINGS, 0, result_callback=site.result_callback)
    assert out.error_code is None and len(out.results) == len(LISTING)
    assert {c["_source"] for c in out.results} == {"dmm"}
    assert site.log.count("seed") == 1


def test_results_keep_listing_order_with_official_numbers_and_status_events(site):
    """BE-DATA-20：串流序＝最終序，不重排；首個 status 是 searching、末個是 found:N。"""
    _world(site)
    out = _provider().run_maker(
        "s1", LABEL, SPELLINGS, 0, status_callback=site.status_callback, result_callback=site.result_callback)
    assert [c["number"] for c in out.results] == OFFICIAL_ORDER
    assert site.statuses[0] == ("dmm", "searching")
    assert site.statuses[-1] == ("done", f"found:{len(LISTING)}")
    assert site.detail_calls == [cid for cid, _ in LISTING]  # 詳情依清單順序發起


# ================================================================ 4. 不碰別人的資料
def test_dmm_does_not_touch_library_sampling_or_javbus_map(site, tmp_path):
    """〔DMM 回答時若寫進 JavBus 的片商對照表，對照表被灌入 DMM 的結果，之後 JavBus 排前時膠囊被錯藏、
    片商搜尋查錯 studio〕。片庫樣本相關參數接受不使用：不呼叫取樣、不寫對照表。"""
    db = tmp_path / "t.db"
    init_db(db)
    _world(site)
    with patch("core.scraper.resolve_maker_studio") as rms:
        out = _provider().run_maker("s1", LABEL, SPELLINGS, 0, titles=["SONE-205"], today=TODAY, db_path=db)
    assert out.results and out.error_code is None
    assert rms.call_count == 0
    assert maker_javbus_map.get_mapping("s1", db_path=db) is None


def test_names_are_deduped_by_maker_key_keeping_order(monkeypatch):
    """_resolve_maker 收到的 names＝[label, *spellings] 以 maker_key_of 去重保序（重複拼法只探一次，不佔 3 次上限）。"""
    seen = []

    def spy(self, names):
        seen.append(list(names))
        return None

    monkeypatch.setattr(DMMProvider, "_resolve_maker", spy)
    DMMProvider().run_maker("s1", "S1", ["S1", DMM_NAME, "ｓ１", " s1 ", DMM_NAME], 0)
    assert seen == [["S1", DMM_NAME]]


def test_all_spellings_are_match_candidates(site):
    """〔使用者點 S1 膠囊 → 前端送來的各種拼法（含 DMM 站上的名字「エスワン ナンバーワンスタイル」）若被丟掉，
    DMM 只拿 S1 去比、認不出該片商，明明有數千部卻回「沒有」〕。probe「S1」撈回的片商叫 DMM_NAME，
    只有 spellings 內含這個寫法才比得中（label 本身不等於它）。"""
    _world(site)
    assert maker_spellings(LABEL)[1] == DMM_NAME  # 前提：DMM 站上的名字確實在 S1 的拼法集合內
    out = _provider().run_maker("s1", LABEL, SPELLINGS, 0)
    assert out.error_code is None and len(out.results) == len(LISTING)
    assert [c["filter"] for c in site.list_calls] == [FILTER]

