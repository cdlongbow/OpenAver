"""
web.routers.wishlist — 書籤路由（TASK-140-T4）。

七個端點連接 WishlistRepository、wishlist_cover_cache 與 VideoRepository。
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
    return {"success": True, "cover_available": cover_available}


@router.get("")
def list_wishlist() -> list:
    init_db()
    repo = WishlistRepository()
    items = repo.list_all()
    numbers = [item["number"] for item in items]
    video_repo = VideoRepository()
    owned = video_repo.get_by_numbers(numbers)
    for item in items:
        item["_owned"] = bool(owned.get(item["number"]))
    unowned = [item for item in items if not item["_owned"]]
    owned_items = [item for item in items if item["_owned"]]
    return unowned + owned_items


@router.delete("/{number}")
def delete_wishlist(number: str) -> dict:
    init_db()
    repo = WishlistRepository()
    removed = repo.remove(number)
    if removed:
        wishlist_cover_cache.remove(number)
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


@router.post("/cleanup")
def cleanup_wishlist() -> dict:
    init_db()
    repo = WishlistRepository()
    items = repo.list_all()
    numbers = [item["number"] for item in items]
    owned = VideoRepository().get_by_numbers(numbers)
    owned_numbers = [n for n in numbers if owned.get(n)]
    # 🔴 順序：**先刪 DB，成功了才刪封面**（Codex review P3），與單筆刪除端點
    # `delete_wishlist()` 同形。反過來（先刪封面）的話，`delete_many()` 若拋例外
    # （DB 鎖住／磁碟滿），使用者會看到「書籤列還在、封面全沒了」的破圖清單——
    # 那不在 spec §5 已接受的殘留裡；spec 接受的是**反方向**：DB 刪掉了、檔案沒刪掉
    # 而留下孤兒 webp（單人本機、幾十 KB 一張，不做 GC）。
    deleted_count = repo.delete_many(owned_numbers)
    if deleted_count:
        for n in owned_numbers:
            wishlist_cover_cache.remove(n)
    return {"deleted_count": deleted_count}


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
