"""
test_tags_top.py — GET /api/tags/top 整合測試

策略：TDD-lite（TestClient + tmp_path 真實 SQLite DB，不 mock SQL）
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from core.database import init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """建立臨時測試資料庫，插入含日中英混合 tag 的測試資料"""
    db_path = tmp_path / "test_tags_top.db"
    init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # 插入 9 筆影片，各種 tags 組合
    # tag 出現次數：
    #   巨乳: 5, 高畫質: 3, DMM獨家: 2, 女教師: 2,
    #   Big Tits: 1, 単体作品: 1, 痴女: 1 (噪音 tag)
    #   空字串: 應被過濾
    videos = [
        ("file:///1.mp4", "AAA-001", '["巨乳","高畫質","DMM獨家"]'),
        ("file:///2.mp4", "AAA-002", '["巨乳","高畫質","女教師"]'),
        ("file:///3.mp4", "AAA-003", '["巨乳","高畫質","DMM獨家"]'),
        ("file:///4.mp4", "AAA-004", '["巨乳","女教師"]'),
        ("file:///5.mp4", "AAA-005", '["巨乳","Big Tits"]'),
        ("file:///6.mp4", "AAA-006", '["単体作品"]'),
        ("file:///7.mp4", "AAA-007", '["痴女"]'),
        ("file:///8.mp4", "AAA-008", '[""]'),        # 空字串 tag → 應過濾
        ("file:///9.mp4", "AAA-009", "[]"),          # 空 tags
    ]
    conn.executemany(
        "INSERT INTO videos (path, number, tags) VALUES (?, ?, ?)",
        videos,
    )
    # B3：user_tags 獨有字串不得進入 /api/tags/top；既有 9 列資料不改
    conn.execute(
        "INSERT INTO videos (path, number, tags, user_tags) VALUES (?, ?, ?, ?)",
        ("file:///10.mp4", "AAA-010", "[]", '["僅限自訂標籤ZZZ"]'),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """空資料庫（無影片）"""
    db_path = tmp_path / "test_tags_empty.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(tmp_db, monkeypatch):
    """TestClient，monkeypatch get_db_path 指向 tmp DB"""
    monkeypatch.setattr("web.routers.tags.get_db_path", lambda: tmp_db)
    from web.app import app
    return TestClient(app)


@pytest.fixture
def empty_client(empty_db, monkeypatch):
    """TestClient，指向空 DB"""
    monkeypatch.setattr("web.routers.tags.get_db_path", lambda: empty_db)
    from web.app import app
    return TestClient(app)


# ── Schema Check ──────────────────────────────────────────────────────────────

class TestResponseSchema:
    def test_required_fields_present(self, client):
        """response 必有 success / items / total_unique_tags / applied_min_count"""
        resp = client.get("/api/tags/top")
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "items" in data
        assert "total_unique_tags" in data
        assert "applied_min_count" in data


# ── Happy Path ────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_default_min_count_filters_noise(self, client):
        """預設 min_count=2：Big Tits/単体作品/痴女（各1次）不在結果中"""
        resp = client.get("/api/tags/top")
        tags = [item["tag"] for item in resp.json()["items"]]
        assert "Big Tits" not in tags
        assert "単体作品" not in tags
        assert "痴女" not in tags


    def test_top_tag_correct_count(self, client):
        """巨乳出現 5 次，應為最高頻 tag"""
        resp = client.get("/api/tags/top")
        items = resp.json()["items"]
        assert items[0]["tag"] == "巨乳"
        assert items[0]["count"] == 5


# ── min_count 邊界 ─────────────────────────────────────────────────────────────

class TestMinCount:
    def test_min_count_1_shows_all_tags(self, client):
        """min_count=1 opt-in：全部 tag 含噪音都出現"""
        resp = client.get("/api/tags/top?min_count=1")
        tags = [item["tag"] for item in resp.json()["items"]]
        assert "Big Tits" in tags
        assert "単体作品" in tags
        assert "痴女" in tags


# ── limit 邊界 ─────────────────────────────────────────────────────────────────


# ── 空 corpus ─────────────────────────────────────────────────────────────────


# ── 全噪音 corpus ─────────────────────────────────────────────────────────────

class TestAllNoisyCorpus:
    @pytest.fixture
    def noisy_db(self, tmp_path):
        """所有 tag 出現次數 = 1"""
        db_path = tmp_path / "test_noisy.db"
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.executemany(
            "INSERT INTO videos (path, number, tags) VALUES (?, ?, ?)",
            [
                ("file:///a.mp4", "NNN-001", '["tagA"]'),
                ("file:///b.mp4", "NNN-002", '["tagB"]'),
                ("file:///c.mp4", "NNN-003", '["tagC"]'),
            ],
        )
        conn.commit()
        conn.close()
        return db_path


# ── 空字串 tag 過濾 ────────────────────────────────────────────────────────────


# ── First-run（Codex P2-1）──────────────────────────────────────────────────────

class TestFirstRunNoDb:
    """Regression: AI agent 在用戶第一次跑 scan/search 前直接呼叫 /api/tags/top，
    DB 檔尚未建立 → 端點應 init_db 自救，回 success=True + 空 corpus，不噴 500。"""

    def test_first_run_db_missing_returns_empty_success(self, tmp_path, monkeypatch):
        """DB 檔不存在 → init_db 自動建表 → 回 success=True + items=[]"""
        missing_db = tmp_path / "nonexistent.db"
        assert not missing_db.exists()

        monkeypatch.setattr("web.routers.tags.get_db_path", lambda: missing_db)
        from web.app import app
        client = TestClient(app)
        resp = client.get("/api/tags/top")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["items"] == []
        assert data["total_unique_tags"] == 0
        # 端點呼叫後 DB 檔應已被建立（init_db 副作用）
        assert missing_db.exists()


# ── B3：user_tags 不進 /api/tags/top 統計 ──────────────────────────────────────

_USER_TAGS_EXCLUSIVE = "僅限自訂標籤ZZZ"


class TestUserTagsExcludedFromTop:
    def test_user_tags_exclusive_string_absent_from_top(self, client):
        """tags 欄位從未出現的 user_tags 獨有字串不得出現在 /api/tags/top。"""
        # min_count=1：若 SQL 誤讀 user_tags，count=1 也會進 items
        resp = client.get("/api/tags/top?min_count=1")
        assert resp.status_code == 200
        data = resp.json()
        tags = [item["tag"] for item in data["items"]]
        assert _USER_TAGS_EXCLUSIVE not in tags
        assert _USER_TAGS_EXCLUSIVE not in resp.text
