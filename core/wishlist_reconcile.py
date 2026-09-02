"""書籤與片庫對帳（feature/141 T2）。

唯一的對帳函式 reconcile_wishlist()：算出片庫已有的書籤 → 刪列 ＋ 刪封面
→ 回傳被移除的番號快照。不發通知——通知是呼叫端（T4／T5）的事。

設計約束：
- 屬 core/ 層，不 import web（BE-LINT-01／import-linter）。
- 「被移除」＝呼叫 delete_many 之前的快照，不是 rowcount 子集（spec §5 residual #8）。
- videos 表零寫入（CD-3）。
"""
from __future__ import annotations

from core import wishlist_cover_cache
from core.database import VideoRepository, WishlistRepository


def reconcile_wishlist() -> list[str]:
    """對帳：刪除片庫已有的書籤列＋封面快取，回傳「被移除」的番號清單。

    「被移除」＝對帳當下判定為已入手的番號（呼叫 delete_many 之前的快照），
    不是 delete_many 實際 rowcount 命中的子集——兩者理論上可能不同（見 spec §5
    residual #8：兩個分頁同時對帳，其中一個先刪，另一個的 delete_many 對已刪的
    number 是 no-op 但不報錯）。刻意用前者，讓通知即使在該競態下仍然如實反映
    「這次判定出哪些已入手」，不因為誰先誰後而少報。
    """
    wishlist_repo = WishlistRepository()
    items = wishlist_repo.list_all()
    numbers = [item["number"] for item in items]
    if not numbers:
        return []

    video_repo = VideoRepository()
    owned = video_repo.get_by_numbers(numbers)
    owned_numbers = [n for n in numbers if owned.get(n)]
    if not owned_numbers:
        return []

    wishlist_repo.delete_many(owned_numbers)
    for n in owned_numbers:
        wishlist_cover_cache.remove_best_effort(n)
    return owned_numbers


def format_wishlist_removed_message(numbers: list[str]) -> str:
    """組裝對帳移除通知文案（CD-6／plan §六 141a-2）。

    句型：``{total} 部片已入庫，已從書籤移除：{前 5 個以「、」相連}``；
    剩餘數 > 0 時句尾接 ``，及其他 {rest} 部``。呼叫端保證 numbers 非空。
    """
    total = len(numbers)
    shown = numbers[:5]
    rest = total - len(shown)
    msg = f"{total} 部片已入庫，已從書籤移除：{'、'.join(shown)}"
    if rest > 0:
        msg += f"，及其他 {rest} 部"
    return msg
