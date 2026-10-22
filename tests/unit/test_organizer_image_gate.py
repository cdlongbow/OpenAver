"""CD-132b-16：下載端寫檔前解碼 → 驗魔數；壞 payload 不留檔。

亦鎖「補劇照不覆蓋既有檔」（B4／BE-TEST-10）。
測試不得發出真實網路請求。
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from core.organizer import download_image


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _raise(*_a, **_k):
        raise AssertionError("Network access attempted without mock!")

    import requests

    monkeypatch.setattr(requests, "get", _raise)
    monkeypatch.setattr(requests, "post", _raise)


def _jpeg_bytes(color=(10, 20, 30)) -> bytes:
    # ≥160×160 才能穩定超過 download_image 的 1000-byte 長度閘
    img = Image.new("RGB", (160, 160), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    assert len(data) > 1000
    assert data[:3] == b"\xff\xd8\xff"
    return data


def _xor_encode(plain: bytes, key: int = 0x5A) -> bytes:
    return bytes([key]) + bytes(b ^ key for b in plain)


def _ok_resp(content: bytes, content_type: str = "binary/octet-stream"):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    return resp


class TestBadPayloadNeverWritten:
    @patch("core.organizer.requests.get")
    def test_undecodable_payload_leaves_no_file(self, mock_get, tmp_path):
        """mutation magic-gate-blocks-write：拿掉魔數閘 → 磁碟會留下打不開的 .jpg。"""
        # 編碼後解出來不是圖片（亂數 XOR）
        bad_plain = b"<!DOCTYPE html>" + b"x" * 1200
        encoded = _xor_encode(bad_plain)
        mock_get.return_value = _ok_resp(encoded)

        save_path = tmp_path / "cover.jpg"
        result = download_image(
            "https://tp.spfcas.com/covers/bad.jpg", str(save_path)
        )

        assert result is False
        assert not save_path.exists()


class TestDecodeThenWrite:
    @patch("core.organizer.requests.get")
    def test_codec_host_writes_decoded_jpeg(self, mock_get, tmp_path):
        plain = _jpeg_bytes()
        mock_get.return_value = _ok_resp(_xor_encode(plain))

        save_path = tmp_path / "cover.jpg"
        result = download_image(
            "https://tp.spfcas.com/covers/ok.jpg", str(save_path)
        )

        assert result is True
        written = save_path.read_bytes()
        assert written == plain
        img = Image.open(io.BytesIO(written))
        img.load()


class TestExtrafanartSkipExisting:
    def test_existing_fanart_not_overwritten(self, tmp_path, monkeypatch):
        """B4／BE-TEST-10：基準 bytes 必須在被測操作之前讀。"""
        from core.enricher import _write_extrafanart

        movie = tmp_path / "SSIS-001.mp4"
        movie.write_bytes(b"fake")
        extra = tmp_path / "extrafanart"
        extra.mkdir()
        dest = extra / "fanart1.jpg"
        original = _jpeg_bytes(color=(99, 88, 77))
        dest.write_bytes(original)

        # BE-TEST-10：基準在操作前讀
        baseline = dest.read_bytes()

        def _should_not_download(*_a, **_k):
            raise AssertionError("既有劇照不得觸發 download_image")

        monkeypatch.setattr("core.enricher.download_image", _should_not_download)

        result = _write_extrafanart(
            str(movie),
            sample_images=["https://tp.spfcas.com/samples/1.jpg"],
            write_extrafanart=True,
        )

        assert result.skipped_existing == 1
        assert result.downloaded == 0
        assert dest.read_bytes() == baseline


