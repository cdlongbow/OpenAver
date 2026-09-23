"""tests/unit/test_data_root.py — core.data_root resolver 正向鎖（TASK-153b-T1／T2）。

期望值一律由本檔位置字面組出，不得呼叫被測 resolver 同源路徑推算。
比對左邊必須讀 production 模組真正在用的值（不得自己串）。
"""
from pathlib import Path
from types import SimpleNamespace

import core.actress_photo as actress_photo
import core.config as core_config
import core.data_root as data_root_module
import core.thumbnail_cache as thumbnail_cache
import core.wishlist_cover_cache as wishlist_cover_cache
from core.database import get_db_path
from core.readonly_paths import resolve_output_root


# tests/unit/test_data_root.py → parents[2] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_OUTPUT = _REPO_ROOT / "output"
# T2：CONFIG_PATH 切到 <root>/config.json；CONFIG_DEFAULT_PATH 仍為程式區 template
_EXPECTED_CONFIG = _EXPECTED_OUTPUT / "config.json"
_EXPECTED_CONFIG_DEFAULT = _REPO_ROOT / "web" / "config.default.json"
_EXPECTED_DB = _EXPECTED_OUTPUT / "openaver.db"
_EXPECTED_DB_WAL = _EXPECTED_OUTPUT / "openaver.db-wal"
_EXPECTED_DB_SHM = _EXPECTED_OUTPUT / "openaver.db-shm"
_EXPECTED_GFRIENDS = _EXPECTED_OUTPUT / "Gfriends"
_EXPECTED_THUMB = _EXPECTED_OUTPUT / "thumb"
_EXPECTED_WISHLIST_COVER = _EXPECTED_OUTPUT / "wishlist_cover"
_EXPECTED_LIB = _EXPECTED_OUTPUT / "lib"


def test_default_root_matches_existing_output_dir():
    """resolver 與 production 衍生路徑皆與既有 <repo>/output 體系逐字相同。"""
    assert str(data_root_module.get_data_root()) == str(_EXPECTED_OUTPUT)

    # config／config default — production module-level 常數
    assert str(core_config.CONFIG_PATH) == str(_EXPECTED_CONFIG)
    assert str(core_config.CONFIG_DEFAULT_PATH) == str(_EXPECTED_CONFIG_DEFAULT)

    # DB（含 WAL／SHM 同目錄）— production get_db_path()
    db_path = get_db_path()
    assert str(db_path) == str(_EXPECTED_DB)
    assert str(db_path.parent / "openaver.db-wal") == str(_EXPECTED_DB_WAL)
    assert str(db_path.parent / "openaver.db-shm") == str(_EXPECTED_DB_SHM)

    # Gfriends — production module-level 常數
    assert str(actress_photo.GFRIENDS_DIR) == str(_EXPECTED_GFRIENDS)

    # thumb — 對外入口 thumb_file_for → _thumb_dir()（= get_db_path().parent / "thumb"）
    thumb_dir = thumbnail_cache.thumb_file_for("file:///probe").parent.parent
    assert str(thumb_dir) == str(_EXPECTED_THUMB)

    # wishlist_cover — 對外入口 cover_file_for → get_db_path().parent / "wishlist_cover" / …
    wishlist_cover_dir = wishlist_cover_cache.cover_file_for("PROBE").parent.parent
    assert str(wishlist_cover_dir) == str(_EXPECTED_WISHLIST_COVER)

    # lib — readonly_paths off-mode：resolve_output_root → …/lib/<name>，取其 parent
    lib_with_name = Path(
        resolve_output_root(
            SimpleNamespace(path="/tmp/probe-source"),
            {"scraper": {"external_manager": "off"}},
        )
    )
    assert str(lib_with_name.parent) == str(_EXPECTED_LIB)


def test_openaver_data_dir_env_var_is_effective(tmp_path, monkeypatch):
    """OPENAVER_DATA_DIR 生效：get_data_root() 回傳 env 路徑，且 resolver 本身零建立。

    external-root gate（空 override + 本機有舊資料 → 阻斷）由
    tests/unit/test_data_layout.py::test_external_empty_root_with_local_legacy_is_rejected 鎖住。
    """
    env_dir = tmp_path / "never_created"
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(env_dir))

    root = data_root_module.get_data_root()
    assert str(root) == str(env_dir)
    assert not env_dir.exists()
    assert not (env_dir / "openaver.db").exists()
    # default root 仍可獨立取得，供 gate 比較
    assert str(data_root_module.get_default_data_root()) == str(_EXPECTED_OUTPUT)


def test_resolve_gallery_output_path_empty_returns_data_root():
    """空字串 → get_data_root()（跟著資料根走）。"""
    from core.data_root import resolve_gallery_output_path, get_data_root

    assert resolve_gallery_output_path("") == get_data_root()


def test_resolve_gallery_output_path_whitespace_returns_data_root():
    """純空白 → 等同空值，回 get_data_root()。"""
    from core.data_root import resolve_gallery_output_path, get_data_root

    assert resolve_gallery_output_path("  ") == get_data_root()


def test_resolve_gallery_output_path_relative_uses_project_root():
    """非空相對值 → get_project_root() / value。"""
    from core.data_root import resolve_gallery_output_path, get_project_root

    assert resolve_gallery_output_path("custom_dir") == get_project_root() / "custom_dir"


def test_resolve_gallery_output_path_absolute_unchanged():
    """非空絕對值 → 原樣 Path。"""
    from core.data_root import resolve_gallery_output_path

    assert resolve_gallery_output_path("/abs/path") == Path("/abs/path")
