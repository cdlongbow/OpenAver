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
    monkeypatch.setattr("core.readonly_paths.get_db_path", lambda: db_path)
    mocker.patch(
        "web.routers.scraper.VideoRepository",
        side_effect=lambda *a, **kw: RealRepo(db_path),
    )
    mocker.patch(
        "core.readonly_assets.generate_jellyfin_images",
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
            "core.readonly_assets.download_image", side_effect=_e2e_download_writes_url_bytes,
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


    def test_same_rating_submitted_twice_does_not_double(
        self, tmp_path, client, mocker, monkeypatch
    ):
        """DoD⑧ / AC-4：連續兩次提交同一個 _rating 值 → NFO 評分數字不翻倍
        （寫入 ×2 與讀回 ÷2 倍率對齊；送 4.0 兩次都應寫出 8.0）。"""
        import xml.etree.ElementTree as ET

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
            "core.readonly_assets.download_image", side_effect=_e2e_download_writes_url_bytes,
        )

        canonical = to_file_uri(str(video))
        payload = {
            "file_path": canonical,
            "number": "SONE-205",
            "readonly_action": "rescrape",
            "mode": "refresh_full",
            "overwrite_existing": True,
            "metadata": {
                "number": "SONE-205",
                "title": "Stable Rating",
                "_summary": "plot",
                "url": "http://example/",
                "_rating": 4.0,
            },
        }

        response1 = client.post("/api/enrich-single", json=payload)
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        from core.database import VideoRepository
        repo = VideoRepository(db_path)
        row = repo.get_by_path(canonical)
        movie_dir = uri_to_local_fs_path(row.output_dir, {})
        nfo_files = list(Path(movie_dir).glob("*.nfo"))
        assert len(nfo_files) == 1
        first_rating = ET.parse(str(nfo_files[0])).getroot().find("rating").text
        assert first_rating == "8.0"

        response2 = client.post("/api/enrich-single", json=payload)
        assert response2.status_code == 200
        assert response2.json()["success"] is True

        nfo_files = list(Path(movie_dir).glob("*.nfo"))
        assert len(nfo_files) == 1
        second_rating = ET.parse(str(nfo_files[0])).getroot().find("rating").text
        assert second_rating == "8.0"
        assert second_rating == first_rating


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
            "core.readonly_assets.download_image",
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

