"""TASK-132b-T6: 四條寫入路徑對帳（整理／補完／唯讀產出／掃描）。

驗證 132b 擴充欄位（duration / director / label / series / sample_images）
在四條路徑中皆能正確寫入 NFO 或磁碟，並由掃描路徑正確讀回。

關於欄位對帳的特殊設計與限制說明：
1. votes 不列入任何對帳清單（F4）：
   votes 沒有任何寫入端：不進 DB（core/database/ 零出現）、
   不進 NFO（generate_nfo 沒這個參數）、不上畫面（前端零出現）。
   其唯一消費者為 core/source_merger.py 的跨來源合併（text_source 為空時備援）。
   若列入對帳清單測試將永遠轉紅。
2. 掃描路徑（scan）與前三條路徑不對稱：
   前三條路徑（organize / enrich / readonly）負責「寫 NFO 與 extrafanart」；
   掃描路徑（scan）負責「讀 NFO 與 extrafanart 並寫入 VideoInfo / DB」。
   NFO 中的 plot、rating、website 欄位在 DB 的 videos 資料表及 VideoInfo 中無對應欄位儲存，
   這是資料庫架構設計（非回歸），故掃描路徑只斷言 DB / VideoInfo 實際支援的欄位。
3. 對帳清單硬編碼（BE-TEST-09）：
   不得由 generate_nfo 簽名或 Video 欄位反推，確保為獨立基準。
"""

from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import readonly_producer
from core.database import Video, VideoRepository, init_db
from core.gallery_scanner import VideoScanner
from core.organizer import organize_file

# 🔴 硬編碼寫死（BE-TEST-09）。不得由 generate_nfo 的簽名或 Video 的欄位反推——
# 反推的話 missing 恆為空集合，這支測試結構上不可能轉紅。
#
# 「132b 之前就有」與「132b 補的」分開列，是為了讓回歸訊息指得出是哪一種。
_NFO_TAGS_BEFORE_132B = frozenset({
    "num",
    "title",
    "premiered",
    "studio",
    "actor",
    "genre",
    "plot",
    "rating",
    "website",
})

_NFO_TAGS_ADDED_BY_132B = frozenset({
    "runtime",  # ← Video.duration
    "director",  # ← Video.director
    "label",  # ← Video.label
    "set",  # ← Video.series
})

# 掃描路徑對應的 VideoInfo / DB 欄位（votes 不入庫、plot/rating/website 不進 VideoInfo）
_SCAN_FIELDS_BEFORE_132B = frozenset({
    "num",
    "title",
    "date",
    "maker",
    "actor",
    "genre",
})

_SCAN_FIELDS_ADDED_BY_132B = frozenset({
    "duration",
    "director",
    "label",
    "series",
})


def _fake_download_image(url: str, dest: str, **kwargs) -> bool:
    """Mock 下載圖片：建立目標目錄並寫入虛擬圖片 bytes。"""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    return True


def _get_element_content(root: ET.Element, tag: str) -> str:
    """取得 NFO 中指定 tag 的非空文字內容（支援 set/name, actor/name 等結構）。"""
    elem = root.find(tag)
    if elem is None:
        return ""
    if tag == "set":
        name_elem = elem.find("name")
        if name_elem is not None and name_elem.text:
            return name_elem.text.strip()
        return (elem.text or "").strip()
    if tag == "actor":
        name_elem = elem.find("name")
        if name_elem is not None and name_elem.text:
            return name_elem.text.strip()
        return (elem.text or "").strip()
    return (elem.text or "").strip()


def _assert_nfo_tags_present(nfo_text: str, path_name: str) -> None:
    """斷言 NFO XML 中包含兩組硬編碼清單的所有 tag 且內容非空。"""
    root = ET.fromstring(nfo_text)
    missing_before = {
        tag for tag in _NFO_TAGS_BEFORE_132B
        if not _get_element_content(root, tag)
    }
    missing_added = {
        tag for tag in _NFO_TAGS_ADDED_BY_132B
        if not _get_element_content(root, tag)
    }
    assert not missing_before, (
        f"{path_name}的 NFO 少了 {missing_before}（132b 之前就有那組）"
    )
    assert not missing_added, (
        f"{path_name}的 NFO 少了 {missing_added}（132b 補的那組）"
    )


# ── 1. 整理路徑（organize_file）──────────────────────────────────────────────

def _organize_config(**overrides):
    cfg = {
        "create_folder": True,
        "filename_format": "[{num}] {title}{suffix}",
        "download_cover": False,
        "download_sample_images": True,
        "create_nfo": True,
        "max_title_length": 50,
        "max_filename_length": 60,
        "suffix_keywords": ["-cd1", "-cd2", "-4k", "-uc"],
        "external_manager": "off",
    }
    cfg.update(overrides)
    return cfg


def _organize_metadata(**overrides):
    md = {
        "number": "ABC-123",
        "title": "一般標題",
        "original_title": "オリジナルタイトル",
        "actors": ["女優A", "女優B"],
        "tags": ["TAG1", "TAG2"],
        "maker": "Studio",
        "date": "2024-01-15",
        "cover": "",
        "url": "https://example.com/ABC-123",
        "director": "導演名",
        "duration": 120,
        "series": "系列名",
        "label": "廠牌名",
        "_summary": "這是劇情簡介",
        "_rating": 4.5,
        "sample_images": [
            "https://example.com/sample1.jpg",
            "https://example.com/sample2.jpg",
        ],
        "preview_sample_images": [
            "https://example.com/preview1.jpg",
            "https://example.com/preview2.jpg",
        ],
    }
    md.update(overrides)
    return md


def _run_organize(tmp_path: Path, filename: str = "ABC-123.mp4", metadata: dict = None, **config_overrides):
    work = tmp_path / "organize"
    work.mkdir(parents=True, exist_ok=True)
    src = work / filename
    src.write_bytes(b"content")
    md = metadata if metadata is not None else _organize_metadata()
    cfg = _organize_config(**config_overrides)
    with patch("core.organizer.download_image", side_effect=_fake_download_image):
        result = organize_file(str(src), md, cfg)
    assert result["success"] is True, f"organize 失敗: {result.get('error')}"
    return result, md


def test_organize_path_field_coverage(tmp_path: Path):
    """整理路徑（organize_file）：完整寫入 132b 前後所有 NFO tag 與 extrafanart 劇照。"""
    result, _ = _run_organize(tmp_path)
    nfo_path = Path(result["nfo_path"])
    assert nfo_path.is_file(), f"NFO 檔案不存在: {nfo_path}"

    nfo_text = nfo_path.read_text(encoding="utf-8")
    _assert_nfo_tags_present(nfo_text, "整理路徑")

    # sample_images 走 extrafanart/ 目錄（檔案存在性對帳，非 NFO tag）
    extrafanart_dir = nfo_path.parent / "extrafanart"
    assert extrafanart_dir.is_dir(), "整理路徑未建立 extrafanart 目錄"
    assert (extrafanart_dir / "fanart1.jpg").is_file(), "整理路徑缺少 extrafanart/fanart1.jpg"
    assert (extrafanart_dir / "fanart2.jpg").is_file(), "整理路徑缺少 extrafanart/fanart2.jpg"


# ── 2. 補完路徑（enrich_single）──────────────────────────────────────────────

def _scraper_result(number: str = "ABC-123", **overrides):
    data = {
        "number": number,
        "title": "一般標題",
        "original_title": "オリジナルタイトル",
        "actors": ["女優A", "女優B"],
        "cover": "https://example.com/cover.jpg",
        "date": "2024-01-15",
        "maker": "Studio",
        "director": "導演名",
        "series": "系列名",
        "label": "廠牌名",
        "tags": ["TAG1", "TAG2"],
        "sample_images": [
            "https://example.com/sample1.jpg",
            "https://example.com/sample2.jpg",
        ],
        "preview_sample_images": [
            "https://example.com/preview1.jpg",
            "https://example.com/preview2.jpg",
        ],
        "duration": 120,
        "url": "https://example.com/ABC-123",
        "_summary": "這是劇情簡介",
        "_rating": 4.5,
        "source": "javdb",
    }
    data.update(overrides)
    return data


def _run_enrich(tmp_path: Path, filename: str = "ABC-123.mp4", number: str = "ABC-123", scraper_overrides: dict = None):
    work = tmp_path / "enrich"
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "test.db"
    init_db(db_path)
    repo = VideoRepository(db_path=db_path)
    video_path = work / filename
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")

    patches = (
        patch("core.enricher.VideoRepository", MagicMock(return_value=repo)),
        patch("core.enricher.download_image", side_effect=_fake_download_image),
        patch(
            "core.enricher.search_jav",
            side_effect=AssertionError("search_jav 不應被呼叫（已提供 scraper_data）"),
        ),
    )
    scraper_data = _scraper_result(number=number, **(scraper_overrides or {}))
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number=number,
            mode="refresh_full",
            write_nfo=True,
            write_cover=False,
            write_extrafanart=True,
            scraper_data=scraper_data,
        )
    assert result.success is True, f"enrich 失敗: {result.error}"
    assert nfo_path.is_file(), f"NFO 檔案未產生: {nfo_path}"
    nfo_text = nfo_path.read_text(encoding="utf-8")
    extrafanart_dir = video_path.parent / "extrafanart"
    return result, nfo_text, extrafanart_dir, repo


def test_enrich_path_field_coverage(tmp_path: Path):
    """補完路徑（enrich_single）：完整寫入 132b 前後所有 NFO tag 與 extrafanart 劇照。"""
    _, nfo_text, extrafanart_dir, _ = _run_enrich(tmp_path)
    _assert_nfo_tags_present(nfo_text, "補完路徑")

    # sample_images 走 extrafanart/ 目錄（檔案存在性對帳，非 NFO tag）
    assert extrafanart_dir.is_dir(), "補完路徑未建立 extrafanart 目錄"
    assert (extrafanart_dir / "fanart1.jpg").is_file(), "補完路徑缺少 extrafanart/fanart1.jpg"
    assert (extrafanart_dir / "fanart2.jpg").is_file(), "補完路徑缺少 extrafanart/fanart2.jpg"


# ── 3. 唯讀產出路徑（_write_movie_assets）───────────────────────────────────

def _readonly_config(**overrides):
    cfg = {
        "filename_format": "{num} {title}",
        "max_filename_length": 60,
        "max_title_length": 50,
        "suffix_keywords": [],
        "external_manager": "off",
        "download_sample_images": True,
    }
    cfg.update(overrides)
    return cfg


def _readonly_meta(**overrides):
    md = {
        "number": "ABC-123",
        "title": "一般標題",
        "original_title": "オリジナルタイトル",
        "actors": ["女優A", "女優B"],
        "tags": ["TAG1", "TAG2"],
        "maker": "Studio",
        "date": "2024-01-15",
        "cover": "",
        "url": "https://example.com/ABC-123",
        "director": "導演名",
        "duration": 120,
        "series": "系列名",
        "label": "廠牌名",
        "_summary": "這是劇情簡介",
        "_rating": 4.5,
        "sample_images": [
            "https://example.com/sample1.jpg",
            "https://example.com/sample2.jpg",
        ],
        "preview_sample_images": [
            "https://example.com/preview1.jpg",
            "https://example.com/preview2.jpg",
        ],
    }
    md.update(overrides)
    return md


def _run_readonly(tmp_path: Path, filename: str = "ABC-123.mp4", meta: dict = None, **config_overrides):
    work = tmp_path / "readonly"
    work.mkdir(parents=True, exist_ok=True)
    source_dir = work / "source"
    source_dir.mkdir(exist_ok=True)
    source_path = source_dir / filename
    source_path.write_bytes(b"video")
    movie_dir = work / "output" / "movie"
    md = meta if meta is not None else _readonly_meta()
    cfg = _readonly_config(**config_overrides)
    fd = readonly_producer._format_data(md, str(source_path), cfg)
    with patch("core.readonly_producer.download_image", side_effect=_fake_download_image):
        readonly_producer._write_movie_assets(
            str(movie_dir),
            md,
            fd,
            str(source_path),
            cfg,
            cover_strategy=("none",),
        )
    nfos = list(movie_dir.glob("*.nfo"))
    assert len(nfos) == 1, f"預期恰好一份 NFO，實際 {len(nfos)}: {nfos}"
    nfo_path = nfos[0]
    extrafanart_dir = movie_dir / "extrafanart"
    return md, nfo_path.read_text(encoding="utf-8"), nfo_path, extrafanart_dir


def test_readonly_path_field_coverage(tmp_path: Path):
    """唯讀產出路徑（_write_movie_assets）：完整寫入 132b 前後所有 NFO tag 與 extrafanart 劇照。"""
    _, nfo_text, _, extrafanart_dir = _run_readonly(tmp_path)
    _assert_nfo_tags_present(nfo_text, "唯讀產出路徑")

    # sample_images 走 extrafanart/ 目錄（檔案存在性對帳，非 NFO tag）
    assert extrafanart_dir.is_dir(), "唯讀產出路徑未建立 extrafanart 目錄"
    assert (extrafanart_dir / "fanart1.jpg").is_file(), "唯讀產出路徑缺少 extrafanart/fanart1.jpg"
    assert (extrafanart_dir / "fanart2.jpg").is_file(), "唯讀產出路徑缺少 extrafanart/fanart2.jpg"


# ── 4. 掃描路徑（VideoScanner().scan_file）───────────────────────────────────

def _run_scan(tmp_path: Path, filename: str = "ABC-123.mp4", nfo_body: str = None, create_extrafanart: bool = True):
    work = tmp_path / "scan"
    work.mkdir(parents=True, exist_ok=True)
    video = work / filename
    video.write_bytes(b"\x00" * 100)
    if nfo_body is not None:
        video.with_suffix(".nfo").write_text(textwrap.dedent(nfo_body), encoding="utf-8")
    if create_extrafanart:
        ef_dir = work / "extrafanart"
        ef_dir.mkdir(parents=True, exist_ok=True)
        (ef_dir / "fanart1.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
        (ef_dir / "fanart2.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    return VideoScanner().scan_file(str(video))


def test_scan_path_field_coverage(tmp_path: Path):
    """掃描路徑（scan_file）：讀取含 132b 欄位的 NFO 與 extrafanart，正確解析進 VideoInfo 與 DB Video 模型。"""
    full_nfo = """\
    <?xml version="1.0" encoding="utf-8"?>
    <movie>
      <title>[ABC-123]一般標題</title>
      <originaltitle>オリジナルタイトル</originaltitle>
      <num>ABC-123</num>
      <studio>Studio</studio>
      <year>2024</year>
      <premiered>2024-01-15</premiered>
      <release>2024-01-15</release>
      <rating>9.0</rating>
      <plot>這是劇情簡介</plot>
      <runtime>120</runtime>
      <director>導演名</director>
      <label>廠牌名</label>
      <set><name>系列名</name></set>
      <website>https://example.com/ABC-123</website>
      <actor>
        <name>女優A</name>
      </actor>
      <actor>
        <name>女優B</name>
      </actor>
      <tag>TAG1</tag>
      <tag>TAG2</tag>
      <genre>TAG1</genre>
      <genre>TAG2</genre>
    </movie>
    """
    info = _run_scan(tmp_path, nfo_body=full_nfo, create_extrafanart=True)

    # 斷言 132b 之前就有與 132b 補的欄位在 VideoInfo 上皆存在且非空
    missing_scan_before = {
        f for f in _SCAN_FIELDS_BEFORE_132B
        if not getattr(info, f, None)
    }
    missing_scan_added = {
        f for f in _SCAN_FIELDS_ADDED_BY_132B
        if not getattr(info, f, None)
    }
    assert not missing_scan_before, (
        f"掃描路徑的 VideoInfo 少了 {missing_scan_before}（132b 之前就有那組）"
    )
    assert not missing_scan_added, (
        f"掃描路徑的 VideoInfo 少了 {missing_scan_added}（132b 補的那組）"
    )

    # sample_images 檔案存在性由 scanner 讀入 info.sample_images
    assert len(info.sample_images) == 2, (
        f"掃描路徑未正確讀取 extrafanart 劇照（預期 2 張，實際 {len(info.sample_images)} 張）"
    )

    # 驗證轉入 DB Video 模型後欄位一致
    video = Video.from_video_info(info)
    assert video.number == "ABC-123"
    assert video.title == "[ABC-123]一般標題"
    assert video.director == "導演名"
    assert video.duration == 120
    assert video.label == "廠牌名"
    assert video.series == "系列名"
    assert len(video.sample_images) == 2
