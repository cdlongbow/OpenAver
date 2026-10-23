from urllib.parse import quote
from core.path_utils import to_file_uri


# [lint-guard: pytest-justified] 斷言的是端點 render 出來的 HTML，不是靜態檔案裡的字面。中間隔著 f-string 組裝、i18n_t() 解析與例外路徑——「掃源碼有那個字面」是比「回應真的有那個字面」更弱的代理。
class TestPlayerErrorHints:
    """測試影片播放失敗訊息分級（TASK-128-T5）"""

    def test_onerror_maps_decode_and_src_not_supported_to_format_hint(self, client, monkeypatch, tmp_path):
        """error.code 3 (DECODE) 與 4 (SRC_NOT_SUPPORTED) 對應至 format hint，其餘落至 network hint"""
        # [lint-guard: pytest-justified] 斷言端點 render 出來的 onerror 屬性邏輯
        monkeypatch.setattr("web.routers.gallery_media.get_db_path", lambda: tmp_path / "test.db")
        video_path = to_file_uri("C:/videos/test.mp4")
        response = client.get(f"/api/gallery/player?path={quote(video_path)}")
        assert response.status_code == 200
        html = response.text

        expected_onerror = (
            "this.style.display='none';var c=this.error?this.error.code:0;"
            "document.getElementById((c===3||c===4)?'video-error-hint-format':'video-error-hint-network').style.display='flex'"
        )
        assert f"onerror=\"{expected_onerror}\"" in html


