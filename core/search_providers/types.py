"""共用查詢介面的型別（CD-175a-1）。純資料與 Protocol，不含任何站方邏輯。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NamedTuple, Protocol


class Kind(str, Enum):
    """能力詞彙。前五個是「名字 → 實體」；後三個是「字串 → 清單」。"""

    ACTOR = "actor"
    SERIES = "series"
    DIRECTOR = "director"
    LABEL = "label"
    MAKER = "maker"
    CODE = "code"
    PARTIAL = "partial"
    KEYWORD = "keyword"


class Outcome(str, Enum):
    """一個視窗（或一家 provider）的答覆結果。

    ANSWERED：至少一張卡。
    NOT_ANSWERABLE：這家確定沒有（空頁、守衛不通過、全部被丟棄）。
    UNREACHABLE：連不上或被擋（與「沒有」必須分得開，BE-PY-03）。
    """

    ANSWERED = "answered"
    NOT_ANSWERABLE = "not_answerable"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class EntityRef:
    kind: Kind
    id: str  # 對該 provider 不透明
    label: str


@dataclass(frozen=True)
class Window:
    offset: int
    limit: int


@dataclass
class WorkItem:
    """統一的作品形狀；只活在 provider 與 pipeline 之間。"""

    number: str
    title: str
    cover_url: str
    date: str
    actors: list[str] | None  # None＝列表沒給（要靠 enrich 補）；[]＝確定沒有
    source: str
    ref: object = None  # provider 內部用（例如 JavDB 的 movie id）


@dataclass
class Page:
    items: list[WorkItem] = field(default_factory=list)
    has_next: bool = False
    total: int | None = None  # 可無（JavDB 列表沒有總數）


@dataclass
class Enriched:
    card: dict | None  # legacy dict；None／空視同該部失敗
    belongs: bool | None = None  # 該片是否屬於 ref；None＝不適用／未知


@dataclass
class WindowResult:
    outcome: Outcome
    cards: list[dict]  # 依視窗內 slot 排序，被丟棄的不在內
    seeded: bool  # 本次呼叫是否已送出 seed（relay 據此決定後續 provider 拿 None）


class Provider(Protocol):
    id: str
    capabilities: frozenset[Kind]
    supports_discovery: bool

    def resolve(self, kind: Kind, name: str) -> EntityRef | None:
        """名字 → 實體；沒有／不是 ⇒ None；連不上 ⇒ raise SourceUnreachable／SourceBlocked。"""
        ...

    def list_entity(self, ref: EntityRef, w: Window) -> Page:
        """實體（含 CODE／PARTIAL 的「實體」）的作品。"""
        ...

    def search_keyword(self, q: str, w: Window) -> Page:
        """標題關鍵字。"""
        ...

    def enrich(self, item: WorkItem, ref: EntityRef | None) -> Enriched:
        """管線掛鉤：把 WorkItem 補成結果卡（legacy dict）＋成員資格事實。"""
        ...


class MakerSearchResult(NamedTuple):
    """片商最新作品的回覆（173）；欄位與順序不可變。"""

    results: list[dict[str, Any]]
    has_more: bool
    error_code: str | None


MAKER_RESOLUTION_ERRORS = {
    "absent": "maker_not_found",
    "unreachable": "maker_unreachable",
    "no_sample": "maker_no_sample",
}
