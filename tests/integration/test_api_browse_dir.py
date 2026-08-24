import os
from unittest.mock import MagicMock
from urllib.parse import quote
from core.path_utils import to_file_uri


class TestBrowseDirAPI:
    """測試 GET /api/gallery/browse-dir 端點"""

    def test_browse_dir_success_normal(self, client, tmp_path):
        """正常目錄列舉：回傳 200，entries 依名稱不分大小寫排序，包含子目錄不含檔案，parent_path 正確。"""
        work_dir = tmp_path / "normal_test"
        work_dir.mkdir()
        dir_b = work_dir / "Beta"
        dir_a = work_dir / "alpha"
        dir_c = work_dir / "gamma"
        dir_b.mkdir()
        dir_a.mkdir()
        dir_c.mkdir()
        (work_dir / "some_file.txt").write_text("hello")

        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(work_dir))}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == str(work_dir)
        assert data["parent_path"] == str(work_dir.parent)
        assert [e["name"] for e in data["entries"]] == ["alpha", "Beta", "gamma"]
        assert [e["path"] for e in data["entries"]] == [str(dir_a), str(dir_b), str(dir_c)]
        assert "files" not in data

    def test_browse_dir_empty_directory(self, client, tmp_path):
        """空目錄：回傳 200 且 entries 為空陣列，非 404。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(empty_dir))}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == str(empty_dir)
        assert data["entries"] == []

    def test_expand_videos_filters_non_video_files(self, client, tmp_path, monkeypatch):
        """expand=videos：只回傳第一層影片檔案絕對路徑，過濾非影片檔案，不遞迴。"""
        test_config = {
            "scraper": {
                "video_extensions": [".mp4", ".mkv"]
            }
        }
        monkeypatch.setattr("web.routers.scanner.load_config", lambda: test_config)

        work_dir = tmp_path / "expand_test"
        work_dir.mkdir()
        v1 = work_dir / "movie1.mp4"
        v2 = work_dir / "movie2.MKV"
        nfo = work_dir / "movie1.nfo"
        poster = work_dir / "poster.jpg"
        txt = work_dir / "readme.txt"
        sub_dir = work_dir / "sub"
        sub_dir.mkdir()
        sub_v = sub_dir / "nested.mp4"

        for f in (v1, v2, nfo, poster, txt, sub_v):
            f.write_text("data")

        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(work_dir))}&expand=videos")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert sorted(data["files"]) == sorted([str(v1), str(v2)])
        assert len(data["entries"]) == 1
        assert data["entries"][0]["name"] == "sub"

    def test_browse_dir_expand_videos_empty(self, client, tmp_path):
        """expand=videos：無任何影片的目錄回傳 files 為空陣列。"""
        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(tmp_path))}&expand=videos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []

    def test_browse_dir_expand_other_value_ignored(self, client, tmp_path):
        """expand 帶其他值或空字串時被忽略，不回傳 files 欄位，不報錯。"""
        (tmp_path / "test.mp4").write_text("video")
        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(tmp_path))}&expand=all")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" not in data

    def test_browse_dir_not_found(self, client, tmp_path):
        """路徑不存在：回傳 404 {"success": false, "error": "not_found"}。"""
        not_exist = tmp_path / "does_not_exist"
        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(not_exist))}")
        assert resp.status_code == 404
        data = resp.json()
        assert data == {"success": False, "error": "not_found"}

    def test_browse_dir_not_a_directory(self, client, tmp_path):
        """路徑指向一般檔案：回傳 400 {"success": false, "error": "not_a_directory"}。"""
        file_path = tmp_path / "a_file.txt"
        file_path.write_text("not a dir")
        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(file_path))}")
        assert resp.status_code == 400
        data = resp.json()
        assert data == {"success": False, "error": "not_a_directory"}

    def test_browse_dir_permission_denied_root(self, client, tmp_path, monkeypatch):
        """整題目錄 scandir PermissionError：回傳 403 {"success": false, "error": "permission_denied"}。"""
        original_scandir = os.scandir

        def mock_scandir(p):
            if str(p) == str(tmp_path):
                raise PermissionError("Access denied")
            return original_scandir(p)

        monkeypatch.setattr("web.routers.scanner.os.scandir", mock_scandir)

        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(tmp_path))}")
        assert resp.status_code == 403
        data = resp.json()
        assert data == {"success": False, "error": "permission_denied"}

    def test_browse_dir_skips_unreadable_entry(self, client, tmp_path, monkeypatch):
        """逐項容錯：目錄內單一 entry 讀取拋出 PermissionError/OSError 時跳過該項，其餘照常列出，不回 500。"""
        entry1 = MagicMock()
        entry1.name = "accessible_a"
        entry1.path = str(tmp_path / "accessible_a")
        entry1.is_dir.return_value = True

        entry2 = MagicMock()
        entry2.name = "broken_entry"
        entry2.path = str(tmp_path / "broken_entry")
        entry2.is_dir.side_effect = PermissionError("Permission denied on entry")

        entry3 = MagicMock()
        entry3.name = "accessible_b"
        entry3.path = str(tmp_path / "accessible_b")
        entry3.is_dir.return_value = True

        class FakeScandirContext:
            def __enter__(self):
                return [entry1, entry2, entry3]

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr("web.routers.scanner.os.scandir", lambda p: FakeScandirContext())

        resp = client.get(f"/api/gallery/browse-dir?path={quote(str(tmp_path))}")
        assert resp.status_code == 200
        data = resp.json()
        assert [e["name"] for e in data["entries"]] == ["accessible_a", "accessible_b"]

    def test_browse_dir_relative_path_normalized(self, client, tmp_path):
        """路徑含 '..' 相對路徑片段時，會先經 realpath 正規化後再回傳。"""
        sub_dir = tmp_path / "folder1" / "folder2"
        sub_dir.mkdir(parents=True)
        query_path = str(sub_dir) + "/../folder2"

        resp = client.get(f"/api/gallery/browse-dir?path={quote(query_path)}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == str(sub_dir.resolve())

    def test_browse_dir_posix_root(self, client, monkeypatch):
        """POSIX 根目錄 '/'：parent_path 應為 null。"""
        monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)
        resp = client.get("/api/gallery/browse-dir?path=/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == "/"
        assert data["parent_path"] is None

    def test_browse_dir_windows_virtual_drives(self, client, monkeypatch):
        """Windows 虛擬節點 path=''：回傳磁碟機清單，parent_path 為 null，current_path 為 ''。"""
        monkeypatch.setattr("web.routers.scanner._is_windows", lambda: True)
        monkeypatch.setattr("web.routers.scanner._list_windows_drives", lambda: ["C:\\", "D:\\"])

        resp = client.get("/api/gallery/browse-dir?path=&expand=videos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == ""
        assert data["parent_path"] is None
        assert data["entries"] == [
            {"name": "C:\\", "path": "C:\\"},
            {"name": "D:\\", "path": "D:\\"},
        ]
        assert data["files"] == []

    def test_browse_dir_default_start_dir(self, client, tmp_path, monkeypatch):
        """path 參數省略時，透過起點決議取得預設目錄並列舉。"""
        sub_dir = tmp_path / "library" / "action"
        sub_dir.mkdir(parents=True)
        test_config = {
            "gallery": {
                "directories": [
                    {"path": str(sub_dir)}
                ]
            }
        }
        monkeypatch.setattr("web.routers.scanner.load_config", lambda: test_config)
        monkeypatch.setattr("web.routers.scanner._is_windows", lambda: False)

        resp = client.get("/api/gallery/browse-dir")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_path"] == str(tmp_path / "library")
