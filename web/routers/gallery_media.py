"""
Gallery media 路由 - 圖片／影片代理服務（TASK-150a-T1 自 web/routers/scanner.py 搬出）

端點：
- GET  /api/gallery/image                 — 代理圖片請求（解決 file:// 限制）
- GET  /api/gallery/video                 — 代理影片請求，支援 Range 請求（影片 seek）
"""

import os
import time
from typing import List
from urllib.parse import unquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, FileResponse, StreamingResponse

from core.path_utils import to_file_uri, is_path_under_dir, uri_to_fs_path, uri_to_local_fs_path
from core.config import load_config, iter_gallery_sources, get_gallery_source_paths
from core.video_extensions import get_proxy_extensions
from core.readonly_producer import resolve_output_root
from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/gallery", tags=["gallery"])

# TASK-73: 白名單目錄 dual-form TTL 快取（key: (raw_dir, frozen_mappings), value: (forms, expire_monotonic)）
_dir_forms_cache: dict = {}
_DIR_FORMS_TTL = 60.0  # 秒


def safe_realpath(fs_path: str, endpoint_label: str) -> str:
    """TASK-73: realpath-or-normpath helper。
    回傳 FS path（str）：realpath 成功則用 realpath 結果，OSError（FUSE/WinFsp）則降級 normpath。
    只回傳 FS path，不回傳 URI；realpath 只跑一次（serving + 白名單比對共用）。
    """
    try:
        return os.path.realpath(fs_path)
    except OSError as e:
        logger.warning(
            "%s: realpath 失敗（FUSE/WinFsp？），降級為 normpath path=%s err=%s",
            endpoint_label, fs_path, e,
        )
        return os.path.normpath(fs_path)


def _dir_candidate_forms(raw_dir: str, path_mappings: dict) -> tuple:
    """TASK-73: 回傳白名單目錄的候選 file:/// URI tuple（1 或 2 個，已 dedup）。
    normpath_form 永遠存在；realpath_form 在 realpath 成功時加入。
    cache-on-success-only：realpath OSError 時不寫快取（避免 NAS 重連後 false-403 窗口）。
    並發安全：dict 賦值原子，無需鎖（冪等計算）。
    """
    cache_key = (raw_dir, frozenset(path_mappings.items()) if path_mappings else frozenset())
    now = time.monotonic()
    cached = _dir_forms_cache.get(cache_key)
    if cached is not None:
        forms, expire = cached
        if now < expire:
            return forms

    # raw_dir 可能是 FS 路徑或 file:/// URI（DirectoryConfig.path schema：「FS 路徑或
    # URI」）。先過 uri_to_fs_path 統一成 FS 路徑（URI→FS，FS→FS 冪等，path-contract
    # 合規，不手刻 startswith('file:///')）。否則對 URI 直接 os.path.normpath/realpath
    # 會把 file:/// 折成 file:/ 再被 to_file_uri 二次包成 file:///file:/…，image/video
    # 兩條白名單同時誤殺（PR#91 P2-D 同源）。FS 輸入行為不變 → 保留 dual-form + TASK-73
    # 跨格式 casefold。
    fs_dir = uri_to_fs_path(raw_dir)  # uri-no-reverse: native config path (DirectoryConfig.path), no DB-mapped namespace
    normpath_form = to_file_uri(os.path.normpath(fs_dir), path_mappings)
    try:
        realpath_form = to_file_uri(os.path.realpath(fs_dir), path_mappings)
        forms = tuple(dict.fromkeys([normpath_form, realpath_form]))
        # cache-on-success-only
        _dir_forms_cache[cache_key] = (forms, now + _DIR_FORMS_TTL)
    except OSError:
        # FUSE/WinFsp: normpath fallback — 不寫快取，確保 NAS 重連後立即重算
        forms = (normpath_form,)
    return forms


def _image_whitelist_dirs(config: dict) -> List[str]:
    """TASK-88c-T1 / TASK-89a-T2: /api/gallery/image 白名單的候選 raw 目錄清單。

    每個來源 emit `src.path`，並在 `resolve_output_root(src, config)`（CD-89a-7）
    非空時一併 emit——off 風味回傳固定 `output/lib/<name>` 根（讓唯讀 + off 風味
    生成的封面/劇照能經 image proxy 服務，Codex #1 回歸鎖：只改 producer 不改
    白名單會讓 off 封面 404）；jellyfin/emby/kodi 沿用 `source.output_path` 原值。

    純函式、無 IO（`resolve_output_root` 本身無 IO）。空字串仍被過濾——不讓空
    字串進 `_dir_candidate_forms`（避免 `to_file_uri('') = 'file:///'` 根路徑
    把整顆磁碟放進白名單，CWE-allowlist bypass）。get_video 不共用此 helper
    （獨立 call site，spec P1a）。
    """
    gallery_config = config.get('gallery', {})
    dirs: List[str] = []
    for src in iter_gallery_sources(gallery_config):
        dirs.append(src.path)
        resolved = resolve_output_root(src, config)
        if resolved:
            dirs.append(resolved)
    return dirs


@router.get("/image")
def get_image(path: str = Query(..., description="圖片路徑")):
    """代理圖片請求，解決 file:// 在 iframe 中無法載入的問題"""
    from urllib.parse import unquote
    from core.path_utils import normalize_path

    # URL decode
    path = unquote(path)

    # 使用 path_utils 統一處理路徑轉換
    try:
        local_path = normalize_path(path)
    except ValueError:
        local_path = path  # 無法轉換時使用原路徑

    # 0. 字面式早退（PR#178 R2 缺陷C）：在任何 realpath 之前，用純字面（lexical）URI
    # 判斷來源是否已知斷線。safe_realpath 與 _dir_candidate_forms 都會對位在斷線來源上
    # 的路徑呼叫 os.path.realpath()（跑在 sync def 的 threadpool worker），滿頁封面請求
    # 會在走到下方既有 fast-fail 之前就先一張一張卡在遠端逾時——這裡把判斷挪到任何遠端
    # IO 之前，不呼叫 realpath / safe_realpath / _dir_candidate_forms / os.path.exists。
    # config/gallery_config/path_mappings 從原本「3. 目錄白名單」段落整段上移到這裡
    # （不多呼叫一次 load_config()，下方該段落改用這裡算好的變數）。
    config = load_config()
    gallery_config = config.get('gallery', {})
    path_mappings = gallery_config.get('path_mappings', {})

    from core.source_reachability import is_path_on_unreachable_source
    lexical_uri = to_file_uri(os.path.normpath(local_path), path_mappings)
    if is_path_on_unreachable_source(lexical_uri, gallery_config):
        return Response(status_code=404, content="來源目前無法存取")

    # 1. 解析 .. 並追蹤 symlink target（realpath）；FUSE/WinFsp OSError 時降級 normpath
    local_path = safe_realpath(local_path, "get_image")

    # 2. 副檔名白名單（只允許圖片格式）
    ext = os.path.splitext(local_path)[1].lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.tbn': 'image/jpeg',  # Kodi ecosystem: JPEG with a .tbn suffix
    }
    if ext not in mime_types:
        logger.warning("get_image: 拒絕非圖片副檔名請求 ext=%s", ext)
        return Response(status_code=403, content="不允許的檔案類型")

    # 3. 目錄白名單：只允許 gallery.directories 底下的檔案
    # config / gallery_config / path_mappings 已於上方「0. 字面式早退」段落算好（不重複
    # 呼叫 load_config()）。

    # TASK-73: 兩端對稱正規化 — request_uri 用 single-form（realpath已做）；
    # dir 端用 dual-form（normpath + realpath 候選），避免 SMB mapped drive 格式不同 403 誤殺
    request_uri = to_file_uri(local_path, path_mappings)
    # TASK-88c-T1: 白名單納入各來源非空 output_path（唯讀 off 風味封面服務）；
    # 複用 _dir_candidate_forms dual-form，不另寫 single-form 比對
    allowed = any(
        is_path_under_dir(request_uri, form)
        for p in _image_whitelist_dirs(config)
        for form in _dir_candidate_forms(p, path_mappings)
    )
    if not allowed:
        logger.warning("get_image: 拒絕白名單外路徑請求 uri=%s", request_uri)
        return Response(status_code=403, content="路徑不在允許的資料夾範圍內")

    # 來源可達性已在上方「0. 字面式早退」判過（PR#178 R2）。這裡不再判第二次：
    # 兩處用的是同一組來源前綴，只差 normpath vs realpath 形式，對非 symlink 路徑
    # 完全等價 —— 留著第二道會變成沒有任何測試守得住的死碼（mutation M5 SURVIVED），
    # 而「守不住的守衛」比沒有守衛更糟（它會讓全綠變成假的）。
    # 放棄的涵蓋範圍：realpath 之後才落進斷線來源的 symlink（那種情況 realpath 本身
    # 就已經先付過遠端成本，第二道也救不了牆），行為等同本 branch 之前。

    # 4. 檔案存在性
    if not os.path.exists(local_path):
        return Response(status_code=404, content="檔案不存在")

    media_type = mime_types[ext]
    return FileResponse(
        local_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/video")
def get_video(request: Request, path: str = Query(..., description="影片路徑（file:/// URI 或 FS 路徑）")):
    """代理影片請求，解決瀏覽器無法開啟 file:/// URI 的問題"""
    # URL decode
    path = unquote(path)

    # TASK-91-T2b #12：config/gallery_config/path_mappings 搬到 local_path 計算之前，
    # 讓 uri_to_local_fs_path 取用得到 path_mappings（原本晚於 local_path 賦值，會 NameError）。
    config = load_config()
    gallery_config = config.get('gallery', {})
    path_mappings = gallery_config.get('path_mappings', {})

    # 1. 轉換為 FS 路徑（WSL+UNC path_mappings 環境下反解成真正能 open() 的本機路徑）
    local_path = uri_to_local_fs_path(path, path_mappings)

    # 2. 解析 .. 並追蹤 symlink target（realpath）；FUSE/WinFsp OSError 時降級 normpath
    local_path = safe_realpath(local_path, "get_video")

    # 3. 副檔名白名單（用 realpath/normpath 解析後的路徑）
    #    使用 get_proxy_extensions() = user config ∩ SAFE_PROXY_EXTENSIONS
    allowed_extensions = get_proxy_extensions(config)
    ext = os.path.splitext(local_path)[1].lower()
    if ext not in allowed_extensions:
        logger.warning("get_video: 拒絕非影片副檔名請求 ext=%s", ext)
        return Response(status_code=403, content="不允許的檔案類型")

    # 4. 目錄白名單：只允許 gallery.directories 底下的檔案
    # TASK-73: 兩端對稱正規化 — request_uri 用 single-form（realpath已做）；
    # dir 端用 dual-form（normpath + realpath 候選），避免 SMB mapped drive 格式不同 403 誤殺
    request_uri = to_file_uri(local_path, path_mappings)
    allowed = any(
        is_path_under_dir(request_uri, form)
        for p in get_gallery_source_paths(gallery_config)
        for form in _dir_candidate_forms(p, path_mappings)
    )
    if not allowed:
        logger.warning("get_video: 拒絕白名單外路徑請求 uri=%s", request_uri)
        return Response(status_code=403, content="路徑不在允許的資料夾範圍內")

    # 5. 檔案存在性
    if not os.path.exists(local_path):
        return Response(status_code=404, content="檔案不存在")

    # 6. MIME 類型映射
    video_mime = {
        '.mp4': 'video/mp4', '.mkv': 'video/x-matroska',
        '.avi': 'video/x-msvideo', '.wmv': 'video/x-ms-wmv',
        '.mov': 'video/quicktime', '.flv': 'video/x-flv',
        '.webm': 'video/webm', '.m4v': 'video/x-m4v',
        '.ts': 'video/mp2t', '.m2ts': 'video/mp2t',
        '.mpg': 'video/mpeg', '.mpeg': 'video/mpeg',
    }
    media_type = video_mime.get(ext, 'application/octet-stream')

    # 7. Range request 支援（影片 seek 必要）
    file_size = os.path.getsize(local_path)
    range_header = request.headers.get("range")

    if range_header:
        import re
        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            end = min(end, file_size - 1)

            # 無效 Range：start 超出檔案大小或 start > end
            if start >= file_size or start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )

            chunk_size = end - start + 1

            def iter_file():
                with open(local_path, 'rb') as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        read_size = min(remaining, 65536)
                        data = f.read(read_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_file(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                    "Content-Disposition": "inline",
                },
            )

    # 無 Range：完整回傳
    return FileResponse(
        local_path, media_type=media_type,
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
        },
    )
