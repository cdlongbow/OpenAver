"""
tests/unit/test_generate_nfo.py
TASK-72b-T3：generate_nfo external_manager 參數 + F3 欄位 + poster/fanart 模式切換

TDD-lite：先跑 RED（實作前這些測試應全部 FAIL），實作後應全部 GREEN。
"""
import xml.etree.ElementTree as ET
from core.organizer import generate_nfo


def _read_nfo(tmp_path, **kwargs) -> str:
    """輔助：呼叫 generate_nfo，回傳 NFO 字串。"""
    nfo_path = tmp_path / "ABC-123.nfo"
    defaults = dict(
        number="ABC-123",
        title="Test Title",
        output_path=str(nfo_path),
    )
    defaults.update(kwargs)
    result = generate_nfo(**defaults)
    assert result is True, "generate_nfo 應回傳 True"
    return nfo_path.read_text(encoding="utf-8")


def _parse(nfo: str) -> ET.Element:
    """輔助：XML parse，回傳 root <movie> element。"""
    return ET.fromstring(nfo)


# ─────────────────────────────────────────────
# A. external_manager="off"（預設，回歸基線）
# ─────────────────────────────────────────────

class TestOffMode:
    """external_manager="off"（或不傳）時的行為"""

    def test_f3_fields_absent_explicit_off(self, tmp_path):
        """明確傳 external_manager='off' → 五個 F3 欄位全不存在"""
        nfo = _read_nfo(tmp_path, external_manager="off")
        assert "<lockdata>" not in nfo
        assert 'uniqueid type="num"' not in nfo and 'uniqueid type=\'num\'' not in nfo
        assert "<sorttitle>" not in nfo
        assert "<country>" not in nfo
        assert "<language>" not in nfo


    def test_poster_stem_no_suffix_off(self, tmp_path):
        """off + has_poster=False → <poster>{stem}.jpg"""
        nfo = _read_nfo(tmp_path, has_poster=False, external_manager="off")
        assert "<poster>ABC-123.jpg</poster>" in nfo

    def test_poster_stem_with_suffix_off(self, tmp_path):
        """off + has_poster=True → <poster>{stem}-poster.jpg"""
        nfo = _read_nfo(tmp_path, has_poster=True, external_manager="off")
        assert "<poster>ABC-123-poster.jpg</poster>" in nfo


    def test_thumb_always_stem_off(self, tmp_path):
        """off 模式：<thumb> 永遠是 {stem}.jpg（CD-12）"""
        nfo = _read_nfo(tmp_path, external_manager="off")
        assert "<thumb>ABC-123.jpg</thumb>" in nfo


# ─────────────────────────────────────────────
# B. external_manager="jellyfin"
# ─────────────────────────────────────────────

class TestJellyfinMode:
    """external_manager="jellyfin" 時的行為"""

    def test_f3_all_five_fields_present(self, tmp_path):
        """jellyfin → 五個 F3 欄位全部存在"""
        nfo = _read_nfo(tmp_path, external_manager="jellyfin")
        assert "<lockdata>true</lockdata>" in nfo
        assert "<country>Japan</country>" in nfo
        assert "<language>ja</language>" in nfo
        assert "<sorttitle>" in nfo
        # uniqueid type="num" 存在
        assert 'type="num"' in nfo or "type='num'" in nfo


    def test_thumb_follows_fanart_tag_jellyfin(self, tmp_path):
        """jellyfin + has_fanart=True → <thumb> 指向 {stem}-fanart.jpg（不是裸 stem）。

        T3/CD-112-5：`<thumb>` 改用既有 `fanart_tag` 變數（`core/organizer.py:755`），
        `has_fanart=True` 時指向 `-fanart.jpg`。原本這支測試不傳 `has_fanart`
        （預設 False），斷言值在翻面前後逐字相同、對翻面沒有鑑別力（T3 §H-7 已確認）；
        本支顯式傳 `has_fanart=True` 才第一次真正踩到 ② 的翻面路徑。
        # 真理表 Table 1 #7
        """
        nfo = _read_nfo(tmp_path, external_manager="jellyfin", has_fanart=True)
        assert "<thumb>ABC-123-fanart.jpg</thumb>" in nfo


# ─────────────────────────────────────────────
# C. external_manager="kodi"（與 jellyfin 相同：stem 長格式）
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# D. external_manager="emby"（等價 jellyfin）
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# E. off/jellyfin 回歸
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# D. html.escape（跨模式）
# ─────────────────────────────────────────────

class TestHtmlEscape:
    """特殊字元在 F3 欄位中正確 escape"""


    def test_title_with_special_chars_escaped_in_sorttitle(self, tmp_path):
        """title 含 & 和 < → <sorttitle> 內容正確 escape"""
        nfo = _read_nfo(tmp_path, number="ABC-123", title="T&<x",
                        external_manager="jellyfin")
        # sorttitle 應是 [ABC-123]T&amp;&lt;x
        assert "&amp;" in nfo
        assert "&lt;" in nfo
        # 用 parse 驗證 text value
        root = _parse(nfo)
        sorttitle = root.findtext("sorttitle")
        assert sorttitle == "[ABC-123]T&<x"  # ET 自動 unescape

