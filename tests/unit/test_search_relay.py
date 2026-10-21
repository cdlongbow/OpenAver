"""175a-T7a：relay（接力）與註冊表 providers_for／new_provider。

全部用測試檔內的合成 provider，不 import 真 JavBusProvider／DMMProvider 的行為、不連網（BE-TEST-43）。
鏈順序與開關 patch 使用端 core.scraper.*（BE-TEST-01）；「不准呼叫」量 call_count（BE-TEST-46）。
"""

import concurrent.futures as cf
import itertools
import time
from unittest.mock import MagicMock

import pytest

from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import registry, relay
from core.search_providers.types import Enriched, EntityRef, Kind, Page, Window, WorkItem

W = Window(0, 20)
REF = EntityRef(Kind.ACTOR, "a1", "someone")
BASE_CAPS = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE})


def card(n):
    return {"number": n, "title": f"t {n}"}


class Fake:
    """行為由建構參數決定：cards＝run 回傳；seed＝拿到 callback 時先送 seed；raises＝run 拋；
    seed 與 raises 同時給＝送 seed 後才拋。"""

    def __init__(self, pid, *, cards=(), seed=None, raises=None, discovery=False, caps=BASE_CAPS,
                 fallback_streaming=True):
        self.id = pid
        self.fallback_streaming = fallback_streaming
        self.capabilities = caps
        self.supports_discovery = discovery
        self.cards = list(cards)
        self.seed = seed
        self.raises = raises
        self.run_calls = []  # (kind, target, w, status_cb, result_cb, discovery_only)
        self.order_log = None

    def run(self, kind, target, w, *, status_callback=None, result_callback=None, discovery_only=False):
        self.run_calls.append((kind, target, w, status_callback, result_callback, discovery_only))
        if self.order_log is not None:
            self.order_log.append(self.id)
        if self.seed and result_callback is not None:
            result_callback(-1, list(self.seed))
        if self.raises is not None:
            raise self.raises
        return list(self.cards)

    @property
    def received_callbacks(self):
        return [c[4] for c in self.run_calls]


class EntityFake(Fake):
    """宣告 ACTOR 的實體型 provider：resolve → list_entity → enrich；KEYWORD 走 run。"""

    def __init__(self, pid, *, ref=REF, resolve_raises=None, belongs=True, enrich_raises=None, n_items=4, **kw):
        super().__init__(pid, caps=BASE_CAPS | {Kind.ACTOR}, **kw)
        self.ref = ref
        self.resolve_raises = resolve_raises
        self.belongs = belongs
        self.enrich_raises = enrich_raises
        self.items = [WorkItem(f"E-{i:03d}", f"t{i}", "", "", None, pid) for i in range(n_items)]
        self.resolve_calls = []

    def resolve(self, kind, name):
        self.resolve_calls.append((kind, name))
        if self.resolve_raises is not None:
            raise self.resolve_raises
        return self.ref

    def list_entity(self, ref, w):
        return Page(list(self.items), False, None)

    def enrich(self, item, ref):
        if self.enrich_raises is not None:
            raise self.enrich_raises
        return Enriched(card(item.number), self.belongs)


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
        except Exception as exc:  # noqa: BLE001 — 與真 executor 相同
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)


@pytest.fixture
def chain(monkeypatch):
    """chain(providers, order=None, enabled=None, extra_registered=()) ：把合成 provider 放進註冊表並固定順序／開關。
    order 預設＝providers 的 id 順序；enabled 預設＝全開。回傳每個 id 的工廠呼叫計數 dict。"""

    def setup(providers, order=None, enabled=None, extra_registered=()):
        counts = {}
        for p in providers:
            counts[p.id] = 0

            def factory(p=p):
                counts[p.id] += 1
                return p

            monkeypatch.setitem(registry._REGISTRY, p.id, factory)
        for pid in extra_registered:
            monkeypatch.setitem(registry._REGISTRY, pid, lambda pid=pid: Fake(pid, cards=[card("X")]))
        ids = order if order is not None else [p.id for p in providers]
        on = (set(ids) | set(extra_registered)) if enabled is None else set(enabled)
        monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: list(ids))
        monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid in on)
        return counts

    return setup


def search(mode="partial", q="q", w=W, **kw):
    return relay.search_by_intent(mode, q, w, **kw)


# ---------------------------------------------------------------- registry
def test_registered_ids_are_javbus_and_dmm():
    assert registry.registered_ids() == frozenset({"javbus", "dmm"})


# ---------------------------------------------------------------- 接力語意
def test_first_non_empty_provider_wins_and_later_not_asked(chain):
    a, b = Fake("a", cards=[card("A-1")]), Fake("b", cards=[card("B-1")])
    chain([a, b])
    assert search() == [card("A-1")]
    assert len(a.run_calls) == 1
    assert len(b.run_calls) == 0  # call_count，不用 side_effect


def test_empty_first_provider_falls_through_and_empty_chain_is_empty_list(chain):
    a, b = Fake("a"), Fake("b", cards=[card("B-1")])
    chain([a, b])
    assert search() == [card("B-1")]
    assert len(a.run_calls) == 1 and len(b.run_calls) == 1
    chain([], order=[])
    assert search() == []


@pytest.mark.parametrize(
    "exc",
    [SourceBlocked("b"), SourceUnreachable("u"), ValueError("v"), KeyError("k"), RuntimeError("r")],
    ids=lambda e: type(e).__name__,
)
def test_provider_failure_of_any_kind_falls_through_to_next(chain, exc):
    a, b = Fake("a", raises=exc), Fake("b", cards=[card("B-1")])
    chain([a, b])
    assert search() == [card("B-1")]
    assert len(a.run_calls) == 1 and len(b.run_calls) == 1


def test_all_providers_failing_gives_empty_list_not_exception(chain):
    chain([Fake("a", raises=SourceBlocked("x")), Fake("b", raises=SourceUnreachable("y"))])
    assert search() == []


def test_base_exception_is_not_swallowed(chain):
    class Fatal(BaseException):
        pass

    chain([Fake("a", raises=Fatal())])
    with pytest.raises(Fatal):
        search()


@pytest.mark.parametrize(
    "mode,kind", [("partial", Kind.PARTIAL), ("prefix", Kind.CODE), ("actress", Kind.KEYWORD)]
)
def test_mode_maps_to_kind_and_forwards_window_and_callbacks(chain, mode, kind):
    a = Fake("a", cards=[card("A")])
    chain([a])
    status, result = MagicMock(), MagicMock()
    w = Window(30, 7)
    search(mode, "needle", w, status_callback=status, result_callback=result, discovery_only=False)
    k, target, got_w, got_status, got_result, got_disc = a.run_calls[0]
    assert (k, target, got_w, got_status, got_disc) == (kind, "needle", w, status, False)
    assert got_result is not None and got_result is not result  # 包過 tracker，不是原物件


def test_discovery_only_asks_only_discovery_capable_providers(chain):
    plain, disc = Fake("plain"), Fake("disc", cards=[card("D")], discovery=True)
    chain([plain, disc])
    assert search(discovery_only=True) == [card("D")]
    assert len(plain.run_calls) == 0
    assert disc.run_calls[0][5] is True
    assert search(discovery_only=False) == [card("D")]
    assert len(plain.run_calls) == 1  # 非 discovery 時 plain 照常被問


def test_capability_filter_skips_provider_lacking_kind(chain):
    only_kw = Fake("kw", caps=frozenset({Kind.KEYWORD}), cards=[card("K")])
    both = Fake("both", cards=[card("B")])
    chain([only_kw, both])
    assert search("partial") == [card("B")]
    assert len(only_kw.run_calls) == 0


# ---------------------------------------------------------------- 順序與開關
def test_dmm_first_order_asks_dmm_first(chain):
    log = []
    jb, dmm = Fake("javbus"), Fake("dmm")
    jb.order_log = dmm.order_log = log
    chain([jb, dmm], order=["dmm", "javbus"], extra_registered=["aaa-extra"])
    search()
    assert log == ["dmm", "javbus"]  # 不在 order 的已註冊者（aaa-extra）不被問


def test_javbus_asked_when_its_switch_is_off(chain):
    jb = Fake("javbus", cards=[card("J")])
    chain([jb], enabled=[])
    assert search() == [card("J")]  # CD-65-4：JavBus 不看開關


def test_dmm_skipped_when_its_switch_is_off(chain):
    jb, dmm = Fake("javbus"), Fake("dmm", cards=[card("D")])
    chain([jb, dmm], enabled=["javbus"])
    assert search() == []
    assert len(dmm.run_calls) == 0


def test_each_search_builds_fresh_providers(chain):
    a = Fake("a")
    counts = chain([a])
    search()
    search()
    assert counts["a"] == 2


# ---------------------------------------------------------------- seed 閘
def test_fallback_provider_gets_callback_until_seed_sent(chain):
    a, b = Fake("a"), Fake("b", cards=[card("B")])  # a 拿到 callback 卻從未 seed
    chain([a, b])
    user = MagicMock()
    assert search(result_callback=user) == [card("B")]
    assert a.received_callbacks[0] is not None
    assert b.received_callbacks[0] is not None  # 「給過就算」的假實作在這裡會紅
    b.received_callbacks[0](-1, ["B"])
    user.assert_called_once_with(-1, ["B"])  # 轉送到呼叫端


def test_non_streaming_fallback_gets_none(chain):
    """第一家查無、後備的結果會被重排（fallback_streaming=False）→ 後備拿 None，使用者最後看到的順序與今天相同"""
    a, b = Fake("a"), Fake("b", cards=[card("B")], fallback_streaming=False)
    chain([a, b])
    assert search(result_callback=MagicMock()) == [card("B")]
    assert a.received_callbacks[0] is not None
    assert b.received_callbacks == [None]


def test_first_dispatched_gets_callback_even_if_not_streaming_fallback(chain):
    a = Fake("a", cards=[card("A")], fallback_streaming=False)
    chain([a])
    assert search(result_callback=MagicMock()) == [card("A")]
    assert a.received_callbacks[0] is not None


def test_real_providers_declare_fallback_streaming():
    from core.search_providers.dmm import DMMProvider
    from core.search_providers.javbus import JavBusProvider

    assert DMMProvider.fallback_streaming is True  # 串流順序＝最終順序
    assert JavBusProvider.fallback_streaming is False  # 補完詳情後依日期重排


@pytest.mark.parametrize("a_raises", [None, RuntimeError("late")], ids=["seed-then-empty", "seed-then-raise"])
def test_seed_sent_blocks_later_providers(chain, a_raises):
    a = Fake("a", seed=["N-1"], raises=a_raises)
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    user = MagicMock()
    assert search(result_callback=user) == [card("B")]
    assert b.received_callbacks == [None]
    assert user.call_args_list == [((-1, ["N-1"]),)]  # 呼叫端只收到一次 seed


def test_no_callback_from_caller_means_none_all_the_way(chain):
    a, b = Fake("a"), Fake("b", cards=[card("B")])
    chain([a, b])
    search(result_callback=None)
    assert a.received_callbacks == [None] and b.received_callbacks == [None]


def test_unrelated_entity_page_sends_no_seed_and_falls_through(chain):
    a = EntityFake("a", belongs=False)  # 站方回全站最新：頁面與實體無關
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    user = MagicMock()
    assert search("actress", "someone", result_callback=user) == [card("B")]
    assert user.call_count == 0  # 沒有 seed、沒有 result-item
    assert len(a.run_calls) == 0  # 該家不再問 KEYWORD
    assert len(b.run_calls) == 1


def test_guard_all_blocked_is_unreachable_then_next_provider_asked(chain):
    a = EntityFake("a", enrich_raises=SourceBlocked("cf"))
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    user = MagicMock()
    assert search("actress", "someone", result_callback=user) == [card("B")]
    assert user.call_count == 0
    assert len(a.run_calls) == 0 and len(b.run_calls) == 1


def test_entity_hit_streams_seed_then_items_and_skips_keyword(chain):
    a = EntityFake("a", n_items=3)
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    user = MagicMock()
    out = search("actress", "someone", result_callback=user)
    assert [c["number"] for c in out] == ["E-000", "E-001", "E-002"]
    slots = [c.args[0] for c in user.call_args_list]
    assert slots.count(-1) == 1 and slots[0] == -1
    assert len(a.run_calls) == 0 and len(b.run_calls) == 0


@pytest.mark.parametrize("kw", [{"ref": None}, {"resolve_raises": RuntimeError("boom")}], ids=["no-ref", "resolve-raises"])
def test_entity_ladder_empty_then_keyword_else_next_provider(chain, kw):
    a = EntityFake("a", cards=[card("A-kw")], **kw)
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    out = search("actress", "someone")
    if "resolve_raises" in kw:
        assert out == [card("B")] and len(a.run_calls) == 0  # resolve 拋例外 ⇒ 該家不再問 KEYWORD
    else:
        assert out == [card("A-kw")] and len(a.run_calls) == 1  # 梯子全空 ⇒ 問 KEYWORD


def test_entity_ladder_only_asks_declared_kinds_and_not_for_other_modes(chain):
    a = EntityFake("a", ref=None, cards=[card("A")])
    chain([a])
    search("actress", "x")
    assert [k for k, _ in a.resolve_calls] == [Kind.ACTOR]
    search("partial", "x")
    assert len(a.resolve_calls) == 1


_BEHAVIOURS = {
    "seed-empty": dict(seed=["N"]),
    "seed-raise": dict(seed=["N"], raises=RuntimeError("x")),
    "noseed-empty": dict(),
}


@pytest.mark.parametrize("combo", list(itertools.product(_BEHAVIOURS, repeat=3)), ids="/".join)
def test_relay_never_emits_second_seed(chain, combo):
    ps = [Fake(f"p{i}", **_BEHAVIOURS[name]) for i, name in enumerate(combo)]
    ps.append(Fake("last", cards=[card("L")], seed=["N"]))
    chain(ps)
    user = MagicMock()
    search(result_callback=user)
    assert [c.args[0] for c in user.call_args_list].count(-1) <= 1


# ---------------------------------------------------------------- relay 不自送 status
def test_relay_emits_no_status_events_of_its_own(chain):
    status = MagicMock()
    a = Fake("a")
    b = Fake("b", cards=[card("B")])
    chain([a, b])
    search(status_callback=status)
    assert status.call_count == 0
    assert a.run_calls[0][3] is status  # 原物件透傳，不包裝
    chain([], order=[])
    search(status_callback=status)
    assert status.call_count == 0


def test_relay_does_not_add_source_or_reorder(chain):
    cards = [card("Z"), card("A")]
    chain([Fake("a", cards=cards)])
    out = search()
    assert [c["number"] for c in out] == ["Z", "A"]
    assert all("_source" not in c for c in out)


# ---------------------------------------------------------------- _resolve_refs