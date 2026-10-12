"""core/client_settings.py — 「這台電腦的設定」的家（桌面殼用）。

檔案 = ``<資料根>/client.json``（每次呼叫現算路徑，``OPENAVER_DATA_DIR`` 才能被測試覆寫）。
``mode()`` 為 ``'client'`` 若且唯若該檔存在、可解析為 dict、``version == 1``、
``server.url`` 為非空 http(s) URL；其餘一律 ``'local'``。

本機模式：accessors 逐字沿用今天的讀取方式（``config.json``），**永不建立 client.json**。
連線模式：只讀 client.json，缺鍵用內建預設，**不回頭讀本機 config.json**。

純函式、無 class；不 import web／windows／webview。
"""
import json
from pathlib import Path
from urllib.parse import urlparse

import core.config as core_config
from core.atomic_write import atomic_write
from core.data_root import get_data_root
from core.i18n import FALLBACK_LOCALE
from core.logger import get_logger
from core.video_extensions import (
    DEFAULT_VIDEO_EXTENSIONS,
    get_video_extensions,
    normalize_extensions,
)

logger = get_logger(__name__)

CLIENT_FILE_NAME = "client.json"
CLIENT_VERSION = 1
_CLOSE_ACTIONS = ("ask", "tray", "exit")

# (key, 本機讀取來源, client 讀取來源, accessor 名)
LOCAL_MACHINE_KEYS = (
    ("server.url", "（無；本機模式即本機伺服器）", "client.json server.url", "server_url"),
    ("path_map", "（無；本機模式不翻譯路徑）", "client.json path_map", "path_map"),
    ("player", "config.json showcase.player", "client.json player", "player_path"),
    ("video_extensions", "config.json scraper.video_extensions", "client.json video_extensions", "video_extensions"),
    ("close_action", "config.json general.close_action", "client.json close_action", "close_action"),
    ("tray_locale", "config.json general.locale", "client.json tray_locale", "tray_locale"),
)

SERVER_OWNED_NOTE = (
    "歸伺服器管、不屬這台電腦：general.server_mode、gallery.*、所有爬蟲設定（scraper.*，"
    "含伺服器掃描用的 scraper.video_extensions；這台電腦 bridge 用的副檔名清單是另一份，見 video_extensions）。"
)


def _client_path() -> Path:
    return get_data_root() / CLIENT_FILE_NAME


def _valid_url(url) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _load_valid():
    """回傳有效的 client.json dict；無效（不存在／壞檔／版本不符／url 無效）回 None。"""
    path = _client_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[client_settings] {path} 無法解析：{e}；視為本機模式")
        return None
    if not isinstance(data, dict):
        logger.warning(f"[client_settings] {path} 頂層不是物件；視為本機模式")
        return None
    if data.get("version") != 1:
        logger.warning(f"[client_settings] {path} version 非 1；視為本機模式")
        return None
    server = data.get("server")
    if not isinstance(server, dict) or not _valid_url(server.get("url")):
        return None
    return data


def _client_data() -> dict:
    data = _load_valid()
    return data if data is not None else {}


def _read_raw_config():
    """讀本機 config.json 原始 JSON；檔不存在回 None，壞 JSON 往外丟。"""
    if core_config.CONFIG_PATH.exists():
        with open(core_config.CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def mode() -> str:
    return "client" if _load_valid() is not None else "local"


def server_url() -> str:
    server = _client_data().get("server")
    return str(server.get("url") or "").strip() if isinstance(server, dict) else ""


def path_map() -> list:
    pm = _client_data().get("path_map")
    return pm if isinstance(pm, list) else []


def player_path():
    if mode() == "local":
        try:
            config = _read_raw_config()
            if config is not None:
                return config.get("showcase", {}).get("player", "")
        except Exception as e:
            logger.warning(f"[client_settings] player_path failed to read config: {e}; falling back to empty string (OS default player)")
        return ""
    return str(_client_data().get("player") or "")


def video_extensions() -> set:
    if mode() == "local":
        try:
            config = _read_raw_config()
            if config is not None:
                return get_video_extensions(config)
        except Exception as e:
            logger.warning(f"[client_settings] video_extensions failed to read config: {e}; falling back to DEFAULT_VIDEO_EXTENSIONS")
        return set(DEFAULT_VIDEO_EXTENSIONS)
    exts = _client_data().get("video_extensions")
    if isinstance(exts, list) and exts:
        return normalize_extensions([e for e in exts if isinstance(e, str)])
    return set(DEFAULT_VIDEO_EXTENSIONS)


def close_action() -> str:
    if mode() == "local":
        return core_config.load_config().get("general", {}).get("close_action", "ask")
    value = _client_data().get("close_action")
    return value if value in _CLOSE_ACTIONS else "ask"


def tray_locale() -> str:
    if mode() == "local":
        return core_config.load_config().get("general", {}).get("locale", FALLBACK_LOCALE)
    return _client_data().get("tray_locale") or FALLBACK_LOCALE


def save_client_settings(d: dict) -> None:
    """原子寫入 client.json（0600）。僅供測試與開發者手改輔助。"""
    path = _client_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(path, mode="w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_close_action(action: str) -> None:
    """寫入關閉行為。本機寫 config.json（同今天 mutator）；連線模式只寫 client.json。"""
    if mode() == "local":
        def _mutator(cfg):
            cfg.setdefault("general", {})["close_action"] = action
        core_config.mutate_config(_mutator)
    else:
        save_client_settings({**_client_data(), "close_action": action})


def server_origin(local_origin: str) -> str:
    """連線模式回 server.url 的 scheme://netloc；本機模式原樣回傳 local_origin。"""
    if mode() == "local":
        return local_origin
    parsed = urlparse(server_url())
    return f"{parsed.scheme}://{parsed.netloc}"


def shell_entry_url(local_origin: str, shell_kind: str) -> str:
    return f"{server_origin(local_origin)}/?oa_shell={shell_kind}"
