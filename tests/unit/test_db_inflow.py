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
U16 old_uri 使用 to_file_uri(normalize_path(...))，無手拼 URI、無 [8:] strip  # path-contract-ok
U25 正常 UPDATE — output_dir 保留（incoming 空，Codex branch-review P2）
U26 正常 UPDATE — scrape_attempted_at 保留（incoming 0，Codex branch-review P2）
U27 正常 UPDATE — output_dir/scrape_attempted_at happy path（incoming 有值正常寫入）
U28 碰撞 delete-merge — output_dir/scrape_attempted_at 保留（Codex branch-review P2）

TASK-showcase-nfo-mtime（in-flow nfo_mtime 回填）：
N1 有 NFO 落磁碟 → DB nfo_mtime == 該 NFO 的 st_mtime（>0）
N2 無 NFO 落磁碟 → DB nfo_mtime == 0（誠實回報無 NFO，非回歸）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

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


# ─── U2: 正常 UPDATE — created_at 保留 ─────────────────────────────────────


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


# ─── U25/U26: 正常 UPDATE 分支 — output_dir / scrape_attempted_at 保留 ─────
# Codex branch-review P2：repath 逐欄直寫，未對 output_dir/scrape_attempted_at
# 套用 upsert() 已有的「incoming 空/0 → 保留既有」保護，organize/搬移時新掃描
# 的 Video（output_dir='' / scrape_attempted_at=0.0）會把既有 marker 洗掉。


# ─── U28: 碰撞 delete-merge 分支 — output_dir / scrape_attempted_at 保留 ───


# ─── U9: 碰撞分支 atomicity（INSERT 失敗 → rollback） ──────────────────────


def test_u9_collision_rollback_via_real_repath(tmp_path):
    """U9 替代測試：使用真實 repath，確保 old row 在 rollback 後存活。"""
    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    old_uri = "file:///tmp/old9.mp4"
    new_uri = "file:///tmp/new9.mp4"

    _seed_video(repo, old_uri, user_tags=["看過"])
    _seed_video(repo, new_uri, user_tags=["A"])

    # 注入 commit 失敗以觸發 repath collision 分支的 rollback 路徑。
    # 真 sqlite3.Connection.commit 是唯讀 C 屬性，無法直接賦值 monkeypatch
    # （`conn.commit = ...` 會拋 AttributeError）；改包一層 proxy 覆寫 commit，
    # 其餘屬性（cursor/rollback/close…）委派真連線。每個 proxy 自帶 commit 計數，
    # 只有 collision 分支的寫入連線會 commit → 其第一次 commit 觸發注入的失敗。
    real_get_connection = repo._get_connection

    class _FailFirstCommitConn:
        def __init__(self, real):
            self._real = real
            self._commits = 0

        def commit(self):
            self._commits += 1
            if self._commits == 1:
                # 不預先 rollback：讓 repath 自己的 except 走 conn.rollback()（待驗行為本體）
                raise sqlite3.OperationalError("Simulated commit failure")
            return self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    def failing_get_connection():
        return _FailFirstCommitConn(real_get_connection())

    with patch.object(repo, "_get_connection", failing_get_connection):
        with patch("core.similar.ranker_cache.SimilarRankerCache"):
            # collision 分支 commit 失敗 → repath 應 rollback 後如實 re-raise
            with pytest.raises(sqlite3.OperationalError, match="Simulated commit failure"):
                repo.repath(old_uri, new_uri, Video(
                    path=new_uri, number="ABC-001", title="Fail",
                    original_title="", actresses=[], maker="", director="",
                    series=None, label="", tags=[], user_tags=["C"],
                    sample_images=[], duration=None, size_bytes=0,
                    cover_path="", release_date="", mtime=0.0, nfo_mtime=0.0,
                ))

    # rollback 生效：old row 應存活（DELETE 被撤銷），new row 內容不被 merge 覆寫
    assert repo.get_by_path(old_uri) is not None, \
        "rollback 後 old row 應存活（不雙失）"
    new_row = repo.get_by_path(new_uri)
    assert new_row is not None and new_row.user_tags == ["A"], \
        f"rollback 後 new row 應保留原內容 ['A']，實際: {new_row.user_tags if new_row else None!r}"


# ─── U10: old-not-in-DB（純 Search，無前置 Scanner）───────────────────────


# ─── U11: old_file_path=None 向後相容 ──────────────────────────────────────


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


# ─── U14: ranker invalidate — scan-fail 保卡分支 ──────────────────────────


# ─── U15: ranker invalidate — 碰撞 delete-merge 分支 ──────────────────────


# ─── U16: grep 守衛 — 無手拼 URI ─────────────────────────────────────────


# ─── U17: repath_path_only — 正常搬移（Fix 2） ────────────────────────────────


# ─── U18: repath_path_only — new_uri 碰撞（Fix 2） ─────────────────────────────


# ─── U19: repath_path_only — self no-op（Fix 2） ────────────────────────────────


# ─── U20: repath_path_only — empty old_uri（Fix 2） ─────────────────────────────


# ─── U21: db_inflow scan-fail 保卡用 repath_path_only（Fix 2 layering） ──────────


# ─── U22: Fix 1 rowcount=0 fallback → upsert（Fix 1） ───────────────────────────


# ─── N1/N2: TASK-showcase-nfo-mtime — in-flow nfo_mtime 磁碟回填 ───────────
# 根因：try_inflow_upsert → Video.from_video_info 寫死 nfo_mtime=0.0，
# 目錄掃描路徑（scanner.py:510）事後從磁碟回填，in-flow 路徑原本缺這一步，
# 導致 search 頁刮好的新片 showcase 誤顯示缺 NFO 🔍 icon。
# 主修：db_inflow.py 在 from_video_info 之後、repath 之前 stat 新 NFO。

def test_n1_nfo_mtime_backfilled_from_disk_when_nfo_exists(tmp_path):
    """有 NFO 落磁碟 → DB nfo_mtime == 該 NFO 檔案的真實 st_mtime（>0）。

    這是主要的 RED→GREEN：移除 db_inflow.py 的回填 patch 後，本測試應變 RED
    （nfo_mtime 恆為 0.0，因為 Video.from_video_info 寫死 0.0）。
    """
    from core.path_utils import normalize_path, to_file_uri

    db_path = _make_db(tmp_path)
    repo = VideoRepository(db_path=db_path)

    video_path = tmp_path / "n1_video.mp4"
    nfo_path = tmp_path / "n1_video.nfo"
    video_path.write_bytes(b"fake video bytes")
    nfo_path.write_text("<movie><title>N1</title></movie>", encoding="utf-8")
    expected_mtime = nfo_path.stat().st_mtime

    new_uri = to_file_uri(normalize_path(str(video_path)), None)
    video_info = _make_video_info(new_uri, num="N1-001", title="N1 Video")

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
        MockScanner.return_value.scan_file.return_value = video_info

        result = _db_inflow_mod.try_inflow_upsert(str(video_path), old_file_path=None)

    assert result == "synced", f"應回 'synced'，實際: {result!r}"

    row = repo.get_by_path(new_uri)
    assert row is not None, "DB row 應存在"
    assert row.nfo_mtime == pytest.approx(expected_mtime), (
        f"nfo_mtime 應為磁碟 NFO 的 st_mtime={expected_mtime}，實際: {row.nfo_mtime!r}"
    )
    assert row.nfo_mtime > 0, "nfo_mtime 應 >0（has_nfo=true）"


