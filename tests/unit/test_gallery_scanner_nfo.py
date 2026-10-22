"""
測試 core/gallery_scanner.py 中的 parse_nfo() 新欄位讀取、
VideoInfo round-trip 及 scan_file() merge 邏輯。
"""
import textwrap


from core.gallery_scanner import VideoScanner


# ============ VideoInfo dataclass 測試 ============


# ============ parse_nfo() 新欄位測試 ============

class TestParseNfoNewFields:
    """parse_nfo() 讀取 <runtime>, <director>, <set><name>, <label> 測試"""

    def _write_nfo(self, tmp_path, content: str) -> str:
        """寫入 NFO 並回傳路徑字串"""
        nfo = tmp_path / "test.nfo"
        nfo.write_text(content, encoding="utf-8")
        return str(nfo)


# ============ scan_file() merge 測試 ============

class TestScanFileMerge:
    """scan_file() NFO merge 區塊覆蓋 director/duration/series/label"""

    def test_merge_new_fields_from_nfo(self, tmp_path):
        """scan_file() 應從 NFO merge director/duration/series/label"""
        # 建立假影片檔（touch）
        video_file = tmp_path / "TEST-001.mp4"
        video_file.write_bytes(b"\x00" * 100)

        # 建立 NFO
        nfo_file = tmp_path / "TEST-001.nfo"
        nfo_file.write_text(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <movie>
              <title>テストタイトル</title>
              <num>TEST-001</num>
              <runtime>90</runtime>
              <director>A監督</director>
              <set><name>Aシリーズ</name></set>
              <label>premium</label>
            </movie>
        """), encoding="utf-8")

        scanner = VideoScanner()
        info = scanner.scan_file(str(video_file))

        assert info.duration == 90
        assert info.director == "A監督"
        assert info.series == "Aシリーズ"
        assert info.label == "premium"

