"""前端契約守衛（KEEP，跨檔 contract）— 由 test_frontend_lint.py 拆出（96c T5，純搬移零行為變更）。

module-level 路徑常數為源檔複製（CD-96c-7：源檔殘留 class 仍引用同名常數，故複製非剪走）。
"""
from pathlib import Path

SETTINGS_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "settings.html"
ZH_TW_JSON = Path(__file__).parent.parent.parent.parent / "locales" / "zh_TW.json"
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # /home/peace/OpenAver
_OPEN_LOCAL_SHARED = PROJECT_ROOT / "web" / "static" / "js" / "shared" / "open-local.js"
_OPEN_LOCAL_PAGE_FILES = [
    PROJECT_ROOT / "web" / "static" / "js" / "pages" / "search" / "state" / "result-card.js",
    PROJECT_ROOT / "web" / "static" / "js" / "pages" / "showcase" / "state-videos.js",
]
_BOOTSTRAP_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "_advanced_search_bootstrap.html"
_STATE_RESCRAPE_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "shared" / "state-rescrape.js"
_APP_PY = Path(__file__).parent.parent.parent.parent / "web" / "app.py"
_MODAL_HTML_70 = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "_rescrape_modal.html"
_LOCALES_ROOT_70 = Path(__file__).parent.parent.parent.parent / "locales"
STATE_RESCRAPE_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "shared" / "state-rescrape.js"
)


class TestHelpUpdateButtonGuard:
    """84-T3: Help 頁「更新」按鈕 + confirm modal 靜態守衛

    契約：
    1. {% if is_desktop %} gate 存在於 help.html（按鈕被正確 gate）
    2. 「更新」按鈕的 @click="triggerUpdate()" 存在於 gate 內
    3. triggerUpdate() DOM binding 不應出現在 gate 外
    4. help.js 定義 triggerUpdate function
    5. modal 的 x-show="showUpdateModal" binding 存在
    6. modal 內含 confirm / cancel 按鈕
    """

    HELP_HTML = PROJECT_ROOT / "web" / "templates" / "help.html"
    HELP_JS   = PROJECT_ROOT / "web" / "static" / "js" / "pages" / "help.js"

    def _html(self):
        return self.HELP_HTML.read_text(encoding="utf-8")

    def _js(self):
        return self.HELP_JS.read_text(encoding="utf-8")

    def test_update_modal_x_show_binding_exists(self):
        """modal 含 x-show="showUpdateModal" binding（防按鈕存在但 modal 永不出現）"""
        html = self._html()
        assert 'showUpdateModal' in html, \
            "help.html 缺 showUpdateModal binding — update confirm modal 無法顯示"

    def test_update_modal_has_confirm_and_cancel(self):
        """modal 內含 confirmUpdate() 和 cancelUpdate() 呼叫（confirm/cancel 按鈕齊全）"""
        html = self._html()
        assert 'confirmUpdate()' in html, \
            "help.html 缺 confirmUpdate() — modal 確認按鈕不存在"
        assert 'cancelUpdate()' in html, \
            "help.html 缺 cancelUpdate() — modal 取消按鈕不存在"

