"""atomic_write.py — 共用、無狀態的原子寫檔 primitive（CD-113d-1/2）。

收斂 core.config / core.thumbnail_cache / web.routers.actress 三處各自手寫的
「同目錄 mkstemp → 拿到開著的 fh → 關 fd → os.replace → 例外時清 temp」骨架。
只做這一件事：鎖策略、成功後清舊 sibling 檔、失敗語意（拋例外 vs 回 False）、
dest 在哪，全部留給呼叫端決定（spec §2.5 / D-8）。
"""
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, Optional, Union
import os          # 🔴 必須是屬性存取形式：禁 `from os import replace`
import tempfile    # 🔴 同上：禁 `from tempfile import mkstemp`


@contextmanager
def atomic_write(
    dest: Union[Path, str],
    *,
    mode: str = "wb",
    encoding: Optional[str] = None,
    suffix: str = ".tmp",
) -> Iterator[IO]:
    """Yield an open file handle whose content lands at `dest` atomically.

    Mechanics (the part every caller must share): create the temp file in
    `dest.parent` via `tempfile.mkstemp` — same directory means same volume,
    without which `os.replace` fails with `EXDEV` — hand the caller the open
    handle, close the fd, then `os.replace(tmp, dest)`. The fd is closed
    *before* the replace because Windows refuses to replace a file that is
    still open (`BE-ENV-01`).

    Two failure paths, both handled identically: the caller's block raises
    while writing, or `os.replace` itself fails (on Windows it is not
    guaranteed to succeed — antivirus and the thumbnail cache hold handles).
    Either way the temp file is removed, `dest` is left **byte-for-byte
    untouched**, and the original exception propagates unchanged.

    `dest.parent` must already exist — creating it is the caller's business,
    because whether a missing directory is an error or a routine first write
    differs per caller. `suffix` reaches `mkstemp` verbatim; pass the real
    extension when something downstream sniffs the temp name.

    Deliberately NOT here (spec-113 §2.5 — each stays with the caller):
    locking, deleting old sibling files after a successful write, turning
    failures into a `False` return, and deciding where `dest` is.
    """
    dest = Path(dest)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=suffix)
    tmp = Path(tmp)
    try:
        with os.fdopen(fd, mode, encoding=encoding) as f:
            yield f
        # fd 已由上面的 with 關閉 → 安全 replace（Windows file-lock 前提）
        os.replace(tmp, dest)
    except Exception:
        # 路徑 1：區塊內使用者程式碼拋例外；路徑 2：os.replace 自己拋例外
        # （BE-ENV-01：Windows 防毒/縮圖快取會擋，不是必成功）。
        # 兩條路徑都落在這個 except，行為一致：清 temp、不動 dest、原例外往上傳。
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
