"""Integration：/api/proxy-image 解碼 ＋ Content-Type ＋ 既有圖床逐位元不變。

測試不得發出真實網路請求（一律 mock requests.get）。
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image


def _jpeg_bytes(color=(50, 100, 150)) -> bytes:
    img = Image.new("RGB", (32, 32), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _xor_encode(plain: bytes, key: int = 0x5A) -> bytes:
    return bytes([key]) + bytes(b ^ key for b in plain)


def _mock_resp(content: bytes, content_type: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    return resp


class TestProxyImageCodecHost:
    def test_decodes_and_sets_image_content_type(self, client):
        """上游 binary/octet-stream → 解碼後必須改成 image/jpeg（D3／D-9）。"""
        plain = _jpeg_bytes()
        encoded = _xor_encode(plain)
        url = "https://tp.spfcas.com/rhe951l4q/covers/p9/P9QrXa.jpg"

        with patch(
            "web.routers.search.requests.get",
            return_value=_mock_resp(encoded, "binary/octet-stream"),
        ):
            response = client.get("/api/proxy-image", params={"url": url})

        assert response.status_code == 200
        assert response.content == plain
        assert response.headers["content-type"].startswith("image/jpeg")
        img = Image.open(io.BytesIO(response.content))
        img.load()

    def test_bad_payload_returns_404_empty(self, client):
        """壞 payload 走代理回 404 空圖，不回垃圾 bytes（D-12）。"""
        bad = _xor_encode(b"<html>" + b"z" * 200)
        url = "https://tp.spfcas.com/covers/bad.jpg"

        with patch(
            "web.routers.search.requests.get",
            return_value=_mock_resp(bad, "binary/octet-stream"),
        ):
            response = client.get("/api/proxy-image", params={"url": url})

        assert response.status_code == 404
        assert response.content == b""


class TestProxyImagePlainHostUnchanged:
    def test_existing_host_bytes_identical(self, client):
        """既有圖床零改變：回應 body 逐位元組比對（D-10）。"""
        plain = _jpeg_bytes(color=(1, 2, 3))
        url = "https://pics.dmm.co.jp/mono/movie/adult/sone103/sone103jp-1.jpg"

        with patch(
            "web.routers.search.requests.get",
            return_value=_mock_resp(plain, "image/jpeg"),
        ):
            response = client.get("/api/proxy-image", params={"url": url})

        assert response.status_code == 200
        assert response.content == plain
        assert response.content is not None
        # Content-Type 沿用上游（非 codec host）
        assert "image/jpeg" in response.headers["content-type"]

    def test_plain_host_non_image_passes_through(self, client):
        """🔴 範圍鎖：魔數閘只作用在標了 codec 的 host。

        上面那支餵真 JPEG，閘擴到全站也會綠——鎖不住範圍決定。
        這一支餵非圖片內容：132b 之前會原樣回 200，之後也必須一樣。
        閘一旦擴到全站，這裡會變成 404。
        """
        not_an_image = b"<html>upstream 200 error page</html>"
        url = "https://pics.dmm.co.jp/mono/movie/adult/x/x.jpg"

        with patch(
            "web.routers.search.requests.get",
            return_value=_mock_resp(not_an_image, "text/html"),
        ):
            response = client.get("/api/proxy-image", params={"url": url})

        assert response.status_code == 200
        assert response.content == not_an_image
