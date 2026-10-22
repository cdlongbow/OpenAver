"""test_provider_entity_contract.py — 任關一家矩陣（TASK-175c-T10，plan CD-175c-11／-10／-12，F1）。

設定頁任關一家，前綴／部分番號／女優／系列／導演／label／片商／關鍵字八種查詢鏈上仍有人回答。
stub 的能力屬性在測試當下才從真 provider 類別讀（不抄成字面），所以任何一家少宣告一個能力都會紅。

三家各自「屬於／不屬於」的守衛合約原本在這裡用假傳輸驗；站方回應不在單元測試裡造假，改靠活站金絲雀
（tests/smoke/test_javbus_search_canary.py、tests/smoke/test_dmm_search_canary.py）。
"""
from __future__ import annotations

import concurrent.futures as cf
import time

import pytest

from core.search_providers import registry, relay
from core.search_providers.types import EntityRef, Enriched, Kind, MakerSearchResult, Page, Window, WorkItem

NAME = "Alice"
WINDOW = Window(0, 20)
# 矩陣的順序偏好；registry 之後新增的 id 接在後面
_ORDER_PREF = ("javbus", "dmm", "javdb")


# ================================================================ 隔離
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
    """pipeline 每部詳情後 sleep：換掉；執行緒池換成同步（完成順序＝提交順序）；maker 接力的行程內 LRU 前後都清。"""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    relay._reset_maker_answerers()
    yield
    relay._reset_maker_answerers()


def _set_chain(monkeypatch, order, enabled=None):
    """順序與開關 patch 使用端 core.scraper.*（BE-TEST-01／02）。"""
    on = set(order if enabled is None else enabled)
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(order))
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)


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
