"""
test_cover_image.py — E1-E24 測試 find_cover_image() 4 層 fallback + NFO thumb 支援
"""
from pathlib import Path
from unittest.mock import patch


from core.gallery_scanner import VideoScanner


# ─── NFO helper ───────────────────────────────────────────────────────────────

def make_nfo(path: Path, thumb: str = None) -> Path:
    """建立最小 NFO，可選含 <thumb> 元素"""
    thumb_tag = f"  <thumb>{thumb}</thumb>\n" if thumb else ""
    content = f'<?xml version="1.0" encoding="utf-8"?>\n<movie>\n{thumb_tag}</movie>'
    path.write_text(content, encoding='utf-8')
    return path


# ─── TestL1SameName ───────────────────────────────────────────────────────────

class TestL1SameName:
    """E1, E2 — 同名圖片優先（回歸）"""

    def test_e1_same_name_jpg(self, tmp_path):
        """E1: abc-123.mp4 + abc-123.jpg → 命中 L1"""
        (tmp_path / "abc-123.mp4").write_bytes(b"")
        jpg = tmp_path / "abc-123.jpg"
        jpg.write_bytes(b"")
        scanner = VideoScanner()
        result = scanner.find_cover_image(str(tmp_path / "abc-123.mp4"))
        assert result == str(jpg)


# ─── TestL2StandardNames ──────────────────────────────────────────────────────

class TestL2StandardNames:
    """E3, E4 — 標準名稱（fanart/poster/cover/folder）回歸"""

    def test_e3_cover_fallback(self, tmp_path):
        """E3: 無同名圖 + cover.jpg → 命中 L2"""
        (tmp_path / "abc-123.mp4").write_bytes(b"")
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"")
        scanner = VideoScanner()
        result = scanner.find_cover_image(str(tmp_path / "abc-123.mp4"))
        assert result == str(cover)


# ─── TestL3NfoThumb ───────────────────────────────────────────────────────────

class TestL3NfoThumb:
    """E5-E10, E21, E22 — NFO <thumb> 路徑解析（新邏輯 + 跨平台）"""


    def test_e22_unc_path_wsl_valueerror(self, tmp_path):
        """E22: UNC backslash path → WSL normalize_path 拋 ValueError → None (fall through)"""
        scanner = VideoScanner()
        # 在 WSL 環境，normalize_path('\\\\NAS\\share\\...') 會拋 ValueError
        with patch('core.gallery_scanner.normalize_path', side_effect=ValueError("WSL 環境不支援 SMB 路徑")):
            result = scanner._resolve_thumb_path(
                "\\\\NAS\\share\\cover.jpg",
                tmp_path
            )
        assert result is None

    def test_e25_windows_style_relative_thumb(self, tmp_path):
        """E25: Windows-authored NFO 相對路徑 'covers\\poster.jpg' 在 POSIX 應正確解析"""
        covers_dir = tmp_path / "covers"
        covers_dir.mkdir()
        poster = covers_dir / "poster.jpg"
        poster.write_bytes(b"")

        scanner = VideoScanner()
        # 第三方 Windows-authored NFO 的 <thumb> 值
        result = scanner._resolve_thumb_path("covers\\poster.jpg", tmp_path)
        assert result == str(poster)

    def test_e3_l3_takes_priority_over_l4(self, tmp_path):
        """L3 命中時不走到 L4（確保 fallback 優先順序正確）"""
        (tmp_path / "abc-123.mp4").write_bytes(b"")
        nfo_cover = tmp_path / "nfo_cover.jpg"
        nfo_cover.write_bytes(b"")
        other_jpg = tmp_path / "other.jpg"
        other_jpg.write_bytes(b"")
        scanner = VideoScanner()
        result = scanner.find_cover_image(
            str(tmp_path / "abc-123.mp4"),
            nfo_thumb="nfo_cover.jpg"
        )
        assert result == str(nfo_cover)


# ─── TestL4SafeFallback ───────────────────────────────────────────────────────

class TestL4SafeFallback:
    """E11-E15, E20, E23 — 安全 fallback 雙條件（mp4==1 AND 0<img<=2）"""

    def test_e11_one_mp4_one_jpg(self, tmp_path):
        """E11: 1 mp4 + 1 jpg（無同名/標準名/NFO）→ L4 命中，回傳 jpg"""
        (tmp_path / "abc-123.mp4").write_bytes(b"")
        jpg = tmp_path / "x.jpg"
        jpg.write_bytes(b"")
        scanner = VideoScanner()
        result = scanner.find_cover_image(str(tmp_path / "abc-123.mp4"))
        assert result == str(jpg)


    def test_e20_cross_pollution_blocked(self, tmp_path):
        """E20（Codex F2）: 2 mp4 + 2 jpg 混放 → L4 不 fallback → 空字串"""
        (tmp_path / "abc-123.mp4").write_bytes(b"")
        (tmp_path / "def-456.mp4").write_bytes(b"")
        (tmp_path / "abc-123-cover.jpg").write_bytes(b"")
        (tmp_path / "def-456-cover.jpg").write_bytes(b"")
        scanner = VideoScanner()
        # def-456 沒同名 jpg → 應回空，不應誤抓 abc-123-cover.jpg
        result = scanner.find_cover_image(str(tmp_path / "def-456.mp4"))
        assert result == ""


# ─── TestDirScanCache ─────────────────────────────────────────────────────────


# ─── TestEdgeCases ────────────────────────────────────────────────────────────


# ─── TestParseNfoThumb ────────────────────────────────────────────────────────

class TestParseNfoThumb:
    """驗證 parse_nfo() 能正確讀取 <thumb> 元素"""

    def test_parse_nfo_with_thumb(self, tmp_path):
        """NFO 含 <thumb> → nfo_info.nfo_thumb 正確設定"""
        nfo_path = tmp_path / "test.nfo"
        make_nfo(nfo_path, thumb="my_cover.jpg")
        scanner = VideoScanner()
        nfo_info = scanner.parse_nfo(str(nfo_path))
        assert nfo_info is not None
        assert nfo_info.nfo_thumb == "my_cover.jpg"


