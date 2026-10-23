"""
Unit tests for core/settings_link.py — find_matched_directory()
全 mock，無外部依賴。
"""
from unittest.mock import patch
from core.path_utils import to_file_uri as _real_to_file_uri


# ─────────────────────────────────────────────
# import subject under test
# ─────────────────────────────────────────────

from core.settings_link import find_matched_directory  # noqa: E402


# ─────────────────────────────────────────────
# T1: empty favorite → None
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# T2: exact match
# ─────────────────────────────────────────────

class TestExactMatch:

    def test_uri_form_directory_matched(self):
        """PR#91: directory 已是 file:/// URI（schema「FS 路徑或 URI」）→ 仍能命中。

        pre-fix `normalize_path` 對 URI 原樣通過 → `to_file_uri` 二次包成
        file:///file:///… → 永不命中（RED）。改用 uri_to_fs_path 後冪等命中。
        favorite 端維持 FS 路徑（真實使用者最愛資料夾）。
        """
        uri_dir = _real_to_file_uri('/home/user/media')
        with patch('core.settings_link.expand_env_vars', return_value='/home/user/media/jav'), \
             patch('core.settings_link.normalize_path', side_effect=lambda x: x), \
             patch('core.settings_link.to_file_uri', side_effect=_real_to_file_uri):
            result = find_matched_directory('/home/user/media/jav', [uri_dir])
        assert result == uri_dir


# ─────────────────────────────────────────────
# T3: subdirectory match
# ─────────────────────────────────────────────

class TestSubdirectoryMatch:
    def test_subdirectory_returns_parent_directory(self):
        """favorite 是某 directory 子目錄 → 回傳父 directory"""
        with patch('core.settings_link.expand_env_vars', return_value='/mnt/e/media/jav'), \
             patch('core.settings_link.normalize_path', side_effect=lambda x: x), \
             patch('core.settings_link.to_file_uri', side_effect=_real_to_file_uri):
            result = find_matched_directory(
                '/mnt/e/media/jav',
                ['/mnt/e/media', '/mnt/f/videos']
            )
        assert result == '/mnt/e/media'


# ─────────────────────────────────────────────
# T4: no match
# ─────────────────────────────────────────────

class TestNoMatch:

    def test_prefix_collision_not_matched(self):
        """E:/media 不可誤匹配 E:/media2 (前綴碰撞防護)"""
        with patch('core.settings_link.expand_env_vars', return_value='/mnt/e/media2'), \
             patch('core.settings_link.normalize_path', side_effect=lambda x: x), \
             patch('core.settings_link.to_file_uri', side_effect=_real_to_file_uri):
            result = find_matched_directory(
                '/mnt/e/media2',
                ['/mnt/e/media']
            )
        assert result is None


# ─────────────────────────────────────────────
# T5: empty directories list
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# T6: WSL path_mappings forwarded
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# T7: expand_env_vars ValueError on Linux/Mac
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# T8: tilde expansion
# ─────────────────────────────────────────────

