"""TASK-152a-T4 接線層：縮圖／封面／字型／BMP 排除矩陣 ＋ 真實 SSE 端點 header 斷言。

邊界條件：
1. 帶 Accept-Encoding: gzip 請求 /api/gallery/thumb（webp）、/api/gallery/image（jpg/png/webp/gif/tbn）、
   縮圖 fallback 原圖（web/routers/gallery_media.py 的 get_thumb() fallback 原圖分支）、/api/wishlist/cover（webp）、
   /api/actresses/actress-crop（jpeg）→ 回應不出現 Content-Encoding。
2. 帶 Accept-Encoding: gzip 請求 /api/gallery/image 且副檔名為 .bmp → 同樣不出現 Content-Encoding。
3. 帶 Accept-Encoding: gzip 請求靜態 .woff2 字型 → 不出現 Content-Encoding。
4. GET /api/search/stream?q=a → status_code == 200、content-type 前綴 text/event-stream、無 Content-Encoding。
"""

from urllib.parse import quote

import pytest

from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri

# GZipMiddleware 的 minimum_size 預設 500：小於此門檻的回應會被直接原樣轉發、
# 完全不進壓縮邏輯。fixture 若落在門檻以下，排除清單就算整個失效測試也會綠
# ——這是假綠，不是通過。所有 fixture 一律過 _assert_fixture_large_enough()。
_GZIP_MINIMUM_SIZE = 500


def _assert_fixture_large_enough(payload: bytes) -> bytes:
    assert len(payload) > _GZIP_MINIMUM_SIZE, (
        f'fixture 只有 {len(payload)} bytes，未超過 GZipMiddleware 的 '
        f'minimum_size={_GZIP_MINIMUM_SIZE}；這支測試不管排除清單有沒有失效都會綠'
    )
    return payload


def _mock_gallery_config(tmp_path, monkeypatch) -> None:
    def mock_load_config():
        return {
            "gallery": {
                "directories": [str(tmp_path)],
                "path_mappings": {},
            }
        }

    monkeypatch.setattr("web.routers.gallery_media.load_config", mock_load_config)


def test_gallery_image_bmp_not_gzip_compressed(client, tmp_path, monkeypatch):
    """帶 Accept-Encoding: gzip 請求 /api/gallery/image 且為 .bmp：不被壓縮。

    BMP 在 web/routers/gallery_media.py 的 get_image() 裡那張 mime_types 副檔名白名單內。
    fixture 大小必須 > 500 bytes，使 mutation 拿掉排除項時能被 GZipMiddleware 壓縮轉紅。
    """
    _mock_gallery_config(tmp_path, monkeypatch)
    bmp_file = tmp_path / "test.bmp"
    bmp_file.write_bytes(_assert_fixture_large_enough(b"BM" + b"A" * 1024))

    path_q = quote(str(bmp_file), safe="/:")
    resp = client.get(f"/api/gallery/image?path={path_q}", headers={"Accept-Encoding": "gzip"})

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/bmp")
    assert "content-encoding" not in resp.headers


@pytest.mark.parametrize(
    "ext,expected_mime",
    [
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".tbn", "image/jpeg"),
    ],
)
def test_gallery_image_formats_not_gzip_compressed(
    client, tmp_path, monkeypatch, ext, expected_mime
):
    """帶 Accept-Encoding: gzip 請求 /api/gallery/image 的其餘圖片格式：不被壓縮。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    img_file = tmp_path / f"test{ext}"
    img_file.write_bytes(_assert_fixture_large_enough(b"TEST-IMAGE-CONTENT-" * 40))

    path_q = quote(str(img_file), safe="/:")
    resp = client.get(f"/api/gallery/image?path={path_q}", headers={"Accept-Encoding": "gzip"})

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith(expected_mime)
    assert "content-encoding" not in resp.headers


def test_gallery_thumb_hit_not_gzip_compressed(client, tmp_path, monkeypatch):
    """帶 Accept-Encoding: gzip 請求 /api/gallery/thumb hit（webp）：不被壓縮。"""
    thumb_file = tmp_path / "thumb.webp"
    thumb_file.write_bytes(_assert_fixture_large_enough(b"RIFF" + b"WEBP-THUMB-" * 60))

    monkeypatch.setattr(
        "web.routers.gallery_media.thumbnail_cache.thumb_file_for",
        lambda p: thumb_file,
    )

    resp = client.get(
        "/api/gallery/thumb?path=file:///movies/test.mp4",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/webp")
    assert "content-encoding" not in resp.headers


def test_gallery_thumb_fallback_not_gzip_compressed(client, tmp_path, monkeypatch):
    """帶 Accept-Encoding: gzip 請求 /api/gallery/thumb fallback 原圖（jpeg）：不被壓縮。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    repo = VideoRepository(db_path)

    cover = tmp_path / "fallback_cover.jpg"
    cover.write_bytes(_assert_fixture_large_enough(b"JPEG-FALLBACK-COVER-" * 40))

    video_uri = to_file_uri(str(tmp_path / "video.mp4"))
    cover_uri = to_file_uri(str(cover))
    repo.upsert_batch([Video(path=video_uri, mtime=100.0, cover_path=cover_uri)])

    monkeypatch.setattr("web.routers.gallery_media.get_db_path", lambda: db_path)
    monkeypatch.setattr(
        "web.routers.gallery_media.load_config",
        lambda: {
            "thumbnail_cache_enabled": False,
            "gallery": {"directories": [str(tmp_path)], "path_mappings": {}},
        },
    )
    monkeypatch.setattr(
        "web.routers.gallery_media.thumbnail_cache.thumb_file_for",
        lambda p: tmp_path / "missing_thumb.webp",
    )

    path_q = quote(video_uri, safe="/:")
    resp = client.get(f"/api/gallery/thumb?path={path_q}", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/jpeg")
    assert "content-encoding" not in resp.headers


def test_wishlist_cover_not_gzip_compressed(client, tmp_path, monkeypatch):
    """帶 Accept-Encoding: gzip 請求 /api/wishlist/cover（webp）：不被壓縮。"""
    cover_file = tmp_path / "wishlist_cover.webp"
    cover_file.write_bytes(_assert_fixture_large_enough(b"RIFF" + b"WEBP-WISHLIST-" * 40))

    monkeypatch.setattr(
        "web.routers.wishlist.wishlist_cover_cache.cover_file_for",
        lambda number: cover_file,
    )

    resp = client.get(
        "/api/wishlist/cover?number=ABC-123",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/webp")
    assert "content-encoding" not in resp.headers


def test_actress_crop_not_gzip_compressed(client, monkeypatch):
    """帶 Accept-Encoding: gzip 請求 /api/actresses/actress-crop（jpeg）：不被壓縮。"""
    monkeypatch.setattr("web.routers.actress._check_cover_path", lambda p: True)
    monkeypatch.setattr(
        "web.routers.actress.crop_video_cover",
        lambda p, s: _assert_fixture_large_enough(b"JPEG-CROP-BYTES-" * 40),
    )

    resp = client.get(
        "/api/actresses/actress-crop?path=%2Fdummy%2Fcover.jpg",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/jpeg")
    assert "content-encoding" not in resp.headers


def test_static_woff2_font_not_gzip_compressed(client):
    """帶 Accept-Encoding: gzip 請求靜態 .woff2 字型：不被壓縮。"""
    resp = client.get(
        "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("font/woff2")
    assert "content-encoding" not in resp.headers


def test_search_stream_wiring_not_gzip_compressed(client):
    """帶 Accept-Encoding: gzip 請求 GET /api/search/stream?q=a 接線層斷言：不被壓縮且瞬間結束。"""
    resp = client.get("/api/search/stream?q=a", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    assert "content-encoding" not in resp.headers
