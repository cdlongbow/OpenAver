"""
web.routers.wishlist — 書籤路由（TASK-140-T4）。

六個端點連接 WishlistRepository、wishlist_cover_cache 與 VideoRepository。
一律使用同步 def，FastAPI 自動交由 threadpool 處理。
"""
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from core import wishlist_cover_cache
from core.database import VideoRepository, WishlistRepository, get_db_path as get_db_path, init_db
from core.logger import get_logger
from core.scraper import normalize_number
from core.wishlist_reconcile import reconcile_wishlist, format_wishlist_removed_message
from web.routers.notifications import emit_notification as _emit_notif

logger = get_logger(__name__)

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"])


class WishlistAddRequest(BaseModel):
    number: str
    title: str = ""
    actors: List[str] = []
    tags: List[str] = []
    maker: str = ""
    director: str = ""
    series: str = ""
    label: str = ""
    duration: Optional[int] = None
    date: str = ""
    cover: str = ""
    preview_cover_url: str = ""
    sample_images: List[str] = []
    preview_sample_images: List[str] = []
    source: str = ""
    url: str = ""


class WishlistMembershipRequest(BaseModel):
    numbers: List[str]


@router.post("")
def add_wishlist(req: WishlistAddRequest) -> dict:
    init_db()
    number = normalize_number(req.number)

    video_repo = VideoRepository()
    owned = video_repo.get_by_numbers([number])
    videos = owned.get(number)
    if videos:
        return {
            "success": False,
            "already_owned": True,
            "local_status": {
                "exists": True,
                "count": len(videos),
                "paths": [v.path for v in videos],
            },
        }

    repo = WishlistRepository()
    added = repo.add(
        number,
        title=req.title,
        actresses=req.actors,
        tags=req.tags,
        maker=req.maker,
        director=req.director,
        series=req.series,
        label=req.label,
        duration=req.duration,
        release_date=req.date,
        cover_path=str(wishlist_cover_cache.cover_file_for(number)),
        sample_images=req.sample_images,
        preview_sample_images=req.preview_sample_images,
        source=req.source,
        source_url=req.url,
    )
    cover_available = False
    if added:
        primary_url = req.preview_cover_url or req.cover
        if primary_url:
            try:
                cover_available = wishlist_cover_cache.download_and_save(number, primary_url, req.cover)
            except Exception:
                logger.warning("wishlist cover 下載/寫檔失敗: number=%s", number, exc_info=True)
                cover_available = False
    else:
        cover_available = wishlist_cover_cache.cover_file_for(number).exists()
    # 🔴 branch review P2-1（2026-09-02）：多回一個 `added`。`success` 維持 True
    # （加入書籤是冪等的，重複加入不是錯誤——既有契約由
    # `test_add_wishlist_duplicate_number` 釘住，不改），但前端需要分辨「真的多了一筆」
    # 與「本來就有」，否則樂觀 +1 永遠補不回來：切換版本會把整顆結果物件換掉
    # （state-rescrape.js 的 `t.arr[t.idx] = variant`），連帶清掉 `_wishlisted`，卡片
    # 於是變回「加入書籤」，再按一次就重複 +1。與 DELETE 端點回 `success: removed`
    # 是同一組對稱資訊，那一半已經有了。
    return {"success": True, "added": added, "cover_available": cover_available}


@router.get("")
def list_wishlist() -> list:
    init_db()
    removed = reconcile_wishlist()
    if removed:
        _emit_notif(
            "info",
            "notif.wishlist_auto_removed",
            message=format_wishlist_removed_message(removed),
            task_type="wishlist_reconcile",
        )
    return WishlistRepository().list_all()


@router.delete("/{number}")
def delete_wishlist(number: str) -> dict:
    init_db()
    repo = WishlistRepository()
    removed = repo.remove(number)
    if removed:
        wishlist_cover_cache.remove_best_effort(number)
    return {"success": removed}


@router.get("/count")
def wishlist_count() -> dict:
    init_db()
    return {"count": WishlistRepository().count()}


@router.post("/membership")
def wishlist_membership(req: WishlistMembershipRequest) -> dict:
    init_db()
    stored = {item["number"] for item in WishlistRepository().list_all()}
    return {raw: normalize_number(raw) in stored for raw in req.numbers}


@router.get("/cover")
def get_wishlist_cover(number: str = Query(..., description="番號")):
    cover_file = wishlist_cover_cache.cover_file_for(number)
    if not cover_file.exists():
        return Response(status_code=404)
    try:
        data = cover_file.read_bytes()
    except OSError:
        return Response(status_code=404)
    return Response(content=data, media_type="image/webp", headers={"Cache-Control": "no-cache"})
