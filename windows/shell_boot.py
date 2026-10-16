"""桌面殼啟動決策：本機／連線／離線小頁，與小頁文案、pywebview 日誌票證遮蔽（168b-T5a）"""
import contextlib
import logging
import os
import re
from typing import NamedTuple, Optional

from core import client_connect, client_settings
from core.i18n import t
from core.logger import get_logger

OFFLINE_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline", "offline.html")

logger = get_logger(__name__)

_REASONS = ("unreachable", "lan_forbidden", "incompatible", "relogin")
_TEXT_KEYS = ("url_label", "retry", "retrying", "switch_local", "password_label", "submit",
              "bad_url", "bad_pin", "login_failed", "retry_failed")
_TOKEN_RE = re.compile(r"oa_token=[^&\s\"']+")


class OfflineState(NamedTuple):
    reason: str
    failed_url: str


class BootTarget(NamedTuple):
    kind: str
    url: str
    title: str
    offline: Optional[OfflineState]


def _boot_local(local_origin, shell_kind):
    return BootTarget("local", client_settings.shell_entry_url(local_origin, shell_kind),
                      "OpenAver", None)


def _boot_client(local_origin, shell_kind, token):
    client_settings.touch_last_ok()
    url = client_settings.shell_entry_url(local_origin, shell_kind, token=token)
    title = f"OpenAver — {client_settings.display_host(client_settings.server_url())}"
    return BootTarget("client", url, title, None)


def _boot_offline(pf):
    reason = pf.reason
    failed = client_settings.canonical_server_url(client_settings.server_url()) or ""
    return BootTarget("offline", OFFLINE_PAGE, "OpenAver", OfflineState(reason, failed))


def resolve_boot(local_origin, shell_kind):
    """決定殼要載入哪裡；本機模式不做任何網路探測"""
    if client_settings.mode() == "local":
        return _boot_local(local_origin, shell_kind)
    token = client_settings.server_token()
    pf = client_connect.preflight(client_settings.server_url(), token)
    if pf.status == "ok":
        return _boot_client(local_origin, shell_kind, token)
    return _boot_offline(pf)


def offline_texts(reason, host_port):
    """小頁文案（跟隨托盤語系，缺 key 退 zh-TW）；永不拋"""
    try:
        key = reason if reason in _REASONS else "unreachable"
        locale = client_settings.tray_locale()
        texts = {"message": t(f"desktop.offline.message.{key}", locale, host=host_port)}
        for name in _TEXT_KEYS:
            texts[name] = t(f"desktop.offline.{name}", locale)
        return texts
    except Exception as e:
        logger.warning(f"[shell_boot] offline texts failed ({type(e).__name__})")
        return {}


def _redact(value):
    return _TOKEN_RE.sub("oa_token=<redacted>", value) if isinstance(value, str) else value


class _TokenRedactFilter(logging.Filter):
    def filter(self, record):
        with contextlib.suppress(Exception):
            record.msg = _redact(record.msg)
            args = record.args
            if isinstance(args, tuple):
                record.args = tuple(_redact(a) for a in args)
            elif isinstance(args, dict):
                record.args = {k: _redact(v) for k, v in args.items()}
        return True


def install_webview_token_filter():
    """pywebview 會把入口網址（含 oa_token）寫進 DEBUG 日誌；掛過濾器遮掉"""
    # 第三方（pywebview）的 logger 名稱固定為 "pywebview"，get_logger 會加前綴對不上；
    # 經 manager 取同一個物件（ruff 禁 logging.getLogger 是為自家模組）
    target = logging.Logger.manager.getLogger("pywebview")
    if not any(isinstance(f, _TokenRedactFilter) for f in target.filters):
        target.addFilter(_TokenRedactFilter())
