"""
OpenAver PyWebView 共用 API 模組
供 launcher.py 和 standalone.py 共用
"""
import os
import sys
import json
import subprocess
import webview
import core.client_settings as client_settings
from core.path_translate import Mapped, PathMap, Uncovered, to_local, to_server
from core.path_utils import file_uri_to_server_path, uri_to_fs_path
from core.video_extensions import DEFAULT_VIDEO_EXTENSIONS
from core.logger import get_logger
from webview.dom import DOMEventHandler

logger = get_logger(__name__)

# 支援的影片副檔名（from core.video_extensions Single Source of Truth）
VIDEO_EXTENSIONS = set(DEFAULT_VIDEO_EXTENSIONS)

# 全域 window 參考（由 launcher/standalone 設定）
_window = None


def set_window(w):
    """設定全域 window 參考"""
    global _window
    _window = w


def get_window():
    """取得全域 window 參考"""
    return _window


def is_video_file(filename, extensions=None):
    """檢查是否為影片檔案

    Args:
        filename: 檔案名稱
        extensions: 可選的副檔名集合，未提供時使用模組級 VIDEO_EXTENSIONS 預設值
    """
    ext = os.path.splitext(filename)[1].lower()
    if extensions is not None:
        return ext in extensions
    return ext in VIDEO_EXTENSIONS


def _path_map():
    """每次呼叫現建（不快取：設定改了立刻生效）"""
    return PathMap.from_rules(client_settings.path_map())


def bridge_resolve(value):
    """伺服器端路徑／URI → 這台電腦的本機路徑。

    本機模式＝uri_to_fs_path；client 模式查對照表，不在表內回 Uncovered()（絕不回原字串）。
    """
    if client_settings.mode() != 'client':
        return uri_to_fs_path(value)  # uri-no-reverse: windows native runtime, path_mappings N/A
    translated = to_local(file_uri_to_server_path(value), _path_map())
    return translated.path if isinstance(translated, Mapped) else translated


def bridge_unresolve(local_path):
    """這台電腦的本機路徑 → 伺服器端路徑；本機模式恆等，client 模式不在表內回 Uncovered()。"""
    if client_settings.mode() != 'client':
        return local_path
    found = to_server(local_path, _path_map())
    return found.path if isinstance(found, Mapped) else found


def _result(ok, reason, local_path, server_path):
    return {"ok": ok, "reason": reason, "local_path": local_path, "server_path": server_path}


def _refuse(method, reason, server_path, local_path):
    """拒絕結果＋固定形狀 WARNING（f-string 預先格式化）"""
    logger.warning(f"[pywebview] {method} refused reason={reason} server={server_path!r} local={local_path!r}")
    return _result(False, reason, local_path, server_path)


def _resolve_forward(method, path):
    """正向翻譯：回 (local_path, server_path, 拒絕結果或 None)；uncovered 即止、不碰檔案系統"""
    server_path = file_uri_to_server_path(path)
    local_path = bridge_resolve(path)
    if isinstance(local_path, Uncovered):
        return None, server_path, _refuse(method, "uncovered", server_path, None)
    return local_path, server_path, None


def _is_video_path(local_path):
    return os.path.splitext(local_path)[1].lower() in client_settings.video_extensions()


def _split_reverse(local_paths):
    """本機路徑逐個翻成伺服器路徑；回 (已翻譯清單, 未涵蓋的本機路徑清單)"""
    kept, uncovered = [], []
    for local_path in local_paths:
        server = bridge_unresolve(local_path)
        if isinstance(server, Uncovered):
            uncovered.append(local_path)
        else:
            kept.append(server)
    return kept, uncovered


def _notify_uncovered(method, paths):
    """每次出口呼叫最多通知一次：保序去重，每個路徑一行 WARNING"""
    unique = list(dict.fromkeys(paths))
    if not unique:
        return
    for local_path in unique:
        logger.warning(f"[pywebview] {method} refused reason=uncovered server=None local={local_path!r}")
    window = get_window()
    if window is not None:
        paths_json = json.dumps(unique)
        window.evaluate_js(f'if(typeof handleBridgeUncovered === "function") handleBridgeUncovered({paths_json})')


class Api:
    """供前端 JS 調用的 Python API"""

    def select_files(self):
        """
        開啟檔案選擇對話框，選取影片檔案
        Returns: 選取的檔案路徑陣列（已翻譯成伺服器路徑；未涵蓋者不回傳，改發通知）
        """
        window = get_window()
        exts = client_settings.video_extensions()
        ext_filter = ';'.join(f'*{ext}' for ext in sorted(exts))
        file_types = (f'影片檔案 ({ext_filter})',
                      '所有檔案 (*.*)')
        result = window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=file_types
        )
        if not result:
            return []
        kept, uncovered = _split_reverse(list(result))
        _notify_uncovered('select_files', uncovered)
        return kept

    def select_folder(self):
        """
        開啟資料夾選擇對話框，返回資料夾路徑和內部影片檔案
        Returns: { folder: 資料夾路徑, files: 影片檔案陣列 }（伺服器路徑）；資料夾未涵蓋回 None
        """
        window = get_window()
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not (result and len(result) > 0):
            return None
        folder_path = result[0]
        folder_kept, uncovered = _split_reverse([folder_path])
        if not folder_kept:
            _notify_uncovered('select_folder', uncovered)
            return None
        exts = client_settings.video_extensions()
        local_files = []
        for f in os.listdir(folder_path):
            file_path = os.path.join(folder_path, f)
            if os.path.isfile(file_path) and is_video_file(f, exts):
                local_files.append(file_path)
        files, uncovered_files = _split_reverse(local_files)
        _notify_uncovered('select_folder', uncovered_files)
        return {"folder": folder_kept[0], "files": files}

    def select_folder_path(self):
        """開啟資料夾選擇對話框，只返回資料夾路徑（伺服器路徑；未涵蓋回 None）"""
        window = get_window()
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not (result and len(result) > 0):
            return None
        kept, uncovered = _split_reverse([result[0]])
        _notify_uncovered('select_folder_path', uncovered)
        return kept[0] if kept else None

    def open_file(self, path):
        """用系統預設程式或指定播放器開啟檔案

        支援格式：
        - file:///C:/path/to/file.mp4
        - C:/path/to/file.mp4
        - C:\\path\\to\\file.mp4

        Returns: {"ok", "reason", "local_path", "server_path"}；
        reason ∈ None / uncovered / not_video / not_found / failed
        """
        local_path, server_path, refused = _resolve_forward('open_file', path)
        if refused:
            return refused

        if not _is_video_path(local_path):
            return _refuse('open_file', 'not_video', server_path, local_path)

        if not os.path.exists(local_path):
            return _refuse('open_file', 'not_found', server_path, local_path)

        # 讀取設定，檢查是否有指定播放器
        player = client_settings.player_path()

        if player and os.path.exists(player):
            try:
                subprocess.Popen([player, local_path])
                return _result(True, None, local_path, server_path)
            except Exception as e:
                logger.warning(f"[pywebview] custom player failed for {local_path!r} (player={player!r}): {e}; falling back to OS default")
                pass  # fallback 到系統預設

        # 跨平台開啟檔案
        try:
            if sys.platform == 'win32':
                os.startfile(local_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', local_path])
            else:
                subprocess.run(['xdg-open', local_path])
            return _result(True, None, local_path, server_path)
        except Exception as e:
            logger.error(f"[pywebview] open_file failed for {local_path!r}: {e}")
            return _result(False, 'failed', local_path, server_path)

    def open_url(self, url: str) -> bool:
        """用系統預設瀏覽器開啟 URL

        僅接受 http:// 或 https:// 開頭的 URL，其他 scheme 一律拒絕。
        任何例外均捕捉並回傳 False，不讓異常傳播。

        Args:
            url: 要開啟的 URL 字串

        Returns:
            True 表示成功呼叫系統 API，False 表示驗證失敗或系統呼叫拋出例外
        """
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            return False
        try:
            if sys.platform == 'win32':
                os.startfile(url)
                return True
            elif sys.platform == 'darwin':
                result = subprocess.run(['open', url])
                return result.returncode == 0
            else:
                result = subprocess.run(['xdg-open', url])
                return result.returncode == 0
        except Exception as e:
            logger.error(f"[pywebview] open_url failed for {url!r}: {e}")
            return False

    def open_folder(self, path):
        """用系統檔案管理員開啟檔案所在資料夾

        支援格式同 open_file()：
        - file:///C:/path/to/file.mp4
        - C:/path/to/file.mp4
        - C:\\path\\to\\file.mp4

        Windows: explorer /select, → 打開資料夾並選中檔案
        macOS:   open -R          → Finder 中顯示檔案
        Linux:   xdg-open         → 打開所在資料夾

        Returns: 同 open_file()（無 not_video）；local_path 永遠報原路徑不報父層
        """
        local_path, server_path, refused = _resolve_forward('open_folder', path)
        if refused:
            return refused

        target = local_path
        if not os.path.exists(target):
            # 檔案不存在，嘗試開啟父資料夾
            parent = os.path.dirname(target)
            if not os.path.exists(parent):
                return _refuse('open_folder', 'not_found', server_path, local_path)
            target = parent

        try:
            if sys.platform == 'win32':
                # /select, 會打開資料夾並選中該檔案
                subprocess.Popen(['explorer', '/select,', target])
                ok = True
            elif sys.platform == 'darwin':
                # -R 會在 Finder 中顯示並選中該檔案
                ok = subprocess.run(['open', '-R', target]).returncode == 0
            else:
                # Linux: 開啟所在資料夾
                folder = os.path.dirname(target) if os.path.isfile(target) else target
                ok = subprocess.run(['xdg-open', folder]).returncode == 0
        except Exception as e:
            logger.error(f"[pywebview] open_folder failed for {target!r}: {e}")
            ok = False
        return _result(ok, None if ok else 'failed', local_path, server_path)



def on_drop(e):
    """處理拖放事件，取得完整路徑並傳給前端（支援多檔案和資料夾；路徑已翻譯成伺服器路徑）"""
    window = get_window()

    files = e.get('dataTransfer', {}).get('files', [])
    if not files:
        return

    expanded_paths = []  # 影片檔案路徑（給 search 用）
    folder_paths = []    # 資料夾路徑（給 scanner 用）
    uncovered = []       # 未涵蓋的本機路徑（只通知，不推送）

    exts = client_settings.video_extensions()

    for file_info in files:
        win_path = file_info.get('pywebviewFullPath', '')
        if not win_path:
            continue

        if os.path.isdir(win_path):
            folder_kept, folder_uncovered = _split_reverse([win_path])
            folder_paths.extend(folder_kept)
            uncovered.extend(folder_uncovered)
            if not folder_kept:
                continue
            # 資料夾：展開第一層影片檔案（給 search 用）
            local_files = []
            for f in os.listdir(win_path):
                file_win_path = os.path.join(win_path, f)
                if os.path.isfile(file_win_path) and is_video_file(f, exts):
                    local_files.append(file_win_path)
            kept, file_uncovered = _split_reverse(local_files)
            expanded_paths.extend(kept)
            uncovered.extend(file_uncovered)
        else:
            kept, file_uncovered = _split_reverse([win_path])
            expanded_paths.extend(kept)
            uncovered.extend(file_uncovered)

    # 傳送影片檔案路徑（search 頁面用）
    if expanded_paths:
        paths_json = json.dumps(expanded_paths)
        window.evaluate_js(f'if(typeof handlePyWebViewDrop === "function") handlePyWebViewDrop({paths_json})')

    # 傳送資料夾路徑（scanner 頁面用）
    if folder_paths:
        folders_json = json.dumps(folder_paths)
        window.evaluate_js(f'if(typeof handleFolderDrop === "function") handleFolderDrop({folders_json})')

    _notify_uncovered('on_drop', uncovered)


def bind_events(w):
    """綁定 DOM 事件（頁面加載後綁定 drop 事件）"""
    set_window(w)

    def on_loaded():
        """每次頁面加載後綁定 drop 事件"""
        window = get_window()
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    # 監聯頁面加載事件（每次導航後都會觸發）
    w.events.loaded += on_loaded


# 建立全域 api 實例
api = Api()
