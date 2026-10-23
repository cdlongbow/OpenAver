# tests/integration/test_static_mime.py
"""
契約測試：/static mount 的 .js/.mjs/.css/.svg MIME 兩層強制（issue #66、#119）。

精簡版 Windows registry 把 HKEY_CLASSES_ROOT\\.js Content Type 污染成 text/plain，
會讓 ES module 被瀏覽器 strict-MIME 拒收。NoCacheStaticFiles 在 super().file_response()
回傳後 post-construction 覆寫 Content-Type → 對 OS registry / guess_type 污染免疫。

.svg 為 issue #119 補入：同一族污染打在 HKCR\\.svg 上時，Chromium 對 <img> 載入的 SVG
走 strict MIME，非 image/svg+xml 一律不 decode → sidebar logo 破圖。raster 圖（png/webp）
與字型會被瀏覽器 sniff、不吃 strict MIME，故**刻意不納入**白名單（見 test_png_not_overridden
這支負向控制：把 .png 加進清單會讓它失去意義）。

依 CLAUDE.md「Lint 守衛規則」：此為「副檔名 → Content-Type 強制 API contract」→ pytest 正確。
"""
from fastapi.testclient import TestClient
from web.app import app


def test_js_forced_even_when_guess_type_polluted(monkeypatch):
    # Starlette 以 `from mimetypes import guess_type` 把函式 bind 進 starlette.responses
    # 自己的 namespace；要污染對 Starlette 生效須 patch starlette.responses.guess_type
    # （patch mimetypes.guess_type 會是 silent no-op，喪失對抗性）。
    monkeypatch.setattr(
        "starlette.responses.guess_type",
        lambda *a, **k: ("text/plain", None),
    )
    # Starlette 在 FileResponse 建構時（每 request）讀 guess_type，故 patch 後再建
    # 一個 TestClient GET 即可讓污染生效；主修仍會把 header 覆寫回正確值。
    polluted_client = TestClient(app)
    resp = polluted_client.get("/static/js/pages/scanner/main.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")


