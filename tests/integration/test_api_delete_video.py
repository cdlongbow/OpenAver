"""
test_api_delete_video.py — DELETE /api/showcase/video 整合測試（71-T7）

核心安全契約：DELETE 只刪 DB row + 衍生縮圖 WebP，**絕不 unlink 影片檔或原始封面檔**。

測試用真 temp DB + 真 temp 影片檔 + 真 temp 封面檔 + 真 temp thumb dir，
DELETE 後明確斷言：
- DB row 消失（repo.get_by_path → None）
- 影片檔 & 封面檔仍在磁碟（os.path.exists True）—— 最重要的斷言
- 預先 generate 的 thumb webp 被 invalidate 砍掉
- 未知 path → {"deleted": 0} no-op，不拋、不影響其他 row
"""

import os
import pytest
from pathlib import Path
from PIL import Image
from core.database import init_db, VideoRepository, Video
from core.path_utils import to_file_uri
from core import thumbnail_cache


@pytest.fixture
def delete_setup(tmp_path):
    """真 temp DB + 真影片檔 + 真封面檔；thumb dir = db.parent/thumb（thumbnail_cache 推導規則）。

    回傳 dict：{db_path, vid_uri, vid_fs, cover_fs, vid2_uri}
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    # 真實影片檔 + 封面檔（內容隨意，存在性才是重點）
    vid_fs = video_dir / "video1.mp4"
    vid_fs.write_bytes(b"\x00fake-mp4-bytes\x00")
    cover_fs = video_dir / "video1.jpg"
    # 真實可解碼 JPG（thumbnail generate 需要真圖；存在性才是核心斷言目標）
    Image.new("RGB", (200, 300), (180, 120, 90)).save(cover_fs, "JPEG")

    vid_uri = to_file_uri(str(vid_fs), {})
    cover_uri = to_file_uri(str(cover_fs), {})
    vid2_uri = to_file_uri(str(video_dir / "video2.mp4"), {})

    db_path = tmp_path / "showcase_test.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=vid_uri,
            number="SONE-001",
            title="To Be Deleted",
            cover_path=cover_uri,
            size_bytes=12,
            mtime=1700000000.0,
        ),
        Video(
            path=vid2_uri,
            number="SONE-002",
            title="Bystander",
            size_bytes=0,
            mtime=0.0,
        ),
    ])

    return {
        "db_path": db_path,
        "vid_uri": vid_uri,
        "vid_fs": vid_fs,
        "cover_fs": cover_fs,
        "vid2_uri": vid2_uri,
    }


def _patch_db_path(mocker, db_path):
    """showcase endpoint 與 thumbnail_cache 都從 get_db_path 解析（後者推導 thumb dir）。"""
    mocker.patch("web.routers.showcase.get_db_path", return_value=db_path)
    mocker.patch("core.thumbnail_cache.get_db_path", return_value=db_path)


class TestDeleteVideoRemovesDbRow:
    def test_delete_removes_db_row(self, client, delete_setup, mocker):
        """DELETE 後 repo.get_by_path → None（DB row 消失）。"""
        _patch_db_path(mocker, delete_setup["db_path"])

        resp = client.delete(
            "/api/showcase/video", params={"path": delete_setup["vid_uri"]}
        )

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}

        repo = VideoRepository(delete_setup["db_path"])
        assert repo.get_by_path(delete_setup["vid_uri"]) is None

    def test_delete_does_not_affect_other_rows(self, client, delete_setup, mocker):
        """只刪目標 row，其他 row 不受影響。"""
        _patch_db_path(mocker, delete_setup["db_path"])

        client.delete("/api/showcase/video", params={"path": delete_setup["vid_uri"]})

        repo = VideoRepository(delete_setup["db_path"])
        assert repo.get_by_path(delete_setup["vid2_uri"]) is not None


class TestDeleteVideoNeverUnlinksFiles:
    """【核心安全】DELETE 絕不刪磁碟上的影片檔或原始封面檔。"""

    def test_video_file_still_exists(self, client, delete_setup, mocker):
        _patch_db_path(mocker, delete_setup["db_path"])

        client.delete("/api/showcase/video", params={"path": delete_setup["vid_uri"]})

        assert os.path.exists(delete_setup["vid_fs"]), \
            "DELETE 不得 unlink 影片檔"

    def test_cover_file_still_exists(self, client, delete_setup, mocker):
        _patch_db_path(mocker, delete_setup["db_path"])

        client.delete("/api/showcase/video", params={"path": delete_setup["vid_uri"]})

        assert os.path.exists(delete_setup["cover_fs"]), \
            "DELETE 不得 unlink 原始封面檔"


class TestDeleteVideoInvalidatesThumb:
    def test_pregenerated_thumb_removed_after_delete(self, client, delete_setup, mocker):
        """預先 generate 的縮圖 WebP，DELETE 後被 invalidate 砍掉。"""
        _patch_db_path(mocker, delete_setup["db_path"])

        # 預先 generate 一個真 thumb（thumb dir = db.parent/thumb，已 patch get_db_path）
        thumb = thumbnail_cache.get_or_create(
            delete_setup["vid_uri"], str(delete_setup["cover_fs"])
        )
        assert thumb is not None and thumb.exists(), "前置：thumb 應已生成"

        client.delete("/api/showcase/video", params={"path": delete_setup["vid_uri"]})

        assert not thumb.exists(), "DELETE 後對應 thumb webp 應被 invalidate 砍掉"


class TestDeleteVideoUnknownPath:
    def test_unknown_path_is_noop(self, client, delete_setup, mocker):
        """未知 path → {"deleted": 0}，不拋、不影響其他 row。"""
        _patch_db_path(mocker, delete_setup["db_path"])

        unknown = to_file_uri(str(Path(delete_setup["vid_fs"]).parent / "ghost.mp4"), {})
        resp = client.delete("/api/showcase/video", params={"path": unknown})

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 0}

        repo = VideoRepository(delete_setup["db_path"])
        assert repo.get_by_path(delete_setup["vid_uri"]) is not None
        assert repo.get_by_path(delete_setup["vid2_uri"]) is not None


# ============ feature/122 T4：整組刪除 / CD-122-10 反例 / 畸形 path fail-safe ============


@pytest.fixture
def multipart_delete_setup(tmp_path):
    """同資料夾 ABC-123-cd1.mp4 + ABC-123-cd2.mp4（AC-12 整組刪除）。

    獨立 fixture，不复用 delete_setup：那邊的 vid2 語意是「不相干的 bystander，不該被刪」，
    與「同一組的 part-2，應該一起被刪」相反。子目錄 multipart/ 與 mixed/ 分開，避免兩種
    分組情境互相干擾。
    """
    video_dir = tmp_path / "multipart"
    video_dir.mkdir()

    cd1_fs = video_dir / "ABC-123-cd1.mp4"
    cd2_fs = video_dir / "ABC-123-cd2.mp4"
    cd1_fs.write_bytes(b"\x00cd1-bytes\x00")
    cd2_fs.write_bytes(b"\x00cd2-bytes\x00")

    cd1_uri = to_file_uri(str(cd1_fs), {})
    cd2_uri = to_file_uri(str(cd2_fs), {})

    db_path = tmp_path / "multipart_delete.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=cd1_uri,
            number="ABC-123",
            title="Part 1",
            size_bytes=12,
            mtime=1700000000.0,
        ),
        Video(
            path=cd2_uri,
            number="ABC-123",
            title="Part 2",
            size_bytes=12,
            mtime=1700000000.0,
        ),
    ])

    return {
        "db_path": db_path,
        "cd1_uri": cd1_uri,
        "cd2_uri": cd2_uri,
        "cd1_fs": cd1_fs,
        "cd2_fs": cd2_fs,
    }


@pytest.fixture
def mixed_nontoken_delete_setup(tmp_path):
    """同資料夾 ABC-123.mp4（無 token）+ ABC-123-cd2.mp4（AC-16 誤併反例）。"""
    video_dir = tmp_path / "mixed"
    video_dir.mkdir()

    bare_fs = video_dir / "ABC-123.mp4"
    cd2_fs = video_dir / "ABC-123-cd2.mp4"
    bare_fs.write_bytes(b"\x00bare-bytes\x00")
    cd2_fs.write_bytes(b"\x00cd2-bytes\x00")

    bare_uri = to_file_uri(str(bare_fs), {})
    cd2_uri = to_file_uri(str(cd2_fs), {})

    db_path = tmp_path / "mixed_nontoken_delete.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=bare_uri,
            number="ABC-123",
            title="No Token",
            size_bytes=12,
            mtime=1700000000.0,
        ),
        Video(
            path=cd2_uri,
            number="ABC-123",
            title="Has Token",
            size_bytes=12,
            mtime=1700000000.0,
        ),
    ])

    return {
        "db_path": db_path,
        "bare_uri": bare_uri,
        "cd2_uri": cd2_uri,
        "bare_fs": bare_fs,
        "cd2_fs": cd2_fs,
    }


class TestAC12DeleteRemovesWholeGroup:
    def test_delete_part1_removes_both_rows_and_invalidates_each_member(
        self, client, multipart_delete_setup, mocker
    ):
        """AC-12：刪 cd1 → DB 兩列都消失，thumbnail_cache.invalidate 各呼叫一次。"""
        _patch_db_path(mocker, multipart_delete_setup["db_path"])
        inv = mocker.spy(thumbnail_cache, "invalidate")

        resp = client.delete(
            "/api/showcase/video",
            params={"path": multipart_delete_setup["cd1_uri"]},
        )

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 2}

        repo = VideoRepository(multipart_delete_setup["db_path"])
        assert repo.get_by_path(multipart_delete_setup["cd1_uri"]) is None
        assert repo.get_by_path(multipart_delete_setup["cd2_uri"]) is None

        assert inv.call_count == 2
        called_paths = [call.args[0] for call in inv.call_args_list]
        assert multipart_delete_setup["cd1_uri"] in called_paths
        assert multipart_delete_setup["cd2_uri"] in called_paths


class TestAC16DeleteDoesNotMergeNoToken:
    def test_delete_nontoken_leaves_cd2_row(self, client, mixed_nontoken_delete_setup, mocker):
        """AC-16：同資料夾無 token 片 + 帶 token 片，刪無 token 那張只移除一列。"""
        _patch_db_path(mocker, mixed_nontoken_delete_setup["db_path"])
        inv = mocker.spy(thumbnail_cache, "invalidate")

        resp = client.delete(
            "/api/showcase/video",
            params={"path": mixed_nontoken_delete_setup["bare_uri"]},
        )

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}

        repo = VideoRepository(mixed_nontoken_delete_setup["db_path"])
        assert repo.get_by_path(mixed_nontoken_delete_setup["bare_uri"]) is None
        assert repo.get_by_path(mixed_nontoken_delete_setup["cd2_uri"]) is not None

        assert inv.call_count == 1
        assert inv.call_args.args[0] == mixed_nontoken_delete_setup["bare_uri"]


class TestDeleteVideoMalformedPathFailsafe:
    def test_group_resolve_exception_falls_back_to_single_delete(self, client, delete_setup, mocker):
        """分組反解**拋例外**時 fail-safe 退回單路徑刪除，不 500。

        為什麼要 patch 才測得到：`uri_to_fs_path()` 對畸形輸入是寬容的（原樣回傳，
        不拋），所以下面那支 malformed-path 測試走的是「反解不到組 → group is None」
        那條路，**不會**碰到 try/except。真正會拋的是 `load_config()`（使用者手改壞
        config.json 就會），那時整組刪除若沒有 fail-safe，使用者按「從收藏移除」會
        收到 500、卡片不消失、也不知道發生什麼事。

        這支測試對 fail-safe 是 mutation-sensitive 的：把 `except Exception` 收窄
        （例如改成 `except ZeroDivisionError`）這支就會紅。
        """
        _patch_db_path(mocker, delete_setup["db_path"])
        mocker.patch(
            "web.routers.showcase.load_config",
            side_effect=RuntimeError("config.json 壞了"),
        )
        inv = mocker.patch("core.thumbnail_cache.invalidate")

        resp = client.delete(
            "/api/showcase/video", params={"path": delete_setup["vid_uri"]}
        )

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}

        repo = VideoRepository(delete_setup["db_path"])
        assert repo.get_by_path(delete_setup["vid_uri"]) is None
        assert inv.call_count == 1
        assert inv.call_args.args[0] == delete_setup["vid_uri"]

    def test_malformed_path_returns_200_deleted_zero(self, client, delete_setup, mocker):
        """畸形 path → 200 + {"deleted": 0}（走 group is None 那條路，非例外路徑）。"""
        _patch_db_path(mocker, delete_setup["db_path"])

        resp = client.delete("/api/showcase/video", params={"path": "not-a-uri"})

        assert resp.status_code == 200
        assert resp.json() == {"deleted": 0}

        repo = VideoRepository(delete_setup["db_path"])
        assert repo.get_by_path(delete_setup["vid_uri"]) is not None
        assert repo.get_by_path(delete_setup["vid2_uri"]) is not None
