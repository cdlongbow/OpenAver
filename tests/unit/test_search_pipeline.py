"""175a-T3：共用介面骨架（fetch_window / verify_page / run_window）。

全部用測試檔內的合成 provider，不 import 任何真爬蟲、不連網（BE-TEST-43）。
「不准呼叫」一律量 call_count（BE-TEST-46：逐部 except Exception 會吞 AssertionError）。
"""

import concurrent.futures as cf
import threading
import time
from unittest.mock import MagicMock

import pytest

from core.scraper import MAX_WORKERS, REQUEST_DELAY
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers import pipeline
from core.search_providers.pipeline import BREAKER_THRESHOLD, fetch_window, run_window, verify_page
from core.search_providers.types import Enriched, EntityRef, Kind, Outcome, Page, Window, WorkItem

REF = EntityRef(Kind.ACTOR, "a1", "someone")
FAILURES = [SourceBlocked("b"), SourceUnreachable("u"), ValueError("v"), KeyError("k")]


# ---------------------------------------------------------------- helpers
def make_items(n, start=1):
    return [
        WorkItem(f"AAA-{i:03d}", f"title {i}", f"http://x/{i}.jpg", "2026-01-01", None, "fake", ref=i)
        for i in range(start, start + n)
    ]


def full_card(item):
    return {"number": item.number, "title": item.title, "actors": ["actor-x"], "full": True}


class FakeProvider:
    """script: number -> 'T'（belongs True）/ 'F'（False）/ 'N'（None）/ 'OK'（belongs None 的好卡）/
    'EMPTY'（card=None）/ Exception 實例（raise）。沒列的號碼＝'OK'。"""

    id = "fake"
    capabilities = frozenset({Kind.ACTOR})
    supports_discovery = False

    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []
        self._lock = threading.Lock()

    def enrich(self, item, ref):
        with self._lock:
            self.calls.append(item.number)
        act = self.script.get(item.number, "OK")
        if isinstance(act, Exception):
            raise act
        if act == "EMPTY":
            return Enriched(None, True)
        belongs = {"T": True, "F": False}.get(act)
        return Enriched(full_card(item), belongs)


class SyncExecutor:
    """submit 當下就跑完的 executor：完成順序＝提交順序（決定性）。"""

    def __init__(self, max_workers=None, **_):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        fut = cf.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 — 與真 executor 相同：例外存進 future
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    rec = []
    monkeypatch.setattr(time, "sleep", lambda s: rec.append(s))
    return rec


@pytest.fixture
def sync_executor(monkeypatch):
    monkeypatch.setattr(cf, "ThreadPoolExecutor", SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))


def is_degraded(card, item):
    return card["actors"] == [] and card["number"] == item.number and card["title"] == item.title and "full" not in card


# ---------------------------------------------------------------- fetch_window
def make_fetch(page_size, total_pages, requested, clamp_to=None):
    def fetch_page(page):
        requested.append(page)
        p = min(page, clamp_to) if clamp_to else page
        if p > total_pages:
            return Page([], True, None)  # 剛好整除：provider 仍說 has_next
        base = (p - 1) * page_size
        items = [WorkItem(f"N-{base + i}", "t", "", "", None, "fake") for i in range(page_size)]
        return Page(items, p < total_pages or True, None)

    return fetch_page


@pytest.mark.parametrize(
    "page_size, offset, limit, pages",
    [
        (30, 0, 20, [1]),
        (30, 20, 20, [1, 2]),
        (30, 30, 20, [2]),
        (30, 40, 20, [2]),
        (30, 60, 20, [3]),
        (50, 20, 20, [1]),
        (50, 40, 20, [1, 2]),
        (50, 50, 20, [2]),
    ],
)
def test_fetch_window_page_math(page_size, offset, limit, pages):
    requested = []
    page = fetch_window(page_size, make_fetch(page_size, 50, requested), Window(offset, limit))
    assert requested == pages
    assert [i.number for i in page.items] == [f"N-{n}" for n in range(offset, offset + limit)]
    assert page.has_next is True


def test_fetch_window_page_cap_matches_todays_javbus_bound():
    # 每頁只回 10 筆（< page_size）、has_next 一直 True：上界＝((limit+skip)//page_size)+2 頁
    requested = []

    def fetch_page(page):
        requested.append(page)
        return Page([WorkItem(f"P{page}-{i}", "t", "", "", None, "f") for i in range(10)], True, None)

    fetch_window(30, fetch_page, Window(0, 100))
    assert requested == [1, 2, 3, 4, 5]
    requested.clear()
    fetch_window(30, fetch_page, Window(20, 100))  # skip=20：(120//30)+2 = 6 頁
    assert requested == [1, 2, 3, 4, 5, 6]


def test_fetch_window_empty_page_is_end_even_when_has_next_true_and_total_none():
    requested = []
    fetch = make_fetch(20, 2, requested)  # 兩頁各 20 筆；第 3 頁空但前一頁仍說 has_next
    first = fetch_window(20, fetch, Window(20, 20))
    assert [i.number for i in first.items] == [f"N-{n}" for n in range(20, 40)]
    assert first.has_next is True and first.total is None
    requested.clear()
    last = fetch_window(20, fetch, Window(40, 20))
    assert last.items == [] and last.has_next is False
    assert requested == [3]
    requested.clear()
    big = fetch_window(20, fetch, Window(0, 60))  # 取到空頁就停，不報錯
    assert len(big.items) == 40 and big.has_next is False
    assert requested == [1, 2, 3]


def test_fetch_window_stops_when_provider_says_no_next():
    requested = []

    def fetch_page(page):
        requested.append(page)
        return Page([WorkItem(f"X{page}-{i}", "t", "", "", None, "f") for i in range(30)], False, 30)

    page = fetch_window(30, fetch_page, Window(0, 100))
    assert requested == [1]
    assert len(page.items) == 30 and page.has_next is False and page.total == 30


def test_fetch_window_never_requests_past_max_page():
    # 模擬站方：超過第 99 頁時把頁碼夾回 99（回同一頁內容）
    requested = []
    fetch = make_fetch(50, 99, requested, clamp_to=99)
    page = fetch_window(50, fetch, Window(4940, 20), max_page=99)
    assert requested == [99]
    assert len(page.items) == 10 and page.has_next is False
    requested.clear()
    page = fetch_window(50, fetch, Window(4950, 20), max_page=99)
    assert requested == [] and page.items == [] and page.has_next is False


# ---------------------------------------------------------------- verify_page / guard
def run_guarded(script, n=6, cb=None, **kw):
    prov = FakeProvider(script)
    items = make_items(n)
    res = run_window(prov, items, REF, result_callback=cb, guard=True, **kw)
    return prov, items, res


def test_guard_rejects_page_with_no_member(sync_executor):
    cb = MagicMock()
    script = {f"AAA-{i:03d}": "F" for i in range(1, 7)}
    prov, _, res = run_guarded(script, cb=cb)
    assert res.outcome is Outcome.NOT_ANSWERABLE
    assert res.cards == [] and res.seeded is False
    assert cb.call_count == 0
    assert len(prov.calls) == 3  # 只抓守衛那 3 部


@pytest.mark.parametrize("exc", FAILURES, ids=lambda e: type(e).__name__)
def test_guard_all_failed_is_unreachable_not_empty(sync_executor, exc):
    cb = MagicMock()
    script = {f"AAA-{i:03d}": exc for i in (1, 2, 3)}
    prov, _, res = run_guarded(script, cb=cb)
    assert res.outcome is Outcome.UNREACHABLE
    assert res.cards == [] and res.seeded is False
    assert cb.call_count == 0
    assert len(prov.calls) == 3


def test_guard_false_plus_exception_without_true_is_unreachable(sync_executor):
    script = {"AAA-001": "F", "AAA-002": SourceBlocked("b"), "AAA-003": "F"}
    _, _, res = run_guarded(script)
    assert res.outcome is Outcome.UNREACHABLE and res.seeded is False


def test_guard_unknown_membership_is_not_answerable(sync_executor):
    script = {"AAA-001": "N", "AAA-002": "F", "AAA-003": "N"}
    _, _, res = run_guarded(script)
    assert res.outcome is Outcome.NOT_ANSWERABLE and res.seeded is False


def test_guard_one_of_three_passes_and_reuses_guard_cards(sync_executor):
    cb = MagicMock()
    script = {"AAA-001": "F", "AAA-002": "T", "AAA-003": "F"}
    prov, items, res = run_guarded(script, n=6, cb=cb)
    assert res.outcome is Outcome.ANSWERED and res.seeded is True
    assert sorted(prov.calls) == sorted(i.number for i in items)  # 每部恰好抓一次（守衛那 3 部不重抓）
    assert len(res.cards) == 6 and all(c.get("full") for c in res.cards)
    assert [c["number"] for c in res.cards] == [i.number for i in items]


def test_guard_pass_with_failed_guard_item_degrades_only_it(sync_executor):
    script = {"AAA-001": ValueError("v"), "AAA-002": "T", "AAA-003": "OK"}
    prov, items, res = run_guarded(script, n=4)
    assert res.outcome is Outcome.ANSWERED
    assert is_degraded(res.cards[0], items[0])
    assert len(prov.calls) == 4  # 不重試


def test_guard_with_fewer_than_three_items_uses_all(sync_executor):
    prov, _, res = run_guarded({"AAA-002": "T"}, n=2)
    assert res.outcome is Outcome.ANSWERED and len(res.cards) == 2
    assert len(prov.calls) == 2


def test_guard_failure_sends_no_seed_and_no_result_item(sync_executor):
    for script in (
        {f"AAA-{i:03d}": "F" for i in (1, 2, 3)},
        {f"AAA-{i:03d}": SourceBlocked("b") for i in (1, 2, 3)},
    ):
        cb = MagicMock()
        _, _, res = run_guarded(script, cb=cb)
        assert cb.call_count == 0
        assert res.seeded is False and res.cards == []


def test_guard_requires_ref():
    with pytest.raises(ValueError):
        run_window(FakeProvider(), make_items(3), None, guard=True)


def test_verify_page_returns_cards_by_slot(sync_executor):
    prov = FakeProvider({"AAA-001": "F", "AAA-002": "T", "AAA-003": ValueError("v")})
    verdict = verify_page(prov, make_items(5), REF, delay=0)
    assert verdict.passed is True and verdict.outcome is None
    assert sorted(verdict.cards) == [0, 1, 2]
    assert verdict.cards[0]["number"] == "AAA-001" and verdict.cards[2] is None
    assert len(prov.calls) == 3


# ---------------------------------------------------------------- seed / outcome / on_fail
def test_seed_sent_once_first_with_all_numbers_then_slot_results(sync_executor):
    events = []
    prov = FakeProvider()
    items = make_items(5)
    res = run_window(prov, items, result_callback=lambda slot, payload: events.append((slot, payload)))
    assert events[0] == (-1, [i.number for i in items])
    assert [e[0] for e in events].count(-1) == 1
    assert sorted(e[0] for e in events[1:]) == [0, 1, 2, 3, 4]
    assert all(e[1]["number"] == items[e[0]].number for e in events[1:])
    assert res.outcome is Outcome.ANSWERED and res.seeded is True
    assert [c["number"] for c in res.cards] == [i.number for i in items]


def test_cards_ordered_by_slot_even_if_completion_out_of_order():
    order = _run_gated(
        {1: "OK", 2: "OK", 3: "OK", 4: "OK"}, release_order=[2, 1, 4, 3], n=4
    )
    assert [c["number"] for c in order.cards] == [f"AAA-{i:03d}" for i in range(1, 5)]


def test_guard_seed_comes_after_pass_and_only_once(sync_executor):
    events = []
    script = {"AAA-001": "T"}
    run_guarded(script, n=5, cb=lambda s, p: events.append(s))
    assert events[0] == -1 and events.count(-1) == 1
    assert sorted(events[1:]) == [0, 1, 2, 3, 4]


def test_empty_window_is_not_answerable_and_not_seeded():
    cb = MagicMock()
    res = run_window(FakeProvider(), [], result_callback=cb)
    assert res.outcome is Outcome.NOT_ANSWERABLE and res.cards == [] and res.seeded is False
    assert cb.call_count == 0


def test_on_fail_drop_omits_failed_items_but_still_seeds(sync_executor):
    events = []
    script = {"AAA-002": SourceBlocked("b"), "AAA-004": ValueError("v")}
    prov = FakeProvider(script)
    items = make_items(5)
    res = run_window(prov, items, on_fail="drop", result_callback=lambda s, p: events.append((s, p)))
    assert res.seeded is True and res.outcome is Outcome.ANSWERED
    assert [c["number"] for c in res.cards] == ["AAA-001", "AAA-003", "AAA-005"]
    assert sorted(s for s, _ in events if s >= 0) == [0, 2, 4]
    assert events[0] == (-1, [i.number for i in items])


def test_on_fail_drop_all_failed_is_not_answerable_but_seeded(sync_executor):
    script = {f"AAA-{i:03d}": ValueError("v") for i in range(1, 4)}
    cb = MagicMock()
    res = run_window(FakeProvider(script), make_items(3), on_fail="drop", result_callback=cb)
    assert res.outcome is Outcome.NOT_ANSWERABLE and res.cards == [] and res.seeded is True
    assert cb.call_args_list[0].args[0] == -1


def test_seeded_reflects_whether_seed_was_actually_sent(sync_executor):
    script = {f"AAA-{i:03d}": ValueError("v") for i in range(1, 4)}
    for kw in ({}, {"on_fail": "drop"}):
        res = run_window(FakeProvider(script), make_items(3), **kw)  # 沒有 result_callback
        assert res.seeded is False
    assert run_window(FakeProvider(), make_items(2)).seeded is False
    assert run_window(FakeProvider(), make_items(2), result_callback=MagicMock()).seeded is True


def test_invalid_on_fail_rejected():
    with pytest.raises(ValueError):
        run_window(FakeProvider(), make_items(2), on_fail="nope")


# ---------------------------------------------------------------- 單部失敗
@pytest.mark.parametrize("exc", FAILURES, ids=lambda e: type(e).__name__)
def test_single_detail_failure_degrades_only_that_card(sync_executor, exc):
    prov = FakeProvider({"AAA-003": exc})
    items = make_items(6)
    res = run_window(prov, items)
    assert res.outcome is Outcome.ANSWERED and len(res.cards) == 6
    assert is_degraded(res.cards[2], items[2])
    assert res.cards[2]["cover"] == items[2].cover_url and res.cards[2]["date"] == items[2].date
    for k in (0, 1, 3, 4, 5):
        assert res.cards[k].get("full") is True
    assert sorted(prov.calls) == sorted(i.number for i in items)  # 恰 N 次，不重試


def test_empty_enriched_card_counts_as_failure(sync_executor):
    items = make_items(3)
    res = run_window(FakeProvider({"AAA-002": "EMPTY"}), items)
    assert is_degraded(res.cards[1], items[1])


def test_base_exception_is_not_swallowed(sync_executor):
    class Boom(BaseException):
        pass

    class Prov(FakeProvider):
        def enrich(self, item, ref):
            raise Boom

    with pytest.raises(Boom):
        run_window(Prov(), make_items(2))


# ---------------------------------------------------------------- 斷路器
def remaining_numbers(n, first=4):
    return [f"AAA-{i:03d}" for i in range(first, n + 1)]


def test_breaker_stops_new_requests_after_consecutive_blocks(sync_executor):
    n = 12
    script = {f"AAA-{i:03d}": "T" for i in (1, 2, 3)}
    script.update({f"AAA-{i:03d}": SourceBlocked("b") for i in range(4, n + 1)})  # 補卡階段一路被擋
    prov = FakeProvider(script)
    items = make_items(n)
    res = run_window(prov, items, REF, guard=True)
    assert len(res.cards) == n  # 卡數仍滿
    rest = remaining_numbers(n)
    requested = [c for c in prov.calls if c in rest]
    never = [c for c in rest if c not in prov.calls]
    assert len(never) >= 1
    # 斷路後新發起的呼叫數為 0：補卡階段實際請求 ≤ 門檻 + 已在途（MAX_WORKERS-1）
    assert len(requested) <= BREAKER_THRESHOLD + MAX_WORKERS - 1
    for c in res.cards[3:]:
        assert is_degraded(c, items[int(c["number"][-3:]) - 1])


def test_breaker_counter_reset_by_success_or_other_failure(sync_executor):
    script = {f"AAA-{i:03d}": "T" for i in (1, 2, 3)}
    script.update(
        {
            "AAA-004": SourceBlocked("b"),
            "AAA-005": SourceBlocked("b"),
            "AAA-006": ValueError("v"),
            "AAA-007": SourceBlocked("b"),
            "AAA-008": SourceBlocked("b"),
            "AAA-009": "OK",
            "AAA-010": SourceBlocked("b"),
            "AAA-011": SourceBlocked("b"),
        }
    )
    prov = FakeProvider(script)
    run_window(prov, make_items(12), REF, guard=True)
    assert len(prov.calls) == 12  # 從未連續 3 次，一部都沒被省


def test_guard_stage_failures_do_not_count_toward_breaker(sync_executor):
    script = {"AAA-001": "T", "AAA-002": SourceBlocked("b"), "AAA-003": SourceBlocked("b"), "AAA-004": SourceBlocked("b")}
    prov = FakeProvider(script)
    run_window(prov, make_items(8), REF, guard=True)
    assert len(prov.calls) == 8


def test_breaker_can_be_disabled(sync_executor):
    script = {f"AAA-{i:03d}": SourceBlocked("b") for i in range(1, 11)}
    prov = FakeProvider(script)
    res = run_window(prov, make_items(10), breaker=False)
    assert len(prov.calls) == 10 and len(res.cards) == 10


def test_breaker_drop_policy_omits_unrequested(sync_executor):
    script = {f"AAA-{i:03d}": SourceBlocked("b") for i in range(1, 13)}
    prov = FakeProvider(script)
    res = run_window(prov, make_items(12), on_fail="drop")
    assert res.cards == [] and res.seeded is False and res.outcome is Outcome.NOT_ANSWERABLE
    assert len(prov.calls) < 12


class GatedProvider(FakeProvider):
    """每部 enrich 卡在自己的 gate 上，測試用 release 順序決定真實完成順序（真執行緒）。"""

    def __init__(self, script, n):
        super().__init__(script)
        self.started = {i: threading.Event() for i in range(1, n + 1)}
        self.gates = {i: threading.Event() for i in range(1, n + 1)}

    def enrich(self, item, ref):
        k = int(item.number[-3:])
        self.started[k].set()
        assert self.gates[k].wait(10), f"gate {k} never released"
        return super().enrich(item, ref)


def _run_gated(script, release_order, n, wait_started=None):
    """script: {1-based 序號: 行為}；release_order：依序放行；wait_started[k]＝放行 k 前先等哪一部已開始。"""
    named = {f"AAA-{k:03d}": v for k, v in script.items()}
    prov = GatedProvider(named, n)
    wait_started = wait_started or {}

    def driver():
        for k in release_order:
            if k in wait_started:
                assert prov.started[wait_started[k]].wait(10)
            prov.gates[k].set()
        for g in prov.gates.values():
            g.set()

    t = threading.Thread(target=driver)
    t.start()
    res = run_window(prov, make_items(n))
    t.join(10)
    res.prov = prov
    return res


def test_breaker_counts_in_true_completion_order():
    # 完成順序：被擋、被擋、成功、被擋 ⇒ 連續數 2→0→1，不得斷路，8 部全都要被呼叫
    blocked = SourceBlocked("b")
    res = _run_gated(
        {1: blocked, 2: blocked, 4: blocked},
        release_order=[1, 2, 3, 4],
        n=8,
        wait_started={2: 3, 3: 4, 4: 5},  # 放行 2 前先等 3 補位開始（＝1 已完成），以此類推
    )
    assert len(res.prov.calls) == 8
    assert sum(1 for c in res.cards if "full" in c) == 5


# ---------------------------------------------------------------- 並行與間隔
def test_enrichment_respects_concurrency_and_delay_limits(monkeypatch, sleeps):
    created = []
    real = cf.ThreadPoolExecutor

    class Spy(real):
        def __init__(self, *a, **kw):
            created.append(kw.get("max_workers", a[0] if a else None))
            super().__init__(*a, **kw)

    monkeypatch.setattr(cf, "ThreadPoolExecutor", Spy)
    prov = FakeProvider()
    items = make_items(8)
    res = run_window(prov, items)
    assert len(res.cards) == 8
    assert created and all(m is not None and m <= MAX_WORKERS for m in created)
    assert len(sleeps) >= len(items)
    assert all(s >= REQUEST_DELAY for s in sleeps)


def test_delay_zero_and_custom_delay_are_honoured(sync_executor, sleeps):
    run_window(FakeProvider(), make_items(4), delay=0)
    assert all(s == 0 for s in sleeps)
    sleeps.clear()
    run_window(FakeProvider(), make_items(4), delay=0.7)
    assert len(sleeps) >= 4 and all(s >= 0.7 for s in sleeps)


def test_pipeline_has_no_own_threads_or_other_pools():
    import inspect

    src = inspect.getsource(pipeline)
    assert "threading.Thread" not in src and "ProcessPoolExecutor" not in src
    assert ".map(" not in src


# ---------------------------------------------------------------- 175a-T4：on_item_done 掛鉤
def run_hooked(script, n=6, guard=False, ref=None, **kw):
    prov = FakeProvider(script)
    events = []
    hook = lambda slot, ok: events.append(("done", slot, ok))  # noqa: E731
    cb = lambda slot, card: events.append(("item", slot))  # noqa: E731
    res = run_window(prov, make_items(n), ref, result_callback=cb, on_item_done=hook, guard=guard, **kw)
    return events, res


def test_item_done_counts_failed_detail(sync_executor):
    """前綴搜尋某部詳情失敗，進度仍要數到 N/N：每部各呼叫一次、失敗那部 ok=False。"""
    events, _ = run_hooked({"AAA-002": ValueError("boom"), "AAA-004": "EMPTY"}, n=5, on_fail="drop")
    done = [e for e in events if e[0] == "done"]
    assert sorted(s for _, s, _ in done) == [0, 1, 2, 3, 4]
    assert {s: ok for _, s, ok in done} == {0: True, 1: False, 2: True, 3: False, 4: True}


def test_item_done_comes_before_that_items_result_callback(sync_executor):
    events, _ = run_hooked({"AAA-002": ValueError("boom")}, n=3, on_fail="degrade")
    for slot in range(3):
        assert events.index(("done", slot, slot != 1)) < events.index(("item", slot))


def test_item_done_covers_items_never_started_after_breaker(sync_executor):
    script = {f"AAA-{i:03d}": SourceBlocked("b") for i in range(1, 4)}
    events, _ = run_hooked(script, n=6, on_fail="drop")
    done = [e for e in events if e[0] == "done"]
    assert sorted(s for _, s, _ in done) == list(range(6))  # 每部恰一次，含從未發起的
    assert {s: ok for _, s, ok in done if s in (0, 1, 2, 4, 5)} == {0: False, 1: False, 2: False, 4: False, 5: False}


def test_item_done_not_called_when_guard_rejects(sync_executor):
    events, _ = run_hooked({f"AAA-{i:03d}": "F" for i in range(1, 7)}, n=6, guard=True, ref=REF)
    assert events == []


def test_item_done_with_guard_pass_covers_every_item_in_order(sync_executor):
    events, _ = run_hooked({"AAA-001": "T"}, n=5, guard=True, ref=REF)
    done = [s for k, s, *_ in events if k == "done"]
    assert sorted(done) == [0, 1, 2, 3, 4]
    for slot in range(5):
        assert events.index(("done", slot, True)) < events.index(("item", slot))


def test_item_done_empty_window_and_none_hook_do_nothing(sync_executor):
    events = []
    run_window(FakeProvider(), [], on_item_done=lambda s, ok: events.append(s))
    assert events == []
    res = run_window(FakeProvider(), make_items(3), on_item_done=None)
    assert len(res.cards) == 3
