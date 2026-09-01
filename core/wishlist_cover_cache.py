"""書籤封面快取（feature/140 T3，純函式模組）。

以正規化番號為 key、扁平 hash 分桶（wishlist_cover/<h[:2]>/<h>.webp）、
原子寫的本地封面快取。仿 core.thumbnail_cache 的形狀。

設計約束：
- 純函式，無 class。
- 不 import web、不 import config（保持 core 不反向依賴）。
- 下載失敗（網路例外 / 非 200 / 內容過小）→ logger.warning 後回 False，不拋例外（I2）。
- 不走 actress_photo SSRF 白名單（JAV host 會被 fail-closed）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import requests

from core.atomic_write import atomic_write
from core.database import get_db_path
from core.logger import get_logger
from core.scraper import normalize_number

logger = get_logger(__name__)


def cover_file_for(number: str) -> Path:
    """以正規化番號推導封面檔路徑（純路徑推導，無 I/O）。

    h = sha1(normalize_number(number)).hexdigest()；
    回 wishlist_cover/<h[:2]>/<h>.webp。呼叫端不得假設本函式會建目錄。
    """
    h = hashlib.sha1(normalize_number(number).encode("utf-8")).hexdigest()
    return get_db_path().parent / "wishlist_cover" / h[:2] / f"{h}.webp"


def _fetch_image_bytes(url: str, timeout: float = 30) -> bytes | None:
    """下載封面 bytes；失敗回 None（不拋）。"""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        logger.warning("wishlist cover fetch failed: url=%s", url)
        return None
    if resp.status_code == 200 and len(resp.content) > 1000:
        return resp.content
    return None


def download_and_save(number: str, cover_url: str, fallback_url: str = "") -> bool:
    """下載封面並原子寫到 cover_file_for(number)。

    先試 cover_url，拿不到且 fallback_url 非空再試 fallback。
    兩個 URL 都失敗 → logger.warning 後回 False（不拋，I2）。
    """
    data = _fetch_image_bytes(cover_url)
    if data is None and fallback_url:
        data = _fetch_image_bytes(fallback_url)
    if data is None:
        logger.warning(
            "wishlist cover download failed: number=%s cover_url=%s fallback_url=%s",
            number,
            cover_url,
            fallback_url,
        )
        return False

    dest = cover_file_for(number)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(dest) as f:
        f.write(data)
    return True


def remove(number: str) -> None:
    """刪掉某番號的封面檔（缺檔 no-op，不拋）。"""
    cover_file_for(number).unlink(missing_ok=True)
