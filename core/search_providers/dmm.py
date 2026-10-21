"""DMM 的 Provider（175a-T5）：把 scraper.py 的 DMM「列表＋逐部補詳情」原封包入。

行為與事件序與搬家前逐一相同（離線 A/B 40 題 ALL SAME 為守門）。
頂層不得 import core.scraper／core.database（BE-PY-08）。補詳情一律經 pipeline.run_window。
"""

from __future__ import annotations

from core.logger import get_logger
from core.scrapers.dmm import DMMScraper, _actress_main_name
from core.scrapers.models import Actress, Video
from core.search_providers.pipeline import run_window
from core.search_providers.types import Enriched, Kind, Page, Window, WorkItem

logger = get_logger(__name__)

SOURCE = "dmm"


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
