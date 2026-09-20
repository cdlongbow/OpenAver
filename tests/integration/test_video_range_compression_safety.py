"""TASK-152a-T3: 影片 range 位元組正確性、排除清單、與靜態資產 206 短路。

影片端點的 media_type 只有 video/* 與 application/octet-stream，兩者都已在
排除清單內——那邊的 range 測試驗的是「排除清單生效 + range 切片正確」，
測不到 206 短路本身。靜態資產（如 text/css）不在排除清單裡，/static 的
Range 才是 206 短路唯一真正承重的路徑。

所有 range／octet-stream 相關斷言取原始 ASGI wire（自訂 send recorder），
不用 TestClient／httpx 的 response.content（遇 Content-Encoding: gzip 會自動解壓）。
"""

from __future__ import annotations

import random
from pathlib import Path
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from web.app import app

# 決定性 fixture：固定 seed；長度取數百 KB，讓開頭／中段／末尾三個 range 有間距。
_FIXTURE_SEED = b"152a-video-fixture"
_FIXTURE_SIZE = 256 * 1024
_RANGE_CHUNK = 1024

# octet-stream fixture 必須 > minimum_size(500)——gzip.py 對小於此門檻的回應直接原樣
# 轉發、不進壓縮邏輯，fixture 太小的話 mutation 拿掉排除項也不會壓，gate 假綠。
# （內容本身可不可壓縮不影響：starlette 判的是「壓縮後 bytes 是否不等於原始 bytes」
# 而非「有沒有變小」，見 starlette/middleware/gzip.py 的 GZipResponder.send_with_compression()
# ——判斷式是 `if body != message["body"]:`（標準回應與串流回應兩條分支各有一份），
# 所以不可壓縮內容照樣會被標 Content-Encoding。）
_OCTET_STREAM_EXTS = (".asf", ".divx", ".iso", ".rm", ".rmvb", ".vob")
_OCTET_FIXTURE_BODY = b"OPENAVER-152A-COMPRESSIBLE-" * 40  # 1120 bytes
assert len(_OCTET_FIXTURE_BODY) > 500


def _header_map(raw_headers: list) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in raw_headers
    }


def wire_get(path: str, headers: dict[str, str] | None = None) -> dict:
    """掛 send() recorder 在 ASGI app 外側，收集原始 wire headers／body。

    TestClient／httpx 會依 Content-Encoding 自動解壓 response.content；
    recorder 抓的是 GZipMiddleware 送出後、httpx 解壓前的訊息。
    """
    recorded: dict = {"status": None, "headers": {}, "body": b""}

    async def recording_app(scope, receive, send):
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                recorded["status"] = message["status"]
                recorded["headers"] = _header_map(list(message.get("headers", [])))
            elif message["type"] == "http.response.body":
                recorded["body"] += message.get("body", b"")
            await send(message)

        await app(scope, receive, send_wrapper)

    # 不用 `with TestClient(...)`：context manager 會跑 lifespan，觸發真實 DB 連線被
    # repo_write_guard 擋下。integration 層的 client fixture 同樣是裸 TestClient(app)。
    client = TestClient(recording_app)
    client.get(path, headers=headers or {})
    return recorded


def _mock_gallery_config(tmp_path, monkeypatch) -> None:
    def mock_load_config():
        return {
            "gallery": {
                "directories": [str(tmp_path)],
                "path_mappings": {},
            }
        }

    monkeypatch.setattr("web.routers.gallery_media.load_config", mock_load_config)


def _write_video_fixture(tmp_path) -> tuple[object, bytes]:
    fixture_bytes = random.Random(_FIXTURE_SEED).randbytes(_FIXTURE_SIZE)
    video = tmp_path / "fixture.mp4"
    video.write_bytes(fixture_bytes)
    return video, fixture_bytes


def _assert_range_uncompressed(
    *,
    video_path,
    fixture_bytes: bytes,
    start: int,
    end: int,
) -> None:
    expected = fixture_bytes[start : end + 1]
    expected_len = end - start + 1
    file_size = len(fixture_bytes)
    path_q = quote(str(video_path), safe="/:")
    recorded = wire_get(
        f"/api/gallery/video?path={path_q}",
        headers={
            "Accept-Encoding": "gzip",
            "Range": f"bytes={start}-{end}",
        },
    )

    assert recorded["status"] == 206
    headers = recorded["headers"]
    assert "content-encoding" not in headers
    assert headers.get("content-length") == str(expected_len)
    assert headers.get("content-range") == f"bytes {start}-{end}/{file_size}"
    assert headers.get("accept-ranges") == "bytes"
    assert recorded["body"] == expected


def test_range_start_not_gzip_compressed(tmp_path, monkeypatch):
    """開頭 Range bytes=0-1023：206、無 Content-Encoding、wire body 逐位元組相同。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    video, fixture_bytes = _write_video_fixture(tmp_path)
    _assert_range_uncompressed(
        video_path=video,
        fixture_bytes=fixture_bytes,
        start=0,
        end=_RANGE_CHUNK - 1,
    )


def test_range_middle_not_gzip_compressed(tmp_path, monkeypatch):
    """中段 Range：206、無 Content-Encoding、wire body 逐位元組相同。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    video, fixture_bytes = _write_video_fixture(tmp_path)
    mid = _FIXTURE_SIZE // 2
    start = mid
    end = mid + _RANGE_CHUNK - 1
    _assert_range_uncompressed(
        video_path=video,
        fixture_bytes=fixture_bytes,
        start=start,
        end=end,
    )


def test_range_end_not_gzip_compressed(tmp_path, monkeypatch):
    """末尾前一小段 Range：206、無 Content-Encoding、wire body 逐位元組相同。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    video, fixture_bytes = _write_video_fixture(tmp_path)
    start = _FIXTURE_SIZE - _RANGE_CHUNK
    end = _FIXTURE_SIZE - 1
    _assert_range_uncompressed(
        video_path=video,
        fixture_bytes=fixture_bytes,
        start=start,
        end=end,
    )


def test_full_mp4_response_not_gzip_compressed(tmp_path, monkeypatch):
    """無 Range 完整回應（video/mp4）：不被壓縮。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    video, fixture_bytes = _write_video_fixture(tmp_path)
    path_q = quote(str(video), safe="/:")
    recorded = wire_get(
        f"/api/gallery/video?path={path_q}",
        headers={"Accept-Encoding": "gzip"},
    )
    assert recorded["status"] == 200
    assert "content-encoding" not in recorded["headers"]
    assert recorded["body"] == fixture_bytes


@pytest.mark.parametrize("ext", _OCTET_STREAM_EXTS)
def test_full_octet_stream_extensions_not_gzip_compressed(tmp_path, monkeypatch, ext):
    """6 種落成 application/octet-stream 的副檔名：無 Range 完整回應不被壓縮。"""
    _mock_gallery_config(tmp_path, monkeypatch)
    video = tmp_path / f"fixture{ext}"
    video.write_bytes(_OCTET_FIXTURE_BODY)
    path_q = quote(str(video), safe="/:")
    recorded = wire_get(
        f"/api/gallery/video?path={path_q}",
        headers={"Accept-Encoding": "gzip"},
    )
    assert recorded["status"] == 200
    assert recorded["headers"].get("content-type", "").startswith("application/octet-stream")
    assert "content-encoding" not in recorded["headers"]
    assert recorded["body"] == _OCTET_FIXTURE_BODY


def test_static_css_range_not_gzip_compressed():
    """靜態 CSS 的 Range／206 不得被 gzip——這是 206 短路唯一真正承重的路徑。

    影片端點的 media_type（video/*、application/octet-stream）都已在排除清單內，
    206 短路在那裡被 content-type 排除遮蔽，本檔其他測試分辨不出它有沒有在工作。
    text/css 不在排除清單裡，所以 /static 的 Range 只剩 206 短路在擋壓縮。
    """
    css_path = (
        Path(__file__).resolve().parents[2]
        / "web"
        / "static"
        / "css"
        / "pages"
        / "showcase"
        / "01-toolbar.css"
    )
    css_bytes = css_path.read_bytes()
    start, end = 0, 999
    expected = css_bytes[start : end + 1]

    recorded = wire_get(
        "/static/css/pages/showcase/01-toolbar.css",
        headers={
            "Accept-Encoding": "gzip",
            "Range": f"bytes={start}-{end}",
        },
    )

    assert recorded["status"] == 206
    assert "content-encoding" not in recorded["headers"]
    assert recorded["headers"].get("content-length") == "1000"
    assert recorded["headers"].get("content-range") == f"bytes {start}-{end}/{len(css_bytes)}"
    assert recorded["body"] == expected


@pytest.mark.xfail(
    strict=True,
    reason=(
        "starlette 1.6.0 本身的 Accept-Encoding 子字串比對不解析 q= 權重，屬 accepted residual，"
        "見 plan-152a.md §0.4 與 PR body 已接受的 residual 欄位；這是 starlette 自己的行為不是"
        "我們的選擇，不加前置檢查"
    ),
)
def test_accept_encoding_gzip_q0_not_compressed(client):
    """Accept-Encoding: gzip;q=0 應不被當成接受 gzip（已知 residual，預期失敗）。"""
    response = client.get(
        "/static/css/theme.css",
        headers={"Accept-Encoding": "gzip;q=0"},
    )
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
