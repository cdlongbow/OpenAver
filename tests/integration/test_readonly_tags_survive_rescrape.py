"""Integration test for TASK-143-T5: Readonly tags survive rescrape.

Two-stage real request integration test (spec §3.2 AC2-3):
1. POST /api/user-tags adds a tag to a readonly source video.
2. POST /api/enrich-single triggers rescrape.
Assert: Rescraped output NFO retains the tag, and DB user_tags is unchanged.
"""
from pathlib import Path

import pytest
from core.database import VideoRepository as RealRepo, init_db
from core.path_utils import uri_to_local_fs_path
from tests.integration.test_user_tags_api import setup_readonly_user_tags_env


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test_user_tags.db"
    init_db(db_path)
    return db_path


class TestReadonlyTagsSurviveRescrape:
    def test_readonly_tags_survive_rescrape(self, tmp_db, tmp_path, monkeypatch):
        client, src_dir, out_dir, file_uri = setup_readonly_user_tags_env(
            tmp_db, tmp_path, monkeypatch, with_source_nfo=False, with_output_nfo=True
        )

        fake_config = {
            "gallery": {
                "directories": [{"path": str(src_dir), "readonly": True, "output_path": ""}],
                "path_mappings": {},
            },
            "scraper": {},
        }
        monkeypatch.setattr("web.routers.scraper.load_config", lambda: fake_config)
        monkeypatch.setattr("web.routers.collection.load_config", lambda: fake_config)
        monkeypatch.setattr(
            "web.routers.scraper.VideoRepository",
            lambda *a, **kw: RealRepo(tmp_db),
        )
        monkeypatch.setattr("core.readonly_paths.get_db_path", lambda: tmp_db)
        monkeypatch.setattr("core.readonly_assets.download_image", lambda *a, **kw: False)
        # /api/enrich-single 成功後會呼叫 _reconcile_wishlist_after_write() → reconcile_wishlist()，
        # 而 WishlistRepository() 不帶參數時走 connection.get_db_path()（模組屬性、呼叫當下才解析）。
        # 不 patch 它 → 這支測試會去開**使用者真實的 output/openaver.db**，被 repo_write_guard G1 擋下。
        # ⚠️ 這條在 git worktree 裡不會紅（G1 只認真 repo 路徑），只有在主工作樹跑才看得到。
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)
        # 同一個陷阱的姊妹案例（T5 sonnet review P2）：`core/thumbnail_cache.py:22` 是
        # `from core.database import get_db_path`——**import 當下就複製了參照**，
        # 所以 patch `core.database.connection.get_db_path` 對它完全無效
        # （實測：patch 後 `thumbnail_cache.get_db_path()` 仍回真實 repo 路徑）。
        # 不 patch 它 → enrich 成功後的 `thumbnail_cache.invalidate()` 會對專案真實的
        # `output/thumb/` 做 unlink。目前因為檔名是 sha1(合成 tmp 路徑) 且 missing_ok=True
        # 所以靜默 no-op、測試照樣綠——**這正是它危險的地方**，必須顯式擋掉。
        monkeypatch.setattr("core.thumbnail_cache.get_db_path", lambda: tmp_db)

        # ① 加標籤
        resp1 = client.post("/api/user-tags", json={"file_path": file_uri, "add": ["SURVIVE"]})
        assert resp1.status_code == 200
        assert resp1.json()["success"] is True

        repo = RealRepo(tmp_db)
        assert repo.get_by_path(file_uri).user_tags == ["SURVIVE"]

        # ② 觸發重刮
        resp2 = client.post(
            "/api/enrich-single",
            json={
                "file_path": file_uri,
                "number": "TEST-001",
                "readonly_action": "rescrape",
                "mode": "refresh_full",
                "overwrite_existing": True,
                "metadata": {"number": "TEST-001", "title": "Rescraped Title"},
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True

        # 斷言：從 DB 讀出 output_dir，找到重刮後的 NFO
        row = repo.get_by_path(file_uri)
        assert row is not None
        output_dir_fs = Path(uri_to_local_fs_path(row.output_dir, {}))
        nfo_files = list(output_dir_fs.glob("*.nfo"))
        assert len(nfo_files) >= 1
        nfo_content = nfo_files[0].read_text(encoding="utf-8")
        assert "<user_tag>SURVIVE</user_tag>" in nfo_content

        # DB 值沒有被這次重刮改變（維持保留語意）
        assert repo.get_by_path(file_uri).user_tags == ["SURVIVE"]

    def test_readonly_rescrape_preserve_title_keeps_title_single_prefix(self, tmp_db, tmp_path, monkeypatch):
        """TASK-154a-T1: 唯讀重刮 preserve_title=True 時，保留既有標題（只有一層番號前綴），其他欄位為新值。"""
        import xml.etree.ElementTree as ET

        client, src_dir, out_dir, file_uri = setup_readonly_user_tags_env(
            tmp_db, tmp_path, monkeypatch, with_source_nfo=False, with_output_nfo=True
        )

        fake_config = {
            "gallery": {
                "directories": [{"path": str(src_dir), "readonly": True, "output_path": ""}],
                "path_mappings": {},
            },
            "scraper": {},
        }
        monkeypatch.setattr("web.routers.scraper.load_config", lambda: fake_config)
        monkeypatch.setattr("web.routers.collection.load_config", lambda: fake_config)
        monkeypatch.setattr(
            "web.routers.scraper.VideoRepository",
            lambda *a, **kw: RealRepo(tmp_db),
        )
        monkeypatch.setattr("core.readonly_paths.get_db_path", lambda: tmp_db)
        monkeypatch.setattr("core.readonly_assets.download_image", lambda *a, **kw: False)
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)
        monkeypatch.setattr("core.thumbnail_cache.get_db_path", lambda: tmp_db)

        # 初始狀態：DB 既有列 title="[TEST-001]中文片名"，original_title="旧原題"
        repo = RealRepo(tmp_db)
        existing = repo.get_by_path(file_uri)
        existing.title = "[TEST-001]中文片名"
        existing.original_title = "旧原題"
        repo.upsert(existing)

        # 觸發重刮：preserve_title=True，scraper 回傳 title="日文片名", original_title="新日文原題"
        resp = client.post(
            "/api/enrich-single",
            json={
                "file_path": file_uri,
                "number": "TEST-001",
                "readonly_action": "rescrape",
                "mode": "refresh_full",
                "overwrite_existing": True,
                "preserve_title": True,
                "metadata": {
                    "number": "TEST-001",
                    "title": "日文片名",
                    "original_title": "新日文原題",
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # (a) 輸出 NFO <title> == "[TEST-001]中文片名"（只有一層）
        # (c) NFO <originaltitle> 為本次刮到的新值
        row = repo.get_by_path(file_uri)
        assert row is not None
        output_dir_fs = Path(uri_to_local_fs_path(row.output_dir, {}))
        nfo_files = list(output_dir_fs.glob("*.nfo"))
        assert len(nfo_files) >= 1
        root = ET.parse(nfo_files[0]).getroot()
        assert root.findtext("title") == "[TEST-001]中文片名"
        assert root.findtext("originaltitle") == "新日文原題"

        # (b) DB title 逐字 == "[TEST-001]中文片名"
        # (c) DB original_title 為本次刮到的新值
        assert row.title == "[TEST-001]中文片名"
        assert row.original_title == "新日文原題"

    def test_readonly_rescrape_preserve_title_scraped_number_mismatch_uses_new_title(
        self, tmp_db, tmp_path, monkeypatch
    ):
        """Codex PR#202 P2：真實前端 confirm 流程不帶 `metadata`（見
        web/static/js/shared/state-rescrape.js rescrapeConfirm 的 fetch body），
        後端會獨立重新搜尋一次（core.readonly_producer.resolve_ingest_plan 的
        rescrape 分支）——這次搜尋回傳的番號可能與既有番號不同（auto 來源可能
        命中不同 provider／正規化結果，不受前端 numberChanged 檢查保護）。preserve_title=True
        時仍必須偵測這個不一致並回退新標題，不可把舊標題文字配上新番號寫進
        NFO／DB。"""
        import xml.etree.ElementTree as ET

        client, src_dir, out_dir, file_uri = setup_readonly_user_tags_env(
            tmp_db, tmp_path, monkeypatch, with_source_nfo=False, with_output_nfo=True
        )

        fake_config = {
            "gallery": {
                "directories": [{"path": str(src_dir), "readonly": True, "output_path": ""}],
                "path_mappings": {},
            },
            "scraper": {},
        }
        monkeypatch.setattr("web.routers.scraper.load_config", lambda: fake_config)
        monkeypatch.setattr("web.routers.collection.load_config", lambda: fake_config)
        monkeypatch.setattr(
            "web.routers.scraper.VideoRepository",
            lambda *a, **kw: RealRepo(tmp_db),
        )
        monkeypatch.setattr("core.readonly_paths.get_db_path", lambda: tmp_db)
        monkeypatch.setattr("core.readonly_assets.download_image", lambda *a, **kw: False)
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: tmp_db)
        monkeypatch.setattr("core.thumbnail_cache.get_db_path", lambda: tmp_db)

        # 初始狀態：DB 既有列 number="TEST-001"，title="[TEST-001]中文片名"
        repo = RealRepo(tmp_db)
        existing = repo.get_by_path(file_uri)
        existing.title = "[TEST-001]中文片名"
        existing.original_title = "旧原題"
        repo.upsert(existing)

        # 獨立重新搜尋（無 metadata）回傳的番號與既有列不同（刮到另一部片）
        monkeypatch.setattr(
            "core.readonly_producer.search_jav",
            lambda *a, **kw: {
                "number": "OTHER-777",
                "title": "刮到別部片的新標題",
                "original_title": "新日文原題",
            },
        )

        # 觸發重刮：preserve_title=True，不帶 metadata（鏡射前端 rescrapeConfirm 的真實請求形狀）
        resp = client.post(
            "/api/enrich-single",
            json={
                "file_path": file_uri,
                "number": "TEST-001",
                "readonly_action": "rescrape",
                "mode": "refresh_full",
                "overwrite_existing": True,
                "preserve_title": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        row = repo.get_by_path(file_uri)
        assert row is not None
        output_dir_fs = Path(uri_to_local_fs_path(row.output_dir, {}))
        nfo_files = list(output_dir_fs.glob("*.nfo"))
        assert len(nfo_files) >= 1
        root = ET.parse(nfo_files[0]).getroot()
        # 番號不一致 → 不保留舊標題，NFO 用新番號＋新標題，不是「[OTHER-777][TEST-001]中文片名」
        assert root.findtext("title") == "[OTHER-777]刮到別部片的新標題"
        assert row.title == "刮到別部片的新標題"
