"""test_api_thumb.py - 縮圖快取 API 整合測試（feature/71 T3）

涵蓋 TASK-71-T3 邊界 1-9：
- GET /api/gallery/thumb：hit serve webp + no-cache + 強 ETag；If-None-Match → 304；
  hit 零 DB/零 NAS；miss 生成；無 cover 404；generate 失敗 fallback 原圖。

隔離關鍵：thumbnail_cache._thumb_dir 與 scanner.get_db_path 是兩個獨立 reference，
兩者都要 patch（見 TASK card 測試隔離坑）。
"""
import pytest
from pathlib import Path

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
def thumb_enabled(mocker):
    """把 thumbnail_cache_enabled 設 True（P2-B gate：預設 False，generate 測試需啟用）。"""
    mocker.patch(
        "web.routers.scanner.load_config",
        return_value={"thumbnail_cache_enabled": True},
    )


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
        repo_spy = mocker.patch("web.routers.gallery_media.VideoRepository")
        db_spy = mocker.patch("web.routers.gallery_media.get_db_path")

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200
        gen_spy.assert_not_called()
        repo_spy.assert_not_called()
        db_spy.assert_not_called()


class TestGetThumbMiss:
    def test_miss_generates_webp(self, client, thumb_dir, thumb_enabled, temp_db, tmp_path, mocker):
        """邊界4：miss + DB 有 video + cover 真小圖 → 200 image/webp，thumb 檔被建立。"""
        from core.database import Video
        db_path, repo = temp_db
        mocker.patch(
            "web.routers.gallery_media.load_config",
            return_value={"thumbnail_cache_enabled": True},
        )
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
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


    def test_generate_fail_fallbacks_to_original(self, client, thumb_dir, temp_db, tmp_path, mocker):
        """邊界6：generate 失敗 → fallback 原圖（200，非 image/webp、非 404、非破圖）。"""
        from core.database import Video
        db_path, repo = temp_db
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
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


# ============ Codex round-2 P2: miss→generate 成功的 serve 在 OSError guard 外 ============


# ============ Codex round-2 P1: generate 後 fresh is None / 空 cover → stale ============


# ============ P1: generate 後 cover stale → invalidate + serve 當前封面 ============

class TestGetThumbStaleCoverAfterGenerate:
    """Codex P1：miss 路徑 generate(cover_fs) 成功後、serve 前 re-read DB cover；
    若 cover_path 已被並發換掉（enrich/rescrape）→ 丟棄剛寫的 stale thumb（invalidate）
    並改 serve 當前封面，避免把舊封面 thumb 當新圖回給用戶。
    """

    def test_stale_cover_invalidates_and_serves_current_cover(
        self, client, thumb_dir, thumb_enabled, temp_db, tmp_path, mocker
    ):
        from core.database import Video
        db_path, repo = temp_db
        mocker.patch(
            "web.routers.gallery_media.load_config",
            return_value={"thumbnail_cache_enabled": True},
        )
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
        cover_a = _make_small_jpg(tmp_path / "cover_a.jpg", size=(800, 600))
        cover_b = _make_small_jpg(tmp_path / "cover_b.jpg", size=(640, 480))
        uri = to_file_uri("/movies/v1.mp4")
        # DB 初始 cover A
        repo.upsert_batch([
            Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover_a))),
        ])

        invalidate_spy = mocker.patch(
            "web.routers.scanner.thumbnail_cache.invalidate"
        )

        # generate(cover_a, tf) 「成功」後，模擬 DB 已被換成 cover B：
        # 讓 generate 真寫一個 thumb（回 True），且在 generate 後把 DB cover_path 改 B。
        real_generate = thumbnail_cache.generate

        def generate_then_swap(cover_fs, dst):
            ok = real_generate(cover_fs, dst)
            # 模擬並發 enrich 換封面
            repo.upsert_batch([
                Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover_b))),
            ])
            return ok

        mocker.patch(
            "web.routers.scanner.thumbnail_cache.generate",
            side_effect=generate_then_swap,
        )

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        # 偵測 stale → invalidate(path) 被呼叫丟棄剛寫的舊 thumb
        invalidate_spy.assert_called_once_with(uri)
        # serve 的不是 stale thumb（非 image/webp），而是當前封面 B 的原圖
        assert resp.status_code == 200
        assert resp.headers["content-type"] != "image/webp"
        assert resp.headers["content-type"] == "image/jpeg"
        # 內容是 cover B（當前封面），不是 cover A
        assert resp.content == cover_b.read_bytes()


# ============ M1: hit 後並發 unlink race（feature/71 T8）============


# ============ POST /api/gallery/thumb/clear (71b-T2) ============

class TestThumbClear:
    """71b-T2：DB-safe 清空端點。清 output/thumb/、回 {"cleared": True}，
    **絕不碰 videos DB**（row 數不變）。"""


    def test_clear_removes_thumb_dir_contents(self, client, thumb_dir):
        """thumb_dir 內既有 webp → 清後目錄被移除（rmtree，缺目錄 no-op）。"""
        uri = to_file_uri("/movies/v1.mp4")
        _make_webp(thumbnail_cache.thumb_file_for(uri))
        assert any(thumb_dir.iterdir()), "前置：thumb_dir 應有檔"

        resp = client.post("/api/gallery/thumb/clear")

        assert resp.status_code == 200
        # rmtree(_thumb_dir())：整個目錄移除（CD-11 缺目錄 no-op）
        assert not thumb_dir.exists() or not any(thumb_dir.iterdir()), \
            "thumb_dir 應被清空"

    def test_clear_does_not_touch_videos_db(self, client, thumb_dir, temp_db):
        """硬約束：videos DB row 數清前清後不變（端點絕不碰 DB）。"""
        from core.database import Video
        _, repo = temp_db
        repo.upsert_batch([
            Video(path=to_file_uri("/movies/a.mp4"), mtime=1.0),
            Video(path=to_file_uri("/movies/b.mp4"), mtime=2.0),
            Video(path=to_file_uri("/movies/c.mp4"), mtime=3.0),
        ])
        before = repo.count()
        assert before == 3, "前置：DB 應有 3 筆"

        resp = client.post("/api/gallery/thumb/clear")

        assert resp.status_code == 200
        assert repo.count() == before, \
            f"videos DB row 數不得變（清前 {before}，清後 {repo.count()}）"


# ============ TASK-71c P2-A：double-decode（字面 % 路徑 miss → 404）============

class TestGetThumbDoubleDecodeP2A:
    """P2-A：get_thumb 對 FastAPI 已 decode 的 path 再 unquote → double-decode。
    路徑含字面 % 字元（如 file:///nas/Test%20File.mp4）→ key 失配 → miss 404。
    修法：移除 get_thumb 內的 path = unquote(path)，信任 FastAPI 已 decode。
    """

    def test_miss_with_literal_percent_in_path(self, client, thumb_dir, temp_db, tmp_path, mocker):
        """P2-A RED → GREEN：path 含字面 %，FastAPI 已 decode，handler 不應再 unquote。
        TestClient 走真 FastAPI decode pipeline（quote → ASGI → FastAPI decode → handler）。
        修前 double-decode → key 失配 → 404（RED）。修後 200（GREEN）。
        """
        from core.database import Video

        db_path, repo = temp_db
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
        # path 含字面 %（不是 URL encode 序列，而是檔名本身含 % 的字串）
        v_path = to_file_uri("/nas/Test%20File.mp4")  # 字面 % 在 URI 中
        cover = _make_small_jpg(tmp_path / "cover_percent.jpg")
        repo.upsert_batch([
            Video(path=v_path, mtime=100.0, cover_path=to_file_uri(str(cover))),
        ])

        # TestClient(httpx) 自動 percent-encode params → FastAPI decode 一次 → handler 收到的
        # path 應等於原始 v_path（含字面 %）。修前多餘 unquote 會再 decode 一次 → key 失配。
        resp = client.get("/api/gallery/thumb", params={"path": v_path})

        # 修前：double-decode → key 失配 → 404（RED）
        # 修後：handler 直接用 FastAPI decode 後的值 → key 命中 → 不是 404（GREEN）
        assert resp.status_code != 404, (
            f"path 含字面 % 不應 double-decode 導致 key 失配 404，實際 {resp.status_code}\n"
            f"v_path={v_path!r}"
        )


# ============ TASK-71c P2-B：miss 路徑無 disabled gate ============

class TestGetThumbMissDisabledGateP2B:
    """P2-B：get_thumb miss 路徑未先檢查 thumbnail_cache_enabled，
    用戶關閉快取後仍重生 WebP → 「關閉並清除」無效。
    修法：generate 前加 gate，disabled → fall through 到 fallback 原圖。
    """

    def test_miss_disabled_does_not_generate(
        self, client, thumb_dir, temp_db, tmp_path, mocker
    ):
        """P2-B RED → GREEN：快取關閉時 miss 路徑不應呼叫 generate。
        修前：generate 被呼叫（RED）。修後：generate 未被呼叫 + 200 fallback 原圖（GREEN）。
        """
        from core.database import Video

        db_path, repo = temp_db
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
        cover = _make_small_jpg(tmp_path / "cover_disabled.jpg")
        uri = to_file_uri("/movies/disabled_test.mp4")
        repo.upsert_batch([
            Video(path=uri, mtime=100.0, cover_path=to_file_uri(str(cover))),
        ])

        # 快取關閉
        mocker.patch(
            "web.routers.gallery_media.load_config",
            return_value={"thumbnail_cache_enabled": False},
        )
        gen_spy = mocker.patch("web.routers.scanner.thumbnail_cache.generate")

        # thumb_dir 空（模擬 clear 後 miss），不預建 thumb

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        # generate 不得被呼叫（快取已關閉）
        gen_spy.assert_not_called()
        # fallback 原圖：200 image/jpeg（不是 404、不是 image/webp）
        assert resp.status_code == 200, (
            f"disabled miss 應 fallback 原圖 200，實際 {resp.status_code}"
        )
        assert resp.headers["content-type"] == "image/jpeg", (
            f"fallback 應是原圖 jpeg，實際 {resp.headers['content-type']}"
        )


# ============ TASK-91-T2b #9/#10/#11: WSL+UNC path_mappings 反解 ============

class TestUriToLocalFsPathReverseMappingThumb:
    """get_thumb miss 分支（#9 首次 generate 用的 cover_fs / #10 generate 後
    re-read 的 fresh_fs）在 WSL + UNC path_mappings 環境下，餵給磁碟 I/O
    （thumbnail_cache.generate/os.path.exists）的路徑必須是反解後的本機路徑，
    而不是裸 uri_to_fs_path() 產生的映射端 UNC 字串。
    """

    def test_get_thumb_miss_generate_uses_reverse_mapped_path(
        self, client, thumb_dir, temp_db, tmp_path, mocker, monkeypatch
    ):
        """#9：miss→generate，DB cover_path 為 mapped UNC URI，config 帶 WSL+mapping
        → thumbnail_cache.generate 收到的 cover_fs 是反解後的本機路徑（可 open()），
        而非裸 UNC 字串 //NAS/share/...（該路徑在測試環境不存在，會讓 generate 失敗）。
        """
        import core.path_utils as path_utils
        from core.database import Video

        db_path, repo = temp_db
        mocker.patch("web.routers.gallery_media.get_db_path", return_value=db_path)
        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        nas_dir = tmp_path / "nas"
        nas_dir.mkdir()
        cover = _make_small_jpg(nas_dir / "cover.jpg")
        mappings = {str(nas_dir): "//NAS/share"}

        mocker.patch(
            "web.routers.gallery_media.load_config",
            return_value={
                "thumbnail_cache_enabled": True,
                "gallery": {"path_mappings": mappings},
            },
        )

        uri = to_file_uri("/movies/wsl_unc.mp4")
        cover_uri = "file://///NAS/share/cover.jpg"
        repo.upsert_batch([Video(path=uri, mtime=100.0, cover_path=cover_uri)])

        gen_spy = mocker.spy(thumbnail_cache, "generate")

        resp = client.get("/api/gallery/thumb", params={"path": uri})

        assert resp.status_code == 200, (
            f"反解後應能真的 open() 本機檔案生成 webp，實際 {resp.status_code}"
        )
        assert resp.headers["content-type"] == "image/webp"
        gen_spy.assert_called_once()
        called_cover_fs = gen_spy.call_args[0][0]
        assert called_cover_fs == str(cover), (
            f"generate 應收到反解後的本機路徑 {cover}，實際 {called_cover_fs}"
        )
        assert "//NAS/share" not in called_cover_fs, (
            f"generate 不應收到裸 UNC 映射端字串，實際 {called_cover_fs}"
        )

