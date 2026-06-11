"""test_api_thumb.py - 縮圖快取 API 整合測試（feature/71 T3）

涵蓋 TASK-71-T3 邊界 1-9：
- GET /api/gallery/thumb：hit serve webp + no-cache + 強 ETag；If-None-Match → 304；
  hit 零 DB/零 NAS；miss 生成；無 cover 404；generate 失敗 fallback 原圖。
- POST /api/gallery/thumb/prewarm：disabled gate / started / already_running 重入。

隔離關鍵：thumbnail_cache._thumb_dir 與 scanner.get_db_path 是兩個獨立 reference，
兩者都要 patch（見 TASK card 測試隔離坑）。
"""
import pytest
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from core.path_utils import to_file_uri
from core import thumbnail_cache


# ---------- helpers ----------

def _make_small_jpg(path: Path, size=(800, 600)):
    """產生一張真 JPG 小圖（用於 cover 來源）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 60, 200)).save(path, "JPEG")
    return path


def _make_webp(path: Path, size=(400, 300)):
    """直接放一張真 webp 到 thumb 位置（用於 hit 測試）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 200, 100)).save(path, "WEBP")
    return path


@pytest.fixture
def thumb_dir(tmp_path, mocker):
    """把 thumbnail_cache._thumb_dir 導向 temp，避免污染真 output/thumb。"""
    d = tmp_path / "thumb"
    d.mkdir()
    mocker.patch("core.thumbnail_cache._thumb_dir", return_value=d)
    return d


@pytest.fixture
def temp_db(tmp_path, mocker):
    """建真 temp DB + 把 scanner.get_db_path 導向它，回 (db_path, repo)。"""
    from core.database import init_db, VideoRepository
    db_path = tmp_path / "test.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    mocker.patch("web.routers.scanner.get_db_path", return_value=db_path)
    return db_path, repo


# ============ GET /api/gallery/thumb ============

class TestGetThumbHit:
    def test_hit_serves_webp_with_no_cache_and_etag(self, client, thumb_dir):
        """邊界1：hit → 200 image/webp + Cache-Control: no-cache + 強 ETag。"""
        uri = to_file_uri("/movies/v1.mp4")
        _make_webp(thumbnail_cache.thumb_file_for(uri))

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert resp.headers["cache-control"] == "no-cache"
        etag = resp.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')
        assert etag.strip('"').isdigit()

    def test_hit_zero_db_zero_nas(self, client, thumb_dir, mocker):
        """邊界2：hit 路徑零 DB、零 NAS（generate / VideoRepository 未被呼叫）。"""
        uri = to_file_uri("/movies/v1.mp4")
        _make_webp(thumbnail_cache.thumb_file_for(uri))

        gen_spy = mocker.patch("web.routers.scanner.thumbnail_cache.generate")
        repo_spy = mocker.patch("web.routers.scanner.VideoRepository")
        db_spy = mocker.patch("web.routers.scanner.get_db_path")

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200
        gen_spy.assert_not_called()
        repo_spy.assert_not_called()
        db_spy.assert_not_called()

    def test_if_none_match_returns_304(self, client, thumb_dir):
        """邊界3：If-None-Match 命中 → 304 空 body。"""
        uri = to_file_uri("/movies/v1.mp4")
        _make_webp(thumbnail_cache.thumb_file_for(uri))

        first = client.get("/api/gallery/thumb", params={"path": uri})
        etag = first.headers["etag"]

        resp = client.get(
            "/api/gallery/thumb",
            params={"path": uri},
            headers={"If-None-Match": etag},
        )
        assert resp.status_code == 304
        assert resp.content == b""


class TestGetThumbMiss:
    def test_miss_generates_webp(self, client, thumb_dir, temp_db, tmp_path):
        """邊界4：miss + DB 有 video + cover 真小圖 → 200 image/webp，thumb 檔被建立。"""
        from core.database import Video
        _, repo = temp_db
        cover = _make_small_jpg(tmp_path / "cover.jpg")
        uri = to_file_uri("/movies/v1.mp4")
        repo.upsert_batch([
            Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover))),
        ])

        tf = thumbnail_cache.thumb_file_for(uri)
        assert not tf.exists()

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert tf.exists()

    def test_no_cover_returns_404(self, client, thumb_dir, temp_db):
        """邊界5a：DB 有 video 但 cover_path 空 → 404。"""
        from core.database import Video
        _, repo = temp_db
        uri = to_file_uri("/movies/nocover.mp4")
        repo.upsert_batch([Video(path=uri, mtime=100.0)])

        resp = client.get("/api/gallery/thumb", params={"path": uri})
        assert resp.status_code == 404

    def test_no_video_returns_404(self, client, thumb_dir, temp_db):
        """邊界5b：DB 無該 video → 404。"""
        uri = to_file_uri("/movies/ghost.mp4")
        resp = client.get("/api/gallery/thumb", params={"path": uri})
        assert resp.status_code == 404

    def test_db_not_exists_returns_404(self, client, thumb_dir, mocker):
        """miss 但 DB 不存在 → 404（不 500）。"""
        mocker.patch("web.routers.scanner.get_db_path",
                     return_value=Path("/nonexistent/openaver.db"))
        uri = to_file_uri("/movies/v1.mp4")
        resp = client.get("/api/gallery/thumb", params={"path": uri})
        assert resp.status_code == 404

    def test_generate_fail_fallbacks_to_original(self, client, thumb_dir, temp_db, tmp_path, mocker):
        """邊界6：generate 失敗 → fallback 原圖（200，非 image/webp、非 404、非破圖）。"""
        from core.database import Video
        _, repo = temp_db
        cover = _make_small_jpg(tmp_path / "cover.jpg")
        uri = to_file_uri("/movies/v1.mp4")
        repo.upsert_batch([
            Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover))),
        ])
        mocker.patch("web.routers.scanner.thumbnail_cache.generate", return_value=False)

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200
        assert resp.headers["content-type"] != "image/webp"
        assert resp.headers["content-type"] == "image/jpeg"
        assert len(resp.content) > 0


# ============ POST /api/gallery/thumb/prewarm ============

class TestThumbPrewarm:
    def test_disabled_returns_disabled(self, client, mocker):
        """邊界7：thumbnail_cache_enabled=False → disabled，worker 未啟動。"""
        mocker.patch("web.routers.scanner.load_config",
                     return_value={"thumbnail_cache_enabled": False})
        iter_spy = mocker.patch("web.routers.scanner.thumbnail_cache.iter_missing")
        gen_spy = mocker.patch("web.routers.scanner.thumbnail_cache.generate")
        thread_spy = mocker.patch("web.routers.scanner.threading.Thread")

        resp = client.post("/api/gallery/thumb/prewarm")

        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"
        iter_spy.assert_not_called()
        gen_spy.assert_not_called()
        thread_spy.assert_not_called()

    def test_started_returns_started(self, client, mocker):
        """邊界8：enabled → started（patch Thread no-op 避免 flakiness）。"""
        import web.routers.scanner as scanner_mod
        mocker.patch("web.routers.scanner.load_config",
                     return_value={"thumbnail_cache_enabled": True})
        thread_spy = mocker.patch("web.routers.scanner.threading.Thread")

        # 確保 flag 乾淨
        scanner_mod._prewarming = False
        try:
            resp = client.post("/api/gallery/thumb/prewarm")
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"
            thread_spy.assert_called_once()
            thread_spy.return_value.start.assert_called_once()
        finally:
            scanner_mod._prewarming = False

    def test_reentrant_returns_already_running(self, client, mocker):
        """邊界9：_prewarming=True → already_running，且不啟新 thread。"""
        import web.routers.scanner as scanner_mod
        mocker.patch("web.routers.scanner.load_config",
                     return_value={"thumbnail_cache_enabled": True})
        thread_spy = mocker.patch("web.routers.scanner.threading.Thread")

        scanner_mod._prewarming = True
        try:
            resp = client.post("/api/gallery/thumb/prewarm")
            assert resp.status_code == 200
            assert resp.json()["status"] == "already_running"
            thread_spy.assert_not_called()
        finally:
            scanner_mod._prewarming = False


# ============ M1: hit 後並發 unlink race（feature/71 T8）============

class TestThumbHitConcurrentUnlinkRace:
    """T8 邊界9：hit 判定（tf.exists()）通過後、_serve_thumb_file 內 tf.stat() 前，
    thumb 被並發 invalidate(unlink) → 不得 500（降級走 miss 重生或 404）。
    """

    def test_stat_filenotfound_does_not_500(self, client, thumb_dir, temp_db, tmp_path, mocker):
        """hit 後 stat 拋 FileNotFoundError：DB 有 video+cover → 降級重生 200（非 500）。"""
        from core.database import Video
        _, repo = temp_db
        cover = _make_small_jpg(tmp_path / "cover.jpg")
        uri = to_file_uri("/movies/v1.mp4")
        # 放真 thumb 讓 tf.exists() 為 True（hit 判定通過）
        _make_webp(thumbnail_cache.thumb_file_for(uri))
        repo.upsert_batch([
            Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover))),
        ])

        # 模擬 race：tf.exists() 仍 True（hit 判定通過），但 _serve_thumb_file 的
        # tf.stat()（無 follow_symlinks kwarg）拋 FileNotFoundError。
        # Path.exists() 內部 stat 帶 follow_symlinks → 用此區分，不影響 hit 判定。
        # 只在「第一次」serve stat 拋（模擬 race）；降級重生後的 serve stat 正常。
        real_stat = Path.stat
        tf = thumbnail_cache.thumb_file_for(uri)
        state = {"raised": False}

        def racing_stat(self, *a, **kw):
            if self == tf and "follow_symlinks" not in kw and not state["raised"]:
                state["raised"] = True
                raise FileNotFoundError("raced unlink")
            return real_stat(self, *a, **kw)

        mocker.patch.object(Path, "stat", racing_stat)

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code != 500, (
            f"hit 後並發 unlink（stat FileNotFound）不得 500，實際 {resp.status_code}"
        )
        # 降級重生：200 webp（DB 有 cover）
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"

    def test_stat_filenotfound_no_cover_returns_404_not_500(
        self, client, thumb_dir, temp_db, mocker
    ):
        """hit 後 stat 拋 FileNotFoundError、DB 無 video → 404（非 500）。"""
        uri = to_file_uri("/movies/ghost.mp4")
        _make_webp(thumbnail_cache.thumb_file_for(uri))  # 有檔 → hit

        real_stat = Path.stat
        tf = thumbnail_cache.thumb_file_for(uri)

        def racing_stat(self, *a, **kw):
            if self == tf and "follow_symlinks" not in kw:
                raise FileNotFoundError("raced unlink")
            return real_stat(self, *a, **kw)

        mocker.patch.object(Path, "stat", racing_stat)

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code != 500
        assert resp.status_code == 404
