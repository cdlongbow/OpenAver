"""175d-T3：WorkItem.origin ＋ pipeline.merge_windows（CD-175d-4、CD-175d-5）。

全部用測試檔內的合成 provider（回我們自己的 WorkItem／Page），不 import 任何真爬蟲、不連網（BE-TEST-43）。
「不准呼叫」一律量呼叫記錄（BE-TEST-46）；stub 記錄 (ref.id, offset, limit)（BE-TEST-23）。
I-M3 的期望由 oracle() 獨立算出（全部片依 (日期新→舊, ref 序, ref 內序) 排序後依每頁實際消耗數切段、段內去重），
不呼叫 merge_windows 自己產生。
"""

import concurrent.futures as cf
import math
import random
import threading
import time
from unittest.mock import MagicMock

import pytest

from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.search_providers.pipeline import merge_windows, run_window
from core.search_providers.types import Enriched, EntityRef, Kind, Outcome, Page, WorkItem


# ---------------------------------------------------------------- helpers
def refs_for(n):
    return [EntityRef(Kind.ACTOR, f"r{k + 1}", f"name{k + 1}") for k in range(n)]


def wi(number, date):
    return WorkItem(number, f"title {number}", f"http://x/{number}.jpg", date, None, "fake", ref=number)


class ListProvider:
    """list_entity 依 lists[ref.id] 切片回 Page。optimistic＝JavBus 式（塊滿就 has_next=True，下一塊才回空）；
    否則精確（真的沒有更多才 False）。fail: ref.id -> (第 n 次呼叫, 例外)。owners: 番號大寫 -> 擁有者 ref.id，
    enrich 的 belongs 依「收到的 ref」算（不恆真）。"""

    id = "fake"
    capabilities = frozenset({Kind.ACTOR})
    supports_discovery = False
    fallback_streaming = False

    def __init__(self, lists, *, optimistic=False, chunk=None, owners=None, fail=None):
        self.lists = lists
        self.optimistic = optimistic
        self.owners = owners
        self.fail = fail or {}
        self.raised = False
        self.calls = []
        self.enrich_calls = []
        self._lock = threading.Lock()
        if chunk is not None:
            self.list_chunk = chunk  # 不設＝merge_windows 用預設 30

    def list_entity(self, ref, w):
        self.calls.append((ref.id, w.offset, w.limit))
        nth = sum(1 for c in self.calls if c[0] == ref.id)
        if ref.id in self.fail and self.fail[ref.id][0] == nth:
            self.raised = True
            raise self.fail[ref.id][1]
        full = self.lists[ref.id]
        got = full[w.offset : w.offset + w.limit]
        has_next = len(got) >= w.limit if self.optimistic else w.offset + w.limit < len(full)
        return Page(list(got), has_next)

    def enrich(self, item, ref):
        with self._lock:
            self.enrich_calls.append((item.number, ref.id if ref is not None else None))
        belongs = None
        if self.owners is not None and ref is not None:
            belongs = self.owners.get(item.number.upper()) == ref.id
        return Enriched({"number": item.number, "title": item.title, "actors": ["x"], "full": True}, belongs)

    def calls_for(self, ref_id):
        return [c for c in self.calls if c[0] == ref_id]


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


def make_lists(sizes, seed, shared=6):
    """每個 ref 的清單自己已「日期新→舊、缺日期殿後」排好（merge_windows 只歸併、不重排）。
    日期從 45 天內抽 ⇒ 大量同日；部分 ref 尾巴缺日期；日期混用 '/' 與 '-'；
    ref2 起有 shared 部換成 ref1 某部的（番號隨機大小寫、同日期）⇒ 跨 ref 同號。"""
    rng = random.Random(seed)
    lists = []
    for r, size in enumerate(sizes):
        dated = size - 3 if (size > 8 and r % 2 == 0) else size
        lo = 36 if r == 1 else 1  # ref2 的片都較新 ⇒ 比別人早到底
        days = sorted((rng.randrange(lo, 46) for _ in range(dated)), reverse=True)
        items = []
        for k, day in enumerate(days):
            sep = "/" if rng.random() < 0.3 else "-"
            items.append(wi(f"R{r + 1}-{k:03d}", f"2026{sep}{(day - 1) // 30 + 1:02d}{sep}{(day - 1) % 30 + 1:02d}"))
        items += [wi(f"R{r + 1}-{k:03d}", "") for k in range(dated, size)]
        lists.append(items)
    for r in range(1, len(sizes)):
        if not lists[0] or not shared:
            continue
        for k in rng.sample(range(len(lists[r])), min(shared, len(lists[r]))):
            src = rng.choice(lists[0][:30] if r == 1 else lists[0])  # 同號同日 ⇒ 歸併後緊鄰，會落在同頁（被丟）或頁界（跨頁各出現）
            lists[r][k] = wi(src.number.lower() if rng.random() < 0.5 else src.number, src.date)
        lists[r].sort(key=lambda it: it.date.replace("/", "-"), reverse=True)  # 維持「日期新→舊、缺日期殿後」
    return lists


def by_id(lists):
    return {f"r{k + 1}": items for k, items in enumerate(lists)}


def walk(provider, refs, limit, max_pages=300):
    """把 new_positions 餵回下一頁直到 exhausted；回 [(該頁起點 positions, MergeResult)]。有頁數上限。"""
    positions = [0] * len(refs)
    steps = []
    for _ in range(max_pages):
        res = merge_windows(provider, refs, positions, limit)
        steps.append((list(positions), res))
        positions = list(res.new_positions)
        if res.exhausted:
            return steps
    pytest.fail(f"walk did not terminate within {max_pages} pages")
    return steps


def oracle(lists, limit):
    """獨立 oracle：全部片依 (日期新→舊, ref 序, ref 內序) 排序（缺日期殿後），依每頁實際消耗數切段、段內各自去重。
    回 (pages: [[(number, ref_idx)]], cums: 每頁結束時各 ref 的累計消耗數)。"""
    entries = [(it.date.replace("/", "-"), r, k, it.number) for r, lst in enumerate(lists) for k, it in enumerate(lst)]
    entries.sort(key=lambda e: (e[1], e[2]))
    entries.sort(key=lambda e: e[0], reverse=True)  # reverse 仍穩定；缺日期（空字串）自然殿後
    pages, cums, consumed, i = [], [], [0] * len(lists), 0
    while i < len(entries):
        page, seen = [], set()
        while i < len(entries) and len(page) < limit:
            _, r, _, num = entries[i]
            i += 1
            consumed[r] += 1
            if num.upper() not in seen:
                seen.add(num.upper())
                page.append((num, r))
        pages.append(page)
        cums.append(list(consumed))
    return pages, cums


def numbers(res):
    return [it.number for it in res.items]


# ---------------------------------------------------------------- 形狀


# ---------------------------------------------------------------- I-M1
@pytest.mark.parametrize("optimistic", [False, True], ids=["exact", "optimistic"])
def test_i_m1_no_duplicate_in_page_case_insensitive(optimistic):
    # mutation 1 的 why：兩個代號各列了大小寫不同的同一部片 → 同一頁出現兩張一樣的封面
    refs = refs_for(2)
    a = [wi("ABC-001", "2026-03-01"), wi("AAA-002", "2026-02-01")]
    b = [wi("abc-001", "2026-03-01"), wi("BBB-003", "2026-01-01")]
    res = merge_windows(ListProvider(by_id([a, b]), optimistic=optimistic), refs, [0, 0], 10)
    keys = [n.upper() for n in numbers(res)]
    assert len(keys) == len(set(keys))
    assert numbers(res) == ["ABC-001", "AAA-002", "BBB-003"]  # 先出現者留（ref 序在前）
    assert [i.origin for i in res.items] == [refs[0], refs[0], refs[1]]
    assert res.new_positions == [-1, -1]  # 被丟掉的 abc-001 仍計入 r2 的消耗位置


# ---------------------------------------------------------------- I-M2
def test_i_m2_same_day_follows_ref_order_then_inner_order():
    # mutation 2 的 why：同一天發行的片兩個代號交錯排列而非照代號順序 → 排序結果使用者無法目視校驗
    refs = refs_for(2)
    r1 = [wi("X1", "2026-05-05"), wi("X2", "2026-05-05"), wi("X3", "2026-05-01"), wi("U1", "")]
    r2 = [wi("Y1", "2026/05/05"), wi("Y2", "2026/05/02"), wi("U2", "")]  # '/' 視同 '-'
    res = merge_windows(ListProvider(by_id([r1, r2])), refs, [0, 0], 20)
    # 同日：ref1 的全部（X1、X2）再 ref2（Y1）；缺日期殿後且依 ref 序
    assert numbers(res) == ["X1", "X2", "Y1", "Y2", "X3", "U1", "U2"]
    assert res.exhausted is True


# ---------------------------------------------------------------- I-M3
@pytest.mark.parametrize("limit", [20, 30, 50])
@pytest.mark.parametrize("n_refs", [2, 3, 4])
@pytest.mark.parametrize("optimistic", [False, True], ids=["exact", "optimistic"])
@pytest.mark.parametrize("chunk", [None, 7], ids=["chunk30", "chunk7"])
def test_i_m3_token_walk_equals_one_shot(limit, n_refs, optimistic, chunk):
    # mutation 5 的 why：按載入更多 → 下一頁從錯的位置接，漏掉或重複一批作品，片數不對而畫面看起來完全正常
    lists = make_lists([140, 17, 61, 33][:n_refs], seed=7)
    refs = refs_for(n_refs)
    prov = ListProvider(by_id(lists), optimistic=optimistic, chunk=chunk)
    steps = walk(prov, refs, limit)
    exp_pages, cums = oracle(lists, limit)

    got = [(res, [(it.number, refs.index(it.origin)) for it in res.items]) for _, res in steps]
    got = [(res, page) for res, page in got if page]  # optimistic 版最後可能多一頁空頁（才發現到底）
    assert [page for _, page in got] == exp_pages

    for (res, _), cum in zip(got, cums, strict=True):
        for i, pos in enumerate(res.new_positions):
            assert pos == cum[i] or (pos == -1 and cum[i] == len(lists[i])), (i, pos, cum[i])
    assert steps[-1][1].exhausted is True
    # 有牙檢查：這組 stub 真的含「被去重丟掉的項」，且至少一個 ref 比別人早到底
    assert sum(cums[-1]) > sum(len(p) for p in exp_pages)
    assert any(res.new_positions[1] == -1 for _, res in steps[:-1])


# ---------------------------------------------------------------- I-M4
@pytest.mark.parametrize("optimistic", [False, True], ids=["exact", "optimistic"])
def test_i_m4_exhausted_ref_never_called_again(optimistic):
    # mutation 3 的 why：一路載入更多翻到舊代號的片單到底後 → 已到底的代號每一頁仍被重複向站方請求
    refs = refs_for(3)
    lists = make_lists([60, 40, 5], seed=3, shared=0)
    # (a) 起點就是 -1 的 ref：整個走完零呼叫
    prov = ListProvider(by_id(lists), optimistic=optimistic)
    positions = [0, -1, 0]
    for _ in range(40):
        res = merge_windows(prov, refs, positions, 10)
        assert res.new_positions[1] == -1
        positions = list(res.new_positions)
        if res.exhausted:
            break
    assert res.exhausted is True
    assert prov.calls_for("r2") == []
    assert prov.calls_for("r1") and prov.calls_for("r3")  # 另外兩個有被問（stub 該問的有問）
    # (b) 走到一半到底的 ref：變 -1 之後的頁不再被呼叫
    prov = ListProvider(by_id(lists), optimistic=optimistic)
    positions, calls_when_done = [0, 0, 0], None
    for _ in range(40):
        res = merge_windows(prov, refs, positions, 10)
        if calls_when_done is None and res.new_positions[2] == -1:
            calls_when_done = len(prov.calls_for("r3"))
        positions = list(res.new_positions)
        if res.exhausted:
            break
    assert calls_when_done is not None and calls_when_done >= 1
    assert len(prov.calls_for("r3")) == calls_when_done


# ---------------------------------------------------------------- I-M5
@pytest.mark.parametrize("chunk", [7, None], ids=["chunk7", "chunk30"])
def test_i_m5_calls_per_ref_per_page_bounded(chunk):
    refs = refs_for(3)
    lists = make_lists([120, 120, 90], seed=11)
    prov = ListProvider(by_id(lists), chunk=chunk)
    size = chunk or 30
    limit = 20
    positions = [0, 0, 0]
    for _ in range(60):
        before = len(prov.calls)
        res = merge_windows(prov, refs, positions, limit)
        page_calls = prov.calls[before:]
        for i, ref in enumerate(refs):
            mine = [c for c in page_calls if c[0] == ref.id]
            assert len(mine) <= math.ceil(limit / size) + 1
            if positions[i] >= 0:
                # 第一塊從 token 帶的位置開始；續取接在已取回的塊後面；塊長固定 C
                assert [c[1] for c in mine] == [positions[i] + n * size for n in range(len(mine))]
                assert all(c[2] == size for c in mine)
            else:
                assert mine == []
        positions = list(res.new_positions)
        if res.exhausted:
            break
    assert res.exhausted is True


# ---------------------------------------------------------------- I-M6
@pytest.mark.parametrize(
    "exc",
    [SourceBlocked("b"), SourceUnreachable("u"), Exception("boom")],
    ids=["SourceBlocked", "SourceUnreachable", "Exception"],
)
@pytest.mark.parametrize("nth", [1, 2], ids=["first_chunk", "continuation_chunk"])
def test_i_m6_chunk_failure_fails_whole_page(exc, nth):
    # mutation 4 的 why：使用者翻片單時其中一個代號暫時連不上 → 看到只剩另一個代號的殘缺清單卻被當成完整
    refs = refs_for(2)
    lists = make_lists([80, 80], seed=5, shared=0)
    prov = ListProvider(by_id(lists), chunk=5, fail={"r2": (nth, exc)})
    with pytest.raises(type(exc)) as info:
        merge_windows(prov, refs, [0, 0], 30)
    assert info.value is exc  # 原例外，不包裝、不吞
    assert prov.raised is True  # 確實是在第 nth 次取塊丟的（續取失敗也不被吞）
    assert len(prov.calls_for("r2")) == nth


# ---------------------------------------------------------------- origin／守衛
def guard_scenario():
    refs = refs_for(2)
    r1 = [wi("A-001", "2026-01-05"), wi("A-002", "2026-01-04")]
    r2 = [wi("B-001", "2026-02-09"), wi("B-002", "2026-02-08"), wi("B-003", "2026-02-07"), wi("B-004", "2026-01-06")]
    owners = {"A-001": "r1", "A-002": "r1", "B-001": "r2", "B-002": "r2", "B-003": "r2", "B-004": "r2"}
    return refs, by_id([r1, r2]), owners


def test_enrich_receives_item_origin_ref(sync_executor):
    # mutation 6 的 why：前 3 部都來自第二個代號 → 拿第一個代號判「是否屬於她」全判否，整份清單被守衛丟掉
    refs, lists, owners = guard_scenario()
    prov = ListProvider(lists, owners=owners)
    items = merge_windows(prov, refs, [0, 0], 10).items
    assert {i.origin.id for i in items} == {"r1", "r2"}  # 非空轉：兩個 ref 的片都在視窗內
    run_window(prov, items, refs[0], delay=0)
    assert sorted(prov.enrich_calls) == sorted((i.number, owners[i.number]) for i in items)
    assert any(num.startswith("B-") and rid == "r2" for num, rid in prov.enrich_calls)


def test_enrich_without_origin_receives_passed_ref(sync_executor):
    refs, lists, owners = guard_scenario()
    prov = ListProvider(lists, owners=owners)
    items = [wi("A-001", "2026-01-05"), wi("B-001", "2026-02-09")]  # origin=None
    run_window(prov, items, refs[1], delay=0)
    assert sorted(prov.enrich_calls) == [("A-001", "r2"), ("B-001", "r2")]


def seeds(cb):
    return sum(1 for c in cb.call_args_list if c.args[0] == -1)


def test_guard_all_belongs_false_is_not_answerable_with_no_seed(sync_executor):
    refs, lists, _ = guard_scenario()
    prov = ListProvider(lists, owners={})  # 沒有任何片屬於任何 ref
    items = merge_windows(prov, refs, [0, 0], 10).items
    cb = MagicMock()
    out = run_window(prov, items, refs[0], guard=True, delay=0, result_callback=cb)
    assert out.outcome is Outcome.NOT_ANSWERABLE and out.cards == []
    assert seeds(cb) == 0
    assert len(prov.enrich_calls) == 3  # 只抓守衛那 3 部
