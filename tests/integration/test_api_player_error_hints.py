from urllib.parse import quote
import re
from core.path_utils import to_file_uri


# [lint-guard: pytest-justified] 斷言的是端點 render 出來的 HTML，不是靜態檔案裡的字面。中間隔著 f-string 組裝、i18n_t() 解析與例外路徑——「掃源碼有那個字面」是比「回應真的有那個字面」更弱的代理。
class TestPlayerErrorHints:
    """測試影片播放失敗訊息分級（TASK-128-T5）"""

    def test_onerror_maps_decode_and_src_not_supported_to_format_hint(self, client, monkeypatch, tmp_path):
        """error.code 3 (DECODE) 與 4 (SRC_NOT_SUPPORTED) 對應至 format hint，其餘落至 network hint"""
        # [lint-guard: pytest-justified] 斷言端點 render 出來的 onerror 屬性邏輯
        monkeypatch.setattr("web.routers.scanner.get_db_path", lambda: tmp_path / "test.db")
        video_path = to_file_uri("C:/videos/test.mp4")
        response = client.get(f"/api/gallery/player?path={quote(video_path)}")
        assert response.status_code == 200
        html = response.text

        expected_onerror = (
            "this.style.display='none';var c=this.error?this.error.code:0;"
            "document.getElementById((c===3||c===4)?'video-error-hint-format':'video-error-hint-network').style.display='flex'"
        )
        assert f"onerror=\"{expected_onerror}\"" in html

    def test_two_hint_texts_are_different(self, client, monkeypatch, tmp_path):
        """network 與 format 兩則 hint 文案在 HTML 裡皆存在且內容不同"""
        # [lint-guard: pytest-justified] 斷言端點 render 出來的兩則 i18n 提示文案非空且不相同
        monkeypatch.setattr("web.routers.scanner.get_db_path", lambda: tmp_path / "test.db")
        video_path = to_file_uri("C:/videos/test.mp4")
        response = client.get(f"/api/gallery/player?path={quote(video_path)}")
        assert response.status_code == 200
        html = response.text

        network_match = re.search(r'id="video-error-hint-network"[^>]*>(.*?)</div>', html)
        format_match = re.search(r'id="video-error-hint-format"[^>]*>(.*?)</div>', html)

        assert network_match is not None, "video-error-hint-network element must exist in HTML"
        assert format_match is not None, "video-error-hint-format element must exist in HTML"

        network_text = network_match.group(1).strip()
        format_text = format_match.group(1).strip()

        assert network_text != "", "network hint text should not be empty"
        assert format_text != "", "format hint text should not be empty"
        assert network_text != format_text, "network and format hint texts must be different"

        # Opus 第 2 輪補（agy 與 muse 兩邊都漏了，卡片沒要求 → 卡片的洞不是它們的）：
        # 上面的「兩則不同」在新 key 根本不存在時**照樣會過**——那時 format 那格
        # render 出來的是 `[showcase.video.player_unavailable_format]` 佔位符，
        # 與 network 那句確實不同。使用者會在播不出來的畫面上看到一串方括號 key。
        assert "[showcase.video.player_unavailable_format]" not in html
        assert "[showcase.video.player_unavailable]" not in html

    def test_both_hints_hidden_by_default(self, client, monkeypatch, tmp_path):
        """兩個 hint div 預設皆含有 style=\"display:none\" """
        # [lint-guard: pytest-justified] 斷言端點 render 出來的兩個 hint div 皆預設 display:none
        monkeypatch.setattr("web.routers.scanner.get_db_path", lambda: tmp_path / "test.db")
        video_path = to_file_uri("C:/videos/test.mp4")
        response = client.get(f"/api/gallery/player?path={quote(video_path)}")
        assert response.status_code == 200
        html = response.text

        assert '<div id="video-error-hint-network" style="display:none">' in html
        assert '<div id="video-error-hint-format" style="display:none">' in html
