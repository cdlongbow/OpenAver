"""
test_alias_api.py — 女優別名 API 整合測試

端點：
    GET    /api/actress-aliases                   列出所有別名組
    GET    /api/actress-aliases/{name}            查單一別名組（primary 或 alias 查）
    POST   /api/actress-aliases/search-online     線上搜尋建議別名
    POST   /api/actress-aliases                   新增別名組
    DELETE /api/actress-aliases/{name}            刪除別名組
    POST   /api/actress-aliases/{name}/alias      為 group 新增 alias
    DELETE /api/actress-aliases/{name}/alias/{a} 移除單一 alias

策略：TestClient + mock AliasRepository（monkeypatch）。不使用真實 DB。
"""

from collections import namedtuple
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers — 建立測試用 AliasRecord-like object
# ---------------------------------------------------------------------------

def _make_record(primary_name, aliases=None, source="manual",
                 created_at=None, updated_at=None):
    """建立符合 AliasRecord 介面的 MagicMock"""
    record = MagicMock()
    record.primary_name = primary_name
    record.aliases = aliases or []
    record.source = source
    record.applied_count = 0
    record.created_at = created_at or datetime(2026, 4, 13)
    record.updated_at = updated_at
    return record


ProfileResult = namedtuple("ProfileResult", ["data", "timed_out"])


# ---------------------------------------------------------------------------
# Fixture: client with mocked AliasRepository
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_repo():
    """回傳一個 MagicMock AliasRepository"""
    return MagicMock()


@pytest.fixture
def client(mock_repo, monkeypatch):
    """
    TestClient — monkeypatch AliasRepository constructor 回傳 mock_repo。
    """
    monkeypatch.setattr(
        "web.routers.actress_alias.AliasRepository",
        lambda *args, **kwargs: mock_repo,
    )
    monkeypatch.setattr(
        "web.routers.actress_alias.init_db",
        lambda *args, **kwargs: None,
    )
    from web.app import app
    return TestClient(app)


# ===========================================================================
# GET /api/actress-aliases — 列出所有別名組
# ===========================================================================

class TestListAliases:
    """GET /api/actress-aliases"""


    def test_returns_all_records(self, client, mock_repo):
        """兩筆資料 → total=2，每筆含 primary_name / aliases / source"""
        records = [
            _make_record("橋本ありな", ["新ありな"]),
            _make_record("三上悠亜", ["鬼頭桃菜"]),
        ]
        mock_repo.get_all.return_value = records
        resp = client.get("/api/actress-aliases")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["groups"]) == 2
        names = [g["primary_name"] for g in data["groups"]]
        assert "橋本ありな" in names
        assert "三上悠亜" in names


# ===========================================================================
# GET /api/actress-aliases/{name} — 查單一別名組
# ===========================================================================

class TestGetOneAlias:
    """GET /api/actress-aliases/{name}"""


    def test_alias_hit(self, client, mock_repo):
        """name = alias → get_by_primary miss → find_by_alias hit"""
        record = _make_record("橋本ありな", ["新ありな"])
        mock_repo.get_by_primary.return_value = None
        mock_repo.find_by_alias.return_value = record
        resp = client.get("/api/actress-aliases/新ありな")
        assert resp.status_code == 200
        data = resp.json()
        assert data["group"]["primary_name"] == "橋本ありな"


# ===========================================================================
# POST /api/actress-aliases/search-online — 線上搜尋建議別名
# NOTE: 靜態路徑，必須在 /{name} 之前定義
# ===========================================================================

class TestSearchOnline:
    """POST /api/actress-aliases/search-online"""


    def test_success_with_str_aliases(self, client, mock_repo, monkeypatch):
        """orchestrator 回傳 str list aliases → suggested_aliases 是 str list"""
        profile_data = {
            "name": "橋本ありな",
            "text": {
                "aliases": ["新ありな", "アリス"]
            }
        }
        monkeypatch.setattr(
            "web.routers.actress_alias.get_actress_profile",
            lambda *a, **kw: ProfileResult(data=profile_data, timed_out=False),
        )
        resp = client.post("/api/actress-aliases/search-online", json={"name": "橋本ありな"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "新ありな" in data["suggested_aliases"]
        assert "アリス" in data["suggested_aliases"]


# ===========================================================================
# POST /api/actress-aliases — 新增別名組
# ===========================================================================

class TestCreateAliasGroup:
    """POST /api/actress-aliases"""

    def test_success_with_aliases(self, client, mock_repo):
        """成功建立 group → 200 + {success: true, group: {...}}"""
        record = _make_record("橋本ありな", ["新ありな"])
        mock_repo.add.return_value = record
        resp = client.post("/api/actress-aliases", json={
            "primary_name": "橋本ありな",
            "aliases": ["新ありな"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["group"]["primary_name"] == "橋本ありな"


    def test_primary_conflict_returns_400(self, client, mock_repo):
        """primary_name 已存在為其他 group 的 primary → repo.add raises ValueError → 400"""
        mock_repo.add.side_effect = ValueError("primary_name '橋本ありな' 已被使用")
        resp = client.post("/api/actress-aliases", json={"primary_name": "橋本ありな"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "error" in data


# ===========================================================================
# DELETE /api/actress-aliases/{name} — 刪除別名組
# ===========================================================================

class TestDeleteAliasGroup:
    """DELETE /api/actress-aliases/{name}"""

    def test_delete_by_primary(self, client, mock_repo):
        """name = primary → repo.delete 回 True → 200"""
        mock_repo.delete.return_value = True
        resp = client.delete("/api/actress-aliases/橋本ありな")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# POST /api/actress-aliases/{name}/alias — 為 group 新增 alias
# ===========================================================================

class TestAddAlias:
    """POST /api/actress-aliases/{name}/alias"""

    def test_success(self, client, mock_repo):
        """成功新增 → 200 + {success: true, group: {...}}"""
        record = _make_record("橋本ありな", ["新ありな"])
        mock_repo.get_by_primary.return_value = record
        mock_repo.add_alias.return_value = (True, None)
        # re-read record after add
        mock_repo.get_by_primary.side_effect = [
            record,   # 第一次：確認 group 存在
            _make_record("橋本ありな", ["新ありな", "アリス"]),  # 第二次：re-read
        ]
        resp = client.post("/api/actress-aliases/橋本ありな/alias", json={"alias": "アリス"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "group" in data


    def test_alias_conflict_returns_400(self, client, mock_repo):
        """alias 已屬其他 group → add_alias 回 (False, msg) → 400"""
        record = _make_record("橋本ありな", [])
        mock_repo.get_by_primary.return_value = record
        mock_repo.add_alias.return_value = (False, "alias 'アリス' 已屬於其他 group")
        resp = client.post("/api/actress-aliases/橋本ありな/alias", json={"alias": "アリス"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "error" in data


# ===========================================================================
# DELETE /api/actress-aliases/{name}/alias/{alias} — 移除單一 alias
# ===========================================================================

