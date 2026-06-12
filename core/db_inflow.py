"""
DB In-flow Upsert Helper

Search 頁整理完成後，條件式將影片寫入 DB（in-flow upsert）。
僅在檔案路徑落在 Scanner 追蹤目錄範圍內時執行。
"""
from __future__ import annotations

from core.config import load_config
from core.database import Video, VideoRepository
from core.gallery_scanner import VideoScanner
from core.logger import get_logger
from core.path_utils import to_file_uri
from core.settings_link import find_matched_directory

logger = get_logger(__name__)


def try_inflow_upsert(target_file_path: str, old_file_path: str | None = None) -> str:
    """
    條件式 in-flow upsert（B1 擴充版）。

    Args:
        target_file_path: 整理後影片的完整 FS 路徑字串（非 file:// URI）
        old_file_path: 整理前原始 FS 路徑（optional）；提供時觸發 repath 邏輯，
                       讓 DB 中舊路徑那筆原地 UPDATE 為新路徑，保留 id/created_at/user_tags。

    Returns:
        "synced"     — 成功寫入 DB
        "not_linked" — 不在 Scanner directories 範圍內（靜默 skip）
        "failed"     — 發生例外 / scan-fail 保卡（整理本身不受影響）
    """
    try:
        config = load_config()
        gallery_cfg = config.get("gallery", {})
        directories: list = gallery_cfg.get("directories", [])
        path_mappings: dict | None = gallery_cfg.get("path_mappings") or None

        # 步驟 2.5：算 old_uri（禁止手拼 file:///，依 CLAUDE.md 路徑規則）
        # to_file_uri 內部已處理 Windows/WSL/Linux 各路徑格式，不可再套 normalize_path
        # （guard: test_no_normalize_before_to_file_uri 禁止此疊加模式）
        old_uri: str | None = None
        if old_file_path:
            old_uri = to_file_uri(old_file_path, path_mappings)

        # 步驟 1：確認檔案在 Scanner 追蹤範圍內
        matched = find_matched_directory(target_file_path, directories, path_mappings)
        if matched is None:
            logger.debug(
                "try_inflow_upsert: %r 不在任何 Scanner directory，skip",
                target_file_path,
            )
            return "not_linked"

        # 步驟 2：掃描影片資訊（傳 path_mappings → canonical path 與 Scanner 一致）
        scanner = VideoScanner(path_mappings=path_mappings)
        video_info = scanner.scan_file(target_file_path)

        if not video_info:
            logger.debug(
                "try_inflow_upsert: scan_file 回空值，%r",
                target_file_path,
            )
            # scan-fail 保卡（B1 finding #2）：
            # 若舊 row 存在，UPDATE-path-only 保住卡（保留舊 metadata），回 "failed"。
            # 若無舊 row，沿用既有 "not_linked" 行為。
            if old_uri:
                repo = VideoRepository()
                if repo.get_by_path(old_uri):
                    new_uri_fallback = to_file_uri(target_file_path, path_mappings)
                    repo.repath_path_only(old_uri, new_uri_fallback)
                    logger.info(
                        "try_inflow_upsert: scan-fail 保卡 — 舊路徑 %r → %r",
                        old_uri,
                        new_uri_fallback,
                    )
                    return "failed"
            return "not_linked"

        # 步驟 3：repath（含 upsert 降級）
        repo = VideoRepository()
        video = Video.from_video_info(video_info)
        new_uri = video.path  # scan_file 寫入 Video.path 即 canonical new_uri
        repo.repath(old_uri, new_uri, video)

        logger.info(
            "try_inflow_upsert: %r 已寫入 DB（matched dir=%r, old_uri=%r）",
            target_file_path,
            matched,
            old_uri,
        )
        return "synced"

    except Exception:
        logger.exception(
            "try_inflow_upsert: %r 發生例外，DB 寫入失敗（整理結果不受影響）",
            target_file_path,
        )
        return "failed"
