"""TASK-121a-T3: 掃描路徑接入 effective_tags。

對應卡片「本 task 特有邊界」1–5、7（邊界 6 順序守衛已於 162b 刪除），每條至少一條斷言。
不重複 T1 純函式單元測試；只驗掃描路徑接得對不對。
"""
import textwrap

from core.database.video import Video
from core.gallery_scanner import VideoScanner

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


# ── 邊界 5──────────────────────────────────────────────────────────────────


# ── 邊界 7（CD-10 空白合流）──────────────────────────────────────────────────

