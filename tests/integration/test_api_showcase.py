"""
test_api_showcase.py — Showcase API 整合測試

測試 GET /api/showcase/videos 端點行為，
包含 user_tags 欄位補充（T4）。
"""

import pytest
from urllib.parse import quote
from core.database import init_db, VideoRepository, Video
from core.path_utils import to_file_uri, uri_to_fs_path
from core.database.version_tracker import get_showcase_revision
import web.routers.showcase as showcase_router


# ============ Fixtures ============

@pytest.fixture
def showcase_setup(tmp_path):
    """
    建立含測試資料的臨時 DB（含 user_tags）。
    回傳 dict：{db_path, vid1_uri, vid2_uri, config}
    """
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
            title="Test Video With Tags",
            actresses=["Test Actress"],
            maker="Test Maker",
            release_date="2024-01-01",
            tags=["高畫質", "單體作品"],
            user_tags=["★5", "足"],
            size_bytes=1073741824,
            mtime=1700000000.0,
        ),
        Video(
            path=vid2_uri,
            number="SONE-002",
            title="Test Video No User Tags",
            actresses=[],
            maker="",
            release_date="",
            tags=[],
            user_tags=[],
            size_bytes=0,
            mtime=0.0,
        ),
    ])
    # user_rating 只由 set_user_rating()/set_user_rating_bulk() 寫入（upsert 排除該欄位，
    # CD-123-3）——vid1 精選、vid2 維持預設 0（未精選），驗證 _serialize_video 無條件輸出。
    repo.set_user_rating(vid1_uri, 3)

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


# ============ Tests ============

class TestShowcaseVideosUserTags:
    """測試 GET /api/showcase/videos 包含 user_tags 欄位（T4）"""

    def test_response_contains_user_tags_field(self, client, showcase_setup, mocker):
        """每個 video 物件必須包含 user_tags 欄位"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["videos"]) == 2

        for video in data["videos"]:
            assert "user_tags" in video, f"user_tags 欄位缺失：{video.get('path')}"
            assert isinstance(video["user_tags"], list), "user_tags 應為 list"

    def test_user_tags_values_preserved(self, client, showcase_setup, mocker):
        """user_tags 值應與 DB 一致"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        # 找到有 user_tags 的影片
        video_with_tags = next(
            v for v in data["videos"] if v["path"] == showcase_setup["vid1_uri"]
        )
        assert video_with_tags["user_tags"] == ["★5", "足"]

    def test_empty_user_tags_returns_empty_list(self, client, showcase_setup, mocker):
        """無 user_tags 時應回傳空 list（不是 null）"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        video_no_tags = next(
            v for v in data["videos"] if v["path"] == showcase_setup["vid2_uri"]
        )
        assert video_no_tags["user_tags"] == []


class TestShowcaseResponseShape:
    """GET /api/showcase/videos 回應形狀契約（162a T4：取代 unit 20 支）"""

    def test_videos_response_shape_and_values(self, client, tmp_path, mocker):
        """兩支影片（全欄位／空欄位）：key 集合、值、型別、sample_images URL 轉換"""
        EXPECTED_KEYS = {
            "path", "title", "original_title", "actresses", "number", "maker", "release_date", "tags",
            "size", "cover_url", "cover_full_url", "mtime", "director", "duration", "series", "label",
            "sample_images", "user_tags", "user_rating", "has_cover", "has_nfo", "auto_focal", "crop_mode",
            "part_tokens",
        }
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        fan_dir = tmp_path / "extrafanart"
        fan_dir.mkdir()
        img1 = fan_dir / "fanart1.jpg"
        img1.write_bytes(b"img")
        img2 = fan_dir / "fanart2.jpg"
        img2.write_bytes(b"img")

        full_uri = to_file_uri(str(video_dir / "full.mp4"), {})
        empty_uri = to_file_uri(str(video_dir / "empty.mp4"), {})
        db_path = tmp_path / "shape.db"
        init_db(db_path)
        VideoRepository(db_path).upsert_batch([
            Video(
                path=full_uri, number="ABC-123", title="Full Title", original_title="フルタイトル",
                actresses=["坂道みる", "深田えいみ"], maker="Full Maker", release_date="2024-03-05",
                tags=["単体作品", "ハイビジョン", "独占配信"], size_bytes=2147483648,
                mtime=1705276800.0, director="山田太郎", duration=120, series="素人シリーズ",
                label="S1",
                sample_images=[to_file_uri(str(img1)), to_file_uri(str(img2))],
            ),
            Video(
                path=empty_uri, number="FC2-PPV-001", title="Empty Title", original_title="",
                actresses=[], maker="", release_date="", tags=[], size_bytes=0, mtime=0.0,
                director="", duration=None, series=None, label="", sample_images=[],
            ),
        ])
        config = {
            "gallery": {"directories": [str(video_dir)], "path_mappings": {},
                        "min_size_mb": 0, "thumbnail_width": 400},
            "scraper": {"video_extensions": [".mp4"], "image_extensions": [".jpg"]},
            "database": {"path": ":memory:"},
            "translate": {"provider": "ollama", "ollama_model": "llama3"},
        }
        mocker.patch("web.routers.showcase.get_db_path", return_value=db_path)
        mocker.patch("web.routers.showcase.load_config", return_value=config)

        response = client.get("/api/showcase/videos")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["videos"]) == 2
        by_number = {v["number"]: v for v in data["videos"]}
        full = by_number["ABC-123"]
        empty = by_number["FC2-PPV-001"]

        assert set(full.keys()) == EXPECTED_KEYS
        assert set(empty.keys()) == EXPECTED_KEYS
        assert full["path"].startswith("file:///")
        assert empty["path"].startswith("file:///")

        # 全欄位影片
        assert full["title"] == "Full Title"
        assert full["original_title"] == "フルタイトル"
        assert full["maker"] == "Full Maker"
        assert full["release_date"] == "2024-03-05"
        assert full["actresses"] == "坂道みる,深田えいみ"
        assert full["tags"] == "単体作品,ハイビジョン,独占配信"
        assert full["size"] == 2147483648
        assert full["mtime"] == 1705276800 and type(full["mtime"]) is int
        assert full["director"] == "山田太郎"
        assert full["duration"] == 120 and type(full["duration"]) is int
        assert full["series"] == "素人シリーズ"
        assert full["label"] == "S1"
        assert full["part_tokens"] == []
        assert len(full["sample_images"]) == 2
        for url, name in zip(full["sample_images"], ["fanart1.jpg", "fanart2.jpg"], strict=True):
            assert url.startswith("/api/gallery/image?path=")
            assert name in url

        # 空欄位影片
        assert empty["title"] == "Empty Title"
        assert empty["original_title"] == ""
        assert empty["maker"] == ""
        assert empty["release_date"] == ""
        assert empty["actresses"] == ""
        assert empty["tags"] == ""
        assert empty["size"] == 0
        assert empty["cover_url"] == ""
        assert empty["mtime"] == 0 and type(empty["mtime"]) is int
        assert empty["director"] == ""
        assert empty["series"] == ""
        assert empty["label"] == ""
        assert empty["duration"] is None
        assert empty["sample_images"] == []
        assert empty["part_tokens"] == []


class TestShowcaseUserRatingField:
    """測試 GET /api/showcase/videos 無條件輸出 user_rating 欄位（TASK-123-T2，FE-ALPINE-06）。

    Alpine 3 讀取 x-data 未宣告的屬性會丟 ReferenceError，`x || fallback` 擋不住，
    所以未精選的片也必須輸出鍵，值為 0，不可省略。
    """

    def test_response_contains_user_rating_field(self, client, showcase_setup, mocker):
        """每個 video 物件必須包含 user_rating 欄位（精選與未精選皆然）"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")

        assert response.status_code == 200
        data = response.json()
        assert len(data["videos"]) == 2

        for video in data["videos"]:
            assert "user_rating" in video, f"user_rating 欄位缺失：{video.get('path')}"
            assert isinstance(video["user_rating"], int)

    def test_picked_video_returns_positive_rating(self, client, showcase_setup, mocker):
        """已精選的片 user_rating > 0"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        picked = next(v for v in data["videos"] if v["path"] == showcase_setup["vid1_uri"])
        assert picked["user_rating"] > 0

    def test_unpicked_video_returns_zero_not_missing_key(self, client, showcase_setup, mocker):
        """未精選的片 user_rating == 0（不是缺鍵）"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        unpicked = next(v for v in data["videos"] if v["path"] == showcase_setup["vid2_uri"])
        assert "user_rating" in unpicked
        assert unpicked["user_rating"] == 0


# ============ auto_focal / crop_mode Tests (98b-T1) ============

class TestShowcaseFocalFields:
    """測試 /api/showcase/videos 與 /api/showcase/video 回傳 auto_focal / crop_mode 兩欄（98b-T1）。

    serializer 由列表端點與單筆端點共用，兩欄純加、值等於 DB。
    """

    @pytest.fixture
    def focal_setup(self, tmp_path):
        """建立含 focal 座標與空 focal 兩片的臨時 DB。"""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()

        vid_focal_uri = to_file_uri(str(video_dir / "with_focal.mp4"), {})
        vid_empty_uri = to_file_uri(str(video_dir / "no_focal.mp4"), {})

        db_path = tmp_path / "focal_test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(
                path=vid_focal_uri,
                number="FOC-001",
                title="With Focal",
                auto_focal="0.6231,0.4177",
                crop_mode="auto",
            ),
            Video(
                path=vid_empty_uri,
                number="FOC-002",
                title="No Focal",
                auto_focal="",
                crop_mode="default",
            ),
        ])

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
            "vid_focal_uri": vid_focal_uri,
            "vid_empty_uri": vid_empty_uri,
            "config": config,
        }

    def test_videos_contains_focal_fields(self, client, focal_setup, mocker):
        """列表端點：每片含 auto_focal / crop_mode，值等於 DB。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=focal_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=focal_setup["config"])

        response = client.get("/api/showcase/videos")
        assert response.status_code == 200
        videos = {v["path"]: v for v in response.json()["videos"]}

        for v in videos.values():
            assert "auto_focal" in v, f"auto_focal 欄位缺失：{v.get('path')}"
            assert "crop_mode" in v, f"crop_mode 欄位缺失：{v.get('path')}"

        v_focal = videos[focal_setup["vid_focal_uri"]]
        assert v_focal["auto_focal"] == "0.6231,0.4177"
        assert v_focal["crop_mode"] == "auto"

        v_empty = videos[focal_setup["vid_empty_uri"]]
        assert v_empty["auto_focal"] == ""
        assert v_empty["crop_mode"] == "default"

    def test_single_video_contains_focal_fields(self, client, focal_setup, mocker):
        """單筆端點：同含兩欄，值等於 DB（覆蓋 serializer 共用兩端點）。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=focal_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=focal_setup["config"])

        response = client.get(f"/api/showcase/video?path={focal_setup['vid_focal_uri']}")
        assert response.status_code == 200
        video = response.json()["video"]
        assert video["auto_focal"] == "0.6231,0.4177"
        assert video["crop_mode"] == "auto"


# ============ has_cover / has_nfo Tests ============

class TestShowcaseHasCoverHasNfo:
    """測試 GET /api/showcase/videos 包含 has_cover / has_nfo 欄位（T2）"""

    @pytest.fixture
    def cover_nfo_setup(self, tmp_path):
        """建立含 4 種 has_cover×has_nfo 組合的臨時 DB"""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()

        # 建立假封面 URI（不需要真實檔案，DB 初判不做 IO）
        cover_uri = to_file_uri(str(tmp_path / "cover.jpg"), {})

        uris = {
            "v_ff": to_file_uri(str(video_dir / "v_ff.mp4"), {}),  # cover=False, nfo=False
            "v_tf": to_file_uri(str(video_dir / "v_tf.mp4"), {}),  # cover=True,  nfo=False
            "v_ft": to_file_uri(str(video_dir / "v_ft.mp4"), {}),  # cover=False, nfo=True
            "v_tt": to_file_uri(str(video_dir / "v_tt.mp4"), {}),  # cover=True,  nfo=True
        }

        db_path = tmp_path / "cover_nfo_test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(path=uris["v_ff"], title="FF", cover_path="",        nfo_mtime=0.0),
            Video(path=uris["v_tf"], title="TF", cover_path=cover_uri, nfo_mtime=0.0),
            Video(path=uris["v_ft"], title="FT", cover_path="",        nfo_mtime=1700000000.0),
            Video(path=uris["v_tt"], title="TT", cover_path=cover_uri, nfo_mtime=1700000000.0),
        ])

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

        return {"db_path": db_path, "uris": uris, "config": config}

    def test_has_cover_and_has_nfo_fields_present(self, client, cover_nfo_setup, mocker):
        """每個 video 物件必須包含 has_cover 與 has_nfo 欄位"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=cover_nfo_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=cover_nfo_setup["config"])

        response = client.get("/api/showcase/videos")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        for video in data["videos"]:
            assert "has_cover" in video, f"has_cover 欄位缺失：{video.get('path')}"
            assert "has_nfo" in video, f"has_nfo 欄位缺失：{video.get('path')}"
            assert isinstance(video["has_cover"], bool)
            assert isinstance(video["has_nfo"], bool)

    def test_has_cover_false_when_cover_path_empty(self, client, cover_nfo_setup, mocker):
        """cover_path 為空字串時 has_cover 應為 False"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=cover_nfo_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=cover_nfo_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        v_ff = next(v for v in data["videos"] if v["path"] == cover_nfo_setup["uris"]["v_ff"])
        assert v_ff["has_cover"] is False
        assert v_ff["has_nfo"] is False

    def test_has_cover_true_when_cover_path_set(self, client, cover_nfo_setup, mocker):
        """cover_path 非空時 has_cover 應為 True"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=cover_nfo_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=cover_nfo_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        v_tf = next(v for v in data["videos"] if v["path"] == cover_nfo_setup["uris"]["v_tf"])
        assert v_tf["has_cover"] is True
        assert v_tf["has_nfo"] is False

    def test_has_nfo_true_when_nfo_mtime_positive(self, client, cover_nfo_setup, mocker):
        """nfo_mtime > 0 時 has_nfo 應為 True"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=cover_nfo_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=cover_nfo_setup["config"])

        response = client.get("/api/showcase/videos")
        data = response.json()

        v_ft = next(v for v in data["videos"] if v["path"] == cover_nfo_setup["uris"]["v_ft"])
        assert v_ft["has_cover"] is False
        assert v_ft["has_nfo"] is True

        v_tt = next(v for v in data["videos"] if v["path"] == cover_nfo_setup["uris"]["v_tt"])
        assert v_tt["has_cover"] is True
        assert v_tt["has_nfo"] is True


# ============ Single Video Endpoint Tests ============

class TestShowcaseVideoSingle:
    """測試 GET /api/showcase/video?path= 單筆查詢端點（T2）"""

    @pytest.fixture
    def single_setup(self, tmp_path):
        """建立含 1 筆有封面＋NFO 影片的臨時 DB"""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()

        cover_uri = to_file_uri(str(tmp_path / "cover.jpg"), {})
        vid_uri = to_file_uri(str(video_dir / "video.mp4"), {})

        db_path = tmp_path / "single_test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(
                path=vid_uri,
                number="ABC-001",
                title="Single Test Video",
                actresses=["Actress A"],
                maker="Test Maker",
                release_date="2024-06-01",
                tags=["HD"],
                user_tags=["★5"],
                size_bytes=2147483648,
                mtime=1700000000.0,
                cover_path=cover_uri,
                nfo_mtime=1700000001.0,
            ),
        ])

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

        return {"db_path": db_path, "vid_uri": vid_uri, "video_dir": video_dir, "config": config}

    def test_happy_path_returns_video(self, client, single_setup, mocker):
        """正常情況：回傳 200 + video dict 欄位完整"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=single_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=single_setup["config"])

        response = client.get(f"/api/showcase/video?path={single_setup['vid_uri']}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "video" in data

        video = data["video"]
        assert video["path"] == single_setup["vid_uri"]
        assert video["number"] == "ABC-001"
        assert video["has_cover"] is True
        assert video["has_nfo"] is True
        assert isinstance(video["user_tags"], list)
        # 確認所有必要欄位存在
        # 番號持久化契約 (62b-2 #3): /api/showcase/video 必須回 `number`，
        # commit 後前端 refreshVideoData 才能突變 video.number → 再開彈窗預填新值。
        for field in ("path", "title", "number", "cover_url", "has_cover", "has_nfo",
                      "user_tags", "tags", "actresses", "size", "mtime"):
            assert field in video, f"欄位 {field} 缺失"

    def test_nonexistent_path_returns_404(self, client, single_setup, mocker):
        """DB 中不存在的 path → 404"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=single_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=single_setup["config"])

        # 用 to_file_uri 產生 configured directory 下的合法 URI（避免手刻 URI 拼接）
        # 確保真的測到「path 在 dir 下但 DB 沒記錄」分支，而非被 dir filter 先擋
        ghost_uri = to_file_uri(str(single_setup["video_dir"] / "ghost.mp4"), {})

        response = client.get(f"/api/showcase/video?path={ghost_uri}")
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "video not found"

    def test_path_not_in_configured_dir_returns_404(self, client, single_setup, mocker, tmp_path):
        """path 不在 configured directory → 404（不洩漏目錄資訊）"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=single_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=single_setup["config"])

        # 建構一個合法 URI 但在不同目錄
        other_dir = tmp_path / "other_dir"
        other_dir.mkdir()
        other_uri = to_file_uri(str(other_dir / "other.mp4"), {})

        response = client.get(f"/api/showcase/video?path={other_uri}")
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "video not found"

    def test_missing_path_param_returns_422(self, client, single_setup, mocker):
        """path query param 缺失 → FastAPI 回 422"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=single_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=single_setup["config"])

        response = client.get("/api/showcase/video")
        assert response.status_code == 422

    def test_serializer_consistency_list_vs_single(self, client, single_setup, mocker):
        """列表查詢與單筆查詢同一影片，has_cover / has_nfo / cover_url / path 完全相等"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=single_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=single_setup["config"])

        list_resp = client.get("/api/showcase/videos")
        assert list_resp.status_code == 200
        list_video = list_resp.json()["videos"][0]

        single_resp = client.get(f"/api/showcase/video?path={single_setup['vid_uri']}")
        assert single_resp.status_code == 200
        single_video = single_resp.json()["video"]

        for field in ("path", "has_cover", "has_nfo", "cover_url", "cover_full_url", "number", "user_tags"):
            assert list_video[field] == single_video[field], (
                f"serializer 不一致欄位 {field}: list={list_video[field]!r} single={single_video[field]!r}"
            )


# ============ is_readonly_source field removed Tests (TASK-104-T4) ============
# 90c-T2 引入的 is_readonly_source 欄位曾用來 disable 唯讀來源片的四顆寫入按鈕
# （放大鏡×2/補劇照/齒輪）；TASK-104-T4 解禁四鈕（唯讀改道 output_dir，見 T3），
# 該欄位在前端零消費者 → 連同 _serialize_video 的 readonly_prefixes/writable_prefixes
# plumbing 一併移除（非 weakening，欄位已死；見 plan-104.md CD-104-5/T4）。
# 以下沿用原 fixture（ro_setup 唯讀來源 / mixed_setup 唯讀+可寫混合），斷言方向反轉為
# 「payload 不再帶這個 key」。

class TestShowcaseIsReadonlySourceRemoved:
    """測試 GET /api/showcase/videos / video payload 不再帶 is_readonly_source（TASK-104-T4）。"""

    def _make_config(self, directories):
        return {
            "gallery": {
                "directories": directories,
                "path_mappings": {},
                "min_size_mb": 0,
                "thumbnail_width": 400,
            },
            "scraper": {"video_extensions": [".mp4"], "image_extensions": [".jpg"]},
            "database": {"path": ":memory:"},
            "translate": {"provider": "ollama", "ollama_model": "llama3"},
        }

    @pytest.fixture
    def ro_setup(self, tmp_path):
        """單一唯讀來源夾，含 2 片。"""
        ro_dir = tmp_path / "ro_videos"
        ro_dir.mkdir()
        v1 = to_file_uri(str(ro_dir / "v1.mp4"), {})
        v2 = to_file_uri(str(ro_dir / "v2.mp4"), {})

        db_path = tmp_path / "ro_test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(path=v1, number="RO-001", title="Readonly 1"),
            Video(path=v2, number="RO-002", title="Readonly 2"),
        ])

        config = self._make_config([{"path": str(ro_dir), "readonly": True}])
        return {"db_path": db_path, "v1": v1, "v2": v2, "config": config}

    @pytest.fixture
    def mixed_setup(self, tmp_path):
        """一唯讀夾 + 一可寫夾，各含一片。"""
        ro_dir = tmp_path / "ro_videos"
        ro_dir.mkdir()
        rw_dir = tmp_path / "rw_videos"
        rw_dir.mkdir()
        v_ro = to_file_uri(str(ro_dir / "ro.mp4"), {})
        v_rw = to_file_uri(str(rw_dir / "rw.mp4"), {})

        db_path = tmp_path / "mixed_test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(path=v_ro, number="RO-001", title="Readonly片"),
            Video(path=v_rw, number="RW-001", title="Writable片"),
        ])

        config = self._make_config([
            {"path": str(ro_dir), "readonly": True},
            {"path": str(rw_dir), "readonly": False},
        ])
        return {"db_path": db_path, "v_ro": v_ro, "v_rw": v_rw,
                "ro_dir": ro_dir, "config": config}

    def test_field_absent_readonly_source(self, client, ro_setup, mocker):
        """唯讀來源片 payload 不含 is_readonly_source key（TASK-104-T4 拔除）。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=ro_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=ro_setup["config"])

        data = client.get("/api/showcase/videos").json()
        assert len(data["videos"]) == 2
        for video in data["videos"]:
            assert "is_readonly_source" not in video

    def test_field_absent_writable_source(self, client, showcase_setup, mocker):
        """既有 showcase_setup（裸 str 來源）payload 亦不含 is_readonly_source key。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=showcase_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=showcase_setup["config"])

        data = client.get("/api/showcase/videos").json()
        assert len(data["videos"]) == 2
        for video in data["videos"]:
            assert "is_readonly_source" not in video

    def test_field_absent_mixed_source(self, client, mixed_setup, mocker):
        """混合來源（唯讀+可寫）逐片 payload 皆不含 is_readonly_source key。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=mixed_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=mixed_setup["config"])

        videos = {v["path"]: v for v in client.get("/api/showcase/videos").json()["videos"]}
        assert "is_readonly_source" not in videos[mixed_setup["v_ro"]]
        assert "is_readonly_source" not in videos[mixed_setup["v_rw"]]

    def test_single_endpoint_field_absent(self, client, ro_setup, mocker):
        """單筆端點 payload 同樣不含 is_readonly_source key（與列表端點一致）。"""
        mocker.patch("web.routers.showcase.get_db_path", return_value=ro_setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=ro_setup["config"])

        list_video = next(
            v for v in client.get("/api/showcase/videos").json()["videos"]
            if v["path"] == ro_setup["v1"]
        )
        single_video = client.get(f"/api/showcase/video?path={ro_setup['v1']}").json()["video"]
        assert "is_readonly_source" not in list_video
        assert "is_readonly_source" not in single_video


# ============ Thumbnail cache cover_url switch Tests (T4) ============

class TestShowcaseThumbnailCacheCoverUrl:
    """feature/71 T4：thumbnail_cache_enabled 開關切換 cover_url thumb/image 分支 + cover_full_url 恆原圖。"""

    @pytest.fixture
    def cover_setup(self, tmp_path):
        """1 部有封面 + 1 部無封面的 DB。"""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()

        cover_uri = to_file_uri(str(tmp_path / "cover.jpg"), {})
        vid_cover_uri = to_file_uri(str(video_dir / "with_cover.mp4"), {})
        vid_nocover_uri = to_file_uri(str(video_dir / "no_cover.mp4"), {})

        db_path = tmp_path / "thumb_switch.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(path=vid_cover_uri, number="COV-001", title="With Cover", cover_path=cover_uri),
            Video(path=vid_nocover_uri, number="NOC-001", title="No Cover", cover_path=""),
        ])

        base_config = {
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
            "cover_uri": cover_uri,
            "vid_cover_uri": vid_cover_uri,
            "vid_nocover_uri": vid_nocover_uri,
            "base_config": base_config,
        }

    def _get_videos(self, client, mocker, setup, enabled):
        config = dict(setup["base_config"])
        config["thumbnail_cache_enabled"] = enabled
        mocker.patch("web.routers.showcase.get_db_path", return_value=setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=config)
        resp = client.get("/api/showcase/videos")
        assert resp.status_code == 200
        return {v["path"]: v for v in resp.json()["videos"]}

    def test_enabled_cover_url_is_thumb_keyed_by_video_path(self, client, cover_setup, mocker):
        """邊界 1：enabled → cover_url = /api/gallery/thumb?path=quote(v.path)。"""
        videos = self._get_videos(client, mocker, cover_setup, enabled=True)
        v = videos[cover_setup["vid_cover_uri"]]
        expected = f"/api/gallery/thumb?path={quote(cover_setup['vid_cover_uri'], safe='')}"
        assert v["cover_url"] == expected
        # thumb key 必須是 video path，不是 cover path
        assert quote(cover_setup["cover_uri"], safe="") not in v["cover_url"]

    def test_disabled_cover_url_is_image_bytewise(self, client, cover_setup, mocker):
        """邊界 2：disabled → cover_url = /api/gallery/image?path=quote(uri_to_fs_path(cover))（字節不變）。"""
        videos = self._get_videos(client, mocker, cover_setup, enabled=False)
        v = videos[cover_setup["vid_cover_uri"]]
        expected = f"/api/gallery/image?path={quote(uri_to_fs_path(cover_setup['cover_uri']), safe='')}"
        assert v["cover_url"] == expected
        assert v["cover_url"].startswith("/api/gallery/image?path=")
        assert "%2F" in v["cover_url"]

    def test_cover_full_url_always_image_regardless_of_flag(self, client, cover_setup, mocker):
        """邊界 3：cover_full_url 恆原圖 image url（不受 flag 影響）。"""
        expected = f"/api/gallery/image?path={quote(uri_to_fs_path(cover_setup['cover_uri']), safe='')}"
        for enabled in (True, False):
            videos = self._get_videos(client, mocker, cover_setup, enabled=enabled)
            v = videos[cover_setup["vid_cover_uri"]]
            assert v["cover_full_url"] == expected, f"enabled={enabled}"
            assert v["cover_full_url"].startswith("/api/gallery/image?path=")

    def test_no_cover_video_empty_urls_both_flags(self, client, cover_setup, mocker):
        """邊界 4：無 cover → cover_url == cover_full_url == ''、has_cover False（兩 flag 皆然）。"""
        for enabled in (True, False):
            videos = self._get_videos(client, mocker, cover_setup, enabled=enabled)
            v = videos[cover_setup["vid_nocover_uri"]]
            assert v["cover_url"] == "", f"enabled={enabled}"
            assert v["cover_full_url"] == "", f"enabled={enabled}"
            assert v["has_cover"] is False


# ============ AC-18: 合併卡 path 為 part-1，enrich 只作用 part-1（TASK-122-T2）============

class TestAC18EnrichOnlyTouchesPart1:
    """CD-122-11：補齊資料一律只作用 part-1。這是 `_serialize_group()` 把 `path`
    定死為 part-1（AC-18 契約）的自然結果——前端所有「拿 video.path 打 API」的
    既有呼叫（包含 enrich）天然只送 part-1 path，不需要任何分組感知。本測試驗證
    這條鏈路的最後一環：真的呼叫 enrich（mode='db_to_sidecar'，不打外部 scraper，
    只把 DB 現有 metadata 寫進 sidecar NFO）於合併卡的代表段 path，斷言 part-1
    的 NFO 被寫入、part-2 的檔案在磁碟上完全未被觸碰（mtime 與內容不變）。
    """

    def test_enrich_db_to_sidecar_on_part1_path_leaves_part2_untouched(self, tmp_path, mocker):
        video_dir = tmp_path / "videos"
        video_dir.mkdir()

        part1_fs = video_dir / "ABC-123-cd1.mp4"
        part2_fs = video_dir / "ABC-123-cd2.mp4"
        part1_fs.write_bytes(b"part1-video-bytes")
        part2_fs.write_bytes(b"part2-video-bytes-untouched")

        part1_uri = to_file_uri(str(part1_fs), {})
        part2_uri = to_file_uri(str(part2_fs), {})

        db_path = tmp_path / "ac18.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        repo.upsert_batch([
            Video(
                path=part1_uri,
                number="ABC-123",
                title="AC-18 Part 1",
                original_title="",
                actresses=["Actress"],
                maker="Maker",
                release_date="2024-01-01",
                tags=["tag1"],
                duration=60,
                size_bytes=100,
                mtime=part1_fs.stat().st_mtime,
            ),
            Video(
                path=part2_uri,
                number="ABC-123",
                title="AC-18 Part 2",
                original_title="",
                actresses=["Actress"],
                maker="Maker",
                release_date="2024-01-01",
                tags=["tag1"],
                duration=60,
                size_bytes=100,
                mtime=part2_fs.stat().st_mtime,
            ),
        ])

        # 先確認 showcase 序列化真的把合併卡的 path 定成 part-1（AC-18 前半段契約），
        # 再拿這個 path 去打 enrich（後半段：用這個 path 觸發 enrich 只碰 part-1）。
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
        mocker.patch("web.routers.showcase.get_db_path", return_value=db_path)
        mocker.patch("web.routers.showcase.load_config", return_value=config)
        from fastapi.testclient import TestClient
        from web.app import app
        showcase_client = TestClient(app, client=("127.0.0.1", 50000))
        resp = showcase_client.get("/api/showcase/videos")
        body = resp.json()
        assert body["total"] == 1, "part1/part2 應合併成一張卡"
        card = body["videos"][0]
        assert card["path"] == part1_uri
        assert card["part_tokens"] == ["cd1", "cd2"]

        part2_mtime_before = part2_fs.stat().st_mtime
        part2_content_before = part2_fs.read_bytes()
        part2_nfo = part2_fs.with_suffix(".nfo")
        assert not part2_nfo.exists()

        from core.enricher import enrich_single
        mocker.patch("core.enricher.VideoRepository", return_value=repo)
        result = enrich_single(
            file_path=card["path"],  # 合併卡回傳的代表段 path == part-1
            number="ABC-123",
            mode="db_to_sidecar",
            write_nfo=True,
            write_cover=False,
            path_mappings={},
        )

        assert result.success is True
        assert result.nfo_written is True

        part1_nfo = part1_fs.with_suffix(".nfo")
        assert part1_nfo.exists(), "part-1 的 NFO 必須被寫入"

        # part-2 完全未被觸碰：沒有新產生 NFO、mtime 與內容不變
        assert not part2_nfo.exists(), "part-2 不應該生出 NFO"
        assert part2_fs.stat().st_mtime == part2_mtime_before
        assert part2_fs.read_bytes() == part2_content_before


# ============ ETag / 304 (TASK-145-T3, CD-145a-8/11/12) ============

class TestShowcaseVideosETag:
    """GET /api/showcase/videos 的 ETag / 304 行為。

    ETag 涵蓋 DB 內部寫入 revision、DB/-wal 檔案指紋（涵蓋外部抽換或還原備份）、
    無機密設定投影（來源資料夾／path_mappings／縮圖開關）三項；命中 If-None-Match
    時要在序列化之前短路回 304。
    """

    def _get(self, client, mocker, setup, if_none_match=None):
        mocker.patch("web.routers.showcase.get_db_path", return_value=setup["db_path"])
        mocker.patch("web.routers.showcase.load_config", return_value=setup["config"])
        headers = {"If-None-Match": if_none_match} if if_none_match else {}
        return client.get("/api/showcase/videos", headers=headers)

    def test_route_passes_revision_into_compute_etag(self, client, showcase_setup, mocker):
        """route 層獨立驗證：`get_videos()` 真的把 `get_showcase_revision()` 的值接進
        `compute_etag()` 呼叫——不是只驗 `compute_etag()` 這個函式本身吃 revision 當參數
        （那件事 unit 測試已經驗過）。

        把 `compute_db_fingerprint` monkeypatch 成固定回傳同一個常數，讓 db_fingerprint
        這個訊號完全不會變動、不會「頂替」revision 的訊號（真實寫入必然也改變 -wal 檔案
        stat，這正是 mutation 點 1 一度在 integration 層 SURVIVED 的根因——這支測試就是
        為了在 route 呼叫點堵住那個縫：先把 db_fingerprint 按死，才能單獨看 revision 有沒有
        真的被傳進去）。
        """
        mocker.patch("web.routers.showcase.compute_db_fingerprint", return_value="frozen-fingerprint")

        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]
        revision_before = get_showcase_revision()

        repo = VideoRepository(showcase_setup["db_path"])
        repo.set_user_rating(showcase_setup["vid2_uri"], 5)

        assert get_showcase_revision() != revision_before, (
            "自我把關：這支測試的前提是這筆寫入真的 bump 了 revision，否則後面的 200 斷言" \
            "測不出任何東西（假綠）"
        )

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200, (
            "db_fingerprint 被凍結不動，若 route 沒有把 revision 傳進 compute_etag()，"
            "這裡會誤回 304——使用者剛操作完（精選/標籤/焦點/掃描新片）切回瀏覽頁，"
            "看到的還是操作前的舊清單"
        )

    def test_second_request_no_writes_returns_304_and_skips_serialization(self, client, showcase_setup, mocker):
        """驗收 1／DoD ①：兩次無寫入的請求，第二次回 304，且 _serialize_group 完全沒被呼叫
        （方案 B 的判別點——不是只驗傳輸變小，要驗序列化真的沒發生）。"""
        spy = mocker.spy(showcase_router, "_serialize_group")
        first = self._get(client, mocker, showcase_setup)
        assert first.status_code == 200
        etag = first.headers["etag"]
        spy.reset_mock()

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 304
        assert second.headers["etag"] == etag
        spy.assert_not_called()
        assert second.content == b""

    def test_consecutive_gets_without_writes_return_304(self, client, showcase_setup, mocker):
        """DoD ②：init_db() 每次請求都跑，其 no-op commit 不可反覆 bump revision——
        route 層級端到端驗證：連續兩次 GET（中間無真實寫入）第二次必回 304。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]
        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 304

    def test_user_rating_write_then_stale_etag_returns_200_with_new_value(self, client, showcase_setup, mocker):
        """DoD ③（user_rating）：set_user_rating() 成功 commit 後，帶舊 ETag 再請求必回 200，
        且新值反映在回應。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        repo = VideoRepository(showcase_setup["db_path"])
        repo.set_user_rating(showcase_setup["vid2_uri"], 5)

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200
        assert second.headers["etag"] != etag
        video = next(v for v in second.json()["videos"] if v["path"] == showcase_setup["vid2_uri"])
        assert video["user_rating"] == 5

    def test_user_tags_write_then_stale_etag_returns_200_with_new_value(self, client, showcase_setup, mocker):
        """DoD ③（user_tags）：update_user_tags() 成功 commit 後，帶舊 ETag 再請求必回 200。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        repo = VideoRepository(showcase_setup["db_path"])
        repo.update_user_tags(showcase_setup["vid2_uri"], ["新標籤"])

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200
        video = next(v for v in second.json()["videos"] if v["path"] == showcase_setup["vid2_uri"])
        assert video["user_tags"] == ["新標籤"]

    def test_manual_focal_write_then_stale_etag_returns_200_with_new_value(self, client, showcase_setup, mocker):
        """DoD ③（auto_focal / crop_mode）：update_manual_focal() 單一 UPDATE 同時寫兩欄，
        成功 commit 後帶舊 ETag 再請求必回 200，兩欄新值都反映在回應。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        repo = VideoRepository(showcase_setup["db_path"])
        row = repo.get_by_path(showcase_setup["vid1_uri"])
        written = repo.update_manual_focal(showcase_setup["vid1_uri"], "0.5000,0.5000", row.cover_path or "")
        assert written is True

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200
        video = next(v for v in second.json()["videos"] if v["path"] == showcase_setup["vid1_uri"])
        assert video["auto_focal"] == "0.5000,0.5000"
        assert video["crop_mode"] == "manual"

    def test_new_video_after_scan_is_visible_via_304_then_200(self, client, showcase_setup, mocker):
        """DoD ①②（硬條件）＋ mutation 點 1：少算 revision 一項會讓這支紅——
        先確認無變動時回 304，掃描新片 INSERT+commit 後帶舊 ETag 再請求必回 200，
        新片出現在回應裡。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        unchanged = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert unchanged.status_code == 304

        video_dir = showcase_setup["db_path"].parent / "videos"
        new_uri = to_file_uri(str(video_dir / "video3.mp4"), {})
        repo = VideoRepository(showcase_setup["db_path"])
        repo.upsert_batch([Video(path=new_uri, number="SONE-003", title="New Scanned Video")])

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200
        paths = {v["path"] for v in second.json()["videos"]}
        assert new_uri in paths

    def test_external_db_file_replacement_forces_200(self, client, showcase_setup, mocker):
        """DoD ④（硬條件）＋ mutation 點 2：少算 db_fingerprint 一項會讓這支紅——外部整份
        抽換／還原 DB 檔（沒有任何 commit 經過我們的連線工廠），帶舊 ETag 再請求必回 200，
        新內容可見。

        建替換內容刻意走 `shutil.copy` + 一條 raw `sqlite3.connect()`（不透過
        `core.database.connection.get_connection()` 那個掛了 `_RevisionTrackingConnection`
        的工廠），確保這支測試量到的是 db_fingerprint 本身的效果，不是連帶 bump 到
        process-global revision 的副作用（revision 是進程全域計數器，若改用
        `init_db()`/`VideoRepository` 建替換檔，即使寫的是另一個檔案，也會誤讓這支測試
        在 db_fingerprint 被拿掉時仍意外通過）。
        """
        import shutil
        import sqlite3

        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]
        revision_before = get_showcase_revision()

        db_path = showcase_setup["db_path"]
        video_dir = db_path.parent / "videos"
        replaced_uri = to_file_uri(str(video_dir / "video1.mp4"), {})

        replacement_path = db_path.parent / "replacement.db"
        shutil.copy(db_path, replacement_path)
        conn = sqlite3.connect(str(replacement_path))
        conn.execute("UPDATE videos SET title = ? WHERE path = ?", ("Replaced DB Content", replaced_uri))
        conn.commit()
        conn.close()

        replacement_path.replace(db_path)  # 原子整份覆蓋，模擬還原備份／外部抽換

        assert get_showcase_revision() == revision_before, (
            "建替換內容的過程不該動到 process-global revision，否則量不到 db_fingerprint 單獨的效果"
        )

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200
        titles = {v["path"]: v["title"] for v in second.json()["videos"]}
        assert titles.get(replaced_uri) == "Replaced DB Content"

    def test_external_connection_write_not_through_factory_forces_200(self, client, showcase_setup, mocker):
        """DoD ④ 另一半：外部連線（不經過 `core.database.connection.get_connection()`
        那個掛了 `_RevisionTrackingConnection` 的工廠——模擬別的行程/工具直接開 DB 檔）
        做一筆真實寫入＋commit，process-global revision 不會跟著動，但 `compute_db_fingerprint()`
        仍能從檔案 stat（commit 觸發的 checkpoint 落盤）量到差異，帶舊 ETag 再請求必回 200。

        直接對 -wal 檔案寫入任意位元組不是這個情境的忠實模擬——init_db() 每次請求都會先
        跑，開新連線時 SQLite 會判斷 -wal header 無效並整份丟棄重置（已用腳本實測：寫入
        垃圾位元組後，下一次 init_db() 會讓 -wal 變回「不存在」，指紋跟外部寫入前逐位元組
        相同），反而會製造假陰性，所以改用一條真實的 sqlite3 連線做合法寫入。
        """
        import sqlite3

        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]
        revision_before = get_showcase_revision()

        conn = sqlite3.connect(str(showcase_setup["db_path"]))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO videos (path, number) VALUES (?, ?)",
            ("file:///ext/external-write.mp4", "EXT-001"),
        )
        conn.commit()
        conn.close()

        assert get_showcase_revision() == revision_before, (
            "外部連線不走我們的連線工廠，process-global revision 本就不該被它動到"
        )

        second = self._get(client, mocker, showcase_setup, if_none_match=etag)
        assert second.status_code == 200

    def test_config_change_reflected_immediately(self, client, showcase_setup, mocker):
        """驗收 3 ＋ mutation 點 3：少算設定投影一項會讓這支紅——來源資料夾集合改變後，
        帶舊 ETag 請求必回 200，新設定生效（新來源夾的片可見）。

        額外一支片的 DB row 刻意在 `first` 請求**之前**就寫好（擺在當前設定的資料夾
        範圍外，`first` 天然看不到它），兩次請求之間**不**再對 DB 做任何真實寫入——
        只改 config。這樣才能確定是「設定投影」本身讓 ETag 改變，不是夾帶一次真實
        commit（會連動 bump process-global revision，讓這支測試在設定投影被拿掉時
        仍意外通過）。
        """
        video_dir = showcase_setup["db_path"].parent / "videos"
        extra_dir = showcase_setup["db_path"].parent / "extra_videos"
        extra_dir.mkdir()
        extra_uri = to_file_uri(str(extra_dir / "extra.mp4"), {})
        VideoRepository(showcase_setup["db_path"]).upsert_batch(
            [Video(path=extra_uri, number="EXTRA-001", title="Extra Dir Video")]
        )

        first = self._get(client, mocker, showcase_setup)
        assert extra_uri not in {v["path"] for v in first.json()["videos"]}, (
            "額外片此時應仍在設定資料夾範圍外，first 不該看到它"
        )
        etag = first.headers["etag"]
        revision_before = get_showcase_revision()

        new_config = dict(showcase_setup["config"])
        new_config["gallery"] = dict(new_config["gallery"])
        new_config["gallery"]["directories"] = [str(video_dir), str(extra_dir)]
        setup_with_new_config = {**showcase_setup, "config": new_config}

        second = self._get(client, mocker, setup_with_new_config, if_none_match=etag)
        assert get_showcase_revision() == revision_before, (
            "兩次請求之間不該有任何真實 DB 寫入，否則量不到設定投影單獨的效果"
        )
        assert second.status_code == 200
        paths = {v["path"] for v in second.json()["videos"]}
        assert extra_uri in paths

    def test_thumbnail_cache_flag_change_reflected_immediately(self, client, showcase_setup, mocker):
        """驗收 3：設定投影第三項（thumbnail_cache_enabled）改變同樣要讓舊 ETag 失效。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        new_config = dict(showcase_setup["config"])
        new_config["thumbnail_cache_enabled"] = True
        setup_with_new_config = {**showcase_setup, "config": new_config}

        second = self._get(client, mocker, setup_with_new_config, if_none_match=etag)
        assert second.status_code == 200
        assert second.headers["etag"] != etag

    def test_empty_db_response_has_no_etag_header(self, client, showcase_setup, mocker, tmp_path):
        """驗收 5：DB 檔案不存在時的空庫早退分支，回應逐位元組與改動前相同，
        且完全沒有 ETag header（沒有走到本次改動加入的計算路徑）。"""
        missing_db = tmp_path / "does_not_exist.db"
        setup = {**showcase_setup, "db_path": missing_db}
        response = self._get(client, mocker, setup)
        assert response.status_code == 200
        assert response.json() == {"success": True, "videos": [], "total": 0}
        assert "etag" not in response.headers

    def test_if_none_match_multi_value_or_weak_prefix_still_matches(self, client, showcase_setup, mocker):
        """mutation 點 4：破壞逗號拆分／`W/` 弱驗證前綴比對語意會讓這支紅——瀏覽器真實
        送出的多值或帶弱驗證前綴的 If-None-Match，資料沒變時仍必須回 304。"""
        first = self._get(client, mocker, showcase_setup)
        etag = first.headers["etag"]

        weak = self._get(client, mocker, showcase_setup, if_none_match=f'W/{etag}')
        assert weak.status_code == 304

        multi = self._get(client, mocker, showcase_setup, if_none_match=f'"bogus-etag-value", {etag}')
        assert multi.status_code == 304

    def test_response_shape_unchanged_besides_new_headers(self, client, showcase_setup, mocker):
        """既有回應形狀不因加了 ETag 而改變（success/videos/total 三鍵仍在，200 分支
        額外多 ETag／Cache-Control 兩個 header）。"""
        response = self._get(client, mocker, showcase_setup)
        data = response.json()
        assert data["success"] is True
        assert data["total"] == len(data["videos"])
        assert response.headers["cache-control"] == "no-cache"
