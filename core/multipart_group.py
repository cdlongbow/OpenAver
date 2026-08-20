"""core/multipart_group.py — 分集影片分組判斷的單一真理來源（feature/122，CD-122-2）。

依賴 `core.organizer`（`MULTIPART_TOKENS` / `_detect_multipart_token` /
`_strip_part_token`，**只 import，不重寫**——那三個原語是檔名組裝用途，本模組反過來
用它們判斷「哪些 DB 列屬於同一組」，兩件事故意不合併，見 CD-122-2）＋ `os.path`
（Zone 1 字串運算，同 `core/cover_layout.py` 先例：呼叫端已把 file:// URI 轉成 fs
path 才傳進來，不在此模組碰 URI，不違反 `path_utils.py` 的跨 Zone 轉換禁止清單）。

**單一真理來源（CD-122-2）**：任何需要判斷「這些 DB 列是不是同一組分集片」的地方
（列表序列化／單筆 refresh／刪除／播放頁接續），一律呼叫本模組的 `group_rows()` /
`resolve_group_for_path()`，不得各自重新推導比對邏輯。

**CD-122-10（Codex plan review 2026-08-20，P0）**：一組成立的條件是「成員數 >= 2
**且**每一個成員都帶 part token」；不成立時，bucket 內每一列各自單飛成單檔組
（`part_tokens=[]`）。反例：`ABC-123.mp4`（無 token）＋ `ABC-123-cd2.mp4` 必須回
兩個單檔組，不可把無 token 的那個當 part-1 併入。

**CD-122-13（Codex PR review 2026-08-20，P0）**：成組條件再加「**每個 part number
必須唯一**」。`ABC-123-cd1.mp4` ＋ `ABC-123-cd1.mkv`（同一片留兩種容器）剝 token 後
stem 相同、兩者都帶 token，只有這條擋得住——那是「同一片的兩個版本」不是「一片的兩段」，
spec §7 明文不做多版本合併。比對用 part **number** 而非 token 字面（`cd1` 與 `pt1`
都是第 1 段，同樣衝突）。

**CD-122-3**：分組比對鍵只在 `normalize_stem_key()` 內做「去除所有空白字元 +
lower()」；回傳給前端的顯示值（`part_tokens` 的 token 字面）不額外正規化。
"""

from dataclasses import dataclass
from typing import Callable, Generic, List, Optional, Tuple, TypeVar
import os
import re

from core.organizer import _detect_multipart_token, _strip_part_token

T = TypeVar('T')  # 呼叫端的 row 型別（Video ORM 物件、或任意帶 path 的物件）


def normalize_stem_key(stem: str) -> str:
    """CD-122-3：剝 token 後的 stem 正規化比對鍵（去空白 + lower）。"""
    stripped = _strip_part_token(stem)
    return re.sub(r'\s+', '', stripped).lower()


def group_key(fs_path: str) -> Tuple[str, str]:
    """(資料夾, 正規化 stem)。

    fs_path 必須是 Zone 1 原生路徑（呼叫端已用 path_utils 轉換過），本函式內只做
    檔名尾端字串運算，不碰 file:// URI。
    """
    folder = os.path.dirname(fs_path)
    stem = os.path.splitext(os.path.basename(fs_path))[0]
    return (folder, normalize_stem_key(stem))


def part_number(fs_path: str) -> int:
    """單檔片（無 token）視為 part 1。"""
    match = _detect_multipart_token(os.path.basename(fs_path))
    return match[1] if match else 1


def part_token(fs_path: str) -> Optional[str]:
    """回傳原始 token 字面（已是小寫，如 'cd1'），無 token 回 None。"""
    match = _detect_multipart_token(os.path.basename(fs_path))
    return match[0] if match else None


@dataclass
class VideoGroup(Generic[T]):
    """一組分集片（或單檔片）。

    members: 依 part_number 升冪排序，長度 >= 1；members[0] 恆為 part-1
             （單檔片時就是它自己）。
    part_tokens: 對應 members 的 token 字面（如 ['cd1', 'cd2']）；單檔片為 []。
    """
    members: List[T]
    part_tokens: List[str]


def group_rows(rows: List[T], fs_path_of: Callable[[T], str]) -> List['VideoGroup[T]']:
    """把 rows 依「同資料夾 + 剝 token 後正規化 stem 相同」分桶，再依 CD-122-10 判定
    每個桶是否成組。

    Args:
        rows: 任意物件列表（Video ORM 或 dict-like），只要求可用 fs_path_of(row)
            取得 Zone 1 fs path。
        fs_path_of: Callable[[T], str] — 呼叫端負責把 row 換成 Zone 1 fs path
            （showcase.py 用 `uri_to_local_fs_path(v.path, path_mappings)`）。

    Returns:
        groups，組內 members 依 part_number 升冪排列；組間順序＝第一次見到該 key
        的順序（呼叫端若要整體排序，序列化前再排 videos 陣列，不影響分組正確性）。
    """
    buckets: dict = {}
    order: List[Tuple[str, str]] = []
    for row in rows:
        fs_path = fs_path_of(row)
        key = group_key(fs_path)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)

    groups: List[VideoGroup] = []
    for key in order:
        members = buckets[key]
        tokens = [part_token(fs_path_of(r)) for r in members]

        # CD-122-10（P0）：一組成立的條件是「成員 >= 2 且每一個成員都帶 part token」。
        # 不成立 → bucket 內每一列各自單飛成單檔組。少了這條，
        # `ABC-123.mp4`（無 token）＋ `ABC-123-cd2.mp4` 會被誤併，無 token 那個
        # 被當 part-1、part_tokens 出現 None，且刪除會一次移除兩列。
        #
        # CD-122-13（Codex PR review P0，2026-08-20）：**再加「每個 part number 必須唯一」**。
        # 少了這條，`ABC-123-cd1.mp4` ＋ `ABC-123-cd1.mkv`（同一片留兩種容器，收藏者常見
        # 的「原檔 ＋ 相容版」擺法）會被誤併成「同一片的兩段」：剝 token 後 stem 相同、
        # 兩者都帶 token，現行條件擋不住。後果是另一個容器版本從瀏覽頁消失、播放頁把同一段
        # 連播兩次，而刪除那張卡會一次移除兩列 DB——`user_tags` 還能靠 NFO 重掃回來，
        # 但**手動封面裁切座標（auto_focal / crop_mode）只存在 DB、不進 NFO**，
        # 使用者得重新框一次。
        # 比對用 part **number** 而非 token 字面：`cd1` 與 `pt1` 字面不同但都是第 1 段，
        # 同樣是衝突（這條順手把 Codex 沒點名的同款漏洞一起堵掉）。
        part_numbers = [part_number(fs_path_of(r)) for r in members]
        if (len(members) < 2
                or not all(tokens)
                or len(set(part_numbers)) != len(part_numbers)):
            for row in members:
                groups.append(VideoGroup(members=[row], part_tokens=[]))
            continue

        order_pairs = sorted(
            zip(members, tokens, strict=True),
            key=lambda mt: part_number(fs_path_of(mt[0])),
        )
        groups.append(VideoGroup(
            members=[m for m, _ in order_pairs],
            part_tokens=[t for _, t in order_pairs],
        ))
    return groups


def resolve_group_for_path(
    target_uri: str,
    candidates: List[T],
    fs_path_of: Callable[[T], str],
    uri_of: Callable[[T], str],
) -> Optional['VideoGroup[T]']:
    """在 candidates 裡找出包含 target_uri 的組；找不到回 None（不拋例外）。

    **兩個取值函式的分工是定死的，不得合併成一個**：
      - `fs_path_of(row)` → Zone 1 原生 fs 路徑，**只**餵給 `group_key()`（分組運算）
      - `uri_of(row)`     → DB key 的 file:/// URI，**只**用來與 target_uri 比對身分

    Why 分兩個：分組必須在 fs path 上做（`group_key` 是檔名尾端字串運算，且
    `path_utils.py` 禁止在別處手搓 URI）；而呼叫端握有的、前端送上來的是 DB key
    URI。用同一個函式兼差會逼出「到底該傳哪一種」的二義性。
    """
    for group in group_rows(candidates, fs_path_of):
        if any(uri_of(m) == target_uri for m in group.members):
            return group
    return None
