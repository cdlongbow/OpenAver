"""TASK-152a-T4 接線層：縮圖／封面／字型／BMP 排除矩陣 ＋ 真實 SSE 端點 header 斷言。

邊界條件：
1. 帶 Accept-Encoding: gzip 請求 /api/gallery/thumb（webp）、/api/gallery/image（jpg/png/webp/gif/tbn）、
   縮圖 fallback 原圖（web/routers/gallery_media.py 的 get_thumb() fallback 原圖分支）、/api/wishlist/cover（webp）、
   /api/actresses/actress-crop（jpeg）→ 回應不出現 Content-Encoding。
2. 帶 Accept-Encoding: gzip 請求 /api/gallery/image 且副檔名為 .bmp → 同樣不出現 Content-Encoding。
3. 帶 Accept-Encoding: gzip 請求靜態 .woff2 字型 → 不出現 Content-Encoding。
4. GET /api/search/stream?q=a → status_code == 200、content-type 前綴 text/event-stream、無 Content-Encoding。
"""




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


def test_search_stream_wiring_not_gzip_compressed(client):
    """帶 Accept-Encoding: gzip 請求 GET /api/search/stream?q=a 接線層斷言：不被壓縮且瞬間結束。"""
    resp = client.get("/api/search/stream?q=a", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    assert "content-encoding" not in resp.headers
