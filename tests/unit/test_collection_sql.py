"""
test_collection_sql.py — SQL 驗證邏輯 unit tests（全 mock，不碰 FS）

覆蓋 TASK-T5 的 41 個邊界條件。
"""

from unittest.mock import patch, MagicMock


# ── 匯入待測模組 ─────────────────────────────────────────────────────────────

def _get_validate():
    """延遲 import，讓 RED 階段的 import 錯誤只在測試函數中爆"""
    from web.routers.collection import validate_sql
    return validate_sql


# ── 層 1：SELECT 開頭 ─────────────────────────────────────────────────────────

class TestLayer1SelectOnly:


    def test_delete_rejected(self):
        validate = _get_validate()
        err = validate("DELETE FROM videos")
        assert err is not None
        assert "只允許 SELECT" in err


# ── 層 2：禁止 ; ──────────────────────────────────────────────────────────────

class TestLayer2NoSemicolon:
    def test_semicolon_mid_rejected(self):
        validate = _get_validate()
        err = validate("SELECT * FROM videos; DROP TABLE videos")
        assert err is not None
        assert "不合法" in err


# ── 層 3：PRAGMA 禁止 ─────────────────────────────────────────────────────────

class TestLayer3NoPragma:
    def test_pragma_uppercase_rejected(self):
        validate = _get_validate()
        err = validate("SELECT * FROM videos PRAGMA journal_mode")
        assert err is not None
        assert "不合法" in err


# ── 層 4：ATTACH / DETACH 禁止 ───────────────────────────────────────────────

class TestLayer4NoAttachDetach:

    def test_attach_without_semicolon_rejected(self):
        validate = _get_validate()
        # 讓層 4 觸發而非層 2
        err = validate("SELECT ATTACH DATABASE '/etc/passwd' AS pw FROM videos")
        assert err is not None
        assert "不合法" in err


# ── 層 5：sqlite_master / sqlite_schema 禁止 ─────────────────────────────────

class TestLayer5NoSqliteMaster:
    def test_sqlite_master_rejected(self):
        validate = _get_validate()
        err = validate("SELECT * FROM sqlite_master")
        assert err is not None
        assert "不合法" in err


# ── 層 6：load_extension 禁止 ─────────────────────────────────────────────────

class TestLayer6NoLoadExtension:
    def test_load_extension_lowercase_rejected(self):
        validate = _get_validate()
        err = validate("SELECT load_extension('/usr/lib/evil.so')")
        assert err is not None
        assert "不合法" in err


# ── 層 7：表白名單 ────────────────────────────────────────────────────────────

class TestLayer7TableWhitelist:
    def test_videos_allowed(self):
        validate = _get_validate()
        err = validate("SELECT * FROM videos")
        assert err is None


    def test_unknown_table_rejected(self):
        validate = _get_validate()
        err = validate("SELECT * FROM users")
        assert err is not None
        assert "不允許的資料表" in err

    def test_join_unknown_table_rejected(self):
        validate = _get_validate()
        err = validate("SELECT v.* FROM videos v JOIN users u ON v.id = u.id")
        assert err is not None
        assert "不允許的資料表" in err

    def test_json_each_tvf_allowed(self):
        """json_each 是 TVF，應略過不視為表名"""
        validate = _get_validate()
        err = validate("SELECT value FROM videos, json_each(videos.actresses)")
        assert err is None


    def test_comma_join_disallowed_table_rejected(self):
        """逗號 JOIN 的第二個表名不在白名單 → 拒絕（F1 修正）"""
        validate = _get_validate()
        err = validate("SELECT * FROM videos, evil_table")
        assert err is not None
        assert "不允許的資料表" in err


# ── 層 6.5：引號包裹識別符 ────────────────────────────────────────────────────

class TestQuotedIdentifiers:
    def test_double_quoted_table_rejected(self):
        """雙引號包裹的表名 → 拒絕（防繞過白名單）"""
        validate = _get_validate()
        err = validate('SELECT * FROM "sqlite_sequence"')
        assert err is not None
        assert "不合法" in err


# ── 層 8：DB 不存在 ───────────────────────────────────────────────────────────


# ── 層 9：結果限制 ────────────────────────────────────────────────────────────

class TestLayer9Limit:
    def _make_mock_conn(self, rows, columns=None):
        """建立 mock sqlite3 connection，回傳指定 rows"""
        conn = MagicMock()
        cursor = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        cursor.description = [(c,) for c in (columns or ["id"])]
        cursor.fetchmany.return_value = rows[:500]  # simulate fetchmany
        conn.execute.return_value = cursor
        conn.cursor.return_value = cursor
        return conn, cursor


# ── 層 11–12：錯誤訊息固定化 ──────────────────────────────────────────────────

class TestLayer11_12ErrorShielding:
    def test_syntax_error_fixed_message(self, tmp_path):
        """SQL 語法錯誤 → success=False，error 是固定字串"""
        from web.routers.collection import collection_sql, SqlRequest
        from core.database import init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)

        req = SqlRequest(sql="SELECT * FORM videos")  # 故意拼錯

        with patch("web.routers.collection.get_db_path", return_value=db_path):
            result = collection_sql(req)

        assert result["success"] is False
        assert "SQL 執行失敗" in result["error"]
        # 不應含 sqlite 原始訊息
        assert "FORM" not in result["error"]


# ── 輸入驗證 ──────────────────────────────────────────────────────────────────


# ── Happy Path（validate_sql 邏輯層面）──────────────────────────────────────


# ── 層 6.5：字串字面值含 [] 的 False Positive 修正 ──────────────────────────────

class TestLayer65StringLiterals:
    def test_string_value_with_brackets(self):
        """WHERE actresses = '[]' → 字串值含 [] 不應被擋"""
        validate = _get_validate()
        err = validate("SELECT * FROM videos WHERE actresses = '[]'")
        assert err is None


    def test_bracket_identifier_still_blocked(self):
        """SELECT * FROM [videos] → 方括號識別符仍應被擋（regression guard）"""
        validate = _get_validate()
        err = validate("SELECT * FROM [videos]")
        assert err is not None
        assert "不合法" in err


