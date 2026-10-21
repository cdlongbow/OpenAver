"""test_dmm_entity_list.py — DMM 實體清單＋官方番號＋守衛 belongs＋宣告能力（TASK-175c-T8，plan CD-175c-7／-10／-12）。

傳輸邊界只有三個方法名（類別層）：`DMMScraper.list_contents`／`fetch_facts`／`_fetch_by_id`，外加 `DMMProvider.resolve`
（名稱→實體的解析是 T7 的事，這裡直接指定「解析出哪個 ref」）。真 registry ＋ 真 `DMMProvider` ＋ 假後備 provider；
不 patch `list_entity`／`enrich`（那會跳過本 task 要驗的接線）。
替身依參數（filter／query_word）回不同資料並記錄每次呼叫的引數（BE-TEST-23）；計數看呼叫紀錄（BE-TEST-46）。
梯子對 `list_entity`／`enrich` 內的任何例外一律 `except Exception → []`，所以「只看回傳 []」會假綠：
守衛的每一案都同時斷言清單真的被取過、`enrich` 被呼叫 3 次且逐次 `belongs is False`。

合成資料全為檔內字面（形狀依 plan 活站紀錄），不收站方 JSON；零活站請求。官方番號的期望值一律是字面常數，
不用 `_content_id_to_number` 現算（同源恆真）；`h_` 那筆的官方值是合成字面，不是站方真值。
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.proxy_policy import ProxySettings
from core.scrapers.dmm import DMMScraper, Facts, ListResult, Named
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.models import ScraperConfig, Video
from core.search_providers import registry, relay
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import EntityRef, Kind, Window


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
    """pipeline 每部詳情後 sleep、DMM 詳情解析 rate_limit 也 sleep：全換掉；執行緒池換成同步（完成順序＝提交順序）。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)


# ---------------------------------------------------------------- 合成資料
W = Window(0, 20)
NAME = "三上悠亜"
REF = "777"  # 目標實體的站方 id
OTHER = "888"  # 別的實體的站方 id
FILTER_KEY = {
    Kind.ACTOR: "actressIds",
    Kind.SERIES: "seriesIds",
    Kind.DIRECTOR: "directorIds",
    Kind.LABEL: "labelIds",
    Kind.MAKER: "makerIds",
}
LADDER_KINDS = [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL]  # 能走梯子（宣告能力）的四種；MAKER 不經梯子
NO_FACTS = object()  # facts 沒有這個 alias

# (content_id, facts.makerContentId, 期望番號)。期望值是字面常數：
#   13dsvr01774 推導值會是 DSVR-1774、55t28103 推導值會是 T-28103、h_ 開頭推導值原樣；
#   makerContentId 為 null／alias 缺漏的兩列都退推導值（字面 SSIS-001／ABP-1234）。
SPECIAL = [
    ("13dsvr01774", "3DSVR-1774", "3DSVR-1774"),
    ("55t28103", "T28-103", "T28-103"),
    ("h_113id00057", "SYNTH-057", "SYNTH-057"),  # 官方值為檔內合成字面
    ("ssis00001", None, "SSIS-001"),
    ("abp01234", NO_FACTS, "ABP-1234"),
]
FILLER = [(f"mide{i:05d}", f"MIDE-{i:03d}", f"MIDE-{i:03d}") for i in range(1, 16)]
SPEC20 = SPECIAL + FILLER
EXPECTED20 = [expected for _, _, expected in SPEC20]

# 站方順序：番號不遞增（反序、依番號排序兩種變異都會改變結果）
LIST5 = [("zzz00003", "ZZZ-003"), ("aaa00002", "AAA-002"), ("mmm00001", "MMM-001"),
         ("13dsvr01774", "3DSVR-1774"), ("55t28103", "T28-103")]
LIST5_NUMBERS = [n for _, n in LIST5]


def _row(cid, *, actress_ids=(REF,), maker_id=OTHER):
    return {
        "id": cid,
        "title": f"title {cid}",
        "packageImage": {"largeUrl": f"https://img.invalid/{cid}.jpg"},
        "actresses": [{"id": a, "name": f"女優{a}"} for a in actress_ids],
        "maker": {"id": maker_id, "name": f"片商{maker_id}"},
    }


def _facts(maker_content_id, *, series=None, label=None, directors=()):
    return Facts(
        maker_content_id,
        None if series is None else Named(series, f"series {series}"),
        None if label is None else Named(label, f"label {label}"),
        [Named(d, f"director {d}") for d in directors],
    )


class Site:
    """DMM 的傳輸邊界（類別層替身）＋ resolve 的回答。"""

    def __init__(self):
        self.log = []  # 事件順序：list／facts／detail（I-D2）
        self.by_word = {}  # query_word -> ListResult
        self.by_filter = {}  # (filter 鍵, id) -> ListResult
        self.facts = {}  # content_id -> Facts；沒登記＝alias 缺漏
        self.details = {}  # content_id -> Video | None | 例外；沒登記＝回一張預設卡
        self.refs = {}  # Kind -> EntityRef；沒登記＝resolve 回 None
        self.list_error = None
        self.facts_error = None
        self.list_calls = []  # {"query_word", "filter", "limit", "offset"}
        self.facts_calls = []  # tuple(content_ids)
        self.detail_calls = []  # content_id
        self.resolve_calls = []  # (kind, name)

    def install(self, monkeypatch):
        site = self

        def list_contents(scraper, query_word=None, filter=None, *, limit, offset):
            site.log.append("list")
            site.list_calls.append({"query_word": query_word, "filter": filter, "limit": limit, "offset": offset})
            if site.list_error is not None:
                raise site.list_error
            if filter is not None:
                key, spec = next(iter(filter.items()))
                found = site.by_filter.get((key, spec["ids"][0]["id"]))
            else:
                found = site.by_word.get(query_word)
            if found is None:
                return ListResult([], 0, False)
            return ListResult(copy.deepcopy(found.rows), found.total, found.has_next)

        def fetch_facts(scraper, content_ids):
            ids = tuple(content_ids)
            site.log.append("facts")
            site.facts_calls.append(ids)
            if site.facts_error is not None:
                raise site.facts_error
            return {cid: site.facts[cid] for cid in ids if cid in site.facts}

        def fetch_by_id(scraper, content_id):
            site.log.append("detail")
            site.detail_calls.append(content_id)
            out = site.details.get(content_id, Video(number=f"DETAIL-{content_id}", title="full", source="dmm"))
            if isinstance(out, BaseException):
                raise out
            return out

        def resolve(provider, kind, name):
            site.resolve_calls.append((kind, name))
            return site.refs.get(kind)

        monkeypatch.setattr(DMMScraper, "list_contents", list_contents)  # raising=True：命名錯誤會直接 AttributeError
        monkeypatch.setattr(DMMScraper, "fetch_facts", fetch_facts)
        monkeypatch.setattr(DMMScraper, "_fetch_by_id", fetch_by_id)
        monkeypatch.setattr(DMMProvider, "resolve", resolve)


@pytest.fixture
def site(monkeypatch):
    s = Site()
    s.install(monkeypatch)
    return s


class Other:
    """後備 provider（假 JavBus）：run 回預設 cards 並記錄呼叫的 kind。"""

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
    """真 registry 的 dmm（排第一）＋ 假後備；順序與開關 patch core.scraper.*（BE-TEST-01／02）。"""
    def setup(*, other_cards=(), discovery=False, order=("dmm", "javbus")):
        other = Other("javbus", other_cards, discovery)
        monkeypatch.setitem(registry._REGISTRY, "javbus", lambda: other)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in order)
        return other

    return setup


@pytest.fixture
def spies(site):
    """provider 方法的包裝式 spy（呼叫真函式）：量 call_count 並記錄 enrich 的回傳（量 belongs）。"""
    class Spies:
        enrich_returns: list

    s = Spies()
    s.enrich_returns = []
    orig_enrich = DMMProvider.enrich

    def enrich_spy(self, item, ref=None):
        out = orig_enrich(self, item, ref)
        s.enrich_returns.append(out)
        return out

    with patch.object(DMMProvider, "enrich", autospec=True, side_effect=enrich_spy) as enrich, \
            patch.object(DMMProvider, "run", autospec=True, side_effect=DMMProvider.run) as run, \
            patch.object(DMMProvider, "list_entity", autospec=True, side_effect=DMMProvider.list_entity) as lst:
        s.enrich, s.run, s.list_entity = enrich, run, lst
        yield s


def _scraper():
    return DMMScraper(ScraperConfig(proxy_settings=ProxySettings(url="")))


def _provider():
    return DMMProvider(_scraper())


def _register_numbers_world(site, *, kind=Kind.ACTOR):
    """20 筆 rows＋facts＋詳情（詳情卡的番號＝官方值）；KEYWORD 的 'q' 與 ACTOR 的 REF 回同一份清單。"""
    rows = [_row(cid) for cid, _, _ in SPEC20]
    result = ListResult(rows, 999, True)
    site.by_word["q"] = result
    site.by_filter[(FILTER_KEY[kind], REF)] = result
    site.refs[kind] = EntityRef(kind, REF, NAME)
    for cid, official, expected in SPEC20:
        if official is not NO_FACTS:
            site.facts[cid] = _facts(official)
        site.details[cid] = Video(number=expected, title=f"full {cid}", source="dmm")


def _arrange(site, kind, members, listing=LIST5):
    """登記一份實體清單：members[i]＝第 i 部是否屬於 REF（四個維度都放 REF；不屬於的放『別人』的 id，不是缺值）。"""
    rows, facts = [], {}
    for (cid, number), member in zip(listing, members, strict=False):
        owner = REF if member else OTHER
        rows.append(_row(cid, actress_ids=(owner, "111"), maker_id=owner))
        facts[cid] = _facts(number, series=owner, label=owner, directors=("999", owner))
        site.details[cid] = Video(number=number, title=f"full {cid}", source="dmm")
    site.by_filter[(FILTER_KEY[kind], REF)] = ListResult(rows, len(rows), False)
    site.facts.update(facts)
    site.refs[kind] = EntityRef(kind, REF, NAME)


def _numbers(cards):
    return [c["number"] for c in cards]


# ================================================================ 邊界條件 1：官方番號（列表階段）
ENTRIES = ["run_keyword", "search_keyword", "list_entity", "ladder"]


def _seed_or_items(site, chain, entry):
    """四個入口 → 該視窗的番號清單（run／ladder 取 seed 事件；Page 入口取 items）。"""
    chain()
    seeds = []

    def cb(slot, payload):
        if slot == -1:
            seeds.append(list(payload))

    if entry == "run_keyword":
        out = _provider().run(Kind.KEYWORD, "q", W, result_callback=cb)
        assert len(out) == 20
        assert len(seeds) == 1
        return seeds[0]
    if entry == "search_keyword":
        return [i.number for i in _provider().search_keyword("q", W).items]
    if entry == "list_entity":
        return [i.number for i in _provider().list_entity(EntityRef(Kind.ACTOR, REF, NAME), W).items]
    out = relay.search_by_intent("actress", "q", W, result_callback=cb)
    assert len(out) == 20 and len(seeds) == 1
    return seeds[0]


@pytest.mark.parametrize("entry", ENTRIES)
def test_window_numbers_are_official_and_null_falls_back_to_derived(site, chain, entry):
    """〔使用者把 DMM 排第一搜 3DSVR 1774 → 骨架占位格若顯示推導的 DSVR-1774，數字看起來合理所以無從目視校驗，
    點進去或加入收藏可能刮到別部片〕官方番號只管列表階段：seed 事件與 Page.items 的 number。"""
    _register_numbers_world(site)
    got = _seed_or_items(site, chain, entry)
    assert got == EXPECTED20
    # 期望值確實不同於推導值（防止『兩邊同源』的假綠）：這兩筆的推導值是已知的錯番號
    assert "DSVR-1774" not in got and "T-28103" not in got
    assert got[2] == "SYNTH-057" and got[3] == "SSIS-001" and got[4] == "ABP-1234"  # h_／null／缺 alias


@pytest.mark.parametrize("failure", ["returns_none", "raises"])
@pytest.mark.parametrize("entry", ["run_keyword", "ladder"])
def test_all_detail_failures_keep_official_numbers_on_degraded_cards(site, chain, entry, failure):
    """〔使用者搜 3DSVR 1774、DMM 詳情暫時失敗 → shallow 卡若仍用推導番號，卡片就寫成 DSVR-1774，
    加進收藏或點下去可能刮到別部片（番號看起來合理，使用者無從察覺）〕
    DMM 的 enrich 會吞下 _fetch_by_id 的失敗並退回 shallow 卡（不走 pipeline._degraded_card），所以 shallow 卡的番號來源要官方。
    守衛的『屬於』案同時驗：詳情全失敗，belongs 照樣算得出（梯子入口仍放行）。"""
    _register_numbers_world(site)
    for cid, _, _ in SPEC20:
        site.details[cid] = None if failure == "returns_none" else RuntimeError("detail down")
    chain()
    seeds = []
    if entry == "run_keyword":
        out = _provider().run(Kind.KEYWORD, "q", W, result_callback=lambda s, d: seeds.append(s))
    else:
        out = relay.search_by_intent("actress", "q", W, result_callback=lambda s, d: seeds.append(s))
    assert len(site.detail_calls) >= 20  # 詳情真的全試過、全失敗
    assert _numbers(out) == EXPECTED20
    assert {c["_source"] for c in out} == {"dmm"}
    assert seeds[0] == -1 and sorted(seeds[1:]) == list(range(20))


@pytest.mark.parametrize("entry", ["run_keyword", "ladder"])
def test_card_with_empty_number_gets_item_number_but_nonempty_is_kept(site, chain, entry):
    """〔詳情成功但卡片番號是空的 → 補上列表階段的官方番號，不是留一張沒有番號的卡；卡片自己有番號時不被覆蓋〕"""
    _register_numbers_world(site)
    site.details["13dsvr01774"] = Video(number="", title="no number", source="dmm")
    site.details["55t28103"] = Video(number="CARD-OWN", title="own number", source="dmm")
    chain()
    if entry == "run_keyword":
        out = _provider().run(Kind.KEYWORD, "q", W)
    else:
        out = relay.search_by_intent("actress", "q", W)
    assert out[0]["number"] == "3DSVR-1774"  # 空 → 補 item.number
    assert out[1]["number"] == "CARD-OWN"  # 有值 → 不覆蓋
    assert _numbers(out)[2:] == EXPECTED20[2:]


# ---------------------------------------------------------------- I-D2：facts 恰 1 次且先於 seed
@pytest.mark.parametrize("entry", ["run_keyword", "ladder"])
def test_fetch_facts_once_per_window_and_before_seed(site, chain, entry):
    """〔I-D2〕每個非空視窗 fetch_facts 恰 1 次，且先於 result_callback(-1, …)。
    若改成 seed 之後才取：骨架先畫出推導番號、之後才被官方番號蓋過（或根本沒蓋），使用者先看到錯番號。"""
    _register_numbers_world(site)
    chain()

    def cb(slot, payload):
        site.log.append("seed" if slot == -1 else "item")

    if entry == "run_keyword":
        out = _provider().run(Kind.KEYWORD, "q", W, result_callback=cb)
    else:
        out = relay.search_by_intent("actress", "q", W, result_callback=cb)
    assert len(out) == 20  # 路徑真的跑完（不是被梯子吞掉的空殼）
    assert site.log.count("facts") == 1 and site.log.count("seed") == 1
    assert site.log.index("list") < site.log.index("facts") < site.log.index("seed")
    assert site.facts_calls == [tuple(cid for cid, _, _ in SPEC20)]  # 一次、依清單順序、全部 id
    if entry == "ladder":  # 守衛的 3 部詳情夾在 facts 與 seed 之間
        assert site.log[site.log.index("facts") + 1: site.log.index("seed")] == ["detail"] * 3


@pytest.mark.parametrize("entry", ["search_keyword", "list_entity"])
@pytest.mark.parametrize("rows", [[], [{"title": "no id"}, {"id": "", "title": "empty id"}]], ids=["empty", "no-ids"])
def test_empty_window_sends_no_facts_request(site, entry, rows):
    """〔查無的視窗不多打一個必空的請求〕空視窗或全部缺 id ⇒ fetch_facts 0 次。"""
    site.by_word["q"] = ListResult(rows, 0, False)
    site.by_filter[("actressIds", REF)] = ListResult(rows, 0, False)
    provider = _provider()
    if entry == "search_keyword":
        page = provider.search_keyword("q", W)
    else:
        page = provider.list_entity(EntityRef(Kind.ACTOR, REF, NAME), W)
    assert page.items == []
    assert site.facts_calls == [] and len(site.list_calls) == 1


# ================================================================ 邊界條件 2：守衛（relay 入口）
def test_belonging_listing_returns_cards_with_one_seed_in_list_order(site, chain, spies):
    """〔使用者在 DMM 排第一打女優／系列／導演／label 名 → 守衛若恆答不了，DMM 的實體清單每次被跳過，
    使用者只看到標題關鍵字結果而不是完整片單，沒有任何錯誤提示〕"""
    other = chain(other_cards=[{"number": "J-1"}])
    _arrange(site, Kind.ACTOR, [True] * 5)
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    calls = [c.args for c in seeds.call_args_list]
    assert [slot for slot, _ in calls].count(-1) == 1  # seed 恰 1 次
    assert calls[0] == (-1, LIST5_NUMBERS)  # 骨架＝清單順序
    assert [(slot, card["number"]) for slot, card in calls[1:]] == list(enumerate(LIST5_NUMBERS))
    assert _numbers(out) == LIST5_NUMBERS
    assert {c["_source"] for c in out} == {"dmm"}  # 梯子路徑沒有 run 的收尾補，enrich 自己補
    assert all(card["_source"] == "dmm" for _, card in calls[1:])  # callback payload 也有
    assert [r.belongs for r in spies.enrich_returns[:3]] == [True, True, True]
    assert other.run_calls == [] and spies.run.call_count == 0  # 該家答了，不再問 KEYWORD／後面


@pytest.mark.parametrize("kind", LADDER_KINDS)
def test_foreign_listing_is_rejected_and_next_provider_asked(site, chain, spies, kind):
    """〔使用者在 DMM 排第一打女優名、名稱解析認成同名別人或站方回了別份清單 → 守衛若恆放行，
    整頁別人的片被當成她的作品端出、後面的家根本沒被問，畫面看起來完全正常〕"""
    other = chain(other_cards=[{"number": "J-1", "title": "from javbus"}])
    _arrange(site, kind, [False] * 5)
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    assert out == [{"number": "J-1", "title": "from javbus"}]
    assert seeds.call_count == 0  # seed 0 次
    # 梯子吞一切例外：[] 也可能是 list_entity／enrich 內部出錯。必須量到清單真的被以正確的 filter 取過……
    assert [(c["query_word"], c["filter"], c["limit"], c["offset"]) for c in site.list_calls] == [
        (None, {FILTER_KEY[kind]: {"ids": [{"id": REF}], "op": "OR"}}, 20, 0)]
    assert len(site.facts_calls) == 1
    # ……且 3 次守衛詳情每次都明確回 belongs is False（不是 None，不是例外）
    assert spies.enrich.call_count == 3
    assert [r.belongs for r in spies.enrich_returns] == [False, False, False]
    assert len(site.detail_calls) == 3  # 守衛不通過就不再抓後面的
    assert spies.run.call_count == 0  # 命中實體的那家不再問 KEYWORD
    assert other.run_calls == [Kind.KEYWORD]  # 下一家被問到了


@pytest.mark.parametrize("kind", [Kind.ACTOR, Kind.SERIES])
@pytest.mark.parametrize("member_at", [0, 1, 2])
def test_one_of_three_guard_members_passes_the_guard(site, chain, spies, kind, member_at):
    """〔守衛只要前 3 部中有 1 部屬於就放行：少一筆關聯的片不能讓整家被跳過〕"""
    other = chain(other_cards=[{"number": "J-1"}])
    _arrange(site, kind, [i == member_at for i in range(3)], LIST5[:3])
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    assert _numbers(out) == LIST5_NUMBERS[:3]
    assert [c.args[0] for c in seeds.call_args_list].count(-1) == 1
    assert sorted(r.belongs for r in spies.enrich_returns) == [False, False, True]
    assert other.run_calls == []


@pytest.mark.parametrize("asked", [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER])
@pytest.mark.parametrize("holder", [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER])
def test_belongs_reads_the_source_of_its_own_kind(site, holder, asked):
    """五個 kind 各取對來源：REF 只出現在 holder 那一個維度（ACTOR＝列表列的女優 id、MAKER＝列表列的片商 id、
    SERIES／LABEL／DIRECTOR＝facts），問 asked 時只有 holder == asked 為 True，其餘為 False。
    〔取錯來源（例如 SERIES 去比女優 id）→ 該種實體清單永遠被守衛擋下或永遠放行〕MAKER 直接呼叫，不經梯子。"""
    row = _row("sone00001", actress_ids=(REF,) if holder is Kind.ACTOR else (OTHER,),
               maker_id=REF if holder is Kind.MAKER else OTHER)
    site.by_filter[(FILTER_KEY[asked], REF)] = ListResult([row], 1, False)
    site.facts["sone00001"] = _facts(
        "SONE-001",
        series=REF if holder is Kind.SERIES else OTHER,
        label=REF if holder is Kind.LABEL else OTHER,
        directors=("999", REF) if holder is Kind.DIRECTOR else ("999", OTHER),
    )
    provider = _provider()
    ref = EntityRef(asked, REF, NAME)
    page = provider.list_entity(ref, W)
    assert provider.enrich(page.items[0], ref).belongs is (holder is asked)


_ABSENT = [
    pytest.param(Kind.ACTOR, {"actresses": None}, _facts("X-1"), id="actor-null-actresses"),
    pytest.param(Kind.ACTOR, {"actresses": []}, _facts("X-1"), id="actor-no-actresses"),
    pytest.param(Kind.MAKER, {"maker": None}, _facts("X-1"), id="maker-null"),
    pytest.param(Kind.SERIES, {}, None, id="series-no-facts-alias"),
    pytest.param(Kind.SERIES, {}, _facts("X-1", series=None), id="series-null"),
    pytest.param(Kind.LABEL, {}, None, id="label-no-facts-alias"),
    pytest.param(Kind.LABEL, {}, _facts("X-1", label=None), id="label-null"),
    pytest.param(Kind.DIRECTOR, {}, None, id="director-no-facts-alias"),
    pytest.param(Kind.DIRECTOR, {}, _facts("X-1", directors=()), id="director-empty"),
]


@pytest.mark.parametrize("kind,row_patch,facts", _ABSENT)
def test_missing_facts_or_field_is_false_not_none(site, kind, row_patch, facts):
    """〔站方少給一個欄位 → belongs 必須是 False（確定不屬於），不是 None（梯子/守衛只認 True；None 與 False 在
    verify_page 同樣不通過，但 None 代表『不適用』會掩蓋本該被發現的缺漏〕"""
    row = {**_row("sone00001"), **row_patch}
    site.by_filter[(FILTER_KEY[kind], REF)] = ListResult([row], 1, False)
    if facts is not None:
        site.facts["sone00001"] = facts
    provider = _provider()
    ref = EntityRef(kind, REF, NAME)
    enriched = provider.enrich(provider.list_entity(ref, W).items[0], ref)
    assert enriched.belongs is False


@pytest.mark.parametrize("kind,row_patch", [
    pytest.param(Kind.ACTOR, {"actresses": [{"id": 777, "name": "x"}]}, id="actor-int-id"),
    pytest.param(Kind.MAKER, {"maker": {"id": 777, "name": "x"}}, id="maker-int-id"),
])
def test_site_ids_are_compared_as_strings(site, kind, row_patch):
    """站方 id 若是數字型（777）而 ref.id 是字串（'777'）仍算同一個。"""
    row = {**_row("sone00001", actress_ids=(OTHER,)), **row_patch}
    site.by_filter[(FILTER_KEY[kind], REF)] = ListResult([row], 1, False)
    provider = _provider()
    ref = EntityRef(kind, REF, NAME)
    assert provider.enrich(provider.list_entity(ref, W).items[0], ref).belongs is True


def test_enrich_sends_no_list_or_facts_requests(site):
    """I-D3：belongs 全由列表階段已取得的事實算出，enrich 內除 _fetch_by_id 外零網路。"""
    provider = _provider()
    for kind in (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER):
        _arrange(site, kind, [True, False, True])
    page_ref = EntityRef(Kind.SERIES, REF, NAME)
    page = provider.list_entity(page_ref, W)
    before = (len(site.list_calls), len(site.facts_calls))
    with patch.object(provider._scraper._session, "post") as post:
        verdicts = [provider.enrich(item, page_ref).belongs for item in page.items]
    assert verdicts == [True, False, True]
    assert (len(site.list_calls), len(site.facts_calls)) == before  # list_contents／fetch_facts 呼叫數 0
    assert post.call_count == 0  # 傳輸層也 0
    assert len(site.detail_calls) == 3  # 只有 _fetch_by_id


def test_entity_path_stamps_source_and_keyword_path_does_not(site):
    """實體路徑（ref 不為 None，含 T9 的 MAKER）enrich 自補 _source；KEYWORD（ref 為 None）enrich 維持今天——
    既有 test_dmm_source_stamped_after_callbacks 零修改仍綠（只有 run 收尾補，callback payload 沒有）。"""
    site.by_word["q"] = ListResult([_row("sone00001")], 1, False)
    provider = _provider()
    item = provider.search_keyword("q", W).items[0]
    keyword = provider.enrich(item, None)
    assert keyword.belongs is None and "_source" not in keyword.card
    for kind in (Kind.ACTOR, Kind.MAKER):
        assert provider.enrich(item, EntityRef(kind, REF, NAME)).card["_source"] == "dmm"
    payloads = []
    out = provider.run(Kind.KEYWORD, "q", W, result_callback=lambda s, d: payloads.append(copy.deepcopy(d)))
    item_payloads = [p for p in payloads if isinstance(p, dict)]
    assert all(c["_source"] == "dmm" for c in out)
    assert item_payloads and all("_source" not in p for p in item_payloads)


# ================================================================ 邊界條件 3：視窗與失敗
@pytest.mark.parametrize("kind", [Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER])
def test_filter_variables_shape_per_kind_and_keyword_has_no_filter(kind):
    """變數形狀固定 {limit, offset, sort, filter}、實體清單沒有 queryWord；KEYWORD 反過來沒有 filter（離線 A/B 逐位元比對靠它）。
    在傳輸層量（scraper._session.post），不在 list_contents 層。"""
    scraper = _scraper()
    body = {"data": {"legacySearchPPV": {"result": {"pageInfo": {"totalCount": 0, "hasNext": False}, "contents": []}}}}
    resp = MagicMock(status_code=200, json=lambda: body)
    with patch.object(scraper._session, "post", return_value=resp) as post:
        DMMProvider(scraper).list_entity(EntityRef(kind, REF, NAME), Window(40, 15))
        DMMProvider(scraper).search_keyword("温泉", Window(0, 20))
    assert post.call_args_list[0].kwargs["json"]["variables"] == {
        "limit": 15, "offset": 40, "sort": "RELEASE_DATE",
        "filter": {FILTER_KEY[kind]: {"ids": [{"id": REF}], "op": "OR"}}}
    assert post.call_args_list[1].kwargs["json"]["variables"] == {
        "limit": 20, "offset": 0, "sort": "RELEASE_DATE", "queryWord": "温泉"}
    assert post.call_count == 2  # 空清單 ⇒ 沒有 facts 請求


def test_window_is_passed_through_with_fixed_call_shapes():
    """Window(offset, limit) 原樣傳到 list_contents；KEYWORD 的呼叫形狀固定 (q, limit=, offset=)（不傳 filter）。"""
    provider = _provider()
    with patch.object(DMMScraper, "list_contents", return_value=ListResult([], 0, False)) as lc:
        provider.search_keyword("q", Window(20, 15))
        provider.list_entity(EntityRef(Kind.LABEL, REF, NAME), Window(40, 30))
    assert lc.call_args_list[0] == (("q",), {"limit": 15, "offset": 20})
    assert lc.call_args_list[1] == ((None,), {"filter": {"labelIds": {"ids": [{"id": REF}], "op": "OR"}},
                                              "limit": 30, "offset": 40})


@pytest.mark.parametrize("entry", ["search_keyword", "list_entity"])
@pytest.mark.parametrize("has_next,total,n_rows", [(False, 20, 20), (True, 999, 3)], ids=["full-page-but-no-next", "short-page-with-next"])
def test_has_next_and_total_come_from_page_info_not_row_count(site, entry, has_next, total, n_rows):
    """〔整頁滿而站方說沒有下一頁 → 不再用『筆數 ≥ 視窗』猜，否則多出一個必空的『載入更多』〕"""
    rows = [_row(f"mide{i:05d}") for i in range(1, n_rows + 1)]
    site.by_word["q"] = ListResult(rows, total, has_next)
    site.by_filter[("actressIds", REF)] = ListResult(rows, total, has_next)
    provider = _provider()
    if entry == "search_keyword":
        page = provider.search_keyword("q", W)
    else:
        page = provider.list_entity(EntityRef(Kind.ACTOR, REF, NAME), W)
    assert len(page.items) == n_rows
    assert page.has_next is has_next and page.total == total


def test_offset_boundary_is_measured_at_the_transport():
    """〔在長清單連按『載入更多』翻過站方上限 → 若多打必被拒的請求，使用者看到的是來源錯誤而不是『已到底』〕
    offset=10000 仍發請求（列表＋facts 兩個罐頭回應）、has_next 取自 pageInfo；offset=10001 ⇒ post 呼叫數 0。"""
    scraper = _scraper()
    list_body = {"data": {"legacySearchPPV": {"result": {
        "pageInfo": {"totalCount": 10050, "hasNext": True}, "contents": [_row("sone00001")]}}}}
    facts_body = {"data": {"a0": {"makerContentId": "SONE-001", "series": None, "label": None, "directors": []}}}
    responses = [MagicMock(status_code=200, json=lambda: list_body), MagicMock(status_code=200, json=lambda: facts_body)]
    ref = EntityRef(Kind.ACTOR, REF, NAME)
    with patch.object(scraper._session, "post", side_effect=responses) as post:
        page = DMMProvider(scraper).list_entity(ref, Window(10000, 20))
    assert post.call_count == 2
    assert page.has_next is True and page.total == 10050 and [i.number for i in page.items] == ["SONE-001"]
    with patch.object(scraper._session, "post") as post:
        beyond = DMMProvider(scraper).list_entity(ref, Window(10001, 20))
        beyond_kw = DMMProvider(scraper).search_keyword("q", Window(10001, 20))
    assert post.call_count == 0
    assert beyond.items == [] and beyond.has_next is False and beyond_kw.items == []


FAILURES = [
    pytest.param(SourceBlocked("blocked"), id="SourceBlocked"),
    pytest.param(SourceUnreachable("down"), id="SourceUnreachable"),
    pytest.param(requests.Timeout("slow"), id="Timeout"),
    pytest.param(ConnectionError("refused"), id="ConnectionError"),
]


@pytest.mark.parametrize("exc", FAILURES)
@pytest.mark.parametrize("stage", ["list", "facts"])
@pytest.mark.parametrize("entry", ["ladder", "keyword"])
def test_transport_failure_propagates_and_next_provider_is_asked(site, chain, entry, stage, exc):
    """〔DMM 暫擋 → 若被當空頁，使用者以為這位女優沒有作品而不是改問下一家〕list_contents／fetch_facts 任何失敗
    原樣往外丟（BE-PY-03）：經 relay 回到下一家（梯子入口＝命中實體的那家不再問 KEYWORD；KEYWORD 入口＝run 拋出由 relay 接住）。"""
    other = chain(other_cards=[{"number": "J-1"}])
    if entry == "ladder":
        _arrange(site, Kind.ACTOR, [True] * 5)
    else:
        site.by_word[NAME] = ListResult([_row("sone00001")], 1, False)
    if stage == "list":
        site.list_error = exc
    else:
        site.facts_error = exc
    seeds = MagicMock()
    out = relay.search_by_intent("actress", NAME, W, result_callback=seeds)
    assert out == [{"number": "J-1"}]
    assert other.run_calls == [Kind.KEYWORD]
    assert seeds.call_count == 0
    assert site.list_calls and (stage == "list" or site.facts_calls)  # 路徑真的走到出錯的那一步
    # 直接呼叫：不吞、不轉型、不退成空頁
    provider = _provider()
    with pytest.raises(type(exc)):
        if entry == "ladder":
            provider.list_entity(EntityRef(Kind.ACTOR, REF, NAME), W)
        else:
            provider.search_keyword(NAME, W)


@pytest.mark.parametrize("kind", [Kind.CODE, Kind.PARTIAL, Kind.KEYWORD])
def test_list_entity_unsupported_kind_raises_value_error_without_request(site, kind):
    with pytest.raises(ValueError):
        _provider().list_entity(EntityRef(kind, REF, NAME), W)
    assert site.list_calls == [] and site.facts_calls == []


# ================================================================ 邊界條件 4：null 容錯
@pytest.mark.parametrize("entry", ["search_keyword", "list_entity"])
def test_rows_with_null_fields_still_become_items(site, entry):
    """〔DMM 某一列缺標題或封面 → 若整頁被丟，使用者搜尋結果少了一整頁卻不知道原因（舊函式就是整頁吞成空）〕
    title／largeUrl／maker.name 為 null、maker 為 null、actresses 為 null：該列仍成 WorkItem（欄位空字串）；
    只有缺 id（或 id 為空）的列被丟，其餘列不受影響。"""
    rows = [
        {"id": "sone00001", "title": None, "packageImage": None, "actresses": None, "maker": None},
        {"id": "sone00002", "title": "t2", "packageImage": {"largeUrl": None}, "actresses": [], "maker": {"id": "1", "name": None}},
        {"id": "sone00003", "title": "t3", "packageImage": {"largeUrl": "u3"},
         "actresses": [{"id": None, "name": None}, {"id": "5", "name": "甲（舊名）"}], "maker": {"id": "2", "name": "M3"}},
        {"title": "no id"},
        {"id": "", "title": "empty id"},
        _row("sone00004"),
    ]
    site.by_word["q"] = ListResult(rows, 6, False)
    site.by_filter[("actressIds", REF)] = ListResult(rows, 6, False)
    provider = _provider()
    if entry == "search_keyword":
        page = provider.search_keyword("q", W)
    else:
        page = provider.list_entity(EntityRef(Kind.ACTOR, REF, NAME), W)
    assert site.facts_calls == [("sone00001", "sone00002", "sone00003", "sone00004")]  # 缺 id 的不送
    assert [i.ref[0] for i in page.items] == ["sone00001", "sone00002", "sone00003", "sone00004"]
    first, second, third, fourth = (i.ref[1] for i in page.items)
    assert (first.title, first.cover_url, first.maker, first.actresses) == ("", "", "", [])
    assert (second.title, second.cover_url, second.maker) == ("t2", "", "")
    assert (third.title, third.cover_url, third.maker, [a.name for a in third.actresses]) == ("t3", "u3", "M3", ["甲"])
    assert (fourth.title, fourth.cover_url, fourth.maker) == ("title sone00004", "https://img.invalid/sone00004.jpg", "片商888")
    assert [i.title for i in page.items] == ["", "t2", "t3", "title sone00004"]
    # 這些列的 shallow 卡也能照常出（詳情失敗退回 shallow）
    site.details.update({"sone00001": None, "sone00002": RuntimeError("x")})
    card = provider.enrich(page.items[0], None).card
    assert card["number"] == "SONE-001" and card["title"] == "" and card["cover"] == "" and card["actors"] == []


# ================================================================ 邊界條件 5：能力與接線
def test_capabilities_are_exactly_the_four_entities_plus_keyword():
    """〔使用者把 DMM 排第一打 MIDV／MIDV-01 → 若誤宣告 CODE／PARTIAL，結果混入 48midv… 重製版與別片商；
    若誤宣告 MAKER 而沒有 run_maker，片商膠囊一按就丟 TypeError〕"""
    assert DMMProvider.capabilities == frozenset({Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.KEYWORD})
    assert not DMMProvider.capabilities & {Kind.MAKER, Kind.CODE, Kind.PARTIAL}
    assert DMMProvider.supports_discovery is False and DMMProvider.fallback_streaming is True


@pytest.mark.parametrize("kind", [Kind.CODE, Kind.PARTIAL, Kind.MAKER])
def test_run_rejects_kinds_it_does_not_declare(site, kind):
    with pytest.raises(ValueError):
        _provider().run(kind, "MIDV", W)
    assert site.list_calls == [] and site.facts_calls == [] and site.detail_calls == []


def test_discovery_only_touches_no_transport_and_ladder_is_not_asked(site, chain, spies):
    """discovery_only：run 不碰傳輸；relay 入口 DMM（supports_discovery=False）不在鏈上，resolve／list_entity 呼叫數 0。"""
    assert _provider().run(Kind.KEYWORD, "q", W, discovery_only=True) == []
    other = chain(discovery=True)
    site.refs[Kind.ACTOR] = EntityRef(Kind.ACTOR, REF, NAME)
    relay.search_by_intent("actress", NAME, W, discovery_only=True)
    assert site.resolve_calls == [] and spies.list_entity.call_count == 0
    assert site.list_calls == [] and site.facts_calls == [] and site.detail_calls == []
    assert other.run_calls == [Kind.KEYWORD]


def test_keyword_path_numbers_follow_the_window_and_cards_keep_today_shape(site):
    """KEYWORD 路徑（ref 為 None）行為維持今天：骨架 → 逐部卡 → 收尾補 _source；沒有 facts 時番號走推導退路。"""
    site.by_word["q"] = ListResult([_row("sone00001"), _row("sone00002")], 2, False)
    site.details = {"sone00001": None, "sone00002": None}
    events = []
    out = _provider().run(Kind.KEYWORD, "q", W, result_callback=lambda s, d: events.append((s, copy.deepcopy(d))))
    assert events[0] == (-1, ["SONE-001", "SONE-002"])  # 沒登記 facts ⇒ 推導退路（字面值）
    assert [c["number"] for c in out] == ["SONE-001", "SONE-002"]
    assert all(c["_source"] == "dmm" for c in out)
