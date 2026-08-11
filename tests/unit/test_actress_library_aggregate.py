"""tests/unit/test_actress_library_aggregate.py — TASK-117-T1

`ActressRepository.get_video_actress_pairs()` 邊界測試（比照
test_database_actress_queries.py 的既有測試風格）＋
`core.database.actress_library.get_library_actresses()` 分組／聚合／別名合併／
parity 可證偽測試。
"""
import sqlite3

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

def test_get_video_actress_pairs_empty_db_returns_empty_list(temp_db):
    repo = ActressRepository(temp_db)
    assert repo.get_video_actress_pairs() == []


def test_get_video_actress_pairs_returns_all_pairs(temp_db):
    VideoRepository(temp_db).upsert(_video("v1", ["Alice", "Bob"]))
    repo = ActressRepository(temp_db)
    names = sorted(p[1] for p in repo.get_video_actress_pairs())
    assert names == ["Alice", "Bob"]


def test_get_video_actress_pairs_excludes_empty_array(temp_db):
    """A video with actresses=[] must not produce any pair."""
    VideoRepository(temp_db).upsert(_video("v1", []))
    repo = ActressRepository(temp_db)
    assert repo.get_video_actress_pairs() == []


def test_get_video_actress_pairs_handles_null_actresses(temp_db):
    """A row with actresses=NULL must not crash; it is silently skipped."""
    conn = sqlite3.connect(str(temp_db))
    conn.execute(
        "INSERT INTO videos (path, title, actresses) VALUES (?, ?, NULL)",
        (to_file_uri("/test/null_actress.mp4"), "null test"),
    )
    conn.commit()
    conn.close()

    repo = ActressRepository(temp_db)
    assert repo.get_video_actress_pairs() == []  # must not raise


def test_get_video_actress_pairs_handles_malformed_json(temp_db):
    """A row with actresses='not-json' must not crash (json_valid guard)."""
    conn = sqlite3.connect(str(temp_db))
    conn.execute(
        "INSERT INTO videos (path, title, actresses) VALUES (?, ?, ?)",
        (to_file_uri("/test/bad_json.mp4"), "bad json", "not-json"),
    )
    conn.commit()
    conn.close()

    repo = ActressRepository(temp_db)
    assert repo.get_video_actress_pairs() == []


# ── get_library_actresses() 分組／聚合 ──────────────────────────────────────

def test_get_library_actresses_excludes_zero_video_actress(library_db):
    """AC-2.7：收藏但 0 片的女優不出現在回應中（group 只由 pairs 建立，不 outer join 收藏表）"""
    ActressRepository(library_db).save(Actress(name="無片女優"))
    groups = get_library_actresses()
    assert all(g["primary_name"] != "無片女優" for g in groups)


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


def test_get_library_actresses_manual_group_parity_with_favorited_alias(library_db):
    """CD-117-2 parity：即使顯示名換成已收藏的 alias（而非 group 自己的 primary），
    video_count 口徑仍須與 count_videos_for_actress_names(resolve(顯示名)) 一致——
    resolve() 雙向解析，換名不改變 group 本身。"""
    ActressRepository(library_db).save(Actress(name="B已收藏"))
    AliasRepository(library_db).add(primary_name="A手打的別名組", aliases=["B已收藏"])
    vrepo = VideoRepository(library_db)
    vrepo.upsert(_video("v1", ["A手打的別名組"]))
    vrepo.upsert(_video("v2", ["B已收藏"]))

    groups = get_library_actresses()
    g = next(g for g in groups if g["primary_name"] == "B已收藏")
    expected = ActressRepository(library_db).count_videos_for_actress_names(
        AliasRepository(library_db).resolve("B已收藏")
    )
    assert g["video_count"] == expected
    assert g["video_count"] == 2


def test_get_library_actresses_display_name_deterministic_when_multiple_aliases_favorited(library_db):
    """確定性規則：group 自己的 primary 未收藏、但有兩個 alias 成員都已收藏時，顯示名必須
    是 names_list（= [primary_name] + aliases，既有儲存順序）裡第一個命中 favorite_names
    的名字，不是任意挑一個——鎖住這條規則不隨字典雜湊順序漂移。"""
    ActressRepository(library_db).save(Actress(name="先收藏的B"))
    ActressRepository(library_db).save(Actress(name="後收藏的C"))
    AliasRepository(library_db).add(
        primary_name="A手打的別名組", aliases=["先收藏的B", "後收藏的C"]
    )
    VideoRepository(library_db).upsert(_video("v1", ["A手打的別名組"]))

    groups = get_library_actresses()
    g = next(
        g for g in groups
        if set(g["names"]) == {"A手打的別名組", "先收藏的B", "後收藏的C"}
    )
    assert g["primary_name"] == "先收藏的B"
    assert g["is_favorite"] is True


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


def test_get_library_actresses_db_calls_independent_of_group_count(library_db, monkeypatch):
    """迴圈內不得開 DB 連線（DoD）：get_video_actress_pairs / AliasRepository.get_all /
    ActressRepository.get_all 各只呼叫一次，與 group 數無關（10 個各自獨立的 group）。"""
    calls = {"pairs": 0, "alias_all": 0, "actress_all": 0}
    orig_pairs = ActressRepository.get_video_actress_pairs
    orig_alias_all = AliasRepository.get_all
    orig_actress_all = ActressRepository.get_all

    def counted_pairs(self):
        calls["pairs"] += 1
        return orig_pairs(self)

    def counted_alias_all(self):
        calls["alias_all"] += 1
        return orig_alias_all(self)

    def counted_actress_all(self):
        calls["actress_all"] += 1
        return orig_actress_all(self)

    monkeypatch.setattr(ActressRepository, "get_video_actress_pairs", counted_pairs)
    monkeypatch.setattr(AliasRepository, "get_all", counted_alias_all)
    monkeypatch.setattr(ActressRepository, "get_all", counted_actress_all)

    vrepo = VideoRepository(library_db)
    for i in range(10):
        vrepo.upsert(_video(f"v{i}", [f"女優{i}"]))

    get_library_actresses()

    assert calls == {"pairs": 1, "alias_all": 1, "actress_all": 1}


# ── parity 測試：video_count == count_videos_for_actress_names(resolve(primary_name)) ──
# CD-117-2：新聚合查詢的片數口徑必須與既有 count_videos_for_actress_names 對帳，
# 不得自行重新發明計數邏輯。

def test_get_library_actresses_parity_no_alias_single_actress(library_db):
    """無別名的單獨女優"""
    VideoRepository(library_db).upsert(_video("v1", ["Solo"]))
    groups = get_library_actresses()
    g = next(g for g in groups if g["primary_name"] == "Solo")
    expected = ActressRepository(library_db).count_videos_for_actress_names(
        AliasRepository(library_db).resolve("Solo")
    )
    assert g["video_count"] == expected


def test_get_library_actresses_parity_merged_group(library_db):
    """已合併的 group"""
    ActressRepository(library_db).save(Actress(name="橋本ありな"))
    AliasRepository(library_db).add(primary_name="橋本ありな", aliases=["新ありな"])
    vrepo = VideoRepository(library_db)
    vrepo.upsert(_video("v1", ["橋本ありな"]))
    vrepo.upsert(_video("v2", ["新ありな"]))

    groups = get_library_actresses()
    g = next(g for g in groups if g["primary_name"] == "橋本ありな")
    expected = ActressRepository(library_db).count_videos_for_actress_names(
        AliasRepository(library_db).resolve("橋本ありな")
    )
    assert g["video_count"] == expected


def test_get_library_actresses_parity_sort_adjacent_same_count(library_db):
    """片數相同排序相鄰的兩個 group，各自 parity 仍成立"""
    vrepo = VideoRepository(library_db)
    vrepo.upsert(_video("a1", ["Apple"]))
    vrepo.upsert(_video("m1", ["Mango"]))

    groups = get_library_actresses()
    arepo = ActressRepository(library_db)
    alias_repo = AliasRepository(library_db)
    for g in groups:
        expected = arepo.count_videos_for_actress_names(alias_repo.resolve(g["primary_name"]))
        assert g["video_count"] == expected
