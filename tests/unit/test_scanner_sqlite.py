"""測試 Scanner SQLite 整合"""
import pytest
import tempfile
from pathlib import Path

from core.gallery_scanner import VideoScanner
from core.database import VideoRepository


@pytest.fixture
def temp_video_dir():
    """建立臨時影片目錄"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_video_file(dir_path: Path, name: str, size: int = 1024 * 1024) -> Path:
    """建立測試影片檔案"""
    video_path = dir_path / name
    with open(video_path, 'wb') as f:
        f.write(b'0' * size)
    return video_path


def create_nfo_file(video_path: Path, title: str = "測試影片", num: str = "ABC-123",
                    actor: str = "演員A", maker: str = "片商") -> Path:
    """建立測試 NFO 檔案"""
    nfo_path = video_path.with_suffix('.nfo')
    nfo_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<movie>
    <title>{title}</title>
    <num>{num}</num>
    <maker>{maker}</maker>
    <actor><name>{actor}</name></actor>
</movie>
"""
    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(nfo_content)
    return nfo_path


class TestScanToSqlite:
    """scan_to_sqlite 測試"""

    def test_scan_incremental_no_changes(self, temp_db, temp_video_dir):
        """測試增量掃描（無變更）"""
        video_path = create_video_file(temp_video_dir, "test.mp4")
        create_nfo_file(video_path, title="測試影片")

        scanner = VideoScanner()

        # 第一次掃描
        result1 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result1['inserted'] == 1

        # 第二次掃描（無變更）
        result2 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result2['inserted'] == 0
        assert result2['updated'] == 0
        assert result2['deleted'] == 0
        assert result2['total'] == 1


    def test_scan_incremental_nfo_mtime_changed(self, temp_db, temp_video_dir):
        """測試增量掃描（NFO 修改時間變更）"""
        import time

        video_path = create_video_file(temp_video_dir, "test.mp4")
        nfo_path = create_nfo_file(video_path, title="原始標題")

        scanner = VideoScanner()

        # 第一次掃描
        result1 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result1['inserted'] == 1

        # 等待確保 mtime 不同
        time.sleep(0.1)

        # 修改 NFO（觸發 nfo_mtime 變更）
        create_nfo_file(video_path, title="修改後標題")

        # 第二次掃描
        result2 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result2['updated'] == 1

        # 驗證標題已更新
        repo = VideoRepository(temp_db)
        video = repo.get_all()[0]
        assert video.title == "修改後標題"

    def test_scan_incremental_extrafanart_added(self, temp_db, temp_video_dir):
        """新增劇照（N -> N+1）→ 該片被排進重掃，即使影片檔與 NFO 的 mtime 都沒變
        （TASK-118b-T9）"""
        video_path = create_video_file(temp_video_dir, "test.mp4")
        create_nfo_file(video_path, title="測試影片")

        scanner = VideoScanner()

        # 第一次掃描：無 extrafanart（N=0）
        result1 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result1['inserted'] == 1
        repo = VideoRepository(temp_db)
        assert repo.get_all()[0].sample_images == []

        # 新增劇照（N+1=1），不動影片檔、不動 NFO
        extrafanart = temp_video_dir / "extrafanart"
        extrafanart.mkdir()
        (extrafanart / "fanart1.jpg").write_bytes(b"img")

        # 第二次掃描：張數變了 → 必須被排進重掃
        result2 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result2['updated'] == 1
        assert result2['inserted'] == 0
        assert len(repo.get_all()[0].sample_images) == 1


    def test_scan_min_size_filter(self, temp_db, temp_video_dir):
        """測試最小檔案大小過濾"""
        # 建立小檔案（100 bytes）
        create_video_file(temp_video_dir, "small.mp4", size=100)
        # 建立大檔案（2 MB）
        create_video_file(temp_video_dir, "large.mp4", size=2 * 1024 * 1024)

        scanner = VideoScanner()
        result = scanner.scan_to_sqlite(str(temp_video_dir), temp_db, min_size_mb=1)

        # 只有大檔案被掃描
        assert result['inserted'] == 1
        assert result['total'] == 1

    def test_scan_subdirectories(self, temp_db, temp_video_dir):
        """測試掃描子目錄"""
        # 在子目錄建立影片
        subdir = temp_video_dir / "subdir"
        subdir.mkdir()
        create_video_file(subdir, "video1.mp4")
        create_video_file(temp_video_dir, "video2.mp4")

        scanner = VideoScanner()
        result = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)

        # 兩部影片都應該被掃描
        assert result['inserted'] == 2
        assert result['total'] == 2


    def test_scan_nfo_with_bare_ampersand(self, temp_db, temp_video_dir):
        """含 bare & 的 NFO 應可解析，actor 和 genre 正確讀取"""
        video_path = create_video_file(temp_video_dir, "test.mp4")
        nfo_content = '<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>測試影片</title>\n  <num>ADN-700</num>\n  <maker>片商</maker>\n  <actor><name>女優A</name></actor>\n  <genre>劇情</genre>\n  <trailer>https://example.com/video?sign=abc&t=123</trailer>\n</movie>'
        nfo_path = video_path.with_suffix('.nfo')
        nfo_path.write_text(nfo_content, encoding='utf-8')

        scanner = VideoScanner()
        result = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)

        assert result['inserted'] == 1
        repo = VideoRepository(temp_db)
        videos = repo.get_all()
        assert len(videos) == 1
        assert videos[0].title == "測試影片"
        assert "女優A" in videos[0].actresses
        assert "劇情" in videos[0].tags


class TestZeroSizeExtensionExemption:
    """.strm min_size exemption in fast_scan_directory"""

    def test_strm_not_filtered_by_min_size(self, temp_video_dir):
        """A .strm file with 100 bytes should NOT be filtered by min_size (ZERO_SIZE_EXTENSIONS exemption)"""
        from core.gallery_scanner import fast_scan_directory, VIDEO_EXTENSIONS
        # Create a .strm file (100 bytes - normally would be filtered by 1MB min_size)
        strm_file = temp_video_dir / "test.strm"
        strm_file.write_bytes(b'x' * 100)

        # Create a regular .mp4 file (100 bytes - should be filtered by 1MB min_size)
        mp4_file = temp_video_dir / "small.mp4"
        mp4_file.write_bytes(b'x' * 100)

        # Scan with 1MB min_size
        extensions = VIDEO_EXTENSIONS | {'.strm'}
        results = fast_scan_directory(str(temp_video_dir), extensions, min_size_bytes=1 * 1024 * 1024)

        # .strm should be found (exempted from min_size), .mp4 should be filtered out
        found_paths = [r['path'] for r in results]
        assert any('test.strm' in p for p in found_paths), \
            ".strm file should NOT be filtered by min_size"
        assert not any('small.mp4' in p for p in found_paths), \
            "small .mp4 file should be filtered by min_size"


class TestScanToSqliteIntegration:
    """scan_to_sqlite 整合測試"""

    def test_full_workflow(self, temp_db, temp_video_dir):
        """測試完整工作流程"""
        scanner = VideoScanner()
        repo = VideoRepository(temp_db)

        # 1. 初始掃描
        video1 = create_video_file(temp_video_dir, "video1.mp4")
        create_nfo_file(video1, title="影片1", num="ABC-001", actor="演員A")

        result1 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result1['inserted'] == 1

        # 2. 新增檔案
        video2 = create_video_file(temp_video_dir, "video2.mp4")
        create_nfo_file(video2, title="影片2", num="ABC-002", actor="演員B")

        result2 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result2['inserted'] == 1
        assert result2['total'] == 2

        # 3. 刪除檔案
        video1.unlink()
        video1.with_suffix('.nfo').unlink()

        result3 = scanner.scan_to_sqlite(str(temp_video_dir), temp_db)
        assert result3['deleted'] == 1
        assert result3['total'] == 1

        # 4. 驗證最終狀態
        videos = repo.get_all()
        assert len(videos) == 1
        assert videos[0].title == "影片2"
        assert videos[0].number == "ABC-002"


class TestSampleImagesScanner:
    """extrafanart 掃描邊界條件測試"""

    def test_extrafanart_any_image_file_included(self, temp_video_dir):
        """非 fanart* 檔名與非 jpg 圖片都會被收；非圖片副檔名不收"""
        from core.gallery_scanner import VideoScanner
        video_path = create_video_file(temp_video_dir, "test.mp4")
        create_nfo_file(video_path)
        extrafanart = temp_video_dir / "extrafanart"
        extrafanart.mkdir()
        (extrafanart / "fanart1.jpg").write_bytes(b"img")
        (extrafanart / "fanart1.png").write_bytes(b"img")
        (extrafanart / "thumb.jpg").write_bytes(b"img")
        (extrafanart / "extrafanart-1.jpg").write_bytes(b"img")
        (extrafanart / "notes.txt").write_bytes(b"txt")
        scanner = VideoScanner()
        info = scanner.scan_file(str(video_path))
        names = [s.split("/")[-1] for s in info.sample_images]
        assert names == [
            "extrafanart-1.jpg",
            "fanart1.jpg",
            "fanart1.png",
            "thumb.jpg",
        ]


class TestSampleImagesDB:
    """sample_images DB 序列化/反序列化邊界條件"""


    def test_migration_adds_sample_images_column(self, tmp_path):
        """migration: 舊 schema 無 sample_images 欄位，init_db 後應自動補齊"""
        import sqlite3
        from core.database import init_db

        db_path = tmp_path / "migration_test.db"

        # 建立舊 schema（不含 sample_images、director、label 欄位）
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                number TEXT,
                title TEXT,
                original_title TEXT,
                actresses TEXT,
                maker TEXT,
                tags TEXT,
                duration INTEGER,
                size_bytes INTEGER,
                cover_path TEXT,
                release_date TEXT,
                mtime REAL,
                nfo_mtime REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        # 執行 init_db（應執行 migration）
        init_db(db_path)

        # 驗證 sample_images 欄位存在
        conn = sqlite3.connect(str(db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
        conn.close()
        assert 'sample_images' in cols, "migration 應補齊 sample_images 欄位"
