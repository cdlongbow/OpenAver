"""Unit tests for core.wishlist_cover_cache (feature/140 T3).

隔離策略：patch 使用端 `core.wishlist_cover_cache.get_db_path` → tmp_path，
以及 `core.wishlist_cover_cache.requests`（不是定義端 / 全域 requests）。
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from PIL import Image

import core.wishlist_cover_cache as wcc
from core.scraper import normalize_number


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """導向 tmp_path，避免 G1 守衛擋真實 DB / output 寫入。"""
    path = tmp_path / "openaver.db"
    monkeypatch.setattr(wcc, "get_db_path", lambda: path)
    return path


def _sha1_path(number: str, db_path: Path) -> Path:
    h = hashlib.sha1(normalize_number(number).encode("utf-8")).hexdigest()
    return db_path.parent / "wishlist_cover" / h[:2] / f"{h}.webp"


def _ok_response(content: bytes, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


# ── DoD-1: cover_file_for 純推導 ─────────────────────────────────
def test_cover_file_for_same_number_forms_share_path(db_path):
    a = wcc.cover_file_for("fc2ppv-1234567")
    b = wcc.cover_file_for("FC2-1234567")
    assert a == b
    assert a == _sha1_path("FC2-1234567", db_path)


def test_cover_file_for_bucket_format(db_path):
    number = "SONE-001"
    h = hashlib.sha1(normalize_number(number).encode("utf-8")).hexdigest()
    p = wcc.cover_file_for(number)
    assert p == db_path.parent / "wishlist_cover" / h[:2] / f"{h}.webp"
    assert p.parent.name == h[:2]
    assert p.stem == h
    assert p.suffix == ".webp"


def test_cover_file_for_creates_nothing_on_disk(db_path):
    p = wcc.cover_file_for("ABC-123")
    assert not p.exists()
    assert not p.parent.exists()
    assert not (db_path.parent / "wishlist_cover").exists()


def _jpeg_bytes(w: int = 120, h: int = 80) -> bytes:
    """產一張**真的** JPEG（外站給的通常就是 JPEG，不是 WebP）。

    用雜訊不用純色：純色 JPEG 壓完只有 ~790 bytes，會低於
    `_fetch_image_bytes()` 的 1000 bytes 門檻而被當成「下載失敗」。
    """
    img = Image.new("RGB", (w, h))
    img.putdata([((x * 7) % 256, (y * 13) % 256, (x * y) % 256)
                 for y in range(h) for x in range(w)])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    data = buf.getvalue()
    assert len(data) > 1000, "fixture 必須大於 _fetch_image_bytes 的 1000 bytes 門檻"
    return data


# ── DoD-2: 下載成功落地，且**內容真的是 WebP** ──────────────────
def test_download_and_save_writes_real_webp(db_path, monkeypatch):
    """副檔名是 .webp、`/api/wishlist/cover` 也回 image/webp ⇒ 內容必須真的是 WebP。

    這支測試取代原本的「逐位元等於下載到的 bytes」——那個斷言把一個**錯的契約**
    鎖死了（Codex review P2）：外站給 JPEG，原樣寫進 .webp 檔就是副檔名與 mime
    兩邊一起說謊。Chrome 靠 magic bytes 嗅探所以照樣顯示，但那是它寬容不是我們對。
    """
    src = _jpeg_bytes()
    monkeypatch.setattr(wcc.requests, "get", lambda *a, **k: _ok_response(src))

    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is True

    dest = wcc.cover_file_for("SONE-001")
    assert dest.exists()
    assert list(dest.parent.glob("*.tmp")) == []

    # 正向鎖：讀回來必須是 WEBP，而且**不等於**下載到的原始 bytes
    with Image.open(dest) as img:
        assert img.format == "WEBP", f"落地檔應為 WebP，實際是 {img.format}"
        assert img.size == (120, 80), "不縮放：封面要原尺寸（書籤卡與燈箱都用它）"
    assert dest.read_bytes() != src, "若逐位元相同代表根本沒轉檔"


def test_download_and_save_undecodable_primary_falls_back_to_transcodable(db_path, monkeypatch):
    """主圖拿得到但**解不開**時，要繼續試 fallback（Codex review 第 2 輪第 2 點）。

    CDN 回一頁 HTML、或格式 Pillow 不認得時，備援那張往往是好的。
    只有「下載失敗」才換備援是不夠的。
    """
    good = _jpeg_bytes(90, 60)
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        if "cover" in url:
            return _ok_response(b"<html>404 not found</html>" + b"x" * 1500)  # 下載成功但解不開
        return _ok_response(good)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001",
            "https://cdn.example/cover.jpg",
            fallback_url="https://cdn.example/fallback.jpg",
        )
        is True
    )
    assert calls == [
        "https://cdn.example/cover.jpg",
        "https://cdn.example/fallback.jpg",
    ], "主圖轉檔失敗後必須真的去打 fallback"

    dest = wcc.cover_file_for("SONE-001")
    with Image.open(dest) as img:
        assert img.format == "WEBP"
        assert img.size == (90, 60), "落地的應該是 fallback 那張"


def test_download_and_save_returns_false_when_nothing_decodable(db_path, monkeypatch):
    """兩個 URL 都解不開 → 回 False 且**不留檔**（Codex review 第 2 輪第 1 點）。

    刻意**不**寫回原始 bytes：對解不開的資料而言，寫下去的產物本來就是破圖，
    只是多騙一個 `cover_available: true`。書籤那一列照樣留著（I2），
    前端走既有的破圖 fallback。
    """
    junk = b"\x00NOT-AN-IMAGE" + b"x" * 1500
    monkeypatch.setattr(wcc.requests, "get", lambda *a, **k: _ok_response(junk))

    assert (
        wcc.download_and_save(
            "SONE-002",
            "https://cdn.example/cover.bin",
            fallback_url="https://cdn.example/fallback.bin",
        )
        is False
    )

    dest = wcc.cover_file_for("SONE-002")
    assert not dest.exists(), "解不開就不該留下任何檔案"
    assert not dest.parent.exists(), "也不該留下空的 bucket 目錄"


# ── DoD-3 / M2: RequestException → False，不拋、不留檔 ───────────
def test_download_and_save_returns_false_on_request_exception(db_path, monkeypatch):
    def _boom(*_a, **_k):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(wcc.requests, "get", _boom)
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()
    if dest.parent.exists():
        assert list(dest.parent.iterdir()) == []


# ── DoD-3 / M1: 過小回應 → False ─────────────────────────────────
def test_download_and_save_rejects_undersized_response(db_path, monkeypatch):
    tiny = b"tiny-error-page"  # << 1000
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(tiny)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()
    if dest.parent.exists():
        assert list(dest.parent.iterdir()) == []


def test_download_and_save_returns_false_on_non_200(db_path, monkeypatch):
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(b"x" * 1500, status_code=500)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is False
    dest = wcc.cover_file_for("SONE-001")
    assert not dest.exists()


# ── DoD-4: fallback 生效 ─────────────────────────────────────────
def test_download_and_save_uses_fallback_when_cover_fails(db_path, monkeypatch):
    fallback_bytes = _jpeg_bytes(90, 60)
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        if "cover" in url:
            return _ok_response(b"tiny")  # undersized → fail
        return _ok_response(fallback_bytes)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001",
            "https://cdn.example/cover.jpg",
            fallback_url="https://cdn.example/fallback.jpg",
        )
        is True
    )
    dest = wcc.cover_file_for("SONE-001")
    with Image.open(dest) as img:
        assert img.format == "WEBP"
        assert img.size == (90, 60), "落地的應該是 fallback 那張"
    assert calls == [
        "https://cdn.example/cover.jpg",
        "https://cdn.example/fallback.jpg",
    ]


def test_download_and_save_empty_cover_url_tries_fallback(db_path, monkeypatch):
    fallback_bytes = _jpeg_bytes(70, 50)
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        return _ok_response(fallback_bytes)

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001",
            "",
            fallback_url="https://cdn.example/fallback.jpg",
        )
        is True
    )
    assert calls == ["https://cdn.example/fallback.jpg"]
    with Image.open(wcc.cover_file_for("SONE-001")) as img:
        assert img.format == "WEBP"
        assert img.size == (70, 50)


def test_download_and_save_both_urls_empty_returns_false(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: calls.append(1) or _ok_response(b"x" * 1500)
    )
    assert wcc.download_and_save("SONE-001", "", fallback_url="") is False
    assert calls == []
    assert not wcc.cover_file_for("SONE-001").exists()


# ── DoD-5: remove ────────────────────────────────────────────────
def test_remove_deletes_existing_file(db_path, monkeypatch):
    payload = _jpeg_bytes()
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(payload)
    )
    assert wcc.download_and_save("SONE-001", "https://cdn.example/cover.jpg") is True
    dest = wcc.cover_file_for("SONE-001")
    assert dest.exists()
    assert wcc.remove("SONE-001") is None
    assert not dest.exists()


def test_remove_missing_is_noop(db_path):
    assert wcc.remove("NEVER-EXISTED") is None


# ── 鏡像對稱：download / remove 對不同格式番號走同一路徑 ─────────
def test_download_and_remove_share_path_across_number_forms(db_path, monkeypatch):
    payload = _jpeg_bytes()
    monkeypatch.setattr(
        wcc.requests, "get", lambda *a, **k: _ok_response(payload)
    )
    assert wcc.download_and_save("fc2ppv-1234567", "https://cdn.example/c.jpg") is True
    written = wcc.cover_file_for("fc2ppv-1234567")
    assert written.exists()
    # remove 用另一種寫法的同一番號
    wcc.remove("FC2-1234567")
    assert not written.exists()
    assert wcc.cover_file_for("FC2-1234567") == written


# ── timeout 必須傳入 requests.get ────────────────────────────────
def test_fetch_passes_timeout(db_path, monkeypatch):
    seen = {}

    def fake_get(url, *a, **k):
        seen.update(k)
        return _ok_response(_jpeg_bytes())

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert wcc.download_and_save("SONE-001", "https://cdn.example/c.jpg") is True
    assert "timeout" in seen
    assert seen["timeout"] == 30


# ── headers 必須帶 organizer 那組（UA + javbus Referer）──────────
def test_fetch_passes_organizer_headers(db_path, monkeypatch):
    seen = {}

    def fake_get(url, *a, **k):
        seen.update(k)
        return _ok_response(_jpeg_bytes())

    monkeypatch.setattr(wcc.requests, "get", fake_get)
    assert (
        wcc.download_and_save(
            "SONE-001", "https://www.javbus.com/pics/cover/ci5u_b.jpg"
        )
        is True
    )
    assert "headers" in seen
    assert "User-Agent" in seen["headers"]
    assert seen["headers"].get("Referer") == "https://www.javbus.com/"


def test_download_and_save_does_not_refetch_identical_fallback(tmp_path, monkeypatch):
    """Codex PR#175 P2：primary 與 fallback 是同一個網址時只准打一次。

    `add_wishlist()` 傳的是 `(preview_cover_url or cover, cover)`，而 `preview_cover_url`
    只有 metatube 會填 ⇒ 沒接 metatube 的人兩個參數恆為同一字串。不去重的話圖床連不上時
    會各等一次 30 秒 timeout，使用者按下加入書籤要轉 60 秒而不是 30 秒。
    """
    monkeypatch.setattr(wcc, "get_db_path", lambda: tmp_path / "db.sqlite")
    calls = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        raise requests.RequestException("host unreachable")

    monkeypatch.setattr(wcc.requests, "get", _fake_get)

    same = "https://cdn.example/only.jpg"
    assert wcc.download_and_save("DEDUP-001", same, same) is False
    assert calls == [same], f"同一個網址只准打一次，實際打了 {len(calls)} 次：{calls}"


def test_download_and_save_still_tries_distinct_fallback(tmp_path, monkeypatch):
    """反向鎖：兩個網址不同時 fallback 仍必須被嘗試（去重不得誤殺備援）。"""
    monkeypatch.setattr(wcc, "get_db_path", lambda: tmp_path / "db.sqlite")
    calls = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        raise requests.RequestException("host unreachable")

    monkeypatch.setattr(wcc.requests, "get", _fake_get)

    primary, fallback = "https://cdn.example/a.jpg", "https://cdn.example/b.jpg"
    assert wcc.download_and_save("DEDUP-002", primary, fallback) is False
    assert calls == [primary, fallback], "兩個不同網址都必須各打一次"
