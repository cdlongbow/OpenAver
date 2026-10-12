"""
OpenAver PyWebView 共用 API 模組
供 launcher.py 和 standalone.py 共用
"""
import os
import sys
import json
import subprocess
from urllib.parse import urlparse
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


# 連不到伺服器時殼自帶的小頁（只組字串，檔案由離線小頁那張卡建立）
OFFLINE_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline", "offline.html")
_OFFLINE_HOSTS = ("127.0.0.1", "localhost")

# bridge 方法 → 允許呼叫的頁面種類（唯一對照表；沒登記的方法一律拒絕）
_SCOPE = {
    "select_files": "server",
    "select_folder": "server",
    "select_folder_path": "server",
    "open_file": "server",
    "open_folder": "server",
    "open_url": "server",
    "on_drop": "server",
}


def _is_offline_landing(js_raw, native_raw):
    """JS 與原生 URL 的原字串都指向本機 /offline.html 且 origin 一致才回 True"""
    js_origin = client_settings.normalize_origin(js_raw)
    native_origin = client_settings.normalize_origin(native_raw)
    if js_origin is None or js_origin != native_origin:
        return False
    try:
        parsed = urlparse(native_raw.strip())
    except ValueError:
        return False
    if parsed.hostname not in _OFFLINE_HOSTS:
        return False
    return parsed.path.endswith("/offline.html")


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
    """供前端 JS 調用的 Python API（信任閘：依落地頁面種類放行，預設 fail-closed）"""

    def __init__(self):
        self._page_kind = None  # None / "server" / "offline"
        self._trusted_origin = None
        self._nav_gen = 0
        self._seen_origin = None
        self._offline_expected = False
        self._offline_origin = None
        self._offline_state = None

    def _get_trusted(self):
        """相容屬性 getter：目前頁面是否為伺服器頁"""
        return self._page_kind == "server"

    def _put_trusted(self, value):
        """相容屬性 setter：真 → server、假 → None"""
        self._page_kind = "server" if value else None

    _trusted = property(_get_trusted, _put_trusted)

    def _set_trusted_origin(self, origin):
        """設定唯一信任的 origin（尾斜線不計）。底線開頭：pywebview 不會把它注入頁面"""
        self._trusted_origin = client_settings.normalize_origin(str(origin)) or str(origin).rstrip("/")

    def _denied(self, method):
        """頁面種類不符該方法的範圍：記一行 WARNING 並回 True"""
        scope = _SCOPE.get(method)
        if scope is not None and scope == self._page_kind:
            return False
        origin = None if self._seen_origin is None else str(self._seen_origin)[:128]
        logger.warning(f"[pywebview] {method} refused reason=untrusted origin={origin!r}")
        return True

    def _expect_offline(self):
        """殼即將載入離線小頁：下一次通過世代守衛的驗證才可把本機 /offline.html 判成小頁"""
        self._offline_expected = True

    def _set_offline_state(self, reason, failed_url):
        """離線狀態容器：網址只存規範化後的 scheme://host[:port]（不含票證）"""
        failed = client_settings.canonical_server_url(failed_url) or ""
        self._offline_state = {
            "reason": reason,
            "failed_url": failed,
            "host_port": client_settings.display_host(failed, with_port=True),
        }

    def _show_offline(self, reason):
        """把視窗換成離線小頁"""
        self._set_offline_state(reason, self._trusted_origin)
        self._expect_offline()
        get_window().load_url(OFFLINE_PAGE)

    def _on_before_load(self):
        """每次導航注入前：世代遞增並立即撤銷頁面種類"""
        self._nav_gen += 1
        self._page_kind = None  # before_load reset (I7)

    def _on_loaded(self):
        """頁面載入後：讀實際落地 origin 判定頁面種類；只有伺服器頁才綁 drop"""
        gen = self._nav_gen
        window = get_window()
        js_raw, native_raw, ok = self._read_origins(window)
        if gen != self._nav_gen:
            return
        expected, self._offline_expected = self._offline_expected, False
        origin = self._agreed_origin(js_raw, native_raw) if ok else None
        self._seen_origin = origin
        self._page_kind = self._classify(origin, js_raw, native_raw, expected)
        if self._page_kind == "server":
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        elif self._page_kind is None:
            self._on_nav_failure(js_raw, native_raw)

    @staticmethod
    def _read_origins(window):
        """回 (JS 原字串, 原生 URL 原字串, 是否讀成功)；任何例外 fail-closed"""
        if window is None:
            return None, None, False
        try:
            return window.evaluate_js("location.origin"), window.get_current_url(), True
        except Exception as e:
            logger.warning(f"[pywebview] origin check failed ({type(e).__name__}); treated as untrusted")
            return None, None, False

    @staticmethod
    def _agreed_origin(js_raw, native_raw):
        """兩個來源正規化後一致才回 origin；否則 None"""
        js_origin = client_settings.normalize_origin(js_raw)
        native_origin = client_settings.normalize_origin(native_raw)
        if native_origin is None or native_origin != js_origin:
            logger.warning("[pywebview] origin sources disagree or missing; treated as untrusted")
            return None
        return js_origin

    def _classify(self, origin, js_raw, native_raw, expected):
        """伺服器頁優先；其次（等待中或同一小頁重整）的本機離線小頁；其餘 None"""
        if origin is not None and origin == self._trusted_origin:
            return "server"
        remembered = self._offline_origin is not None and origin == self._offline_origin
        if (expected or remembered) and _is_offline_landing(js_raw, native_raw):
            self._offline_origin = origin
            return "offline"
        return None

    def _on_nav_failure(self, js_raw, native_raw):
        """信任伺服器的導航失敗（錯誤頁簽名）且為連線模式 → 換成離線小頁"""
        if not (isinstance(js_raw, str) and js_raw.startswith("chrome-error://")):
            return
        native_origin = client_settings.normalize_origin(native_raw)
        if native_origin is None or native_origin != self._trusted_origin:
            return
        if client_settings.mode() != "client":
            return
        logger.warning(f"[pywebview] server unreachable host={client_settings.display_host(native_origin, with_port=True)}")
        self._show_offline("unreachable")

    def select_files(self):
        """
        開啟檔案選擇對話框，選取影片檔案
        Returns: 選取的檔案路徑陣列（已翻譯成伺服器路徑；未涵蓋者不回傳，改發通知）
        """
        if self._denied("select_files"):
            return []
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
        if self._denied("select_folder"):
            return None
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
        if self._denied("select_folder_path"):
            return None
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
        if self._denied("open_file"):
            return {"ok": False, "reason": "untrusted", "local_path": None, "server_path": None}
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
        if self._denied("open_url"):
            return False
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
        if self._denied("open_folder"):
            return {"ok": False, "reason": "untrusted", "local_path": None, "server_path": None}
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
    if api._denied("on_drop"):
        return
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
    """綁定導航事件（信任閘；信任頁載入後才綁 drop 事件）"""
    set_window(w)

    # 每次導航：before_load 撤銷信任（先於注入），loaded 驗證落地 origin
    w.events.before_load += api._on_before_load
    w.events.loaded += api._on_loaded


# 建立全域 api 實例
api = Api()


# --- 注入面：模組層包裝函式（窗口以 js_api=None＋window.expose 註冊，派送端只做精確名稱查表）---
# 包裝函式不可有 self（expose 依 getfullargspec 產 stub）；on_drop 是 DOM 事件不是 JS 呼叫，不在其中。

def open_file(path):
    return api.open_file(path)


def open_folder(path):
    return api.open_folder(path)


def open_url(url):
    return api.open_url(url)


def select_files():
    return api.select_files()


def select_folder():
    return api.select_folder()


def select_folder_path():
    return api.select_folder_path()


def exposed_functions():
    """給 window.expose(*...) 的 bridge 白名單"""
    return [open_file, open_folder, open_url, select_files, select_folder, select_folder_path]
