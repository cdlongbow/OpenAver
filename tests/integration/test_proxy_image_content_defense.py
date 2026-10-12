"""Integration：/api/proxy-image 內容防線（167-T3）。

所有 host 同一條：看解碼後的檔頭魔數，不信上游 Content-Type；不跟轉址。
魔數樣本一律內嵌位元組；測試不得發出真實網路請求（一律 mock requests.get）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

MARKER = b"MARKER"
LISTED = "https://pics.dmm.co.jp/mono/movie/adult/x/x.jpg"
UNKNOWN = "https://cdn.example.com/c.jpg"
CODEC = "https://tp.spfcas.com/covers/c.jpg"

BAD_BODIES = {
    "html": (b"<html>MARKER</html>", "text/html"),
    "json": (b'{"error": "MARKER"}', "application/json"),
    "svg": (b'<svg xmlns="http://www.w3.org/2000/svg"><text>MARKER</text></svg>', "image/svg+xml"),
}

# 近似魔數：長得像圖、其實不是
NEAR_MISS = {
    "mp4_ftyp": b"\x00\x00\x00\x18ftypmp42MARKER",
    "heic_ftyp": b"\x00\x00\x00\x18ftypheicMARKER",
    "mif1_compat_heic_only": b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heicMARKER",
    "riff_wave": b"RIFF\x00\x00\x00\x00WAVEMARKER",
    "empty": b"",
    "text_bm": b"B MARKER",
}

GOOD = {
    "jpeg": (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg", "application/octet-stream"),
    "png": (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png", "image/jpeg"),
    "gif87a": (b"GIF87a\x01\x00\x01\x00", "image/gif", "image/jpeg"),
    "gif89a": (b"GIF89a\x01\x00\x01\x00", "image/gif", "text/html"),
    "webp": (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp", "application/octet-stream"),
    "avif": (b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00", "image/avif", "image/jpeg"),
    "avis": (b"\x00\x00\x00\x1cftypavis\x00\x00\x00\x00", "image/avif", "image/jpeg"),
    "avif_major_mif1": (b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1avif\x00\x00", "image/avif", "image/jpeg"),
    "bmp": (b"BM\x36\x00\x00\x00\x00\x00", "image/bmp", "text/html"),
}


def _xor_encode(plain: bytes, key: int = 0x5A) -> bytes:
    return bytes([key]) + bytes(b ^ key for b in plain)


def _resp(content: bytes, content_type: str, status: int = 200, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = {"Content-Type": content_type, **(headers or {})}
    return resp


def _upstream(url: str, body: bytes) -> bytes:
    """codec host 的上游 body 是 xor 編碼；其餘原樣。"""
    return _xor_encode(body) if "spfcas" in url else body


@pytest.fixture(autouse=True)
def _public_dns(public_resolver):
    return public_resolver()


def _get(client, url, resp):
    with patch("web.routers.search.requests.get", return_value=resp) as mock_get:
        response = client.get("/api/proxy-image", params={"url": url})
    return response, mock_get


# 壞內容＋誠實標頭；近似魔數（影片／音訊片段、空 body）併入同一組斷言
_NON_IMAGE_CASES = {**BAD_BODIES, **{k: (v, "image/jpeg") for k, v in NEAR_MISS.items()}}


@pytest.mark.parametrize("url", [LISTED, UNKNOWN, CODEC], ids=["listed", "unknown", "codec"])
@pytest.mark.parametrize("kind", sorted(_NON_IMAGE_CASES))
def test_non_image_never_forwarded(client, url, kind):
    """來源回登入頁／JSON／SVG／影片片段 → 瀏覽器不會收到那些內容。"""
    body, ctype = _NON_IMAGE_CASES[kind]
    response, _ = _get(client, url, _resp(_upstream(url, body), ctype))
    assert response.status_code in (403, 404)
    assert MARKER not in response.content


@pytest.mark.parametrize("url", [LISTED, UNKNOWN, CODEC], ids=["listed", "unknown", "codec"])
@pytest.mark.parametrize("kind", sorted(BAD_BODIES))
def test_lying_image_header_rejected(client, url, kind):
    """站方標頭謊稱 image/jpeg 也擋得住。"""
    body, _ = BAD_BODIES[kind]
    response, _ = _get(client, url, _resp(_upstream(url, body), "image/jpeg"))
    assert response.status_code in (403, 404)
    assert MARKER not in response.content


def test_listed_host_html_rejected_403(client):
    """內建圖床回 200 錯誤頁，不再原樣轉給瀏覽器。"""
    response, _ = _get(client, LISTED, _resp(b"<html>MARKER</html>", "text/html"))
    assert response.status_code == 403
    assert response.content == b""


@pytest.mark.parametrize("url", [LISTED, UNKNOWN, CODEC], ids=["listed", "unknown", "codec"])
@pytest.mark.parametrize("kind", sorted(GOOD))
def test_image_formats_forwarded_with_sniffed_type(client, url, kind):
    """真圖照常顯示；Content-Type 取魔數值，上游標頭亂標也不影響。"""
    body, media, upstream_ctype = GOOD[kind]
    response, _ = _get(client, url, _resp(_upstream(url, body), upstream_ctype))
    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"].split(";")[0] == media
    assert response.headers["cache-control"] == "public, max-age=86400"


@pytest.mark.parametrize("url", [LISTED, UNKNOWN], ids=["listed", "unknown"])
def test_requests_get_never_follows_redirects(client, url):
    """上游 302 指到內網 → 代理不跟過去。"""
    resp = _resp(b"<html>MARKER</html>", "text/html", status=302,
                 headers={"Location": "http://127.0.0.1/evil"})
    response, mock_get = _get(client, url, resp)
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["allow_redirects"] is False
    assert response.status_code != 200
    assert MARKER not in response.content
