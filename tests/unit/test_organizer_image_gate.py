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

    @patch("core.organizer.requests.get")
    def test_plain_host_bytes_unchanged(self, mock_get, tmp_path):
        """既有明文圖床寫進磁碟的 bytes 與改動前相同（D-10）。"""
        plain = _jpeg_bytes(color=(1, 2, 3))
        mock_get.return_value = _ok_resp(plain, content_type="image/jpeg")

        save_path = tmp_path / "cover.jpg"
        result = download_image(
            "https://pics.dmm.co.jp/mono/movie/adult/x/x.jpg", str(save_path)
        )

        assert result is True
        assert save_path.read_bytes() == plain


class TestPlainHostScopeLock:
    """🔴 鎖住「魔數閘只作用在標了 codec 的 host」這個**範圍決定**。

    plan §T4 明寫範圍限定 javdb 的圖片 host，其他 15 個列 backlog。
    理由是爆炸半徑：魔數表只認 JPEG/PNG/GIF/WebP，全站閘一開，
    哪天某個既有圖床改用 AVIF 之類的新格式就是「那個來源整排破圖」——
    那會是本 branch 引進的**新**回歸，而它要修的「明文 CDN 回 200 錯誤頁」
    是本來就存在的曝險。

    ⚠️ 上面 `test_plain_host_bytes_unchanged` 餵的是真 JPEG，**閘全站開著也會綠**，
    鎖不住這個決定。這一支餵的是**非圖片**內容——閘一旦擴到全站，它就會紅。
    """

    @patch("core.organizer.requests.get")
    def test_plain_host_non_image_still_written(self, mock_get, tmp_path):
        not_an_image = b"<!DOCTYPE html><html>200 but an error page</html>" + b"x" * 1200
        mock_get.return_value = _ok_resp(not_an_image, content_type="text/html")

        save_path = tmp_path / "cover.jpg"
        result = download_image(
            "https://pics.dmm.co.jp/mono/movie/adult/x/x.jpg", str(save_path)
        )

        # 132b 之前的行為：200 ＋ >1000 bytes 就寫檔。逐位元不變。
        assert result is True
        assert save_path.read_bytes() == not_an_image


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


class TestMalformedPortStillDecodes:
    """畸形 port 不得讓「解碼 → 驗魔數」整組被跳過（pre-merge branch review P3）。

    背景：`_host_key()` 對非數字／超範圍 port 回 `None`（那是它自己的正確行為，
    見它的 docstring——早期版本讓例外穿出 `organize_file()`，而那時影片檔已經搬走了）。
    解碼用的 host 若沿用它，`https://tp.spfcas.com:99999/x.jpg` 會拿到空 host
    ⇒ `codec_for_host("")` 回 None ⇒ **原始位元組直接寫檔**。

    使用者流程：整理一部片 → 資料夾裡多一個打不開的 `cover.jpg` → Jellyfin 破圖，
    而且不會自己好，要手動刪檔重刮。CD-132b-16 承諾「不存在『寫了一個打不開的檔』
    這個狀態」，這條就是那個狀態。

    proxy 端（`web/routers/search.py`）用的是 `urlparse().hostname`，`.port` 根本
    不會被碰 ⇒ 它一直是對的。這支鎖的是兩個消費端的**對稱**。
    """

    def test_malformed_port_url_is_still_decoded_and_gated(self, tmp_path, monkeypatch):
        import core.organizer as organizer

        raw = b"\x5a" + bytes(b ^ 0x5a for b in (b"\xff\xd8\xff" + b"J" * 2000))
        resp = MagicMock(status_code=200, content=raw)
        monkeypatch.setattr(organizer.requests, "get", MagicMock(return_value=resp))

        dest = tmp_path / "cover.jpg"
        ok = organizer._attempt_download_image(
            "https://tp.spfcas.com:99999/rhe/covers/x.jpg", str(dest)
        )

        assert ok is True
        assert dest.read_bytes()[:3] == b"\xff\xd8\xff", (
            "畸形 port 讓解碼被跳過了——寫進去的是未解碼的原始位元組"
        )

    def test_malformed_port_url_with_garbage_leaves_no_file(self, tmp_path, monkeypatch):
        """反向鎖：同樣的畸形 port，內容不是圖片時**必須**擋下、不留檔。

        沒有這一支，上一支可以靠「解碼後不驗魔數」通過。
        """
        import core.organizer as organizer

        resp = MagicMock(status_code=200, content=b"\x00" + b"not an image" * 200)
        monkeypatch.setattr(organizer.requests, "get", MagicMock(return_value=resp))

        dest = tmp_path / "cover.jpg"
        ok = organizer._attempt_download_image(
            "https://tp.spfcas.com:99999/rhe/covers/x.jpg", str(dest)
        )

        assert ok is False
        assert not dest.exists()
