"""tests/unit/test_actress_library_aggregate.py — TASK-117-T1

`ActressRepository.get_video_actress_pairs()` 邊界測試（比照
test_database_actress_queries.py 的既有測試風格）＋
`core.database.actress_library.get_library_actresses()` 分組／聚合／別名合併／
parity 可證偽測試。
"""

import pytest

from core.database import Actress, ActressRepository, AliasRepository, Video, VideoRepository
from core.database.actress_library import get_library_actresses
from core.path_utils import to_file_uri


def _video(path_suffix: str, actresses: list, number: str = None) -> Video:
    """Build a minimal Video for upsert."""
    return Video(
        path=to_file_uri(f"/test/{path_suffix}.mp4"),
        number=number or path_suffix.upper(),
        title=path_suffix,
        actresses=actresses,
    )


@pytest.fixture
def library_db(temp_db, monkeypatch):
    """get_library_actresses() 內部一律用 module-level ActressRepository()/AliasRepository()
    （無 db_path 參數，落在 connection.get_db_path()）——monkeypatch 讓它指向 temp_db
    （比照 tests/unit/test_api_actress_showcase.py 既有慣例）。"""
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: temp_db)
    return temp_db


# ── ActressRepository.get_video_actress_pairs() 邊界測試 ───────────────────


# ── get_library_actresses() 分組／聚合 ──────────────────────────────────────


def test_get_library_actresses_merges_alias_group_and_counts_correctly(library_db):
    """AC-3.1/3.3/3.4 形狀：本名 0 片、別名 41 片（此處用 3 片模擬）→ 只出現一列，
    video_count 等於插入的片數，is_favorite=True，不得有獨立的別名列。"""
    ActressRepository(library_db).save(Actress(name="橋本ありな"))
    AliasRepository(library_db).add(primary_name="橋本ありな", aliases=["新ありな"])
    vrepo = VideoRepository(library_db)
    for i in range(3):
        vrepo.upsert(_video(f"v{i}", ["新ありな"]))

    groups = get_library_actresses()
    assert not any(g["primary_name"] == "新ありな" for g in groups)
    hashimoto = next(g for g in groups if g["primary_name"] == "橋本ありな")
    assert hashimoto["video_count"] == 3
    assert hashimoto["is_favorite"] is True
    assert set(hashimoto["names"]) == {"橋本ありな", "新ありな"}


def test_get_library_actresses_same_video_two_aliases_counted_once(library_db):
    """同一部片同時掛 primary + alias（合名寫法／多女優欄位）→ video_count 只算一次"""
    ActressRepository(library_db).save(Actress(name="橋本ありな"))
    AliasRepository(library_db).add(primary_name="橋本ありな", aliases=["新ありな"])
    VideoRepository(library_db).upsert(_video("v1", ["橋本ありな", "新ありな"]))

    groups = get_library_actresses()
    hashimoto = next(g for g in groups if g["primary_name"] == "橋本ありな")
    assert hashimoto["video_count"] == 1


def test_get_library_actresses_sort_desc_count_then_asc_name(library_db):
    """AC-2.2：video_count desc；片數相同時 primary_name asc（穩定次序，非插入順序或雜湊順序）"""
    vrepo = VideoRepository(library_db)
    # 插入順序刻意與期望排序相反
    vrepo.upsert(_video("z1", ["Zebra"]))
    vrepo.upsert(_video("a1", ["Apple"]))
    vrepo.upsert(_video("m1", ["Mango"]))
    vrepo.upsert(_video("m2", ["Mango"]))  # Mango: 2 片，最多

    groups = get_library_actresses()
    names = [g["primary_name"] for g in groups]
    assert names == ["Mango", "Apple", "Zebra"]


def test_get_library_actresses_manual_group_favorited_alias_counts_as_favorite(library_db):
    """Codex PR review P2（已查證屬實）：`AliasRepository.add()` 允許使用者自己在別名管理
    UI 手打任意 primary_name、把已收藏女優的正式名加成 alias——「A 是使用者手打的 group
    primary（未收藏）、B 是已收藏女優的正式名」是 UI 上點幾下就能做到的合法資料形狀。
    is_favorite 判定必須看整組 names，不能只看 group 自己的 primary_name。"""
    ActressRepository(library_db).save(Actress(name="B已收藏"))
    AliasRepository(library_db).add(primary_name="A手打的別名組", aliases=["B已收藏"])
    VideoRepository(library_db).upsert(_video("v1", ["A手打的別名組"]))

    groups = get_library_actresses()
    g = next(g for g in groups if set(g["names"]) == {"A手打的別名組", "B已收藏"})
    assert g["is_favorite"] is True


def test_get_library_actresses_manual_group_displays_favorited_official_name(library_db):
    """AC-3.1「顯示已收藏女優的正式名」：group 自己的 primary_name（使用者手打、未收藏）
    不得出現在回應清單中；顯示用的 primary_name 必須是已收藏那一位的正式名。"""
    ActressRepository(library_db).save(Actress(name="B已收藏"))
    AliasRepository(library_db).add(primary_name="A手打的別名組", aliases=["B已收藏"])
    VideoRepository(library_db).upsert(_video("v1", ["A手打的別名組"]))

    groups = get_library_actresses()
    assert not any(g["primary_name"] == "A手打的別名組" for g in groups)
    g = next(g for g in groups if g["primary_name"] == "B已收藏")
    assert g["is_favorite"] is True
    assert set(g["names"]) == {"A手打的別名組", "B已收藏"}


def test_get_library_actresses_is_favorite_false_when_alias_record_remains_but_actress_deleted(library_db):
    """§1.1 定死規則 2 ＋ Opus 裁決②的規格守門：is_favorite 判定必須讀 actresses 表
    （get_all() 集合），不是「這個 group 在 alias 表裡存在」——取消收藏（刪 actresses
    row）但 actress_aliases 記錄還在時，is_favorite 必須是 False。若實作誤查 alias
    表存在與否，本測試會抓到。"""
    ActressRepository(library_db).save(Actress(name="橋本ありな"))
    AliasRepository(library_db).add(primary_name="橋本ありな", aliases=["新ありな"])
    VideoRepository(library_db).upsert(_video("v1", ["新ありな"]))
    ActressRepository(library_db).delete_by_name("橋本ありな")  # 取消收藏，alias 記錄仍在

    groups = get_library_actresses()
    hashimoto = next(g for g in groups if g["primary_name"] == "橋本ありな")
    assert hashimoto["is_favorite"] is False


# ── parity 測試：video_count == count_videos_for_actress_names(resolve(primary_name)) ──
# CD-117-2：新聚合查詢的片數口徑必須與既有 count_videos_for_actress_names 對帳，
# 不得自行重新發明計數邏輯。


