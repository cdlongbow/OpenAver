"""
tests/unit/test_enricher_attributes.py

TASK-121a-T4：補完路徑（core/enricher.py）接入 effective_tags()，
並修兩個既有裂縫：
- CD-7：字幕偵測只看 sidecar .srt，不看檔名（本檔用 check_subtitle 補上）
- CD-9：屬性 tag 只餵進 NFO，沒同步進 DB videos.tags（本檔新增
  VideoRepository.update_tags_if_changed() 補上）

策略：真的打 tmp_path 上的暫存 SQLite（透過 core.enricher.VideoRepository
被 patch 成回傳指向該暫存 db 的真實 VideoRepository instance），只在
network 呼叫（search_jav / download_image）上用 mock 防呆。NFO 用真的
generate_nfo() 寫實體檔，讀檔內容驗證。
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import core.enricher as enricher_mod
from core.database import Video, VideoRepository, init_db
from core.organizer import generate_nfo as real_generate_nfo
from core.path_utils import to_file_uri


# ── helpers ──────────────────────────────────────────────────────────────────

def _scraper_result(number="ABC-123", tags=None, source="javbus", **overrides):
    data = {
        "number": number,
        "title": "タイトル",
        "actors": ["女優A"],
        "cover": "https://example.com/cover.jpg",
        "date": "2024-01-01",
        "maker": "SOD",
        "director": "監督",
        "series": "シリーズ",
        "label": "LABEL",
        "tags": tags if tags is not None else [],
        "sample_images": [],
        "duration": 100,
        "url": "https://example.com/x",
        "source": source,
    }
    data.update(overrides)
    return data


def _make_db_video(number, path_uri, tags):
    return Video(
        number=number,
        path=path_uri,
        title="舊標題",
        original_title="Old Title",
        actresses=["女優X"],
        maker="MakerX",
        director="監督X",
        series="シリーズX",
        label="LABELX",
        tags=list(tags),
        release_date="2023-05-01",
        duration=90,
    )


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return VideoRepository(db_path=db_path)


def _patches(repo_instance, search_jav_forbidden=True):
    """共用防呆：VideoRepository() 一律回傳真的暫存 db repo；search_jav/download_image
    預設禁止被呼叫（本檔所有 enrich_single 呼叫都應該靠 scraper_data/DB/NFO 完成，
    不打真網路）。"""
    ps = [
        patch("core.enricher.VideoRepository", MagicMock(return_value=repo_instance)),
        patch("core.enricher.download_image",
              side_effect=AssertionError("download_image 不應被呼叫（write_cover=False）")),
    ]
    if search_jav_forbidden:
        ps.append(patch("core.enricher.search_jav",
                         side_effect=AssertionError("search_jav 不應被呼叫（已提供 scraper_data 或 meta 已完整）")))
    return ps


def _read_nfo(nfo_path: Path) -> str:
    return nfo_path.read_text(encoding="utf-8")


# ── 邊界 1：A3 核心（CD-7）─────────────────────────────────────────────────────

def test_boundary1_cd7_filename_subtitle_detected_without_sidecar(tmp_path, repo):
    """ABC-123-C.mp4、無 .srt sidecar → has_subtitle 必須靠檔名判定為 True
    （mutation①：拿掉 check_subtitle(...) or 之後這條必紅），
    NFO 與 DB 的 tags 皆含「中文字幕」。"""
    video_path = tmp_path / "ABC-123-C.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")

    real_write_nfo = enricher_mod._write_nfo
    spy_write_nfo = MagicMock(side_effect=real_write_nfo)

    patches = _patches(repo)
    with patches[0], patches[1], patches[2], patch.object(enricher_mod, "_write_nfo", spy_write_nfo):
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABC-123-C",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="ABC-123-C", tags=[]),
        )

    assert result.success is True
    # mutation①-sensitive：has_subtitle 傳進 _write_nfo 必須是 True
    _, call_kwargs = spy_write_nfo.call_args
    assert call_kwargs["has_subtitle"] is True

    nfo_text = _read_nfo(nfo_path)
    assert "<tag>中文字幕</tag>" in nfo_text

    path_uri = to_file_uri(str(video_path))
    updated = repo.get_by_path(path_uri)
    assert updated is not None
    assert "中文字幕" in updated.tags


# ── 邊界 2：A3 延伸 ×3（CD-9，三種 source_used）───────────────────────────────

def test_boundary2_source_scraper_syncs_nfo_and_db(tmp_path, repo):
    """mode=fill_missing、source_used=scraper（brand-new file，無 DB/NFO）→
    NFO 與 DB 都同步（走既有 _db_upsert() 路徑）。"""
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="ABP-999-UC", tags=["Drama"], source="scraper"),
        )

    assert result.success is True
    assert result.source_used == "scraper"

    nfo_text = _read_nfo(nfo_path)
    assert "<tag>中文字幕</tag>" in nfo_text
    assert "<tag>無碼破解</tag>" in nfo_text

    path_uri = to_file_uri(str(video_path))
    updated = repo.get_by_path(path_uri)
    assert updated is not None
    assert "中文字幕" in updated.tags
    assert "無碼破解" in updated.tags


def test_boundary2_source_nfo_syncs_db_via_new_mutator(tmp_path, repo):
    """mode=fill_missing、source_used=nfo（meta 來自 sidecar NFO，DB 對這個 number
    查無資料，但同一 path 早有一筆舊 row，模擬「已入庫但這次改走 NFO 路徑」）→
    DB tags 必須靠新 mutator 同步（mutation②：拿掉 repo.update_tags_if_changed(...)
    那行之後這條必紅）。"""
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")
    real_generate_nfo(
        number="ABP-999-UC",
        title="舊標題",
        original_title="Old Title",
        actors=["女優X"],
        tags=["Drama"],
        date="2023-05-01",
        maker="MakerX",
        director="監督X",
        output_path=str(nfo_path),
        series="シリーズX",
        label="LABELX",
    )

    path_uri = to_file_uri(str(video_path))
    repo.upsert(_make_db_video("ABP-999-UC", path_uri, tags=["Drama"]))

    # 強迫走 nfo 分支：即使同一 path 早有 row，get_by_numbers（用 number 查）故意
    # 回傳空，模擬這次呼叫選擇讀 NFO 而非 DB 取 meta 的情境。
    repo.get_by_numbers = MagicMock(return_value={})

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
        )

    assert result.success is True
    assert result.source_used == "nfo"

    updated = repo.get_by_path(path_uri)
    assert updated is not None
    assert "中文字幕" in updated.tags
    assert "無碼破解" in updated.tags


def test_boundary2_source_db_syncs_db_via_new_mutator(tmp_path, repo):
    """mode=fill_missing、source_used=db（DB 對這個 number 有完整資料）→
    DB tags 必須靠新 mutator 同步（mutation②-sensitive，同上）。"""
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")

    path_uri = to_file_uri(str(video_path))
    repo.upsert(_make_db_video("ABP-999-UC", path_uri, tags=["Drama"]))

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
        )

    assert result.success is True
    assert result.source_used == "db"

    updated = repo.get_by_path(path_uri)
    assert updated is not None
    assert "中文字幕" in updated.tags
    assert "無碼破解" in updated.tags


# ── 邊界 3：effective_tags 每次 enrich_single 只算一次 ─────────────────────────

def test_boundary3_effective_tags_called_exactly_once(tmp_path, repo):
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")

    from core.cover_attributes import effective_tags as real_effective_tags
    spy = MagicMock(side_effect=real_effective_tags)

    patches = _patches(repo)
    with patches[0], patches[1], patches[2], patch.object(enricher_mod, "effective_tags", spy):
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="ABP-999-UC", tags=["Drama"]),
        )

    assert result.success is True
    assert spy.call_count == 1


# ── 邊界 4 + 5：不變不寫 + ranker invalidate（直接測 mutator）───────────────────

def test_boundary4_and_5_update_tags_if_changed_noop_when_unchanged(tmp_path, repo):
    """值相同 → 回傳 False、不執行 UPDATE（用 sentinel updated_at 驗證未被寫入）、
    不呼叫 SimilarRankerCache.invalidate()（mutation③：拿掉「不變不寫」比對之後
    這條必紅——UPDATE 會被永遠執行，sentinel 會被洗掉）。"""
    path_uri = to_file_uri(str(tmp_path / "X.mp4"))
    repo.upsert(_make_db_video("X-001", path_uri, tags=["A", "B"]))

    conn = repo._get_connection()
    try:
        conn.execute(
            "UPDATE videos SET updated_at = ? WHERE path = ?",
            ("2000-01-01 00:00:00", path_uri),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("core.similar.ranker_cache.SimilarRankerCache.invalidate") as mock_invalidate:
        result = repo.update_tags_if_changed(path_uri, ["A", "B"])

    assert result is False
    mock_invalidate.assert_not_called()

    conn = repo._get_connection()
    try:
        row = conn.execute("SELECT updated_at FROM videos WHERE path = ?", (path_uri,)).fetchone()
    finally:
        conn.close()
    assert row[0] == "2000-01-01 00:00:00"  # 未被 UPDATE 洗掉


def test_boundary5_update_tags_if_changed_invalidates_when_changed(tmp_path, repo):
    """值不同 → 回傳 True、真的 UPDATE、呼叫 SimilarRankerCache.invalidate()。"""
    path_uri = to_file_uri(str(tmp_path / "Y.mp4"))
    repo.upsert(_make_db_video("Y-001", path_uri, tags=["A"]))

    with patch("core.similar.ranker_cache.SimilarRankerCache.invalidate") as mock_invalidate:
        result = repo.update_tags_if_changed(path_uri, ["A", "B"])

    assert result is True
    mock_invalidate.assert_called_once()

    updated = repo.get_by_path(path_uri)
    assert updated.tags == ["A", "B"]


# ── 邊界 6：A4 — 無屬性檔名不產生任何屬性 tag ──────────────────────────────────

def test_boundary6_a4_no_attribute_tags_for_plain_multipart(tmp_path, repo):
    video_path = tmp_path / "ABC-123-cd1.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABC-123",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="ABC-123", tags=["Drama"]),
        )

    assert result.success is True
    nfo_text = _read_nfo(nfo_path)
    for attr_tag in ("中文字幕", "無碼破解", "無碼流出", "4K", "VR"):
        assert f"<tag>{attr_tag}</tag>" not in nfo_text
    assert "<tag>Drama</tag>" in nfo_text

    path_uri = to_file_uri(str(video_path))
    updated = repo.get_by_path(path_uri)
    for attr_tag in ("中文字幕", "無碼破解", "無碼流出", "4K", "VR"):
        assert attr_tag not in updated.tags


# ── 邊界 7：檔案不在 DB → mutator 回 False，enrich_single 不炸掉 ────────────────

def test_boundary7_mutator_returns_false_when_row_not_in_db(tmp_path, repo):
    """完全沒入過庫的 path 直接呼叫 update_tags_if_changed() → False、不炸。"""
    path_uri = to_file_uri(str(tmp_path / "NEVER-SEEN.mp4"))
    result = repo.update_tags_if_changed(path_uri, ["中文字幕"])
    assert result is False


def test_boundary7_enrich_single_survives_when_path_not_in_db(tmp_path, repo):
    """source_used=nfo、DB 對這個 path 完全沒有任何 row（真正「未入庫」情境）→
    enrich_single 仍成功完成，不因 mutator 找不到 row 而炸掉。"""
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")
    real_generate_nfo(
        number="ABP-999-UC",
        title="舊標題",
        original_title="Old Title",
        actors=["女優X"],
        tags=["Drama"],
        date="2023-05-01",
        maker="MakerX",
        director="監督X",
        output_path=str(nfo_path),
        series="シリーズX",
        label="LABELX",
    )
    repo.get_by_numbers = MagicMock(return_value={})  # 強迫走 nfo 分支

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
        )

    assert result.success is True
    assert result.source_used == "nfo"

    path_uri = to_file_uri(str(video_path))
    assert repo.get_by_path(path_uri) is None  # mutator 沒有插入新 row


# ── 邊界 8：meta['tags'] 不存在 / 為 None → 不炸 ───────────────────────────────

def test_boundary8_meta_tags_none_does_not_crash(tmp_path, repo):
    """_video_to_meta 回傳的 meta['tags'] 為 None（防禦性邊界，非自然路徑會產生，
    模擬未來上游變化）→ enrich_single 不炸，effective_tags 收到空 list 起算。

    scraper_data 的 tags 刻意給 []（falsy）：_missing_fields 見 tags=None 判定缺失、
    觸發 _merge_meta，但 supplement.tags 同為 falsy 不會覆寫，merged['tags'] 在
    進入 has_subtitle/effective_tags 那段時仍是原本的 None ——真正驗到的就是這段
    防禦 `list(meta.get('tags', []) or [])`，不是「原本就沒 tags 缺失」這種假路徑。
    """
    video_path = tmp_path / "DBN-001.mp4"
    video_path.write_bytes(b"stub")

    fake_meta = {
        "title": "T", "original_title": "T", "actresses": ["A"],
        "maker": "M", "director": "D", "series": "S", "label": "L",
        "tags": None, "release_date": "2020-01-01", "duration": 10,
        "cover_url": "", "url": "", "sample_images": [],
    }
    path_uri = to_file_uri(str(video_path))
    repo.upsert(_make_db_video("DBN-001", path_uri, tags=[]))

    patches = _patches(repo, search_jav_forbidden=False)
    with patches[0], patches[1], \
         patch("core.enricher.search_jav",
               side_effect=AssertionError("scraper_data 已提供，不該再打 search_jav")), \
         patch("core.enricher._video_to_meta", return_value=fake_meta):
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="DBN-001",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="DBN-001", tags=[]),
        )

    assert result.success is True


def test_boundary8_scraper_data_missing_tags_key_does_not_crash(tmp_path, repo):
    """scraper_data 字典本身沒有 'tags' 這個 key（非 None，是缺 key）→ 不炸。"""
    video_path = tmp_path / "DBN-002.mp4"
    video_path.write_bytes(b"stub")

    data = _scraper_result(number="DBN-002")
    del data["tags"]

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="DBN-002",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=data,
        )

    assert result.success is True


# ── 邊界 9：既有 NFO 不重複（T2 dedup 在補完路徑也成立）─────────────────────────

def test_boundary9_nfo_no_duplicate_subtitle_tag(tmp_path, repo):
    """meta['tags'] 已含「中文字幕」＋ has_subtitle=True（filename token 判定）→
    NFO 輸出恰好一份 <tag>中文字幕</tag>。"""
    video_path = tmp_path / "ABC-123-C.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABC-123-C",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
            scraper_data=_scraper_result(number="ABC-123-C", tags=["中文字幕", "Drama"]),
        )

    assert result.success is True
    nfo_text = _read_nfo(nfo_path)
    assert nfo_text.count("<tag>中文字幕</tag>") == 1
    assert nfo_text.count("<genre>中文字幕</genre>") == 1


# ── review finding（2026-08-19）：mutator 例外不得把「部分成功」誤報成「整體失敗」──

def test_tags_sync_failure_does_not_fail_the_whole_enrich(tmp_path, repo):
    """update_tags_if_changed() 拋例外（sqlite busy/locked）時，enrich_single 仍回成功。

    使用者流程：按「補齊資料」→ NFO／封面／其他 DB 欄位其實都已寫好 → 若這一行的
    例外穿透出去，使用者會看到「處理失敗」而重按，實際上檔案早就寫完了。
    錯誤隔離比照同檔 _db_upsert() 的既有慣例。
    """
    video_path = tmp_path / "ABP-999-UC.mp4"
    video_path.write_bytes(b"stub")
    nfo_path = video_path.with_suffix(".nfo")
    real_generate_nfo(
        number="ABP-999-UC",
        title="舊標題",
        original_title="Old Title",
        actors=["女優X"],
        tags=["Drama"],
        date="2023-05-01",
        maker="MakerX",
        director="監督X",
        output_path=str(nfo_path),
        series="シリーズX",
        label="LABELX",
    )
    repo.get_by_numbers = MagicMock(return_value={})  # 強迫走 nfo 分支
    repo.update_tags_if_changed = MagicMock(side_effect=RuntimeError("database is locked"))

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(video_path),
            number="ABP-999-UC",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
        )

    assert repo.update_tags_if_changed.called
    assert result.success is True
    # 例外沒有穿透：流程一路跑到底（source_used 是回傳前才填的欄位）
    assert result.source_used == "nfo"
