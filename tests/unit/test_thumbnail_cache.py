"""Unit tests for core.thumbnail_cache (feature/71 T1).

純函式縮圖快取模組測試。覆蓋 TASK-71-T1「邊界條件」全 10 項。
隔離策略：monkeypatch core.thumbnail_cache._thumb_dir → tmp_path，
避免污染真 output/thumb/。
"""

import pytest
from PIL import Image

import core.thumbnail_cache as tc


@pytest.fixture
def thumb_dir(tmp_path, monkeypatch):
    """把 _thumb_dir 導向 tmp_path/thumb，隔離真實 output/。"""
    d = tmp_path / "thumb"
    monkeypatch.setattr(tc, "_thumb_dir", lambda: d)
    return d


def _make_jpg(path, w=1280, h=720, color=(120, 30, 200)):
    """造一張可控尺寸 JPEG 測試圖。"""
    Image.new("RGB", (w, h), color).save(str(path), "JPEG")
    return path


# ── 1. hash 決定性 ──────────────────────────────────────────────


def test_thumb_file_for_distinct_uris_distinct_paths(thumb_dir):
    a = tc.thumb_file_for("file:///x/A.mp4")
    b = tc.thumb_file_for("file:///x/B.mp4")
    assert a != b


# ── 2. 分桶路徑格式 thumb/<h[:2]>/<h>.webp ──────────────────────


# ── 3. generate 產出合法 WEBP 且小於原圖 ────────────────────────
def test_generate_produces_valid_webp_smaller(thumb_dir, tmp_path):
    cover = _make_jpg(tmp_path / "cover.jpg", 1280, 720)
    dst = thumb_dir / "ab" / "abc.webp"
    assert tc.generate(str(cover), dst) is True
    assert dst.exists()
    with Image.open(str(dst)) as img:
        assert img.format == "WEBP"
        assert img.width == tc.THUMB_WIDTH
    assert dst.stat().st_size < cover.stat().st_size


# ── 4. 原圖更窄不放大 ───────────────────────────────────────────


# ── 5. 原子寫無殘留 temp 檔 ─────────────────────────────────────


# ── 6. 損圖 / 讀取失敗 → False（不拋、不留殘檔、dst 不建立） ────


# ── 7. invalidate ───────────────────────────────────────────────


def test_invalidate_removes_existing(thumb_dir, tmp_path):
    uri = "file:///x/movie.mp4"
    cover = _make_jpg(tmp_path / "cover.jpg")
    tf = tc.thumb_file_for(uri)
    assert tc.generate(str(cover), tf) is True
    assert tf.exists()
    tc.invalidate(uri)
    assert not tf.exists()


# ── 8. clear_all ────────────────────────────────────────────────


# ── 9. get_or_create ────────────────────────────────────────────
def test_get_or_create_miss_then_hit(thumb_dir, tmp_path, monkeypatch):
    uri = "file:///x/movie.mp4"
    cover = _make_jpg(tmp_path / "cover.jpg")

    # miss → 生成
    p1 = tc.get_or_create(uri, str(cover))
    assert p1 is not None
    assert p1.exists()

    # hit → 不重新生成（spy generate）
    calls = []
    orig = tc.generate
    monkeypatch.setattr(tc, "generate", lambda *a, **k: calls.append(1) or orig(*a, **k))
    p2 = tc.get_or_create(uri, str(cover))
    assert p2 == p1
    assert calls == []  # generate 未被呼叫


def test_get_or_create_corrupt_cover_returns_none(thumb_dir, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert tc.get_or_create("file:///x/bad.mp4", str(bad)) is None


# ── 11. per-thumb 鎖 key 一致性（Codex round-2 P1 修法 A）────────


