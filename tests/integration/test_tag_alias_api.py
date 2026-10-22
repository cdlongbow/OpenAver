"""
test_tag_alias_api.py — Tag 別名 API 整合測試

端點：
    GET    /api/tag-aliases                   列出所有別名組
    POST   /api/tag-aliases                   新增別名組
    GET    /api/tag-aliases/{name}            查單一別名組（primary 或 alias 查）
    DELETE /api/tag-aliases/{name}            刪除別名組
    POST   /api/tag-aliases/{name}/alias      為 group 新增 alias
    DELETE /api/tag-aliases/{name}/alias/{a}  移除單一 alias

策略：TestClient + mock TagAliasRepository（monkeypatch）。不使用真實 DB。
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers — 建立測試用 TagAliasRecord-like object
# ---------------------------------------------------------------------------

def _make_record(primary_name, aliases=None, source="manual",
                 created_at=None, updated_at=None):
    """建立符合 TagAliasRecord 介面的 MagicMock"""
    record = MagicMock()
    record.primary_name = primary_name
    record.aliases = aliases or []
    record.source = source
    record.created_at = created_at or datetime(2026, 4, 13)
    record.updated_at = updated_at
    return record


# ---------------------------------------------------------------------------
# Fixture: client with mocked TagAliasRepository
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_repo():
    """回傳一個 MagicMock TagAliasRepository"""
    return MagicMock()


@pytest.fixture
def client(mock_repo, monkeypatch):
    """
    TestClient — monkeypatch TagAliasRepository constructor 回傳 mock_repo。
    """
    monkeypatch.setattr(
        "web.routers.tag_alias.TagAliasRepository",
        lambda *args, **kwargs: mock_repo,
    )
    monkeypatch.setattr(
        "web.routers.tag_alias.init_db",
        lambda *args, **kwargs: None,
    )
    from web.app import app
    return TestClient(app)


# ===========================================================================
# TestTagAliasListAndCreate
# ===========================================================================

class TestTagAliasListAndCreate:
    """GET /api/tag-aliases 及 POST /api/tag-aliases"""

    # --- GET --- list


    def test_list_returns_all_records(self, client, mock_repo):
        """兩筆資料 → total=2，每筆含 primary_name / aliases / source"""
        records = [
            _make_record("美少女", ["kawaii", "loli"]),
            _make_record("巨乳", ["big-boobs"]),
        ]
        mock_repo.get_all.return_value = records
        resp = client.get("/api/tag-aliases")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["groups"]) == 2
        names = [g["primary_name"] for g in data["groups"]]
        assert "美少女" in names
        assert "巨乳" in names

    # --- POST --- create

    def test_create_success_with_aliases(self, client, mock_repo):
        """成功建立 group → 200 + {success: true, group: {...}}"""
        record = _make_record("美少女", ["kawaii"])
        mock_repo.add.return_value = record
        resp = client.post("/api/tag-aliases", json={
            "primary_name": "美少女",
            "aliases": ["kawaii"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["group"]["primary_name"] == "美少女"


    def test_create_conflict_fixed_message(self, client, mock_repo):
        """衝突 error 固定中文訊息，不 leak str(exc)"""
        mock_repo.add.side_effect = ValueError("這是 repo 內部訊息")
        resp = client.post("/api/tag-aliases", json={"primary_name": "美少女"})
        assert resp.status_code == 409
        error_msg = resp.json()["error"]
        assert error_msg == "Tag 別名衝突（名字已屬其他組）"
        assert "這是 repo 內部訊息" not in error_msg


# ===========================================================================
# TestTagAliasGetByName
# ===========================================================================

class TestTagAliasGetByName:
    """GET /api/tag-aliases/{name}"""


    def test_alias_hit(self, client, mock_repo):
        """name = alias → get_by_primary miss → find_by_alias hit"""
        record = _make_record("美少女", ["kawaii"])
        mock_repo.get_by_primary.return_value = None
        mock_repo.find_by_alias.return_value = record
        resp = client.get("/api/tag-aliases/kawaii")
        assert resp.status_code == 200
        data = resp.json()
        assert data["group"]["primary_name"] == "美少女"


# ===========================================================================
# TestTagAliasDelete
# ===========================================================================

class TestTagAliasDelete:
    """DELETE /api/tag-aliases/{name}"""

    def test_delete_by_primary(self, client, mock_repo):
        """name = primary → repo.delete 回 True → 200"""
        mock_repo.delete.return_value = True
        resp = client.delete("/api/tag-aliases/美少女")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# TestTagAliasAddRemoveAlias
# ===========================================================================

class TestTagAliasAddRemoveAlias:
    """POST /api/tag-aliases/{name}/alias 及 DELETE /api/tag-aliases/{name}/alias/{alias}"""

    # --- POST --- add alias

    def test_add_alias_success(self, client, mock_repo):
        """成功新增 → 200 + {success: true, group: {...}}"""
        record = _make_record("美少女", ["kawaii"])
        mock_repo.get_by_primary.side_effect = [
            record,   # 第一次：確認 group 存在
            _make_record("美少女", ["kawaii", "loli"]),  # 第二次：re-read
        ]
        mock_repo.add_alias.return_value = (True, None)
        resp = client.post("/api/tag-aliases/美少女/alias", json={"alias": "loli"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "group" in data


    def test_add_alias_conflict_fixed_message(self, client, mock_repo):
        """衝突 error 固定中文訊息，不 leak repo 的 msg"""
        record = _make_record("美少女", [])
        mock_repo.get_by_primary.return_value = record
        internal_msg = "alias 'loli' 已屬於其他 group 這是內部訊息"
        mock_repo.add_alias.return_value = (False, internal_msg)
        resp = client.post("/api/tag-aliases/美少女/alias", json={"alias": "loli"})
        assert resp.status_code == 409
        error_msg = resp.json()["error"]
        assert error_msg == "Tag 別名衝突（名字已屬其他組）"
        assert internal_msg not in error_msg


    # --- DELETE --- remove alias

    def test_remove_alias_success(self, client, mock_repo):
        """成功移除 → 200 + {success: true}"""
        record = _make_record("美少女", ["kawaii"])
        mock_repo.get_by_primary.return_value = record
        mock_repo.remove_alias.return_value = True
        resp = client.delete("/api/tag-aliases/美少女/alias/kawaii")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# TestTagAliasErrorMasking — CD-58-14：驗證 error response 不含 str(exc) leak
# ===========================================================================

class TestTagAliasErrorMasking:
    """CD-58-14：所有端點 error 訊息不 leak 內部 exception 訊息"""


    def test_500_does_not_leak_exception_message(self, client, mock_repo):
        """
        各端點 except Exception → 500 response["error"] == "操作失敗"，不含 Python exception 訊息
        """
        internal_msg = "internal DB error XYZ-secret"
        mock_repo.get_all.side_effect = RuntimeError(internal_msg)
        resp = client.get("/api/tag-aliases")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "操作失敗"
        assert internal_msg not in str(data)
        assert "XYZ-secret" not in str(data)
