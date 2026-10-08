"""前端靜態守衛 — 確保 template 包含必要的 Alpine 綁定"""
import json
import re
from pathlib import Path

import pytest
from tests.unit.frontend_contracts._showcase_css import read_showcase_css_full

SHOWCASE_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "showcase.html"


SEARCH_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "search.html"


SHOWCASE_BASE_JS     = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-base.js"
SHOWCASE_VIDEOS_JS   = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-videos.js"
SHOWCASE_ACTRESS_JS  = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-actress.js"
SHOWCASE_LIGHTBOX_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
SHOWCASE_MAIN_JS     = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "main.js"


SETTINGS_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "settings.html"
SCANNER_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "scanner.html"
SCANNER_BATCH_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "scanner" / "state-batch.js"
SCANNER_ALIAS_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "scanner" / "state-alias.js"
SCANNER_MAIN_JS  = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "scanner" / "main.js"
TAILWIND_CSS = Path(__file__).parent.parent.parent / "web" / "static" / "css" / "tailwind.css"

BASE_HTML_T76 = Path(__file__).parent.parent.parent / "web" / "templates" / "base.html"

APPLE_TOUCH_ICON_PNG = Path(__file__).parent.parent.parent / "web" / "static" / "apple-touch-icon.png"
# theme-color 兩個白名單 hex，須與 CSS --color-base-100 token 換算一致
# （dim=[data-theme=dim] base-100、light=[data-theme=light] base-100）
THEME_COLOR_DIM = "#2a303c"
THEME_COLOR_LIGHT = "#ffffff"


BATCH_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "batch.js"
SEARCH_FLOW_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "search-flow.js"
BASE_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "base.js"
SETTINGS_CONFIG_JS    = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"
SETTINGS_PROVIDERS_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-providers.js"
SETTINGS_UI_JS        = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-ui.js"


MAIN_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "main.js"


LOCALES_ROOT = Path(__file__).parent.parent.parent / "locales"


GRID_MODE_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "grid-mode.js"


NAVIGATION_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "navigation.js"
ANIMATIONS_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "animations.js"


RESULT_CARD_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "result-card.js"
PATH_UTILS_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "components" / "path-utils.js"
FILE_LIST_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "file-list.js"


# TestShowcaseActressCRUD（Phase 44a-T5，9 條）已於 117-T6 等價遷入
# scripts/static_guard_lint.mjs [117-T6] R1–R9；#10/#11 由 [117-T4] R3/R4 承接。
# 對帳表見 feature/117-actress-add-panel/TASK-117-T6.md。


# ---------------------------------------------------------------------------
# T6: Scanner Alias UI v2 — 舊 token 移除 + 新 token 存在守衛
# ---------------------------------------------------------------------------
SCANNER_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "scanner.html"
ZH_TW_JSON = Path(__file__).parent.parent.parent / "locales" / "zh_TW.json"


SHOWCASE_ANIMATIONS_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "animations.js"
)


GHOST_FLY_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "shared" / "ghost-fly.js"


class TestDetailSwipeGuard:
    """81c-T4: 守衛 search detail 封面區 swipe 掛載與 handler 契約。

    靜態鎖死：search.html `.av-card-full-cover-wrapper`（只含海報）容器有
    `@touchstart.passive` + `@touchend.passive` 綁定（bs4），且**隔離**確認掛在
    海報 wrapper 而非整個 detail 卡 `.av-card-full`（避免誤掛 metadata 捲動區）、
    亦非外層 `.av-card-full-cover`（含 `.sample-strip` 水平縮圖捲動列，P2 fix：
    避免橫滑縮圖列誤觸 navigate）、且 `.sample-strip` 本身不可有 touch 綁定；navigation.js
    `_dtTouchEnd` handler 含 3 條短路/gate（`rescrapeOpen` / `sampleGalleryOpen` /
    `displayMode`）、直呼 `navigate(1)` / `navigate(-1)`、`detectSwipe(` 呼叫、
    threshold `50`、passive 不 `preventDefault`，且**負向**不含 `showFavoriteActresses`
    （CD-3，detail 純導航不分流）、不含 `lightboxOpen` / `prevLightboxVideo` /
    `nextLightboxVideo`（detail/燈箱隔離）。手勢真實行為由 owner 真機 hard-gate。
    """

    def _js(self):
        return NAVIGATION_JS.read_text(encoding="utf-8")

    def _dt_touch_end_block(self):
        """抽出 _dtTouchEnd method 區塊（brace-depth 匹配，與方法擺放位置無關）。"""
        js = self._js()
        start = js.index("_dtTouchEnd(e) {")
        depth = 0
        for i in range(js.index("{", start), len(js)):
            if js[i] == "{":
                depth += 1
            elif js[i] == "}":
                depth -= 1
                if depth == 0:
                    return js[start:i + 1]
        raise AssertionError("_dtTouchEnd: unbalanced braces")

    def test_dt_touch_end_no_prevent_default(self):
        """_dtTouchEnd 不呼叫 preventDefault（CD-2 passive）"""
        block = self._dt_touch_end_block()
        assert "preventDefault" not in block, \
            "_dtTouchEnd 不可呼叫 preventDefault（passive 掛載）"

    def test_dt_touch_end_no_actress_gate(self):
        """負向守衛：_dtTouchEnd 不含 showFavoriteActresses（CD-3，detail 純導航不分流）"""
        block = self._dt_touch_end_block()
        assert "showFavoriteActresses" not in block, \
            "_dtTouchEnd 不可含 showFavoriteActresses（detail 純導航不分流，CD-3）"

    def test_dt_touch_end_no_lightbox_dispatch(self):
        """負向守衛：_dtTouchEnd 不含 lightbox 字串（detail/燈箱隔離）"""
        block = self._dt_touch_end_block()
        for token in [
            "lightboxOpen",
            "prevLightboxVideo",
            "nextLightboxVideo",
        ]:
            assert token not in block, \
                f"_dtTouchEnd 不可含 {token!r}（detail/燈箱隔離，掛不同容器 / 不同 dispatch）"


# ─── 49b-T4cd: Actress Photo Picker UI/Alpine/SSE 整合守衛 ──────────────────

# Removed in T55b — superseded by stylelint:
#   TestSettingsCssHardcoded, TestHelpCssHardcoded, TestDesignSystemCssHardcoded
#     -> declaration-property-value-disallowed-list (transition / filter / box-shadow)
#        + color-no-hex (with design-system.css whole-file ignore).
# Removed in 96c-T4 — migrated to scripts/css-guard.mjs (zero-dep HTML <style> scan,
# no postcss-html dependency):
#   TestMotionLabHtmlHardcoded       -> CG-ML-01 (blur/hex/radius/duration bans)
#   TestMotionLabObjectPositionGuard -> CG-ML-02 (clip-lab object-position / slot width)


# === 從 tests/test_frontend_lint.py 搬移（T55e）===

# --- 以下為搬移自根目錄的 module-level helpers ---
from typing import List, Tuple

# 專案根目錄（T55e: 從根目錄 tests/test_frontend_lint.py 搬移）
PROJECT_ROOT = Path(__file__).parent.parent.parent  # /home/peace/OpenAver


def find_pattern_in_file(file_path: Path, regex: str,
                         exclude_lines: callable = None) -> List[Tuple[int, str]]:
    """
    在檔案中尋找符合 regex 的行

    Args:
        file_path: 檔案路徑
        regex: 正則表達式 pattern
        exclude_lines: 排除規則函數，接收 (line, line_number) 回傳 True 表示排除

    Returns:
        List of (line_number, line_content) tuples
    """
    violations = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if re.search(regex, line):
                    # 套用排除規則
                    if exclude_lines and exclude_lines(line, i):
                        continue
                    violations.append((i, line.rstrip()))
    except Exception as e:
        pytest.fail(f"無法讀取檔案 {file_path}: {e}")

    return violations


class TestJellyfinFrontend:
    """確認 Jellyfin 前端基礎設施完整"""

    def test_jellyfin_toggle_in_settings(self):
        """settings.html externalManager segmented control（T-d2：4 態 segmented，off/jellyfin/emby/kodi）
        - 舊的 x-model="form.jellyfinMode" 已移除（dead field）
        - 舊的 interim :checked / @change checkbox 綁定已移除
        - 舊的 jellyfin_emby 合併態已拆為獨立 jellyfin / emby（T-d2）
        - 新的 4 態 segmented control + trailing hint 版面
        """
        import re
        html_file = PROJECT_ROOT / "web" / "templates" / "settings.html"
        content = html_file.read_text(encoding='utf-8')
        # 舊 dead field 不存在
        assert 'x-model="form.jellyfinMode"' not in content, \
            "settings.html 不應再有 x-model=\"form.jellyfinMode\"（dead field，已由 externalManager 取代）"
        # interim checkbox 綁定已移除（負守衛）
        assert ":checked=\"form.externalManager === 'jellyfin_emby'\"" not in content, \
            "settings.html 不應再有 interim :checked binding（T8 已換 segmented control）"
        assert "@change=\"form.externalManager = $event.target.checked" not in content, \
            "settings.html 不應再有 interim @change checkbox binding（T8 已換 segmented control）"
        # segmented 容器存在
        assert 'class="settings-sources-segmented"' in content, \
            "settings.html 缺少 .settings-sources-segmented 容器（T8 segmented control）"

        # ---- 負守衛（forbidden）：舊 jellyfin_emby binding 不得殘留 ----
        assert "'is-on': form.externalManager === 'jellyfin_emby'" not in content, \
            "settings.html 不應殘留 jellyfin_emby is-on binding（T-d2 已拆四態）"
        assert "@click=\"form.externalManager = 'jellyfin_emby'\"" not in content, \
            "settings.html 不應殘留 @click = 'jellyfin_emby'（T-d2 已拆四態）"

        # ---- 正斷言：四態 is-on（element-bound 到 segmented 區塊）----
        #   從 content 擷取 settings-form-row--external-manager 區塊後再斷言，
        #   確保 is-on 綁在外部管理器的 segmented button 而非其他地方（element-bound）
        # 80a-T3：頁面 header 另有一個 .settings-sources-segmented[role=group]（server-mode 膠囊），
        # 故先 anchor 到外部管理器 row 再抓 segmented，避免誤匹配 header 膠囊（regex 健化）。
        _em_anchor = content.find("settings-form-row--external-manager")
        assert _em_anchor != -1, "settings.html 缺少 settings-form-row--external-manager 區塊"
        seg_match = re.search(
            r'class="settings-sources-segmented" role="group".*?</div>',
            content[_em_anchor:], re.DOTALL
        )
        assert seg_match, "settings.html 缺少 .settings-sources-segmented[role=group] 容器（外部管理器）"
        seg_block = seg_match.group(0)

        for val in ('off', 'jellyfin', 'emby', 'kodi'):
            assert f"'is-on': form.externalManager === '{val}'" in seg_block, \
                f"settings.html segmented 缺少 externalManager === '{val}' 的 is-on binding"
            # 90c-T5：@click 從靜默 form.externalManager='x' 改為攔截式 requestExternalManagerChange('x')
            assert f"@click=\"requestExternalManagerChange('{val}')\"" in seg_block, \
                f"settings.html segmented 缺少 @click=\"requestExternalManagerChange('{val}')\"（90c-T5 攔截）"
            assert f"@click=\"form.externalManager = '{val}'\"" not in seg_block, \
                f"settings.html segmented 不應殘留舊 @click 直寫 form.externalManager='{val}'（90c-T5 已改攔截）"

        # ---- 正斷言：四段 hint x-show（trailing） ----
        for val in ('off', 'jellyfin', 'emby', 'kodi'):
            assert f"x-show=\"form.externalManager === '{val}'\"" in content, \
                f"settings.html 缺少 externalManager === '{val}' 的 hint x-show"

        # ---- 正斷言：off hint 的 i18n key（新增，驗證 T-d3 key 已引用） ----
        assert "external_manager_off_hint" in content, \
            "settings.html 缺少 external_manager_off_hint i18n key 引用（T-d3 key）"
        assert "external_manager_emby_hint" in content, \
            "settings.html 缺少 external_manager_emby_hint i18n key 引用（T-d3 key）"

    def test_jellyfin_update_in_scanner(self):
        """scanner/state-scan.js 包含 runJellyfinImageUpdate method"""
        js_file = PROJECT_ROOT / "web" / "static" / "js" / "pages" / "scanner" / "state-scan.js"
        content = js_file.read_text(encoding='utf-8')
        assert 'runJellyfinImageUpdate' in content, \
            "scanner/state-scan.js 缺少 runJellyfinImageUpdate（T6d Jellyfin 批次補齊）"


class TestHelpPage:
    """T4b 守衛 — Help 頁必要元素"""

    def test_help_html_contains(self):
        """help.html 含 helpPage / checkUpdate / hero-terminal / help.hero.ai_instruction；
        help.js 以 type="module" 載入（107-P1-T3 Option A：page-module + alpine:init 註冊，
        比照 scanner/main.js；module 隱式 defer 但 helpPage() 經 `alpine:init` listener 註冊
        Alpine.data，時序安全）。禁 defer 屬性（module 已隱式 defer，顯式 defer 無意義且混淆）。"""
        html = (PROJECT_ROOT / 'web/templates/help.html').read_text(encoding='utf-8')
        for expected in ['helpPage', 'checkUpdate', 'hero-terminal', 'help.hero.ai_instruction']:
            assert expected in html, f"help.html missing: {expected!r}"
        assert (PROJECT_ROOT / 'web/static/js/pages/help.js').exists(), \
            "help.js missing: file does not exist"
        matches = re.findall(r'<script[^>]*help\.js[^>]*>', html)
        assert len(matches) == 1, \
            f"help.html 應恰好有 1 個 help.js script tag，找到 {len(matches)} 個"

    def test_help_js_contains(self):
        """help.js 含 copyCurlCommand / execCommand"""
        js = (PROJECT_ROOT / 'web/static/js/pages/help.js').read_text(encoding='utf-8')
        for expected in ['copyCurlCommand', 'execCommand']:
            assert expected in js, f"help.js missing: {expected!r}"

    def test_help_hero_terminal_has_capabilities_base(self):
        """help.html .hero-terminal 帶 data-capabilities-base 屬性（server-aware base_url 來源）。

        81b-T4/T5（US-7）：copy 來源從 window.location.origin 改 server-render base_url，
        經 .hero-terminal 的 data-attr 傳入。值為 Jinja {{ base_url }}，只斷屬性存在。
        mutation：移除 data-capabilities-base → help.js 退 window.location.origin（複製回歸）→ RED。"""
        from bs4 import BeautifulSoup
        html = (PROJECT_ROOT / 'web/templates/help.html').read_text(encoding='utf-8')
        term = BeautifulSoup(html, "html.parser").find(class_="hero-terminal")
        assert term is not None, "help.html 缺少 .hero-terminal 元素"
        assert term.has_attr("data-capabilities-base"), \
            ".hero-terminal 缺少 data-capabilities-base 屬性（US-7 server-aware base_url 來源）"

    def test_help_copy_button_has_aria_label(self):
        """help.html .terminal-copy-btn 為 icon-only（<i class="bi bi-clipboard">）+ a11y 標籤
        （:aria-label 引用 help.hero.copy_curl，鏡像 settings copy 鈕 T6 守衛）。

        Codex P3：T4 換 bi-clipboard icon 後 copy 鈕失去 accessible name → 補 aria-label。
        mutation：移除 :aria-label 或改引用別 key → a11y 斷言 RED。"""
        from bs4 import BeautifulSoup
        html = (PROJECT_ROOT / 'web/templates/help.html').read_text(encoding='utf-8')
        btn = BeautifulSoup(html, "html.parser").find(class_="terminal-copy-btn")
        assert btn is not None, "help.html 缺少 .terminal-copy-btn（curl 複製鈕）"
        assert btn.find("i", class_="bi-clipboard") is not None, \
            ".terminal-copy-btn 缺少 <i class=\"bi bi-clipboard\"> icon"
        aria = btn.get(":aria-label") or btn.get("aria-label")
        assert aria is not None and "help.hero.copy_curl" in aria, \
            f"copy 鈕 aria-label 應引用 help.hero.copy_curl，實際: {aria!r}（P3 a11y 標籤）"

    def test_help_js_copy_uses_capabilities_base_dataset(self):
        """help.js 複製來源讀 dataset.capabilitiesBase（primary），curl 模板用該 base。

        81b-T5（US-7 #7）：base = .hero-terminal?.dataset.capabilitiesBase || window.location.origin。
        防呆 fallback || window.location.origin 刻意保留 — 守衛**不**斷言其不存在（會 false-fail），
        只斷 capabilitiesBase 為 primary 來源 + curl 模板用 derived base。
        mutation：把複製來源改回純 window.location.origin（移除 dataset 讀取）→ capabilitiesBase 消失 → RED。"""
        js = (PROJECT_ROOT / 'web/static/js/pages/help.js').read_text(encoding='utf-8')
        assert "capabilitiesBase" in js, \
            "help.js 缺少 capabilitiesBase（dataset 複製來源 — US-7 #7 primary source）"
        assert "${base}" in js, \
            "help.js curl 模板未用 derived base（應為 `${base}/api/capabilities` — 證 data-attr 是實際來源）"


class TestStreamState:
    """T4 Frontend State + Skeleton Grid 靜態守衛測試

    確認 SSE stream state 的 contract 存在：
    - base.js 宣告 stream state 欄位
    - search-flow.js 處理三種 SSE 事件類型
    - search.html 包含 skeleton template 綁定
    - failed slot 使用 visibility 而非 x-show（C10 約束）
    - search.css 包含 skeleton 動畫樣式
    """

    BASE_JS = PROJECT_ROOT / "web/static/js/pages/search/state/base.js"
    SEARCH_FLOW_JS = PROJECT_ROOT / "web/static/js/pages/search/state/search-flow.js"
    SEARCH_HTML = PROJECT_ROOT / "web/templates/search.html"
    SEARCH_CSS = PROJECT_ROOT / "web/static/css/pages/search.css"

    def test_base_js_core_stream_state(self):
        """base.js 宣告核心 stream state 欄位"""
        content = self.BASE_JS.read_text(encoding='utf-8')
        assert 'streamSlots' in content, "缺少 streamSlots 宣告"
        assert 'streamComplete' in content, "缺少 streamComplete 宣告"
        assert 'isStreaming' in content, "缺少 isStreaming 宣告"

    def test_base_js_staging_buffer_state(self):
        """base.js 宣告 U2 staging buffer state 欄位"""
        content = self.BASE_JS.read_text(encoding='utf-8')
        assert 'streamBuffer' in content, "缺少 streamBuffer 宣告"
        assert 'streamBurstTimer' in content, "缺少 streamBurstTimer 宣告"
        assert 'streamBurstedSlots' in content, "缺少 streamBurstedSlots 宣告"
        assert 'stagingVisible' in content, "缺少 stagingVisible 宣告"

    def test_result_item_uses_stream_buffer(self):
        """result-item handler 推入 streamBuffer，不直接更新 searchResults（U2 batching 約束）；U3 新增 staging state 更新"""
        content = self.SEARCH_FLOW_JS.read_text(encoding='utf-8')
        assert 'streamBuffer' in content, \
            "search-flow.js 缺少 streamBuffer 引用 — U2 batching 邏輯"
        assert 'streamBurstTimer' in content, \
            "search-flow.js 缺少 streamBurstTimer 引用 — U2 時間窗口 timer"
        # U3: result-item handler 更新 staging state
        assert 'stagingCover' in content, \
            "search-flow.js 缺少 stagingCover 引用 — U3 result-item handler 更新 staging display state"
        assert 'stagingNumber' in content, \
            "search-flow.js 缺少 stagingNumber 引用 — U3 result-item handler 更新 staging display state"

    def test_search_flow_handles_seed_event(self):
        """search-flow.js 包含 seed、result-item、result-complete 三種 SSE 事件 handler"""
        content = self.SEARCH_FLOW_JS.read_text(encoding='utf-8')
        assert "data.type === 'seed'" in content, \
            "search-flow.js 缺少 data.type === 'seed' handler — T4 SSE protocol"
        assert "data.type === 'result-item'" in content, \
            "search-flow.js 缺少 data.type === 'result-item' handler — T4 SSE protocol"
        assert "data.type === 'result-complete'" in content, \
            "search-flow.js 缺少 data.type === 'result-complete' handler — T4 SSE protocol"

    def test_search_flow_has_stream_guard(self):
        """search-flow.js 的 result handler 包含 streamComplete guard（C12 約束）"""
        content = self.SEARCH_FLOW_JS.read_text(encoding='utf-8')
        assert 'this.streamComplete' in content, \
            "search-flow.js 缺少 streamComplete guard — T4 防止漸進路徑 result 覆蓋 searchResults"


# ====================================================================
# D1 Guards: 錯誤訊息收斂 + console.log 清理
# ====================================================================


class TestRescrapeVersionStateGuard:
    """86-T3: state-rescrape.js candidates 短狀態 + routing + confirm contract。"""

    SHARED_DIR = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "shared"
    SEARCH_STATE_DIR = (
        Path(__file__).parent.parent.parent
        / "web" / "static" / "js" / "pages" / "search" / "state"
    )
    STATE_RESCRAPE_JS = SHARED_DIR / "state-rescrape.js"
    ADVANCED_PICKER_JS = SEARCH_STATE_DIR / "advanced-picker.js"

    def _rescrape(self):
        return self.STATE_RESCRAPE_JS.read_text(encoding="utf-8")

    def _picker(self):
        return self.ADVANCED_PICKER_JS.read_text(encoding="utf-8")

    # ── (B) advanced-picker.js: _commitSearchResults helper ──

    def test_advanced_search_delegates_to_helper(self):
        """CD-86-14: advancedSearch 成功分支必須委派給 _commitSearchResults，不 inline 賦值。
        element-bound：確認 advancedSearch body 內呼叫 _commitSearchResults（不靠字串存在性）。
        """
        src = self._picker()
        m = re.search(
            r"async\s+advancedSearch\s*\([^)]*\)\s*\{.*?this\._commitSearchResults\s*\(",
            src, re.DOTALL,
        )
        assert m, (
            "CD-86-14 違規：advancedSearch body 中未找到 this._commitSearchResults( 呼叫"
        )

    # ── (B) state-rescrape.js: candidates 短狀態 ──

    def test_candidates_state_keys_present(self):
        """86-T3: rescrapeCandidates / rescrapeVersionIdx 必須平鋪定義。"""
        src = self._rescrape()
        for key in ("rescrapeCandidates", "rescrapeVersionIdx"):
            assert key in src, f"state-rescrape.js missing state key: {key}"

    def test_version_methods_present(self):
        """86-T3: rescrapeHasVersions / rescrapeVersionGo 必須存在。"""
        src = self._rescrape()
        for method in ("rescrapeHasVersions", "rescrapeVersionGo"):
            assert method in src, f"state-rescrape.js missing method: {method}"

    # ── (B) routing: search 入口 javlib 不早 return ──

    def test_search_javlib_does_not_early_return_advancedSearch(self):
        """CD-86-8 / T4：search early return 必須是有條件的，不得無條件走 advancedSearch。

        舊判準是字面 sourceId !== 'javlibrary'；T4 改成查該來源 manual_only。
        意圖不變：search 入口的 preview 路徑只給 CF/manual_only 來源。
        element-bound：search 條件後 400 字元內必須出現 manual_only（防 file-wide false GREEN）。
        """
        src = self._rescrape()
        m_search = re.search(
            r"rescrapeEntryPoint\s*===\s*['\"]search['\"]",
            src,
        )
        assert m_search, "rescrapeWithSource 中未見 rescrapeEntryPoint === 'search' 判斷"
        window = src[m_search.start():m_search.start() + 400]
        # [lint-guard: pytest-justified] method-body window 守衛：斷言的不是「這個字串在檔案裡」，
        # 而是「它出現在 rescrapeEntryPoint === 'search' 這個分支之後的 400 字元內」——
        # 錨點是 regex 比對到的位置，切片範圍由它決定。static_guard_lint 的 required-string
        # 是 whole-file/scope 粒度，表達不了這種相對位移窗口（同 test_contract_code_shape.py:18
        # 的 method-body ordering 案例）。file-wide 版本會假綠：manual_only 在本檔別處也出現。
        assert "manual_only" in window, (
            "CD-86-8 違規：rescrapeWithSource search 分支（前 400 字元）未見 manual_only 判斷——"
            "search 入口 early return 必須依來源 manual_only 條件分流，不得無條件 advancedSearch"
        )

    # ── (B) switch-source 多版本切換器（T7） ──

    def test_switch_source_takes_candidates_first(self):
        """T7（語意反轉）: switch-source 多版本（candidates.length > 1）進 rescrapeStep='preview'，
        不再直接取 candidates[0] 靜默替換；candidates[0] 僅作單版本 fallback。
        element-bound: switch-source + candidates.length > 1 後 900 字元內必有 rescrapeStep='preview'
        （900 < showcase block 距離，mutation A 移除後 next occurrence 在 4000+ 字元外 → RED）。
        """
        src = self._rescrape()
        m = re.search(
            r"rescrapeEntryPoint\s*===\s*['\"]switch-source['\"]"
            r".*?data\.candidates\s*&&\s*data\.candidates\.length\s*>\s*1",
            src, re.DOTALL,
        )
        assert m, (
            "T7 違規：switch-source 分支缺 candidates.length > 1 多版本分叉"
        )
        # element-bound 900-char window（switch-source multiversion block ~773 chars）
        window = src[m.end():m.end() + 900]
        assert re.search(r"rescrapeStep\s*=\s*['\"]preview['\"]", window), (
            "T7 違規：switch-source candidates.length > 1 分叉（900 字元窗口內）缺 rescrapeStep='preview'——"
            "多版本應進 preview 切換器，不直接取 candidates[0] 靜默替換"
        )

    def test_switch_source_multiversion_enters_preview(self):
        """T7: switch-source 分支 candidates.length > 1 → rescrapeStep = 'preview'。
        element-bound: 先找 switch-source if-block 起點，再在 900 字元窗口內斷言 rescrapeStep='preview'。
        （防 DOTALL 跨 block 假綠；showcase block 的 rescrapeStep 距離 4000+ 字元外）
        """
        src = self._rescrape()
        m = re.search(
            r"rescrapeEntryPoint\s*===\s*['\"]switch-source['\"]"
            r".*?if\s*\(\s*data\.candidates\s*&&\s*data\.candidates\.length\s*>\s*1\s*\)",
            src, re.DOTALL,
        )
        assert m, (
            "T7 違規：switch-source if-block 缺 candidates.length > 1 多版本分叉"
        )
        # 900-char window covers multiversion block body but stops before showcase block
        window = src[m.end():m.end() + 900]
        assert re.search(r"rescrapeStep\s*=\s*['\"]preview['\"]", window), (
            "T7 違規：switch-source candidates.length > 1 if-block body（900 字元內）缺 rescrapeStep='preview'"
        )

    def test_switch_source_confirm_branch_present(self):
        """T7: rescrapeConfirm 必須有 switch-source 分支，body 含 t.arr[t.idx] in-place 替換，
        不含 _commitSearchResults（in-place 替換語意，非搜尋結果提交）。
        element-bound: 鎖定 rescrapeConfirm 的 switch-source 分支起點後 800 字元。
        """
        src = self._rescrape()
        m = re.search(
            r"rescrapeConfirm\s*\(\s*\).*?rescrapeEntryPoint\s*===\s*['\"]switch-source['\"]",
            src, re.DOTALL,
        )
        assert m, (
            "T7 違規：rescrapeConfirm 中未見 rescrapeEntryPoint === 'switch-source' 分支"
        )
        # m.end() 是 switch-source 條件字串結尾，從此往後 800 字元是分支 body
        block = src[m.end():m.end() + 800]
        assert re.search(r"t\.arr\s*\[\s*t\.idx\s*\]", block), (
            "T7 違規：rescrapeConfirm switch-source 分支缺 t.arr[t.idx] in-place 替換"
        )
        assert "_commitSearchResults" not in block, (
            "T7 違規：rescrapeConfirm switch-source 分支不得呼叫 _commitSearchResults"
            "（in-place 替換語意，非搜尋結果提交）"
        )

    # ── (B) confirm: detail_url 取值 .url ──

    def test_confirm_lightbox_detail_url_from_url_field(self):
        """CD-86-13: rescrapeConfirm lightbox 分支 detail_url 值必須來自 rescrapePreview.url。"""
        src = self._rescrape()
        # 確認 .url 在 confirm context 存在
        assert re.search(
            r"rescrapeConfirm.*?detail_url.*?rescrapePreview.*?\.url",
            src, re.DOTALL,
        ), (
            "CD-86-13: rescrapeConfirm 中未見 rescrapePreview.url 取值（detail_url 欄位值）"
        )

    # ── (B) confirm: search 走 helper 非 inline ──

    def test_confirm_search_calls_commit_helper(self):
        """CD-86-14: rescrapeConfirm search 分支必須呼叫 _commitSearchResults，禁 inline。
        element-bound：rescrapeConfirm body 內找 search 分支 + helper 呼叫。
        """
        src = self._rescrape()
        m = re.search(
            r"rescrapeConfirm.*?rescrapeEntryPoint.*?['\"]search['\"].*?_commitSearchResults",
            src, re.DOTALL,
        )
        assert m, (
            "CD-86-14 違規：rescrapeConfirm search 分支未呼叫 _commitSearchResults helper"
        )

    # ── lifecycle 對稱：close/back reset candidates ──

    def test_close_rescrape_resets_candidates(self):
        """lifecycle 對稱：closeRescrape 必須 reset rescrapeCandidates。
        element-bound：在 closeRescrape method 體內找 rescrapeCandidates（允許內層 if block）。
        """
        src = self._rescrape()
        # closeRescrape 函式體可能含有內層 if {...} block，故使用 .*? 而非 [^}]*
        m = re.search(
            r"closeRescrape\s*\(\s*\)\s*\{.*?rescrapeCandidates",
            src, re.DOTALL,
        )
        assert m, "closeRescrape 必須 reset rescrapeCandidates（lifecycle 對稱）"

    def test_back_to_pick_resets_candidates(self):
        """lifecycle 對稱：rescrapeBackToPick 必須 reset rescrapeCandidates。"""
        src = self._rescrape()
        m = re.search(
            r"rescrapeBackToPick\s*\(\s*\)\s*\{[^}]*rescrapeCandidates",
            src, re.DOTALL,
        )
        assert m, "rescrapeBackToPick 必須 reset rescrapeCandidates（lifecycle 對稱）"

    # ── CD-86-P2: javlib search 採用路徑同步 currentQuery ──

    def test_javlib_single_version_search_falls_through_to_preview(self):
        """86 修正（取代過時的 ..._syncs_current_query 守衛）：rescrapeWithSource 的單版本
        分支（data.success）不再於 search 入口靜默 _commitSearchResults + closeRescrape
        early-return，而是 fall through 進 preview 卡（rescrapeStep='preview'）。

        為何過時：原守衛斷言「rescrapeWithSource 單版本 search 分支在 _commitSearchResults
        前同步 currentQuery」。該 search-entry 早 return commit 已移除（單版本 search 一閃
        就關被使用者回報「直接跳過」），採用改由 rescrapeConfirm 的 search 分支負責（query
        同步由 test_javlib_confirm_search_syncs_current_query 涵蓋）。

        element-bound：鎖定 data.success 分支區塊（到 not-found else 的 rescrapeNotFound=true
        為止），斷言 (a) 進入 preview（rescrapeStep='preview'），(b) 該區塊不含
        _commitSearchResults / closeRescrape（單版本不再於 rescrapeWithSource commit/關窗）。
        mutation 驗證：把 _commitSearchResults + closeRescrape 早 return 加回 → RED。
        """
        src = self._rescrape()
        # 取 rescrapeWithSource 內 data.success else-if 區塊（至 not-found else 的 rescrapeNotFound）
        m_ctx = re.search(
            r"else\s+if\s*\(\s*data\s*&&\s*data\.success\s*\)\s*\{(.*?)this\.rescrapeNotFound\s*=\s*true",
            src, re.DOTALL,
        )
        assert m_ctx, (
            "86 修正：未找到 rescrapeWithSource 的 data.success 單版本分支區塊"
        )
        block = m_ctx.group(1)
        # (a) 單版本 fall through 進 preview
        assert re.search(r"rescrapeStep\s*=\s*['\"]preview['\"]", block), (
            "86 修正違規：data.success 單版本分支未進 preview（rescrapeStep='preview' 不可達）"
        )
        # (b) 不再於 rescrapeWithSource 單版本分支 commit / 關窗（已移交 rescrapeConfirm）
        # 比對「呼叫」語法（含 ?. optional chain），避免誤判註解中提及的字串。
        assert not re.search(r"_commitSearchResults\s*\??\.?\s*\(", block), (
            "86 修正違規：data.success 單版本分支仍呼叫 _commitSearchResults——"
            "search 單版本應 fall through 進 preview，採用由 rescrapeConfirm 負責"
        )
        assert not re.search(r"\bcloseRescrape\s*\(", block), (
            "86 修正違規：data.success 單版本分支仍呼叫 closeRescrape early return——"
            "search 單版本應 fall through 進 preview（一閃就關是回報的 bug）"
        )

    def test_javlib_confirm_search_syncs_current_query(self):
        """CD-86-P2: rescrapeConfirm search 採用路徑，在 _commitSearchResults 前
        必須同步 currentQuery（對齊非 javlib 路徑，防 session restore 回舊 query）。

        element-bound：在 rescrapeConfirm 的 search 分支找 currentQuery 賦值，
        確認在同一 if(search) block 的 _commitSearchResults 呼叫之前。
        mutation 驗證：移除補的同步 → RED。
        """
        src = self._rescrape()
        # 鎖定 rescrapeConfirm 函式體中 search 分支，_commitSearchResults 呼叫前的 currentQuery 賦值
        m_ctx = re.search(
            r"rescrapeConfirm\b.*?"
            r"rescrapeEntryPoint\s*===\s*['\"]search['\"]"
            r"(.*?)_commitSearchResults",
            src, re.DOTALL,
        )
        assert m_ctx, (
            "CD-86-P2 違規（rescrapeConfirm）：未在 search 分支 _commitSearchResults 前 "
            "找到 currentQuery 同步——多版本 confirm 採用後 session restore 殘留舊 query"
        )
        block = m_ctx.group(1)
        assert re.search(r"\bthis\.currentQuery\s*=", block), (
            "CD-86-P2 違規（rescrapeConfirm）：_commitSearchResults 前缺少 "
            "this.currentQuery = ... 賦值（對齊 advancedSearch :38 的同步語意）"
        )


# ─── 63c-7: i18n zh_TW（DMM proxy hint + Help metatube SQLite hint）───
class TestSettingsQuickToggleGuard:
    """64b-3: quick-toggle 列存在 + 兩 toggle 在列內（CD-64-B8）"""

    SETTINGS_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "settings.html"

    def _html(self):
        return self.SETTINGS_HTML.read_text(encoding="utf-8")

    def test_download_sample_images_in_quick_toggle_row(self):
        html = self._html()
        row_start = html.index('class="settings-quick-toggle-row"')
        # 結束點：取列 div 結束標記（class 末尾）— 用 sec-search 開始當界
        sec_search_pos = html.index('id="sec-search"')
        row_block = html[row_start:sec_search_pos]
        assert 'x-model="form.downloadSampleImages"' in row_block, \
            "64b-3 違規：form.downloadSampleImages x-model 必須在 .settings-quick-toggle-row 內"

    def test_advanced_search_toggle_removed_from_quick_toggle_row(self):
        """74c-T1：進階搜尋 toggle 已從 quick-toggle 列退役（負向守衛）。"""
        html = self._html()
        assert 'x-model="form.advancedSearchEnabled"' not in html, \
            "74c-T1 違規：settings.html 仍含 form.advancedSearchEnabled（toggle 應已退役）"
        assert 'id="advancedSearchToggle"' not in html, \
            "74c-T1 違規：settings.html 仍含 id=advancedSearchToggle（toggle 應已退役）"

    def test_thumbnail_cache_enabled_in_quick_toggle_row(self):
        """71-T5：封面縮圖快取 toggle（form.thumbnailCacheEnabled）必須在 quick-toggle 列內"""
        html = self._html()
        row_start = html.index('class="settings-quick-toggle-row"')
        sec_search_pos = html.index('id="sec-search"')
        row_block = html[row_start:sec_search_pos]
        assert 'x-model="form.thumbnailCacheEnabled"' in row_block, \
            "71-T5 違規：form.thumbnailCacheEnabled x-model 必須在 .settings-quick-toggle-row 內"

    def test_thumbnail_cache_has_help_popover_state(self):
        """71-T5→131b-T4：封面縮圖快取區塊必須有可運作的 help popover（Alpine↔HTML API contract）。

        131b-T4 把 showThumbCacheHelp 旗標搬進 Alpine.data('helpPopover') 共用元件，原字面消失。
        ⚠️ 錨點不能只換成 x-data="helpPopover"／class="help-popover"：舊的 settings-quick-toggle-row
        區間裡有**兩顆**結構相同的浮層（下載劇照 + 封面縮圖快取），共用字面會讓「只拆掉縮圖快取那顆」
        仍然全綠（131b-T4 雙審都抓到這條）。改用**全檔唯一**的 x-model="form.thumbnailCacheEnabled"
        往回找它自己那個 wrapper，把範圍收窄到只含這一顆，專一性與舊錨點相同。"""
        html = self._html()
        tc_pos = html.index('x-model="form.thumbnailCacheEnabled"')  # 全檔唯一（見同 class 其他測試）
        block_start = html.rindex('<div class="settings-form-group popover-anchor"', 0, tc_pos)
        next_group = html.find('<div class="settings-form-group popover-anchor"', tc_pos)
        block_end = next_group if next_group != -1 else html.index('id="sec-search"')
        block = html[block_start:block_end]
        # [lint-guard: pytest-justified] Alpine↔HTML binding contract（pre-merge.md §5.7 例外清單第 2 條）。
        # 鎖的不是「這個字串在檔案裡」，而是「擁有全檔唯一 x-model="form.thumbnailCacheEnabled" 的那個
        # wrapper，必須自己掛著 popover 元件」——範圍由該字面**往回**解析出它自己的 wrapper 決定。
        # ⚠️ 不寫「lint 表達不了」：`static_guard_lint` 的 `scope` 吃整條 RegExp（含 capture group），
        # 用 negative-lookahead 把「不含下一個 wrapper 開頭」寫進去是做得到的。不遷移的理由是另外三個：
        #   ① 這支是 71-T5 就存在的既有測試，131b-T4 只改錨點；遷移要走「等價性維持嚴審」，
        #      成本遠高於它擋的東西（判準句：不修＝我們自己再收斂一次，不是使用者的損失）。
        #   ② 要寫的那條 RegExp 約 200 字元、lookahead 密集，比這 6 行 Python 更難驗；寫歪了是 fail-open。
        #   ③ 它是 TestSettingsQuickToggleGuard 這 17 支同型 HTML 斷言裡的一員，單獨搬走只會讓
        #      class 覆蓋面破碎，而三桶棘輪本來就合計計量——搬桶不減量（§5.7 明文提醒的「換桶」）。
        assert 'x-data="helpPopover"' in block, \
            "71-T5→131b-T4 違規：封面縮圖快取那一顆 ? 的 wrapper 缺少 x-data=\"helpPopover\" 元件掛載"
        assert 'class="help-popover"' in block, \
            "71-T5→131b-T4 違規：封面縮圖快取那一顆 ? 缺少 help-popover 浮層本體"

    def test_thumbnail_cache_toggle_has_change_interceptor(self):
        """71-T11：thumbnailCacheEnabled toggle 必須有 @change="onThumbCacheToggleChange()" 攔截（鏡像 metatube）"""
        html = self._html()
        row_start = html.index('class="settings-quick-toggle-row"')
        sec_search_pos = html.index('id="sec-search"')
        row_block = html[row_start:sec_search_pos]
        m = re.search(
            r'<input\b[^>]*x-model="form\.thumbnailCacheEnabled"[^>]*>',
            row_block, re.DOTALL,
        )
        assert m, "71-T11 違規：找不到 form.thumbnailCacheEnabled toggle input"
        tag = m.group(0)
        assert 'onThumbCacheToggleChange()' in tag, \
            "71-T11 違規：thumbnailCacheEnabled toggle 必須在同一 input 上綁 @change=onThumbCacheToggleChange()"
        assert 'x-model="form.thumbnailCacheEnabled"' in tag, \
            "71-T11 違規：thumbnailCacheEnabled toggle 必須保留 x-model（@change 攔截不取代 x-model）"

    # ===== 71b-T2: disable confirm modal contract =====
    STATE_CONFIG_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"
    STATE_UI_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-ui.js"
    LOCALES_ROOT = Path(__file__).parent.parent.parent / "locales"

    def test_thumb_cache_disable_modal_contract(self):
        """71b-T2：disable fluent-modal 綁 thumbCacheDisableConfirmOpen + i18n title + confirm/cancel handler（element-bound）。"""
        html = self._html()
        # 抽 thumbCacheDisableConfirmOpen 綁定的 <dialog> ... </dialog>
        m = re.search(
            r'<dialog\b[^>]*thumbCacheDisableConfirmOpen[^>]*>(.*?)</dialog>',
            html, re.DOTALL,
        )
        assert m, "71b-T2 違規：缺少綁 thumbCacheDisableConfirmOpen 的 disable <dialog>"
        dialog_open_tag = m.group(0)[:m.group(0).find('>') + 1]
        block = m.group(1)
        assert 'fluent-modal' in dialog_open_tag, \
            f"71b-T2 違規：disable modal 缺 fluent-modal class: {dialog_open_tag!r}"
        assert 'settings.thumbnail_cache.disable_modal.title' in block, \
            "71b-T2 違規：disable modal 缺 i18n disable_modal.title"
        assert 'confirmThumbCacheDisable()' in block, \
            "71b-T2 違規：disable modal 缺 confirmThumbCacheDisable() 確認 handler"
        assert 'cancelThumbCacheDisable()' in block, \
            "71b-T2 違規：disable modal 缺 cancelThumbCacheDisable() 取消 handler"

    def test_thumb_cache_disable_state_stub_declared(self):
        """71b-T2：state-ui.js 必須先宣告 thumbCacheDisableConfirmOpen stub（Alpine 3 ReferenceError 防護）。"""
        js = self.STATE_UI_JS.read_text(encoding="utf-8")
        assert 'thumbCacheDisableConfirmOpen' in js, \
            "71b-T2 違規：state-ui.js 缺 thumbCacheDisableConfirmOpen state stub"

    def test_thumb_cache_disable_handlers_in_state_config(self):
        """71b-T2：state-config.js 含 disable 流程三件（trigger clear + cancel + confirm handler）。"""
        js = self.STATE_CONFIG_JS.read_text(encoding="utf-8")
        assert '_triggerThumbClear' in js, \
            "71b-T2 違規：state-config.js 缺 _triggerThumbClear()（fire-and-forget POST clear）"
        assert '/api/gallery/thumb/clear' in js, \
            "71b-T2 違規：_triggerThumbClear 必須 POST /api/gallery/thumb/clear"
        assert 'cancelThumbCacheDisable' in js, \
            "71b-T2 違規：state-config.js 缺 cancelThumbCacheDisable()"
        assert 'confirmThumbCacheDisable' in js, \
            "71b-T2 違規：state-config.js 缺 confirmThumbCacheDisable()"

    def test_thumb_cache_disable_clear_gated_on_save_success(self):
        """71b-T2：clear trigger 必綁在 saveConfig 成功分支（prevThumbEnabled true→false 才清，先存才清）。"""
        js = self.STATE_CONFIG_JS.read_text(encoding="utf-8")
        # prevThumbEnabled 與 false 的轉換條件 + _triggerThumbClear 同時出現
        assert re.search(
            r'prevThumbEnabled\b.*thumbnailCacheEnabled\s*===\s*false',
            js, re.DOTALL,
        ), "71b-T2 違規：缺 prevThumbEnabled && thumbnailCacheEnabled===false 的 clear 觸發條件"


class TestSettingsDmmProxyContract:
    """64b-3: DMM 灰化 + proxy binding contract 驗證（CD-64-B4）"""

    SETTINGS_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "settings.html"
    STATE_CONFIG_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"

    def _html(self): return self.SETTINGS_HTML.read_text(encoding="utf-8")
    def _js(self): return self.STATE_CONFIG_JS.read_text(encoding="utf-8")

    def test_is_dmm_available_in_state_config(self):
        assert "isDmmAvailable" in self._js(), \
            "64b-3 違規：state-config.js 缺少 isDmmAvailable 函式（DMM 灰化 binding contract）"

    def test_is_dmm_available_reads_proxy_url(self):
        """isDmmAvailable 必須讀 form.proxyUrl（不可改讀其他變數）"""
        js = self._js()
        # 找到 isDmmAvailable 函式 block，確認其中含 proxyUrl
        idx = js.index("isDmmAvailable")
        block = js[idx:idx+200]
        assert "proxyUrl" in block, \
            "64b-3 違規：isDmmAvailable 應讀 form.proxyUrl（DMM 灰化 reactive 來源）"

    def test_dmm_pill_reads_is_dmm_available(self):
        assert ":data-proxy-required" in self._html(), \
            "64b-3 違規：settings.html 缺少 :data-proxy-required（Active Row DMM pill binding）"

    def test_proxy_url_x_model_in_sources_card(self):
        """64b-6: proxy x-model 已移至搜尋來源卡（sec-search），不在 scraperAdvanced 摺疊內"""
        html = self._html()
        # 1. proxy x-model 存在且只有 1 次（搬移非複製）
        assert html.count('x-model="form.proxyUrl"') == 1, \
            "64b-6 違規：x-model=\"form.proxyUrl\" 應恰好出現 1 次（搬移非複製）"
        proxy_model_pos = html.index('x-model="form.proxyUrl"')
        # 2. 位置在 id="sec-search" 之後
        sec_search_pos = html.index('id="sec-search"')
        assert proxy_model_pos > sec_search_pos, \
            "64b-6 違規：proxy x-model 應在 id=\"sec-search\" 之後（在搜尋來源卡內）"
        # 3. 位置在 id="sec-gallery" 之前
        sec_gallery_pos = html.index('id="sec-gallery"')
        assert proxy_model_pos < sec_gallery_pos, \
            "64b-6 違規：proxy x-model 應在 id=\"sec-gallery\" 之前（在搜尋來源卡內，不在 gallery 卡）"
        # 4. 位置在第一個 collapsible-content（scraperAdvanced 摺疊）之前（已移出摺疊）
        collapsible_pos = html.index('class="collapsible-content"')
        assert proxy_model_pos < collapsible_pos, \
            "64b-6 違規：proxy x-model 應在第一個 collapsible-content 之前（已移出進階刮削摺疊）"


PAGE_LIFECYCLE_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "components" / "page-lifecycle.js"


class TestCoverLoadingUx67Guard:
    """67 Cover Loading UX + Showcase Console 清零 守衛（HTML/CSS contract；JS 字串守衛走 eslint，CD-67-8）。

    全部依 G5：先 regex 抽出目標 tag/區塊再斷言其內容，不整檔裸 grep（showcase.html 別處仍有
    合法 <template x-for> 與多個 <img>）。每條皆可 RED→GREEN（破壞 contract 跑 RED、還原 GREEN）。
    """

    def _html(self):
        return SHOWCASE_HTML.read_text(encoding="utf-8")

    def _css(self):
        return read_showcase_css_full(PROJECT_ROOT / "web" / "static")

    def _grid_img(self):
        """抽出 grid 卡片封面 <img>。

        定位不錨在 :src 表達式（該屬性最常被改，150b-T3 已踩過一次），也不錨在本 class
        斷言目標（@load / _imgLoaded / :loading / :fetchpriority）上——否則斷言變同義反覆。
        改走結構錨：`<template x-for="(video, index) in paginatedVideos"` 全檔出現 3 次
        （#1 格狀／#2 表格／#3 清單），re.search 取第一個＝格狀；再從該處往後抓第一個 <img>。
        quote-aware 收尾，避免 x-init 內 `=>` 被 `.*?>` 提前截斷。
        """
        html = self._html()
        m_for = re.search(
            r'<template x-for="\(video, index\) in paginatedVideos"', html
        )
        assert m_for, (
            "showcase.html: 找不到 <template x-for=\"(video, index) in paginatedVideos\" "
            "（取第一個＝格狀；後兩次為表格／清單）"
        )
        rest = html[m_for.start():]
        # <img\s（要空白）避開註解裡的字面「<img>」；quote-aware 收尾避開 x-init 內 `=>`
        m = re.search(r'<img\s(?:[^>"\']|"[^"]*"|\'[^\']*\')*>', rest, re.S)
        assert m, (
            "showcase.html: 格狀 paginatedVideos 區塊內找不到 <img> "
            "（定位自第一個 x-for=\"(video, index) in paginatedVideos\"）"
        )
        return m.group(0)

    def _hero_img(self):
        """抽出 hero 卡片 <img>（含 _matchedActress?.photo_url 的 img tag）"""
        html = self._html()
        m = re.search(r"<img :src=\"_matchedActress\?\.photo_url \|\| ''\".*?>", html, re.S)
        assert m, "showcase.html: hero <img :src=\"_matchedActress?.photo_url || ''\"> 不存在"
        return m.group(0)

    def _rails_svg(self):
        """抽出相似 stage rails <svg class=\"similar-stage-rails\">…</svg> 區塊"""
        html = self._html()
        m = re.search(r'<svg class="similar-stage-rails".*?</svg>', html, re.S)
        assert m, "showcase.html: <svg class=\"similar-stage-rails\"> 區塊不存在"
        return m.group(0)

    # ---- Track B: SVG 靜態化（B1）----

    # ---- Track A: grid 卡片三態（A2）----

    def test_grid_img_first_screen_fetchpriority(self):
        """A2/DoD A-5: grid <img> 首屏前 8 張 eager+high（不可 lazy+high 並存）"""
        img = self._grid_img()
        assert ":loading=\"index < 8 ? 'eager' : 'lazy'\"" in img, \
            "grid <img> 缺首屏 :loading 綁定（index<8 eager 其餘 lazy）"
        assert ":fetchpriority=\"index < 8 ? 'high' : 'auto'\"" in img, \
            "grid <img> 缺 :fetchpriority 綁定（index<8 high 其餘 auto）"
        assert 'loading="lazy"' not in img, \
            "grid <img> 仍有寫死 loading=\"lazy\"（應改 :loading 綁定）"

    # ---- Track A: hero 卡片三態（A3）----

    # ---- Track A: JS 旗標初始化/重置（A2）----

    # ---- Track A: CSS 淡入歸屬 + PRM 退化（A1，DoD A-3/A-4）----

    # ---- Track B: unload 已遷 pagehide（B2，eslint 也擋；此處正向確認 pagehide 在位）----

    # ---- 71-T6: 燈箱封面 blur-up（thumb 底層秒出 → 原圖淡入）----

    def _lightbox_cover_block(self):
        """抽出影片燈箱封面 <div class="lightbox-cover" :class="{'has-cover':…}">…</div> 區塊"""
        html = self._html()
        # 83a modal-hug 給影片 div 加了 :class has-cover（與女優 div 區分）；
        # 83b-T1 在 </div> 後插入說明注釋，故用 has-cover 錨點 + .*?<!-- Metadata Panel 取代 \s*
        m = re.search(r'<div class="lightbox-cover"[^>]*has-cover[^>]*>.*?</div>.*?<!-- Metadata Panel', html, re.S)
        assert m, "showcase.html: 影片燈箱 .lightbox-cover（has-cover :class）區塊不存在"
        return m.group(0)

    def _lb_overlay_img(self):
        """抽出燈箱封面 overlay <img class=\"lb-full\" …>（blur-up 原圖層）"""
        block = self._lightbox_cover_block()
        m = re.search(r'<img class="lb-full"[^>]*>', block, re.S)
        assert m, "showcase.html .lightbox-cover 內缺 overlay <img class=\"lb-full\">（blur-up 原圖層）"
        return m.group(0)


# ── TASK-141b-T10: 書籤牆封面淡入 + 骨架 + 首屏優先 + 空狀態淡入 ──

    # ── 以下五條純字串掃描已於 2026-09-03 搬去 lint（Codex PR review BLOCKER）──────────
    # CLAUDE.md「Lint 守衛規則」north-star：能用 lint 機械處理的就不該進 pytest。
    # plan NC-3 只裁定「既有那支 scope 守衛（test_fade_rule_scoped_to_showcase_container）
    # 維持 pytest」，**沒有**授權新增的這五條；T10 實作端把那個授權就地擴大套用了。
    #   test_wishlist_img_first_screen_fetchpriority → static_guard_lint.mjs（required×2 + forbidden×1）
    #   test_wishlist_has_skeleton_cover            → static_guard_lint.mjs（required-string）
    #   test_wishlist_js_declares_cover_state       → static_guard_lint.mjs（required-string，wishlist.js）
    #   test_wishlist_empty_has_fade_in_animation   → css-guard.mjs CG-WISH-01（沿用同一個 findStandalone 結果）
    #   test_wishlist_fade_and_empty_prm_degrade    → static_guard_lint.mjs（braceBalanced @media scope）
    # 上面 test_wishlist_img_has_load_and_covererror_fade 留在 pytest：它是同檔十個既有
    # 「跨檔 Alpine binding contract」測試的同一家族，單獨搬走一條會製造風格不一致——
    # 那批舊測試要不要一起遷移，依「守衛的退場」規則等下次真的要動它們時再判。


# ── TASK-70-T5: JavLibrary Picker BETA 視覺 + 不可用 gate 靜態守衛 ──

_BOOTSTRAP_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "_advanced_search_bootstrap.html"
_STATE_RESCRAPE_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "shared" / "state-rescrape.js"
_APP_PY = Path(__file__).parent.parent.parent / "web" / "app.py"
_MODAL_HTML_70 = Path(__file__).parent.parent.parent / "web" / "templates" / "_rescrape_modal.html"
_LOCALES_ROOT_70 = Path(__file__).parent.parent.parent / "locales"


# ── TASK-70-T6: CF flow 前端靜態守衛 ──

class TestJavlibraryCfFlowT6Guard:
    """70-T6: CF flow 前端靜態守衛。"""

    # (3) state-rescrape.js 定義 _pollCfThenRetry
    def test_state_rescrape_has_pollCfThenRetry(self):
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        assert "_pollCfThenRetry" in js, \
            "70-T6 違規：state-rescrape.js 未定義 _pollCfThenRetry"

    # (4) state-rescrape.js 定義 cancelCfPoll
    def test_state_rescrape_has_cancelCfPoll(self):
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        assert "cancelCfPoll" in js, \
            "70-T6 違規：state-rescrape.js 未定義 cancelCfPoll"

    # (5) rescrapeWithSource 含 cf_needed 且在 rescrapeNotFound = true 之前
    def test_state_rescrape_cf_needed_before_notfound(self):
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        # Anchor on the consuming expression `data.cf_needed` (not bare `cf_needed`
        # which could match a comment at an earlier position — B2-P3-1 hardening).
        assert "data.cf_needed" in js, \
            "70-T6 違規：state-rescrape.js 未含 data.cf_needed 消費表達式"
        cf_pos = js.index("data.cf_needed")
        # rescrapeNotFound = true 在 showcase 分支的 else 中（最後一次出現）
        notfound_pos = js.rindex("rescrapeNotFound = true")
        assert cf_pos < notfound_pos, \
            "70-T6 違規：cf_needed check 必須在 rescrapeNotFound = true 之前"

    # (5b) P2-2（Codex PR#89）：rescrapeConfirm lightbox 寫檔分支接 cf_needed / cf_unavailable
    def test_rescrape_confirm_handles_cf(self):
        """P2-2：rescrapeConfirm 的 lightbox 寫檔分支必須接 result.cf_needed / result.cf_unavailable。

        T2 後 javlibrary && detail_url 走後端 detail 重抓分支，若預覽→確認間 CF session 過期，
        後端回 {cf_needed} / {cf_unavailable}（已 begin_solve）。confirm 不接 → 卡在模糊「失敗」
        且不啟動 CF 流程。element-bound：鎖定 rescrapeConfirm body（至 _pollCfThenRetry 定義前）。
        mutation：拿掉 CF 接法 → RED。
        """
        import re as _re
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        m = _re.search(r"rescrapeConfirm\s*\(\s*\)\s*\{", js)
        assert m is not None, "P2-2 違規：找不到 rescrapeConfirm() 定義"
        # T4：簽章是 _pollCfThenRetry(number, sourceId)。用 regex 錨定（含逗號），
        # 不得改成去掉右括號的子字串比對（v0.13.10 綠殼坑）。
        end_m = _re.search(r"_pollCfThenRetry\s*\(\s*number\s*,", js[m.start():])
        assert end_m is not None, (
            "P2-2 違規：找不到 _pollCfThenRetry(number, …) 定義錨點"
        )
        end = m.start() + end_m.start()
        body = js[m.start():end]
        assert "result.cf_unavailable" in body, (
            "P2-2 違規：rescrapeConfirm lightbox 分支未接 result.cf_unavailable（CF session 過期靜默卡死）"
        )
        assert "result.cf_needed" in body, (
            "P2-2 違規：rescrapeConfirm lightbox 分支未接 result.cf_needed（CF flow 不啟動）"
        )

    # (6) closeRescrape 含 clearInterval（清 CF poll）
    def test_close_rescrape_clears_interval(self):
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        # 找 closeRescrape 方法定義（定義行含 `closeRescrape() {`）
        # 用 rindex 找最後一個出現的 closeRescrape()，往後 500 chars 覆蓋方法體
        close_pos = js.rindex("closeRescrape()")
        segment = js[close_pos:close_pos + 500]
        assert "clearInterval" in segment, \
            "70-T6 違規：closeRescrape 未呼叫 clearInterval 清 CF poll handle"

    # (7) _rescrape_modal.html 含 rescrapeCfWaiting div + jl_cf_solving + cancelCfPoll
    def test_modal_has_cf_waiting_block(self):
        html = _MODAL_HTML_70.read_text(encoding="utf-8")
        assert "rescrapeCfWaiting" in html, \
            "70-T6 違規：_rescrape_modal.html 缺 rescrapeCfWaiting waiting 區塊"
        assert "jl_cf_solving" in html, \
            "70-T6 違規：_rescrape_modal.html 缺 jl_cf_solving i18n key"
        assert "cancelCfPoll" in html, \
            "70-T6 違規：_rescrape_modal.html Cancel 鈕缺 cancelCfPoll() 綁定"

    # (9) P2 fix: cf_needed / cf_unavailable 必須在 switch-source 分支之前（字串位置守衛）
    # 防回歸：確保 cf_needed 處理不再被 switch-source 分支攔截而落入 rescrapeNotFound=true
    def test_cf_needed_before_switch_source_branch(self):
        """70-T6 P2：cf_needed / cf_unavailable 處理必須在 switch-source 分支之前。

        Codex P2 指出：switch-source 收到 {cf_needed:true} 時，因 data.success falsy
        落入 rescrapeNotFound=true，CF flow 不觸發。修法：上移 cf_needed/cf_unavailable
        至所有入口分支（switch-source / showcase）之前統一處理。
        此守衛確保上移後不回歸（字串位置比對）。

        B2-P3-1 hardening: anchor on `data.cf_needed` (the consuming expression),
        not bare `cf_needed` which could match a comment appearing earlier in the file.

        74a-T4 hardening: anchor sw_pos on the PREVIEW switch-source branch opener
        `rescrapeEntryPoint === 'switch-source') {` (bare, closing-paren + brace),
        NOT the bare-first-occurrence `.index()`. 74a-T4 introduces a switch-source + auto
        short-circuit branch (`rescrapeEntryPoint === 'switch-source' && sourceId === 'auto'`)
        that runs BEFORE the fetch — it cannot intercept CF data, so it is irrelevant to the
        property this guard protects (CF handling must precede the data-consuming PREVIEW branch).
        Anchoring on the bare-opener keeps the guard meaningful (the auto branch opener has
        `&& sourceId === 'auto'` before `)`, so it never matches this anchor).
        """
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        assert "data.cf_needed" in js, \
            "70-T6 P2 違規：state-rescrape.js 未含 data.cf_needed 消費表達式"
        assert "rescrapeEntryPoint === 'switch-source') {" in js, \
            "70-T6 P2 違規：state-rescrape.js 未含 preview switch-source 分支"
        cf_pos = js.index("data.cf_needed")
        sw_pos = js.index("rescrapeEntryPoint === 'switch-source') {")
        assert cf_pos < sw_pos, (
            f"70-T6 P2 違規：data.cf_needed 處理（pos={cf_pos}）必須在 preview switch-source 分支"
            f"（pos={sw_pos}）之前，否則 switch-source 入口永遠看不到 CF flow"
        )

    def test_cf_unavailable_before_switch_source_branch(self):
        """70-T6 P2：cf_unavailable 處理必須在 switch-source 分支之前（與 cf_needed 同理）。

        74a-T4 hardening: 同 test_cf_needed_before_switch_source_branch，sw_pos 錨在 preview
        switch-source 分支 opener（bare `) {`），不受 74a-T4 fetch 前的 auto short-circuit 分支影響。
        """
        js = _STATE_RESCRAPE_JS.read_text(encoding="utf-8")
        assert "cf_unavailable" in js, \
            "70-T6 P2 違規：state-rescrape.js 未含 cf_unavailable 處理"
        assert "rescrapeEntryPoint === 'switch-source') {" in js, \
            "70-T6 P2 違規：state-rescrape.js 未含 preview switch-source 分支"
        cf_unav_pos = js.index("cf_unavailable")
        sw_pos = js.index("rescrapeEntryPoint === 'switch-source') {")
        assert cf_unav_pos < sw_pos, (
            f"70-T6 P2 違規：cf_unavailable 處理（pos={cf_unav_pos}）必須在 preview switch-source 分支"
            f"（pos={sw_pos}）之前"
        )


# ── CD-86-7 frontend guard: search 入口 JL pill gate 改用 isJlUnavailable ──

class TestRescrapeModalSearchHideJlPillGuard:
    """
    CD-86-7：_rescrape_modal.html builtin pill 在 search 入口不再隱藏，改由 isJlUnavailable gate。

    86-T4 rewrite: 舊 search-hide x-show 表達式（FIX-2）已移除（CD-86-7），
    改交 isJlUnavailable 統一管可點性（非桌面仍 aria-disabled，AC8 不回歸）。
    """

    def _html(self):
        return _MODAL_HTML_70.read_text(encoding="utf-8")

    def test_modal_builtin_pill_search_gate_uses_isJlUnavailable(self):
        """CD-86-7: search 入口 javlib pill 不再由 manual_only+is_beta+search 隱藏，
        改由 isJlUnavailable 統一 gate（非桌面仍 aria-disabled）。
        舊 search-hide 表達式必須已移除。
        """
        html = self._html()
        OLD_HIDE = "s.manual_only && s.is_beta && rescrapeEntryPoint === 'search'"
        assert OLD_HIDE not in html, (
            "CD-86-7 違規：_rescrape_modal.html builtin pill 仍含舊 search 入口隱藏條件—"
            "應已移除，改交 isJlUnavailable gate"
        )
        assert "isJlUnavailable" in html, (
            "CD-86-7 違規：_rescrape_modal.html 移除 search-hide 後必須保留 isJlUnavailable gate"
        )

    def test_modal_builtin_pill_jl_gate_preserves_aria_disabled(self):
        """CD-86-7 + AC8: search 入口 javlib pill x-show 放開後，
        isJlUnavailable gate 必須仍帶 aria-disabled 綁定（非桌面不可點語義不回歸）。
        """
        import re
        html = self._html()
        assert "isJlUnavailable" in html, (
            "AC8 違規：_rescrape_modal.html 缺 isJlUnavailable gate"
        )
        assert "aria-disabled" in html, (
            "AC8 違規：_rescrape_modal.html builtin pill 缺 aria-disabled 綁定"
        )
        # element-bound: 確認 isJlUnavailable 和 aria-disabled 在同一 template 上下文（pill 區）
        m = re.search(
            r"isJlUnavailable.*?aria-disabled|aria-disabled.*?isJlUnavailable",
            html, re.DOTALL,
        )
        assert m, (
            "AC8 違規：isJlUnavailable 與 aria-disabled 未出現在 pill 相近上下文"
        )


# ── 86-T4 frontend guard: 版本切換器 + i18n + entry-point gate ──

class TestRescrapeVersionSwitcherGuard:
    """86-T4: _rescrape_modal.html 版本切換器 + i18n + gate 靜態守衛。"""

    TEMPLATES_DIR = Path(__file__).parent.parent.parent / "web" / "templates"
    LOCALES_DIR = Path(__file__).parent.parent.parent / "locales"
    MODAL_HTML = TEMPLATES_DIR / "_rescrape_modal.html"
    ZH_TW_JSON = LOCALES_DIR / "zh_TW.json"

    def _html(self):
        return self.MODAL_HTML.read_text(encoding="utf-8")

    def _locale(self):
        import json
        return json.loads(self.ZH_TW_JSON.read_text(encoding="utf-8"))

    # ── 切換器 x-show binding ──

    def test_version_switcher_uses_rescrapeHasVersions(self):
        """切換器 ‹ › 鈕必須綁 x-show="rescrapeHasVersions()"（element-bound，防 comment 假陽性）。"""
        html = self._html()
        # element-bound: 要求完整屬性綁定出現在非注釋上下文
        BINDING = 'x-show="rescrapeHasVersions()"'
        assert html.count(BINDING) >= 2, (
            f"86-T4 違規：_rescrape_modal.html 缺足夠的 {BINDING!r} 綁定（切換器 ‹ › 各一）"
        )

    def test_version_switcher_uses_rescrapeVersionGo(self):
        """切換器 ‹ › 鈕必須綁 @click rescrapeVersionGo。"""
        html = self._html()
        assert "rescrapeVersionGo(-1)" in html, (
            "86-T4 違規：_rescrape_modal.html 缺 rescrapeVersionGo(-1)（‹ 鈕）"
        )
        assert "rescrapeVersionGo(1)" in html, (
            "86-T4 違規：_rescrape_modal.html 缺 rescrapeVersionGo(1)（› 鈕）"
        )

    # ── versions_found 走 t() 非硬編碼 ──

    # ── 不可逆警告 entry-point gate ──

    def test_overwrite_warning_gated_by_lightbox_entrypoint(self):
        """不可逆警告 rescrape-caption 必須以 rescrapeEntryPoint === 'lightbox' gate。"""
        import re
        html = self._html()
        # element-bound: 在同一個 tag 內找 rescrape-caption 和 lightbox gate
        m = re.search(
            r'rescrape-caption[^>]*rescrapeEntryPoint[^>]*lightbox'
            r'|rescrapeEntryPoint[^>]*lightbox[^>]*rescrape-caption',
            html,
        )
        assert m, (
            "CD-86-9 違規：rescrape-caption（不可逆警告）缺 rescrapeEntryPoint === 'lightbox' gate"
        )

    # 註：search 入口 javlib gate 改 isJlUnavailable 的回歸守衛（CD-86-7 + AC8）
    # 由 TestRescrapeModalSearchHideJlPillGuard 兩條改寫守衛涵蓋，此處不重複。

    # ── i18n key 存在性守衛 ──

    # ── 86-T6: search adopt 鈕 icon 化 + 琥珀色守衛 ──

    def test_search_adopt_btn_uses_check_icon(self):
        """86-T6: search 入口 adopt 鈕必須用 bi-check-lg icon，禁 x-text 文字（破版防回流）。
        element-bound：守衛綁 rescrapeEntryPoint === 'search' 的 confirm-row block。
        aria-label 必須走 adopt_version key（螢幕報讀不退化）。
        """
        import re
        html = self._html()

        # 截出 search confirm-row block（class=rescrape-confirm-row + search gate 的 div 到 </div>）
        m = re.search(
            r'<div[^>]*rescrape-confirm-row[^>]*rescrapeEntryPoint\s*===\s*[\'"]search[\'"][^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        assert m, (
            "86-T6 違規：_rescrape_modal.html 缺 rescrapeEntryPoint === 'search' confirm-row block"
        )
        block = m.group(0)

        # adopt 鈕含 bi-check-lg icon
        assert "bi-check-lg" in block, (
            "86-T6 違規：search adopt 鈕缺 bi-check-lg icon（應鏡射 lightbox ✓ 鈕寫法）"
        )
        # 禁 x-text（防文字溢出破版回流）
        assert "x-text" not in block, (
            "86-T6 違規：search adopt 鈕不得含 x-text（文字溢出 48px 圓鈕破版）"
        )
        # aria-label 走 adopt_version key
        assert "adopt_version" in block, (
            "86-T6 違規：search adopt 鈕缺 adopt_version aria-label（螢幕報讀退化）"
        )

    def test_version_status_uses_warning_color(self):
        """86-T6: .rescrape-version-status 與 .rescrape-ver-indicator 的 color 必須為 var(--color-warning)。
        CSS 守衛（正向 require 值：stylelint 不易 require 特定 token 值，pytest 正向斷言合適）。
        element-bound：綁定該 selector block，避免誤命中其他 selector。
        """
        import re
        css_path = (
            Path(__file__).parent.parent.parent
            / "web" / "static" / "css" / "components" / "rescrape-modal.css"
        )
        css = css_path.read_text(encoding="utf-8")

        def extract_block(selector: str, text: str) -> str:
            """擷取 selector 對應的 { ... } block 內容。"""
            pattern = re.escape(selector) + r"\s*\{([^}]*)\}"
            m = re.search(pattern, text)
            assert m, f"86-T6 違規：rescrape-modal.css 缺 {selector!r} selector block"
            return m.group(1)

        status_block = extract_block(".rescrape-version-status", css)
        assert "var(--color-warning)" in status_block, (
            "86-T6 違規：.rescrape-version-status 的 color 未使用 var(--color-warning)（撞號提示應為琥珀色）"
        )

        indicator_block = extract_block(".rescrape-ver-indicator", css)
        assert "var(--color-warning)" in indicator_block, (
            "86-T6 違規：.rescrape-ver-indicator 的 color 未使用 var(--color-warning)（N/M 指示應為琥珀色）"
        )

    # ── T7: switch-source confirm-row ──

    def test_switch_source_modal_confirm_row(self):
        """T7: _rescrape_modal.html 必須有 rescrapeEntryPoint === 'switch-source' confirm-row，
        含 bi-check-lg icon，且不含 overwrite_warning（只替換結果列 slot，不寫檔）。
        element-bound: 在 switch-source confirm-row block 內驗 icon + 排除 overwrite_warning。
        """
        import re as _re
        html = self._html()
        m = _re.search(
            r'<div[^>]*rescrape-confirm-row[^>]*rescrapeEntryPoint\s*===\s*[\'"]switch-source[\'"][^>]*>(.*?)</div>',
            html,
            _re.DOTALL,
        )
        assert m, (
            "T7 違規：_rescrape_modal.html 缺 rescrapeEntryPoint === 'switch-source' confirm-row"
        )
        block = m.group(0)
        assert "bi-check-lg" in block, (
            "T7 違規：switch-source confirm-row 缺 bi-check-lg icon"
        )
        assert "overwrite_warning" not in block, (
            "T7 違規：switch-source confirm-row 不得含 overwrite_warning（非寫檔操作）"
        )


# ──────────────────────────────────────────────────────────────
# CD-70c-3: frontend CF poll unavailable contract guard
# ──────────────────────────────────────────────────────────────

STATE_RESCRAPE_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "shared" / "state-rescrape.js"
)


SHOWCASE_SIMILAR_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-similar.js"


SOURCE_PILL_MACRO = (
    Path(__file__).parent.parent.parent
    / "web" / "templates" / "_macros" / "source_pill.html"
)


class TestSearchAutoSourcePill:
    """TASK-74a-T2: 搜尋列自動膠囊 macro 呼叫 DOM contract（call-site-bound）。

    守衛抽出 search.html 內含 extra_classes='search-auto-pill' 的 source_pill(...)
    macro 呼叫文字，斷言同一呼叫上：x-show 含 isComposing()；@click 含
    openRescrape(null, 'search') 與 rescrapeNumber = 預填（CD-74a-14 + Codex P1-2）。

    過「三問」：把 isComposing()/@click 搬到別的 macro 呼叫 → 紅（regex 只取
    search-auto-pill 那一個 call）；註解化 → 紅；刪 rescrapeNumber 預填子表達式 → 紅。
    """

    def _auto_pill_call(self) -> str:
        """抽出帶 extra_classes='search-auto-pill' 的 source_pill(...) macro 呼叫文字。"""
        html = SEARCH_HTML.read_text(encoding="utf-8")
        m = re.search(
            r"source_pill\((?:[^()]|\([^()]*\))*search-auto-pill(?:[^()]|\([^()]*\))*\)",
            html,
            re.DOTALL,
        )
        assert m, "search.html 找不到 extra_classes='search-auto-pill' 的 source_pill(...) 呼叫"
        return m.group(0)

    def test_auto_pill_xshow_is_composing(self):
        """自動膠囊 macro 呼叫的 x-show 含 isComposing()（compose 態才顯示）。"""
        call = self._auto_pill_call()
        xshow_m = re.search(r'x-show=\\?["\']([^"\']*)', call)
        assert xshow_m, f"search-auto-pill 呼叫缺 x-show binding；call: {call!r}"
        assert "isComposing()" in xshow_m.group(1), (
            f"search-auto-pill x-show 缺 isComposing()；x-show: {xshow_m.group(1)!r}"
        )


class TestResultSourcePill:
    """TASK-74a-T3: 結果面板「目前來源膠囊」macro 呼叫 DOM contract（call-site-bound）。

    守衛抽出 search.html 內含 extra_classes='result-source-pill' 的 source_pill(...)
    macro 呼叫文字，斷言同一呼叫上接 openSwitchSourcePicker()（@click）、
    _resolveSourceName（name 表達式）、isSwitchingSource（:disabled / :class is-loading）。

    過「三問」：把 binding 搬到別的 macro 呼叫 → 紅（regex 只取 result-source-pill 那一個 call）；
    註解化 → 紅；刪關鍵子表達式 → 紅。
    """

    def _result_pill_call(self) -> str:
        """抽出帶 extra_classes='result-source-pill' 的 source_pill(...) macro 呼叫文字。

        macro 呼叫 attrs 內含多層巢狀括號（rescrapeSources.find(... (current()...) ...)），
        故不走 balanced-paren regex；改抽「source_pill( 起點 → 含 result-source-pill →
        到下一個 ) }} macro 收尾」的呼叫文字（call-site-bound）。
        """
        html = SEARCH_HTML.read_text(encoding="utf-8")
        m = re.search(
            r"source_pill\((?:(?!source_pill\().)*?result-source-pill.*?\)\s*\}\}",
            html,
            re.DOTALL,
        )
        assert m, "search.html 找不到 extra_classes='result-source-pill' 的 source_pill(...) 呼叫"
        return m.group(0)

    def test_result_pill_loading_bound_to_switching(self):
        """目前來源膠囊 loading 綁 isSwitchingSource（:disabled + :class is-loading 驅動 spinner）。"""
        call = self._result_pill_call()
        assert "isSwitchingSource" in call, (
            f"result-source-pill 呼叫缺 isSwitchingSource 綁定（:disabled / is-loading）；call: {call!r}"
        )


STATE_RESCRAPE_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "shared" / "state-rescrape.js"
)


T4_STATE_SIMILAR_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-similar.js"
)


# ============================================================================
# TASK-75b-T6：US1 搜尋詳情重排 + US5 影片卡 poster 格 守衛
# search.html DOM 結構 / search.css + showcase.css element-bound CSS read
# ============================================================================

SEARCH_CSS = Path(__file__).parent.parent.parent / "web" / "static" / "css" / "pages" / "search.css"


# ============================================================================
# TASK-75b-T7（CD-75b-12）：≤480px poster 格 → lightbox ghost-fly 溶接守衛
# 跨檔契約：state-lightbox.js 計算並傳 posterCrop → ghost-fly.js 消費（對齊右裁 + 落地 crossfade）
# ============================================================================

GHOST_FLY_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "shared" / "ghost-fly.js"
STATE_LIGHTBOX_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"


# ============================================================================
# TASK-75b-T8：≤480px 影片燈箱封面貼合原圖比例（消 letterbox 死白 + 根治 T7 seam）
# CSS element-bound 讀取守衛（require-presence of a rule，比照 US5 其他 guard）
# ============================================================================


# ============================================================================
# TASK-75b-T9：search 頁 ≤480px 影片格 + 燈箱修正守衛
# Port of showcase T4/T5/T7/T8 — all search-specific rules live in search.css (決策 ②)
# ============================================================================


# ─── 90c-T5: external_manager switch-mode destructive confirm frontend guards ─


# ─── 80a-T3: Server Mode toggle + info banner frontend guards ───────────────

SETTINGS_CSS = Path(__file__).parent.parent.parent / "web" / "static" / "css" / "pages" / "settings.css"


# ─── TASK-81a-T5: Settings + Help 窄螢幕破版 / 長字串溢出（3 點純 CSS 補丁）───
# ── feature/81 T10 (US-10): 481–899px 影片 grid → 4-col 直式右裁 poster ────────
# ==================== TASK-81a-T11: posterCrop JS↔CSS 門檻對齊（US-10 / CD-10）====================
# 鎖死「posterCrop ghost-fly 門檻 == 燈箱封面貼合斷點 == CSS poster grid 斷點 == 899」跨 4+2 檔。
# 任一處未來漂移（只改一邊）即紅。比照 v0.10.2「JS bail 門檻對齊 CSS」防漂移前例。
T11_BREAKPOINTS_JS    = PROJECT_ROOT / "web" / "static" / "js" / "shared" / "breakpoints.js"
T11_STATE_LIGHTBOX_JS = PROJECT_ROOT / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
T11_GRID_MODE_JS      = PROJECT_ROOT / "web" / "static" / "js" / "pages" / "search" / "state" / "grid-mode.js"
T11_SEARCH_CSS        = PROJECT_ROOT / "web" / "static" / "css" / "pages" / "search.css"


# ---------------------------------------------------------------------------
# feature/82 T4: Settings closeAction select guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# feature/83a T2: Lightbox modal-hug contract guards (8 guards, pure additive)
# ---------------------------------------------------------------------------


# ============================================================================
# TASK-83b-T2: Mobile Similar Panel Contract Guards（13 條）
# 鎖住 T1 建立的行動相似面板合約：CSS default-hidden、safety-net、scrim、burst-card、
# JS drill-lock、no-desktop-close、picker-params、matchMedia、keydown intercept。
# ============================================================================

_T2_SHOWCASE_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "showcase.html"
_T2_SIMILAR_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-similar.js"
)
_T2_LIGHTBOX_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
)
_T2_BASE_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-base.js"
)
_T2_BURST_PICKER_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "shared" / "burst-picker.js"
)


# ============================================================================
# TASK-83b-T3: Mobile Similar Panel Transition Guards（6 條）
# 鎖住 T3 建立的封面飛行進 / 退場合約：helper 存在 / 不包裝禁區 / token 化 /
# async closeMobilePanel / PRM 分支 / 桌面禁區 anchor 不被 mobile helper 引用。
# ============================================================================

_T3_GHOST_FLY_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "shared" / "ghost-fly.js"
)


class TestSimilarMobilePanelT4Guard:
    """83b-T4: 行動相似面板主圖播放按鈕合約守衛"""

    def _html(self):
        return Path("web/templates/showcase.html").read_text(encoding="utf-8")

    def _css(self):
        return read_showcase_css_full(PROJECT_ROOT / "web" / "static")

class TestDirPathHelperGuard:
    """TASK-88a-T2: dirPath helper 簽章守衛 + directory-row template 綁定守衛。

    1. shared/dir-path.js 存在且 export function dirPath
    2. state-scan.js / state-ui.js 各自 import dirPath
    3. scanner.html directory-row 已用 dirPath(dir)（不殘留裸 x-text="dir"）
    4. settings.html directory-row 四處已全 dirPath(dir) 化（:key/:title/@click/x-text）
    5. 無裸 :key="dir" 殘留（settings.html）
    """

    _ROOT = Path(__file__).parent.parent.parent

    def _dir_path_js(self):
        return (self._ROOT / "web" / "static" / "js" / "shared" / "dir-path.js").read_text(encoding="utf-8")

    def _state_scan(self):
        return (self._ROOT / "web" / "static" / "js" / "pages" / "scanner" / "state-scan.js").read_text(encoding="utf-8")

    def _state_ui(self):
        return (self._ROOT / "web" / "static" / "js" / "pages" / "settings" / "state-ui.js").read_text(encoding="utf-8")

    def _scanner_html(self):
        return (self._ROOT / "web" / "templates" / "scanner.html").read_text(encoding="utf-8")

    def _settings_html(self):
        return (self._ROOT / "web" / "templates" / "settings.html").read_text(encoding="utf-8")

class TestDirReadonlyUIGuard:
    """TASK-88a-T4: 唯讀 checkbox + 輸出夾 input Alpine 綁定守衛。

    1. scanner.html 含 x-model="dir.readonly"（checkbox 綁定）
    2. scanner.html 含 x-model="dir.output_path"（輸出夾 input 綁定）
    3. scanner.html 含 x-show="dir.readonly"（條件顯示輸出夾列）
    4. state-scan.js 的 push 包含 readonly 與 output_path 屬性（物件形態，非 bare string）
    """

    _ROOT = Path(__file__).parent.parent.parent

    def _scanner_html(self):
        return (self._ROOT / "web" / "templates" / "scanner.html").read_text(encoding="utf-8")

    def _state_scan(self):
        return (self._ROOT / "web" / "static" / "js" / "pages" / "scanner" / "state-scan.js").read_text(encoding="utf-8")

    def test_scanner_html_output_row_xshow(self):
        """scanner.html 含 x-show="dir.readonly && ..."（條件顯示輸出夾列，非 x-if）

        TASK-89a-T2 (CD-89a-7): 輸出夾欄位現在同時依 `dir.readonly` 與全域
        `external_manager` 白名單顯隱（見 TestOutputPathVisibilityGuard），此測試
        只鎖住「用 x-show 而非 x-if、且條件含 dir.readonly」這個較粗的不變量。
        """
        html = self._scanner_html()
        assert 'x-show="dir.readonly &&' in html, \
            'scanner.html 缺 x-show="dir.readonly && ..." — 應用 x-show 而非 x-if 控制輸出夾列'

    def test_state_scan_push_has_readonly(self):
        """state-scan.js 的 directories.push 包含 readonly 屬性（物件形態）"""
        src = self._state_scan()
        assert 'readonly' in src and 'directories.push' in src, \
            "state-scan.js directories.push 缺 readonly 屬性 — 應改為物件 push"
        # 確認不是 bare push(string)：push 之後必須有物件結構 { path: ..., readonly: ...
        assert '{ path:' in src or '{ path :' in src, \
            "state-scan.js directories.push 應推入 {path, readonly, output_path} 物件"

    def test_state_scan_push_has_output_path(self):
        """state-scan.js 的 directories.push 包含 output_path 屬性（物件形態）"""
        src = self._state_scan()
        assert 'output_path' in src, \
            "state-scan.js 缺 output_path 屬性 — push 物件應含 {path, readonly, output_path}"


# [lint-guard: pytest-justified｜rewrite_failed method-block count (CD-96d-5) + {count} value-format lock (CD-96-14)]
class TestRewriteStrmConfirmGuard:
    """TASK-90c-T6: strm 改寫存後鉤 + heads-up confirm modal 結構守衛（element-bound）"""

    def _html(self):
        return SETTINGS_HTML.read_text(encoding="utf-8")

    def _js(self):
        return SETTINGS_CONFIG_JS.read_text(encoding="utf-8")

    def test_config_js_confirm_calls_real_endpoint_and_toast(self):
        """confirmRewriteStrm 呼叫實際端點 + rewrite_done toast（帶 rewritten）。"""
        js = self._js()
        idx = js.find("async confirmRewriteStrm()")
        assert idx != -1, "state-config.js missing async confirmRewriteStrm()"
        # 界定到方法尾（cancelRewriteStrm 起）——涵蓋 success/else/catch 三分支，避免固定字元窗截斷。
        end = js.find("cancelRewriteStrm()", idx)
        block = js[idx:end if end != -1 else idx + 1200]
        assert "'/api/config/rewrite-strm'" in block, \
            "confirmRewriteStrm missing 實際改寫端點呼叫（無 dry_run）"
        assert "settings.scraper.strm_mapping.rewrite_done" in block, \
            "confirmRewriteStrm missing rewrite_done toast i18n key"
        assert "result.rewritten" in block, \
            "confirmRewriteStrm toast 應帶端點回的精確 rewritten 數"
        # Codex P2：改寫失敗（success:false 或 throw）不可靜默——須 error toast，
        # 否則使用者誤以為「改規則即改寫」已發生（新映射已落盤但既有 .strm 未更新）。
        assert block.count("settings.scraper.strm_mapping.rewrite_failed") >= 2, \
            "confirmRewriteStrm 的 success:false 與 catch 兩分支都須發 rewrite_failed error toast"

    def test_zh_tw_json_has_rewrite_keys(self):
        """locales/zh_TW.json 含 rewrite_confirm 節點 + rewrite_done（只驗 zh_TW，無 4-locale parity）。"""
        zh_tw_path = Path(__file__).parent.parent.parent / "locales" / "zh_TW.json"
        data = json.loads(zh_tw_path.read_text(encoding="utf-8"))
        strm = data.get("settings", {}).get("scraper", {}).get("strm_mapping", {})
        confirm = strm.get("rewrite_confirm")
        assert confirm is not None, "zh_TW.json missing settings.scraper.strm_mapping.rewrite_confirm 節點"
        for key in ["title", "body", "cancel", "confirm"]:
            assert key in confirm, f"rewrite_confirm missing key: {key!r}"
        assert "{count}" in confirm["body"], "rewrite_confirm.body 應含 {count} 插值"
        assert "rewrite_done" in strm, "zh_TW.json missing strm_mapping.rewrite_done"
        assert "{count}" in strm["rewrite_done"], "rewrite_done 應含 {count} 插值"
        assert strm.get("rewrite_failed"), "zh_TW.json missing strm_mapping.rewrite_failed（改寫失敗 toast）"

