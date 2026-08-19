"""TASK-121a-T4b: 唯讀來源產出接入 effective_tags。

對應卡片「本 task 特有邊界」1–6，每條至少一條斷言。
不重複 T1 純函式單元測試；只驗唯讀產出路徑接得對不對。
"""

from pathlib import Path

import pytest

from core import readonly_producer
from core.database import VideoRepository
from core.organizer import generate_nfo
from core.path_utils import to_file_uri

_CANONICAL_ATTR_TAGS = ("中文字幕", "無碼破解", "無碼流出", "4K", "VR")


def _config(**overrides):
    cfg = {
        "filename_format": "{num} {title}",
        "max_filename_length": 60,
        "max_title_length": 50,
        "suffix_keywords": [],
        "external_manager": "off",
        "download_sample_images": False,
    }
    cfg.update(overrides)
    return cfg


def _meta(**overrides):
    md = {
        "number": "ABC-123",
        "title": "一般標題",
        "actors": [],
        "tags": [],
        "maker": "Studio",
        "date": "2024-01-15",
        "cover": "",
        "url": "",
        "sample_images": [],
    }
    md.update(overrides)
    return md


def _source_snapshot(source_dir: Path):
    entries = []
    for path in sorted(source_dir.rglob("*")):
        st = path.stat()
        entries.append((str(path.relative_to(source_dir)), path.is_dir(), st.st_mtime, st.st_size))
    return entries


def _write_assets(tmp_path, source_filename, meta=None, movie_leaf="movie"):
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    source_path = source_dir / source_filename
    if not source_path.exists():
        source_path.write_bytes(b"video")
    movie_dir = tmp_path / "output" / movie_leaf
    md = meta if meta is not None else _meta()
    cfg = _config()
    fd = readonly_producer._format_data(md, str(source_path), cfg)
    assets = readonly_producer._write_movie_assets(
        str(movie_dir),
        md,
        fd,
        str(source_path),
        cfg,
        cover_strategy=("none",),
    )
    return md, assets, movie_dir, source_path, source_dir


def _nfo_path(movie_dir: Path) -> Path:
    nfos = list(movie_dir.glob("*.nfo"))
    assert len(nfos) == 1, f"預期恰好一份 NFO，實際 {len(nfos)}: {nfos}"
    return nfos[0]


def _nfo_text(movie_dir: Path) -> str:
    return _nfo_path(movie_dir).read_text(encoding="utf-8")


def _count_tag(nfo: str, name: str) -> int:
    return nfo.count(f"<tag>{name}</tag>")


def _count_genre(nfo: str, name: str) -> int:
    return nfo.count(f"<genre>{name}</genre>")


def _upsert_row(repo, source_path: Path, movie_dir: Path, meta: dict, assets: dict):
    readonly_producer._upsert_db(
        repo,
        to_file_uri(str(source_path)),
        {"size": source_path.stat().st_size, "mtime": source_path.stat().st_mtime},
        meta,
        assets,
        None,
        to_file_uri(str(movie_dir)),
    )
    return repo.get_by_path(to_file_uri(str(source_path)))


# ── 邊界 1（A9）──────────────────────────────────────────────────────────────

def test_b01_a9_uc_writes_tags_to_nfo(tmp_path):
    """ABP-999-UC.mp4 → 產出夾 NFO 有 <tag>/<genre> 無碼破解 與 中文字幕。"""
    meta = _meta(number="ABP-999")
    _, _, movie_dir, _, _ = _write_assets(tmp_path, "ABP-999-UC.mp4", meta)
    nfo = _nfo_text(movie_dir)
    assert _count_tag(nfo, "無碼破解") == 1
    assert _count_genre(nfo, "無碼破解") == 1
    assert _count_tag(nfo, "中文字幕") == 1
    assert _count_genre(nfo, "中文字幕") == 1


def test_b01_a9_uc_writes_tags_to_db(tmp_path, temp_db):
    """ABP-999-UC.mp4 → _upsert_db 後 DB row 的 tags 含 無碼破解 與 中文字幕。"""
    meta = _meta(number="ABP-999")
    meta, assets, movie_dir, source_path, _ = _write_assets(
        tmp_path, "ABP-999-UC.mp4", meta
    )
    row = _upsert_row(VideoRepository(temp_db), source_path, movie_dir, meta, assets)
    assert "無碼破解" in row.tags
    assert "中文字幕" in row.tags


# ── 邊界 2（A8）──────────────────────────────────────────────────────────────

def test_b02_a8_no_token_nfo_byte_identical_to_unmerged_generate_nfo(tmp_path):
    """來源檔名無任何 token → 產出 NFO 與改動前 generate_nfo 逐字節相同。"""
    original_tags = ["巨乳", "OL"]
    meta = _meta(tags=list(original_tags))
    _, _, movie_dir, _, _ = _write_assets(tmp_path, "ABC-123.mp4", meta)
    actual_path = _nfo_path(movie_dir)
    actual = actual_path.read_text(encoding="utf-8")

    expected_dir = tmp_path / "expected"
    expected_dir.mkdir()
    expected_path = expected_dir / actual_path.name
    assert generate_nfo(
        number="ABC-123",
        title="一般標題",
        original_title="",
        actors=[],
        tags=list(original_tags),
        date="2024-01-15",
        maker="Studio",
        url="",
        output_path=str(expected_path),
        has_poster=False,
        has_fanart=False,
        director="",
        duration=None,
        series="",
        label="",
        summary="",
        rating=None,
        external_manager="off",
    ) is True
    assert actual == expected_path.read_text(encoding="utf-8")


# ── 邊界 3（A4）──────────────────────────────────────────────────────────────

def test_b03_a4_cd1_writes_nfo_without_attribute_tags(tmp_path):
    """ABC-123-cd1.mp4 → 不產生任何屬性 tag。"""
    _, _, movie_dir, _, _ = _write_assets(tmp_path, "ABC-123-cd1.mp4")
    nfo = _nfo_text(movie_dir)
    for name in _CANONICAL_ATTR_TAGS:
        assert _count_tag(nfo, name) == 0, name
        assert _count_genre(nfo, name) == 0, name


# ── 邊界 4───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate", ["missing_key", "none"])
def test_b04_missing_or_none_tags_does_not_crash(tmp_path, mutate):
    """meta 沒有 'tags' key、或 meta['tags'] 為 None 時不炸。"""
    metadata = _meta()
    if mutate == "missing_key":
        metadata.pop("tags")
    else:
        metadata["tags"] = None
    _, _, movie_dir, _, _ = _write_assets(tmp_path, "ABC-123.mp4", metadata)
    _nfo_text(movie_dir)


# ── 邊界 5（來源端零寫入）────────────────────────────────────────────────────

def test_b05_source_dir_listing_and_mtime_unchanged(tmp_path):
    """跑完後來源目錄的檔案清單與 mtime 不變。"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    video = source_dir / "ABP-999-UC.mp4"
    video.write_bytes(b"video")
    sidecar = source_dir / "readme.txt"
    sidecar.write_text("do not touch", encoding="utf-8")
    before = _source_snapshot(source_dir)

    _write_assets(tmp_path, "ABP-999-UC.mp4", _meta(number="ABP-999"))

    assert _source_snapshot(source_dir) == before


# ── 邊界 6（來源檔名，不是產出夾 base name）──────────────────────────────────

def test_b06_uses_source_filename_not_output_basename(tmp_path):
    """產出夾檔名與來源檔名不同時，用的是來源檔名判定。

    來源 ABP-999-UC.mp4；產出夾 leaf 故意叫 FAKE-4K；filename_format 不含
    {suffix}，產出 NFO 的 base name 也不帶 -UC。若誤用產出夾／產出檔名，
    會寫入 4K 或什麼都不寫，而不是 無碼破解＋中文字幕。
    """
    meta = _meta(number="ABP-999")
    _, _, movie_dir, _, _ = _write_assets(
        tmp_path, "ABP-999-UC.mp4", meta, movie_leaf="FAKE-4K"
    )
    nfo = _nfo_text(movie_dir)
    nfo_name = _nfo_path(movie_dir).name
    assert "UC" not in nfo_name
    assert "4K" not in nfo_name
    assert _count_tag(nfo, "無碼破解") == 1
    assert _count_tag(nfo, "中文字幕") == 1
    assert _count_tag(nfo, "4K") == 0
    assert _count_genre(nfo, "4K") == 0
