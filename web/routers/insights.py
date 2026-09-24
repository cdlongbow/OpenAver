"""
Insights API 路由 — 片庫分析快照端點

端點：
- GET /api/insights/snapshot — 聚合所需的最小逐部影片欄位＋收藏女優表（CD-156-1）
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from core.database import (
    VideoRepository,
    ActressRepository,
    AliasRepository,
    TagAliasRepository,
    get_db_path,
    init_db,
)
from core.database.version_tracker import (
    compute_db_fingerprint,
    compute_etag,
    get_showcase_revision,
)
from core.path_utils import is_path_under_dir, uri_to_local_fs_path
from core.logger import get_logger
from core.config import (
    load_config,
    get_gallery_source_paths,
    get_configured_gallery_dirs,
)
from core.multipart_group import group_rows

logger = get_logger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])

_RELEASE_RE = re.compile(r"^(19\d{2}|20\d{2}|21\d{2})(?:-(\d{2})(?:-(\d{2}))?)?")


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """比對 `If-None-Match` 語意（同 showcase.py）。"""
    if not if_none_match:
        return False
    return etag in [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]


def _release_parts(raw: object) -> tuple[int | None, str | None, str | None]:
    """從 release_date 抽出 (year, month='YYYY-MM', date='YYYY-MM-DD')。"""
    match = _RELEASE_RE.match(str(raw or "").strip())
    if not match:
        return None, None, None
    year = int(match.group(1))
    month_num = match.group(2)
    day_num = match.group(3)
    month = None
    if month_num and 1 <= int(month_num) <= 12:
        month = f"{year}-{month_num}"
    date = None
    if month and day_num and 1 <= int(day_num) <= 31:
        date = f"{year}-{month_num}-{day_num}"
    return year, month, date


def _build_alias_lookup(records) -> dict[str, tuple[str, list[str]]]:
    """name -> (primary_name, names_list)；names_list = [primary] + aliases。"""
    lookup: dict[str, tuple[str, list[str]]] = {}
    for record in records:
        primary = str(record.primary_name or "").strip()
        if not primary:
            continue
        aliases = [
            str(a).strip() for a in (record.aliases or []) if str(a).strip()
        ]
        names_list = [primary, *aliases]
        pair = (primary, names_list)
        lookup[primary] = pair
        for alias in aliases:
            lookup[alias] = pair
    return lookup


def _canonical_list(values, lookup: dict[str, tuple[str, list[str]]]) -> list[str]:
    """別名合併後去重，保留首次出現的 primary 順序。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        name = str(raw).strip()
        if not name:
            continue
        primary, _ = lookup.get(name, (name, [name]))
        if primary in seen:
            continue
        seen.add(primary)
        result.append(primary)
    return result


def _serialize_record(v, actress_lookup, tag_lookup) -> dict:
    year, month, date = _release_parts(v.release_date)
    return {
        "year": year,
        "month": month,
        "date": date,
        "duration": v.duration,
        "actresses": _canonical_list(v.actresses, actress_lookup),
        "maker": (str(v.maker).strip() or None) if v.maker else None,
        "director": (str(v.director).strip() or None) if v.director else None,
        "series": (str(v.series).strip() or None) if v.series else None,
        "tags": _canonical_list(v.tags, tag_lookup),
    }


@router.get("/snapshot")
def get_insights_snapshot(request: Request):
    """取得片庫分析快照（聚合在瀏覽器；本端點只出匿名最小欄位，CD-156-1）。"""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return JSONResponse({
                "success": True,
                "logicalTitles": 0,
                "physicalRows": 0,
                "years": [],
                "records": [],
                "actressFavorites": {},
            })

        init_db(db_path)

        config = load_config()
        gallery_config = config.get("gallery", {})
        configured_dir_uris, path_mappings = get_configured_gallery_dirs(config)

        projection = {
            "directories": sorted(get_gallery_source_paths(gallery_config)),
            "path_mappings": path_mappings,
        }
        etag = compute_etag(
            get_showcase_revision(), compute_db_fingerprint(db_path), projection
        )

        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(
                status_code=304,
                headers={"ETag": etag, "Cache-Control": "no-cache"},
            )

        repo = VideoRepository(db_path)
        all_videos = [v for v in repo.get_all() if any(is_path_under_dir(v.path, uri) for uri in configured_dir_uris)]

        groups = group_rows(
            all_videos,
            fs_path_of=lambda v: uri_to_local_fs_path(v.path, path_mappings),
        )

        actress_lookup = _build_alias_lookup(AliasRepository(db_path).get_all())
        tag_lookup = _build_alias_lookup(TagAliasRepository(db_path).get_all())

        records = [
            _serialize_record(g.members[0], actress_lookup, tag_lookup)
            for g in groups
        ]
        years = sorted({r["year"] for r in records if r["year"] is not None})

        favorites_by_primary: dict[str, dict] = {}
        for a in ActressRepository(db_path).get_all():          # 已是 ORDER BY name
            if not a.birth:
                continue
            primary, _ = actress_lookup.get(a.name, (a.name, [a.name]))
            if primary in favorites_by_primary:            # 同組已有更早（字母序更前）的收藏命中，跳過
                continue
            favorites_by_primary[primary] = {
                "birth": a.birth,
                "photoName": a.name,
                "auto_focal": a.auto_focal,
                "crop_mode": a.crop_mode,
            }

        resp = JSONResponse({
            "success": True,
            "logicalTitles": len(records),
            "physicalRows": len(all_videos),
            "years": years,
            "records": records,
            "actressFavorites": favorites_by_primary,
        })
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    except Exception as e:
        logger.error("取得片庫分析快照失敗: %s", e)
        return JSONResponse({
            "success": False,
            "error": "取得片庫分析快照失敗",
        }, status_code=500)
