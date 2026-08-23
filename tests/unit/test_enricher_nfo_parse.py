"""
tests/unit/test_enricher_nfo_parse.py

TASK-113a-T1a: `core.enricher._nfo_to_meta` 對齊
`gallery_scanner.VideoScanner.parse_nfo` / `readonly_producer._nfo_to_producer_meta`
的四處讀取邏輯（演員巢狀 / 片商 fallback / 發行日 fallback / 標籤 genre+tag 合併去重）。

`duration`（T1b）與 `series`（T1c）不在本檔測試範圍內。
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

import core.enricher as enricher_module
from core.database import Video
from core.enricher import _nfo_to_meta, enrich_single


# ── Part 1：六支欄位測試 + 一支 genre-genre 重複去重（Opus 審核補充 2）──────────

class TestNfoToMetaFields:
    """直接呼叫 `_nfo_to_meta(ET.fromstring(xml))`，逐一釘住四處落後點的正確語意。"""

    def test_actors_nested_any_depth(self):
        """表 1：巢狀 <actors><actor><name> 也要讀到（B/C 用 .//actor/name 任意深度）。"""
        root = ET.fromstring("<movie><actors><actor><name>X</name></actor></actors></movie>")
        meta = _nfo_to_meta(root)
        assert meta["actresses"] == ["X"]

    def test_maker_present_without_studio(self):
        """表 2：只有 <maker>，無 <studio> → meta['maker'] 非空。"""
        root = ET.fromstring("<movie><maker>M商</maker></movie>")
        meta = _nfo_to_meta(root)
        assert meta["maker"] == "M商"

    def test_release_date_from_release_tag(self):
        """表 3：只有 <release>，無 <premiered> → meta['release_date'] 非空。"""
        root = ET.fromstring("<movie><release>2024-05-01</release></movie>")
        meta = _nfo_to_meta(root)
        assert meta["release_date"] == "2024-05-01"

    def test_release_date_from_year_tag(self):
        """表 4：只有 <year>，無 <premiered>/<release> → meta['release_date'] 非空。"""
        root = ET.fromstring("<movie><year>2024</year></movie>")
        meta = _nfo_to_meta(root)
        assert meta["release_date"] == "2024"

    def test_tags_from_genre_only(self):
        """表 5：只有 <genre>，無 <tag> → meta['tags'] 非空。"""
        root = ET.fromstring("<movie><genre>G1</genre></movie>")
        meta = _nfo_to_meta(root)
        assert meta["tags"] == ["G1"]

    def test_tags_genre_then_tag_dedup_order(self):
        """表 6：<genre>A</genre><tag>A</tag><tag>B</tag> → ['A', 'B']（保序去重）。"""
        root = ET.fromstring("<movie><genre>A</genre><tag>A</tag><tag>B</tag></movie>")
        meta = _nfo_to_meta(root)
        assert meta["tags"] == ["A", "B"]

    def test_tags_genre_genre_duplicate_dedup(self):
        """Opus 審核補充 2：genre-genre 之間也要去重（對齊 C `_nfo_to_producer_meta` 的
        語意，而非 B `VideoScanner.parse_nfo`——B 的 genre 迴圈本身不比對重複）。"""
        root = ET.fromstring("<movie><genre>A</genre><genre>A</genre></movie>")
        meta = _nfo_to_meta(root)
        assert meta["tags"] == ["A"]


# ── Part 2：端到端鎖（baseline 對照組 + 五格變體）─────────────────────────────

_BASELINE_NFO = (
    "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
    "<movie>\n"
    "  <title>Baseline Title</title>\n"
    "  <originaltitle>Baseline Original</originaltitle>\n"
    "  <actor><name>Actress A</name></actor>\n"
    "  <studio>Studio A</studio>\n"
    "  <director>Director A</director>\n"
    "  <set><name>Series A</name></set>\n"
    "  <label>Label A</label>\n"
    "  <tag>TagA</tag>\n"
    "  <premiered>2024-01-01</premiered>\n"
    "  <runtime>120</runtime>\n"
    "  <website>https://example.com/page</website>\n"
    "</movie>\n"
)


def _variant_nfo(variant: str) -> str:
    """baseline 的 8 個必填欄位全部維持，只改動一個欄位的寫法。"""
    if variant == "baseline":
        return _BASELINE_NFO
    if variant == "actor_nested":
        return _BASELINE_NFO.replace(
            "<actor><name>Actress A</name></actor>",
            "<actors><actor><name>Actress A</name></actor></actors>",
        )
    if variant == "maker":
        return _BASELINE_NFO.replace("<studio>Studio A</studio>", "<maker>Studio A</maker>")
    if variant == "release":
        return _BASELINE_NFO.replace(
            "<premiered>2024-01-01</premiered>", "<release>2024-01-01</release>"
        )
    if variant == "year":
        return _BASELINE_NFO.replace("<premiered>2024-01-01</premiered>", "<year>2024</year>")
    if variant == "genre":
        return _BASELINE_NFO.replace("<tag>TagA</tag>", "<genre>TagA</genre>")
    raise ValueError(f"unknown variant: {variant}")


def _write_pair(tmp_path, number: str, nfo_xml: str):
    """建一組真實 .mp4 佔位檔 + 真實 .nfo 檔（不用 patch os.path.exists 捷徑）。"""
    mp4_path = tmp_path / f"{number}.mp4"
    mp4_path.write_bytes(b"\x00" * 16)
    nfo_path = tmp_path / f"{number}.nfo"
    nfo_path.write_text(nfo_xml, encoding="utf-8")
    return mp4_path, nfo_path


def _run_fill_missing(mp4_path, number: str, *, db_hit: bool = False):
    """跑一次 `enrich_single(mode='fill_missing')`，回傳
    (result, mock_search, spy_nfo_to_meta, mock_repo) 供三向斷言使用。

    Mock target 依 task card 結論：
    - core.enricher.search_jav（觸發刮削的入口）
    - core.enricher.VideoRepository（DB 完全隔離，不碰真實 DB）
    - core.enricher.download_image（防禦性；cover_url 恆為空字串，理論上不會被呼叫）
    - core.enricher._nfo_to_meta 用 wraps= 包成 spy，讓真實邏輯照跑同時能斷言呼叫次數
    刻意不 mock core.enricher.parse_nfo，讓它對真實 tmp_path .nfo 檔案真的執行一遍。
    """
    with (
        patch("core.enricher.VideoRepository") as mock_repo_cls,
        patch("core.enricher.search_jav") as mock_search,
        patch("core.enricher.download_image", return_value=True),
        patch(
            "core.enricher._nfo_to_meta", wraps=enricher_module._nfo_to_meta
        ) as spy_nfo_to_meta,
    ):
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_by_path.return_value = None
        # db_path 設 in-memory：避免 enrich nfo_mtime 更新路徑（enricher.py:525
        # get_connection(repo.db_path)）對 MagicMock 做 sqlite3.connect → 在 repo root
        # 產生 "<MagicMock ...>" 垃圾檔。:memory: 下該 UPDATE 因無 videos 表靜默失敗
        # （已被 try/except 包裹），不留任何檔案。
        mock_repo.db_path = ":memory:"

        if db_hit:
            video = Video(
                number=number,
                title="DB Title",
                original_title="DB Original",
                actresses=["DB Actress"],
                maker="DB Maker",
                director="DB Director",
                series="DB Series",
                label="DB Label",
                tags=["dbtag"],
                sample_images=[],
                duration=100,
                cover_path="",
                release_date="2024-02-02",
                path="",
            )
            mock_repo.get_by_numbers.return_value = {number: [video]}
        else:
            mock_repo.get_by_numbers.return_value = {}

        result = enrich_single(
            file_path=str(mp4_path),
            number=number,
            mode="fill_missing",
        )

    return result, mock_search, spy_nfo_to_meta, mock_repo


class TestEndToEndBaselineAndVariants:
    """baseline 對照組必須先綠，證明測試骨架本身有效；五格變體各自鎖住一處落後點。"""

    def test_baseline_no_scrape_triggered(self, tmp_path):
        """對照組：8 欄全填、全用現況讀得到的寫法 → 不觸發刮削。必須先於五格變體通過。"""
        number = "T113A-BASE"
        mp4_path, nfo_path = _write_pair(tmp_path, number, _variant_nfo("baseline"))
        before = nfo_path.read_bytes()

        result, mock_search, spy_nfo_to_meta, _mock_repo = _run_fill_missing(mp4_path, number)

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "nfo"
        spy_nfo_to_meta.assert_called_once()
        assert nfo_path.read_bytes() == before

    @pytest.mark.parametrize(
        "variant",
        ["actor_nested", "maker", "release", "year", "genre"],
        ids=["V1_actor_nested", "V2_maker", "V3_release", "V4_year", "V5_genre"],
    )
    def test_variant_no_scrape_triggered(self, tmp_path, variant):
        """五格變體：各自只改一個欄位的第三方寫法，其餘七個欄位維持 baseline。"""
        number = f"T113A-{variant.upper()}"
        mp4_path, nfo_path = _write_pair(tmp_path, number, _variant_nfo(variant))
        before = nfo_path.read_bytes()

        result, mock_search, spy_nfo_to_meta, _mock_repo = _run_fill_missing(mp4_path, number)

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "nfo"
        spy_nfo_to_meta.assert_called_once()
        assert nfo_path.read_bytes() == before


class TestNfoToMetaDuration:
    """TASK-113a-T1b：`_nfo_to_meta` 的 `duration` 讀取對齊 B/C 的
    `try: int(...) except ValueError: None` 轉型失敗處理策略（取代原本的
    `.isdigit()` 前置守門）。

    邊界表六格（task card + Opus 審核結論裁決 2）：唯一真正的行為變更格是
    `"-5"`（修正前 `None` → 修正後 `-5`）；其餘五格在修正前後同值，屬於
    「`.isdigit()` 與 `int()` 恰好同意」的回歸釘選，不是本次改動新開放的行為。
    mutation 自驗（把該行還原成 `.isdigit()` 前置守門）時，**只有 `"-5"` 那支
    預期轉紅**，其餘五支預期維持綠——這是設計如此，不是測試沒鑑別力。
    """

    def test_runtime_plain_digits(self):
        """`"120"` → 120。修正前後同值（回歸釘選，非行為變更釘選）。"""
        root = ET.fromstring("<movie><runtime>120</runtime></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] == 120

    def test_runtime_surrounding_whitespace(self):
        """`" 120 "` → 120。`_text()`（`:42-44`）本身已 `.strip()`，修正前後同值
        （回歸釘選，非行為變更釘選；還原 mutation 時預期維持綠——見 Opus 審核
        結論裁決 1，不得為了讓本支轉紅而改寫斷言方式繞過 `_text()`）。"""
        root = ET.fromstring("<movie><runtime> 120 </runtime></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] == 120

    def test_runtime_negative_is_now_accepted(self):
        """`"-5"` → -5。**唯一真正的行為變更格**：修正前 `"-5".isdigit()` 為
        `False`（負號不算數字字元）→ `None`；修正後 `int("-5")` 合法 → `-5`
        （CD-113a-4 接受的相容性擴張）。mutation 還原後，本支預期轉紅。"""
        root = ET.fromstring("<movie><runtime>-5</runtime></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] == -5

    def test_runtime_non_numeric_string(self):
        """`"abc"` → None。修正前後同值（回歸釘選，非行為變更釘選）。"""
        root = ET.fromstring("<movie><runtime>abc</runtime></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] is None

    def test_runtime_empty_string(self):
        """`""`（找不到 tag，`_text()` 回空字串）→ None。`int("")` 拋
        `ValueError` 被同一個 `except` 接住，修正前後同值（回歸釘選，非行為
        變更釘選）。"""
        root = ET.fromstring("<movie></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] is None

    def test_runtime_decimal_string(self):
        """`"12.5"` → None。`int("12.5")` 拋 `ValueError`，修正前後同值
        （回歸釘選，非行為變更釘選；不是本 task 新開放的格）。"""
        root = ET.fromstring("<movie><runtime>12.5</runtime></movie>")
        meta = _nfo_to_meta(root)
        assert meta["duration"] is None


class TestBlankActorOrGenreTriggersScrape:
    """TASK-113a-T4 (Codex PR review P1)：巢狀空白 actor / 空白 genre 不是資料，
    修正前 `nfo_actor_names`/`nfo_merged_tags` 會讓它們以 `['']`（非空 list）
    姿態流入 `_missing_fields`，被誤判為「已具備」而不觸發刮削——這是本 branch
    （T1a）新增的回歸。修正後應正常判缺、觸發刮削。

    刻意不透過既有 `_run_fill_missing`（它預設讓 `search_jav` 回傳
    `MagicMock()`，truthy 會讓 `_scraper_to_meta` 吃到假資料繼續往下跑）；
    這裡改用 `search_jav` 回傳 `None`，只驗證「有無觸發刮削」本身，同時
    完整重現 `enrich_single(mode='fill_missing')` 對真實 tmp_path .nfo 檔案
    的解析路徑。"""

    def _run_and_assert_scrape_triggered(self, tmp_path, number, nfo_xml):
        mp4_path, _nfo_path = _write_pair(tmp_path, number, nfo_xml)

        with (
            patch("core.enricher.VideoRepository") as mock_repo_cls,
            patch("core.enricher.search_jav", return_value=None) as mock_search,
            patch("core.enricher.download_image", return_value=True),
            patch(
                "core.enricher._nfo_to_meta", wraps=enricher_module._nfo_to_meta
            ) as spy_nfo_to_meta,
        ):
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_by_path.return_value = None
            mock_repo.get_by_numbers.return_value = {}

            enrich_single(
                file_path=str(mp4_path),
                number=number,
                mode="fill_missing",
            )

        mock_search.assert_called_once()
        spy_nfo_to_meta.assert_called_once()

    def test_nested_blank_actor_name_triggers_scrape(self, tmp_path):
        """baseline 的唯一 <actor> 換成巢狀空白 name。"""
        nfo_xml = _BASELINE_NFO.replace(
            "<actor><name>Actress A</name></actor>",
            "<actors><actor><name>   </name></actor></actors>",
        )
        self._run_and_assert_scrape_triggered(tmp_path, "T113A-T4-ACTOR", nfo_xml)

    def test_blank_genre_triggers_scrape(self, tmp_path):
        """baseline 的唯一 <tag> 換成空白 <genre>。"""
        nfo_xml = _BASELINE_NFO.replace("<tag>TagA</tag>", "<genre>   </genre>")
        self._run_and_assert_scrape_triggered(tmp_path, "T113A-T4-GENRE", nfo_xml)


class TestDbHitDoesNotCallNfoToMeta:
    """反向測試：DB 命中時完全不進 NFO 讀取分支，_nfo_to_meta 不應被呼叫。"""

    def test_db_hit_skips_nfo_to_meta(self, tmp_path):
        number = "T113A-DBHIT"
        mp4_path, _nfo_path = _write_pair(tmp_path, number, _variant_nfo("baseline"))

        result, mock_search, spy_nfo_to_meta, _mock_repo = _run_fill_missing(
            mp4_path, number, db_hit=True
        )

        mock_search.assert_not_called()
        assert result.success is True
        assert result.source_used == "db"
        spy_nfo_to_meta.assert_not_called()
        assert spy_nfo_to_meta.call_count == 0
