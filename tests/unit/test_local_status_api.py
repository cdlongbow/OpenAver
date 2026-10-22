"""測試 /api/search/local-status API"""
import pytest

from core.database import Video


# temp_db fixture 定義於 tests/unit/conftest.py

@pytest.fixture
def client(make_client, populated_db):
    return make_client(["core.database.connection.get_db_path", "web.routers.search.get_db_path"], mock_db_path=populated_db)

@pytest.fixture
def populated_db(make_populated_db):
    videos = [
        Video(path="/mnt/media/SONE-205.mp4", number="SONE-205", title="Test Video 1", mtime=100.0),
        Video(path="/mnt/media/SONE-205-uncensored.mp4", number="SONE-205", title="Test Video 1 (Uncensored)", mtime=101.0),
        Video(path="/mnt/media/ABW-001.mp4", number="ABW-001", title="Test Video 2", mtime=200.0),
        Video(path="/mnt/media/fc2-ppv-1234567.mp4", number="FC2-PPV-1234567", title="FC2 Video", mtime=300.0),
    ]
    return make_populated_db(videos)


class TestLocalStatusAPI:
    """測試 /api/search/local-status API"""

    def test_single_number_exists(self, client, populated_db, monkeypatch):
        """測試查詢存在的單一番號"""
        def mock_get_db_path():
            return populated_db
        monkeypatch.setattr("web.routers.search.get_db_path", mock_get_db_path)

        response = client.get("/api/search/local-status?numbers=SONE-205")
        assert response.status_code == 200

        data = response.json()
        assert "SONE-205" in data
        assert data["SONE-205"]["exists"] is True
        assert data["SONE-205"]["count"] == 2
        assert len(data["SONE-205"]["paths"]) == 2

    def test_single_number_not_exists(self, client, populated_db, monkeypatch):
        """測試查詢不存在的單一番號"""
        def mock_get_db_path():
            return populated_db
        monkeypatch.setattr("web.routers.search.get_db_path", mock_get_db_path)

        response = client.get("/api/search/local-status?numbers=XYZ-999")
        assert response.status_code == 200

        data = response.json()
        assert "XYZ-999" in data
        assert data["XYZ-999"]["exists"] is False


    def test_case_insensitive_lowercase(self, client, populated_db, monkeypatch):
        """測試大小寫不敏感 - 小寫查詢"""
        def mock_get_db_path():
            return populated_db
        monkeypatch.setattr("web.routers.search.get_db_path", mock_get_db_path)

        response = client.get("/api/search/local-status?numbers=sone-205")
        assert response.status_code == 200

        data = response.json()
        assert "sone-205" in data
        assert data["sone-205"]["exists"] is True
        assert data["sone-205"]["count"] == 2


