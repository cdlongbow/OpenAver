"""前端契約守衛（KEEP，跨檔 contract）— 由 test_frontend_lint.py 拆出（96c T5，純搬移零行為變更）。

module-level 路徑常數為源檔複製（CD-96c-7：源檔殘留 class 仍引用同名常數，故複製非剪走）。
"""
from pathlib import Path

BATCH_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "batch.js"
SEARCH_FLOW_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "search-flow.js"
BASE_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "base.js"
SETTINGS_CONFIG_JS    = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"
SETTINGS_PROVIDERS_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-providers.js"
MAIN_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "main.js"


SETTINGS_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "settings.html"


# [lint-guard: migrate → static_guard_lint]
class TestGalleryOutputDirEmptyFollowsDataRoot:
    """TASK-153b-T3：設定頁空值往返與 resolved placeholder 契約。

    掃描頁 outputPathDisplay 行為由
    web/static/js/pages/scanner/__tests__/output-path-display.test.mjs 守住。
    """

    def _config_js(self):
        return SETTINGS_CONFIG_JS.read_text(encoding="utf-8")

    def _settings_html(self):
        return SETTINGS_HTML.read_text(encoding="utf-8")

    def test_settings_handles_gallery_output_in_program_area_reason(self):
        js = self._config_js()
        assert "gallery_output_in_program_area" in js, \
            "state-config.js 應處理 reason === gallery_output_in_program_area"
        assert "this.showToast(result.error, 'warning')" in js
