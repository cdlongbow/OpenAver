"""TASK-121a-T3: 掃描路徑接入 effective_tags。

對應卡片「本 task 特有邊界」1–7，每條至少一條斷言。
不重複 T1 純函式單元測試；只驗掃描路徑接得對不對。
"""
import inspect
import textwrap
from unittest.mock import patch

from core.database.video import Video
from core.gallery_scanner import VideoInfo, VideoScanner

_ATTR_TAGS = ("中文字幕", "無碼破解", "無碼流出", "4K", "VR")


def _touch_video(tmp_path, filename: str):
    video = tmp_path / filename
    video.write_bytes(b"\x00" * 100)
    return video


def _write_nfo(video_path, body: str) -> None:
    video_path.with_suffix(".nfo").write_text(
        textwrap.dedent(body), encoding="utf-8"
    )


def _scan(tmp_path, filename: str, nfo_body: str | None = None):
    video = _touch_video(tmp_path, filename)
    if nfo_body is not None:
        _write_nfo(video, nfo_body)
    return VideoScanner().scan_file(str(video))


def _genre_parts(info) -> list[str]:
    if not info.genre:
        return []
    return [g.strip() for g in info.genre.split(",") if g.strip()]


# ── 邊界 1（A2）──────────────────────────────────────────────────────────────

def test_b01_a2_uc_filename_writes_cracked_and_subtitle(tmp_path):
    """ABP-999-UC.mp4 掃描後，info.genre 與 DB 側 tags 都含 無碼破解 與 中文字幕。"""
    info = _scan(tmp_path, "ABP-999-UC.mp4")
    assert "無碼破解" in info.genre
    assert "中文字幕" in info.genre
    video = Video.from_video_info(info)
    assert "無碼破解" in video.tags
    assert "中文字幕" in video.tags


# ── 邊界 2（dedup）──────────────────────────────────────────────────────────

def test_b02_dedup_nfo_subtitle_plus_c_filename(tmp_path):
    """NFO 已含 中文字幕、檔名又是 -C → info.genre 裡「中文字幕」只出現一次。"""
    info = _scan(
        tmp_path,
        "ABC-123-C.mp4",
        """\
        <?xml version="1.0" encoding="utf-8"?>
        <movie>
          <title>測試</title>
          <num>ABC-123</num>
          <genre>中文字幕</genre>
        </movie>
        """,
    )
    assert _genre_parts(info).count("中文字幕") == 1


# ── 邊界 3（A4）──────────────────────────────────────────────────────────────

def test_b03_a4_cd1_adds_no_attribute_tags(tmp_path):
    """ABC-123-cd1.mp4 → info.genre 與改動前相同（不新增任何屬性 tag）。"""
    info = _scan(
        tmp_path,
        "ABC-123-cd1.mp4",
        """\
        <?xml version="1.0" encoding="utf-8"?>
        <movie>
          <title>測試</title>
          <num>ABC-123</num>
          <genre>巨乳</genre>
        </movie>
        """,
    )
    assert info.genre == "巨乳"
    for name in _ATTR_TAGS:
        assert name not in _genre_parts(info), name


# ── 邊界 4（A8）──────────────────────────────────────────────────────────────

def test_b04_a8_empty_genre_no_token_stays_empty(tmp_path):
    """info.genre 原本為空、檔名無 token → 結果仍為空字串（不得變成 ',' 或 'None'）。"""
    info = _scan(tmp_path, "ABC-123.mp4")
    assert info.genre == ""
    assert info.genre != ","
    assert info.genre != "None"


# ── 邊界 5──────────────────────────────────────────────────────────────────

def test_b05_genre_none_does_not_raise(tmp_path):
    """info.genre 為 None 時不炸，結果是字串。"""
    video = _touch_video(tmp_path, "ABC-123.mp4")
    scanner = VideoScanner()
    fake = VideoInfo(title="測試", num="ABC-123", genre=None)
    with patch.object(scanner, "parse_filename", return_value=fake):
        info = scanner.scan_file(str(video))
    assert info.genre is not None
    assert isinstance(info.genre, str)


# ── 邊界 6（順序）────────────────────────────────────────────────────────────

def test_b06_effective_tags_called_after_normalize_maker():
    """effective_tags() 的呼叫發生在 normalize_maker() 之後。"""
    src = inspect.getsource(VideoScanner.scan_file)
    assert src.index("normalize_maker") < src.index("effective_tags")


# ── 邊界 7（CD-10 空白合流）──────────────────────────────────────────────────

def test_b07_cd10_whitespace_4k_confluence_no_dup(tmp_path):
    """既有 genre 值含前後空白（' 4K '）→ CD-10 合流命中 4K，且不產生重複項。"""
    video = _touch_video(tmp_path, "ABC-123.mp4")
    video.with_suffix(".nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?><movie><title>x</title></movie>',
        encoding="utf-8",
    )
    scanner = VideoScanner()
    fake = VideoInfo(title="測試", num="ABC-123", genre=" 4K ")
    with patch.object(scanner, "parse_nfo", return_value=fake):
        info = scanner.scan_file(str(video))
    parts = _genre_parts(info)
    assert parts.count("4K") == 1
    four_k_likes = [g for g in info.genre.split(",") if g.strip().lower() == "4k"]
    assert len(four_k_likes) == 1
    assert info.genre == "4K"
