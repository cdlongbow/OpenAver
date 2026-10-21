"""DMM 的 Provider（175a-T5）：把 scraper.py 的 DMM「列表＋逐部補詳情」原封包入。

行為與事件序與搬家前逐一相同（離線 A/B 40 題 ALL SAME 為守門）。
頂層不得 import core.scraper／core.database（BE-PY-08）。補詳情一律經 pipeline.run_window。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from core.logger import get_logger
from core.maker_names import maker_key_of
from core.name_match import fold, split_paren_name
from core.scrapers.dmm import DMMScraper, Facts, _actress_main_name
from core.scrapers.models import Actress, Video
from core.search_providers.names import maker_names
from core.search_providers.pipeline import run_window
from core.search_providers.types import EntityRef, Enriched, Kind, Page, Window, WorkItem

logger = get_logger(__name__)

SOURCE = "dmm"


# ---------------------------------------------------------------- 名稱→實體（175c-T7，plan CD-175c-6 (B)）
_PROBE_LIST_LIMIT = 40  # stage 1 取一頁 40 筆（站方依發行日排序，sort 在 list_contents 內固定）
_PROBE_CACHE_MAX = 256  # 超過整張清空，重啟即清，無持久化
_MAKER_PROBE_MAX = 3  # _resolve_maker 至多問前 3 個拼法
_RESOLVE_KINDS = frozenset({Kind.ACTOR, Kind.MAKER, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL})


@dataclass
class Probe:
    """一個名字的探測結果：stage 1 的 rows（一定有）＋ stage 2 的 facts（用到才取；None＝尚未取到）。"""

    rows: list[dict]
    facts: dict[str, Facts] | None = None


_PROBE_CACHE: dict[str, Probe] = {}


def clear_probe_cache() -> None:
    _PROBE_CACHE.clear()


def _same_name(candidate, wanted) -> bool:
    """名稱精確相等（fold 後）。子字串不算：列表是依關鍵字撈的，共演者、標題碰巧含該字的人都會在 rows 裡。"""
    return fold(candidate) == fold(wanted)


def _ident(value) -> str | None:
    """站方 id → 字串；缺／空 → None（該項略過）。"""
    return None if value in (None, "") else str(value)


def _stage1(scraper, name: str) -> Probe:
    """名字 → Probe（rows）。只快取成功；傳輸例外原樣往外丟、不入快取（BE-PY-03）。"""
    key = fold(name)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    rows = scraper.list_contents(name, limit=_PROBE_LIST_LIMIT, offset=0).rows
    if len(_PROBE_CACHE) >= _PROBE_CACHE_MAX:
        _PROBE_CACHE.clear()
    probe = _PROBE_CACHE[key] = Probe(rows)
    return probe


def _row_ids(probe: Probe) -> list[str]:
    ids = (_ident(r.get("id")) for r in probe.rows)
    return list(dict.fromkeys(i for i in ids if i))


def _stage2(scraper, probe: Probe) -> dict[str, Facts]:
    """Probe 的 facts：每個名字至多一次（SERIES／DIRECTOR／LABEL 共用）；rows 無 id 不發；失敗時 stage 1 保留、下次只重試這段。"""
    if probe.facts is None:
        ids = _row_ids(probe)
        probe.facts = scraper.fetch_facts(ids) if ids else {}
    return probe.facts


def _most_common(hits):
    """hits＝[(id, label)…]（依出現順序）→ 出現次數最多者；平手取先出現；空 → None。"""
    counts = Counter(i for i, _ in hits)
    if not counts:
        return None
    top = max(counts.values())
    return next((i, label) for i, label in hits if counts[i] == top)


def _actor_names(actress: dict) -> list[str]:
    """一位女優可被輸入比中的名字：主名與括號內舊名（あかね麗（二階堂麗）→ あかね麗、二階堂麗）。"""
    main, old = split_paren_name(actress.get("name"))
    return [n for n in (main, old) if n]


def _pick_actor(rows: list[dict], wanted: str) -> EntityRef | None:
    hits = []
    for row in rows:
        for actress in row.get("actresses") or []:
            aid = _ident(actress.get("id"))
            names = _actor_names(actress)
            if aid and any(_same_name(n, wanted) for n in names):
                hits.append((aid, names[0]))
    best = _most_common(hits)
    return None if best is None else EntityRef(Kind.ACTOR, best[0], best[1])


def _named_in(facts: Facts, kind: Kind) -> list:
    """facts 裡該 kind 的 Named 清單（directors 本來就是 list）。"""
    if kind is Kind.DIRECTOR:
        return list(facts.directors)
    one = facts.series if kind is Kind.SERIES else facts.label
    return [] if one is None else [one]


def _pick_named(probe: Probe, facts: dict[str, Facts], kind: Kind, wanted: str) -> EntityRef | None:
    hits = []
    for cid in _row_ids(probe):  # 依 rows 出現順序走，不依 fetch_facts 回傳 dict 的順序
        found = facts.get(cid)
        for named in [] if found is None else _named_in(found, kind):
            nid = _ident(named.id)
            if nid and _same_name(named.name, wanted):
                hits.append((nid, named.name))
    best = _most_common(hits)
    return None if best is None else EntityRef(kind, best[0], best[1])


def _pick_maker(rows: list[dict], spellings: set[str]) -> EntityRef | None:
    hits = []
    for row in rows:
        maker = row.get("maker") or {}
        mid, mname = _ident(maker.get("id")), maker.get("name")
        if mid and mname and maker_key_of(mname) in spellings:
            hits.append((mid, mname))
    best = _most_common(hits)
    return None if best is None else EntityRef(Kind.MAKER, best[0], best[1])


class DMMProvider:
    id = SOURCE
    capabilities = frozenset({Kind.KEYWORD})
    supports_discovery = False
    fallback_streaming = True  # 最終陣列不重排，串流順序＝最終順序

    def __init__(self, scraper=None):
        self._scraper_obj = scraper

    @property
    def _scraper(self):
        if self._scraper_obj is None:
            self._scraper_obj = DMMScraper()
        return self._scraper_obj

    def resolve(self, kind: Kind, name: str) -> EntityRef | None:
        """女優／系列／導演／label／片商名稱 → 站上同一個實體；其他 kind 與空白輸入 → None（0 請求）。

        傳輸只經 list_contents（stage 1）與 fetch_facts（stage 2）；比對全為精確（fold 相等）；
        傳輸例外（SourceBlocked／SourceUnreachable／其他）原樣往外丟，不吞、不轉型、不入快取。
        """
        if kind not in _RESOLVE_KINDS or not fold(name):
            return None
        if kind is Kind.MAKER:
            return self._resolve_maker(maker_names(name))
        probe = _stage1(self._scraper, name)
        if kind is Kind.ACTOR:
            return _pick_actor(probe.rows, name)
        return _pick_named(probe, _stage2(self._scraper, probe), kind, name)

    def _resolve_maker(self, names: list[str]) -> EntityRef | None:
        """逐個拼法各打一次 stage 1，命中即停，至多前 3 個；命中集合＝傳入的全部 names（不展開、不補別名）。"""
        spellings = {maker_key_of(n) for n in names}
        for name in [n for n in names if fold(n)][:_MAKER_PROBE_MAX]:
            ref = _pick_maker(_stage1(self._scraper, name).rows, spellings)
            if ref is not None:
                return ref
        return None

    def search_keyword(self, q: str, w: Window) -> Page:
        """列表一頁 → WorkItem（shallow Video 的取值沿用舊流程：番號由 cid 推導、女優去括號舊名、不帶日期）。
        列表失敗（被擋／連不上）原樣往外拋，由 relay 接住換下一家；contents 為空才是『查無』。"""
        result = self._scraper.list_contents(q, limit=w.limit, offset=w.offset)
        items = []
        for row in result.rows:
            content_id = row.get("id", "")
            if not content_id:
                continue
            shallow = Video(
                number=self._scraper._content_id_to_number(content_id),
                title=row.get("title", ""),
                actresses=[
                    Actress(name=_actress_main_name(a["name"]))
                    for a in (row.get("actresses") or [])
                    if a.get("name")
                ],
                maker=(row.get("maker") or {}).get("name", ""),
                cover_url=(row.get("packageImage") or {}).get("largeUrl", ""),
                source=self._scraper.source_name,
                detail_url=f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={content_id}/",
            )
            items.append(
                WorkItem(
                    number=shallow.number,
                    title=shallow.title,
                    cover_url=shallow.cover_url,
                    date=shallow.date,
                    actors=None,
                    source=SOURCE,
                    ref=(content_id, shallow),
                )
            )
        return Page(items, has_next=len(items) >= w.limit, total=None)

    def enrich(self, item: WorkItem, ref=None) -> Enriched:
        """ref 是實體參照（DMM 無），一律用 item.ref。失敗退 shallow 全欄位卡（與今天相同）。"""
        content_id, shallow = item.ref
        try:
            video = self._scraper._fetch_by_id(content_id)
            if video is None:
                video = shallow
        except Exception:
            logger.error("DMM enrichment failed: %s", content_id)
            video = shallow
        return Enriched(video.to_legacy_dict(), None)

    def run(self, kind: Kind, target: str, w: Window, *, status_callback=None, result_callback=None,
            discovery_only: bool = False) -> list[dict]:
        if kind is not Kind.KEYWORD:
            raise ValueError(f"dmm run: unsupported kind {kind}")
        if discovery_only:
            return []
        if status_callback:
            status_callback("dmm", "searching")
        page = self.search_keyword(target, w)
        if not page.items:
            return []
        res = run_window(
            self,
            page.items,
            None,
            result_callback=result_callback,
            on_fail="degrade",
            delay=0,
            breaker=False,
            guard=False,
        )
        if status_callback:
            status_callback("done", f"found:{len(res.cards)}")
        for card in res.cards:
            card["_source"] = "dmm"
        return res.cards
