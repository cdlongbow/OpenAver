"""TASK-152a-T5 閘：冷載可壓縮端點的 wire 層雙態比較（JSON + HTML/JS/CSS）。

繞過 TestClient／httpx 自動解壓，用 ASGI send recorder 讀原始 wire bytes。
不用任何絕對值或百分比門檻——只比「同一次量測裡 gzip 比 identity 小」與
「gzip.decompress 後逐位元組相同」。
"""

from __future__ import annotations

import gzip

import pytest
from starlette.testclient import TestClient

from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri
from web.app import app

# GZipMiddleware 的 minimum_size 預設 500：小於此門檻的回應會被直接原樣轉發、
# 完全不進壓縮邏輯。fixture 若落在門檻以下，拿掉 middleware 測試也會綠——假綠。
_GZIP_MINIMUM_SIZE = 500

_STATIC_COMPRESSIBLE_PATHS = (
    "/showcase",
    "/static/js/pages/showcase/main.js",
    "/static/css/pages/showcase/01-toolbar.css",
)


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


def _assert_fixture_large_enough(payload: bytes) -> bytes:
    assert len(payload) > _GZIP_MINIMUM_SIZE, (
        f"fixture 只有 {len(payload)} bytes，未超過 GZipMiddleware 的 "
        f"minimum_size={_GZIP_MINIMUM_SIZE}；請增加筆數或欄位長度，"
        f"否則這支測試不管壓縮有沒有失效都會綠"
    )
    return payload


def _assert_endpoint_gzip_smaller_and_reversible(path: str) -> tuple[int, int]:
    """同端點雙態：gzip 帶 Content-Encoding、identity 不帶；可逆；確實變小。"""
    identity = wire_get(path, headers={"Accept-Encoding": "identity"})
    assert identity["status"] == 200, f"{path} identity 應回 200，實際 {identity['status']}"
    assert "content-encoding" not in identity["headers"], (
        f"{path} 未請求壓縮時不應帶 Content-Encoding"
    )

    gzipped = wire_get(path, headers={"Accept-Encoding": "gzip"})
    assert gzipped["status"] == 200, f"{path} gzip 應回 200，實際 {gzipped['status']}"
    assert gzipped["headers"].get("content-encoding") == "gzip", (
        f"{path} 帶 Accept-Encoding: gzip 時回應必須有 Content-Encoding: gzip"
    )

    identity_body = identity["body"]
    gzip_body = gzipped["body"]
    assert gzip.decompress(gzip_body) == identity_body, (
        f"{path} gzip.decompress 後應與 identity wire body 逐位元組相同"
    )
    assert len(gzip_body) < len(identity_body), (
        f"{path} gzip wire body ({len(gzip_body)}) 應小於 identity "
        f"({len(identity_body)})"
    )
    return len(identity_body), len(gzip_body)


@pytest.fixture
def showcase_setup(tmp_path):
    """建立 ≥5 部片的臨時 DB，title／number 用相似前綴製造可壓縮重複結構。

    放大自 test_response_compression.py 的 showcase_setup；目標是 identity
    wire body 清楚超過 minimum_size=500（建議 > 2000）。
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    db_path = tmp_path / "showcase_cold_load.db"
    init_db(db_path)
    repo = VideoRepository(db_path)

    title_prefix = (
        "Cold Load Compression Fixture Title With Repeated Prefix Structure "
        "For Gzip Dictionary Sharing Across Multiple Video Entries "
    )
    shared_tags = [
        "高畫質", "單體作品", "劇情片", "4K", "精選",
        "字幕", "長片", "推薦片單", "測試標籤重複", "壓縮驗證",
    ]
    shared_actresses = [
        "Test Actress Alpha Repeated",
        "Test Actress Beta Repeated",
        "Test Actress Gamma Repeated",
    ]

    videos = []
    uris = []
    for i in range(1, 6):
        uri = to_file_uri(str(video_dir / f"video{i}.mp4"), {})
        uris.append(uri)
        videos.append(
            Video(
                path=uri,
                number=f"SONE-00{i}",
                title=f"{title_prefix} Item Number SONE-00{i} Extra Padding Text",
                actresses=shared_actresses,
                maker="Test Maker Studio Repeated Name For Compression",
                release_date=f"2024-0{i}-01",
                tags=shared_tags,
                user_tags=["★5", "足", "最愛", "待看", "冷載驗證"],
                size_bytes=1_073_741_824 + i,
                mtime=1_700_000_000.0 + i,
            )
        )
    repo.upsert_batch(videos)
    repo.set_user_rating(uris[0], 5)

    config = {
        "gallery": {
            "directories": [str(video_dir)],
            "path_mappings": {},
            "min_size_mb": 0,
            "thumbnail_width": 400,
        },
        "scraper": {"video_extensions": [".mp4"], "image_extensions": [".jpg"]},
        "database": {"path": ":memory:"},
        "translate": {"provider": "ollama", "ollama_model": "llama3"},
    }

    return {
        "db_path": db_path,
        "uris": uris,
        "config": config,
    }


def _patch_showcase(mocker, showcase_setup) -> None:
    mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
    mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])


def test_showcase_videos_identity_wire_body_exceeds_minimum_size(
    showcase_setup, mocker
):
    """前提斷言：/api/showcase/videos identity wire body 必須 > minimum_size。"""
    _patch_showcase(mocker, showcase_setup)
    identity = wire_get(
        "/api/showcase/videos",
        headers={"Accept-Encoding": "identity"},
    )
    assert identity["status"] == 200
    _assert_fixture_large_enough(identity["body"])
    # RED_EVIDENCE：實跑時印出實際長度，確認清楚超過 500（建議 > 2000）
    print(f"RED_EVIDENCE len(identity_wire_body)={len(identity['body'])}")


def test_showcase_videos_gzip_smaller_and_reversible(showcase_setup, mocker):
    """JSON 端點：同端點雙態、Content-Encoding、可逆、確實變小。"""
    _patch_showcase(mocker, showcase_setup)
    identity = wire_get(
        "/api/showcase/videos",
        headers={"Accept-Encoding": "identity"},
    )
    _assert_fixture_large_enough(identity["body"])
    identity_len, gzip_len = _assert_endpoint_gzip_smaller_and_reversible(
        "/api/showcase/videos"
    )
    print(
        f"COMPRESSION /api/showcase/videos identity={identity_len} gzip={gzip_len}"
    )


@pytest.mark.parametrize("path", _STATIC_COMPRESSIBLE_PATHS)
def test_static_or_html_gzip_smaller_and_reversible(path):
    """HTML／JS／CSS：同端點雙態、Content-Encoding、可逆、確實變小。"""
    # /showcase 是動態 TemplateResponse；JS／CSS 是 /static 掛載檔。
    # 三者原始大小皆遠超過 minimum_size，不需額外放大。
    identity = wire_get(path, headers={"Accept-Encoding": "identity"})
    assert identity["status"] == 200, (
        f"{path} identity 應回 200，實際 {identity['status']}；"
        "若 /showcase 因依賴注入失敗，改抽驗其他可壓縮 HTML／JSON 端點"
    )
    _assert_fixture_large_enough(identity["body"])
    identity_len, gzip_len = _assert_endpoint_gzip_smaller_and_reversible(path)
    print(f"COMPRESSION {path} identity={identity_len} gzip={gzip_len}")
