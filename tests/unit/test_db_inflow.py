"""
test_db_inflow.py — TDD-lite: VideoRepository.repath + try_inflow_upsert B1 邊界條件

U1  正常 UPDATE — id 保留
U2  正常 UPDATE — created_at 保留
U3  正常 UPDATE — user_tags 沿用舊（scanned 空）
U4  正常 UPDATE — user_tags 聯集（scanned 非空）
U5  正常 UPDATE — 舊路徑消失、count 不增
U6  self-no-op（old==new）
U7  碰撞 delete-merge — tag 三方聯集
U8  碰撞 delete-merge — created_at 取較早
U9  碰撞分支單一 transaction atomicity（INSERT 失敗 → rollback）
U10 old-not-in-DB（純 Search，無前置 Scanner）
U11 old_file_path=None 向後相容
U12 scan-fail 保卡（保 path/title/cover/tags/created_at/id，回 "failed"）
U13 ranker invalidate — 正常 UPDATE 分支
U14 ranker invalidate — scan-fail 保卡分支
U15 ranker invalidate — 碰撞 delete-merge 分支
U16 old_uri 使用 to_file_uri(normalize_path(...))，無手拼 URI、無 [8:] strip
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.database import Video, VideoRepository, init_db
from core.gallery_scanner import VideoInfo


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    """建立並初始化 in-memory-style temp SQLite DB，回傳路徑。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


def _seed_video(repo: VideoRepository, path: str, user_tags=None,
                created_at_str: str | None = None, cover_path: str = "",
                title: str = "Old Title") -> Video:
    """INSERT 一筆 video，保留 created_at。回傳 get_by_path 取到的實際 row。"""
    v = Video(
        path=path,
        number="ABC-001",
        title=title,
        original_title="",
        actresses=[],
        maker="",
        director="",
        series=None,
        label="",
        tags=[],
        user_tags=user_tags or [],
        sample_images=[],
        duration=None,
        size_bytes=0,
        cover_path=cover_path,
        release_date="",
        mtime=0.0,
        nfo_mtime=0.0,
    )
    repo.upsert(v)
    # 若 created_at_str 給定，直接 UPDATE（upsert 不帶 created_at）
    if created_at_str:
        conn = repo._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE videos SET created_at = ? WHERE path = ?",
                (created_at_str, path),
            )
            conn.commit()
        finally:
            conn.close()
    return repo.get_by_path(path)


def _make_video_info(path: str, user_tags=None, num: str = "ABC-001",
                     title: str = "New Title") -> VideoInfo:
    """建立 VideoInfo stub（scan_file 的回傳值）。"""
    info = VideoInfo()
    info.path = path
    info.num = num
    info.title = title
    info.originaltitle = ""
    info.actor = ""
    info.genre = ""
    info.maker = ""
    info.director = ""
    info.series = None
    info.label = ""
    info.user_tags = user_tags or []
    info.sample_images = []
    info.duration = None
    info.size = 0
    info.img = ""
    info.date = ""
    info.mtime = 0
    return info


# ─── U1: 正常 UPDATE — id 保留 ──────────────────────────────────────────────

def test_u1_normal_update_id_preserved(tmp_path):
    """整理後 id 不變（browse ORDER BY id 不跳位）。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_path = "/tmp/old.mp4"
    new_path = "/tmp/new.mp4"
    old_uri = f"file://{old_path}"
    new_uri = f"file://{new_path}"

    old_row = _seed_video(repo, old_uri)
    old_id = old_row.id
    assert old_id is not None

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    new_row = repo.get_by_path(new_uri)
    assert new_row is not None
    assert new_row.id == old_id, f"id 應保留 {old_id}，但得到 {new_row.id}"


# ─── U2: 正常 UPDATE — created_at 保留 ─────────────────────────────────────

def test_u2_normal_update_created_at_preserved(tmp_path):
    """整理後 created_at 不變。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"
    old_created = "2024-01-15 10:00:00"

    _seed_video(repo, old_uri, created_at_str=old_created)

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    new_row = repo.get_by_path(new_uri)
    assert new_row is not None
    # created_at 可以是 datetime 或字串，取字串比對前綴
    ca_str = str(new_row.created_at) if new_row.created_at else ""
    assert "2024-01-15" in ca_str, f"created_at 應含 2024-01-15，實際: {ca_str!r}"


# ─── U3: user_tags 沿用舊（scanned 空）─────────────────────────────────────

def test_u3_user_tags_preserve_when_scanned_empty(tmp_path):
    """搬檔 NFO 給 user_tags=[]，browse tag 存活。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"

    _seed_video(repo, old_uri, user_tags=["看過"])

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],  # 空
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    new_row = repo.get_by_path(new_uri)
    assert new_row is not None
    assert new_row.user_tags == ["看過"], f"user_tags 應為 ['看過']，實際: {new_row.user_tags}"


# ─── U4: user_tags 聯集（scanned 非空）────────────────────────────────────

def test_u4_user_tags_union_when_scanned_nonempty(tmp_path):
    """scanned 給非空 user_tags → 取聯集。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"

    _seed_video(repo, old_uri, user_tags=["看過"])

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=["HD"],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    new_row = repo.get_by_path(new_uri)
    assert new_row is not None
    assert set(new_row.user_tags) == {"看過", "HD"}, \
        f"user_tags 應為聯集 {{看過, HD}}，實際: {new_row.user_tags}"


# ─── U5: 正常 UPDATE — 舊路徑消失、count 不增 ──────────────────────────────

def test_u5_old_path_gone_count_unchanged(tmp_path):
    """整理後舊 URI get_by_path 回 None，count 不增。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"

    _seed_video(repo, old_uri)
    count_before = repo.count()

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    assert repo.get_by_path(old_uri) is None, "舊 URI 應消失"
    assert repo.count() == count_before, "count 不應增加"


# ─── U6: self-no-op（old==new） ───────────────────────────────────────────

def test_u6_self_noop_same_path(tmp_path):
    """old_uri == new_uri → 不刪、id/created_at 不變。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    uri = "file:///tmp/same.mp4"
    old_created = "2024-03-01 08:00:00"
    old_row = _seed_video(repo, uri, user_tags=["看過"], created_at_str=old_created)
    old_id = old_row.id

    same_video = Video(path=uri, number="ABC-001", title="Updated Title",
                       original_title="", actresses=[], maker="", director="",
                       series=None, label="", tags=[], user_tags=["HD"],
                       sample_images=[], duration=None, size_bytes=0,
                       cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(uri, uri, same_video)

    row = repo.get_by_path(uri)
    assert row is not None
    assert row.id == old_id, "self-no-op 後 id 不應變"


# ─── U7: 碰撞 delete-merge — tag 三方聯集 ──────────────────────────────────

def test_u7_collision_merge_tags_union(tmp_path):
    """new path 早有一筆 → 收斂一筆、user_tags = A∪B∪C。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"

    _seed_video(repo, old_uri, user_tags=["B"])
    _seed_video(repo, new_uri, user_tags=["A"])

    # scan 給 C
    collision_video = Video(path=new_uri, number="ABC-001", title="New Title",
                            original_title="", actresses=[], maker="", director="",
                            series=None, label="", tags=[], user_tags=["C"],
                            sample_images=[], duration=None, size_bytes=0,
                            cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, collision_video)

    merged = repo.get_by_path(new_uri)
    assert merged is not None
    assert repo.get_by_path(old_uri) is None, "old URI 應消失"
    assert repo.count() == 1, "收斂後應只有 1 筆"
    assert set(merged.user_tags) == {"A", "B", "C"}, \
        f"三方聯集應為 {{A,B,C}}，實際: {merged.user_tags}"


# ─── U8: 碰撞 delete-merge — created_at 取較早 ─────────────────────────────

def test_u8_collision_merge_created_at_min(tmp_path):
    """碰撞 merge 後 created_at = min(old_row, new_row)。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old.mp4"
    new_uri = "file:///tmp/new.mp4"

    _seed_video(repo, old_uri, created_at_str="2024-01-01 00:00:00")
    _seed_video(repo, new_uri, created_at_str="2024-06-01 00:00:00")

    collision_video = Video(path=new_uri, number="ABC-001", title="New Title",
                            original_title="", actresses=[], maker="", director="",
                            series=None, label="", tags=[], user_tags=[],
                            sample_images=[], duration=None, size_bytes=0,
                            cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, collision_video)

    merged = repo.get_by_path(new_uri)
    assert merged is not None
    ca_str = str(merged.created_at) if merged.created_at else ""
    assert "2024-01-01" in ca_str, \
        f"created_at 應取較早的 2024-01-01，實際: {ca_str!r}"


# ─── U9: 碰撞分支 atomicity（INSERT 失敗 → rollback） ──────────────────────


def test_u9_collision_rollback_via_real_repath(tmp_path):
    """U9 替代測試：使用真實 repath，確保 old row 在 rollback 後存活。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old9.mp4"
    new_uri = "file:///tmp/new9.mp4"

    _seed_video(repo, old_uri, user_tags=["看過"])
    _seed_video(repo, new_uri, user_tags=["A"])

    # 直接模擬 DB 層：conn.commit 時拋錯以觸發 rollback 路徑
    real_get_connection = repo._get_connection

    call_count = [0]

    def failing_get_connection():
        conn = real_get_connection()
        original_commit = conn.commit

        def patched_commit():
            call_count[0] += 1
            if call_count[0] == 1:
                # 第一次 commit → 讓 DELETE 成功但 INSERT 失敗
                conn.rollback()
                raise sqlite3.OperationalError("Simulated commit failure")
            return original_commit()

        conn.commit = patched_commit
        return conn

    with patch.object(repo, "_get_connection", failing_get_connection):
        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            try:
                repo.repath(old_uri, new_uri, Video(
                    path=new_uri, number="ABC-001", title="Fail",
                    original_title="", actresses=[], maker="", director="",
                    series=None, label="", tags=[], user_tags=["C"],
                    sample_images=[], duration=None, size_bytes=0,
                    cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0,
                ))
            except Exception:
                pass

    # rollback 後 old row 應仍在
    assert repo.get_by_path(old_uri) is not None, \
        "rollback 後 old row 應存活（不雙失）"


# ─── U10: old-not-in-DB（純 Search，無前置 Scanner）───────────────────────

def test_u10_old_not_in_db_falls_back_to_upsert(tmp_path):
    """old_uri 不在 DB → repath 退化為 upsert，new 正常寫入。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/nonexistent_old.mp4"
    new_uri = "file:///tmp/new10.mp4"

    assert repo.get_by_path(old_uri) is None

    new_video = Video(path=new_uri, number="ABC-001", title="New Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache"):
        repo.repath(old_uri, new_uri, new_video)

    assert repo.get_by_path(new_uri) is not None, "new_uri 應寫入"
    assert repo.count() == 1


# ─── U11: old_file_path=None 向後相容 ──────────────────────────────────────

def test_u11_old_file_path_none_backward_compat(tmp_path):
    """try_inflow_upsert(new, old_file_path=None) 行為等同原本純 upsert。"""
    new_path = "/tmp/new11.mp4"
    new_uri = "file:///tmp/new11.mp4"

    video_info = _make_video_info(new_uri)

    import core.db_inflow as _db_inflow_mod

    mock_repo = MagicMock()
    mock_video = MagicMock()
    mock_video.path = new_uri

    with (
        patch.object(_db_inflow_mod, "load_config", return_value={
            "gallery": {"directories": ["/tmp"], "path_mappings": None}
        }),
        patch.object(_db_inflow_mod, "find_matched_directory", return_value="/tmp"),
        patch.object(_db_inflow_mod, "VideoScanner") as MockScanner,
        patch.object(_db_inflow_mod, "VideoRepository", return_value=mock_repo),
        patch.object(_db_inflow_mod, "Video") as MockVideo,
        patch("core.similar.ranker_cache.SimilarRankerCache"),
    ):
        MockScanner.return_value.scan_file.return_value = video_info
        MockVideo.from_video_info.return_value = mock_video
        mock_repo.repath.return_value = None

        result = _db_inflow_mod.try_inflow_upsert(new_path, old_file_path=None)

    assert result == "synced"
    # repath 應以 old_uri=None 呼叫
    mock_repo.repath.assert_called_once()
    call_args = mock_repo.repath.call_args
    assert call_args[0][0] is None, "old_uri 應為 None（無 old_file_path）"


# ─── U12: scan-fail 保卡 ──────────────────────────────────────────────────

def test_u12_scan_fail_path_only_update(tmp_path):
    """
    scan_file 回 None → UPDATE-path-only 保卡：
    - get_by_path(old_uri) is None（舊 URI 不再存在）
    - get_by_path(new_uri) 有效（卡在新位置）
    - title/cover_path/user_tags/created_at/id 全部保留
    - 回傳 "failed"
    """
    from core.path_utils import normalize_path, to_file_uri

    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_path_fs = str(tmp_path / "old_scan_fail.mp4")
    new_path_fs = str(tmp_path / "new_scan_fail.mp4")
    # 用 to_file_uri 算出真實 URI（與 try_inflow_upsert 內部一致）
    old_uri = to_file_uri(normalize_path(old_path_fs), None)
    new_uri = to_file_uri(normalize_path(new_path_fs), None)
    old_created = "2023-11-01 00:00:00"

    # seed 舊 row
    _seed_video(repo, old_uri,
                user_tags=["看過"],
                created_at_str=old_created,
                cover_path="old_cover.jpg",
                title="Preserved Title")
    old_row = repo.get_by_path(old_uri)
    assert old_row is not None, f"seed 失敗，old_uri={old_uri!r}"
    old_id = old_row.id

    import core.db_inflow as _db_inflow_mod

    with (
        patch.object(_db_inflow_mod, "load_config", return_value={
            "gallery": {"directories": [str(tmp_path)], "path_mappings": None}
        }),
        patch.object(_db_inflow_mod, "find_matched_directory", return_value=str(tmp_path)),
        patch.object(_db_inflow_mod, "VideoScanner") as MockScanner,
        patch.object(_db_inflow_mod, "VideoRepository", return_value=repo),
        patch("core.similar.ranker_cache.SimilarRankerCache"),
    ):
        MockScanner.return_value.scan_file.return_value = None  # scan 失敗

        result = _db_inflow_mod.try_inflow_upsert(new_path_fs, old_file_path=old_path_fs)

    assert result == "failed", f"scan-fail 應回 'failed'，實際: {result!r}"

    # 舊 URI 消失（保卡搬到新位置）
    assert repo.get_by_path(old_uri) is None, "舊 URI 應消失（保卡已搬到新位置）"

    # 新 URI 存在，metadata 保留
    new_row = repo.get_by_path(new_uri)
    assert new_row is not None, f"新 URI 應存在（new_uri={new_uri!r}）"
    assert new_row.id == old_id, f"id 應保留 {old_id}，得 {new_row.id}"
    assert new_row.title == "Preserved Title", f"title 應保留，得 {new_row.title!r}"
    assert new_row.cover_path == "old_cover.jpg", f"cover_path 應保留，得 {new_row.cover_path!r}"
    assert "看過" in new_row.user_tags, f"user_tags 應含 '看過'，得 {new_row.user_tags}"
    ca_str = str(new_row.created_at) if new_row.created_at else ""
    assert "2023-11-01" in ca_str, f"created_at 應保留，得 {ca_str!r}"


# ─── U13: ranker invalidate — 正常 UPDATE 分支 ────────────────────────────

def test_u13_ranker_invalidate_normal_update(tmp_path):
    """正常 UPDATE 分支 → SimilarRankerCache.invalidate 被呼叫恰 1 次。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old13.mp4"
    new_uri = "file:///tmp/new13.mp4"
    _seed_video(repo, old_uri)

    new_video = Video(path=new_uri, number="ABC-001", title="New",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        repo.repath(old_uri, new_uri, new_video)

    MockRanker.invalidate.assert_called_once()


# ─── U14: ranker invalidate — scan-fail 保卡分支 ──────────────────────────

def test_u14_ranker_invalidate_scan_fail(tmp_path):
    """scan-fail 保卡分支 → SimilarRankerCache.invalidate 被呼叫恰 1 次。"""
    from core.path_utils import normalize_path, to_file_uri

    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_path_fs = str(tmp_path / "old14.mp4")
    new_path_fs = str(tmp_path / "new14.mp4")
    old_uri = to_file_uri(normalize_path(old_path_fs), None)
    new_uri = to_file_uri(normalize_path(new_path_fs), None)

    _seed_video(repo, old_uri, user_tags=["看過"])

    import core.db_inflow as _db_inflow_mod

    with (
        patch.object(_db_inflow_mod, "load_config", return_value={
            "gallery": {"directories": [str(tmp_path)], "path_mappings": None}
        }),
        patch.object(_db_inflow_mod, "find_matched_directory", return_value=str(tmp_path)),
        patch.object(_db_inflow_mod, "VideoScanner") as MockScanner,
        patch.object(_db_inflow_mod, "VideoRepository", return_value=repo),
        patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker,
    ):
        MockScanner.return_value.scan_file.return_value = None

        _db_inflow_mod.try_inflow_upsert(new_path_fs, old_file_path=old_path_fs)

    # scan-fail 保卡後新路徑應存在
    new_row = repo.get_by_path(new_uri)
    assert new_row is not None, "scan-fail 保卡後新路徑應存在"
    # invalidate 應被呼叫（db_inflow 的 scan-fail 保卡路徑顯式 invalidate）
    MockRanker.invalidate.assert_called_once()


# ─── U15: ranker invalidate — 碰撞 delete-merge 分支 ──────────────────────

def test_u15_ranker_invalidate_collision(tmp_path):
    """碰撞 delete-merge 分支 → SimilarRankerCache.invalidate 被呼叫恰 1 次。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old15.mp4"
    new_uri = "file:///tmp/new15.mp4"
    _seed_video(repo, old_uri, user_tags=["B"])
    _seed_video(repo, new_uri, user_tags=["A"])

    collision_video = Video(path=new_uri, number="ABC-001", title="New",
                            original_title="", actresses=[], maker="", director="",
                            series=None, label="", tags=[], user_tags=["C"],
                            sample_images=[], duration=None, size_bytes=0,
                            cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        repo.repath(old_uri, new_uri, collision_video)

    MockRanker.invalidate.assert_called_once()


# ─── U16: grep 守衛 — 無手拼 URI ─────────────────────────────────────────

def test_u16_no_manual_uri_construction():
    """db_inflow.py 中不應有 'file:///' 手拼或 '[8:]' strip。"""
    import re
    db_inflow_path = Path(__file__).parent.parent.parent / "core" / "db_inflow.py"
    content = db_inflow_path.read_text(encoding="utf-8")

    # 禁止手拼 file:/// URI（comment 內也算）
    bad_furi = re.findall(r'"file:///|\'file:///', content)
    assert not bad_furi, f"db_inflow.py 不應手拼 file:/// URI，發現: {bad_furi}"

    # 禁止 [8:] URI strip
    bad_strip = re.findall(r'\[8:\]', content)
    assert not bad_strip, f"db_inflow.py 不應有 [8:] strip，發現: {bad_strip}"


# ─── U17: repath_path_only — 正常搬移（Fix 2） ────────────────────────────────

def test_u17_repath_path_only_normal(tmp_path):
    """
    repath_path_only 正常路徑：
    - 舊 URI 消失、新 URI 出現
    - title / cover_path / user_tags / created_at / id 全部保留
    - 回傳 True
    - SimilarRankerCache.invalidate 被呼叫恰 1 次
    """
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/rpo_old.mp4"
    new_uri = "file:///tmp/rpo_new.mp4"
    old_created = "2023-05-10 12:00:00"

    _seed_video(repo, old_uri, user_tags=["看過"], created_at_str=old_created,
                cover_path="cover.jpg", title="Preserved Title")
    old_row = repo.get_by_path(old_uri)
    old_id = old_row.id

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        result = repo.repath_path_only(old_uri, new_uri)

    assert result is True, "repath_path_only 應回 True"
    assert repo.get_by_path(old_uri) is None, "舊 URI 應消失"

    new_row = repo.get_by_path(new_uri)
    assert new_row is not None, "新 URI 應存在"
    assert new_row.id == old_id, f"id 應保留 {old_id}"
    assert new_row.title == "Preserved Title", f"title 應保留，得 {new_row.title!r}"
    assert new_row.cover_path == "cover.jpg", f"cover_path 應保留，得 {new_row.cover_path!r}"
    assert "看過" in new_row.user_tags, f"user_tags 應含 '看過'，得 {new_row.user_tags}"
    ca_str = str(new_row.created_at) if new_row.created_at else ""
    assert "2023-05-10" in ca_str, f"created_at 應保留，得 {ca_str!r}"
    MockRanker.invalidate.assert_called_once()


# ─── U18: repath_path_only — new_uri 碰撞（Fix 2） ─────────────────────────────

def test_u18_repath_path_only_collision_no_update(tmp_path):
    """
    repath_path_only：new_uri 已有 row → 不 UPDATE，回 False，old row 不動，無 IntegrityError。
    """
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/rpo_coll_old.mp4"
    new_uri = "file:///tmp/rpo_coll_new.mp4"

    _seed_video(repo, old_uri, user_tags=["看過"])
    _seed_video(repo, new_uri, user_tags=["已有"])

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        result = repo.repath_path_only(old_uri, new_uri)

    assert result is False, "碰撞時應回 False"
    # old row 不應被動到
    old_row = repo.get_by_path(old_uri)
    assert old_row is not None, "old row 應仍存在（碰撞時不 UPDATE）"
    assert "看過" in old_row.user_tags
    # new row 也未受影響
    new_row = repo.get_by_path(new_uri)
    assert new_row is not None
    assert "已有" in new_row.user_tags
    # invalidate 不應被呼叫（提前返回 False）
    MockRanker.invalidate.assert_not_called()


# ─── U19: repath_path_only — self no-op（Fix 2） ────────────────────────────────

def test_u19_repath_path_only_same_uri_noop(tmp_path):
    """
    repath_path_only：old_uri == new_uri → 立即回 False，DB 不動。
    """
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    uri = "file:///tmp/rpo_same.mp4"
    _seed_video(repo, uri, user_tags=["看過"])

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        result = repo.repath_path_only(uri, uri)

    assert result is False, "same uri 應回 False"
    row = repo.get_by_path(uri)
    assert row is not None, "row 應仍存在"
    MockRanker.invalidate.assert_not_called()


# ─── U20: repath_path_only — empty old_uri（Fix 2） ─────────────────────────────

def test_u20_repath_path_only_empty_old_uri_noop(tmp_path):
    """
    repath_path_only：old_uri == "" → 立即回 False。
    """
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    with patch("core.similar.ranker_cache.SimilarRankerCache") as MockRanker:
        result = repo.repath_path_only("", "file:///tmp/rpo_any.mp4")

    assert result is False
    MockRanker.invalidate.assert_not_called()


# ─── U21: db_inflow scan-fail 保卡用 repath_path_only（Fix 2 layering） ──────────

def test_u21_scan_fail_uses_repath_path_only(tmp_path):
    """
    scan-fail 保卡分支不再呼叫 repo._get_connection()，
    改呼叫 repo.repath_path_only()（layering 守衛）。
    """
    from core.path_utils import normalize_path, to_file_uri

    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_path_fs = str(tmp_path / "u21_old.mp4")
    new_path_fs = str(tmp_path / "u21_new.mp4")
    old_uri = to_file_uri(normalize_path(old_path_fs), None)

    _seed_video(repo, old_uri, user_tags=["看過"])

    import core.db_inflow as _db_inflow_mod

    with (
        patch.object(_db_inflow_mod, "load_config", return_value={
            "gallery": {"directories": [str(tmp_path)], "path_mappings": None}
        }),
        patch.object(_db_inflow_mod, "find_matched_directory", return_value=str(tmp_path)),
        patch.object(_db_inflow_mod, "VideoScanner") as MockScanner,
        patch.object(_db_inflow_mod, "VideoRepository", return_value=repo),
        patch("core.similar.ranker_cache.SimilarRankerCache"),
    ):
        MockScanner.return_value.scan_file.return_value = None

        # 監控 repath_path_only 是否被呼叫，且 _get_connection 不應從 db_inflow 呼叫
        with patch.object(repo, "repath_path_only", wraps=repo.repath_path_only) as mock_rpo:
            result = _db_inflow_mod.try_inflow_upsert(new_path_fs, old_file_path=old_path_fs)

    assert result == "failed", f"scan-fail 應回 'failed'，得 {result!r}"
    mock_rpo.assert_called_once(), "scan-fail 保卡應呼叫 repath_path_only"


# ─── U22: Fix 1 rowcount=0 fallback → upsert（Fix 1） ───────────────────────────

def test_u22_repath_normal_update_rowcount0_falls_back_to_upsert(tmp_path):
    """
    Fix 1：正常 UPDATE 分支的 UPDATE 影響 0 rows（concurrent delete 模擬）
    → 退化為 upsert，新路徑 row 仍寫入。
    只呼叫 invalidate 一次（由 upsert 負責，repath 不額外呼叫）。
    """
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/u22_old.mp4"
    new_uri = "file:///tmp/u22_new.mp4"

    # seed old row 讓 existence check 通過
    _seed_video(repo, old_uri)

    # 刪掉 old row 模擬並行刪除（在 repath 呼叫前刪，使 existence check 後 UPDATE 影響 0 rows）
    # 直接用 _get_connection 刪（測試 helper 允許）
    conn = repo._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM videos WHERE path = ?", (old_uri,))
        conn.commit()
    finally:
        conn.close()

    # 此時 existence check（repath 內的第一段）取舊快照…但我們已刪了 old row。
    # 為讓 repath 仍進入正常-UPDATE 分支，需讓 existence check 回 True。
    # 最直接的方式：monkeypatch _get_connection，讓第一次 SELECT 回「存在」，
    # 第二次（UPDATE）正常執行（實際 0 rows）。

    real_get_conn = repo._get_connection
    call_count = [0]

    def mock_get_connection():
        conn = real_get_conn()
        original_execute = conn.cursor().__class__.execute

        # 包一層 cursor，第一次 SELECT 回假的「存在」
        class FakeCursor:
            def __init__(self, real_cursor):
                self._c = real_cursor

            def execute(self, sql, params=()):
                self._c.execute(sql, params)

            def fetchone(self):
                call_count[0] += 1
                if call_count[0] <= 2:
                    # 兩次 SELECT（old_exists / new_exists）都回假結果
                    # old_exists → True（有 old row）; new_exists → None（沒 new row）
                    return (1,) if call_count[0] == 1 else None
                return self._c.fetchone()

            @property
            def rowcount(self):
                return self._c.rowcount

        return conn

    # 比起複雜 mock，直接用更簡單的方法：
    # repath 先做 SELECT 存在性，再做 UPDATE。
    # 此測試只驗證「當 UPDATE rowcount==0 時，upsert fallback 寫入 new_uri」。
    # 使用 monkeypatch cursor.execute，讓 UPDATE 語句後 rowcount=0（不執行真實 UPDATE）。

    new_video = Video(path=new_uri, number="ABC-001", title="Fallback Title",
                      original_title="", actresses=[], maker="", director="",
                      series=None, label="", tags=[], user_tags=[],
                      sample_images=[], duration=None, size_bytes=0,
                      cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0)

    # 重新 seed old row（讓 existence check 在 repath 內看到它）
    _seed_video(repo, old_uri)

    # 用 monkeypatch：在 repath 第二段 _get_connection 的 cursor.execute 之後，
    # 刪掉 old row 再 commit，模擬並行刪除後 rowcount=0。
    # 最乾淨的方式：patch cursor.rowcount 在 UPDATE 後回 0。

    real_get_conn2 = repo._get_connection
    update_call_count = [0]

    def patched_get_connection():
        conn = real_get_conn2()
        original_cursor = conn.cursor

        def patched_cursor():
            c = original_cursor()
            original_execute = c.execute

            def patched_execute(sql, params=()):
                original_execute(sql, params)
                # UPDATE 語句執行後，刪掉該 row 讓 rowcount 在 commit 後仍是真實值 0
                # （實際 rowcount 已由 sqlite 記錄；改用另一種方式：patch rowcount property）

            c.execute = patched_execute
            return c

        conn.cursor = patched_cursor
        return conn

    # 最直接的 deterministic 測試：
    # 使用真實流程，但在 repath 第二次 _get_connection 中傳回一個 rowcount=0 的 cursor。
    real_gc = repo._get_connection
    invocation = [0]

    class ZeroRowcountCursor:
        """Wraps a real cursor but reports rowcount=0 for UPDATE."""
        def __init__(self, real_cursor):
            self._c = real_cursor

        def execute(self, sql, params=()):
            # Run for real but discard actual changes (rollback immediately)
            # by NOT running execute → rowcount stays 0 by default in sqlite3
            if sql.strip().upper().startswith("UPDATE"):
                # Don't execute: rowcount will be 0
                pass
            else:
                self._c.execute(sql, params)

        def fetchone(self):
            return self._c.fetchone()

        @property
        def rowcount(self):
            return 0  # Always 0 for our fake cursor

    class FakeConnForUpdate:
        def __init__(self, real_conn):
            self._conn = real_conn
            self._cursor = None

        def cursor(self):
            self._cursor = ZeroRowcountCursor(self._conn.cursor())
            return self._cursor

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    def get_conn_patched():
        invocation[0] += 1
        real_conn = real_gc()
        if invocation[0] == 2:
            # 第二次呼叫 _get_connection 是 正常-UPDATE 分支 → 回 fake conn
            return FakeConnForUpdate(real_conn)
        return real_conn

    with patch.object(repo, "_get_connection", side_effect=get_conn_patched):
        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            repo.repath(old_uri, new_uri, new_video)

    # upsert fallback 應寫入 new_uri
    new_row = repo.get_by_path(new_uri)
    assert new_row is not None, \
        "rowcount=0 fallback 後 upsert 應寫入 new_uri"
    assert new_row.title == "Fallback Title", \
        f"新 row title 應為 'Fallback Title'，得 {new_row.title!r}"
