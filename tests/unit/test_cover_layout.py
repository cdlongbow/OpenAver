"""TASK-112-T1/T3: `core/cover_layout.py` 五個公開函式的落地測試。

`resolve_cover_target` 自 T3（PR2，feature/112b）起是三步規則本體（CD-112-3／
CD-112-3b，§6.4）：① `<stem>.jpg` 存在 → 沿用 ② `<stem>-fanart.jpg` 存在 → 沿用
③ 皆無 → `external_manager in STEM_IMAGE_MODES` ? fanart 候選 : 同名候選（正向
白名單，非法值 fail-closed）。三步規則下①②兩步必須呼叫 `os.path.exists`——
`TestResolveCoverTargetThreeStepRule` 鎖的是這個真值表本身，共 28 個 parametrize
case（7 個 `external_manager` 值 × 4 種磁碟狀態）＋另補 `None` 一格。

`cover_base_stem` / `cover_candidates` / `nfo_image_flag` / `same_target_verdict`
四者是最終版，本檔的測試即為正式驗收。
"""

import os

import pytest

from core.config import STEM_IMAGE_MODES
from core.cover_layout import (
    COVER_EXT,
    cover_base_stem,
    cover_candidates,
    nfo_image_flag,
    resolve_cover_target,
    same_target_verdict,
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
# resolve_cover_target — 三步規則本體（T3，CD-112-3／CD-112-3b）：7 個
#   external_manager 值 × {兩候選皆無, 只有同名, 只有 fanart, 兩者皆在} = 28 格，
#   ＋另補 external_manager=None（neither 態）一格。①②兩步必須呼叫
#   os.path.exists（透過 cover_candidates 給的兩個候選路徑）——與 T1 的 stub
#   「零 I/O」契約互斥，故不再用 monkeypatch 擋 os.path.exists。
# ──────────────────────────────────────────────────────────────────────────

_EXTERNAL_MANAGERS = ['off', 'jellyfin', 'emby', 'kodi', 'plex', '', 'JELLYFIN']
_DISK_STATES = [
    'neither',
    'same_name_only',
    'fanart_only',
    'both',
]


def _make_disk_state(tmp_path, base_stem, state):
    """依 state 在 tmp_path 底下造出對應候選檔案。"""
    same = base_stem + '.jpg'
    fanart = base_stem + '-fanart.jpg'
    if state in ('same_name_only', 'both'):
        open(same, 'w').close()
    if state in ('fanart_only', 'both'):
        open(fanart, 'w').close()


def _expected_target(base_stem, external_manager, disk_state):
    """依三步規則（§6.4）逐格推算預期值，供下面的 parametrize 案例比對。

    ①同名候選存在 / ④both（同名也存在，① 優先）→ 同名；②只有 fanart 候選存在
    → fanart；③兩者皆無 → 依 flavour 新建（白名單內 → fanart，否則 fail-closed
    回同名）。順序必須是「先看磁碟狀態，磁碟已決定就不看 external_manager」——
    這正是 CD-112-3 的防彈跳鎖（`both` 態不論 flavour 一律回同名）。
    """
    same = base_stem + '.jpg'
    fanart = base_stem + '-fanart.jpg'
    if disk_state in ('same_name_only', 'both'):
        return same
    if disk_state == 'fanart_only':
        return fanart
    # disk_state == 'neither'：③ 依 flavour 新建，正向白名單、非法值 fail-closed
    return fanart if external_manager in STEM_IMAGE_MODES else same


class TestResolveCoverTargetThreeStepRule:
    """鎖三步規則（CD-112-3／CD-112-3b，§6.4）本體，取代 T1 的 stub 契約測試。

    原本這裡鎖的是「stub 恆回同名、且 os.path.exists 從未被呼叫」——T3 把
    `resolve_cover_target` 從 stub 換成三步規則之後，①②兩步必須呼叫
    `os.path.exists`（透過 `cover_candidates` 給的兩個候選路徑），舊有的
    `_boom` monkeypatch 守衛與新規格互斥，因此整支改寫（class 改名，不再叫
    `StubContract`）。沿用既有的 `_EXTERNAL_MANAGERS` / `_DISK_STATES` 兩條軸
    與 `_make_disk_state` helper——三步規則需要的磁碟狀態建檔邏輯與 stub 版本
    相同，不重寫。
    """

    @pytest.mark.parametrize('external_manager', _EXTERNAL_MANAGERS)
    @pytest.mark.parametrize('disk_state', _DISK_STATES)
    def test_three_step_rule_28_cells(
        self, tmp_path, external_manager, disk_state
    ):
        base_stem = str(tmp_path / 'ABC-123')
        _make_disk_state(tmp_path, base_stem, disk_state)

        result = resolve_cover_target(base_stem, external_manager)

        assert result == _expected_target(base_stem, external_manager, disk_state)

    def test_none_external_manager_neither_state_fails_closed_to_same_name(
        self, tmp_path
    ):
        """補 `None` 一格（config 缺 key 時的實際型別，既有軸沒有）。

        `neither` 態下 `external_manager=None` 不在 `STEM_IMAGE_MODES` 白名單內，
        必須 fail-closed 落到「同名」——與 `plex`/`''`/`JELLYFIN` 三個非法值在
        `neither` 態的結論一致（那三格已由上面的 28 格參數化案例涵蓋）。
        """
        base_stem = str(tmp_path / 'ABC-123')
        _make_disk_state(tmp_path, base_stem, 'neither')

        result = resolve_cover_target(base_stem, None)

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


# ──────────────────────────────────────────────────────────────────────────
# same_target_verdict — Codex PR review P1（feature/112a-T2c，2026-08-04），
# 拆成 (is_same, certain) 雙訊號後由 Stage 2 review P1（2026-08-04）推翻前身
# is_same_target 的單一布林設計。CD-112-8 原文「路徑相等或 os.path.samefile」
# 的落地，補回被 TASK-112-T2c 裁決 3 錯誤收窄掉的 inode 別名感知。
# 五格真值表（同 docstring）：
#   src==dst              → (True,  True)
#   samefile→True（別名）  → (True,  True)
#   samefile→False         → (False, True)
#   FileNotFoundError      → (False, True)
#   其他 OSError（未知）    → (True,  False)
# ──────────────────────────────────────────────────────────────────────────

class TestSameTargetVerdict:
    def test_string_equal_returns_true_certain(self, tmp_path):
        p = str(tmp_path / 'a.jpg')
        assert same_target_verdict(p, p) == (True, True)

    def test_different_unrelated_files_returns_false_certain(self, tmp_path):
        a = tmp_path / 'a.jpg'
        b = tmp_path / 'b.jpg'
        a.write_bytes(b'aaa')
        b.write_bytes(b'bbb')
        assert same_target_verdict(str(a), str(b)) == (False, True)

    def test_dst_not_exists_returns_false_certain(self, tmp_path):
        """最常見的情境：dst 是尚未產生的衍生檔，直接呼叫 samefile 會拋
        FileNotFoundError——這裡驗證專屬的 except FileNotFoundError 分支接住它，
        正常回 (False, True)（不同檔、確定，照常寫入）而不是誤落入
        fail-closed 回 (True, False)。"""
        src = tmp_path / 'cover.jpg'
        src.write_bytes(b'x')
        dst = tmp_path / 'ABC-123-poster.jpg'
        assert not dst.exists()
        assert same_target_verdict(str(src), str(dst)) == (False, True)

    def test_hardlink_alias_returns_true_certain(self, tmp_path):
        src = tmp_path / 'cover.jpg'
        src.write_bytes(b'x')
        dst = tmp_path / 'ABC-123-poster.jpg'
        try:
            os.link(str(src), str(dst))
        except OSError as e:
            pytest.skip(f"hardlink 在當前環境無法建立: {e}")
        assert str(src) != str(dst)
        assert same_target_verdict(str(src), str(dst)) == (True, True)

    def test_symlink_alias_returns_true_certain(self, tmp_path):
        src = tmp_path / 'cover.jpg'
        src.write_bytes(b'x')
        dst = tmp_path / 'ABC-123-poster.jpg'
        try:
            os.symlink(str(src), str(dst))
        except OSError as e:
            pytest.skip(f"symlink 在當前環境無法建立: {e}")
        assert str(src) != str(dst)
        assert same_target_verdict(str(src), str(dst)) == (True, True)

    def test_broken_symlink_returns_false_certain(self, tmp_path):
        """dst 是指向不存在目標的 broken symlink：samefile 對它 follow 後同樣拋
        FileNotFoundError，被專屬的 except FileNotFoundError 分支接住，視為不同檔
        且確定（照常寫入），而不是誤判成 src 的別名——底下沒有真正的檔案內容
        可以被誤判。"""
        src = tmp_path / 'cover.jpg'
        src.write_bytes(b'x')
        dst = tmp_path / 'ABC-123-poster.jpg'
        missing_target = tmp_path / 'does-not-exist.jpg'
        try:
            os.symlink(str(missing_target), str(dst))
        except OSError as e:
            pytest.skip(f"symlink 在當前環境無法建立: {e}")
        assert os.path.lexists(str(dst)) and not os.path.exists(str(dst))
        assert same_target_verdict(str(src), str(dst)) == (False, True)

    def test_samefile_raises_fails_closed_to_true_uncertain(self, tmp_path, monkeypatch):
        """fail-closed 決策：samefile 拋出例外（權限被拒／race／網路磁碟等）時
        `is_same=True`（呼叫端跳過寫入）——因為誤判「不同檔」而照常寫入最壞情況
        是就地毀損使用者原檔（不可逆），跳過寫入最壞情況只是少產一張衍生圖
        （可補救）。但 `certain=False`：呼叫端不能把這格宣稱成功（Stage 2 review
        P1，若混成單一布林會讓 NFO 寫出懸空 tag）。這裡用 monkeypatch 確定性地
        模擬 samefile 拋例外（真實 PermissionError 已用 chmod 手動重現過，但那條
        路徑在 CI 上不可移植，這裡改用 monkeypatch 讓測試確定性可重跑）。"""
        src = tmp_path / 'cover.jpg'
        dst = tmp_path / 'ABC-123-poster.jpg'
        src.write_bytes(b'x')
        dst.write_bytes(b'y')

        def _raise(*args, **kwargs):
            raise PermissionError("simulated permission denied")

        monkeypatch.setattr(os.path, 'samefile', _raise)
        assert same_target_verdict(str(src), str(dst)) == (True, False)

    def test_fail_closed_branch_must_not_be_silent(self, tmp_path, monkeypatch, caplog):
        """fail-closed 不得靜默（pre-merge Stage 1 gemini P3-1）。

        改動前，「目標路徑根本不可寫」這類硬性 I/O 錯誤（不合法字元、
        `NotADirectoryError`、WinError 123…）會在 `copy2` 階段炸出，被呼叫端的
        `except Exception` 記成一行「fanart 複製失敗」。改成 preflight 之後，
        它們被 `same_target_verdict` 的 `except OSError` 攔下並 fail-closed 回
        `(True, False)`——若不記錄，就變成**靜默吞噬**，出事時查不到任何線索
        （雖然此版不再回報假成功，call site 會老實回 False，但沒有日誌仍難查）。

        這支鎖的是「有留下日誌」，不是日誌的確切措辭。
        mutation：把 `except OSError` 分支的 logger.warning 拿掉 → 本支單獨轉紅。
        """
        src = tmp_path / 'cover.jpg'
        dst = tmp_path / 'ABC-123-poster.jpg'
        src.write_bytes(b'x')
        dst.write_bytes(b'y')

        def _raise(*args, **kwargs):
            raise NotADirectoryError('simulated invalid destination path')

        monkeypatch.setattr(os.path, 'samefile', _raise)
        with caplog.at_level('WARNING', logger='OpenAver.core.cover_layout'):
            assert same_target_verdict(str(src), str(dst)) == (True, False)
        assert caplog.records, (
            'fail-closed 分支必須留下日誌——否則硬性 I/O 錯誤會被靜默吞掉'
        )
        assert 'simulated invalid destination path' in caplog.text, (
            '日誌必須帶上原始例外訊息，否則查不出是哪一種 OSError'
        )

    def test_samefile_filenotfounderror_returns_false_certain_not_fail_closed(
        self, tmp_path, monkeypatch
    ):
        """Codex PR review 第二輪 P1（2026-08-04）：這支直接、確定性地釘住
        `FileNotFoundError` 這個**分類規則**本身——與上面 `test_dst_not_exists_
        returns_false_certain` / `test_broken_symlink_returns_false_certain` 驗的
        是不同層次。那兩支驗的是「特定實體情境」（dst 從一開始就不存在／broken
        symlink），走到 `samefile` 時剛好拋出 `FileNotFoundError`；這一支不管
        實體上 src/dst 是否存在，直接 monkeypatch `os.path.samefile` 強制拋出
        `FileNotFoundError`，驗證的是「不論成因為何，`FileNotFoundError` 一律
        分流回 `(False, True)`，不落入 `except OSError` 的 fail-closed」這條
        規則本身——這正是舊版 `os.path.exists(dst)` 前置檢查 + 廣義
        `except OSError` 會漏接的 race：`exists()` 回 True 之後、`samefile()`
        呼叫之前 dst 被外部程序刪除，導致 `samefile` 拋 `FileNotFoundError`，
        舊版會被 `except OSError` 吞掉、誤回 True（回報已產圖但檔案不存在，
        重新製造 NFO 懸空引用）。src/dst 在這裡都刻意造成存在的正常檔案，
        證明回 `(False, True)` 完全是因為分類規則命中，不是因為它們本來就
        不存在。"""
        src = tmp_path / 'cover.jpg'
        dst = tmp_path / 'ABC-123-poster.jpg'
        src.write_bytes(b'x')
        dst.write_bytes(b'y')

        def _raise(*args, **kwargs):
            raise FileNotFoundError("simulated race: dst removed mid-check")

        monkeypatch.setattr(os.path, 'samefile', _raise)
        assert same_target_verdict(str(src), str(dst)) == (False, True)
