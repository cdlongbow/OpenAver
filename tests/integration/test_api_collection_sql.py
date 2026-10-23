"""
test_api_collection_sql.py — POST /api/collection/sql 端點整合測試

使用 FastAPI TestClient + tmp_path 真實 SQLite DB。
"""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from core.database import init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """建立臨時測試資料庫，插入少量測試資料"""
    db_path = tmp_path / "test_collection.db"
    init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # 插入測試影片
    conn.execute("""
        INSERT INTO videos (path, number, title, actresses, maker, tags, duration, size_bytes)
        VALUES
        ('file:///test/SONE-205.mp4', 'SONE-205', 'Test Title 1',
         '["明日花キララ"]', 'Sony', '["巨乳"]', 7200, 4000000000),
        ('file:///test/ABW-001.mp4', 'ABW-001', 'Test Title 2',
         '["葵つかさ","橋本ありな"]', 'ABC', '["女教師"]', 6000, 3500000000),
        ('file:///test/FC2-PPV-1234567.mp4', 'FC2-PPV-1234567', 'Test Title 3',
         '[]', 'FC2', '[]', 3600, 1000000000)
    """)

    # 插入測試別名（新 schema）
    conn.execute("""
        INSERT OR IGNORE INTO actress_aliases (primary_name, aliases, source)
        VALUES ('新ありな', '["橋本ありな"]', 'manual')
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def client(tmp_db, monkeypatch):
    """TestClient，monkeypatch get_db_path 指向 tmp DB"""
    monkeypatch.setattr("web.routers.collection.get_db_path", lambda: tmp_db)

    from web.app import app
    return TestClient(app)


# ── Happy Path ────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_count_all_videos(self, client):
        """SELECT COUNT(*) → success=True，count=1，columns=['total']"""
        resp = client.post("/api/collection/sql", json={
            "sql": "SELECT COUNT(*) as total FROM videos"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["columns"] == ["total"]
        assert len(data["rows"]) == 1
        assert data["rows"][0][0] == 3  # 3 筆測試資料
        assert data["count"] == 1


# ── Security Reject Cases ─────────────────────────────────────────────────────

class TestSecurityRejects:
    def test_insert_rejected_400(self, client):
        """INSERT → 400，error 含 '只允許 SELECT'"""
        resp = client.post("/api/collection/sql", json={
            "sql": "INSERT INTO videos (path) VALUES ('x')"
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "只允許 SELECT" in data["error"]


# ── DB 不存在 ─────────────────────────────────────────────────────────────────


# ── Limit Capping ─────────────────────────────────────────────────────────────


# ── Security Layer 8：PRAGMA 設定驗證（BC28 / BC33）────────────────────────────

class TestLayer8Pragmas:
    """BC28 / BC33 — 驗證 SQLite 連線的 PRAGMA 設定被正確套用（F4 修正）"""

    def _make_mock_conn_with_pragma_tracking(self):
        """
        建立 MagicMock connection，追蹤所有 execute 呼叫的 SQL 語句。
        回傳 (mock_conn, executed_stmts_list)。
        """
        executed_stmts = []
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = [("total",)]
        mock_cursor.fetchmany.return_value = [[1]]

        def track_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt.strip())
            return mock_cursor

        mock_conn.execute.side_effect = track_execute
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        return mock_conn, executed_stmts

    def test_bc28_query_only_pragma_is_set(self, tmp_db, monkeypatch):
        """BC28：驗證 PRAGMA query_only = ON 的 execute 被呼叫（F4 修正）"""
        monkeypatch.setattr("web.routers.collection.get_db_path", lambda: tmp_db)

        mock_conn, executed_stmts = self._make_mock_conn_with_pragma_tracking()

        with patch("sqlite3.connect", return_value=mock_conn):
            from web.app import app
            test_client = TestClient(app)
            resp = test_client.post("/api/collection/sql", json={
                "sql": "SELECT COUNT(*) as total FROM videos"
            })

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 確認 PRAGMA query_only = ON 被呼叫
        query_only_calls = [s for s in executed_stmts if "query_only" in s.lower()]
        assert query_only_calls, (
            f"PRAGMA query_only = ON 未被設定；執行的語句: {executed_stmts}"
        )
        assert any("ON" in s.upper() for s in query_only_calls), (
            f"query_only 值不是 ON：{query_only_calls}"
        )


