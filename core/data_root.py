"""core/data_root.py — process-lifetime data-root resolver.

T1：只暴露「現有預設 output 目錄」；環境覆寫生效押到 T2。
純函式、無 class、不 import web 層。
"""
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent


def _default_output_root() -> Path:
    """現有預設 output 目錄（= <project_root>/output）。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT / "output"


def get_data_root() -> Path:
    """回傳目前 process 的資料根目錄（T1：現有預設位置）。純路徑推導，無 I/O。"""
    return _default_output_root()


def get_project_root() -> Path:
    """回傳專案根目錄。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT
