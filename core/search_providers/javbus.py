"""JavBus 的 Provider（175a-T4）：把 scraper.py 的四條搜尋流程原封包入。

行為與事件序與搬家前逐一相同（離線 A/B 40 題 ALL SAME 為守門）。
頂層不得 import core.scraper／core.database（BE-PY-08）；core.scraper 的名字一律在呼叫當下取
（既有測試 patch 的是 core.scraper.*）。取頁一律經 pipeline.fetch_window、詳情一律經 pipeline.run_window。
"""

from __future__ import annotations

from core.logger import get_logger
from core.scrapers.javbus import JAVBUS_LIST_PAGE_SIZE
from core.search_providers.pipeline import fetch_window, run_window
from core.search_providers.types import (
    MAKER_RESOLUTION_ERRORS,
    Enriched,
    EntityRef,
    Kind,
    MakerSearchResult,
    Page,
    Window,
    WorkItem,
)

logger = get_logger(__name__)

PAGE_SIZE = 30
SOURCE = "javbus"


def _stub(number: str) -> WorkItem:
    return WorkItem(number, "", "", "", None, SOURCE)


def _stubs(numbers) -> list[dict]:
    return [{"number": n, "title": ""} for n in numbers]


def _fetch_page(fetch_ids, w: Window):
    """fetch_ids(page_no) -> list[str]。回 (fetch_window 算好的 Page, 是否曾取回任何 id)。

    「曾取回」另外記：切片後為空（offset 落在該頁筆數之後）與「完全沒有 id」今天的事件不同。
    """
    seen = []

    def fetch_page(page_no):
        ids = fetch_ids(page_no)
        if ids:
            seen.append(True)
        return Page([_stub(n) for n in ids or []], has_next=True)

    return fetch_window(PAGE_SIZE, fetch_page, w), bool(seen)


def _fetch_ids(fetch_ids, w: Window):
    page, got_any = _fetch_page(fetch_ids, w)
    return [i.number for i in page.items], got_any


def _progress_hook(status_callback, total):
    """前綴的 details:k/N：每部（含失敗）各一次，依真實完成順序，先於該部 result-item。"""
    if status_callback is None:
        return None
    done = 0

    def on_item_done(slot, ok):
        nonlocal done
        done += 1
        status_callback("javbus", f"details:{done}/{total}")

    return on_item_done


def _detail_window(provider, numbers, result_callback, on_item_done=None) -> list[dict]:
    """對一批番號抓詳情：失敗／無 title 就丟、不斷路、不加延遲（與今天相同）。"""
    return run_window(
        provider,
        [_stub(n) for n in numbers],
        None,
        result_callback=result_callback,
        on_item_done=on_item_done,
        on_fail="drop",
        delay=0,
        breaker=False,
        guard=False,
    ).cards


def _sorted(cards):
    import core.scraper as m

    return m.sort_results_by_date(cards)


class JavBusProvider:
    id = SOURCE
    capabilities = frozenset({Kind.KEYWORD, Kind.PARTIAL, Kind.CODE, Kind.MAKER})
    supports_discovery = True

    # ------------------------------------------------------------ Protocol
    def resolve(self, kind: Kind, name: str) -> EntityRef | None:
        return None

    def list_entity(self, ref: EntityRef, w: Window) -> Page:
        if ref.kind is Kind.CODE:
            scraper = self._scraper()
            return _fetch_page(lambda p: scraper.get_ids_from_search(ref.id, page=p, search_type=1), w)[0]
        if ref.kind is Kind.PARTIAL:
            import core.scraper as m

            numbers = m.expand_partial_number(ref.id) if w.offset <= 0 else []
            return Page([_stub(n) for n in numbers])
        raise NotImplementedError(f"javbus list_entity: {ref.kind}")

    def search_keyword(self, q: str, w: Window) -> Page:
        scraper = self._scraper()
        return _fetch_page(lambda p: scraper.get_ids_from_search(q, page=p), w)[0]

    def enrich(self, item: WorkItem, ref: EntityRef | None) -> Enriched:
        import core.scraper as m

        data = m.search_jav(item.number, SOURCE)
        if data and data.get("title"):
            return Enriched(card=data, belongs=None)
        return Enriched(card=None)

    # ------------------------------------------------------------ 統一入口
    def run(self, kind: Kind, target: str, w: Window, *, status_callback=None, result_callback=None,
            discovery_only: bool = False) -> list[dict]:
        if kind is Kind.KEYWORD:
            return self.run_keyword(target, w.limit, w.offset, status_callback, result_callback, discovery_only)
        if kind is Kind.PARTIAL:
            if w.offset > 0:
                return []
            return self.run_partial(target, status_callback, result_callback, discovery_only)
        if kind is Kind.CODE:
            return self.run_prefix(target, w.limit, w.offset, status_callback, result_callback, discovery_only)
        raise ValueError(f"javbus run: unsupported kind {kind}")

    # ------------------------------------------------------------ 四條舊流程
    def run_partial(self, partial, status_callback, result_callback, discovery_only):
        """局部搜尋"""
        import core.scraper as m

        candidates = m.expand_partial_number(partial)
        if status_callback:
            status_callback("javbus", "searching")
        if discovery_only:
            if candidates and result_callback:
                result_callback(-1, candidates)
            if status_callback:
                status_callback("done", f"found:{len(candidates)}")
            return _stubs(candidates)
        results = _detail_window(self, candidates, result_callback)
        if status_callback:
            status_callback("done", f"found:{len(results)}")
        return _sorted(results)

    def run_prefix(self, prefix, limit, offset, status_callback, result_callback, discovery_only):
        """前綴搜尋"""
        results: list[dict] = []
        prefix = prefix.strip().upper()
        if status_callback:
            status_callback("javbus", "searching")
        try:
            scraper = self._scraper()
            numbers, got_any = _fetch_ids(
                lambda p: scraper.get_ids_from_search(prefix, page=p, search_type=1), Window(offset, limit))
            if not got_any:
                if status_callback:
                    status_callback("javbus", "found:0")
                return []
            if status_callback:
                status_callback("javbus", f"found:{len(numbers)}")
            if discovery_only:
                if status_callback:
                    status_callback("done", f"found:{len(numbers)}")
                return _stubs(numbers)
            if status_callback:
                status_callback("javbus", "fetching_details")
            results = _detail_window(self, numbers, result_callback, _progress_hook(status_callback, len(numbers)))
        except Exception as e:
            logger.error("search_prefix failed: %s", e)
        if status_callback:
            status_callback("done", f"found:{len(results)}")
        return _sorted(results)

    def run_keyword(self, name, limit, offset, status_callback, result_callback, discovery_only=False, *,
                    ids_provider=None):
        """JavBus keyword search；ids_provider（173）取代「取番號那一步」，簽名 (scraper, page) -> ids。"""
        try:
            if status_callback:
                status_callback("javbus", "searching")
            scraper = self._scraper()
            def fetch_ids(p):
                if ids_provider is None:
                    return scraper.get_ids_from_search(name, page=p)
                return ids_provider(scraper, p)

            numbers, got_any = _fetch_ids(fetch_ids, Window(offset, limit))
            if got_any:
                if status_callback:
                    status_callback("javbus", f"found:{len(numbers)}")
                if discovery_only:
                    if status_callback:
                        status_callback("done", f"found:{len(numbers)}")
                    return _stubs(numbers)
                results = _detail_window(self, numbers, result_callback)
                if status_callback:
                    status_callback("done", f"found:{len(results)}")
                return _sorted(results)
        except Exception as e:
            logger.error("_javbus_keyword_search failed: %s", e)
        return []

    def run_maker(self, maker_key, label, spellings, offset, *, titles, today, status_callback=None,
                  result_callback=None, db_path=None) -> MakerSearchResult:
        """片商最新作品（JavBus 片商頁，一次一頁 30 部，發行日新到舊）。不攔 resolve_maker_studio 的未預期例外。"""
        import core.scraper as m

        if offset < 0 or offset % JAVBUS_LIST_PAGE_SIZE:
            raise ValueError(f"offset must be a non-negative multiple of {JAVBUS_LIST_PAGE_SIZE}: {offset}")
        if status_callback:
            status_callback("javbus", "searching")
        resolution = m.resolve_maker_studio(maker_key, label, spellings, titles, today=today, db_path=db_path)
        if resolution.status != "found":
            code = MAKER_RESOLUTION_ERRORS.get(resolution.status, "maker_unreachable")
            return MakerSearchResult([], False, code)

        ref = (resolution.kind, resolution.studio_id)
        request_page = offset // JAVBUS_LIST_PAGE_SIZE + 1
        counts: dict[int, int] = {}
        errors: list[BaseException] = []

        def ids_provider(scraper, page):
            if page != request_page:
                return []
            try:
                ids = scraper.get_ids_from_studio(ref, page)
            except Exception as e:
                errors.append(e)
                raise
            counts[page] = len(ids)
            return ids

        results = self.run_keyword(
            label, JAVBUS_LIST_PAGE_SIZE, offset, status_callback, result_callback, ids_provider=ids_provider)
        if errors:
            logger.error("maker %s list failed: %s: %s", maker_key, type(errors[0]).__name__, errors[0])
            return MakerSearchResult([], False, "maker_unreachable")
        if not counts.get(request_page):
            logger.info("maker %s page %d empty", maker_key, request_page)
            return MakerSearchResult([], False, "maker_empty")
        return MakerSearchResult(results, counts.get(request_page, 0) >= JAVBUS_LIST_PAGE_SIZE, None)

    # ------------------------------------------------------------ 內部
    def _scraper(self):
        import core.scraper as m

        return m.JavBusScraper(lang=m.get_javbus_lang())
