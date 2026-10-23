"""
/api/parse-filename API 整合測試
"""
from fastapi.testclient import TestClient
from web.app import app


client = TestClient(app)


class TestParseFilename:
    """parse-filename API 測試"""


    def test_multiple_files(self):
        """測試多個檔案批次解析"""
        response = client.post("/api/parse-filename", json={
            "filenames": [
                "SONE-205.mp4",
                "[中文字幕] ABC-123.mkv",
                "FC2-PPV-1234567.mp4"
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["parsed"] == 3
        assert data["results"][0]["number"] == "SONE-205"
        assert data["results"][1]["number"] == "ABC-123"
        assert data["results"][1]["has_subtitle"] is True
        # 139-T1b：FC2 正典形式收斂為 FC2-<純數字>（七種寫法統一，與兩支 FC2 scraper 回的形式一致）
        assert data["results"][2]["number"] == "FC2-1234567"


    def test_mixed_parseable(self):
        """測試混合可解析和不可解析"""
        response = client.post("/api/parse-filename", json={
            "filenames": [
                "SONE-205.mp4",
                "random.mp4",
                "ABC-123.mkv"
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["parsed"] == 2  # 只有 2 個可解析
