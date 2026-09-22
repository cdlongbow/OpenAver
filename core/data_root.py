"""core/data_root.py — process-lifetime data-root resolver.

T2 起 `OPENAVER_DATA_DIR` 生效（與 external-root gate 同顆交付）。
純函式、無 class、不 import web 層。
"""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

# 資料根定版標記檔名。放此檔（而非 data_layout）以免 config ↔ data_layout 循環 import。
LAYOUT_MARKER_NAME = ".layout.json"


def _default_output_root() -> Path:
    """現有預設 output 目錄（= <project_root>/output）。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT / "output"


def get_default_data_root() -> Path:
    """回傳未受 OPENAVER_DATA_DIR 覆寫的預設資料根。純路徑推導，無 I/O。"""
    return _default_output_root()


def get_data_root() -> Path:
    """回傳目前 process 的資料根目錄。

    非空的 OPENAVER_DATA_DIR 覆寫預設位置；本函式只做路徑推導，不建目錄、不讀檔。
    external-root gate（空 override + 本機有舊資料 → 阻斷）由
    ``core.data_layout.bootstrap_data_layout`` 負責。
    """
    raw = os.environ.get("OPENAVER_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _default_output_root()


def get_project_root() -> Path:
    """回傳專案根目錄。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT


def resolve_gallery_output_path(output_dir: str) -> Path:
    """解析 gallery.output_dir 為絕對 Path。

    空／純空白 → get_data_root()（跟著資料根走）；
    非空相對值 → get_project_root() / value；
    非空絕對值 → 原樣。純路徑推導，無 I/O。
    """
    value = (output_dir or "").strip()
    if not value:
        return get_data_root()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return get_project_root() / value
