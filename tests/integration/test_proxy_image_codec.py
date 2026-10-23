"""Integration：/api/proxy-image 解碼 ＋ Content-Type ＋ 既有圖床逐位元不變。

測試不得發出真實網路請求（一律 mock requests.get）。
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
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


@pytest.fixture(autouse=True)
def _public_dns(public_resolver):
    """167 公網規則會解析 host；預設回公網（不放寬外連防線，只假 DNS）。"""
    return public_resolver()


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


