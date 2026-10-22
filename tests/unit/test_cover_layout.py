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
    cover_base_stem,
    nfo_image_flag,
    resolve_cover_target,
    same_target_verdict,
)


# ──────────────────────────────────────────────────────────────────────────
# cover_base_stem — card §7 邊界表全部 10 格
# ──────────────────────────────────────────────────────────────────────────

class TestCoverBaseStem:

    def test_02_standard_fanart_suffix(self):
        """#2：標準 fanart 後綴。"""
        assert cover_base_stem('/dir/ABC-123-fanart.jpg') == '/dir/ABC-123'


# ──────────────────────────────────────────────────────────────────────────
# cover_candidates — 順序固定 (同名, fanart)，零 os.path.exists 呼叫
# ──────────────────────────────────────────────────────────────────────────


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

    @pytest.mark.parametrize(
        'external_manager,disk_state',
        [('off', 'neither'), ('jellyfin', 'neither'), ('off', 'fanart_only'), ('jellyfin', 'both')],
        ids=['neither-off', 'neither-jellyfin', 'fanart_only-off', 'both-jellyfin'],
    )
    def test_three_step_rule_28_cells(
        self, tmp_path, external_manager, disk_state
    ):
        base_stem = str(tmp_path / 'ABC-123')
        _make_disk_state(tmp_path, base_stem, disk_state)

        result = resolve_cover_target(base_stem, external_manager)

        assert result == _expected_target(base_stem, external_manager, disk_state)


# ──────────────────────────────────────────────────────────────────────────
# nfo_image_flag — 四格真值表：只有 wrote_this_run=False 且磁碟不存在才回 False
# ──────────────────────────────────────────────────────────────────────────

class TestNfoImageFlag:


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


