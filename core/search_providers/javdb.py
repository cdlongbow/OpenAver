"""JavDB 的純函式 parser 與資料類別（175b-T2）。

只放「站方回應 dict → 我們的型別」的純函式；不放 provider class（T3／T4 才加），也不做任何傳輸。
頂層不得 import core.scraper／core.database（BE-PY-08）；core/scrapers/ 不得反向 import 本檔。
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from core.logger import get_logger
from core.maker_mapping import load_name_mapping, load_search_aliases
from core.maker_names import maker_key_of
from core.scrapers import javdb_api
from core.scrapers.javdb_api import MAX_PAGE, PAGE_SIZE
from core.scrapers.utils import strip_number_prefix
from core.search_providers.types import EntityRef, Kind, Page, WorkItem

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


# ---------------------------------------------------------------- 名字 → 實體（175b-T3）
_STRIP = set("・·-_")
_SPLIT = re.compile(r"[,、，/／]")
_SERIES_MIN_VIDEOS = 5
_MAKER_MAX_NAMES = 4
_MAKER_REQUEST_GAP = 0.3  # 秒；片商候選名逐名請求之間的最小間隔（主 session 裁決 D4）
_RESOLVE_CACHE_MAX = 1024
_RESOLVE_CACHE: dict[tuple[str, str], EntityRef | None] = {}
_SEARCH_TYPE = {
    Kind.ACTOR: "actor",
    Kind.SERIES: "series",
    Kind.DIRECTOR: "director",
    Kind.MAKER: "maker",
    Kind.CODE: "code",
}


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def clear_resolve_cache() -> None:
    _RESOLVE_CACHE.clear()


def fold(s) -> str:
    """NFKC → casefold → 去空白與 ・·-_（不做漢字字形對照，CD-175b-1）。"""
    t = unicodedata.normalize("NFKC", s if isinstance(s, str) else "").casefold()
    return "".join(ch for ch in t if not ch.isspace() and ch not in _STRIP)


def _names(c: Candidate) -> list[str]:
    return [n for n in (c.name, c.name_zht, *_SPLIT.split(c.other_name)) if n]


def _largest(cands: list[Candidate]) -> Candidate:
    return max(cands, key=lambda c: c.videos_count)  # max 遇平手取先出現


def _pick_actor(cands: list[Candidate], qf: str) -> Candidate | None:
    pool = [c for c in cands if c.type == 0]
    exact = [c for c in pool if any(fold(n) == qf for n in _names(c))]
    if exact:
        return _largest(exact)
    if len(pool) == 1 and not any(qf in fold(n) for n in _names(pool[0])):
        return pool[0]
    return None


def _named_enough(c: Candidate, qf: str) -> bool:
    return fold(c.name) == qf and c.videos_count >= _SERIES_MIN_VIDEOS


def _pick_named(cands: list[Candidate], qf: str) -> Candidate | None:
    ok = [c for c in cands if _named_enough(c, qf)]
    return _largest(ok) if ok else None


def _pick_code(cands: list[Candidate], qf: str) -> Candidate | None:
    ok = [c for c in cands if fold(c.name) == qf]
    return _largest(ok) if ok else None


def _pick_maker(cands: list[Candidate], wanted: set[str]) -> Candidate | None:
    accepted = [
        c
        for c in cands
        if fold(c.name) in wanted and c.videos_count > 0
    ]
    if not accepted:
        return None
    return max(accepted, key=lambda c: c.videos_count)


def _maker_names(q: str) -> list[str]:
    """候選名集合 S：[輸入、正名、該正名底下全部別名]，以 maker_key_of 去重保序，最多 4 個。"""
    canon_of: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for table in (load_name_mapping(), load_search_aliases()):
        for alias, canon in table.items():
            canon_of[maker_key_of(alias)] = canon
            members.setdefault(maker_key_of(canon), []).append(alias)
    canon = canon_of.get(maker_key_of(q), q)
    out: list[str] = []
    seen: set[str] = set()
    for n in (q, canon, *members.get(maker_key_of(canon), [])):
        k = maker_key_of(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out[:_MAKER_MAX_NAMES]


class JavDBProvider:
    id = SOURCE
    capabilities = frozenset({Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE})

    def __init__(self, scraper=None):
        self._scraper_obj = scraper

    @property
    def _scraper(self):
        if self._scraper_obj is None:
            from core.scrapers.javdb import JavDBScraper  # 延後 import（BE-PY-08）

            self._scraper_obj = JavDBScraper()
        return self._scraper_obj

    def _search(self, search_type: str, q: str) -> list[Candidate]:
        proxies = self._scraper._proxy_kwargs().get("proxies")
        return parse_candidates(javdb_api.api_search_typed(search_type, q, proxies=proxies))

    def _lookup(self, kind: Kind, q: str, qf: str) -> Candidate | None:
        if kind is Kind.MAKER:
            names = _maker_names(q)
            wanted = {fold(n) for n in names}
            for i, name in enumerate(names):
                if i:
                    _sleep(_MAKER_REQUEST_GAP)
                hit = _pick_maker(self._search("maker", name), wanted)
                if hit is not None:
                    return hit
            return None
        cands = self._search(_SEARCH_TYPE[kind], q)
        if kind is Kind.ACTOR:
            return _pick_actor(cands, qf)
        if kind is Kind.CODE:
            return _pick_code(cands, qf)
        return _pick_named(cands, qf)

    def resolve(self, kind: Kind, q: str) -> EntityRef | None:
        if kind not in _SEARCH_TYPE:
            return None
        qf = fold(q)
        if not qf:
            return None
        key = (kind.value, maker_key_of(q))
        if key in _RESOLVE_CACHE:
            return _RESOLVE_CACHE[key]
        cand = self._lookup(kind, q, qf)  # 例外原樣往外丟，不入快取（BE-PY-03）
        ref = None
        if cand is not None:
            ref = EntityRef(kind, cand.name if kind is Kind.CODE else cand.id, cand.name)
            if kind is Kind.ACTOR:
                javdb_api.remember_actor_name(cand.id, cand.name)
        if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
            _RESOLVE_CACHE.clear()
        _RESOLVE_CACHE[key] = ref
        return ref
