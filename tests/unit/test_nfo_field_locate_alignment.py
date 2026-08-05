"""
tests/unit/test_nfo_field_locate_alignment.py

TASK-113a-T1c: 對齊 A（core.enricher._nfo_to_meta）/ B（gallery_scanner.VideoScanner.parse_nfo）
/ C（core.readonly_producer._nfo_to_producer_meta）三份 NFO 解析的欄位定位韌性：

- (a) B 的 num/maker/date 三個 fallback 迴圈：空白判斷從「elem.text truthy」改成
  「strip 後非空才採用」，對齊 C（B 靠向 C）。
- (b) A 與 C 的 series 取法：從兩步式 `root.find('set')` + `.find('name')` 改成
  路徑式 `root.find('set/name')`，對齊 B（A/C 靠向 B）。
- (c) B 的 genre 迴圈自身補上去重比對，對齊 C（B 靠向 C）。

七支測試：#1-#3 對應 (a)、#4-#5 對應 (b)、#6 對應 (c)、#7 是 Opus 審核補充的回歸釘選
（date fallback chain 全空白，修正前後同值，永遠綠——不是本 task 改動觸發的新分支）。
"""

import xml.etree.ElementTree as ET

from core.enricher import _nfo_to_meta
from core.gallery_scanner import VideoScanner
from core.readonly_producer import _nfo_to_producer_meta


def _write_nfo(tmp_path, content: str) -> str:
    nfo = tmp_path / "test.nfo"
    nfo.write_text(content, encoding="utf-8")
    return str(nfo)


# ── (a) 三支——B parse_nfo 的 num/maker/date fallback 迴圈 ──────────────────

class TestFallbackBlankSemantics:
    def test_num_fallback_skips_all_blank_tag(self, tmp_path):
        """#1：<num>全形空白</num><id>REAL-001</id> → 修正後應續看 <id> 拿到 REAL-001。

        修正前 info.num == ''（elem.text.strip() 把全形空白 strip 成空字串後仍被採用、
        不繼續找 <id>），不是 info.num == '　'（賦值本身有 strip，不會保留原始空白）。
        """
        nfo_path = _write_nfo(
            tmp_path,
            "<movie><num>　</num><id>REAL-001</id></movie>",
        )
        scanner = VideoScanner()
        info = scanner.parse_nfo(nfo_path)

        assert info is not None
        assert info.num == "REAL-001"
        # 識別欄位：確認沒有靜默退化成空字串或殘留原始全形空白
        assert info.num != ""
        assert info.num != "　"

    def test_maker_fallback_skips_all_blank_tag(self, tmp_path):
        """#2：<maker>全形空白</maker><studio>RealStudio</studio> → 續看 <studio>。"""
        nfo_path = _write_nfo(
            tmp_path,
            "<movie><maker>　</maker><studio>RealStudio</studio></movie>",
        )
        scanner = VideoScanner()
        info = scanner.parse_nfo(nfo_path)

        assert info is not None
        assert info.maker == "RealStudio"

    def test_date_fallback_skips_all_blank_tag(self, tmp_path):
        """#3：<release>全形空白</release><premiered>2024-01-01</premiered> → 續看 <premiered>。"""
        nfo_path = _write_nfo(
            tmp_path,
            "<movie><release>　</release><premiered>2024-01-01</premiered></movie>",
        )
        scanner = VideoScanner()
        info = scanner.parse_nfo(nfo_path)

        assert info is not None
        assert info.date == "2024-01-01"


# ── (b) 兩支——A/C series 取法從兩步式改路徑式 ──────────────────────────────

class TestSeriesPathLookup:
    def test_a_nfo_to_meta_series_skips_set_without_name(self):
        """#4：<set/><set><name>S2</name></set> → A 的 meta['series'] 應為 'S2'。

        兩步式只拿第一個 <set>（無 <name>），路徑式 find('set/name') 會找到第二個 <set>
        下的 <name>。
        """
        root = ET.fromstring("<movie><set/><set><name>S2</name></set></movie>")
        meta = _nfo_to_meta(root)
        assert meta["series"] == "S2"

    def test_c_nfo_to_producer_meta_series_skips_set_without_name(self):
        """#5：同上 NFO，C 的 meta['series'] 應為 'S2'。"""
        root = ET.fromstring("<movie><set/><set><name>S2</name></set></movie>")
        meta = _nfo_to_producer_meta(root, fallback_number="FALLBACK-000")
        assert meta["series"] == "S2"


# ── (c) 一支——B genre 迴圈自身去重 ──────────────────────────────────────

class TestGenreDedup:
    def test_b_parse_nfo_genre_genre_duplicate_dedup(self, tmp_path):
        """#6：<genre>A</genre><genre>A</genre> → info.genre == 'A'（不是 'A,A'）。"""
        nfo_path = _write_nfo(
            tmp_path,
            "<movie><genre>A</genre><genre>A</genre></movie>",
        )
        scanner = VideoScanner()
        info = scanner.parse_nfo(nfo_path)

        assert info is not None
        assert info.genre == "A"


# ── 回歸釘選（Opus 審核補充 1）──────────────────────────────────────────

class TestDateChainAllBlankRegressionPin:
    def test_date_chain_all_blank_stays_empty(self, tmp_path):
        """#7：<release>/<premiered>/<year> 全是空白 → info.date == ''，修正前後同值。

        這條路徑是 (a) 改動後「迴圈跑完沒 break」的分支，非行為變更釘選——本測試
        在 mutation 自驗的任何一次還原中都應該維持綠燈。若之後有人把它的綠燈誤讀成
        「這處還原沒有效果」，這段 docstring 就是提醒：它本來就該一直是綠的。
        """
        nfo_path = _write_nfo(
            tmp_path,
            "<movie><release>　</release><premiered> </premiered>"
            "<year>　</year></movie>",
        )
        scanner = VideoScanner()
        info = scanner.parse_nfo(nfo_path)

        assert info is not None
        assert info.date == ""
