import pytest
from core.database import init_db, VideoRepository, Video
from core.path_utils import to_file_uri


@pytest.fixture
def showcase_setup(tmp_path):
    """建立含足量測試資料的臨時 DB，確保 /api/showcase/videos 回應體大於 500 bytes minimum_size 門檻。"""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    vid1_uri = to_file_uri(str(video_dir / "video1.mp4"), {})
    vid2_uri = to_file_uri(str(video_dir / "video2.mp4"), {})

    db_path = tmp_path / "showcase_test.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=vid1_uri,
            number="SONE-001",
            title="Test Video With Tags and Long Description for Compression Testing",
            actresses=["Test Actress A", "Test Actress B"],
            maker="Test Maker Studio",
            release_date="2024-01-01",
            tags=["高畫質", "單體作品", "劇情片", "4K", "精選"],
            user_tags=["★5", "足", "最愛"],
            size_bytes=1073741824,
            mtime=1700000000.0,
        ),
        Video(
            path=vid2_uri,
            number="SONE-002",
            title="Test Video Second Item For Minimum Size Threshold Guarantee",
            actresses=["Test Actress C"],
            maker="Another Studio",
            release_date="2024-02-01",
            tags=["字幕", "VR"],
            user_tags=["待看"],
            size_bytes=2147483648,
            mtime=1700005000.0,
        ),
    ])
    repo.set_user_rating(vid1_uri, 5)

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
        "vid1_uri": vid1_uri,
        "vid2_uri": vid2_uri,
        "config": config,
    }


def test_showcase_videos_compression_and_identity_parity(client, showcase_setup, mocker):
    """測試 /api/showcase/videos 在帶 Accept-Encoding: gzip 時的壓縮行為與解壓正確性。

    假綠陷阱防護：
    1. 驗證 wire 層確實有 Content-Encoding: gzip 與 Vary: Accept-Encoding（TestClient 自動解壓，直接讀 content 會在 middleware 沒掛時也綠）。
    2. 驗證未帶 Accept-Encoding 時無 Content-Encoding。
    3. 驗證解壓後內容與未壓縮請求逐位元組相同（內容沒壞）。
    """
    mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
    mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

    # 未壓縮基準請求（明確傳入 Accept-Encoding: identity 避免 httpx 預設帶 gzip）
    resp_identity = client.get("/api/showcase/videos", headers={"Accept-Encoding": "identity"})
    assert resp_identity.status_code == 200
    assert "content-encoding" not in resp_identity.headers, "未請求壓縮時不應帶 Content-Encoding"
    assert len(resp_identity.content) > 500, (
        f"自我把關：測試資料長度 {len(resp_identity.content)} 必須 > 500 bytes 門檻，否則 GZipMiddleware 預設略過"
    )

    # 帶 gzip 請求
    resp_gzip = client.get("/api/showcase/videos", headers={"Accept-Encoding": "gzip"})
    assert resp_gzip.status_code == 200

    # 承重斷言 1：wire 確實被壓縮
    assert resp_gzip.headers.get("content-encoding") == "gzip", "帶 Accept-Encoding: gzip 時回應必須有 Content-Encoding: gzip"
    vary_header = resp_gzip.headers.get("vary", "").lower()
    assert "accept-encoding" in vary_header, "壓縮回應必須包含 Vary: Accept-Encoding"

    # 承重斷言 2：解壓後內容相同（內容沒壞）
    assert resp_gzip.content == resp_identity.content, "gzip 解壓後內容應與 identity 請求內容完全一致"


def test_showcase_videos_etag_304_coexists_with_compression(client, showcase_setup, mocker):
    """測試在 GZipMiddleware 啟用下，/api/showcase/videos 的 ETag / 304 快取協商行為仍然正常。

    第一次 200 的 Content-Encoding 斷言是本測試的承重點。
    """
    mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
    mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

    # 第一次請求取得 ETag
    first_resp = client.get("/api/showcase/videos", headers={"Accept-Encoding": "gzip"})
    assert first_resp.status_code == 200
    assert first_resp.headers.get("content-encoding") == "gzip", (
        "第一次 200 回應必須包含 Content-Encoding: gzip，確保對 GZipMiddleware 掛載敏感；"
        "少了此斷言，拿掉 GZipMiddleware 本測試仍會綠，測試名就在說謊"
    )
    etag = first_resp.headers.get("etag")
    assert etag, "回應必須包含 ETag header"

    # 第二次帶 If-None-Match 與 Accept-Encoding: gzip 進行條件請求
    second_resp = client.get(
        "/api/showcase/videos",
        headers={"Accept-Encoding": "gzip", "If-None-Match": etag},
    )
    assert second_resp.status_code == 304, "命中 If-None-Match 應回傳 304 Not Modified"
    assert second_resp.content == b"", "304 回應 body 必須為空"


def test_static_css_compression_and_no_cache(client):
    """測試 /static/css/theme.css 帶 Accept-Encoding: gzip 時同時具有 gzip 與 no-cache。

    繼承陷阱 BE-API-02：靜態資產必須同時斷言 Content-Encoding: gzip 與 Cache-Control: no-cache。
    """
    resp_gzip = client.get("/static/css/theme.css", headers={"Accept-Encoding": "gzip"})
    assert resp_gzip.status_code == 200
    assert resp_gzip.headers.get("content-encoding") == "gzip", "靜態 CSS 必須有 Content-Encoding: gzip"
    assert resp_gzip.headers.get("cache-control") == "no-cache", "靜態資產必須維持 Cache-Control: no-cache (BE-API-02)"
    assert "etag" in resp_gzip.headers, "靜態資產必須帶 ETag"

    # 內容完整性驗證
    resp_identity = client.get("/static/css/theme.css", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in resp_identity.headers
    assert resp_gzip.content == resp_identity.content, "解壓後 CSS 內容應與原始內容一致"
