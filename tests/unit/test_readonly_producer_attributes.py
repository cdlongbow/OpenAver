"""TASK-121a-T4b: 唯讀來源產出接入 effective_tags。

對應卡片「本 task 特有邊界」1–6，每條至少一條斷言。
不重複 T1 純函式單元測試；只驗唯讀產出路徑接得對不對。
"""

from pathlib import Path


from core import readonly_assets, readonly_paths, readonly_producer
from core.database import VideoRepository
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
    fd = readonly_paths._format_data(md, str(source_path), cfg)
    assets = readonly_assets._write_movie_assets(
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


# ── 邊界 3（A4）──────────────────────────────────────────────────────────────


# ── 邊界 4───────────────────────────────────────────────────────────────────


# ── 邊界 5（來源端零寫入）────────────────────────────────────────────────────


# ── 邊界 6（來源檔名，不是產出夾 base name）──────────────────────────────────

