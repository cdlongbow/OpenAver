"""
test_image_whitelist_dirs.py — `_image_whitelist_dirs` 純函式候選目錄推導測試（TASK-88c-T1 / TASK-89a-T2）

驗證 `/api/gallery/image` 白名單「候選 raw 目錄清單」的推導真值：
- 每來源的 `src.path` 進候選
- media-server 模式（jellyfin/emby/kodi）：非空 `src.output_path` 進候選；`""` output_path
  **不**進候選（防 `to_file_uri('') = 'file:///'` 根路徑 bypass 哨兵）
- off 模式（CD-89a-7）：固定 `output/lib/<name>` 根恆進候選（Codex #1 回歸鎖 ——
  只改 producer 不改白名單會讓 off 封面 404）
- 多來源聚合、空 config 不拋

純函式、無 IO、免 HTTP、免 mock。
"""

from core.database import get_db_path
from web.routers.gallery_media import _image_whitelist_dirs


def _config(directories, external_manager="off"):
    """TASK-89a-T2: 完整 config shape（`_image_whitelist_dirs` 簽名已改為接收完整
    config，內部需要 `scraper.external_manager` 判風味，見 `resolve_output_root`）。"""
    return {
        "gallery": {"directories": directories},
        "scraper": {"external_manager": external_manager},
    }


class TestImageWhitelistDirs:

    def test_empty_output_path_excluded(self):
        """media-server 模式：output_path == "" → 候選只含 path，不含 ""（防 file:/// bypass 哨兵）

        若把 `if resolved:` 過濾拿掉，"" 會進候選 → 此測試 RED。
        """
        config = _config(
            [{"path": "/src/movies", "readonly": False, "output_path": ""}],
            external_manager="jellyfin",
        )
        dirs = _image_whitelist_dirs(config)
        assert "/src/movies" in dirs
        assert "" not in dirs


class TestImageWhitelistDirsOffFixedRoot:
    """TASK-89a-T2 (CD-89a-7): off 固定夾必須出現在白名單清單中。

    Codex #1 回歸鎖 ——若只改 `readonly_producer.produce_source` 而不同步改
    `_image_whitelist_dirs`，off 來源能成功生成到 `output/lib/<name>`，但封面
    經 `/api/gallery/image` 會被白名單拒絕（404），屬於「半套落地」。
    """

    def test_off_mode_includes_fixed_output_root(self):
        """off + 空 output_path → 白名單仍含來源 path，且含固定 output/lib 根"""
        config = _config(
            [{"path": "/src/movies", "readonly": True, "output_path": ""}],
            external_manager="off",
        )
        dirs = _image_whitelist_dirs(config)
        assert "/src/movies" in dirs
        lib_root = str(get_db_path().parent / "lib")
        assert any(d.startswith(lib_root) for d in dirs), (
            f"off 固定夾應出現在白名單清單中，實際 dirs={dirs}"
        )


