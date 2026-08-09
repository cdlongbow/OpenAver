"""
T1: Showcase scroll-triggered toolbar collapse guard
守衛 state-base.js 包含 scroll listener、toolbarOpen 條件、search/actressSearch 條件、
相對基準 Y 追蹤（_toolbarOpenY）、以及 cleanup。
"""
import re
from pathlib import Path


class TestShowcaseScrollCollapse:
    """T1: Showcase scroll-triggered toolbar collapse guard"""

    def _read_state_base(self):
        p = Path("web/static/js/pages/showcase/state-base.js")
        return p.read_text()

    def test_scroll_listener_registered(self):
        """state-base.js 必須包含 scroll listener 登記（passive）"""
        content = self._read_state_base()
        assert "addEventListener('scroll'" in content or 'addEventListener("scroll"' in content

    def test_scroll_collapse_checks_toolbar_open(self):
        """scroll handler 必須檢查 toolbarOpen 才能收合"""
        content = self._read_state_base()
        assert "toolbarOpen" in content

    def test_scroll_collapse_checks_empty_search(self):
        """scroll handler 必須在 search 為空時才收合"""
        content = self._read_state_base()
        assert "search !== ''" in content or "search === ''" in content

    def test_scroll_collapse_checks_actress_search(self):
        """scroll handler 必須同時保護 actressSearch 非空情況"""
        content = self._read_state_base()
        assert "actressSearch" in content

    def test_scroll_collapse_uses_relative_threshold(self):
        """scroll handler 使用相對基準 Y（_toolbarOpenY）而非絕對位置"""
        content = self._read_state_base()
        assert "_toolbarOpenY" in content

    def test_scroll_collapse_resets_baseline_on_auto_close(self):
        """auto-close 後必須立即 reset _toolbarOpenY，防止 reopen 時 stale baseline 立即再收"""
        content = self._read_state_base()
        # toolbarOpen = false 之後的 80 字元內必須有 _toolbarOpenY = null
        idx_close = content.index("toolbarOpen = false")
        idx_reset = content.index("_toolbarOpenY = null", idx_close)
        assert idx_reset < idx_close + 120, "auto-close 後未在同一 block 立即 reset _toolbarOpenY"

    def test_scroll_listener_cleanup(self):
        """cleanup callback 必須移除 scroll listener"""
        content = self._read_state_base()
        assert "removeEventListener" in content
        assert "_scrollHideHandler" in content


class TestShowcaseHeaderSearchIcon:
    """T2: Showcase header 行動搜尋 icon 在有搜尋時顯示 X"""

    def _read_base_html(self):
        return Path("web/templates/base.html").read_text()

    def _read_showcase_html(self):
        return Path("web/templates/showcase.html").read_text()

    def _read_state_base(self):
        return Path("web/static/js/pages/showcase/state-base.js").read_text()

    def _read_state_lightbox(self):
        return Path("web/static/js/pages/showcase/state-lightbox.js").read_text()

    def test_store_has_showcase_has_search(self):
        """$store.ui 必須包含 showcaseHasSearch 欄位"""
        content = self._read_base_html()
        assert "showcaseHasSearch" in content

    def test_button_dispatches_clear_search(self):
        """navbar button 在有搜尋時必須 dispatch showcase:clear-search"""
        content = self._read_base_html()
        assert "showcase:clear-search" in content

    def test_showcase_has_window_listener(self):
        """showcase.html 必須有 @showcase:clear-search.window listener"""
        content = self._read_showcase_html()
        assert "showcase:clear-search" in content

    @staticmethod
    def _extract_search_from_metadata_body(content):
        """brace-matched 擷取 searchFromMetadata 函式體（非整檔 grep，防 FE-GUARD-06 假陽性——
        `this.search = ` 這個字面在檔案其他函式仍合法存在）。"""
        sig_idx = content.find("searchFromMetadata(")
        if sig_idx == -1:
            return ""
        open_idx = content.find("{", sig_idx)
        if open_idx == -1:
            return ""
        depth = 0
        for i in range(open_idx, len(content)):
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return content[open_idx + 1:i]
        return ""

    @staticmethod
    def _extract_has_active_filter_body(content):
        """brace-matched 擷取 _hasActiveFilter 方法定義體（非整檔 grep，防 FE-GUARD-06 假陽性）。
        錨定 `_hasActiveFilter() {` 方法定義，避開 `this._hasActiveFilter()` 呼叫點。"""
        m = re.search(r"_hasActiveFilter\s*\(\s*\)\s*\{", content)
        if not m:
            return ""
        open_idx = m.end() - 1  # 指向 `{`
        depth = 0
        for i in range(open_idx, len(content)):
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return content[open_idx + 1:i]
        return ""

    def test_search_from_metadata_delegates_to_add_pill(self):
        """searchFromMetadata 必須把值交給 addPill（防止重構靜默斷開 pill 篩選路徑）。
        115-T4 前此測試斷言 `this.search = ` 存在——115-T4 把 searchFromMetadata 降格為
        adapter，不再直接寫 this.search，改為呼叫 core 的 addPill()。
        T7 會把 showcaseHasSearch 的判準擴充為涵蓋 pills.length > 0（CD-12），
        在那之前，「有 pill 但 header 仍顯示放大鏡」是已知的中間態（見 T4 卡「邊界條件」段）。"""
        content = self._read_state_lightbox()
        body = self._extract_search_from_metadata_body(content)
        assert body, "state-lightbox.js 找不到 searchFromMetadata 函式體"
        # [lint-guard: pytest-justified] Alpine state contract 跨檔守衛：被守的是
        # state-lightbox.js 的 adapter 必須把值交給 state-videos.js 的 addPill（兩個模組間的
        # 所有權契約），不是單檔字面存在。static_guard_lint 的 required-string 一次只綁一個檔，
        # 表達不出「A 檔委派給 B 檔的函式」這個關係，拆兩條規則會失去連結。
        assert "addPill(" in body, "searchFromMetadata 必須委派給 addPill（pill 篩選路徑的入口）"
        assert "this.search = " not in body, "searchFromMetadata 不應再直接寫 this.search（舊的取代行為，CD-2b）"

    def test_watch_search_updates_showcase_has_search(self):
        """state-base.js 必須有 $watch('search') 更新 showcaseHasSearch（mutation guard）"""
        content = self._read_state_base()
        assert "$watch('search'" in content or '$watch("search"' in content
        assert "showcaseHasSearch" in content

    def test_watch_actress_search_updates_showcase_has_search(self):
        """state-base.js 必須有 $watch('actressSearch') 更新 showcaseHasSearch（mutation guard）"""
        content = self._read_state_base()
        assert "$watch('actressSearch'" in content or '$watch("actressSearch"' in content

    def test_init_sync_showcase_has_search_after_watchers(self):
        """init() 必須經 _hasActiveFilter() 同步 showcaseHasSearch（含 pills；CD-12）。
        115-T7 前斷言舊兩欄位字面；現改為等價契約：函式體含 pills.length ＋ init sync 呼叫它。"""
        content = self._read_state_base()
        body = self._extract_has_active_filter_body(content)
        assert body, "state-base.js 找不到 _hasActiveFilter 函式體"
        # [lint-guard: pytest-justified] Alpine store contract 跨檔守衛：被守的是
        # state-base.js 寫入 → Alpine.store('ui').showcaseHasSearch → showcase.html 讀取
        # 這條跨三檔的資料流（清除鈕出不出現）。單檔字面 lint 守得住寫入端存在，
        # 守不住「判準涵蓋 pills」與「init 也走同一個判準」這兩件事同時成立。
        assert "pills.length" in body, "_hasActiveFilter 必須涵蓋 pills（CD-12）"
        # 直接斷言 init sync 語句存在，防止只靠 $watch 而漏掉初始值路徑
        assert "Alpine.store('ui').showcaseHasSearch = this._hasActiveFilter();" in content
