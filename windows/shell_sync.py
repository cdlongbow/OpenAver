"""桌面殼載入同步（168c-T3）：連線模式下，每個頁面載入完成時同步托盤語系、抄副檔名、接上更新提醒。

本模組不 import 殼的 bridge 模組（sibling 與 ``windows.`` 兩條路徑會得到兩份模組）；
由殼在啟動時用 ``install(api_module)`` 把模組傳進來。
"""
import threading

from core import client_connect, client_settings
from core.i18n import SUPPORTED_LOCALES
from core.logger import get_logger
from windows import update_notice

logger = get_logger(__name__)

# synced：本連線世代的副檔名是否已抄成功；probe：gen -> 「該次載入的頁面是否仍是現在的 server 頁」
_state = {"synced": False, "probe": None}


def _run_async(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def _probe_current(gen):
    probe = _state["probe"]
    return bool(probe(gen)) if probe is not None else False


def sync_tray_locale(window):
    """把頁面 <html lang> 同步成托盤語系；非白名單值（頁面可偽造）一律忽略。"""
    try:
        lang = window.evaluate_js("document.documentElement.lang")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[shell_sync] read page lang failed: {type(e).__name__}")
        return
    if not isinstance(lang, str) or lang not in SUPPORTED_LOCALES:
        return
    if lang == client_settings.tray_locale():
        return
    try:
        client_settings.update_local_settings({"tray_locale": lang})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[shell_sync] write tray_locale failed: {type(e).__name__}")


def _copy_extensions(gen):
    """背景：從伺服器抄副檔名到這台；任何失敗都不寫、不立旗標。"""
    try:
        result = client_connect.fetch_video_extensions(*client_settings.server_pair())
        exts = result["extensions"] if result.get("ok") else None
        if exts is None or not _probe_current(gen):
            return
        written = client_settings.update_local_settings({"video_extensions": exts})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[shell_sync] copy video_extensions failed: {type(e).__name__}")
        return
    if written.get("ok") and _probe_current(gen):
        _state["synced"] = True


def on_page_loaded(kind, window, gen):
    """頁面載入鉤子；本機模式立即返回（零網路、零寫檔、零 evaluate_js）。"""
    if client_settings.mode() != "client":
        return
    if kind == "offline":
        _state["synced"] = False
        return
    if kind != "server":
        return
    sync_tray_locale(window)
    if not _state["synced"]:
        _run_async(_copy_extensions, gen)
    update_notice.try_show(window, gen, lambda: _probe_current(gen))


def install(api_module):
    """註冊載入鉤子，並記下「頁面是否仍是當次載入」的探針（讀呼叫當下的 bridge 狀態）。"""
    def probe(gen):
        bridge = api_module.api
        return bridge._page_kind == "server" and bridge._nav_gen == gen

    _state["probe"] = probe
    api_module.set_loaded_hook(on_page_loaded)
