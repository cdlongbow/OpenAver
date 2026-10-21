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
from core.search_providers.pipeline import fetch_window, run_window
from core.search_providers.types import Enriched, EntityRef, Kind, Page, Window, WorkItem

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
    """本檔唯一的 sleep 點（測試 patch 它）。"""
    time.sleep(seconds)


def _request_delay() -> float:
    import core.scraper as m  # 函式內 import：頂層不得 import core.scraper（BE-PY-08）

    return m.REQUEST_DELAY


def _paced(fn, *args, **kwargs):
    """序列階段的每次 JavDB 請求：完成後（含失敗）至少等 REQUEST_DELAY（I-A1：任兩次請求 ≥0.3 秒）。
    後置 sleep 同時保證「最後一次列表請求 → 第一批詳情」也有間隔。詳情階段的間隔由 pipeline 負責。"""
    try:
        return fn(*args, **kwargs)
    finally:
        _sleep(_request_delay())


def norm_number(number) -> str:
    return (number or "").upper().replace("-", "").strip() if isinstance(number, str) else ""


_LIST_FILTER = {
    Kind.ACTOR: "a",
    Kind.SERIES: "s",
    Kind.DIRECTOR: "d",
    Kind.MAKER: "m",
    Kind.CODE: "c",
}


def _partial_matches(items, want):
    out = []
    for it in items:
        if norm_number(it.number).startswith(want):
            out.append(it)
    return out


def _keep_newer(items):
    """同號異片（撞號）只留發行日較新者；保留首次出現的順序。"""
    best: dict[str, WorkItem] = {}
    for it in items:
        key = norm_number(it.number)
        prev = best.get(key)
        if prev is None or it.date > prev.date:
            best[key] = it
    return list(best.values())


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
    capabilities = frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD}
    )
    supports_discovery = False
    # 補完詳情後依日期重排，串流順序≠最終順序（BE-DATA-20）
    fallback_streaming = False

    def __init__(self, scraper=None):
        self._scraper_obj = scraper

    @property
    def _scraper(self):
        if self._scraper_obj is None:
            from core.scrapers.javdb import JavDBScraper  # 延後 import（BE-PY-08）

            self._scraper_obj = JavDBScraper()
        return self._scraper_obj

    def _proxies(self):
        return self._scraper._proxy_kwargs().get("proxies")

    def _search(self, search_type: str, q: str) -> list[Candidate]:
        proxies = self._proxies()
        rows = _paced(lambda: javdb_api.api_search_typed(search_type, q, proxies=proxies))
        return parse_candidates(rows)

    def _lookup(self, kind: Kind, q: str, qf: str) -> Candidate | None:
        if kind is Kind.MAKER:
            names = _maker_names(q)
            wanted = {fold(n) for n in names}
            for name in names:
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
        if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
            _RESOLVE_CACHE.clear()
        _RESOLVE_CACHE[key] = ref
        return ref

    # ------------------------------------------------------------ 清單
    def list_entity(self, ref: EntityRef, w: Window) -> Page:
        flag = _LIST_FILTER.get(ref.kind)
        if flag is None:
            raise ValueError(f"javdb list_entity: unsupported kind {ref.kind}")
        filter_by = f"0:{flag}:{ref.id}"
        proxies = self._proxies()

        def fetch_page(p: int) -> Page:
            rows = _paced(lambda: javdb_api.api_list_tags(filter_by, p, proxies=proxies))
            return list_page(rows, p)

        return fetch_window(PAGE_SIZE, fetch_page, w, max_page=MAX_PAGE)

    def search_keyword(self, q: str, w: Window) -> Page:
        proxies = self._proxies()

        def fetch_page(p: int) -> Page:
            rows = _paced(lambda: javdb_api.api_search_page(q, p, proxies=proxies))
            return list_page(rows, p)

        return fetch_window(PAGE_SIZE, fetch_page, w, max_page=MAX_PAGE)

    # ------------------------------------------------------------ 補詳情
    def _belongs(self, item: WorkItem, ref: EntityRef | None, facts: DetailFacts) -> bool | None:
        if ref is None:
            return None
        if ref.kind is Kind.ACTOR:
            return ref.id in facts.actor_ids
        if ref.kind is Kind.SERIES:
            return facts.series_id == ref.id
        if ref.kind is Kind.DIRECTOR:
            return facts.director_id == ref.id
        if ref.kind is Kind.MAKER:
            return facts.maker_id == ref.id
        if ref.kind is Kind.CODE:
            return norm_number(item.number).startswith(norm_number(ref.id))
        return None

    def enrich(self, item: WorkItem, ref: EntityRef | None) -> Enriched:
        """不自己 sleep：詳情間隔由 pipeline 負責（雙重 sleep 會砍半吞吐）。"""
        detail = javdb_api.api_movie_detail(item.ref, proxies=self._proxies())
        card = javdb_api.to_video(detail, item.number).to_legacy_dict()
        card["_source"] = SOURCE
        return Enriched(card, self._belongs(item, ref, parse_detail_facts(detail)))

    # ------------------------------------------------------------ 統一入口
    def run(self, kind: Kind, target: str, w: Window, *, status_callback=None, result_callback=None,
            discovery_only: bool = False) -> list[dict]:
        if kind not in (Kind.CODE, Kind.KEYWORD, Kind.PARTIAL):
            raise ValueError(f"javdb run: unsupported kind {kind}")
        if discovery_only:
            return []
        if status_callback:
            status_callback(SOURCE, "searching")
        if kind is Kind.CODE:
            cards = self._run_code(target, w, result_callback)
        elif kind is Kind.KEYWORD:
            cards = self._run_keyword(target, w, result_callback)
        else:
            cards = self._run_partial(target, w, result_callback)
        if not cards:
            return []
        if status_callback:
            status_callback("done", f"found:{len(cards)}")
        import core.scraper as m

        cards = m.sort_results_by_date(cards)
        for card in cards:
            card["_source"] = SOURCE
        return cards

    def _run_code(self, target, w, result_callback) -> list[dict]:
        ref = self.resolve(Kind.CODE, target.strip().upper())
        if ref is None:
            return []
        page = self.list_entity(ref, w)
        if not page.items:
            return []
        return run_window(
            self,
            page.items,
            ref,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=True,
            breaker=True,
        ).cards

    def _run_keyword(self, target, w, result_callback) -> list[dict]:
        page = self.search_keyword(target, w)
        if not page.items:
            return []
        return run_window(
            self,
            page.items,
            None,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=False,
            breaker=True,
        ).cards

    def _run_partial(self, target, w, result_callback) -> list[dict]:
        """局部搜尋：忽略 w.limit（relay 傳 Window(0,0)）、只取第 1 頁、客戶端過濾前綴。"""
        if w.offset > 0:
            return []
        proxies = self._proxies()
        rows = _paced(lambda: javdb_api.api_search_page(target.strip(), 1, proxies=proxies))
        items = _keep_newer(_partial_matches(parse_list_rows(rows), norm_number(target)))
        if not items:
            return []
        return run_window(
            self,
            items,
            None,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=False,
            breaker=True,
        ).cards
