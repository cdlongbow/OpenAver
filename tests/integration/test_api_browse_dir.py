from urllib.parse import quote


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
