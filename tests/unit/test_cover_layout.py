"""TASK-112-T1: `core/cover_layout.py` 四個公開函式的落地測試。

⚠️ **範圍警語**：`resolve_cover_target` 本 PR 是 stub（無條件回 `<stem>.jpg`），本檔
只鎖「stub 契約」——不論 `external_manager`、不論磁碟狀態皆恆回同名候選，且
`os.path.exists` 從未被呼叫。**20 格差異化真值表（真正的三步規則）在 T3（PR2，
feature/112b），這裡刻意不測、也測不出來**——本檔的 stub 測試涵蓋 28 個
parametrize case（7 個 `external_manager` 值 × 4 種磁碟狀態，DoD 下限為 20）
只是為了證明「真的無條件」而非「巧合結果一樣」，不是提前驗收 T3 的行為。

`cover_base_stem` / `cover_candidates` / `nfo_image_flag` 三者是最終版，本檔的測試
即為正式驗收（非 stub 契約）。
"""

import os

import pytest

from core.cover_layout import (
    COVER_EXT,
    cover_base_stem,
    cover_candidates,
    nfo_image_flag,
    resolve_cover_target,
)


# ──────────────────────────────────────────────────────────────────────────
# cover_base_stem — card §7 邊界表全部 10 格
# ──────────────────────────────────────────────────────────────────────────

class TestCoverBaseStem:
    def test_01_no_suffix_plain_strip(self):
        """#1：無後綴，單純剝副檔名。"""
        assert cover_base_stem('/dir/ABC-123.jpg') == '/dir/ABC-123'

    def test_02_standard_fanart_suffix(self):
        """#2：標準 fanart 後綴。"""
        assert cover_base_stem('/dir/ABC-123-fanart.jpg') == '/dir/ABC-123'

    def test_03_standard_poster_suffix(self):
        """#3：標準 poster 後綴。"""
        assert cover_base_stem('/dir/ABC-123-poster.jpg') == '/dir/ABC-123'

    def test_04_fanart_in_middle_not_stripped(self):
        """#4：`-fanart` 在中段非尾端，`endswith` 判否，不得誤剝。"""
        assert (
            cover_base_stem('/dir/ABC-123-fanart-extra.jpg')
            == '/dir/ABC-123-fanart-extra'
        )

    def test_05_existing_ambiguity_native_filename_not_fixed(self):
        """#5：既有限制、逐字保留、非本 task 要修的 bug。

        `my-fanart.jpg` 字面上剛好命中 `-fanart` 尾碼，即使它其實是原生檔名
        （非衍生檔），既有實作（`web/routers/scanner.py::_cover_base_stem`）一樣
        會誤剝成 `my`。CD-112-9 要求逐字等價升格，**不在本 task 修正這個二義性**。
        """
        assert cover_base_stem('/dir/my-fanart.jpg') == '/dir/my'

    def test_06_case_sensitive_uppercase_not_stripped(self):
        """#6：既有限制、逐字保留、非本 task 要修的 bug。

        大小寫敏感是既有實作的既有限制：`-FANART`（大寫）不會被
        `str.endswith('-fanart')` 命中，**不做大小寫正規化**。
        """
        assert (
            cover_base_stem('/dir/ABC-123-FANART.jpg') == '/dir/ABC-123-FANART'
        )

    def test_07_splitext_only_strips_last_extension(self):
        """#7：`splitext` 只剝最後一個副檔名，中段的 `.vol1` 不受影響。"""
        assert cover_base_stem('/dir/ABC-123.vol1.jpg') == '/dir/ABC-123.vol1'

    def test_08_windows_backslash_path_unaffected(self):
        """#8：Windows 反斜線路徑，純字串尾碼運算不需要碰路徑分隔符。"""
        assert (
            cover_base_stem('C:\\videos\\ABC-123-fanart.jpg')
            == 'C:\\videos\\ABC-123'
        )

    def test_09_dir_name_containing_fanart_unaffected(self):
        """#9：目錄名含 `-fanart`、檔名正常，不受目錄名影響。"""
        assert (
            cover_base_stem('/dir-fanart/ABC-123.jpg') == '/dir-fanart/ABC-123'
        )

    def test_10_strips_only_once_break(self):
        """#10：只剝一次，剝掉尾端 `-fanart` 後不會連 `-poster` 也剝。

        ⚠️ 這一格**釘不住 `break`**：迴圈的檢查順序是 `('-poster', '-fanart')`，
        對 `-poster-fanart` 而言 `-fanart` 已是迴圈最後一個候選，拿掉 `break`
        結果完全相同（review mutation 實測：拿掉 `break` → 0/45 轉紅）。
        真正釘住 `break` 的是下面 `test_10b`——**兩支要一起看，不可只留一支**。
        """
        assert (
            cover_base_stem('/dir/ABC-123-poster-fanart.jpg')
            == '/dir/ABC-123-poster'
        )

    def test_10b_break_pins_single_strip_reverse_order(self):
        """#10b：`-fanart` 在前、`-poster` 在後——**唯一能讓 `break` 產生分歧的排列**。

        `-poster` 是迴圈第一個候選，命中即 `break`；若拿掉 `break`，迴圈會繼續
        比對 `-fanart` 並剝掉第二層，回傳 `/dir/ABC` 而非 `/dir/ABC-fanart`。

        為什麼補這一格（Sonnet review P2，mutation 實證）：`cover_base_stem` 的
        docstring 宣稱「只剝一次」，但原本的邊界表 10 格**沒有任何一格**能讓那個
        `break` 產生行為差異——宣稱與守衛脫鉤。CD-112-9 要求本函式與
        `web/routers/scanner.py::_cover_base_stem` 逐字等價，等價的每一個構成要素
        都必須有守衛，否則 T2c 把 scanner 改成 import 本模組時，等價性只剩宣稱。
        """
        assert (
            cover_base_stem('/dir/ABC-fanart-poster.jpg')
            == '/dir/ABC-fanart'
        )


# ──────────────────────────────────────────────────────────────────────────
# cover_candidates — 順序固定 (同名, fanart)，零 os.path.exists 呼叫
# ──────────────────────────────────────────────────────────────────────────

class TestCoverCandidates:
    def test_order_is_same_name_then_fanart(self):
        assert cover_candidates('/dir/ABC-123') == (
            '/dir/ABC-123.jpg',
            '/dir/ABC-123-fanart.jpg',
        )

    def test_uses_cover_ext_constant(self):
        same, fanart = cover_candidates('/dir/ABC-123')
        assert same == '/dir/ABC-123' + COVER_EXT
        assert fanart == '/dir/ABC-123-fanart' + COVER_EXT

    def test_never_touches_disk(self, monkeypatch):
        """零 os.path.exists 呼叫（純字串串接，CD-112-3 防彈跳依據）。"""

        def _boom(_path):
            raise AssertionError('cover_candidates must not call os.path.exists')

        monkeypatch.setattr(os.path, 'exists', _boom)
        assert cover_candidates('/dir/ABC-123') == (
            '/dir/ABC-123.jpg',
            '/dir/ABC-123-fanart.jpg',
        )


# ──────────────────────────────────────────────────────────────────────────
# resolve_cover_target — stub 契約：{off, jellyfin, emby, kodi, 非法值}
#   × {兩候選皆無, 只有同名, 只有 fanart, 兩者皆在} = 20 格，恆回 <stem>.jpg
#   且 os.path.exists 從未被呼叫（monkeypatch 佐證，非巧合結果）
# ──────────────────────────────────────────────────────────────────────────

_EXTERNAL_MANAGERS = ['off', 'jellyfin', 'emby', 'kodi', 'plex', '', 'JELLYFIN']
_DISK_STATES = [
    'neither',
    'same_name_only',
    'fanart_only',
    'both',
]


def _make_disk_state(tmp_path, base_stem, state):
    """依 state 在 tmp_path 底下造出對應候選檔案（stub 不應該去讀它們）。"""
    same = base_stem + '.jpg'
    fanart = base_stem + '-fanart.jpg'
    if state in ('same_name_only', 'both'):
        open(same, 'w').close()
    if state in ('fanart_only', 'both'):
        open(fanart, 'w').close()


class TestResolveCoverTargetStubContract:
    @pytest.mark.parametrize('external_manager', _EXTERNAL_MANAGERS)
    @pytest.mark.parametrize('disk_state', _DISK_STATES)
    def test_stub_always_returns_same_name_candidate(
        self, tmp_path, monkeypatch, external_manager, disk_state
    ):
        base_stem = str(tmp_path / 'ABC-123')
        _make_disk_state(tmp_path, base_stem, disk_state)

        def _boom(_path):
            raise AssertionError(
                'resolve_cover_target stub must not call os.path.exists'
            )

        monkeypatch.setattr(os.path, 'exists', _boom)

        result = resolve_cover_target(base_stem, external_manager)

        assert result == base_stem + '.jpg'


# ──────────────────────────────────────────────────────────────────────────
# nfo_image_flag — 四格真值表：只有 wrote_this_run=False 且磁碟不存在才回 False
# ──────────────────────────────────────────────────────────────────────────

class TestNfoImageFlag:
    def test_wrote_true_disk_missing_returns_true(self, tmp_path):
        base_stem = str(tmp_path / 'ABC-123')
        assert nfo_image_flag(base_stem, '-poster', True) is True

    def test_wrote_true_disk_exists_returns_true(self, tmp_path):
        base_stem = str(tmp_path / 'ABC-123')
        open(base_stem + '-poster.jpg', 'w').close()
        assert nfo_image_flag(base_stem, '-poster', True) is True

    def test_wrote_false_disk_exists_returns_true(self, tmp_path):
        base_stem = str(tmp_path / 'ABC-123')
        open(base_stem + '-fanart.jpg', 'w').close()
        assert nfo_image_flag(base_stem, '-fanart', False) is True

    def test_wrote_false_disk_missing_returns_false(self, tmp_path):
        base_stem = str(tmp_path / 'ABC-123')
        assert nfo_image_flag(base_stem, '-fanart', False) is False
