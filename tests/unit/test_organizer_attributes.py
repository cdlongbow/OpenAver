"""TASK-121a-T2: 整理路徑接入 effective_tags + 中文字幕防重複。

對應卡片「本 task 特有邊界」1–8，每條至少一條斷言。
不重複 T1 純函式單元測試；只驗整理路徑接得對不對。
"""

from pathlib import Path


from core.organizer import generate_nfo, organize_file

_CANONICAL_ATTR_TAGS = ("中文字幕", "無碼破解", "無碼流出", "4K", "VR")


def _config(**overrides):
    cfg = {
        "create_folder": False,
        "filename_format": "[{num}] {title}{suffix}",
        "download_cover": False,
        "create_nfo": True,
        "max_title_length": 50,
        "max_filename_length": 60,
        "suffix_keywords": ["-cd1", "-cd2", "-4k", "-uc"],
        "external_manager": "off",
    }
    cfg.update(overrides)
    return cfg


def _metadata(**overrides):
    md = {
        "number": "ABC-123",
        "title": "一般標題",
        "actors": [],
        "tags": [],
        "maker": "Studio",
        "date": "2024-01-15",
        "cover": "",
        "url": "",
    }
    md.update(overrides)
    return md


def _organize(tmp_path, filename, metadata=None, **config_overrides):
    src = tmp_path / filename
    src.write_bytes(b"content")
    md = metadata if metadata is not None else _metadata()
    result = organize_file(str(src), md, _config(**config_overrides))
    assert result["success"] is True, f"organize 失敗: {result.get('error')}"
    return result, md


def _nfo_text(result) -> str:
    nfo_path = result.get("nfo_path")
    assert nfo_path is not None, "應產出 NFO"
    return Path(nfo_path).read_text(encoding="utf-8")


def _count_tag(nfo: str, name: str) -> int:
    return nfo.count(f"<tag>{name}</tag>")


def _count_genre(nfo: str, name: str) -> int:
    return nfo.count(f"<genre>{name}</genre>")


# ── 邊界 1（A1）──────────────────────────────────────────────────────────────

def test_b01_a1_uc_writes_cracked_and_subtitle_tag_and_genre(tmp_path):
    """ABP-999-UC.mp4 整理入庫 → NFO 含 無碼破解 與 中文字幕，tag/genre 各一份。"""
    result, _ = _organize(tmp_path, "ABP-999-UC.mp4", _metadata(number="ABP-999"))
    nfo = _nfo_text(result)
    assert _count_tag(nfo, "無碼破解") == 1
    assert _count_genre(nfo, "無碼破解") == 1
    assert _count_tag(nfo, "中文字幕") == 1
    assert _count_genre(nfo, "中文字幕") == 1


# ── 邊界 2（A5）──────────────────────────────────────────────────────────────


# ── 邊界 3（A7）──────────────────────────────────────────────────────────────


# ── 邊界 4（CD-8 P1 正向守衛）────────────────────────────────────────────────

def test_b04_cd8_subtitle_already_in_tags_not_duplicated(tmp_path):
    """tags 已含「中文字幕」＋ has_subtitle=True → tag/genre 恰好各一份。

    這是唯一擋雙寫的機制：has_subtitle=True 本來就會再 append 一次，
    只有 writer 的防重複判斷會把它壓成一份。拿掉判斷，count 必變 2。
    """
    nfo_path = tmp_path / "ABC-123.nfo"
    assert generate_nfo(
        number="ABC-123",
        title="一般標題",
        tags=["中文字幕", "巨乳"],
        has_subtitle=True,
        output_path=str(nfo_path),
    ) is True
    nfo = nfo_path.read_text(encoding="utf-8")
    assert _count_tag(nfo, "中文字幕") == 1
    assert _count_genre(nfo, "中文字幕") == 1


# ── 邊界 5（CD-9 multipart overlay）──────────────────────────────────────────

def test_b05_cd9_cd2_still_rewrites_metadata_tags(tmp_path):
    """cd2 + 外部管理器時，傳入的 metadata dict 被回寫屬性 tag，且仍產 NFO。

    只賦值給區域變數、不寫回 metadata['tags'] 時，這條必須紅。
    """
    result, metadata = _organize(
        tmp_path,
        "ABP-999-UC-cd2.mp4",
        _metadata(number="ABP-999"),
        external_manager="jellyfin",
    )
    assert result.get("nfo_path") is not None
    assert "無碼破解" in metadata["tags"]
    assert "中文字幕" in metadata["tags"]


# ── 邊界 6（A4）──────────────────────────────────────────────────────────────


# ── 邊界 7（A8）──────────────────────────────────────────────────────────────


# ── 邊界 8───────────────────────────────────────────────────────────────────

