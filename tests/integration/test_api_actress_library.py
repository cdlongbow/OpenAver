"""tests/integration/test_api_actress_library.py — TASK-117-T1

GET /api/actresses/library 端點行為：回應形狀、is_favorite/primary_name 判定、
路由順序（不被 {name} 捕捉）、無網路呼叫。
"""
import sqlite3

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.database import Actress, ActressRepository, AliasRepository, Video, VideoRepository, init_db
from core.path_utils import to_file_uri


def _video(path_suffix: str, actresses: list, number: str = None) -> Video:
    return Video(
        path=to_file_uri(f"/test/{path_suffix}.mp4"),
        number=number or path_suffix.upper(),
        title=path_suffix,
        actresses=actresses,
    )


@pytest.fixture
def tmp_db(tmp_path):
    """建立臨時測試資料庫（空 DB，無預置資料）"""
    db_path = tmp_path / "test_actress_library.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(tmp_db, monkeypatch):
    """TestClient，monkeypatch get_db_path 指向 tmp DB（比照 test_api_actress.py 既有慣例）"""
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)

    from web.app import app
    return TestClient(app)


class TestLibraryActressesEndpoint:
    """GET /api/actresses/library 測試"""

    def test_response_shape(self, client, tmp_db):
        """回應外層形狀 {success, actresses, total}；每筆含四個定死欄位"""
        VideoRepository(tmp_db).upsert(_video("v1", ["Alice"]))

        resp = client.get("/api/actresses/library")

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"success", "actresses", "total"}
        assert data["success"] is True
        assert data["total"] == len(data["actresses"])
        item = data["actresses"][0]
        assert set(item.keys()) == {"primary_name", "names", "video_count", "is_favorite"}

    def test_not_captured_by_name_route(self, client, tmp_db):
        """路由順序守衛：/library 必須定義在 GET /{name} 之前——回 200 + actresses/total，
        不得回 404 或「查無此女優」語意（證明沒有被 {name} 捕捉路由攔截）"""
        resp = client.get("/api/actresses/library")

        assert resp.status_code == 200
        data = resp.json()
        assert "actresses" in data
        assert "total" in data
        assert data.get("error") != "not_found"

    def test_no_network_calls(self, client, tmp_db):
        """patch get_cached_profile / get_actress_profile 為呼叫就 raise，端點仍需 200
        ——證明這條路徑完全不碰 orchestrator（AC-1.6 後端半場）"""
        VideoRepository(tmp_db).upsert(_video("v1", ["Alice"]))

        with patch(
            "web.routers.actress.get_cached_profile",
            side_effect=AssertionError("must not call orchestrator"),
        ), patch(
            "web.routers.actress.get_actress_profile",
            side_effect=AssertionError("must not call orchestrator"),
        ):
            resp = client.get("/api/actresses/library")

        assert resp.status_code == 200

    def test_is_favorite_true_when_favorited(self, client, tmp_db):
        ActressRepository(tmp_db).save(Actress(name="Alice"))
        VideoRepository(tmp_db).upsert(_video("v1", ["Alice"]))

        resp = client.get("/api/actresses/library")

        item = next(a for a in resp.json()["actresses"] if a["primary_name"] == "Alice")
        assert item["is_favorite"] is True

    def test_is_favorite_false_when_not_favorited(self, client, tmp_db):
        VideoRepository(tmp_db).upsert(_video("v1", ["Bob"]))

        resp = client.get("/api/actresses/library")

        item = next(a for a in resp.json()["actresses"] if a["primary_name"] == "Bob")
        assert item["is_favorite"] is False

    def test_is_favorite_false_after_unfavorite_with_alias_record_remaining(self, client, tmp_db):
        """收藏 → alias 記錄建立 → DELETE 取消收藏（delete_by_name 只刪 actresses 表，
        不動 actress_aliases 表）→ GET /library：is_favorite 必須是 False。"""
        ActressRepository(tmp_db).save(Actress(name="橋本ありな"))
        AliasRepository(tmp_db).add(primary_name="橋本ありな", aliases=["新ありな"])
        VideoRepository(tmp_db).upsert(_video("v1", ["新ありな"]))

        with patch("web.routers.actress.delete_local_photo", return_value=True):
            del_resp = client.delete("/api/actresses/橋本ありな")
        assert del_resp.status_code == 200

        resp = client.get("/api/actresses/library")
        item = next(a for a in resp.json()["actresses"] if a["primary_name"] == "橋本ありな")
        assert item["is_favorite"] is False

    def test_is_favorite_true_via_manually_grouped_favorited_alias(self, client, tmp_db):
        """Codex PR review P2（已查證屬實）：別名管理 UI（POST /api/actress-aliases）允許
        使用者自己打任意 primary_name，不要求它是已收藏女優。「A 是使用者手打的 group
        primary（未收藏）、B 是已收藏女優的正式名、B 被加成 A 的 alias」是合法可產的資料
        形狀。GET /library 該列必須判定為已收藏，且顯示名是 B（AC-3.1），不是使用者手打
        的 A。"""
        ActressRepository(tmp_db).save(Actress(name="B已收藏"))
        AliasRepository(tmp_db).add(primary_name="A手打的別名組", aliases=["B已收藏"])
        VideoRepository(tmp_db).upsert(_video("v1", ["A手打的別名組"]))

        resp = client.get("/api/actresses/library")

        names = [a["primary_name"] for a in resp.json()["actresses"]]
        assert "A手打的別名組" not in names
        item = next(a for a in resp.json()["actresses"] if a["primary_name"] == "B已收藏")
        assert item["is_favorite"] is True
        assert set(item["names"]) == {"A手打的別名組", "B已收藏"}

    def test_excludes_zero_video_favorite(self, client, tmp_db):
        """AC-2.7：收藏但庫內 0 片的女優不出現在回應中"""
        ActressRepository(tmp_db).save(Actress(name="無片女優"))

        resp = client.get("/api/actresses/library")

        names = [a["primary_name"] for a in resp.json()["actresses"]]
        assert "無片女優" not in names

    def test_library_non_2xx_when_pairs_query_fails(self, tmp_db, monkeypatch):
        """DB 層 get_video_actress_pairs 丟 OperationalError → 端點必須非 2xx，
        不可回 200 + 空清單（前端 !resp.ok →「載入失敗」）。Codex PR#133 finding A。

        raise_server_exceptions=False：讓 TestClient 回 HTTP 狀態碼而非把例外再拋給測試。
        注入點必須走真實 except 分支（execute 失敗），且只打 pairs 的 json_each SQL——
        勿連 get_all 一起炸掉，否則 mutation 改回 return [] 時後續 get_all 仍會 500、
        測試假綠。
        """
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)

        real_get = ActressRepository._get_connection

        class _FailPairsConn:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                if "json_each(videos.actresses)" in sql:
                    raise sqlite3.OperationalError("simulated json_each failure")
                return self._real.execute(sql, *args, **kwargs)

            def close(self):
                return self._real.close()

            def __getattr__(self, name):
                return getattr(self._real, name)

        monkeypatch.setattr(
            ActressRepository,
            "_get_connection",
            lambda self: _FailPairsConn(real_get(self)),
        )

        from web.app import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/actresses/library")

        assert not (200 <= resp.status_code < 300), (
            f"query failure must not be 2xx (got {resp.status_code}); "
            "old swallow-to-[] path returned 200 + empty list"
        )
        # 明確否定舊契約：200 + {actresses:[], total:0}
        if resp.status_code == 200:
            data = resp.json()
            assert not (data.get("actresses") == [] and data.get("total") == 0)
