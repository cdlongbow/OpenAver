"""pre-merge SA-pre-9 P2：掃描頁「補完 NFO 欄位」不得寫回唯讀來源資料夾。

使用者流程：使用者有一個 MDCX／Jellyfin 整理過的唯讀來源（每部片旁邊都有 `.nfo`）
→ 唯讀入庫後某些欄位不齊 → 在掃描頁按「補完 NFO 欄位」→ 過去 OpenAver 會把
**來源資料夾**那份 `.nfo` 整份重新序列化寫回去（`update_videos_generator` 走的是
`get_nfo_path_from_video` ＝ 影片路徑 `.with_suffix('.nfo')`）→ 使用者叫它別碰的
資料夾被改了，原本手工整理的內容回不來。

唯讀列的 `nfo_mtime` 指的是**輸出夾**那份的 mtime、恆 > 0，所以不主動濾掉就一定會
入選 `check_cache_needs_update` —— 這是 spec-143 不變式（唯讀 ＝ 一般掃描 ＋ 產物落
輸出夾）在盤點時漏掉的第五格。

本檔鎖的是 `_build_nfo_update_cache`：`/api/gallery/update-check`（顯示數字）與
`/api/gallery/update`（真的寫檔）**共用同一個 helper**，兩邊各抄一份判定必然漂移，
而漂移的形狀是「按鈕說要更新 N 部、實際只更新 M 部」。
"""
from core.database import Video
from core.path_utils import to_file_uri
from web.routers.scanner import _build_nfo_update_cache

RO_DIR = "/srv/media/readonly-lib"
RW_DIR = "/srv/media/my-lib"


def _config(sources):
    return {"gallery": {"directories": sources, "path_mappings": {}}}


def _video(fs_path, number="ABC-123"):
    """一列「一定會入選」的影片：nfo_mtime > 0 ＋ 有番號 ＋ 欄位不齊（無 actor/genre）。

    path 一律用 to_file_uri() 建，**不可手寫 `file:///` 字面**——POSIX 絕對路徑在本專案
    是四斜線形式（`file:////srv/...`），手寫三斜線會讓前綴比對永遠不命中、測試假綠。
    """
    return Video(
        path=to_file_uri(fs_path, {}),  # db-ns-ok: 測試資料建構，非 DB-key 寫入路徑
        number=number,
        title="t",
        nfo_mtime=1234.0,
    )


class TestNfoUpdateSkipsReadonlySources:
    def test_readonly_row_excluded_writable_row_kept(self):
        cache, skipped, _ = _build_nfo_update_cache(
            [_video(f"{RO_DIR}/A/A.mp4"), _video(f"{RW_DIR}/B/B.mp4")],
            _config([
                {"path": RO_DIR, "readonly": True, "output_path": "/out"},
                {"path": RW_DIR, "readonly": False},
            ]),
        )

        assert skipped == 1
        assert list(cache) == [to_file_uri(f"{RW_DIR}/B/B.mp4", {})]  # db-ns-ok: 斷言期望值


