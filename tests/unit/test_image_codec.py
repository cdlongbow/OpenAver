"""Unit tests for core/image_codec.py (TASK-132b-T4).

解碼／魔數／registry 查詢的純函式邊緣。測試不得發出真實網路請求。
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from PIL import Image

# 真實形狀的編碼樣本：用真 JPEG 反向產生（D8）。
# KEY 首位元組；去掉後每位元組 XOR KEY ⇒ 解出原 JPEG。
_KEY = 0x5A


def _real_jpeg_bytes() -> bytes:
    img = Image.new("RGB", (16, 16), color=(200, 40, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


JPEG = _real_jpeg_bytes()
ENCODED = bytes([_KEY]) + bytes(b ^ _KEY for b in JPEG)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _raise(*_a, **_k):
        raise AssertionError("Network access attempted in pure unit test!")

    import requests

    monkeypatch.setattr(requests, "get", _raise)
    monkeypatch.setattr(requests, "post", _raise)


class TestJavdbXor:
    def test_decodes_real_sample_to_jpeg(self):
        """解出來的東西必須是 PIL 打得開的 JPEG（D8／mutation xor-strips-key-byte）。"""
        from core.image_codec import decode_image_payload

        with patch(
            "core.image_codec.codec_for_host",
            return_value="javdb-xor",
        ):
            decoded = decode_image_payload("any.example", ENCODED)

        assert decoded[:3] == b"\xff\xd8\xff"
        # 不能只驗 magic 3 bytes——整段必須是合法 JPEG
        img = Image.open(io.BytesIO(decoded))
        img.load()
        assert img.size == (16, 16)
        assert decoded == JPEG

    def test_empty_body_returns_empty(self):
        from core.image_codec import decode_image_payload

        with patch("core.image_codec.codec_for_host", return_value="javdb-xor"):
            assert decode_image_payload("any.example", b"") == b""

    def test_single_byte_body_returns_empty(self):
        from core.image_codec import decode_image_payload

        with patch("core.image_codec.codec_for_host", return_value="javdb-xor"):
            assert decode_image_payload("any.example", bytes([_KEY])) == b""

    def test_no_codec_returns_same_object(self):
        from core.image_codec import decode_image_payload

        raw = b"\xff\xd8\xff" + b"x" * 64
        with patch("core.image_codec.codec_for_host", return_value=None):
            out = decode_image_payload("pics.dmm.co.jp", raw)
        assert out is raw

    def test_unknown_codec_name_raises(self):
        from core.image_codec import decode_image_payload

        with patch("core.image_codec.codec_for_host", return_value="no-such-codec"):
            with pytest.raises(ValueError, match="no-such-codec"):
                decode_image_payload("any.example", ENCODED)


class TestMagicTable:
    def test_looks_like_image_is_media_type_not_none(self):
        """魔數表只有一份：looks_like_image ≡ image_media_type is not None（D6）。"""
        from core.image_codec import image_media_type, looks_like_image

        assert looks_like_image(JPEG) is True
        assert image_media_type(JPEG) == "image/jpeg"
        assert looks_like_image(b"not-an-image") is False
        assert image_media_type(b"not-an-image") is None
        assert looks_like_image(b"") is False

    def test_png_magic(self):
        from core.image_codec import image_media_type, looks_like_image

        png = Image.new("RGB", (4, 4), color=(0, 128, 0))
        buf = io.BytesIO()
        png.save(buf, format="PNG")
        data = buf.getvalue()
        assert looks_like_image(data) is True
        assert image_media_type(data) == "image/png"


class TestCodecForHost:
    def test_registered_codec_host(self):
        from core.image_host_policy import codec_for_host

        assert codec_for_host("tp.spfcas.com") == "javdb-xor"

    def test_plain_host_returns_none(self):
        from core.image_host_policy import codec_for_host

        assert codec_for_host("pics.dmm.co.jp") is None
        assert codec_for_host("c0.jdbstatic.com") is None

    def test_unknown_host_returns_none(self):
        from core.image_host_policy import codec_for_host

        assert codec_for_host("evil.example.com") is None
        assert codec_for_host("") is None
