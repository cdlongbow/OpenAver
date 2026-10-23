"""
TDD-lite — TagAliasRecord dataclass + TagAliasRepository
鏡射 test_alias_repository.py（AliasRepository 區段），無舊 schema 遷移 fixtures
"""
import pytest
import sqlite3

from core.database import init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_db(tmp_path):
    """新 schema DB（供 TagAliasRepository 單元測試隔離使用）"""
    db_path = tmp_path / "empty_tag_alias.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def repo(empty_db):
    """TagAliasRepository，使用 empty_db（無種子資料）"""
    from core.database import TagAliasRepository
    return TagAliasRepository(empty_db)


# ---------------------------------------------------------------------------
# TestTagAliasRepositoryCRUD — 初始化 + CRUD 完整循環
# ---------------------------------------------------------------------------

class TestTagAliasRepositoryCRUD:


    def test_add_and_get_all(self, repo):
        """add(primary, aliases) → get_all() 回傳 1 筆，primary/aliases 正確"""
        repo.add("TagA", ["alias1", "alias2"])
        result = repo.get_all()
        assert len(result) == 1
        assert result[0].primary_name == "TagA"
        assert "alias1" in result[0].aliases
        assert "alias2" in result[0].aliases

    def test_add_then_add_alias(self, repo):
        """add → add_alias → get_by_primary: aliases 含新 alias"""
        repo.add("TagA", ["alias1"])
        ok, msg = repo.add_alias("TagA", "alias2")
        assert ok is True
        record = repo.get_by_primary("TagA")
        assert "alias2" in record.aliases

    def test_add_then_remove_alias(self, repo):
        """add → remove_alias → get_by_primary: aliases 不含已移除 alias"""
        repo.add("TagA", ["alias1", "alias2"])
        repo.remove_alias("TagA", "alias1")
        record = repo.get_by_primary("TagA")
        assert "alias1" not in record.aliases
        assert "alias2" in record.aliases

    def test_add_then_delete(self, repo):
        """add → delete(primary) → get_by_primary 回 None"""
        repo.add("TagA", ["alias1"])
        repo.delete("TagA")
        assert repo.get_by_primary("TagA") is None


    def test_delete_by_alias(self, repo):
        """delete 透過 alias 名稱刪除 group"""
        repo.add("TagA", ["alias1"])
        result = repo.delete("alias1")
        assert result is True
        assert repo.get_by_primary("TagA") is None


    def test_find_by_alias_hit(self, repo):
        """find_by_alias 找到 alias 回傳對應 record"""
        repo.add("TagA", ["alias1", "alias2"])
        result = repo.find_by_alias("alias1")
        assert result is not None
        assert result.primary_name == "TagA"


# ---------------------------------------------------------------------------
# TestTagAliasRepositoryUniqueness — 全域唯一約束 + 跨表正交
# ---------------------------------------------------------------------------

class TestTagAliasRepositoryUniqueness:


    def test_add_primary_conflicts_with_existing_alias_raises(self, repo):
        """add("X", ["A"]) 後 add("A", [])：第二次 raise ValueError（A 已是 alias）"""
        repo.add("X", ["A"])
        with pytest.raises(ValueError):
            repo.add("A", [])


    def test_add_alias_conflicts_with_primary_name(self, repo):
        """add("X") 後 add_alias("Y", "X")：回傳 (False, msg)"""
        repo.add("X", [])
        repo.add("Y", [])
        ok, msg = repo.add_alias("Y", "X")
        assert ok is False
        assert msg is not None

    def test_cross_table_orthogonality(self, empty_db):
        """
        CD-58-3 正交性：actress_aliases 有 primary "X"；
        tag_aliases.add("X") 應成功（兩系統不相互檢查）
        """
        # 直接插入 actress_aliases
        conn = sqlite3.connect(str(empty_db))
        conn.execute(
            "INSERT INTO actress_aliases (primary_name, aliases, source) VALUES (?, ?, ?)",
            ("X", "[]", "manual"),
        )
        conn.commit()
        conn.close()

        # tag_aliases.add("X") 應成功
        from core.database import TagAliasRepository
        repo = TagAliasRepository(empty_db)
        record = repo.add("X", [])
        assert record.primary_name == "X"


# ---------------------------------------------------------------------------
# TestTagAliasRepositoryResolve — primary/alias/miss 三 case
# ---------------------------------------------------------------------------

class TestTagAliasRepositoryResolve:


    def test_resolve_alias_hit(self, repo):
        """resolve(alias) → {primary} ∪ set(aliases)（雙向解析）"""
        repo.add("A", ["B"])
        result = repo.resolve("B")
        assert result == {"A", "B"}

