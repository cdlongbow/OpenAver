"""
test_enrich_single_readonly_metadata.py - TASK-135-T6

覆蓋 POST /api/enrich-single 唯讀來源 ＋ rescrape ＋ metadata 這條路徑的接線與
新增的番號守衛（DoD-1~DoD-7，見 feature/135-ai-reviewed-metadata/TASK-135-T6.md）。

- DoD-1（接線本體）：真檔案 E2E，輸出夾 NFO 含 AI 給的值 ＋ 原始檔零寫入
- DoD-2（只驗不洗）：`scraper_data` 逐字等於 `metadata`（含 number），不經清洗
- DoD-3（ingest+metadata → 400，回歸鎖）
- DoD-4（缺欄位／型別 → 400，回歸鎖）
- DoD-5（番號守衛比對 metadata['number']，本 task 新程式碼）：
    5a 不符→400／5b 帶 allow_number_change→放行／5c DB 查無→不擋／
    5d 頂層 number 打錯但 metadata 對→放行
- DoD-6（write_nfo=false 維持既有 200，回歸鎖）
- DoD-7（互斥在唯讀檔案上成立，回歸鎖）
"""

import hashlib
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.database import Video
from core.path_utils import coerce_to_file_uri

# TASK-141a-T5：本檔測的兩支端點（generate_avlist / enrich_single_endpoint）收尾會
# 無條件呼叫 reconcile_wishlist()，它用無參數 repo ⇒ 解析到真實 DB。逐檔明示 opt-in
# 隔離（fixture 定義見 tests/conftest.py，刻意不做成 autouse——見該處說明）。
pytestmark = pytest.mark.usefixtures("isolate_reconcile_db")



@pytest.fixture(autouse=True)
def reset_buffer():
    """通知 buffer 是模組層級全域 deque，測試間必須清空，否則「恰好一筆」會閃爍。"""
    import web.routers.notifications as notif_mod
    notif_mod._notifications.clear()
    notif_mod._read_ids.clear()
    yield
    notif_mod._notifications.clear()
    notif_mod._read_ids.clear()



# ── mock-only 佈局（DoD-3/4/5/6/7）：照抄 tests/integration/test_api_enrich.py
# 的 _owning_stub / TestEnrichSingleReadonlyGuard._mock_routing 慣例 ─────────

def _owning_stub(path="/tmp/ro_src", output_root="/out/ro_src-abcdef", output_uri="file:///out/ro_src-abcdef"):
    """`resolve_owning_output_root` 的成功回傳 stub：(source, output_root, output_uri)。"""
    source = MagicMock()
    source.path = path
    return (source, output_root, output_uri)


_ENRICH_RESULT_KEYS = {
    'success', 'nfo_written', 'cover_written', 'extrafanart_written',
    'fields_filled', 'source_used', 'error', 'reason',
}


# ── 真檔案 E2E 佈局（DoD-1/DoD-2）：照抄 test_api_enrich.py 的
# _e2e_off_config / _e2e_snapshot / _e2e_download_writes_url_bytes /
# TestReadonlyRoutingE2E._wire/_init_db/_repo（module-level 函式搬進本檔，
# 不 import 另一個測試模組）────────────────────────────────────────────────

def _e2e_off_config(src_path):
    return {
        "gallery": {
            "directories": [{"path": str(src_path), "readonly": True}],
            "path_mappings": {},
        },
        "scraper": {
            "external_manager": "off",
            "folder_layers": [],
            "folder_format": "",
            "filename_format": "{num}",
            "max_title_length": 50,
            "max_filename_length": 60,
            "suffix_keywords": [],
        },
        "search": {"proxy_url": ""},
    }


def _e2e_snapshot(root):
    snap = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fp = Path(dirpath) / f
            st = fp.stat()
            digest = hashlib.sha256(fp.read_bytes()).hexdigest()
            snap[str(fp.relative_to(root))] = (st.st_size, st.st_mtime_ns, digest, st.st_ino)
    return snap


def _e2e_fake_generate_jellyfin_images(cover_fs, base_stem, **_kw):
    Path(base_stem + "-poster.jpg").write_bytes(b"POSTER")
    Path(base_stem + "-fanart.jpg").write_bytes(b"FANART")
    return {"poster": True, "fanart": True}


def _e2e_download_writes_url_bytes(url, dest):
    """side_effect for download_image：內容是 url 的確定性函式，方便驗證封面確實下載。"""
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(f"COVER-BYTES:{url}".encode())
    return True


def _e2e_wire(mocker, monkeypatch, config, db_path):
    from core.database import VideoRepository as RealRepo

    mocker.patch("web.routers.scraper.load_config", return_value=config)
    monkeypatch.setattr("core.readonly_producer.get_db_path", lambda: db_path)
    mocker.patch(
        "web.routers.scraper.VideoRepository",
        side_effect=lambda *a, **kw: RealRepo(db_path),
    )
    mocker.patch(
        "core.readonly_producer.generate_jellyfin_images",
        side_effect=_e2e_fake_generate_jellyfin_images,
    )


def _e2e_init_db(tmp_path):
    from core.database import init_db
    db_path = tmp_path / "db" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    return db_path


class TestReadonlyRescrapeMetadataWiring:
    """DoD-1/DoD-2：真檔案 E2E，唯讀來源 rescrape + metadata 的接線本體。"""

    def test_rescrape_metadata_writes_output_nfo_zero_source_write(
        self, tmp_path, client, mocker, monkeypatch
    ):
        """DoD-1：rescrape ＋ metadata（含 cover URL）→ 200，輸出夾 NFO 含 AI 給的值，
        原始檔（來源夾影片與 sidecar）mtime/bytes 零變化。"""
        from core.path_utils import to_file_uri, uri_to_local_fs_path

        src = tmp_path / "src"
        src.mkdir()
        video = src / "SONE-205.mp4"
        video.write_bytes(b"FAKE-VIDEO")

        db_path = _e2e_init_db(tmp_path)
        config = _e2e_off_config(src)
        _e2e_wire(mocker, monkeypatch, config, db_path)
        mock_search = mocker.patch("core.readonly_producer.search_jav")
        mock_search_single = mocker.patch("core.readonly_producer.search_jav_single_source")
        mocker.patch(
            "core.readonly_producer.download_image", side_effect=_e2e_download_writes_url_bytes,
        )

        # BE-TEST-10：baseline 在 fixture 建檔之後、client.post 之前取
        before = _e2e_snapshot(src)

        canonical = to_file_uri(str(video))
        response = client.post("/api/enrich-single", json={
            "file_path": canonical,
            "number": "SONE-205",
            "readonly_action": "rescrape",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "number": "SONE-205",
                "title": "AI Title",
                "actors": ["A"],
                "maker": "M",
                "date": "2024-01-01",
                "cover": "http://x/c.jpg",
            },
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # scraper_data 有值時 resolve_ingest_plan 的 rescrape 分支短路，零查詢
        mock_search.assert_not_called()
        mock_search_single.assert_not_called()

        # 原始檔（來源夾）零寫入
        assert _e2e_snapshot(src) == before

        from core.database import VideoRepository
        repo = VideoRepository(db_path)
        row = repo.get_by_path(canonical)
        assert row is not None
        assert row.output_dir

        movie_dir = uri_to_local_fs_path(row.output_dir, {})
        nfo_files = list(Path(movie_dir).glob("*.nfo"))
        assert len(nfo_files) == 1
        nfo_text = nfo_files[0].read_text(encoding="utf-8")
        assert "AI Title" in nfo_text

    def test_metadata_number_survives_verbatim_not_cleaned(
        self, tmp_path, client, mocker, monkeypatch
    ):
        """DoD-2（只驗不洗）：輸出 NFO 的 <num> 精確等於 metadata['number']（不是空、
        不是被 T1 清洗函式剔除）。"""
        from core.path_utils import to_file_uri, uri_to_local_fs_path

        src = tmp_path / "src"
        src.mkdir()
        video = src / "SONE-205.mp4"
        video.write_bytes(b"FAKE-VIDEO")

        db_path = _e2e_init_db(tmp_path)
        config = _e2e_off_config(src)
        _e2e_wire(mocker, monkeypatch, config, db_path)
        mocker.patch("core.readonly_producer.search_jav")
        mocker.patch("core.readonly_producer.search_jav_single_source")
        mocker.patch(
            "core.readonly_producer.download_image", side_effect=_e2e_download_writes_url_bytes,
        )

        canonical = to_file_uri(str(video))
        response = client.post("/api/enrich-single", json={
            "file_path": canonical,
            "number": "SONE-205",
            "readonly_action": "rescrape",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "number": "SONE-205",
                "title": "AI Title",
                "actors": ["A"],
                "maker": "M",
                "date": "2024-01-01",
            },
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

        from core.database import VideoRepository
        repo = VideoRepository(db_path)
        row = repo.get_by_path(canonical)
        movie_dir = uri_to_local_fs_path(row.output_dir, {})
        nfo_files = list(Path(movie_dir).glob("*.nfo"))
        assert len(nfo_files) == 1
        nfo_text = nfo_files[0].read_text(encoding="utf-8")
        assert "<num>SONE-205</num>" in nfo_text


class TestReadonlyRescrapeMetadataRegressionLocks:
    """DoD-3/4/6/7：T1 已擋住的組合，本檔重跑一次作回歸鎖（純測試，非新程式碼）。"""

    def test_ingest_with_metadata_rejected_400(self, client, mocker):
        """DoD-3：readonly_action=ingest（或未帶）＋ metadata → 400（不是 200+success:false）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        resp1 = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "metadata": {"number": "ABC-001", "title": "T"},
        })
        assert resp1.status_code == 400

        resp2 = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "ingest",
            "metadata": {"number": "ABC-001", "title": "T"},
        })
        assert resp2.status_code == 400

    def test_missing_number_raises_400(self, client, mocker):
        """DoD-4：metadata 缺 number → 400（不是 500、不是 200）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"title": "T"},
        })
        assert response.status_code == 400

    def test_missing_title_raises_400(self, client, mocker):
        """DoD-4：metadata 缺 title → 400（不是 500、不是 200）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "ABC-001"},
        })
        assert response.status_code == 400

    def test_number_as_int_raises_400(self, client, mocker):
        """DoD-4：metadata['number'] 是整數 → 400（不是 500、不是 200）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": 123, "title": "T"},
        })
        assert response.status_code == 400

    def test_write_nfo_false_readonly_returns_200_not_4xx(self, client, mocker):
        """DoD-6：rescrape ＋ metadata ＋ write_nfo=false → 200 ＋ _readonly_enrich_failure 形狀
        （執行前置條件，不是請求形狀錯，CD-135-12 4xx/200 分界線不動它）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())
        # _validate_enrich_request 在 write_nfo 早退之前就跑，metadata+rescrape 觸發本
        # task 新增的番號守衛，需要 VideoRepository 可用（existing=None → 不擋）。
        mocker.patch("web.routers.scraper.VideoRepository").return_value.get_by_path.return_value = None
        mock_plan = mocker.patch("core.readonly_producer.resolve_ingest_plan")
        mock_produce = mocker.patch("core.readonly_producer._produce_one")

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "ABC-001", "title": "T"},
            "write_nfo": False,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["nfo_written"] is False
        assert data["reason"] == "error"
        assert set(data) >= _ENRICH_RESULT_KEYS
        mock_plan.assert_not_called()
        mock_produce.assert_not_called()

    def test_metadata_and_javlibrary_detail_url_mutually_exclusive_400(self, client, mocker):
        """DoD-7：唯讀來源 ＋ metadata ＋ source=javlibrary ＋ detail_url → 400（互斥）。"""
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/ABC-001.mp4",
            "number": "ABC-001",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "source": "javlibrary",
            "detail_url": "https://www.javlibrary.com/ja/?v=abcxyz",
            "metadata": {"number": "ABC-001", "title": "T"},
        })
        assert response.status_code == 400


class TestReadonlyRescrapeNumberGuard:
    """DoD-5：本 task 新增的番號守衛（比對 metadata['number'] 與 DB 既有值）。"""

    def _mock_repo_existing(self, mocker, existing):
        mocker.patch("web.routers.scraper.resolve_owning_output_root", return_value=_owning_stub())
        mock_repo = mocker.patch("web.routers.scraper.VideoRepository")
        mock_repo.return_value.get_by_path.return_value = existing
        return mock_repo

    def test_5a_number_mismatch_without_allow_change_rejected_400(self, client, mocker):
        """5a：metadata['number'] 與 DB 既有番號不符且未帶 allow_number_change → 400，
        detail 同時含兩個番號。"""
        mock_repo = self._mock_repo_existing(mocker, Video(number="SONE-205"))
        # SA-pre-9 P3-1 / BE-TEST-11：同上——注入映射讓 canonical 與 round-trip key 不同。
        mapping = {"/tmp/ro_src": "/mnt/nas-guard-probe"}
        mocker.patch("web.routers.scraper.load_config", return_value={
            "gallery": {"path_mappings": mapping},
        })

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/SONE-205.mp4",
            "number": "SONE-205",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "SONE-206", "title": "T"},
        })

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "SONE-206" in detail
        assert "SONE-205" in detail

        # SA-pre-9 P3-1：鎖住「查的是哪一個 DB key」。唯讀那條路必須用 canonical
        # （＝ coerce_to_file_uri(file_path, path_mappings)），與 enrich_one_readonly 自己的
        # repo.get_by_path(canonical)（core/readonly_producer.py:1942）同一個 key；
        # 兩條路刻意用不同 key，各自對齊自己的執行路徑。mock 對任何 key 都回同一個物件，
        # 沒有這條斷言的話對調兩者也不會紅。
        mock_repo.return_value.get_by_path.assert_called_once_with(
            coerce_to_file_uri("/tmp/ro_src/SONE-205.mp4", mapping)
        )

    def test_5b_number_mismatch_with_allow_change_permitted_200(self, client, mocker):
        """5b：同上但帶 allow_number_change=true → 放行（200，需 mock 產出核心避免真跑）。"""
        self._mock_repo_existing(mocker, Video(number="SONE-205"))
        mocker.patch(
            "core.readonly_producer.resolve_ingest_plan",
            return_value=({"number": "SONE-206", "title": "T", "cover": ""}, ("none",)),
        )
        mocker.patch(
            "core.readonly_producer._produce_one",
            return_value=(Path("/out/ro_src-abcdef/SONE-206"), {"cover_fs": "", "sample_fs": [], "nfo_mtime": 1.0}),
        )

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/SONE-205.mp4",
            "number": "SONE-205",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "SONE-206", "title": "T"},
            "allow_number_change": True,
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_5c_db_no_existing_row_not_blocked(self, client, mocker, tmp_path):
        """5c：DB 查無該列（新檔）→ 不擋（existing 為 None）。
        existing=None 時 enrich_one_readonly 自己的 step 7（file_info）會落到
        os.path.getsize/getmtime 讀真實檔案，故需要真檔案而非假路徑字串。"""
        from core.path_utils import to_file_uri

        src = tmp_path / "src"
        src.mkdir()
        video = src / "SONE-999.mp4"
        video.write_bytes(b"FAKE-VIDEO")
        canonical = to_file_uri(str(video))

        self._mock_repo_existing(mocker, None)
        mocker.patch(
            "core.readonly_producer.resolve_ingest_plan",
            return_value=({"number": "SONE-999", "title": "T", "cover": ""}, ("none",)),
        )
        mocker.patch(
            "core.readonly_producer._produce_one",
            return_value=(Path("/out/ro_src-abcdef/SONE-999"), {"cover_fs": "", "sample_fs": [], "nfo_mtime": 1.0}),
        )

        response = client.post("/api/enrich-single", json={
            "file_path": canonical,
            "number": "SONE-999",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "SONE-999", "title": "T"},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_5c_db_existing_row_empty_number_not_blocked(self, client, mocker):
        """5c：DB 有列但 existing.number 為空 → 不擋。"""
        self._mock_repo_existing(mocker, Video(number=None))
        mocker.patch(
            "core.readonly_producer.resolve_ingest_plan",
            return_value=({"number": "SONE-999", "title": "T", "cover": ""}, ("none",)),
        )
        mocker.patch(
            "core.readonly_producer._produce_one",
            return_value=(Path("/out/ro_src-abcdef/SONE-999"), {"cover_fs": "", "sample_fs": [], "nfo_mtime": 1.0}),
        )

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/SONE-999.mp4",
            "number": "SONE-999",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "SONE-999", "title": "T"},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_5d_top_level_number_wrong_but_metadata_matches_permitted_200(self, client, mocker):
        """5d：頂層 request.number 打錯，但 metadata['number'] 與 DB 既有值相符 → 放行
        （唯讀路徑真正落地的是 scraper_data['number']，request.number 只是查詢參數）。"""
        self._mock_repo_existing(mocker, Video(number="SONE-205"))
        mocker.patch(
            "core.readonly_producer.resolve_ingest_plan",
            return_value=({"number": "SONE-205", "title": "T", "cover": ""}, ("none",)),
        )
        mocker.patch(
            "core.readonly_producer._produce_one",
            return_value=(Path("/out/ro_src-abcdef/SONE-205"), {"cover_fs": "", "sample_fs": [], "nfo_mtime": 1.0}),
        )

        response = client.post("/api/enrich-single", json={
            "file_path": "/tmp/ro_src/SONE-205.mp4",
            "number": "WRONG-999",
            "mode": "refresh_full",
            "readonly_action": "rescrape",
            "metadata": {"number": "SONE-205", "title": "T"},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True


class TestReadonlyEnrichWishlistReconcile:
    """TASK-141a-T5：enrich-single 唯讀分支掛 reconcile_wishlist（DoD 2/4）。"""

    def test_readonly_rescrape_reconciles_wishlist_on_success(
        self, tmp_path, client, mocker, monkeypatch
    ):
        """DoD 2（唯讀分支）：rescrape 成功 → 恰好一筆 auto_removed，書籤消失。"""
        from core.database import WishlistRepository
        from core.path_utils import to_file_uri

        src = tmp_path / "src"
        src.mkdir()
        video = src / "SONE-205.mp4"
        video.write_bytes(b"FAKE-VIDEO")

        db_path = _e2e_init_db(tmp_path)
        config = _e2e_off_config(src)
        _e2e_wire(mocker, monkeypatch, config, db_path)
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: db_path)
        monkeypatch.setattr("core.wishlist_cover_cache.get_db_path", lambda: db_path)
        mocker.patch("core.readonly_producer.search_jav")
        mocker.patch("core.readonly_producer.search_jav_single_source")
        mocker.patch(
            "core.readonly_producer.download_image",
            side_effect=_e2e_download_writes_url_bytes,
        )

        WishlistRepository().add("SONE-205", title="Owned")

        canonical = to_file_uri(str(video))
        response = client.post("/api/enrich-single", json={
            "file_path": canonical,
            "number": "SONE-205",
            "readonly_action": "rescrape",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "number": "SONE-205",
                "title": "AI Title",
                "actors": ["A"],
                "maker": "M",
                "date": "2024-01-01",
                "cover": "http://x/c.jpg",
            },
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

        notif_items = client.get("/api/notifications").json()["items"]
        auto_removed = [
            i for i in notif_items if i["title_key"] == "notif.wishlist_auto_removed"
        ]
        assert len(auto_removed) == 1
        assert auto_removed[0]["level"] == "info"
        assert auto_removed[0]["task_type"] == "wishlist_reconcile"

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT 1 FROM wishlist WHERE number = ?", ("SONE-205",)
        ).fetchone()
        conn.close()
        assert row is None

    def test_readonly_rescrape_reconcile_failure_keeps_success_response(
        self, tmp_path, client, mocker, monkeypatch
    ):
        """DoD 4（唯讀分支）：對帳丟例外時回應仍是完整成功 EnrichResult。"""
        from core.path_utils import to_file_uri

        src = tmp_path / "src"
        src.mkdir()
        video = src / "SONE-205.mp4"
        video.write_bytes(b"FAKE-VIDEO")

        db_path = _e2e_init_db(tmp_path)
        config = _e2e_off_config(src)
        _e2e_wire(mocker, monkeypatch, config, db_path)
        # reconcile_wishlist 走 connection.get_db_path；必須與 e2e DB 同路徑
        monkeypatch.setattr("core.database.connection.get_db_path", lambda: db_path)
        monkeypatch.setattr("core.wishlist_cover_cache.get_db_path", lambda: db_path)
        mocker.patch("core.readonly_producer.search_jav")
        mocker.patch("core.readonly_producer.search_jav_single_source")
        mocker.patch(
            "core.readonly_producer.download_image",
            side_effect=_e2e_download_writes_url_bytes,
        )

        payload = {
            "file_path": to_file_uri(str(video)),
            "number": "SONE-205",
            "readonly_action": "rescrape",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "number": "SONE-205",
                "title": "AI Title",
                "actors": ["A"],
                "maker": "M",
                "date": "2024-01-01",
                "cover": "http://x/c.jpg",
            },
        }

        # BE-TEST-10：baseline 在注入例外之前取得
        baseline = client.post("/api/enrich-single", json=payload)
        assert baseline.status_code == 200
        baseline_data = baseline.json()
        assert baseline_data["success"] is True

        import web.routers.notifications as notif_mod
        notif_mod._notifications.clear()
        notif_mod._read_ids.clear()

        def _boom():
            raise RuntimeError("reconcile exploded")

        # raising=False：實作前屬性尚不存在；RED 應落在「未發 warn」而非 AttributeError
        monkeypatch.setattr("web.routers.scraper.reconcile_wishlist", _boom, raising=False)

        response = client.post("/api/enrich-single", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["nfo_written"] == baseline_data["nfo_written"]
        assert data["cover_written"] == baseline_data["cover_written"]
        assert data["fields_filled"] == baseline_data["fields_filled"]
        assert data["source_used"] == baseline_data["source_used"]
        assert data["reason"] == baseline_data["reason"]

        notif_items = client.get("/api/notifications").json()["items"]
        warn_items = [
            i for i in notif_items
            if i["title_key"] == "notif.wishlist_reconcile_failed"
        ]
        assert len(warn_items) == 1
        assert warn_items[0]["level"] == "warn"
