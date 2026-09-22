"""core/data_layout.py — 資料根 bootstrap（TASK-153b-T2）。

第一次啟動把 legacy `web/config.json` 安全複製到 `<root>/config.json` 並寫下
`.layout.json` 完成標記；之後只認 root。失敗時拋 DataLayoutError，由呼叫端
（T4）決定可見出口——本模組不吞例外、不開對話框。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.atomic_write import atomic_move, atomic_write, create_staging_file
from core.config import CONFIG_DEFAULT_PATH
import core.data_root as data_root
from core.data_root import LAYOUT_MARKER_NAME
from core.database import init_db
from core.logger import get_logger

logger = get_logger(__name__)

LAYOUT_VERSION = 1
ROOT_CONFIG_NAME = "config.json"


class DataLayoutError(Exception):
    """資料根 bootstrap 失敗；啟動必須中止（可見出口屬 T4）。"""


@dataclass(frozen=True)
class BootstrapResult:
    """bootstrap_data_layout() 的一次結果。"""

    status: str  # already_complete | finalized_legacy | recovered_existing | fresh
    root: Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _legacy_config_path() -> Path:
    return data_root.get_project_root() / "web" / "config.json"


def _read_marker(root: Path) -> Optional[dict[str, Any]]:
    marker_path = root / LAYOUT_MARKER_NAME
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _config_is_readable(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict)


def _root_has_valid_layout(root: Path) -> bool:
    marker = _read_marker(root)
    if marker is None or marker.get("complete") is not True:
        return False
    return _config_is_readable(root / ROOT_CONFIG_NAME)


def _root_is_empty(root: Path) -> bool:
    if not root.exists():
        return True
    if not root.is_dir():
        return False
    try:
        next(root.iterdir())
    except StopIteration:
        return True
    return False


def _root_has_legacy_data(root: Path) -> bool:
    """default root 是否有舊資料（供 external-root gate 判斷）。"""
    return not _root_is_empty(root)


def _write_marker(root: Path) -> None:
    payload = {"version": LAYOUT_VERSION, "complete": True}
    marker_path = root / LAYOUT_MARKER_NAME
    with atomic_write(marker_path, mode="w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _install_config_from_source(source: Path, dest: Path) -> None:
    """複製 source → dest：staging temp → SHA-256 驗證 → atomic_move。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_config_path = create_staging_file(dest.parent, suffix=".config.tmp")
    try:
        shutil.copy2(source, tmp_config_path)
        if _sha256(source) != _sha256(tmp_config_path):
            raise DataLayoutError(
                f"config copy hash mismatch: source={source} tmp={tmp_config_path}"
            )
        atomic_move(tmp_config_path, dest)
        # CD-114c-9: copy2 會把來源 0644 蓋到暫存檔；落地後強制 0600
        dest.chmod(0o600)
    except BaseException:
        try:
            tmp_config_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _install_default_config(dest: Path) -> None:
    if not CONFIG_DEFAULT_PATH.is_file():
        raise DataLayoutError(f"config.default.json missing: {CONFIG_DEFAULT_PATH}")
    _install_config_from_source(CONFIG_DEFAULT_PATH, dest)


def _finalize_from_legacy(root: Path, legacy: Path) -> BootstrapResult:
    dest = root / ROOT_CONFIG_NAME
    root.mkdir(parents=True, exist_ok=True)
    try:
        _install_config_from_source(legacy, dest)
    except DataLayoutError:
        raise
    except OSError as e:
        raise DataLayoutError(f"config copy failed: {e}") from e
    _write_marker(root)
    return BootstrapResult(status="finalized_legacy", root=root)


def _bootstrap_effective_root(root: Path) -> BootstrapResult:
    """對已通過 external-root gate 的 effective root 做定版。"""
    marker = _read_marker(root)
    root_config = root / ROOT_CONFIG_NAME
    legacy = _legacy_config_path()

    # 已定版
    if marker is not None and marker.get("complete") is True:
        if not _config_is_readable(root_config):
            raise DataLayoutError(
                f"layout marker complete but root config unreadable: {root_config}"
            )
        return BootstrapResult(status="already_complete", root=root)

    # marker 存在但 incomplete／損壞 → fail-closed（不得當已定版）
    if marker is not None:
        raise DataLayoutError(
            f"incomplete or invalid layout marker at {root / LAYOUT_MARKER_NAME}"
        )

    # 無 marker、root config 已存在 → 續寫 marker（或歧義阻斷）
    if root_config.is_file():
        if legacy.is_file():
            if _sha256(root_config) != _sha256(legacy):
                raise DataLayoutError(
                    "root config and legacy config differ without a complete marker"
                )
            _write_marker(root)
            return BootstrapResult(status="finalized_legacy", root=root)
        if not _config_is_readable(root_config):
            raise DataLayoutError(f"root config exists but is unreadable: {root_config}")
        # legacy 不在、root config 可讀 → 補 marker；若 root 原本還有其他內容則 recovered
        only_owned = all(
            p.name in {ROOT_CONFIG_NAME, LAYOUT_MARKER_NAME} or p.name.endswith(".tmp")
            for p in root.iterdir()
        ) if root.exists() else True
        _write_marker(root)
        if only_owned:
            return BootstrapResult(status="finalized_legacy", root=root)
        return BootstrapResult(status="recovered_existing", root=root)

    # 無 marker、無 root config
    root_was_empty = _root_is_empty(root)

    if legacy.is_file():
        return _finalize_from_legacy(root, legacy)

    # 無 legacy：fresh 或 recovered-existing
    root.mkdir(parents=True, exist_ok=True)
    try:
        _install_default_config(root_config)
    except DataLayoutError:
        raise
    except OSError as e:
        raise DataLayoutError(f"default config install failed: {e}") from e

    if root_was_empty:
        # fresh：marker 前用既有 initializer 建空 DB（顯式路徑，避免 get_db_path()
        # 在 gate／測試 monkeypatch 情境下落到錯誤 root）
        init_db(root / "openaver.db")
        _write_marker(root)
        return BootstrapResult(status="fresh", root=root)

    # recovered-existing：保留既有 DB，不呼叫 init_db
    _write_marker(root)
    return BootstrapResult(status="recovered_existing", root=root)


def bootstrap_data_layout() -> BootstrapResult:
    """入口閘：external-root gate → effective root 定版。

    失敗拋 DataLayoutError（或底層 I/O 例外原樣上拋）；成功回 BootstrapResult。
    """
    override_root = data_root.get_data_root()
    default_root = data_root.get_default_data_root()

    # CD-B5：external root 不隱式移植
    if override_root != default_root and not _root_has_valid_layout(override_root) and _root_has_legacy_data(default_root):
        raise DataLayoutError(
            "OPENAVER_DATA_DIR points to an empty/incomplete root while the "
            "default data root still has existing data; provision the external "
            "root explicitly before starting"
        )

    if override_root != default_root:
        # override 非空但無有效 layout（且上面沒擋——代表 default 也空）→ 仍阻斷
        if not _root_is_empty(override_root) and not _root_has_valid_layout(override_root):
            raise DataLayoutError(
                f"external data root is non-empty without a valid layout: {override_root}"
            )
        # 兩邊都空、或 override 已有有效 layout → 繼續對 override 定版
        if _root_has_valid_layout(override_root):
            return BootstrapResult(status="already_complete", root=override_root)

    return _bootstrap_effective_root(override_root)
