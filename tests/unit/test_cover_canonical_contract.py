"""TASK-112-T2: 契約表測試（三張表，鎖 22acff9c／v0.13.2 改動前行為，第一版全綠）。

穿三個公開入口（`enrich_one_readonly` / `enrich_single` / `organize_file` +
`try_inflow_upsert`），只驗最終結果（檔案清單、NFO 三個圖片 tag 指向的檔案是否
存在、DB `cover_path`、來源磁碟快照）。這是 T2b 接線與 T3 翻面的驗收網子
（CD-112-12）。**本檔第一版必須全綠**——鎖的是改動前行為，不是預期本檔驅動任何
新實作。全部斷言值抄自 `feature/112-cover-canonical-position/plan-112.md` §0.3
唯一真理表（Table 1 / Table 2）的「→」箭頭**左側**（改動前值），一律不自行推導。

──────────────────────────────────────────────────────────────────────────
NO-PRIVATE-PATCH：本檔唯一允許的 patch 清單
──────────────────────────────────────────────────────────────────────────
Task card（TASK-112-T2.md「本 task 特有邊界」）列出的四項：
  1. core.organizer.requests.get           — download_image 的網路邊界，三表共用
  2. core.enricher.search_jav              — 表 B「_db_upsert 的 source_used 閘門」
                                              每一格都需要，見下方 TestContractTableB
                                              class docstring
  3. core.readonly_producer.search_jav     — 表 A 少數「需要真的觸發下載」的格子
                                              （沒有 sidecar NFO 可用時）
  4. core.enricher.VideoRepository         — 把 enrich_single 內部固定的
                                              `VideoRepository()` 建構呼叫重導向到
                                              已綁 temp db 的真實例，不換行為
                                              （既有模式：test_enricher.py:2490）

**額外新增第 5 項，超出 task card 原始四項清單，實作中發現必要，於此明確標註**：
  5. core.db_inflow.VideoRepository        — 理由見 TestContractTableC_Organizer
                                              class docstring。`try_inflow_upsert`
                                              內部同樣固定 `VideoRepository()`
                                              （db_inflow.py:161），且 `get_db_path()`
                                              是硬編碼的 `<repo_root>/output/openaver.db`
                                              （非 config 驅動，temp_config_path 對它
                                              沒有作用）——不 patch 這行，Table C 的
                                              DB 斷言就會打進真正的專案資料庫，這比
                                              「多一項不在原始清單的 patch」嚴重得多。
                                              性質與第 4 項完全相同（把建構呼叫重導向
                                              到已綁 temp db 的真實例，不換行為），且
                                              codebase 已有先例
                                              （tests/integration/test_search_inflow_upsert.py:506
                                              `patch("core.db_inflow.VideoRepository", return_value=repo)`）。
                                              **這是與 card 預期不符之處，回報時已明確列出。**

任何新增的 `patch(...)` 呼叫若不在以上五項清單內，視為違反 T2 DoD 最後一條。

──────────────────────────────────────────────────────────────────────────
為什麼表 B 每一格都要 patch search_jav（而不是只有部分格）
──────────────────────────────────────────────────────────────────────────
`enrich_single` 的 `_db_upsert`（enricher.py:525）只在
`mode in ("refresh_full", "fill_missing") and source_used not in ("db", "nfo", "")`
才執行。若測試讓 meta 零網路取得（DB 已有完整 row 或有 sidecar NFO），
`source_used` 會落在 `"db"` 或 `"nfo"`，`_db_upsert` 整段被跳過——此時斷言
「DB cover_path 操作前後相同」會是真的，但不是因為 preserve 邏輯生效，是因為
upsert 根本沒跑。故本檔表 B 每一格一律 `patch("core.enricher.search_jav",
return_value=scraper_data)`，確保 source_used 落在 scraper 路徑
（"javbus" 等），DB 斷言才驗到真正的東西。
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from PIL import Image

from core import config as core_config
from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri, uri_to_fs_path

# ---------------------------------------------------------------------------
# 共用 helpers（本檔案私有，不進 conftest：只有本檔案用）
# ---------------------------------------------------------------------------


def _write_jpeg(path, size=(800, 538), color=(128, 64, 32)) -> None:
    """真 JPEG（非 b"fake"）——供既有封面狀態擺放 / curator sidecar 擺放。

    涉及 crop_to_poster 的格子若餵假 bytes 會靜默失敗（回 False），poster 斷言
    就會測不到東西（task card「本 task 特有邊界」明文警告），故一律用 PIL 產生
    真圖，橫向 800x538 是既有測試（test_organizer.py:792-797）驗證過的標準尺寸。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(str(path), "JPEG")


def _jpeg_bytes(size=(800, 538), color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, "JPEG")
    return buf.getvalue()


def _mock_requests_get_jpeg(status_code=200, size=(800, 538), color=(200, 100, 50)):
    """patch core.organizer.requests.get 用：回傳真 JPEG bytes（>1000 bytes，
    通過 download_image 的 len(resp.content) > 1000 檢查），供 crop_to_poster 對
    真實內容裁切。三表唯一合法的網路邊界 patch target（test_organizer.py:1702
    既有模式）。"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.content = _jpeg_bytes(size=size, color=color)
    return mock_resp


def _sidecar_nfo(dir_path, stem: str, number: str, title: str = "Sidecar Title") -> Path:
    """Table A 零網路路徑（ingest）：`resolve_ingest_plan` 對合法 sidecar NFO 走
    `_nfo_to_producer_meta`（零網路），字面值格式沿用既有測試最小合法寫法
    （test_readonly_producer.py:2740）。"""
    nfo_path = Path(dir_path) / f"{stem}.nfo"
    nfo_path.write_text(
        f"<movie><num>{number}</num><title>{title}</title></movie>",
        encoding="utf-8",
    )
    return nfo_path


def _snapshot_dir(root) -> set:
    """遞迴快照一個目錄的所有檔案（相對路徑集合）。AC10：表 A 的來源磁碟快照斷言。
    複製自 test_readonly_producer.py:3788 的同名 helper（task card 允許複製一份，
    避免耦合既有大檔內部改動）。"""
    root = Path(root)
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _read_nfo_tags(nfo_path) -> dict:
    """解析 NFO 的 <poster>/<thumb>/<fanart> 文字值（相對檔名，不含目錄）。"""
    tree = ET.parse(str(nfo_path))
    root = tree.getroot()
    return {
        "poster": (root.findtext("poster") or ""),
        "thumb": (root.findtext("thumb") or ""),
        "fanart": (root.findtext("fanart") or ""),
    }


def _assert_nfo_tags_exist(nfo_path, expect_exists: dict) -> dict:
    """讀 NFO 三個 tag，逐一斷言其指向的檔案在 NFO 所在目錄下是否存在。

    expect_exists: {"poster": bool, "thumb": bool, "fanart": bool}
    回傳解析出的 tag dict，供呼叫端做額外的檔名字面值斷言。
    """
    tags = _read_nfo_tags(nfo_path)
    nfo_dir = Path(nfo_path).parent
    for key, expected in expect_exists.items():
        target = nfo_dir / tags[key]
        actual = target.exists()
        assert actual == expected, (
            f"NFO <{key}> = {tags[key]!r}（{target}），"
            f"exists()={actual}，預期 {expected}"
        )
    return tags


# ---------------------------------------------------------------------------
# BE-TEST-05：未涵蓋組合的機械判定機制。
# 三張表各自的維度較小（表 A/B: manager × 既有封面狀態 × overwrite；表 A 另加
# curator 軸，獨立一個 registry 避免笛卡兒積相乘），逐格白名單 + 已知未涵蓋清單。
# ---------------------------------------------------------------------------

_MANAGERS = ("off", "jellyfin", "emby", "kodi")
_TABLE_A_COVER_STATES = (
    "none", "same_name_full", "same_name_missing_derivatives",
    "fanart_layout_full", "fanart_layout_missing_poster",
    "range_out_png_or_folder",
)
_TABLE_A_CURATOR_STATES = ("none", "fanart_only", "poster_only", "both")
_TABLE_B_C_COVER_STATES = (
    "none", "same_name_full", "same_name_missing_derivatives",
    "fanart_layout", "range_out_png_or_folder",
)

# ---- 表 A registry -----------------------------------------------------
# cell id -> {"flips_after_t3": bool, "truth_table_ref": str, "axes": (...)}
TABLE_A_CELLS: dict[str, dict] = {}
TABLE_A_KNOWN_UNCOVERED: dict[str, str] = {}

# ---- 表 B registry -------------------------------------------------------
TABLE_B_CELLS: dict[str, dict] = {}
TABLE_B_KNOWN_UNCOVERED: dict[str, str] = {}

# ---- 表 C registry -------------------------------------------------------
TABLE_C_CELLS: dict[str, dict] = {}
TABLE_C_KNOWN_UNCOVERED: dict[str, str] = {}


def _register(registry: dict, cell_id: str, *, flips_after_t3: bool, truth_table_ref: str, axes: tuple):
    registry[cell_id] = {
        "flips_after_t3": flips_after_t3,
        "truth_table_ref": truth_table_ref,
        "axes": axes,
    }


# ===========================================================================
# 表 A｜唯讀（enrich_one_readonly）— 13 格
# ===========================================================================
#
# 兩種零/非零網路的 fixture 手法（見檔頭 docstring）：
#   ① "network" 設定：來源目錄只有影片本體，無 sidecar NFO、無任何圖片
#      → resolve_ingest_plan 的 valid_nfo=False，meta 一定走 search_jav
#      （patch core.readonly_producer.search_jav）；find_cover_image 找不到
#      本地封面 → cover_strategy=('download', url)。用於「需要真的觸發下載」
#      的格子：A-off-1 / A-jf-1 / A-emby-1 / A-kodi-1 / A-jf-7。
#   ② "sidecar NFO" 設定：來源目錄有合法 sidecar `.nfo`（zero 網路，meta 走
#      _nfo_to_producer_meta）。若來源目錄另有 curator `-poster`/`-fanart`
#      圖片，find_cover_image 的 L1.5 會撿到 → cover_strategy=('copy', ...)
#      （curator 三格：A-jf-2/2b/3，valid_nfo 在此完全不影響分支選擇，因為
#      cover_fs 命中的 if 分支比 valid_nfo 分支優先）；若無任何本地圖片，
#      valid_nfo=True 卻無 cover_fs → cover_strategy=('none',)（"有效 NFO
#      ingest 路徑上，download 分支永遠到不了"，card 現況分析已查證）。用於
#      「既有封面／preserve」的格子：A-jf-4/5/6a/6b/8。
#
# A-jf-6a/6b 用「staging 造狀態」而非「同一片跑兩次」（Opus 審核記錄修正 #1）：
# 唯讀 preserve gate 讀 DB `cover_path`（cover_uri_is_servable），不是探測
# `{stem}.jpg` 是否存在——直接在輸出夾擺好 `-fanart.jpg`（＋視格子擺或不擺
# `-poster.jpg`）、並 seed 一筆 cover_path 指向它的 DB row，第一次呼叫就走
# preserve 分支，今日即可觀察到懸空，不需要等 T3 產出新佈局。
# ---------------------------------------------------------------------------


class TestContractTableA_Readonly:
    """表 A｜enrich_one_readonly。13 格：Table 2 #1-#8（含 6a/6b）+ curator
    「只有 poster」補一格 + off 基線 + emby/kodi membership 回歸。"""

    _TITLE = "Table A Title"

    def _make_repo(self, tmp_path, name):
        db_file = tmp_path / name
        init_db(db_file)
        return VideoRepository(db_path=db_file)

    def _kwargs(self, *, repo, source_video, output_root, number,
                external_manager, overwrite_existing=False):
        canonical = to_file_uri(str(source_video))
        scraper_cfg = {
            "filename_format": "{num} {title}",
            "folder_format": "",
            "max_title_length": 50,
            "max_filename_length": 60,
            "suffix_keywords": [],
            "external_manager": external_manager,
            "download_sample_images": False,
        }
        return dict(
            repo_factory=lambda: repo,
            ro_source=SimpleNamespace(name="ro_src"),
            output_root=str(output_root),
            output_uri=to_file_uri(str(output_root)),
            canonical=canonical,
            file_path=canonical,
            number=number,
            scraper_cfg=scraper_cfg,
            path_mappings={},
            action="ingest",
            write_cover=True,
            overwrite_existing=overwrite_existing,
        )

    def _movie_dir_for(self, repo, canonical) -> Path:
        row = repo.get_by_path(canonical)
        assert row is not None, "enrich_one_readonly 應該已經 upsert 一筆 DB row"
        assert row.output_dir, "row.output_dir 應該非空"
        return Path(uri_to_fs_path(row.output_dir))

    # ------------------------------------------------------------------
    # ① "network" 設定的共用 runner：off / jf / emby / kodi 基線 + A-jf-7
    # ------------------------------------------------------------------
    def _run_network(self, tmp_path, name, *, external_manager, number,
                      overwrite_existing=False, pre_stage=None):
        source_dir = tmp_path / f"{name}_src"
        source_dir.mkdir()
        output_root = tmp_path / f"{name}_out"
        output_root.mkdir()
        source_video = source_dir / f"{number}.mp4"
        source_video.write_bytes(b"video-bytes")

        repo = self._make_repo(tmp_path, f"{name}.db")
        canonical = to_file_uri(str(source_video))

        if pre_stage:
            pre_stage(repo, output_root, canonical, number)

        scraper_data = {
            "number": number, "title": self._TITLE,
            "cover": "http://example.com/cover.jpg",
            "actors": ["Actress A"], "tags": ["tag1"],
            "date": "2024-01-01", "maker": "TableAMaker",
        }
        kwargs = self._kwargs(
            repo=repo, source_video=source_video, output_root=output_root,
            number=number, external_manager=external_manager,
            overwrite_existing=overwrite_existing,
        )
        source_snapshot_before = _snapshot_dir(source_dir)
        with (
            patch("core.readonly_producer.search_jav", return_value=scraper_data) as mock_search,
            patch("core.organizer.requests.get", return_value=_mock_requests_get_jpeg()),
        ):
            from core.readonly_producer import enrich_one_readonly
            result = enrich_one_readonly(**kwargs)
        source_snapshot_after = _snapshot_dir(source_dir)
        return SimpleNamespace(
            result=result, repo=repo, canonical=canonical,
            source_dir=source_dir, output_root=output_root,
            mock_search=mock_search,
            source_snapshot_before=source_snapshot_before,
            source_snapshot_after=source_snapshot_after,
        )

    # ------------------------------------------------------------------
    # ② "sidecar NFO" 設定的共用 runner：curator 三格 + 既有封面族（4/5/6a/6b/8）
    # ------------------------------------------------------------------
    def _run_sidecar(self, tmp_path, name, *, external_manager, number,
                      overwrite_existing=False, curator=None, pre_stage=None):
        source_dir = tmp_path / f"{name}_src"
        source_dir.mkdir()
        output_root = tmp_path / f"{name}_out"
        output_root.mkdir()
        source_video = source_dir / f"{number}.mp4"
        source_video.write_bytes(b"video-bytes")
        stem = source_video.stem  # == number（檔名就是番號.mp4）
        _sidecar_nfo(source_dir, stem, number, title=self._TITLE)

        curator_bytes = {}
        if curator in ("fanart_only", "both"):
            fanart_src = source_dir / f"{stem}-fanart.jpg"
            _write_jpeg(fanart_src, color=(10, 20, 30))
            curator_bytes["fanart"] = fanart_src.read_bytes()
        if curator in ("poster_only", "both"):
            poster_src = source_dir / f"{stem}-poster.jpg"
            _write_jpeg(poster_src, color=(90, 80, 70))
            curator_bytes["poster"] = poster_src.read_bytes()

        repo = self._make_repo(tmp_path, f"{name}.db")
        canonical = to_file_uri(str(source_video))

        if pre_stage:
            pre_stage(repo, output_root, canonical, number)

        kwargs = self._kwargs(
            repo=repo, source_video=source_video, output_root=output_root,
            number=number, external_manager=external_manager,
            overwrite_existing=overwrite_existing,
        )
        source_snapshot_before = _snapshot_dir(source_dir)
        with patch("core.organizer.requests.get", return_value=_mock_requests_get_jpeg()):
            from core.readonly_producer import enrich_one_readonly
            result = enrich_one_readonly(**kwargs)
        source_snapshot_after = _snapshot_dir(source_dir)
        return SimpleNamespace(
            result=result, repo=repo, canonical=canonical,
            source_dir=source_dir, output_root=output_root,
            curator_bytes=curator_bytes,
            source_snapshot_before=source_snapshot_before,
            source_snapshot_after=source_snapshot_after,
        )

    # ------------------------------------------------------------------
    # A-off-1
    # ------------------------------------------------------------------
    def test_A_off_1_off_no_existing_downloads_plain_jpg(self, tmp_path):
        """A-off-1｜off／無／ovw=False。鎖：off 模式下載封面到 canonical
        `{basename}.jpg`，不產 poster/fanart，NFO 三 tag 皆 `{basename}.jpg`。
        T3-T6 後：不變（off 逐位元組不變，§0.3 legend）。"""
        ctx = self._run_network(tmp_path, "a_off_1", external_manager="off", number="AOFF-001")
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"AOFF-001 {self._TITLE}"
        cover = movie_dir / f"{basename}.jpg"
        nfo = movie_dir / f"{basename}.nfo"
        assert cover.exists()
        assert not (movie_dir / f"{basename}-poster.jpg").exists()
        assert not (movie_dir / f"{basename}-fanart.jpg").exists()
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{basename}.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))
        assert ctx.source_snapshot_before == ctx.source_snapshot_after

    _register(TABLE_A_CELLS, "A-off-1", flips_after_t3=False, truth_table_ref="off-not-in-table",
               axes=("off", "none", False, "none"))

    # ------------------------------------------------------------------
    # A-jf-1 / A-emby-1 / A-kodi-1 (Table2#1 + membership 回歸)
    # ------------------------------------------------------------------
    def _assert_stem_image_matrix_cell1(self, tmp_path, name, manager, number):
        ctx = self._run_network(tmp_path, name, external_manager=manager, number=number)
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"{number} {self._TITLE}"
        # T3 落地後（真理表 Table2#1）：既有=無 → resolve_cover_target 第③步
        # 新建，jellyfin 在 STEM_IMAGE_MODES → canonical 直接落在 -fanart.jpg
        # （同檔保護：fanart 衍生圖與 canonical 是同一個實體檔），不再有獨立的
        # 裸 stem 同名 .jpg。
        cover = movie_dir / f"{basename}-fanart.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        nfo = movie_dir / f"{basename}.nfo"
        assert cover.exists()
        assert poster.exists()
        assert fanart.exists()
        assert not (movie_dir / f"{basename}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["thumb"] == f"{basename}-fanart.jpg", (
            "CD-112-5 落地後：<thumb> 改用 fanart_tag，has_fanart=True → -fanart.jpg（真理表 Table2#1）"
        )
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))
        assert ctx.source_snapshot_before == ctx.source_snapshot_after
        assert ctx.mock_search.call_count >= 1

    def test_A_jf_1_jellyfin_no_existing_no_curator(self, tmp_path):
        """A-jf-1（Table2#1）｜jellyfin／無／ovw=False、curator=無。需 patch
        search_jav——有效 NFO ingest 路徑上，download 分支永遠到不了
        （valid_nfo=True 時 cover_strategy 必為 ('none',)，card 現況分析已查證），
        要驗到 ('download', url) 只能不放 sidecar NFO。
        鎖：canonical=`{stem}.jpg`（未翻面），poster+fanart 皆產生，DB 同步。
        T3-T6 後：翻面，canonical→`{stem}-fanart.jpg`，DB 同步翻面。"""
        self._assert_stem_image_matrix_cell1(tmp_path, "a_jf_1", "jellyfin", "AJF1-001")

    _register(TABLE_A_CELLS, "A-jf-1", flips_after_t3=True, truth_table_ref="Table2#1",
               axes=("jellyfin", "none", False, "none"))

    def test_A_emby_1_membership_guard(self, tmp_path):
        """A-emby-1｜emby／無／ovw=False（membership 回歸guard，同 A-jf-1 邏輯，
        只換 external_manager）。T3-T6 後：同 A-jf-1 翻面方向。"""
        self._assert_stem_image_matrix_cell1(tmp_path, "a_emby_1", "emby", "AEMB-001")

    _register(TABLE_A_CELLS, "A-emby-1", flips_after_t3=True, truth_table_ref="Table2#1",
               axes=("emby", "none", False, "none"))

    def test_A_kodi_1_membership_guard(self, tmp_path):
        """A-kodi-1｜kodi／無／ovw=False（membership 回歸guard）。T3-T6 後：
        同 A-jf-1 翻面方向。"""
        self._assert_stem_image_matrix_cell1(tmp_path, "a_kodi_1", "kodi", "AKOD-001")

    _register(TABLE_A_CELLS, "A-kodi-1", flips_after_t3=True, truth_table_ref="Table2#1",
               axes=("kodi", "none", False, "none"))

    # ------------------------------------------------------------------
    # A-jf-2（curator=只有 fanart，Table2#2）
    # ------------------------------------------------------------------
    def test_A_jf_2_curator_fanart_only(self, tmp_path):
        """A-jf-2（Table2#2）｜jellyfin／無／ingest、curator=只有 fanart。
        find_cover_image 的 L1.5 撿到 curator `-fanart.jpg` 當「本地封面」→
        cover_strategy=('copy', fanart_src, {'poster': None, 'fanart': fanart_src})。
        鎖：curator fanart 複製到 canonical `{stem}.jpg`（覆蓋掉 find_cover_image
        選中的圖，本身就是那張 fanart）、DB→`{stem}.jpg`。
        T3-T6 後：翻面，複製目的地→`{stem}-fanart.jpg`；AC5b：DB 指向該 fanart。"""
        ctx = self._run_sidecar(
            tmp_path, "a_jf_2", external_manager="jellyfin", number="AJF2-001",
            curator="fanart_only",
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"AJF2-001 {self._TITLE}"
        # T3 落地後（真理表 Table2#2）：既有=無 → resolve_cover_target 新建，
        # canonical 直接落在 -fanart.jpg，curator fanart 原檔複製到這個位置。
        cover = movie_dir / f"{basename}-fanart.jpg"
        assert cover.exists()
        assert not (movie_dir / f"{basename}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        assert cover.read_bytes() == ctx.curator_bytes["fanart"], (
            "canonical cover 應為 curator fanart 原檔的複製（find_cover_image 選中的圖）"
        )
        # curator fanart_only：poster 走 crop_to_poster、fanart 走 verbatim copy，
        # 皆成功 → has_poster=has_fanart=True → <poster>/<fanart> 走各自後綴；
        # <thumb>（CD-112-5 落地後）改用 fanart_tag，has_fanart=True → -fanart.jpg。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))
        assert ctx.source_snapshot_before == ctx.source_snapshot_after

    _register(TABLE_A_CELLS, "A-jf-2", flips_after_t3=True, truth_table_ref="Table2#2",
               axes=("jellyfin", "none", False, "fanart_only"))

    # ------------------------------------------------------------------
    # A-jf-2b（curator=只有 poster，Opus 審核記錄修正 #2 補明確預期）
    # ------------------------------------------------------------------
    def test_A_jf_2b_curator_poster_only(self, tmp_path):
        """A-jf-2b（curator 四格之一，plan 未單獨編號）｜jellyfin／無／ingest、
        curator=只有 poster。鎖：canonical=`{stem}.jpg`（find_cover_image 選中
        的圖=curator poster 的複製）；`-poster.jpg` 逐位元組=curator 原 poster
        （verbatim，CD-112-7 第三元素保留）；`-fanart.jpg` 走 generate 分支
        `copy2(cover_fs, fanart_path)`＝canonical 的副本（=curator poster 內容）。
        T3-T6 後：canonical→`{stem}-fanart.jpg`；此時 fanart slot 的
        `copy2(cover_fs, fanart_path)` 變成同檔 → CD-112-8 短路成功；poster 仍
        逐位元組=curator 原檔（verbatim 承諾不因翻面而破，這格是 CD-112-7 的
        第二道鎖，與 A-jf-3 互補）。"""
        ctx = self._run_sidecar(
            tmp_path, "a_jf_2b", external_manager="jellyfin", number="AJF2B-001",
            curator="poster_only",
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"AJF2B-001 {self._TITLE}"
        # T3 落地後：既有=無 → resolve_cover_target 新建，canonical 落在
        # -fanart.jpg（curator poster 原檔複製到這個位置，poster slot 另外
        # verbatim 保留 curator poster）。
        cover = movie_dir / f"{basename}-fanart.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        assert cover.exists() and poster.exists() and fanart.exists()
        assert not (movie_dir / f"{basename}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        assert cover.read_bytes() == ctx.curator_bytes["poster"]
        assert poster.read_bytes() == ctx.curator_bytes["poster"], (
            "poster slot 必須 verbatim = curator 原 poster bytes（CD-112-7）"
        )
        assert fanart.read_bytes() == cover.read_bytes(), (
            "fanart slot 缺席 → 落 generate 分支 copy2(cover_fs, fanart_path)，"
            "= canonical 的副本"
        )
        # 兩個 slot 最終都成功（poster verbatim、fanart 走 copy2 fallback）→
        # has_poster=has_fanart=True →〈poster〉/〈fanart〉走各自後綴、
        # 〈thumb〉（CD-112-5 落地後）改用 fanart_tag，has_fanart=True → -fanart.jpg。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))

    _register(TABLE_A_CELLS, "A-jf-2b", flips_after_t3=True, truth_table_ref="Table2(curator-poster-only, unnumbered)",
               axes=("jellyfin", "none", False, "poster_only"))

    # ------------------------------------------------------------------
    # A-jf-3（curator=poster+fanart，Table2#3，P1-2 鎖定格）
    # ------------------------------------------------------------------
    def test_A_jf_3_curator_both(self, tmp_path):
        """A-jf-3（Table2#3，P1-2 鎖定格）｜jellyfin／無／ingest、curator=
        poster+fanart 皆有。兩者皆走各自 verbatim（generate_jellyfin_images/
        crop_to_poster 完全不被呼叫），canonical=`{stem}.jpg`（=curator fanart
        的複製，因 L1.5 fanart 優先於 poster）。
        T3-T6 後：canonical→fanart；poster 逐位元組=curator 原檔（T3 若寫錯會
        被裁切版取代，這格是 T6 mutation 鎖的對象，T2 只鎖改動前）。"""
        ctx = self._run_sidecar(
            tmp_path, "a_jf_3", external_manager="jellyfin", number="AJF3-001",
            curator="both",
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"AJF3-001 {self._TITLE}"
        # T3 落地後：既有=無 → resolve_cover_target 新建，canonical 落在
        # -fanart.jpg（L1.5 fanart 優先於 poster，curator fanart 原檔即
        # canonical，poster slot 另外 verbatim 保留 curator poster）。
        cover = movie_dir / f"{basename}-fanart.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        assert cover.exists() and poster.exists() and fanart.exists()
        assert not (movie_dir / f"{basename}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        assert poster.read_bytes() == ctx.curator_bytes["poster"], "poster verbatim"
        assert fanart.read_bytes() == ctx.curator_bytes["fanart"], "fanart verbatim"
        assert cover.read_bytes() == ctx.curator_bytes["fanart"], (
            "L1.5 fanart 優先於 poster → find_cover_image 選中 fanart 當『封面』"
        )
        # 兩個 slot 皆 verbatim 成功 → has_poster=has_fanart=True →
        # 〈poster〉/〈fanart〉走各自後綴、〈thumb〉（CD-112-5 落地後）改用
        # fanart_tag，has_fanart=True → -fanart.jpg（curator 三格中最容易漏改
        # 的一格——canonical 切換時若忘了同步這三個 tag，這裡最先炸）。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))

    _register(TABLE_A_CELLS, "A-jf-3", flips_after_t3=True, truth_table_ref="Table2#3",
               axes=("jellyfin", "none", False, "both"))

    # ------------------------------------------------------------------
    # A-jf-4（Table2#4，AC1b-1 唯讀對照）：既有 {stem}.jpg 完整，ovw=False
    # ------------------------------------------------------------------
    def test_A_jf_4_existing_full_no_overwrite_preserved(self, tmp_path):
        """A-jf-4（Table2#4，AC1b-1 唯讀對照）｜jellyfin／既有`{stem}.jpg`完整
        （含既有 poster/fanart 衍生圖）／ovw=False。preserve gate 命中
        （DB cover_path 服務得到）→ 不寫、不改 DB、不清焦點。

        T7 對帳更正（Opus 審核記錄追加要求 #1）：`flips_after_t3` 原標 False，
        實測翻面——preserve 命中 → `has_cover=False`（本次未寫）→ 產品碼直接傳
        `has_poster=has_fanart=False` 進 `nfo_image_flag`，但該函式是
        `wrote_this_run or os.path.exists(...)`（CD-112-16），既有 `-poster.jpg`／
        `-fanart.jpg` 磁碟上都在 → 兩者皆被判定為 True。這**不是**單純 CD-112-5
        （`<thumb>` 改用 `fanart_tag`）的效果，是 CD-112-16 的磁碟真相回退機制
        對這一格的**額外**副作用：`<poster>` 也跟著從退回 `{basename}.jpg`
        變成 `{basename}-poster.jpg`，不只 `<thumb>`/`<fanart>`（見下方斷言與
        §F 的逐格證據，Opus 追加要求 #2 的「只有 thumb」在本格不完全成立，
        原因已如上說明，DB/crop_mode/bytes 斷言未受影響）。
        T3-T6 後：canonical 位置不變（CD-112-15：唯讀不補衍生圖，永遠不變，
        反向鎖）；NFO 三 tag 因上述 CD-112-16 磁碟回退機制而變。"""
        number = "AJF4-001"
        basename = f"{number} {self._TITLE}"
        # P2-3（pre-merge Stage 2 review）：既有封面內容必須是操作**之前**就固定
        # 下來的常數，不能事後才從磁碟讀一次拿來跟自己比（那是恆真的空殼斷言）。
        cover_bytes_pre_stage = _jpeg_bytes(color=(1, 2, 3))

        def _stage(repo, output_root, canonical, number):
            movie_dir = output_root / basename
            movie_dir.mkdir(parents=True)
            cover = movie_dir / f"{basename}.jpg"
            cover.write_bytes(cover_bytes_pre_stage)
            _write_jpeg(movie_dir / f"{basename}-poster.jpg", color=(4, 5, 6))
            _write_jpeg(movie_dir / f"{basename}-fanart.jpg", color=(7, 8, 9))
            repo.upsert(Video(
                path=canonical, number=number, title=self._TITLE,
                output_dir=to_file_uri(str(movie_dir)),
                cover_path=to_file_uri(str(cover)),
            ))

        ctx = self._run_sidecar(
            tmp_path, "a_jf_4", external_manager="jellyfin", number=number,
            pre_stage=_stage,
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        cover = movie_dir / f"{basename}.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover)), "DB cover_path 不變"
        assert cover.read_bytes() == cover_bytes_pre_stage, "既有封面內容不被覆寫（不下載）"
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg", (
            "CD-112-16 nfo_image_flag 磁碟回退：既有 -poster.jpg 存在 → has_poster=True"
        )
        assert tags["thumb"] == f"{basename}-fanart.jpg", (
            "CD-112-16 磁碟回退 has_fanart=True，CD-112-5 <thumb> 隨 fanart_tag 一起變"
        )
        assert tags["fanart"] == f"{basename}-fanart.jpg", (
            "CD-112-16 nfo_image_flag 磁碟回退：既有 -fanart.jpg 存在 → has_fanart=True"
        )

    # 本格翻的是 ②〈thumb〉（CD-112-5）及其連帶的 nfo_image_flag 磁碟回退機制
    # （CD-112-16），不是①正典位置；預測時 flips_after_t3 只建模了①。
    _register(TABLE_A_CELLS, "A-jf-4", flips_after_t3=True, truth_table_ref="Table2#4",
               axes=("jellyfin", "same_name_full", False, "none"))

    # ------------------------------------------------------------------
    # A-jf-5（Table2#5，CD-112-15 正向鎖）：既有 {stem}.jpg 缺衍生圖，ovw=False
    # ------------------------------------------------------------------
    def test_A_jf_5_existing_missing_derivatives_not_backfilled(self, tmp_path):
        """A-jf-5（Table2#5，CD-112-15 正向鎖，⚠️ 與 Table 1 #3 不一致）｜
        jellyfin／既有`{stem}.jpg`但缺衍生圖／ovw=False。preserve → cover_strategy
        =('none',) → has_cover=False → 衍生圖 gate 是 `has_cover`（本次寫入成敗），
        **不看磁碟真相**（readonly_producer.py:894/902）——即使磁碟上這兩個衍生檔
        原本就不存在，也不會被『補上』。鎖：不寫封面、衍生圖仍不補（poster/fanart
        檔案在 NFO 呼叫前後都不存在）、DB 不變。
        T3-T6 後：不變——此格 T3-T6 後仍不補，是刻意保留的既有限制。"""
        number = "AJF5-001"
        basename = f"{number} {self._TITLE}"

        def _stage(repo, output_root, canonical, number):
            movie_dir = output_root / basename
            movie_dir.mkdir(parents=True)
            cover = movie_dir / f"{basename}.jpg"
            _write_jpeg(cover, color=(11, 22, 33))
            repo.upsert(Video(
                path=canonical, number=number, title=self._TITLE,
                output_dir=to_file_uri(str(movie_dir)),
                cover_path=to_file_uri(str(cover)),
            ))

        ctx = self._run_sidecar(
            tmp_path, "a_jf_5", external_manager="jellyfin", number=number,
            pre_stage=_stage,
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        cover = movie_dir / f"{basename}.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        assert cover.exists(), "既有封面保留"
        assert not poster.exists(), "衍生圖 gate 看 has_cover（本次寫入），不看磁碟真相 → 不補"
        assert not fanart.exists()
        # has_cover=False → has_poster=has_fanart=False → 三個 tag 全退回
        # {basename}.jpg——這裡剛好等於既有封面本身，故存在（非懸空，對照
        # A-jf-6a/6b：canonical 已翻面時才會變懸空）（BLOCKER B1 補）。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{basename}.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover))

    _register(TABLE_A_CELLS, "A-jf-5", flips_after_t3=False, truth_table_ref="Table2#5",
               axes=("jellyfin", "same_name_missing_derivatives", False, "none"))

    # ------------------------------------------------------------------
    # A-jf-6a / A-jf-6b（CD-112-16，Opus 審核記錄修正 #1：staging 造狀態）
    # ------------------------------------------------------------------
    def _stage_fanart_layout(self, *, with_poster: bool, color_fanart, color_poster):
        """既有輸出佈局＝`-fanart.jpg`（＋可選 `-poster.jpg`），DB cover_path
        指向該 fanart。basename 一律用 self._TITLE——必須與 `_run_sidecar` 建
        sidecar NFO 用的 title 一致，否則這次呼叫重算的 basename 會跟 staged
        檔名對不上（`_resolve_movie_dir` 的 read-and-reuse 只認 output_dir 是否
        在 output_uri 之下，不看 title/basename 是否一致，重用到同一個目錄後
        NFO 卻會用『這次』的 basename 找檔案）。"""
        def _stage(repo, output_root, canonical, number):
            basename = f"{number} {self._TITLE}"
            movie_dir = output_root / basename
            movie_dir.mkdir(parents=True)
            fanart = movie_dir / f"{basename}-fanart.jpg"
            _write_jpeg(fanart, color=color_fanart)
            if with_poster:
                _write_jpeg(movie_dir / f"{basename}-poster.jpg", color=color_poster)
            repo.upsert(Video(
                path=canonical, number=number, title=self._TITLE,
                output_dir=to_file_uri(str(movie_dir)),
                cover_path=to_file_uri(str(fanart)),
            ))
        return _stage

    def test_A_jf_6a_fanart_layout_full_reentry_dangling_tags(self, tmp_path):
        """A-jf-6a（Table2#6a，CD-112-16 本 branch 唯一新 bug 格，Opus 審核記錄
        修正 #1）｜jellyfin／既有佈局＝`{stem}-fanart.jpg` + `{stem}-poster.jpg`
        齊備、無 `{stem}.jpg`，DB cover_path 指向該 `-fanart.jpg`／ovw=False。

        造法：直接在輸出夾擺好 `-fanart.jpg`+`-poster.jpg`、seed 一筆 cover_path
        指向 `-fanart.jpg` 的 DB row，第一次呼叫就走 preserve（gate 讀 DB
        cover_path，不是探測 `{stem}.jpg`）——不需要等 T3 產出新佈局。

        鎖（今日就驗得到，且今日就是壞的）：preserve 命中 → has_cover=False →
        has_poster=has_fanart=False → NFO **無條件重寫**（generate_nfo 每次都
        被呼叫）→ 三個 tag 全退回 `{basename}.jpg`，**該檔不存在＝懸空**。
        T3-T6 後：CD-112-16 落地後 <thumb>/<fanart>→`{b}-fanart.jpg`✓、
        <poster>→`{b}-poster.jpg`✓，三者皆 exists()。"""
        number = "AJF6A-001"
        stage = self._stage_fanart_layout(
            with_poster=True, color_fanart=(50, 60, 70), color_poster=(80, 90, 100),
        )
        ctx = self._run_sidecar(
            tmp_path, "a_jf_6a", external_manager="jellyfin", number=number,
            pre_stage=stage,
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"{number} {self._TITLE}"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        assert fanart.exists() and poster.exists(), "既有佈局檔案不被清理（preserve 不動既有磁碟檔）"
        nfo = movie_dir / f"{basename}.nfo"
        # CD-112-16 落地後：nfo_image_flag 磁碟回退偵測到既有 -poster.jpg／
        # -fanart.jpg 皆存在 → has_poster=has_fanart=True → 三 tag 皆指向存在的檔案。
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(fanart)), "DB cover_path 不變（仍指向 -fanart.jpg）"

    _register(TABLE_A_CELLS, "A-jf-6a", flips_after_t3=True, truth_table_ref="Table2#6a",
               axes=("jellyfin", "fanart_layout_full", False, "none"))

    def test_A_jf_6b_fanart_layout_missing_poster_named_boundary(self, tmp_path):
        """A-jf-6b（Table2#6b，AC7 具名邊界，round-4 review）｜同 A-jf-6a，但
        佈局**缺** `{stem}-poster.jpg`（只有 `-fanart.jpg`，DB 指向它）／ovw=False。

        鎖：同 A-jf-6a——三 tag 全退回 `{basename}.jpg` 且全懸空（preserve→
        has_poster=has_fanart=False，NFO 無條件重寫，與是否曾經有 poster 無關）。
        T3-T6 後：**部分翻面**——<thumb>/<fanart>→`{b}-fanart.jpg`✓；
        **`<poster>` 仍退回 `{b}.jpg` 且仍懸空**（generate_nfo 的 fallback，
        organizer.py:657）。**這是刻意接受的已知邊界（CD-112-16「已否決的修法」），
        不是 bug**——本測試/註解不得把 `<poster>` 改指 `-fanart.jpg`。"""
        number = "AJF6B-001"
        stage = self._stage_fanart_layout(
            with_poster=False, color_fanart=(150, 160, 170), color_poster=None,
        )
        ctx = self._run_sidecar(
            tmp_path, "a_jf_6b", external_manager="jellyfin", number=number,
            pre_stage=stage,
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        basename = f"{number} {self._TITLE}"
        fanart = movie_dir / f"{basename}-fanart.jpg"
        poster = movie_dir / f"{basename}-poster.jpg"
        assert fanart.exists()
        assert not poster.exists(), "6b 的佈局本來就缺 -poster.jpg（具名邊界前置條件）"
        nfo = movie_dir / f"{basename}.nfo"
        # CD-112-16 落地後：<thumb>/<fanart> 靠磁碟回退指向存在的 -fanart.jpg；
        # <poster> 因 -poster.jpg 缺失，磁碟回退查無此檔，仍退回 {basename}.jpg
        # ＝ AC7 具名邊界，刻意維持懸空，不得改指 -fanart.jpg。
        tags = _assert_nfo_tags_exist(nfo, {"poster": False, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}.jpg", "AC7 具名邊界：poster 仍懸空，不 fallback 到 fanart"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(fanart))

    _register(TABLE_A_CELLS, "A-jf-6b", flips_after_t3=True, truth_table_ref="Table2#6b",
               axes=("jellyfin", "fanart_layout_missing_poster", False, "none"))

    # ------------------------------------------------------------------
    # A-jf-7（Table2#7，AC1b-2）：既有 {stem}.jpg，ovw=True
    # ------------------------------------------------------------------
    def test_A_jf_7_existing_overwrite_true_redownloads_same_name_resets_focal(self, tmp_path):
        """A-jf-7（Table2#7，AC1b-2）｜jellyfin／既有`{stem}.jpg`／ovw=True。
        should_preserve_cover(write_cover=True, overwrite_existing=True,
        cover_exists=True) = False → 不 preserve → 走 network 設定觸發真下載，
        覆寫回**同一個** `{stem}.jpg`（canonical 未翻面）、DB cover_path 值不變
        （字面同一 URI）、焦點被重置。

        **R8／Opus 審核記錄修正 #4**：焦點重置這條鎖的是**改動前就有的行為**
        （`cover_written=True` → `schedule_focal_after_cover_write` 無條件
        `reset_focal_to_auto`，CD-112-14 不觸碰），**不是 112 的承諾**——
        不得誤讀成「112 保證重刮會清焦點」。
        T3-T6 後：canonical 位置不變。理由：T3 後 resolve_cover_target 的第①步
        「`{stem}.jpg` 已存在 → 沿用」會命中（解析發生在覆寫之前、舊檔仍在），
        仍回同名。

        T7 對帳更正（Opus 審核記錄追加要求 #1）：`flips_after_t3` 原標 False，
        實測翻面——但翻的只有②〈thumb〉：ovw=True 這次真的重新產生 poster/
        fanart（has_cover gate 命中），has_poster=has_fanart=True 是**本次
        真實寫入**的結果（不是 CD-112-16 的磁碟回退），CD-112-5 讓〈thumb〉
        隨 fanart_tag 一起變成 -fanart.jpg；DB/crop_mode/封面 bytes 斷言逐字
        保留，不受影響。"""
        number = "AJF7-001"
        basename = f"{number} {self._TITLE}"

        ctx = self._run_network(
            tmp_path, "a_jf_7", external_manager="jellyfin", number=number,
            overwrite_existing=True, pre_stage=self._stage_jf7_with_manual_focal(number, basename),
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        cover = movie_dir / f"{basename}.jpg"
        assert cover.exists()
        assert cover.read_bytes() == _jpeg_bytes(), "覆寫回同一個檔名，內容變成新下載的圖"
        # ovw=True → _write_media_images 的 has_cover gate 命中 → 重新產生
        # poster/fanart → has_poster=has_fanart=True →〈poster〉/〈fanart〉走
        # 各自後綴、〈thumb〉（CD-112-5 落地後）改用 fanart_tag → -fanart.jpg。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{basename}-poster.jpg"
        assert tags["thumb"] == f"{basename}-fanart.jpg"
        assert tags["fanart"] == f"{basename}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover)), "DB cover_path 字面值不變（同一路徑）"
        assert row.crop_mode == "auto", (
            "cover_written=True → 無條件 reset_focal_to_auto（既有行為，非 112 承諾，見 R8）"
        )

    def _stage_jf7_with_manual_focal(self, number, basename):
        def _stage(repo, output_root, canonical, number_):
            movie_dir = output_root / basename
            movie_dir.mkdir(parents=True)
            cover = movie_dir / f"{basename}.jpg"
            _write_jpeg(cover, color=(200, 200, 200))
            repo.upsert(Video(
                path=canonical, number=number, title=self._TITLE,
                output_dir=to_file_uri(str(movie_dir)),
                cover_path=to_file_uri(str(cover)),
            ))
            assert repo.update_manual_focal(canonical, "0.3000,0.6000", to_file_uri(str(cover))) is True
        return _stage

    # 本格翻的是 ②〈thumb〉（CD-112-5），不是①正典位置；預測時 flips_after_t3
    # 只建模了①。
    _register(TABLE_A_CELLS, "A-jf-7", flips_after_t3=True, truth_table_ref="Table2#7",
               axes=("jellyfin", "same_name_full", True, "none"))

    # ------------------------------------------------------------------
    # A-jf-8（Table2#8，範圍外）：既有 .png 或 folder.jpg，ovw=False
    # ------------------------------------------------------------------
    def test_A_jf_8_existing_range_out_extension_preserved_no_download(self, tmp_path):
        """A-jf-8（Table2#8，範圍外，唯讀吃得下任意副檔名）｜jellyfin／既有
        `.png`（範圍外副檔名）／ovw=False。cover_uri_is_servable 讀 DB `cover_path`
        值，任何副檔名都算 servable——與非唯讀（表 B 對應格 B-jf-6）刻意相反
        （§0.4 發現④）。鎖：不下載、不改記帳、不清焦點。
        T3-T6 後：不變。"""
        number = "AJF8-001"
        basename = f"{number} {self._TITLE}"
        # P2-3（pre-merge Stage 2 review）：同 A-jf-4，改成操作前固定的常數，
        # 不再事後讀檔跟自己比。
        cover_png_bytes_pre_stage = _jpeg_bytes(color=(5, 5, 5))

        def _stage(repo, output_root, canonical, number_):
            movie_dir = output_root / basename
            movie_dir.mkdir(parents=True)
            cover_png = movie_dir / f"{basename}.png"
            cover_png.write_bytes(cover_png_bytes_pre_stage)  # 內容不重要，副檔名才是重點
            repo.upsert(Video(
                path=canonical, number=number, title=self._TITLE,
                output_dir=to_file_uri(str(movie_dir)),
                cover_path=to_file_uri(str(cover_png)),
            ))
            assert repo.update_manual_focal(canonical, "0.3000,0.6000", to_file_uri(str(cover_png))) is True

        ctx = self._run_sidecar(
            tmp_path, "a_jf_8", external_manager="jellyfin", number=number,
            pre_stage=_stage,
        )
        movie_dir = self._movie_dir_for(ctx.repo, ctx.canonical)
        cover_png = movie_dir / f"{basename}.png"
        assert not (movie_dir / f"{basename}.jpg").exists(), "不下載新的 .jpg"
        assert cover_png.read_bytes() == cover_png_bytes_pre_stage
        # cover_written=False → has_poster=has_fanart=False → 三個 tag 全退回
        # {basename}.jpg——但實際封面是 {basename}.png，該 .jpg 從未存在過，
        # 三 tag 皆懸空（與 A-jf-6a/6b 同一種「retreat 到不存在的檔名」形狀，
        # 差別只在成因是副檔名不同而非 canonical 位置翻面）（BLOCKER B1 補）。
        nfo = movie_dir / f"{basename}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": False, "thumb": False, "fanart": False})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{basename}.jpg"
        row = ctx.repo.get_by_path(ctx.canonical)
        assert row.cover_path == to_file_uri(str(cover_png)), "DB 記帳不變"
        assert row.crop_mode == "manual", "preserve 命中 → cover_written=False → 不清焦點"

    _register(TABLE_A_CELLS, "A-jf-8", flips_after_t3=False, truth_table_ref="Table2#8",
               axes=("jellyfin", "range_out_png_or_folder", False, "none"))

    # ------------------------------------------------------------------
    # BE-TEST-05：表 A registry 完整性（主矩陣 + curator 軸各自獨立判定）
    # ------------------------------------------------------------------
    def test_registry_complete_manager_x_cover_state_x_overwrite(self):
        """manager × 既有封面狀態 × overwrite 完整笛卡兒積必須全部被
        TABLE_A_CELLS ∪ TABLE_A_KNOWN_UNCOVERED 涵蓋（BE-TEST-05）。"""
        all_cells = {
            (mgr, cover, ovw)
            for mgr in _MANAGERS
            for cover in _TABLE_A_COVER_STATES
            for ovw in (False, True)
        }
        declared = {
            (v["axes"][0], v["axes"][1], v["axes"][2])
            for v in TABLE_A_CELLS.values()
        } | {
            (v["axes"][0], v["axes"][1], v["axes"][2])
            for v in TABLE_A_KNOWN_UNCOVERED_AXES.values()
        }
        missing = all_cells - declared
        assert not missing, f"表 A 未宣告涵蓋與否的組合：{sorted(missing)}"

    def test_registry_complete_curator_axis(self):
        """curator 軸（僅對「既有封面=無」有意義）獨立判定，避免和主矩陣笛卡兒積相乘。"""
        all_curator_cells = {
            (mgr, curator)
            for mgr in ("jellyfin",)  # emby/kodi 已由 membership 回歸格覆蓋同一機制，curator 軸不重複窮舉
            for curator in _TABLE_A_CURATOR_STATES
        }
        declared = {
            (v["axes"][0], v["axes"][3])
            for v in TABLE_A_CELLS.values()
            if v["axes"][1] == "none" and v["axes"][0] == "jellyfin"
        }
        missing = all_curator_cells - declared
        assert not missing, f"表 A curator 軸未宣告涵蓋與否的組合：{sorted(missing)}"


# TABLE_A_KNOWN_UNCOVERED 目前記 cell-id -> 理由字串（供人讀）；registry 完整性判定
# 額外需要 axes-keyed 版本 —— 用同一份資料源生成，避免兩處手key漂移。
TABLE_A_KNOWN_UNCOVERED_AXES: dict[tuple, str] = {}


def _known_uncovered(cell_id: str, axes: tuple, reason: str):
    TABLE_A_KNOWN_UNCOVERED[cell_id] = reason
    TABLE_A_KNOWN_UNCOVERED_AXES[cell_id] = {"axes": axes, "reason": reason}


# off 模式：§0.3 legend「off 不入表」——resolve_cover_target 在 off 恆回同名
# .jpg，衍生圖 off 直接 no-op，<thumb> 置換在 has_fanart=False 時字面值不變，
# 改動前後逐位元組相同，故 off × 任何既有封面狀態 × 任何 overwrite 皆視為與
# A-off-1 同構（單一基線格已覆蓋該機制），其餘 off 組合以此理由列入未涵蓋。
for _cover in _TABLE_A_COVER_STATES:
    for _ovw in (False, True):
        if _cover == "none" and _ovw is False:
            continue  # 這格就是 A-off-1，已 COVERED
        _known_uncovered(
            f"A-off-{_cover}-{_ovw}", ("off", _cover, _ovw, "none"),
            "off 模式全域不入表（plan-112 §0.3 legend）：resolve_cover_target 在 "
            "off 恆回同名 .jpg、衍生圖 off no-op、<thumb> 字面值不變，任何既有封面/"
            "overwrite 組合與 A-off-1 同構，已由該基線格驗證此機制。",
        )

# P2-2（pre-merge Stage 2 review）：以下排除清單改用**硬編碼字面值**（照表
# B／C 的形狀），不再用 `_already_covered = any(v["axes"] == ... for v in
# TABLE_A_CELLS.values())` 動態查表。動態查表版本的問題：它會把「這格是否已
# 被 `_register` 登記」當成「是否要納入 known-uncovered」的判斷依據——一旦
# 某個 `_register(...)` 呼叫被意外刪掉，這個迴圈會自動把騰出來的格子吸收進
# `TABLE_A_KNOWN_UNCOVERED_AXES`，`test_registry_complete_manager_x_cover_
# state_x_overwrite` 因此恆綠、抓不到任何被刪掉的格子（已實測：刪
# `A-jf-7` 的 `_register`，四支 registry 守衛仍全綠）。改成字面值排除清單之
# 後，被刪掉的格子既不在 TABLE_A_CELLS、也不會被這裡的硬編碼字面值吸收進
# known-uncovered，`missing` 集合會真的出現該格、守衛因此轉紅。

# jellyfin：ovw=False 的六個既有封面狀態全部由 A-jf-1／A-jf-4／A-jf-5／
# A-jf-6a／A-jf-6b／A-jf-8 逐格明式驗證（見上方各自的 _register 呼叫），故
# ovw=False 這個分支完全不進本迴圈——它們的完整性單靠「有沒有被 _register
# 登記」判定，不需要、也不該被 known-uncovered 補位。
# ovw=True 只有 same_name_full 由 A-jf-7 驗過；其餘既有封面狀態 × ovw=True
# 的行為與 A-jf-7 同一套 preserve-gate 判斷式（should_preserve_cover 只看
# write_cover/overwrite_existing/cover_exists 三個布林，不看封面副檔名或
# 衍生圖完整度），差異只在「cover_exists」這個單一布林的來源，A-jf-7/A-jf-8
# 兩格已分別驗過 cover_exists=True（same_name_full）與 cover_exists=True
# （range_out，任意副檔名皆 servable）兩種代表性來源，缺衍生圖/fanart_layout
# 對 gate 判斷式本身無額外分支，故不再窮舉。
for _cover in _TABLE_A_COVER_STATES:
    if _cover == "same_name_full":
        continue  # A-jf-7（jellyfin, same_name_full, True, none）
    _known_uncovered(
        f"A-jf-{_cover}-True", ("jellyfin", _cover, True, "none"),
        "should_preserve_cover(write_cover, overwrite_existing, cover_exists) "
        "只是三個布林的純函式，不分支封面副檔名/衍生圖完整度；A-jf-7"
        "（same_name_full, ovw=True）與 A-jf-8（range_out, ovw=False, "
        "servable-regardless-of-ext）已代表性驗過 cover_exists 的兩種來源，"
        "其餘既有封面狀態 × overwrite 組合對 gate 判斷式本身無新分支，"
        "等價於這兩格之一，只差 fixture 的封面副檔名/衍生圖完整度。",
    )

# emby/kodi：只有「既有封面=無、ovw=False」由 A-emby-1／A-kodi-1 的 membership
# 回歸格驗證；其餘既有封面狀態 × overwrite 組合與 jellyfin 版（A-jf-1~8）
# 走同一段程式碼，只差 external_manager 常數，等價不再窮舉。
for _mgr in ("emby", "kodi"):
    for _cover in _TABLE_A_COVER_STATES:
        for _ovw in (False, True):
            if _cover == "none" and _ovw is False:
                continue  # A-emby-1 / A-kodi-1
            _known_uncovered(
                f"A-{_mgr}-{_cover}-{_ovw}", (_mgr, _cover, _ovw, "none"),
                "should_preserve_cover(write_cover, overwrite_existing, cover_exists) "
                "只是三個布林的純函式，不分支封面副檔名/衍生圖完整度，也不讀 "
                "external_manager 的具體值；jellyfin 版（A-jf-1~8）已窮舉這些 "
                "gate 分支，emby/kodi 版是同一段程式碼，等價不再窮舉。membership "
                "本身已由 A-emby-1/A-kodi-1 驗證。",
            )

# curator 軸：emby/kodi 的 curator 組合——curator 偵測/verbatim-copy 機制
# （resolve_ingest_plan 的 cover_fs 判斷、_write_movie_assets 的 source_media
# 三元組處理）完全不讀 external_manager，只有 _write_movie_assets 內
# generate_jellyfin_images 的呼叫與否受 STEM_IMAGE_MODES 白名單控制——curator
# verbatim-copy 路徑本身在三個 STEM_IMAGE_MODES 成員上是同一段程式碼，
# jellyfin 三格（A-jf-2/2b/3）已窮舉 curator 的三種非空狀態，等價於 emby/kodi
# 版（僅 external_manager 常數不同，不影響 curator 分支選擇）。
for _mgr in ("emby", "kodi"):
    for _curator in _TABLE_A_CURATOR_STATES:
        if _curator == "none":
            continue  # 已由 A-emby-1/A-kodi-1 membership 回歸格覆蓋
        _known_uncovered(
            f"A-{_mgr}-none-False-{_curator}", (_mgr, "none", False, _curator),
            "curator 偵測（resolve_ingest_plan 的 find_cover_image/L1.5）與 "
            "verbatim-copy（_write_movie_assets 的 source_media 三元組）皆不讀 "
            "external_manager；三者同屬 STEM_IMAGE_MODES，jellyfin 版"
            "（A-jf-2/2b/3）已窮舉 curator 三種非空狀態，等價於本組合，只差"
            "external_manager 常數。",
        )


# ===========================================================================
# 表 B｜既有庫補完（enrich_single）— 9 格
# ===========================================================================
#
# 每一格都 patch core.enricher.search_jav（見檔頭 docstring「為什麼表 B 每一
# 格都要 patch search_jav」）。mode 一律 'fill_missing'：Video 預設值
# （actresses=[]／director=""／series=None／label=""／tags=[]／release_date=""）
# 天然滿足 `_missing_fields` 非空，不需要額外刻意留空欄位。
# ---------------------------------------------------------------------------


class TestContractTableB_Enricher:
    """表 B｜enrich_single。9 格：Table 1 #1-#6（enricher 部分）+ off 基線 +
    emby/kodi membership 回歸。"""

    _TITLE = "Table B Title"
    _MAKER = "TableBMaker"

    def _make_repo(self, tmp_path, name):
        db_file = tmp_path / name
        init_db(db_file)
        return VideoRepository(db_path=db_file)

    def _scraper_data(self, number):
        return {
            "number": number, "title": self._TITLE, "actors": ["Actress B"],
            "cover": "http://example.com/cover.jpg", "date": "2024-01-01",
            "maker": self._MAKER, "director": "Dir", "series": "Ser",
            "label": "Lab", "tags": ["tag1"], "sample_images": [],
            "source": "javbus",
        }

    @staticmethod
    def _seed_bare_tracked_row(repo, video_dir, db_key, number):
        """預設 pre_stage：DB 已有一筆該片的 row（模擬「已掃描入庫、從未補完過」
        ——真實世界 fill_missing 的前提通常是片已被目錄掃描建檔），但
        `cover_path=""`。

        **這不是可省略的細節**：`_merge_meta` 的 cover_url 合併判斷是
        `merged.get("cover_url") == ""`（enricher.py:146）——若 base meta 連
        `cover_url` 這個 key 都不存在（完全沒有 DB row、也沒有 sidecar NFO，
        `meta` 全程是空 dict `{}`），`merged.get("cover_url")` 回傳 `None`，
        `None == ""` 恆假，scraper 的封面 URL 永遠合併不進去、`_write_cover`
        收到空字串直接短路回 False——這格测出来的『沒有下載』會是這個合併
        quirk 的副作用，不是 preserve gate 真正生效，是本檔實測踩到的一個
        真實 production 邊界（`_video_to_meta`/`_nfo_to_meta` 兩者都明確帶
        `"cover_url"` key，只有『完全沒有 DB row 也沒 NFO』這個組合會漏帶）。
        故「既有封面＝無」統一解讀為「DB 已追蹤、`cover_path` 為空字串」，
        不是「DB 裡連這支影片都不存在」。"""
        repo.upsert(Video(path=db_key, number=number, cover_path=""))

    def _run(self, tmp_path, name, *, number, external_manager,
              overwrite_existing=False, pre_stage=None):
        video_dir = tmp_path / f"{name}_video"
        video_dir.mkdir()
        video_file = video_dir / f"{number}.mp4"
        video_file.write_bytes(b"video-bytes")
        file_path = str(video_file)
        db_key = to_file_uri(uri_to_fs_path(file_path))

        repo = self._make_repo(tmp_path, f"{name}.db")
        (pre_stage or self._seed_bare_tracked_row)(repo, video_dir, db_key, number)

        scraper_data = self._scraper_data(number)
        with (
            patch("core.enricher.VideoRepository", return_value=repo),
            patch("core.enricher.search_jav", return_value=scraper_data) as mock_search,
            patch("core.organizer.requests.get", return_value=_mock_requests_get_jpeg()) as mock_get,
        ):
            from core.enricher import enrich_single
            result = enrich_single(
                file_path=file_path, number=number, mode="fill_missing",
                write_nfo=True, write_cover=True, write_extrafanart=False,
                overwrite_existing=overwrite_existing, external_manager=external_manager,
            )
        return SimpleNamespace(
            result=result, repo=repo, db_key=db_key, video_dir=video_dir,
            video_file=video_file, mock_search=mock_search, mock_get=mock_get,
        )

    # ------------------------------------------------------------------
    # B-off-1
    # ------------------------------------------------------------------
    def test_B_off_1_off_no_existing_downloads_plain_jpg(self, tmp_path):
        """B-off-1｜off／無／ovw=False。鎖：off 模式下載封面到 `{stem}.jpg`
        （stem=原始影片檔名 stem），不產 poster/fanart，DB cover_path 指向該檔。
        T3-T6 後：不變。"""
        ctx = self._run(tmp_path, "b_off_1", external_manager="off", number="BOFF1-001")
        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        nfo = ctx.video_dir / f"{stem}.nfo"
        assert cover.exists()
        assert not (ctx.video_dir / f"{stem}-poster.jpg").exists()
        assert not (ctx.video_dir / f"{stem}-fanart.jpg").exists()
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{stem}.jpg"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover))

    _register(TABLE_B_CELLS, "B-off-1", flips_after_t3=False, truth_table_ref="off-not-in-table",
               axes=("off", "none", False))

    # ------------------------------------------------------------------
    # B-off-2（pre-merge Stage 2 P1，補真格子）：既有 {stem}-fanart.jpg
    # （無同名 .jpg），off flavour，ovw=False
    # ------------------------------------------------------------------
    def test_B_off_2_existing_fanart_only_preserves_no_second_download(self, tmp_path, seed_crop_mode):
        """B-off-2（pre-merge Stage 2 P1 補格）｜off／既有 `{stem}-fanart.jpg`
        （無同名 `.jpg`）／ovw=False。

        這一格鎖的是 `resolve_cover_target` 第②步**刻意不看 flavour**這個設計
        （spec §2.1.1「既有片沿用它現在的位置」，見 AC2 加註）：`KNOWN_UNCOVERED`
        原本以「`resolve_cover_target` 在 off 恆回同名 `.jpg`」為由把 off ×
        全部既有封面狀態整組排除——**該理由對這個磁碟佈局是假的**，第①②步完全
        不讀 `external_manager`，只有第③步（兩候選皆不存在時的新建）才看
        flavour。off 在這個佈局下與 jellyfin（見 B-jf-4）走的是同一條 preserve
        路徑，差別只在 `_write_external_images` 的 off 早退不補 poster。

        實測（不是推理）：`resolve_cover_target(base_stem, 'off')` 在
        `-fanart.jpg` 存在、同名 `.jpg` 不存在時回傳 `-fanart.jpg`（第②步命中）
        → preserve gate 命中 → 零下載（`mock_get.call_count == 0`）、不寫第二份
        底圖、既有 `-fanart.jpg` bytes 原樣不動、DB `cover_path` 維持 pre_stage
        種的空字串（`cover_written=False` → `_db_upsert` 的 `local_cover_path`
        恆空）、`crop_mode` 不被重置。

        NFO 三 tag 的懸空邊界（AC7 具名邊界③）：off 分支的
        `_write_external_images` 對 `external_manager == 'off'` 直接早退回
        `{"poster": False, "fanart": False}`（enricher.py:262-264，不管磁碟上
        是否已有 `-fanart.jpg`）→ `has_poster=has_fanart=False` →
        `generate_nfo` 三個 tag 全部退回指向 `{stem}.jpg`——**該檔並不存在**，
        三 tag 皆懸空。這是已知且刻意接受的邊界（見 AC7 加註），不是本格要修的
        對象；本格斷言的是這個懸空的**實際字面值**，不是「不應該懸空」。"""
        number = "BOFF2-001"
        fanart_bytes_box: dict = {}

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            fanart = video_dir / f"{stem}-fanart.jpg"
            _write_jpeg(fanart, color=(40, 41, 42))
            fanart_bytes_box["pre_stage"] = fanart.read_bytes()
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=""))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_off_2", external_manager="off", number=number,
                         pre_stage=_stage)
        stem = ctx.video_file.stem
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        assert ctx.mock_get.call_count == 0, (
            "resolve_cover_target 第②步不看 flavour，off 也認得既有 -fanart.jpg → preserve 命中，不下載"
        )
        assert fanart.exists()
        assert fanart.read_bytes() == fanart_bytes_box["pre_stage"], "既有 fanart 內容不被覆寫（沿用）"
        assert not (ctx.video_dir / f"{stem}.jpg").exists(), "不寫第二份底圖（沿用既有 fanart 當 canonical）"
        assert not (ctx.video_dir / f"{stem}-poster.jpg").exists(), (
            "off 分支的 _write_external_images 早退，不裁 poster（與 jellyfin 版 B-jf-4 刻意相反）"
        )
        nfo = ctx.video_dir / f"{stem}.nfo"
        # has_poster=has_fanart=False（off 早退，不看磁碟）→ 三 tag 全退回
        # {stem}.jpg，且該檔不存在——刻意接受的懸空邊界（AC7 具名邊界③）。
        tags = _assert_nfo_tags_exist(nfo, {"poster": False, "thumb": False, "fanart": False})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{stem}.jpg", (
            "off 早退 → has_poster=has_fanart=False → 三 tag 退回同名 .jpg 字面值（該檔不存在）"
        )
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == "", "DB 不變（維持 pre_stage 種的空字串，本次未寫入新封面）"
        assert row.crop_mode == "manual", "cover_written=False → 不重置焦點"

    _register(TABLE_B_CELLS, "B-off-2", flips_after_t3=True, truth_table_ref="off-not-in-table",
               axes=("off", "fanart_layout", False))

    # ------------------------------------------------------------------
    # B-jf-1 / B-emby-1 / B-kodi-1 (Table1#1 + membership 回歸)
    # ------------------------------------------------------------------
    def _assert_cell1(self, tmp_path, name, manager, number, overwrite_existing=False):
        ctx = self._run(tmp_path, name, external_manager=manager, number=number,
                         overwrite_existing=overwrite_existing)
        stem = ctx.video_file.stem
        # T3 落地後（真理表 Table1#1）：既有=無 → resolve_cover_target 第③步
        # 新建，jellyfin 在 STEM_IMAGE_MODES → canonical 直接落在 -fanart.jpg。
        cover = ctx.video_dir / f"{stem}-fanart.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        nfo = ctx.video_dir / f"{stem}.nfo"
        assert cover.exists() and poster.exists() and fanart.exists()
        assert not (ctx.video_dir / f"{stem}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["thumb"] == f"{stem}-fanart.jpg", (
            "CD-112-5 落地後：<thumb> 改用 fanart_tag，has_fanart=True → -fanart.jpg"
        )
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover))
        assert ctx.mock_search.call_count >= 1

    def test_B_jf_1_jellyfin_no_existing(self, tmp_path):
        """B-jf-1（Table1#1）｜jellyfin／無／ovw=任意。鎖：下載=是、canonical=
        （翻面前）`{stem}.jpg`、產 poster+fanart。
        T3-T6 後：翻面，canonical→`-fanart.jpg`；DB 同步。"""
        self._assert_cell1(tmp_path, "b_jf_1", "jellyfin", "BJF1-001")

    _register(TABLE_B_CELLS, "B-jf-1", flips_after_t3=True, truth_table_ref="Table1#1",
               axes=("jellyfin", "none", False))

    def test_B_emby_1_membership_guard(self, tmp_path):
        """B-emby-1｜emby／無／ovw=False（membership guard，同 B-jf-1）。"""
        self._assert_cell1(tmp_path, "b_emby_1", "emby", "BEMB-001")

    _register(TABLE_B_CELLS, "B-emby-1", flips_after_t3=True, truth_table_ref="Table1#1",
               axes=("emby", "none", False))

    def test_B_kodi_1_membership_guard(self, tmp_path):
        """B-kodi-1｜kodi／無／ovw=False（membership guard，同 B-jf-1）。"""
        self._assert_cell1(tmp_path, "b_kodi_1", "kodi", "BKOD-001")

    _register(TABLE_B_CELLS, "B-kodi-1", flips_after_t3=True, truth_table_ref="Table1#1",
               axes=("kodi", "none", False))

    # ------------------------------------------------------------------
    # B-jf-2（Table1#2，AC1b-1 核心）：既有 {stem}.jpg 完整（含衍生圖），ovw=False
    # ------------------------------------------------------------------
    def test_B_jf_2_existing_full_no_overwrite_preserved(self, tmp_path, seed_crop_mode):
        """B-jf-2（Table1#2，AC1b-1 核心）｜jellyfin／既有`{stem}.jpg`完整
        （含既有 poster/fanart 衍生圖）／ovw=False。preserve gate
        （os.path.exists(cover_path) and not overwrite_existing）命中 → 不下載、
        不寫封面。衍生圖 gate 是磁碟真相（fanart_path.exists() and not ovw →
        reuse，不重新產生）→ 既有衍生圖原樣算數，不重生。DB/焦點不變。
        T3-T6 後：canonical 位置不變（本改動在此格的唯一承諾——AC1b-1）。

        T7 對帳更正（Opus 審核記錄追加要求 #1）：`flips_after_t3` 原標 False，
        實測翻面——但翻的只有②〈thumb〉：既有 poster/fanart 都在磁碟上、
        `_write_external_images` 判定 `has_fanart=True`（reuse，非重生），
        CD-112-5 讓〈thumb〉隨 fanart_tag 一起變成 -fanart.jpg；DB/crop_mode/
        封面 bytes 斷言逐字保留，不受影響。

        **mutation 自驗注意**：對這格做 `core/enricher.py:235` 一類的 mutation
        時，替代路徑字面值不可撞這格 fixture 已擺好的 `-fanart.jpg` 檔名——
        若替代值恰好等於 `{stem}-fanart.jpg`，preserve gate 會誤判「還是有
        封面」而僥倖通過，訊號會變弱（reviewer 已實測：換成不撞名的字面值後
        9/9 全紅）。"""
        number = "BJF2-001"

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _write_jpeg(cover, color=(1, 1, 1))
            _write_jpeg(video_dir / f"{stem}-poster.jpg", color=(2, 2, 2))
            _write_jpeg(video_dir / f"{stem}-fanart.jpg", color=(3, 3, 3))
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=to_file_uri(str(cover))))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_jf_2", external_manager="jellyfin", number=number,
                         pre_stage=_stage)
        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        assert cover.exists()
        assert poster.exists() and fanart.exists()
        assert ctx.mock_get.call_count == 0, "preserve 命中 → 不應呼叫 download_image/requests.get"
        # 既有衍生圖原樣算數（reuse，非重生）→ has_poster=has_fanart=True →
        # 〈poster〉/〈fanart〉走各自後綴、〈thumb〉（CD-112-5 落地後）改用
        # fanart_tag → -fanart.jpg。
        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover)), "DB cover_path 不變"
        assert row.crop_mode == "manual", "cover_written=False → 不清焦點"

    # 本格翻的是 ②〈thumb〉（CD-112-5），不是①正典位置；預測時 flips_after_t3
    # 只建模了①。
    _register(TABLE_B_CELLS, "B-jf-2", flips_after_t3=True, truth_table_ref="Table1#2",
               axes=("jellyfin", "same_name_full", False))

    # ------------------------------------------------------------------
    # B-jf-3（Table1#3，R2-P1-2 格）：既有 {stem}.jpg 但缺衍生圖，ovw=False
    # ------------------------------------------------------------------
    def test_B_jf_3_existing_missing_derivatives_backfilled(self, tmp_path, seed_crop_mode):
        """B-jf-3（Table1#3，R2-P1-2 格，⚠️ 與 Table 2 #5 不一致）｜jellyfin／
        既有`{stem}.jpg`但缺衍生圖／ovw=False。cover 本身 preserve（不下載）；
        衍生圖 gate 是 `cover_path.exists()` 磁碟真相、與 preserve 無關
        （enricher.py:264-284）→ **會補**（與唯讀路徑 A-jf-5 刻意相反，
        §0.4 發現③，表 A 不得抄表 B 的預測值）。DB/焦點不變。
        T3-T6 後：canonical 位置不變。

        T7 對帳更正（Opus 審核記錄追加要求 #1）：`flips_after_t3` 原標 False，
        實測翻面——但翻的只有②〈thumb〉：衍生圖本次被補齊 →
        `has_fanart=True`，CD-112-5 讓〈thumb〉隨 fanart_tag 一起變成
        -fanart.jpg；DB/crop_mode 斷言逐字保留，不受影響。"""
        number = "BJF3-001"

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _write_jpeg(cover, color=(9, 9, 9))
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=to_file_uri(str(cover))))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_jf_3", external_manager="jellyfin", number=number,
                         pre_stage=_stage)
        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        assert ctx.mock_get.call_count == 0, "cover 本身仍走 preserve，不下載"
        assert poster.exists() and fanart.exists(), "衍生圖 gate 看磁碟 cover_path.exists()，會補"
        # 衍生圖本次被補齊 → has_poster=has_fanart=True →〈poster〉/〈fanart〉
        # 走各自後綴、〈thumb〉（CD-112-5 落地後）改用 fanart_tag → -fanart.jpg。
        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover))
        assert row.crop_mode == "manual"

    # 本格翻的是 ②〈thumb〉（CD-112-5），不是①正典位置；預測時 flips_after_t3
    # 只建模了①。
    _register(TABLE_B_CELLS, "B-jf-3", flips_after_t3=True, truth_table_ref="Table1#3",
               axes=("jellyfin", "same_name_missing_derivatives", False))

    # ------------------------------------------------------------------
    # B-jf-4（Table1#4，差異最大格）：既有 {stem}-fanart.jpg（無 .jpg），ovw=False
    # ------------------------------------------------------------------
    def test_B_jf_4_existing_fanart_only_preserves_no_second_download(self, tmp_path, seed_crop_mode):
        """B-jf-4（Table1#4，差異最大格，**T7 對帳改名**——原名
        `..._still_downloads_second_cover` 鎖的是改動前行為，T3 之後結論整個
        反過來，維持舊名會誤導讀者）｜jellyfin／既有`{stem}-fanart.jpg`
        （無同名 `.jpg`）／ovw=False。

        改動前：`_write_cover` 的 preserve 判斷只探 `with_suffix('.jpg')`，
        `-fanart.jpg` 存在與否不影響它 → 判為「沒有封面」→ 下載，與既有
        `-fanart.jpg` 並存成兩份底圖。
        T3 落地後：`resolve_cover_target` 三步規則第②步認得既有
        `-fanart.jpg` 候選 → preserve gate 命中 → **不下載、沿用既有 fanart
        當 canonical、不寫第二份底圖**；`_write_external_images` 仍會用這張
        既有 fanart 當來源裁出 poster（衍生圖 gate 是磁碟真相，與 preserve
        無關）。DB `cover_path` 不變（維持 pre_stage 種的空字串——本次未寫入
        新封面，`_db_upsert` 的 `local_cover_path` 因 `cover_written=False`
        恆為空）、焦點不重置。

        DB 既有 row 的 `cover_path` 刻意留空（不指向那個孤兒 `-fanart.jpg`）——
        `-fanart.jpg` 是磁碟上的既有檔案（如手動匯入／先前 jellyfin 產出殘留），
        不代表 DB 已經記錄它為封面；若讓 `cover_path` 指向它，`_merge_meta`
        的 cover_url 合併判斷（`merged.get("cover_url") == ""`）會因為既有值
        非空而放棄合併 scraper 的封面 URL，此格會失去驗證「resolver 是否真的
        認得既有 fanart」的意義。"""
        number = "BJF4-001"
        fanart_bytes_box: dict = {}

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            fanart = video_dir / f"{stem}-fanart.jpg"
            _write_jpeg(fanart, color=(40, 41, 42))
            fanart_bytes_box["pre_stage"] = fanart.read_bytes()
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=""))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_jf_4", external_manager="jellyfin", number=number,
                         pre_stage=_stage)
        stem = ctx.video_file.stem
        fanart = ctx.video_dir / f"{stem}-fanart.jpg"
        assert ctx.mock_get.call_count == 0, (
            "T3 後 resolver 認得既有 -fanart.jpg 候選 → preserve 命中，不下載"
        )
        assert fanart.exists()
        assert fanart.read_bytes() == fanart_bytes_box["pre_stage"], "既有 fanart 內容不被覆寫（沿用）"
        assert not (ctx.video_dir / f"{stem}.jpg").exists(), "不寫第二份底圖（沿用既有 fanart 當 canonical）"
        # has_poster=has_fanart=True（fanart 沿用磁碟既有、poster 由
        # _write_external_images 用該既有 fanart 當來源裁出）→〈poster〉/
        # 〈fanart〉走各自後綴、〈thumb〉（CD-112-5）改用 fanart_tag → -fanart.jpg。
        poster = ctx.video_dir / f"{stem}-poster.jpg"
        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"
        assert poster.exists(), "poster 由既有 fanart 當來源裁切產生"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == "", "DB 不變（維持 pre_stage 種的空字串，本次未寫入新封面）"
        assert row.crop_mode == "manual", "cover_written=False → 不重置焦點"

    _register(TABLE_B_CELLS, "B-jf-4", flips_after_t3=True, truth_table_ref="Table1#4",
               axes=("jellyfin", "fanart_layout", False))

    # ------------------------------------------------------------------
    # B-jf-5（Table1#5，AC1b-2 核心）：既有 {stem}.jpg，ovw=True
    # ------------------------------------------------------------------
    def test_B_jf_5_existing_overwrite_true_redownloads_resets_focal(self, tmp_path, seed_crop_mode):
        """B-jf-5（Table1#5，AC1b-2 核心）｜jellyfin／既有`{stem}.jpg`／
        ovw=True。should_preserve_cover(True, True, True)=False → 不 preserve
        → 下載、覆寫回**同一個** `{stem}.jpg`、DB cover_path 值不變、焦點被
        重置。

        **R8**：焦點重置這條鎖的是**改動前就有的行為**（`cover_written=True` →
        `reset_focal_to_auto` 無條件觸發，CD-112-14 不觸碰），**不是 112 的
        承諾**——不得誤讀成「112 保證重刮會清焦點」。
        T3-T6 後：不變（理由與 A-jf-7 相同：resolver 第①步命中同名）。"""
        number = "BJF5-001"

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            cover = video_dir / f"{stem}.jpg"
            _write_jpeg(cover, color=(55, 66, 77))
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=to_file_uri(str(cover))))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_jf_5", external_manager="jellyfin", number=number,
                         overwrite_existing=True, pre_stage=_stage)
        stem = ctx.video_file.stem
        cover = ctx.video_dir / f"{stem}.jpg"
        assert cover.exists()
        assert cover.read_bytes() == _jpeg_bytes(), "覆寫回同一個檔名，內容是新下載的圖"
        # ovw=True → 衍生圖 gate 無條件重生 → has_poster=has_fanart=True →
        # 〈poster〉/〈fanart〉走各自後綴、〈thumb〉（CD-112-5 落地後）改用
        # fanart_tag → -fanart.jpg。
        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover)), "DB cover_path 字面值不變（同一路徑）"
        assert row.crop_mode == "auto", "cover_written=True → 無條件 reset（既有行為，非 112 承諾，見 R8）"

    # 本格翻的是 ②〈thumb〉（CD-112-5），不是①正典位置；預測時 flips_after_t3
    # 只建模了①。
    _register(TABLE_B_CELLS, "B-jf-5", flips_after_t3=True, truth_table_ref="Table1#5",
               axes=("jellyfin", "same_name_full", True))

    # ------------------------------------------------------------------
    # B-jf-6（Table1#6，§4.1 範圍外）：既有 {stem}.png，ovw=False
    # ------------------------------------------------------------------
    def test_B_jf_6_existing_range_out_extension_still_downloads(self, tmp_path, seed_crop_mode):
        """B-jf-6（Table1#6，§4.1 範圍外）｜jellyfin／既有`{stem}.png`／
        ovw=False。preserve 判斷只探 `{stem}.jpg`（不是任意副檔名）→ `.png`
        不算「已有封面」→ 下載到 `{stem}.jpg`。canonical=`{stem}.jpg`、DB 改變、
        焦點清除。**與唯讀路徑 A-jf-8 刻意相反**（§0.4 發現④：唯讀 preserve
        gate 讀 DB cover_path、任何副檔名皆 servable；非唯讀只認 `.jpg`）。
        T3-T6 後：翻面（canonical→`-fanart.jpg`；§0.4 發現②：「是否重新產生」
        不變、「產到哪」變）。"""
        number = "BJF6-001"

        def _stage(repo, video_dir, db_key, number_):
            stem = number_
            cover_png = video_dir / f"{stem}.png"
            _write_jpeg(cover_png, color=(15, 16, 17))
            repo.upsert(Video(path=db_key, number=number_, title="Old", maker="OldMaker",
                               cover_path=to_file_uri(str(cover_png))))
            assert seed_crop_mode(repo, db_key, "manual") is True

        ctx = self._run(tmp_path, "b_jf_6", external_manager="jellyfin", number=number,
                         pre_stage=_stage)
        stem = ctx.video_file.stem
        # T3 落地後：.png 不滿足三步規則第①②步（只認 .jpg／-fanart.jpg 候選）
        # → 第③步新建，jellyfin 在 STEM_IMAGE_MODES → 下載目標是 -fanart.jpg
        # （不再是裸 stem 同名 .jpg，§0.4 發現②：「是否重新產生」不變、
        # 「產到哪」變）。
        cover = ctx.video_dir / f"{stem}-fanart.jpg"
        assert cover.exists(), ".png 不滿足 preserve gate（只認 .jpg/-fanart.jpg）→ 下載"
        assert not (ctx.video_dir / f"{stem}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        assert ctx.mock_get.call_count >= 1
        # cover_written=True，衍生圖 gate 之後跑（新下載的 cover 存在）→
        # has_poster=has_fanart=True →〈poster〉/〈fanart〉走各自後綴、
        # 〈thumb〉（CD-112-5 落地後）改用 fanart_tag → -fanart.jpg。
        nfo = ctx.video_dir / f"{stem}.nfo"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == f"{stem}-poster.jpg"
        assert tags["thumb"] == f"{stem}-fanart.jpg"
        assert tags["fanart"] == f"{stem}-fanart.jpg"
        row = ctx.repo.get_by_path(ctx.db_key)
        assert row.cover_path == to_file_uri(str(cover)), "DB 改變 → 指向新下載的 -fanart.jpg"
        assert row.crop_mode == "auto", "cover_written=True → 焦點清除"

    _register(TABLE_B_CELLS, "B-jf-6", flips_after_t3=True, truth_table_ref="Table1#6",
               axes=("jellyfin", "range_out_png_or_folder", False))

    # ------------------------------------------------------------------
    # BE-TEST-05：表 B registry 完整性
    # ------------------------------------------------------------------
    def test_registry_complete(self):
        """manager × 既有封面狀態 × overwrite 完整笛卡兒積必須全部被
        TABLE_B_CELLS ∪ TABLE_B_KNOWN_UNCOVERED_AXES 涵蓋（BE-TEST-05）。"""
        all_cells = {
            (mgr, cover, ovw)
            for mgr in _MANAGERS
            for cover in _TABLE_B_C_COVER_STATES
            for ovw in (False, True)
        }
        declared = {v["axes"] for v in TABLE_B_CELLS.values()} | set(TABLE_B_KNOWN_UNCOVERED_AXES)
        missing = all_cells - declared
        assert not missing, f"表 B 未宣告涵蓋與否的組合：{sorted(missing)}"


TABLE_B_KNOWN_UNCOVERED_AXES: set = set()


def _b_known_uncovered(cell_id: str, axes: tuple, reason: str):
    TABLE_B_KNOWN_UNCOVERED[cell_id] = reason
    TABLE_B_KNOWN_UNCOVERED_AXES.add(axes)


# off：§0.3 legend「off 不入表」——但排除清單不得建立在「resolve_cover_target
# 在 off 恆回同名 .jpg」這個假前提上（⚠️ T9 erratum，pre-merge Stage 2 P1：
# 該句為假。三步規則第①②步完全不讀 external_manager，只有第③步——兩候選皆
# 不存在時的新建——才依 flavour 分流。off 與 jellyfin/emby/kodi 在①②步走的是
# 同一段程式碼，差別僅在第③步新建落點、以及 _write_external_images 的 off
# 早退不補 poster/fanart。`fanart_layout`／`ovw=False` 這格已由 B-off-2
# 實測覆蓋、移出本清單；其餘 off 組合維持未涵蓋，理由改寫如下）。
for _cover in _TABLE_B_C_COVER_STATES:
    for _ovw in (False, True):
        if _cover == "none" and _ovw is False:
            continue  # B-off-1
        if _cover == "fanart_layout" and _ovw is False:
            continue  # B-off-2（pre-merge Stage 2 P1 補格）
        _b_known_uncovered(
            f"B-off-{_cover}-{_ovw}", ("off", _cover, _ovw),
            "off 模式除 B-off-1／B-off-2 已實測覆蓋的兩格外，其餘既有封面狀態 × "
            "overwrite 組合未逐格驗證。resolve_cover_target 第①②步（同名／既有 "
            "fanart 沿用）不讀 flavour，機制已由 B-off-1（無既有封面 → 第③步新建）"
            "與 B-off-2（既有 -fanart.jpg → 第②步沿用）代表性覆蓋；同名 .jpg 既有"
            "（含缺衍生圖／ovw=True 等組合）走的是同一段第①步程式碼，理由同表 A "
            "對應條目，未另立格子。",
        )

# jellyfin：ovw=True 的其餘既有封面狀態（除 same_name_full，已由 B-jf-5 覆蓋）。
# should_preserve_cover(write_cover, overwrite_existing, cover_exists) 在
# overwrite_existing=True 時，`(cover_exists and not overwrite_existing)` 恆為
# False → preserve 恆假，與 cover_exists（也就是「既有封面狀態」這個軸）完全
# 無關——下載/正典位置/DB 更新的分支選擇在 ovw=True 時對所有既有封面狀態
# 都收斂成同一條路徑。`_write_external_images` 的 regenerate gate 同理
# （`fanart_path.exists() and not overwrite_existing` 恆假）。B-jf-5 已代表性
# 驗過 ovw=True 這整條收斂路徑（下載、regenerate、DB 更新、焦點重置），其餘
# 既有封面狀態只是「原本被覆寫的檔案長什麼樣」不同，對程式碼分支選擇無新增
# 判斷式，故不重複窮舉。
for _cover in _TABLE_B_C_COVER_STATES:
    if _cover == "same_name_full":
        continue  # B-jf-5
    _b_known_uncovered(
        f"B-jf-{_cover}-True", ("jellyfin", _cover, True),
        "overwrite_existing=True 時 should_preserve_cover 恆假，與既有封面狀態"
        "（cover_exists 的具體來源）無關——B-jf-5 已代表性驗過 ovw=True 這整條"
        "收斂路徑（下載/regenerate/DB 更新/焦點重置），其餘既有封面狀態對分支"
        "選擇無新增判斷式，等價於 B-jf-5，只差『被覆寫的舊檔長什麼樣』。",
    )

# emby/kodi：既有封面族 × overwrite 的完整版本——membership 回歸格
# （B-emby-1/B-kodi-1）已驗證三個 STEM_IMAGE_MODES 在同一 call site 的
# `in STEM_IMAGE_MODES` 判斷確實一致生效；`_write_cover`/`_write_external_images`
# 的 preserve/regenerate gate 邏輯完全不讀 external_manager 的具體值（只判斷
# `!= "off"` 或 `in STEM_IMAGE_MODES`），故 jellyfin 版的 B-jf-2~6 五格已窮舉
# 的 gate 分支對 emby/kodi 是同一段程式碼，等價、不再窮舉。
for _mgr in ("emby", "kodi"):
    for _cover in _TABLE_B_C_COVER_STATES:
        for _ovw in (False, True):
            if _cover == "none" and _ovw is False:
                continue  # membership 回歸格已覆蓋
            _b_known_uncovered(
                f"B-{_mgr}-{_cover}-{_ovw}", (_mgr, _cover, _ovw),
                "_write_cover/_write_external_images 的 preserve/regenerate gate 不讀"
                "external_manager 的具體值（只判斷 != 'off' 或 in STEM_IMAGE_MODES）；"
                "jellyfin 版（B-jf-2~6）已窮舉這些 gate 分支，emby/kodi 版是同一段"
                "程式碼，等價不再窮舉。membership 本身已由 B-emby-1/B-kodi-1 驗證。",
            )


# ===========================================================================
# 表 C｜首次整理（organize_file + try_inflow_upsert）— 4 格
# ===========================================================================
#
# `try_inflow_upsert` 內部固定 `VideoRepository()`（core/db_inflow.py:161），
# 而 `VideoRepository()` 的預設 db 路徑 `get_db_path()` 是硬編碼
# `<repo_root>/output/openaver.db`（core/database/connection.py:15-22，非
# config 驅動）——`temp_config_path` 對它沒有作用。不 patch
# `core.db_inflow.VideoRepository`，Table C 的 DB 斷言就會打進真正的專案
# 資料庫，這是絕對不能接受的（見檔頭「NO-PRIVATE-PATCH」第 5 項的完整說明，
# 這是本檔唯一超出 task card 原始四項清單的 patch，已於回報中明確標註）。
# 除此之外，一律用 `temp_config_path` fixture 寫真 config（`gallery.directories`
# 指向 tmp_path 目標資料夾），不 patch `core.db_inflow.load_config` /
# `find_matched_directory`（task card 明文禁止的陷阱）。
# ---------------------------------------------------------------------------


class TestContractTableC_Organizer:
    """表 C｜organize_file + try_inflow_upsert。4 格：Table 1 #7 × 四個 manager。"""

    _TITLE = "Table C Title"
    _MAKER = "TableCMaker"

    def _organize_config(self, external_manager):
        return {
            "create_folder": False,
            "filename_format": "{num} {title}",
            "max_title_length": 50,
            "max_filename_length": 60,
            "suffix_keywords": [],
            "external_manager": external_manager,
            "download_sample_images": False,
        }

    def _run(self, tmp_path, temp_config_path, name, *, number, external_manager):
        library_dir = tmp_path / f"{name}_library"
        library_dir.mkdir()
        video_file = library_dir / f"{number}-SOURCE.mp4"
        video_file.write_bytes(b"video-bytes")

        cfg = core_config.AppConfig().model_dump()
        cfg["gallery"]["directories"] = [str(library_dir)]
        temp_config_path.write_text(json.dumps(cfg), encoding="utf-8")

        db_file = tmp_path / f"{name}.db"
        init_db(db_file)
        repo = VideoRepository(db_path=db_file)

        metadata = {
            "number": number, "title": self._TITLE, "actors": ["Actress C"],
            "tags": ["tag1"], "date": "2024-01-01", "maker": self._MAKER,
            "cover": "http://example.com/cover.jpg",
        }

        with (
            patch("core.organizer.requests.get", return_value=_mock_requests_get_jpeg()) as mock_get,
            patch("core.db_inflow.VideoRepository", return_value=repo),
        ):
            from core.organizer import organize_file
            from core.db_inflow import try_inflow_upsert

            organize_result = organize_file(str(video_file), metadata, self._organize_config(external_manager))
            assert organize_result["success"] is True, organize_result
            new_path = organize_result["new_filename"]
            inflow_status = try_inflow_upsert(new_path)

        return SimpleNamespace(
            organize_result=organize_result, inflow_status=inflow_status,
            repo=repo, library_dir=library_dir, new_path=Path(new_path),
            mock_get=mock_get,
        )

    def test_C_off_first_organize_plain_jpg(self, tmp_path, temp_config_path):
        """C-off｜off（唯一可達列，organize_file 是 shutil.move 新檔案，無既有
        封面軸）。鎖：下載=是、canonical=`{filename_base}.jpg`、無 poster/
        fanart、DB=`{filename_base}.jpg`（經 try_inflow_upsert 重掃磁碟得到，
        非 result['cover_path']）。
        T3-T6 後：不變。"""
        ctx = self._run(tmp_path, temp_config_path, "c_off", number="COFF-001", external_manager="off")
        basename = f"COFF-001 {self._TITLE}"
        cover = ctx.library_dir / f"{basename}.jpg"
        nfo = ctx.library_dir / f"{basename}.nfo"
        assert cover.exists()
        assert not (ctx.library_dir / f"{basename}-poster.jpg").exists()
        assert not (ctx.library_dir / f"{basename}-fanart.jpg").exists()
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["poster"] == tags["thumb"] == tags["fanart"] == f"{basename}.jpg"
        assert ctx.inflow_status == "synced", (
            "not_linked 代表 fixture 的 gallery.directories 沒真的覆蓋到 tmp_path "
            "目標目錄，DB 斷言會恆為『沒有這筆記錄』——這是 fixture 設定錯誤，不能"
            "靜默通過"
        )
        new_uri = to_file_uri(str(ctx.new_path))
        row = ctx.repo.get_by_path(new_uri)
        assert row is not None, "try_inflow_upsert 應已把這支影片寫進 DB"
        assert row.cover_path == to_file_uri(str(cover))

    _register(TABLE_C_CELLS, "C-off", flips_after_t3=False, truth_table_ref="off-not-in-table",
               axes=("off", "none", False))

    def _assert_manager_cell(self, tmp_path, temp_config_path, name, manager, number):
        ctx = self._run(tmp_path, temp_config_path, name, number=number, external_manager=manager)
        basename = f"{number} {self._TITLE}"
        # T3（⑨）落地後（真理表 Table1#7）：organize_file 首次整理，canonical
        # 直接落在 -fanart.jpg（同檔保護），不再有獨立的裸 stem 同名 .jpg；
        # DB 端 find_cover_image L1 miss、L1.5 命中 fanart（CD-112-6 不改優先序）。
        cover = ctx.library_dir / f"{basename}-fanart.jpg"
        poster = ctx.library_dir / f"{basename}-poster.jpg"
        fanart = ctx.library_dir / f"{basename}-fanart.jpg"
        nfo = ctx.library_dir / f"{basename}.nfo"
        assert cover.exists() and poster.exists() and fanart.exists()
        assert not (ctx.library_dir / f"{basename}.jpg").exists(), "翻面後沒有獨立的裸 stem 同名封面"
        tags = _assert_nfo_tags_exist(nfo, {"poster": True, "thumb": True, "fanart": True})
        assert tags["thumb"] == f"{basename}-fanart.jpg", (
            "CD-112-5 落地後：<thumb> 改用 fanart_tag，has_fanart=True → -fanart.jpg"
        )
        assert ctx.inflow_status == "synced"
        new_uri = to_file_uri(str(ctx.new_path))
        row = ctx.repo.get_by_path(new_uri)
        assert row is not None
        assert row.cover_path == to_file_uri(str(cover)), (
            "find_cover_image L1 miss、L1.5 命中 fanart → DB cover_path 指向 canonical（-fanart.jpg）"
        )

    def test_C_jf_first_organize_jellyfin(self, tmp_path, temp_config_path):
        """C-jf（Table1#7）｜jellyfin。鎖：下載=是、canonical=`{filename_base}.jpg`、
        產 poster+fanart、DB 經 find_cover_image L1 命中同名 `.jpg`。
        T3-T6 後：**翻面**，canonical→`-fanart.jpg`；DB 端 find_cover_image
        L1 miss、L1.5 命中 fanart（CD-112-6 不改優先序）——這格是『讀取端零
        改動仍然正確』的活體證明，T4 對帳時特別看這格。"""
        self._assert_manager_cell(tmp_path, temp_config_path, "c_jf", "jellyfin", "CJF-001")

    _register(TABLE_C_CELLS, "C-jf", flips_after_t3=True, truth_table_ref="Table1#7",
               axes=("jellyfin", "none", False))

    def test_C_emby_membership_guard(self, tmp_path, temp_config_path):
        """C-emby（membership guard）｜同 C-jf。"""
        self._assert_manager_cell(tmp_path, temp_config_path, "c_emby", "emby", "CEMB-001")

    _register(TABLE_C_CELLS, "C-emby", flips_after_t3=True, truth_table_ref="Table1#7",
               axes=("emby", "none", False))

    def test_C_kodi_membership_guard(self, tmp_path, temp_config_path):
        """C-kodi（membership guard）｜同 C-jf。"""
        self._assert_manager_cell(tmp_path, temp_config_path, "c_kodi", "kodi", "CKOD-001")

    _register(TABLE_C_CELLS, "C-kodi", flips_after_t3=True, truth_table_ref="Table1#7",
               axes=("kodi", "none", False))

    # ------------------------------------------------------------------
    # BE-TEST-05：表 C registry 完整性
    # ------------------------------------------------------------------
    def test_registry_complete(self):
        """manager × 既有封面狀態（只有『無』這一列可達，§0.3 Table 1 已註明
        organize_file 恆是首次整理）× overwrite（不適用，恆 False）必須全部被
        TABLE_C_CELLS ∪ TABLE_C_KNOWN_UNCOVERED_AXES 涵蓋（BE-TEST-05）。"""
        all_cells = {(mgr, "none", False) for mgr in _MANAGERS}
        declared = {v["axes"] for v in TABLE_C_CELLS.values()} | set(TABLE_C_KNOWN_UNCOVERED_AXES)
        missing = all_cells - declared
        assert not missing, f"表 C 未宣告涵蓋與否的組合：{sorted(missing)}"


TABLE_C_KNOWN_UNCOVERED_AXES: set = set()
# 表 C 的完整維度笛卡兒積只有「manager × 既有封面=無 × ovw=False」（§0.3 Table 1
# 已註明 organize_file 是 shutil.move 新檔案，不存在「既有封面」軸——`result`
# dict 本身沒有 overwrite 概念）。四個 manager 已全部窮舉（C-off/C-jf/C-emby/
# C-kodi），無未涵蓋組合，KNOWN_UNCOVERED 為空集合——保留這個空 set 是刻意的：
# 讓 test_registry_complete 走完整的「宣告 ∪ 未涵蓋 == 完整維度」邏輯，而不是
# 省略未涵蓋分支導致邏輯只剩單邊，兩者在四格全covered時數學上等價，但保留完整
# 形狀讓未來若真的補上其他既有封面狀態的分支時，這支測試的失敗訊息維持一致。
