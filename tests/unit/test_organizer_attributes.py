"""TASK-121a-T2: 整理路徑接入 effective_tags + 中文字幕防重複。

對應卡片「本 task 特有邊界」1–8，每條至少一條斷言。
不重複 T1 純函式單元測試；只驗整理路徑接得對不對。
"""

from pathlib import Path

import pytest

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

def test_b02_a5_cracked_and_leaked_both_written(tmp_path):
    """ABC-123-U-leak.mp4 → 無碼破解 與 無碼流出 兩個都寫進 NFO。"""
    result, _ = _organize(tmp_path, "ABC-123-U-leak.mp4")
    nfo = _nfo_text(result)
    assert _count_tag(nfo, "無碼破解") == 1
    assert _count_genre(nfo, "無碼破解") == 1
    assert _count_tag(nfo, "無碼流出") == 1
    assert _count_genre(nfo, "無碼流出") == 1


# ── 邊界 3（A7）──────────────────────────────────────────────────────────────

def test_b03_a7_4k_tag_independent_of_suffix_keywords(tmp_path):
    """config['suffix_keywords'] 移除 -4k 後，ABC-123-4K.mp4 仍產生 4K tag。"""
    result, _ = _organize(
        tmp_path,
        "ABC-123-4K.mp4",
        suffix_keywords=["-cd1", "-cd2", "-uc"],
    )
    nfo = _nfo_text(result)
    assert _count_tag(nfo, "4K") == 1
    assert _count_genre(nfo, "4K") == 1


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


def test_b05b_cd1_with_attribute_token_still_writes_nfo(tmp_path):
    """正交：cd1 + 外部管理器＋有屬性 token → 仍寫 NFO 且含屬性 tag。"""
    result, metadata = _organize(
        tmp_path,
        "ABP-999-UC-cd1.mp4",
        _metadata(number="ABP-999"),
        external_manager="jellyfin",
    )
    nfo = _nfo_text(result)
    assert _count_tag(nfo, "無碼破解") == 1
    assert _count_tag(nfo, "中文字幕") == 1
    assert "無碼破解" in metadata["tags"]
    assert "中文字幕" in metadata["tags"]


# ── 邊界 6（A4）──────────────────────────────────────────────────────────────

def test_b06_a4_cd1_writes_nfo_without_attribute_tags(tmp_path):
    """ABC-123-cd1.mp4（第 1 段，會寫 NFO）→ 不產生任何屬性 tag。"""
    result, _ = _organize(
        tmp_path,
        "ABC-123-cd1.mp4",
        external_manager="jellyfin",
    )
    nfo = _nfo_text(result)
    for name in _CANONICAL_ATTR_TAGS:
        assert _count_tag(nfo, name) == 0, name
        assert _count_genre(nfo, name) == 0, name


# ── 邊界 7（A8）──────────────────────────────────────────────────────────────

def test_b07_a8_no_token_nfo_byte_identical_to_unmerged_generate_nfo(tmp_path):
    """無屬性 token、tags 不含中文字幕 → organize NFO 與改動前 generate_nfo 逐字節相同。"""
    original_tags = ["巨乳", "OL"]
    result, _ = _organize(
        tmp_path,
        "ABC-123.mp4",
        _metadata(tags=list(original_tags)),
    )
    actual = _nfo_text(result)

    expected_dir = tmp_path / "expected"
    expected_dir.mkdir()
    expected_path = expected_dir / Path(result["nfo_path"]).name
    assert generate_nfo(
        number="ABC-123",
        title="一般標題",
        original_title="一般標題",
        actors=[],
        tags=list(original_tags),
        date="2024-01-15",
        maker="Studio",
        url="",
        has_subtitle=False,
        has_vr=False,
        output_path=str(expected_path),
        has_poster=False,
        has_fanart=False,
        external_manager="off",
    ) is True
    expected = expected_path.read_text(encoding="utf-8")
    assert actual == expected


# ── 邊界 8───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate", ["missing_key", "none"])
def test_b08_missing_or_none_tags_does_not_crash(tmp_path, mutate):
    """metadata 沒有 'tags' key、或 metadata['tags'] 為 None 時不炸。"""
    metadata = _metadata()
    if mutate == "missing_key":
        metadata.pop("tags")
    else:
        metadata["tags"] = None
    result, _ = _organize(tmp_path, "ABC-123.mp4", metadata)
    assert result["success"] is True
    _nfo_text(result)
