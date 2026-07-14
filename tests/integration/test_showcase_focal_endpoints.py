"""
test_showcase_focal_endpoints.py — 98b-T4 / 99a-T1a 兩個 POST endpoint（TDD-lite）

- POST /api/showcase/video/detect-focal {path}   — 純預覽，**不寫 DB**（99a T1a）
- POST /api/showcase/video/focal {path, focal}   — 原子 mutator，存 auto_focal +
  crop_mode='manual'（99a T1a，取代已刪除的 /crop-mode）

**detect_focal 一律 mock（spy），絕不真跑 pigo。** 核心回歸鎖（Codex P0）：
detect_focal 收到的永遠是 row.cover_path 反解的封面 fs（.jpg），
絕非 body path（影片 .mp4 URI）。mutation「改回開 body path」必 RED。

`/api/showcase/video/crop-mode` 端點已於 99a-T1a 移除（見本檔
`TestCropModeRouteRemoved` 回歸鎖）。
"""

import pytest
from core.database import init_db, VideoRepository, Video
from core.path_utils import to_file_uri


@pytest.fixture
def focal_endpoint_setup(tmp_path):
    """臨時 DB：一片有真實封面 .jpg（供 os.path.isfile 通過），一片封面檔缺。

    回傳 dict：db_path / video_uri / cover_uri / cover_fs / video_no_cover_uri /
    config（configured dir = video_dir，非唯讀）。
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    # 真實封面檔（內容不重要——detect_focal 被 mock，不會真讀）
    cover_file = video_dir / "SONE-001-cover.jpg"
    cover_file.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    video_uri = to_file_uri(str(video_dir / "SONE-001.mp4"), {})
    cover_uri = to_file_uri(str(cover_file), {})
    cover_fs = str(cover_file)

    video_no_cover_uri = to_file_uri(str(video_dir / "NOCOVER-001.mp4"), {})
    missing_cover_uri = to_file_uri(str(video_dir / "does-not-exist.jpg"), {})

    db_path = tmp_path / "focal_endpoints.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=video_uri,
            number="SONE-001",
            title="With Cover",
            cover_path=cover_uri,
            crop_mode="default",
            auto_focal="",
        ),
        Video(
            path=video_no_cover_uri,
            number="NOCOVER-001",
            title="Cover File Missing",
            cover_path=missing_cover_uri,   # DB 有值但檔案不存在
            crop_mode="default",
            auto_focal="",
        ),
    ])

    config = {
        "gallery": {
            "directories": [{"path": str(video_dir), "readonly": False, "output_path": ""}],
            "path_mappings": {},
        },
    }

    return {
        "db_path": db_path,
        "video_uri": video_uri,
        "cover_uri": cover_uri,
        "cover_fs": cover_fs,
        "video_no_cover_uri": video_no_cover_uri,
        "video_dir": str(video_dir),
        "config": config,
    }


def _patch_db_and_config(mocker, setup, config=None):
    mocker.patch("web.routers.showcase.get_db_path", return_value=setup["db_path"])
    mocker.patch("web.routers.showcase.load_config", return_value=config or setup["config"])


# ============ crop-mode route removed（99a-T1a 回歸鎖）============

class TestCropModeRouteRemoved:
    def test_crop_mode_route_returns_404(self, client, focal_endpoint_setup, mocker):
        """`/video/crop-mode` 端點已刪除（99a-T1a）——任何 body 都應 404（路由不存在），
        不是被端點邏輯拒絕。回歸鎖：防止未來不慎把端點加回去。
        mutation：把路由復活 → 此測試變 GREEN，證明測試真的在守。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        resp = client.post("/api/showcase/video/crop-mode",
                           json={"path": focal_endpoint_setup["video_uri"], "mode": "auto"})
        assert resp.status_code == 404


# ============ detect-focal ============

class TestDetectFocalEndpoint:
    def test_detects_cover_fs_not_body_path(self, client, focal_endpoint_setup, mocker):
        """Codex P0 回歸鎖：detect_focal 收到 row.cover_path 反解的封面 fs（.jpg），
        絕非 body path（.mp4）。mutation『改回開 body path』必 RED。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        spy = mocker.patch("web.routers.showcase.detect_focal", return_value=(0.42, 0.5))

        resp = client.post("/api/showcase/video/detect-focal",
                           json={"path": focal_endpoint_setup["video_uri"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["auto_focal"] == "0.4200,0.5000"

        spy.assert_called_once()
        called_path = spy.call_args.args[0]
        # ★ 不變式：偵測的是封面 fs，不是 body 的 .mp4 URI/path
        assert called_path == focal_endpoint_setup["cover_fs"]
        assert called_path.endswith(".jpg")
        assert not called_path.endswith(".mp4")
        assert "SONE-001.mp4" not in called_path

    def test_detect_does_not_persist_auto_focal(self, client, focal_endpoint_setup, mocker):
        """99a-T1a：/detect-focal 改純預覽，不寫 DB。mutation 驗證——若把
        repo.update_auto_focal(...) 加回去，此測試必須變 RED。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        mocker.patch("web.routers.showcase.detect_focal", return_value=(0.42, 0.5))
        before = VideoRepository(focal_endpoint_setup["db_path"]).get_by_path(
            focal_endpoint_setup["video_uri"]).auto_focal
        resp = client.post("/api/showcase/video/detect-focal",
                    json={"path": focal_endpoint_setup["video_uri"]})
        assert resp.status_code == 200
        assert resp.json()["auto_focal"] == "0.4200,0.5000"  # 回傳值仍是偵測結果（供前端預覽）
        repo = VideoRepository(focal_endpoint_setup["db_path"])
        assert repo.get_by_path(focal_endpoint_setup["video_uri"]).auto_focal == before

    def test_non_db_path_404_no_detect(self, client, focal_endpoint_setup, mocker):
        _patch_db_and_config(mocker, focal_endpoint_setup)
        spy = mocker.patch("web.routers.showcase.detect_focal", return_value=(0.4, 0.5))
        bogus = to_file_uri(focal_endpoint_setup["video_dir"] + "/not-in-db.mp4", {})
        resp = client.post("/api/showcase/video/detect-focal", json={"path": bogus})
        assert resp.status_code == 404
        assert resp.json()["success"] is False
        spy.assert_not_called()

    def test_readonly_source_in_scope_allowed(self, client, focal_endpoint_setup, mocker):
        """99a-T1a：來源標 readonly 但 in-scope → 放行（200，正常跑偵測）。
        取代舊的「唯讀→403」行為——偵測不寫 DB，不需要可寫權限（D4/CD-7）。"""
        ro_config = {
            "gallery": {
                "directories": [{"path": focal_endpoint_setup["video_dir"],
                                 "readonly": True, "output_path": ""}],
                "path_mappings": {},
            },
        }
        _patch_db_and_config(mocker, focal_endpoint_setup, config=ro_config)
        spy = mocker.patch("web.routers.showcase.detect_focal", return_value=(0.4, 0.5))
        resp = client.post("/api/showcase/video/detect-focal",
                           json={"path": focal_endpoint_setup["video_uri"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        spy.assert_called_once()

    def test_out_of_scope_rejected(self, client, focal_endpoint_setup, mocker, tmp_path):
        """configured dir 不含影片所在夾 → scope 外 → 拒。"""
        other_dir = tmp_path / "elsewhere"
        other_dir.mkdir()
        oos_config = {
            "gallery": {
                "directories": [{"path": str(other_dir), "readonly": False, "output_path": ""}],
                "path_mappings": {},
            },
        }
        _patch_db_and_config(mocker, focal_endpoint_setup, config=oos_config)
        spy = mocker.patch("web.routers.showcase.detect_focal", return_value=(0.4, 0.5))
        resp = client.post("/api/showcase/video/detect-focal",
                           json={"path": focal_endpoint_setup["video_uri"]})
        assert resp.status_code == 403
        spy.assert_not_called()

    def test_cover_file_missing_fixed_string_no_crash(self, client, focal_endpoint_setup, mocker):
        """DB 有 cover_path 但檔案不存在 → 固定字串、不崩、不呼 detect_focal。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        spy = mocker.patch("web.routers.showcase.detect_focal", return_value=(0.4, 0.5))
        resp = client.post("/api/showcase/video/detect-focal",
                           json={"path": focal_endpoint_setup["video_no_cover_uri"]})
        assert resp.status_code == 400
        assert resp.json()["success"] is False
        assert resp.json()["error"]
        spy.assert_not_called()

    def test_no_face_returns_empty_string(self, client, focal_endpoint_setup, mocker):
        """detect_focal 回 None（無臉）→ auto_focal='' 回傳、不崩（99a-T1a：不再存回 DB）。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        mocker.patch("web.routers.showcase.detect_focal", return_value=None)
        resp = client.post("/api/showcase/video/detect-focal",
                           json={"path": focal_endpoint_setup["video_uri"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["auto_focal"] == ""


# ============ /video/focal mutator（99a-T1a）============

class TestManualFocalEndpoint:
    def test_valid_focal_atomic_write(self, client, focal_endpoint_setup, mocker):
        """成功後 auto_focal 與 crop_mode='manual' 同時反映在 DB（單一 UPDATE 原子寫）。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": "0.3,0.6"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        repo = VideoRepository(focal_endpoint_setup["db_path"])
        result = repo.get_by_path(focal_endpoint_setup["video_uri"])
        assert result.auto_focal == "0.3000,0.6000"   # 正規化（format_focal(parse_focal(...))）
        assert result.crop_mode == "manual"

    def test_path_not_in_db_404_no_write(self, client, focal_endpoint_setup, mocker, tmp_path):
        """path 不存在於 DB → 404（不是 500，不新建 row）。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        bogus = to_file_uri(str(tmp_path / "not-in-db.mp4"), {})
        resp = client.post("/api/showcase/video/focal",
                           json={"path": bogus, "focal": "0.3,0.6"})
        assert resp.status_code == 404
        assert resp.json()["success"] is False
        repo = VideoRepository(focal_endpoint_setup["db_path"])
        assert repo.get_by_path(bogus) is None

    def test_invalid_focal_format_400_db_untouched(self, client, focal_endpoint_setup, mocker):
        """非法 focal 格式 → 400 固定字串、DB 完全不碰（連 get_by_path 都不需呼叫，
        格式驗證在 scope 檢查之前）。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        spy = mocker.patch("web.routers.showcase.VideoRepository.get_by_path")
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": "abc"})
        assert resp.status_code == 400
        assert resp.json()["success"] is False
        assert resp.json()["error"]
        spy.assert_not_called()

    def test_invalid_focal_empty_string_400(self, client, focal_endpoint_setup, mocker):
        """空字串焦點 → 400（手動存的 focal 不可為空，不同於 detect 的「無臉」語意）。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": ""})
        assert resp.status_code == 400

    def test_invalid_focal_out_of_range_400(self, client, focal_endpoint_setup, mocker):
        """超出 [0,1] 範圍 → 400。"""
        _patch_db_and_config(mocker, focal_endpoint_setup)
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": "1.5,0.5"})
        assert resp.status_code == 400

    def test_out_of_scope_403_db_unchanged(self, client, focal_endpoint_setup, mocker, tmp_path):
        """path 存在但 out-of-scope（不在任何 configured dir 下）→ 403、DB 不變。

        mutation 驗證（Codex P1-1）：拔掉 scope guard 後 out-of-scope 也能寫入
        → 必須變 RED。"""
        other_dir = tmp_path / "elsewhere"
        other_dir.mkdir()
        oos_config = {
            "gallery": {
                "directories": [{"path": str(other_dir), "readonly": False, "output_path": ""}],
                "path_mappings": {},
            },
        }
        _patch_db_and_config(mocker, focal_endpoint_setup, config=oos_config)
        before = VideoRepository(focal_endpoint_setup["db_path"]).get_by_path(
            focal_endpoint_setup["video_uri"])
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": "0.3,0.6"})
        assert resp.status_code == 403
        assert resp.json()["success"] is False
        after = VideoRepository(focal_endpoint_setup["db_path"]).get_by_path(
            focal_endpoint_setup["video_uri"])
        assert after.auto_focal == before.auto_focal
        assert after.crop_mode == before.crop_mode

    def test_readonly_source_in_scope_allowed_write(self, client, focal_endpoint_setup, mocker):
        """path 存在、in-scope、來源標記 readonly → 仍放行寫入（D4/CD-7，刻意與 98b
        舊行為分歧：唯讀不擋手動存）。"""
        ro_config = {
            "gallery": {
                "directories": [{"path": focal_endpoint_setup["video_dir"],
                                 "readonly": True, "output_path": ""}],
                "path_mappings": {},
            },
        }
        _patch_db_and_config(mocker, focal_endpoint_setup, config=ro_config)
        resp = client.post("/api/showcase/video/focal",
                           json={"path": focal_endpoint_setup["video_uri"], "focal": "0.3,0.6"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        repo = VideoRepository(focal_endpoint_setup["db_path"])
        result = repo.get_by_path(focal_endpoint_setup["video_uri"])
        assert result.auto_focal == "0.3000,0.6000"
        assert result.crop_mode == "manual"
