"""test_provider_entity_contract.py — 三家同組實體合約測試載體（TASK-175c-T10，plan CD-175c-11／-10／-12，F1）。

relay 對「每個宣告實體能力的 provider」的守衛硬契約，對 `registry` 全體成立、新 provider 自動套用：

- (1)(2) 守衛：每個 provider × 其宣告的每個實體 kind 一格；從 `relay.search_by_intent("actress", …)` 入口驗，
  真 registry ＋ 真 provider，只換傳輸邊界（類別層／模組層 monkeypatch，命名錯誤會直接 AttributeError）。
  「屬於」→ 本家答、seed 恰 1 次、不再問 KEYWORD／後備；「不屬於」→ seed 0 次、換下一家。
- (5) 載體自測：本家 `enrich` 的 belongs 被強制為 None 時，(1) 的檢查函式必須紅（它咬得住「守衛恆答不了」）。
- 矩陣：設定頁任關一家，前綴／部分番號／女優／系列／導演／label／片商／關鍵字八種查詢鏈上仍有人回答。
  stub 的能力屬性在測試當下才從真 provider 類別讀（不抄成字面），所以任何一家少宣告一個能力都會紅。

新增 provider 時：在 `FACTORIES` 補一個 fake-transport factory（簽章見 `_factory`）。漏補 ⇒ KeyError ⇒ 紅，不 skip。

不 patch 任何 provider 的 resolve／list_entity／enrich／run（那會跳過本載體要驗的接線），只准包裝式 spy
（BE-TEST-46：量 call_count／Hits，不用 side_effect=AssertionError——梯子逐層 `except Exception` 會吞掉）。
合成資料全為檔內字面，不收站方存檔；零活站請求。

R2 去重：站方順序／slot 號／官方番號／HTTP 狀態碼分類／resolve 例外矩陣／請求預算由各家單元測試守，本檔不重寫；
斷言面只有五種跨 provider 一致的可觀察量——relay 回傳與 `_source`、seed（slot −1）次數、本家與後備 `run` 的呼叫、
本家 `enrich` 回傳的 belongs 序列、清單傳輸 `Hits`。
"""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import time
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from core.scrapers import javdb_api
from core.scrapers.dmm import DMMScraper, Facts, ListResult, Named
from core.scrapers.javbus import JavBusScraper, ListCard, StarCard
from core.scrapers.models import Video
from core.search_providers import javdb as javdb_mod
from core.search_providers import registry, relay
from core.search_providers.javdb import JavDBProvider
from core.search_providers.types import EntityRef, Enriched, Kind, MakerSearchResult, Page, Window, WorkItem

# relay 梯子的實體 kind（字面明定，plan）；MAKER 不經梯子，由矩陣的 search_maker 格驗
ENTITY_KINDS = (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL)
NAME = "Alice"
WINDOW = Window(0, 20)
LIST_SIZE = 3  # 守衛看前 3 部（pipeline.GUARD_SIZE）；清單剛好 3 部，enrich 次數才可斷言
# 矩陣的順序偏好；registry 之後新增的 id 接在後面
_ORDER_PREF = ("javbus", "dmm", "javdb")


# ================================================================ 隔離（設計決策 G）
class SyncExecutor:
    """執行緒池換成同步（完成順序＝提交順序）。"""

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
def _isolation(monkeypatch):
    """pipeline 每部詳情後 sleep、JavDB 每次請求後 sleep：全換掉；UI 語言固定 zh-tw（JavBus 實體清單仍須走 /ja）。
    JavDB 的 resolve 快取沒有任何 conftest 在清（JavBus／DMM 的由 conftest autouse 清），前後都清，
    否則前一格的 resolve 結果被快取、後面的格不再打 api_search_typed，行為隨執行順序而變。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr("core.scraper.get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(javdb_mod, "_sleep", lambda s: None)
    javdb_mod.clear_resolve_cache()
    relay._reset_maker_answerers()
    yield
    javdb_mod.clear_resolve_cache()
    relay._reset_maker_answerers()


# ================================================================ cell 導出（設計決策 B）
def _cells() -> list:
    """registry 全體 × 各自宣告的實體 kind；不手寫（新 provider／新 kind 自動納入）。"""
    out = []
    for pid in sorted(registry.registered_ids()):
        declared = registry.new_provider(pid).capabilities
        out.extend(pytest.param(pid, kind, id=f"{pid}-{kind.value}") for kind in ENTITY_KINDS if kind in declared)
    return out


CELLS = _cells()
# (5) 每家一格：取該家第一個宣告的實體 kind
def _first_kinds() -> dict:
    out: dict = {}
    for cell in CELLS:
        out.setdefault(*cell.values)
    return out


FIRST_KIND = _first_kinds()
SELF_TEST_CELLS = [pytest.param(pid, kind, id=pid) for pid, kind in FIRST_KIND.items()]


# ================================================================ 傳輸替身共用件
class Hits:
    """清單傳輸函式被打到幾次。梯子吞一切例外，單看回傳 [] 可能是 typo 造成的假綠。"""

    def __init__(self):
        self.list = 0


class Other:
    """後備 provider（另一個已註冊 id 的替身）：只宣告 KEYWORD，run 回罐頭卡並記錄呼叫的 kind。"""

    capabilities = frozenset({Kind.KEYWORD})

    def __init__(self, pid):
        self.id = pid
        self.supports_discovery = False
        self.fallback_streaming = True
        self.cards = [{"number": f"FALLBACK-{pid}", "title": "from fallback", "_source": pid}]
        self.run_calls = []

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append(kind)
        return list(self.cards)


def _set_chain(monkeypatch, order, enabled=None):
    """順序與開關 patch 使用端 core.scraper.*（BE-TEST-01／02）。"""
    on = set(order if enabled is None else enabled)
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)


# ---------------------------------------------------------------- JavBus
# kind -> (fetch_entity_link 的 segment；None＝女優走 search_stars, ref.id, Video.entity_ids 的鍵)
_JAVBUS_SHAPE = {
    Kind.ACTOR: (None, "star/okq", "actors"),
    Kind.SERIES: ("series", "series/rvz", "series"),
    Kind.DIRECTOR: ("director", "director/36a", "director"),
    Kind.LABEL: ("label", "label/9x", "label"),
}


def _javbus_factory(monkeypatch, kind, name, *, member):
    segment, ref_id, key = _JAVBUS_SHAPE[kind]
    code = ref_id.rsplit("/", 1)[-1]
    numbers = [f"AAA-{i:03d}" for i in range(1, LIST_SIZE + 1)]
    hits = Hits()

    def search_stars(self, q):
        return [StarCard(ref_id, name, False)] if segment is None else []

    def fetch_entity_link(self, q, seg):
        return (ref_id, name) if seg == segment else None

    def get_entries_from_entity(self, entity_id, page=1):
        hits.list += 1
        if page != 1 or entity_id != ref_id:
            return []
        return [ListCard(n, f"T-{n}", f"/pics/thumb/{n}.jpg", "2026-01-01") for n in numbers]

    def search(self, number):
        return Video(number=number, title=f"Title {number}", maker="M", date="2026-01-01", source="javbus",
                     entity_ids={key: [code] if member else ["zzz"]})

    def get_ids_from_search(self, keyword, page=1, search_type=0, **kw):
        return []  # KEYWORD 安全網：梯子被跳過時才會走到這裡

    for attr, fn in (("search_stars", search_stars), ("fetch_entity_link", fetch_entity_link),
                     ("get_entries_from_entity", get_entries_from_entity), ("search", search),
                     ("get_ids_from_search", get_ids_from_search)):
        monkeypatch.setattr(JavBusScraper, attr, fn)
    return hits


# ---------------------------------------------------------------- DMM
def _dmm_factory(monkeypatch, kind, name, *, member):
    probe_ids = ("p1", "p2")  # 名稱→實體（stage 1／2）的探測列
    list_ids = ("c1", "c2", "c3")  # 實體清單的列
    hits = Hits()

    def row(cid, actress):
        return {"id": cid, "title": f"title {cid}", "packageImage": {"largeUrl": f"https://img.invalid/{cid}.jpg"},
                "actresses": [{"id": actress[0], "name": actress[1]}], "maker": {"id": "M1", "name": "maker"}}

    def list_contents(self, query_word=None, filter=None, *, limit, offset):
        if filter is None:  # Probe：只有被測 kind 是女優時，探測列才帶她的名字（其他格改帶別人，否則 ACTOR 先命中）
            who = ("T1", name) if kind is Kind.ACTOR else ("A0", "someone else")
            return ListResult([row(c, who) for c in probe_ids], len(probe_ids), False)
        hits.list += 1
        return ListResult([row(c, ("T1" if member else "X9", name)) for c in list_ids], len(list_ids), False)

    def fetch_facts(self, content_ids):
        out = {}
        for cid in content_ids:
            mine = Named("T1" if (cid in probe_ids or member) else "X9", name)
            other = Named("O1", "unrelated")
            out[cid] = Facts(f"TST-{cid.upper()}",
                             mine if kind is Kind.SERIES else other,
                             mine if kind is Kind.LABEL else other,
                             [mine if kind is Kind.DIRECTOR else other])
        return out

    def fetch_by_id(self, content_id):
        return None  # 詳情失敗＝退 shallow 卡（enrich 零網路）

    for attr, fn in (("list_contents", list_contents), ("fetch_facts", fetch_facts), ("_fetch_by_id", fetch_by_id)):
        monkeypatch.setattr(DMMScraper, attr, fn)
    return hits


# ---------------------------------------------------------------- JavDB
_JAVDB_SEARCH_TYPE = {Kind.ACTOR: "actor", Kind.SERIES: "series", Kind.DIRECTOR: "director"}  # 沒有 LABEL


def _javdb_factory(monkeypatch, kind, name, *, member):
    search_type = _JAVDB_SEARCH_TYPE[kind]
    hits = Hits()

    def api_search_typed(t, q, proxies=None):
        if t != search_type:
            return []
        cand = {"id": "J1", "name": name, "name_zht": "", "other_name": "", "videos_count": 50}
        if kind is Kind.ACTOR:
            cand["type"] = 0
        return [cand]

    def api_list_tags(filter_by, page, limit=50, proxies=None):
        hits.list += 1
        if page != 1 or not filter_by.endswith(":J1"):
            return []
        return [{"id": f"m{i}", "number": f"JDB-{i:03d}", "title": f"t{i}", "origin_title": f"jt{i}",
                 "cover_url": f"http://c/{i}.jpg", "release_date": "2026-01-01"} for i in range(1, LIST_SIZE + 1)]

    def api_search_page(q, page, limit=50, proxies=None):
        return []

    def api_movie_detail(movie_id, proxies=None):
        owner = "J1" if member else "J9"
        detail = {"id": movie_id, "title": f"jt {movie_id}", "release_date": "2026-01-01",
                  "cover_url": f"http://c/{movie_id}.jpg"}
        if kind is Kind.ACTOR:
            detail["actors"] = [{"id": owner, "name": "n", "gender": 0}]
        elif kind is Kind.SERIES:
            detail["series_id"] = owner
        else:
            detail["director_id"] = owner
        return detail

    for attr, fn in (("api_search_typed", api_search_typed), ("api_list_tags", api_list_tags),
                     ("api_search_page", api_search_page), ("api_movie_detail", api_movie_detail)):
        monkeypatch.setattr(javdb_api, attr, fn)
    monkeypatch.setattr(JavDBProvider, "_proxies", lambda self: None)
    return hits


# 每家一個 fake-transport factory：簽章 (monkeypatch, kind, name, *, member) -> Hits。
# member＝清單的每一部是否真的屬於該實體；Hits.list 在清單傳輸函式內遞增。
FACTORIES = {
    "javbus": _javbus_factory,
    "dmm": _dmm_factory,
    "javdb": _javdb_factory,
}


def _factory(pid):
    try:
        return FACTORIES[pid]
    except KeyError:
        raise KeyError(
            f"已註冊的 provider {pid!r} 沒有 fake-transport factory：請在 FACTORIES 補一個（簽章 "
            f"(monkeypatch, kind, name, *, member) -> Hits）"
        ) from None


# ================================================================ (1)(2) 共用：驅動與檢查（純函式，失敗拋 AssertionError）
@dataclass
class Observed:
    pid: str
    out: list
    seeds: list  # [(slot, payload)…]，relay 轉送給呼叫端的 result_callback
    hits: Hits
    other: Other
    run_calls: int  # 本家 run 被呼叫幾次
    enrich_calls: int
    enrich_returns: list  # 本家 enrich 的回傳（量 belongs）

    @property
    def seed_count(self):
        return [slot for slot, _ in self.seeds].count(-1)


def _drive(monkeypatch, pid, kind, *, member, force_belongs_none=False) -> Observed:
    """被測 provider 排第一、另一個已註冊 id 換成 Other 排第二，只開這兩家；從 relay 入口打女優查詢。
    force_belongs_none：把本家 enrich 包成「呼叫原函式後把 belongs 改 None」（卡片照常回傳；(5) 載體自測用）。"""
    ids = sorted(registry.registered_ids())
    other_id = next(i for i in ids if i != pid)
    other = Other(other_id)
    cls = type(registry.new_provider(pid))  # 不寫死三個類別 import：新 provider 自動套用
    hits = _factory(pid)(monkeypatch, kind, NAME, member=member)
    monkeypatch.setitem(registry._REGISTRY, other_id, lambda: other)
    _set_chain(monkeypatch, [pid, other_id])

    returns = []
    orig_enrich = cls.enrich

    def enrich_spy(self, item, ref):
        out = orig_enrich(self, item, ref)
        if force_belongs_none:
            out = dataclasses.replace(out, belongs=None)
        returns.append(out)
        return out

    seeds = []
    with patch.object(cls, "enrich", autospec=True, side_effect=enrich_spy) as enrich, \
            patch.object(cls, "run", autospec=True, side_effect=cls.run) as run:
        out = relay.search_by_intent("actress", NAME, WINDOW, result_callback=lambda slot, payload: seeds.append((slot, payload)))
    return Observed(pid, out, seeds, hits, other, run.call_count, enrich.call_count, returns)


def _assert_member_page_answers(obs: Observed) -> None:
    """(1) 屬於：本家答、seed 恰 1 次、本家 run 0 次（不再問 KEYWORD）、後備 run 0 次、前 3 次 enrich belongs 皆 True。"""
    assert obs.out, f"{obs.pid}: 屬於她的清單卻回空——守衛恆答不了？（整家被默默跳過）"
    assert {c.get("_source") for c in obs.out} == {obs.pid}, f"{obs.pid}: 卡片來源不是本家: {obs.out}"
    assert obs.seed_count == 1, f"{obs.pid}: seed 應恰 1 次，實際 {obs.seed_count}"
    assert obs.hits.list >= 1, f"{obs.pid}: 清單傳輸沒被打到"
    assert obs.run_calls == 0, f"{obs.pid}: 該家答了實體，不該再問 run（KEYWORD）"
    assert obs.other.run_calls == [], f"{obs.pid}: 後備不該被問到: {obs.other.run_calls}"
    assert [r.belongs for r in obs.enrich_returns[:LIST_SIZE]] == [True] * LIST_SIZE, (
        f"{obs.pid}: 守衛前 {LIST_SIZE} 部的 belongs 應全為 True，實際 {[r.belongs for r in obs.enrich_returns]}")


def _assert_foreign_page_rejected(obs: Observed) -> None:
    """(2) 不屬於：回傳＝後備的卡、seed 0 次、enrich 恰 3 次且逐次 belongs is False、清單真的被取過、本家 run 0 次、
    後備 run 恰一次且為 KEYWORD。梯子吞一切例外，所以不能只看回傳值。"""
    assert obs.out == obs.other.cards, f"{obs.pid}: 別人的清單被端出來了或沒換家: {obs.out}"
    assert obs.seed_count == 0 and not obs.seeds, f"{obs.pid}: 守衛不通過不得送 seed: {obs.seeds}"
    assert obs.hits.list >= 1, f"{obs.pid}: 清單傳輸沒被打到——梯子可能根本沒進場"
    assert obs.enrich_calls == LIST_SIZE, f"{obs.pid}: 守衛應恰抓 {LIST_SIZE} 部詳情，實際 {obs.enrich_calls}"
    assert [r.belongs for r in obs.enrich_returns] == [False] * LIST_SIZE, (
        f"{obs.pid}: 每部都應明確回 belongs is False，實際 {[r.belongs for r in obs.enrich_returns]}")
    assert obs.run_calls == 0, f"{obs.pid}: 命中實體的那家不再問 KEYWORD"
    assert obs.other.run_calls == [Kind.KEYWORD], f"{obs.pid}: 後備應被問一次 KEYWORD: {obs.other.run_calls}"


# ================================================================ (1)(2)(5) 測試
@pytest.mark.parametrize("pid,kind", CELLS)
def test_member_page_answers_with_one_seed(monkeypatch, pid, kind):
    """〔使用者把某家排第一打女優／系列／導演／label 名 → 該家宣告了實體能力卻讓守衛恆答不了，整家被默默跳過、
    只看到後面一家的結果而不是她在這家的片單；沒有任何錯誤提示〕"""
    _assert_member_page_answers(_drive(monkeypatch, pid, kind, member=True))


@pytest.mark.parametrize("pid,kind", CELLS)
def test_foreign_page_is_rejected_and_next_provider_asked(monkeypatch, pid, kind):
    """〔使用者把某家排第一打名字、名稱解析選到同名別人或站方回了別份清單 → 守衛若恆放行，整頁別人的片被當成
    她的作品端出、後面的家根本沒被問，畫面看起來完全正常〕"""
    _assert_foreign_page_rejected(_drive(monkeypatch, pid, kind, member=False))


@pytest.mark.parametrize("pid,kind", SELF_TEST_CELLS)
def test_belongs_always_none_is_caught_by_the_contract(monkeypatch, pid, kind):
    """(5) 載體自測。〔新增或改動 provider 後守衛恆答不了 → 該家實體清單永遠被默默跳過、沒有任何錯誤提示；
    載體若抓不到，這類回歸就無人知道〕本家 enrich 的 belongs 被強制為 None（卡片照常回傳）時，(1) 的檢查函式必須紅。"""
    obs = _drive(monkeypatch, pid, kind, member=True, force_belongs_none=True)
    # 只因 belongs 不同而紅：enrich 照常產出卡片，只有 belongs 被改成「不適用」
    assert obs.enrich_calls == LIST_SIZE and all(r.card for r in obs.enrich_returns)
    assert [r.belongs for r in obs.enrich_returns] == [None] * LIST_SIZE
    with pytest.raises(AssertionError):
        _assert_member_page_answers(obs)


# ================================================================ 任關一家矩陣（設計決策 F）
class Stub:
    """矩陣用 stub：對宣告的 kind 一律回 1 張卡；capabilities／supports_discovery／fallback_streaming 在讀取當下
    才從真 provider 類別取（不抄成字面——真 provider 少宣告一個能力，矩陣就紅）。

    實體 kind：resolve 只對 target 回 ref、list_entity 1 項、enrich 回 belongs=True；run／run_maker 回罐頭卡。
    卡片帶 `_path` 標記，用來分辨「實體路徑」與「關鍵字墊底」。未宣告的 kind，run 拋 ValueError（同真 provider）。"""

    def __init__(self, pid, real_cls, target):
        self.id = pid
        self._real = real_cls
        self._target = target

    @property
    def capabilities(self):
        return self._real.capabilities

    @property
    def supports_discovery(self):
        return self._real.supports_discovery

    @property
    def fallback_streaming(self):
        return self._real.fallback_streaming

    def _card(self, path):
        return {"number": f"{path.upper()}-{self.id}", "title": f"{path} card", "_source": self.id, "_path": path}

    def resolve(self, kind, name):
        return EntityRef(kind, f"{self.id}-ref", name) if kind is self._target else None

    def list_entity(self, ref, w):
        return Page([WorkItem(f"ENT-{self.id}", "t", "", "", None, self.id, ref="x")])

    def enrich(self, item, ref):
        return Enriched(self._card("entity"), True)

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        if kind not in self.capabilities:
            raise ValueError(f"{self.id} run: unsupported kind {kind}")
        return [self._card("keyword" if kind is Kind.KEYWORD else "run")]

    def run_maker(self, maker_key, label, spellings, offset, *, limit=None, titles=None, today=None,
                  status_callback=None, result_callback=None, db_path=None):
        return MakerSearchResult([self._card("maker")], False, None)


def _by_intent(mode, q):
    return lambda: relay.search_by_intent(mode, q, WINDOW)


def _maker_query():
    return relay.search_maker("k", "S1", ["S1"], 0, titles=[], today=None).results


# query id -> (stub.resolve 肯回 ref 的 kind；期望卡片來自哪條路徑；發問)
QUERIES = {
    "code": (None, "run", _by_intent("prefix", "MIDV")),
    "partial": (None, "run", _by_intent("partial", "MIDV-01")),
    "actor": (Kind.ACTOR, "entity", _by_intent("actress", NAME)),
    "series": (Kind.SERIES, "entity", _by_intent("actress", NAME)),
    "director": (Kind.DIRECTOR, "entity", _by_intent("actress", NAME)),
    "label": (Kind.LABEL, "entity", _by_intent("actress", NAME)),
    "keyword": (None, "keyword", _by_intent("actress", NAME)),  # 無任何 kind 解析成功 → 梯子落空 → 問 KEYWORD
    "maker": (None, "maker", _maker_query),
}
MATRIX = [pytest.param(off, query, id=f"off-{off}-{query}")
          for off in sorted(registry.registered_ids()) for query in QUERIES]


@pytest.mark.parametrize("off,query", MATRIX)
def test_any_single_provider_off_still_answers_every_query_kind(monkeypatch, off, query):
    """〔使用者關掉任一家（連不上或不想用）→ 任一種查詢若鏈上沒人宣告：前綴／部分番號／片商＝查無且沒有提示，
    女優／系列／導演／label＝掉到標題關鍵字、拿到的不是該實體的片單；DMM 不宣告前綴／部分番號（CD-175c-10），
    所以 JavBus＋JavDB 兩家必須各自仍在〕經真 registry ＋ 真 relay；實體四格另須經實體路徑回答。"""
    target, path, ask = QUERIES[query]
    ids = sorted(registry.registered_ids())
    reals = {pid: type(registry.new_provider(pid)) for pid in ids}  # 換 stub 之前先取真類別
    for pid in ids:
        monkeypatch.setitem(registry._REGISTRY, pid, lambda s=Stub(pid, reals[pid], target): s)
    order = [p for p in _ORDER_PREF if p in ids] + [p for p in ids if p not in _ORDER_PREF]
    _set_chain(monkeypatch, order, enabled=[p for p in order if p != off])
    cards = ask()
    assert cards, f"關掉 {off} 後，{query} 查詢鏈上沒有任何一家回答（查無且沒有提示）"
    assert {c.get("_path") for c in cards} == {path}, f"關掉 {off} 後，{query} 沒有經 {path} 路徑回答: {cards}"
