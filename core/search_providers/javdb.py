"""JavDB 的純函式 parser 與資料類別（175b-T2）。

只放「站方回應 dict → 我們的型別」的純函式；不放 provider class（T3／T4 才加），也不做任何傳輸。
頂層不得 import core.scraper／core.database（BE-PY-08）；core/scrapers/ 不得反向 import 本檔。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.logger import get_logger
from core.scrapers.javdb_api import MAX_PAGE, PAGE_SIZE
from core.scrapers.utils import strip_number_prefix
from core.search_providers.types import Page, WorkItem

logger = get_logger(__name__)

SOURCE = "javdb"


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _id(v) -> str:
    """id 欄位：字串或整數皆收，其餘（None、bool、容器）視為缺。"""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (str, int)):
        return str(v).strip()
    return ""


def _opt_id(v) -> str | None:
    return _id(v) or None


# ---------------------------------------------------------------- 候選（type= 搜尋）
@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    name_zht: str
    other_name: str  # 不切分：接受規則（T3）自己處理
    videos_count: int
    type: int | None


def parse_candidates(rows) -> list[Candidate]:
    """候選列 → Candidate；非 dict／缺 id／缺 name 的列丟棄，不拋。"""
    out: list[Candidate] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        cid, name = _id(r.get("id")), _s(r.get("name"))
        if not cid or not name:
            continue
        vc = r.get("videos_count")
        t = r.get("type")
        out.append(
            Candidate(
                id=cid,
                name=name,
                name_zht=_s(r.get("name_zht")),
                other_name=_s(r.get("other_name")),
                videos_count=vc if isinstance(vc, int) and not isinstance(vc, bool) else 0,
                type=t if isinstance(t, int) and not isinstance(t, bool) else None,
            )
        )
    return out


# ---------------------------------------------------------------- 列表列
def parse_list_rows(rows) -> list[WorkItem]:
    """列表列 → WorkItem；非 dict／缺 id／缺 number 的列丟棄，不拋。

    標題一律日文原文：origin_title 空則退 title，再過 strip_number_prefix（與 to_video 同規則）。
    列表沒有女優 ⇒ actors=None（要靠 enrich 補）。
    """
    out: list[WorkItem] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        mid, number = _id(r.get("id")), _s(r.get("number"))
        if not mid or not number:
            continue
        title = _s(r.get("origin_title")) or _s(r.get("title"))
        out.append(
            WorkItem(
                number=number,
                title=strip_number_prefix(title, number),
                cover_url=_s(r.get("cover_url")) or _s(r.get("thumb_url")),
                date=_s(r.get("release_date")),
                actors=None,
                source=SOURCE,
                ref=mid,
            )
        )
    return out


def list_page(rows, page: int) -> Page:
    """一頁原始列 → Page。has_next 看「原始列數」是否滿頁（被丟棄的列也算站方給的）；total 恆 None。"""
    raw = rows if isinstance(rows, list) else []
    has_next = len(raw) >= PAGE_SIZE and page < MAX_PAGE
    return Page(parse_list_rows(raw), has_next, None)


# ---------------------------------------------------------------- 詳情事實
@dataclass(frozen=True)
class DetailFacts:
    maker_id: str | None
    series_id: str | None
    director_id: str | None
    publisher_id: str | None
    actor_ids: frozenset[str]
    origin_title: str
    title: str


def parse_detail_facts(movie) -> DetailFacts:
    """詳情 movie dict → DetailFacts；不做 belongs 判斷（T4 的 enrich）。非 dict 回全空。"""
    m = movie if isinstance(movie, dict) else {}
    actors = m.get("actors")
    ids = frozenset(
        a
        for a in (_id(x.get("id")) for x in (actors if isinstance(actors, list) else []) if isinstance(x, dict))
        if a
    )
    return DetailFacts(
        maker_id=_opt_id(m.get("maker_id")),
        series_id=_opt_id(m.get("series_id")),
        director_id=_opt_id(m.get("director_id")),
        publisher_id=_opt_id(m.get("publisher_id")),
        actor_ids=ids,
        origin_title=_s(m.get("origin_title")),
        title=_s(m.get("title")),
    )
