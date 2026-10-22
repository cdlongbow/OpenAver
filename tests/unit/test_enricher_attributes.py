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


# ── 邊界 4 + 5：不變不寫 + ranker invalidate（直接測 mutator）───────────────────


# ── 邊界 6：A4 — 無屬性檔名不產生任何屬性 tag ──────────────────────────────────


# ── 邊界 7：檔案不在 DB → mutator 回 False，enrich_single 不炸掉 ────────────────


# ── 邊界 8：meta['tags'] 不存在 / 為 None → 不炸 ───────────────────────────────


# ── 邊界 9：既有 NFO 不重複（T2 dedup 在補完路徑也成立）─────────────────────────


# ── review finding（2026-08-19）：mutator 例外不得把「部分成功」誤報成「整體失敗」──


# ── 邊界 10：同番號多檔案時，寫回的是「這個檔案自己那一列」 ────────────────────
# 來源：PR #145 Codex P1。`enrich_single()` 用番號查 DB（get_by_numbers），
# 回傳的是**一串**（cd1/cd2、-4k/-uc 變體共用同一個番號，本專案 suffix_keywords
# 明文支援這種擺法），舊寫法無條件取 videos[0]，卻把結果寫進「當前檔案」的
# path_uri —— 等於用另一支片的資料覆蓋這一支。
# 這個選錯列的缺陷早於 121a（sidecar NFO 一直有），但 121a 新增的 DB 同步點
# 讓它第一次咬到 videos.tags：source_used 為 db/nfo 時舊碼根本不寫 DB。

def test_boundary10_same_number_multi_file_uses_own_row(tmp_path, repo):
    """同番號兩列、tags 不同 → 補完 cd2 不得被 cd1 的 tags 覆蓋。"""
    cd1 = tmp_path / "ABC-123-cd1.mp4"
    cd2 = tmp_path / "ABC-123-cd2.mp4"
    cd1.write_bytes(b"stub")
    cd2.write_bytes(b"stub")

    cd1_uri = to_file_uri(str(cd1))
    cd2_uri = to_file_uri(str(cd2))
    # cd1 先寫入 → 它會是 get_by_numbers 回傳串列的第一筆
    repo.upsert(_make_db_video("ABC-123", cd1_uri, tags=["中文字幕", "Drama"]))
    repo.upsert(_make_db_video("ABC-123", cd2_uri, tags=["Drama"]))

    patches = _patches(repo)
    with patches[0], patches[1], patches[2]:
        from core.enricher import enrich_single
        result = enrich_single(
            file_path=str(cd2),
            number="ABC-123",
            mode="fill_missing",
            write_nfo=True,
            write_cover=False,
        )

    assert result.success is True

    cd2_row = repo.get_by_path(cd2_uri)
    assert cd2_row is not None
    # cd2 的檔名沒有字幕 token、DB 那一列也沒有「中文字幕」→ 補完後不該長出來
    assert "中文字幕" not in cd2_row.tags, (
        f"cd2 被 cd1 的 tags 覆蓋了：{cd2_row.tags}（選錯 DB 列）"
    )
    assert "Drama" in cd2_row.tags

    # 連帶：寫出的 NFO 也不該帶上 cd1 的標籤
    nfo_text = _read_nfo(cd2.with_suffix(".nfo"))
    assert "<tag>中文字幕</tag>" not in nfo_text

    # cd1 那一列不得被這次呼叫動到
    cd1_row = repo.get_by_path(cd1_uri)
    assert cd1_row is not None
    assert "中文字幕" in cd1_row.tags
