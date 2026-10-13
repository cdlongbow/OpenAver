"""啟動時更新提醒（168c-T3）：背景查一次，等到頁面確認顯示後才記帳。

本機模式完全不動作（由本機伺服器自己的更新提醒負責）。
"""
import json
import re
import threading

from core import client_settings, self_update
from core.logger import get_logger

logger = get_logger(__name__)

_VERSION_RE = re.compile(r"\d+(\.\d+)*")
_SCRIPT = ("typeof window.handleShellNotice==='function' && "
           "window.handleShellNotice({kind:'update_available',version:%s})")

# pending：待顯示的新版本字串；page：最近一次載入的 (window, gen, is_current)
_state = {"pending": None, "page": None}
_lock = threading.Lock()


def _run_async(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def check_once():
    """查一次 GitHub；通過全部閘才設 pending 並嘗試顯示。"""
    if client_settings.mode() != "client":
        return
    if not client_settings.auto_check_update():
        return
    try:
        result = self_update.check_latest()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[update_notice] check failed: {type(e).__name__}")
        return
    if not isinstance(result, dict) or not result.get("ok") or not result.get("has_update"):
        return
    latest = result.get("latest_version")
    if not isinstance(latest, str) or not _VERSION_RE.fullmatch(latest):
        return
    if latest == client_settings.last_notified_update_version():
        return
    with _lock:
        _state["pending"] = latest
        page = _state["page"]
    if page is not None:
        _show(*page)


def _show(window, gen, is_current):
    with _lock:
        latest = _state["pending"]
        if latest is None or not is_current():
            return
        script = _SCRIPT % json.dumps(latest)
        try:
            shown = window.evaluate_js(script)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[update_notice] show failed: {type(e).__name__}")
            return
        if shown is True:
            _state["pending"] = None
            try:
                client_settings.update_local_settings({"last_notified_update_version": latest})
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[update_notice] record failed: {type(e).__name__}")


def try_show(window, gen, is_current):
    """頁面載入完成時呼叫：記下這一頁，有 pending 就嘗試顯示。"""
    if client_settings.mode() == "local":
        return
    with _lock:
        if is_current():
            _state["page"] = (window, gen, is_current)
    _show(window, gen, is_current)


def start_background_check():
    _run_async(check_once)
