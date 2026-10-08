"""前端契約守衛（KEEP，跨檔 contract）— 由 test_frontend_lint.py 拆出（96c T5，純搬移零行為變更）。

module-level 路徑常數為源檔複製（CD-96c-7：源檔殘留 class 仍引用同名常數，故複製非剪走）。
"""
import re
from pathlib import Path

SEARCH_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "search.html"
SHOWCASE_BASE_JS     = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-base.js"
SHOWCASE_VIDEOS_JS   = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-videos.js"
SHOWCASE_ACTRESS_JS  = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-actress.js"
SHOWCASE_LIGHTBOX_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
SETTINGS_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "settings.html"
SCANNER_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "scanner.html"
SCANNER_SCAN_JS  = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "scanner" / "state-scan.js"
SETTINGS_CONFIG_JS    = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"
MAIN_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "main.js"
LOCALES_ROOT = Path(__file__).parent.parent.parent.parent / "locales"
RESULT_CARD_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "result-card.js"
PATH_UTILS_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "components" / "path-utils.js"
FILE_LIST_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "file-list.js"
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # /home/peace/OpenAver
SETTINGS_CSS            = Path(__file__).parent.parent.parent.parent / "web" / "static" / "css" / "pages" / "settings.css"
STATE_RESCRAPE_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "shared" / "state-rescrape.js"
)


class TestDateGatingGuard:
    """TASK-106-T7: 發售日欄位特例——唯讀 span 與原生 date picker 的互補閘。
    唯讀 span 顯示 = 不可編輯 或 已有日期；picker 顯示 = file 模式 且 無日期。
    兩閘引用 canEditFile()（定義於 base.js），是跨檔 Alpine binding contract，
    非單純字串存在檢查，static_guard_lint 無法表達此跨檔語意。
    """

    def _html(self):
        return SEARCH_HTML.read_text(encoding="utf-8")

    def test_search_html_date_input_wired_to_identity_guarded_methods(self):
        """Codex PR#116 P2: date picker 是四個可編輯欄位中唯一原本沒有 stale-candidate 身分
        守衛的——@change 直寫 `current().date = ...` 在事件當下才 re-resolve current()，若打開
        日曆到選好日期之間候選被換掉（背景批次/換源/切檔）會把日期寫進錯的候選。

        鎖定 date input 必須改走 result-card.js 的 startEditDate()/confirmEditDate()（與
        title/chineseTitle/actors 同源 identity-guard pattern），防未來改回直寫 current().date
        的回歸。這是 search.html ↔ result-card.js 的跨檔 Alpine binding contract（方法是否被
        定義、guard 邏輯是否正確由對應的 .mjs 單元測試覆蓋），非單純字串存在檢查，
        static_guard_lint 無法表達此跨檔語意。
        """
        # [lint-guard: pytest-justified] 同 class docstring 理由：canEditFile() 系列已在本
        # class 建立先例——跨檔 Alpine binding contract 用 pytest 鎖，不是前端靜態字串存在檢查。
        html = self._html()
        for expected in [
            '@focus="startEditDate()"',
            '@change="confirmEditDate($event.target.value)"',
        ]:
            assert expected in html, f"search.html missing: {expected!r}"
        assert "current().date = $event.target.value" not in html, (
            "date input 不應退回直寫 current().date（繞過身分守衛，見 Codex PR#116 P2）"
        )


class TestShowcaseAliasGuard:
    """T5 (45-actress-alias): Frontend Guard — alias injection guard (method folded)"""

    def _js(self):
        return (
            SHOWCASE_BASE_JS.read_text(encoding="utf-8") + "\n" +
            SHOWCASE_ACTRESS_JS.read_text(encoding="utf-8") + "\n" +
            SHOWCASE_VIDEOS_JS.read_text(encoding="utf-8")
        )

    def test_alias_js_contains(self):
        """showcase JS 含 _nameToGroup 宣告 + API + 使用"""
        js = self._js()
        for expected in [
            "var _nameToGroup = {}",
            "/api/actress-aliases",
            "_nameToGroup[a.name]",
            "_nameToGroup[term]",
        ]:
            assert expected in js, f"showcase JS missing: {expected!r}"
        # _checkPreciseActressMatch function body must use _nameToGroup
        func_start = js.find("async _checkPreciseActressMatch")
        func_end = js.find("},", func_start)
        func_body = js[func_start:func_end]
        assert "_nameToGroup" in func_body, \
            "showcase JS _checkPreciseActressMatch missing: '_nameToGroup'"


class TestRescrapeStateGuard:
    """62a-3: 守衛 state-rescrape.js mixin contract — 確保 partial（_rescrape_modal.html）引用的
    state/method 全揭露、commit 契約（enrich-single + refresh_full + overwrite_existing）正確、
    transient 不碰 currentLightboxVideo（CD-62-2），且 main.js mergeState 鏈整合。
    match TestSimilarStageGuard L1164 pattern。
    """

    SHARED_DIR = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "shared"
    SHOWCASE_DIR = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase"
    STATE_RESCRAPE_JS = SHARED_DIR / "state-rescrape.js"
    MAIN_JS = SHOWCASE_DIR / "main.js"

    def _src(self):
        return self.STATE_RESCRAPE_JS.read_text(encoding="utf-8")

    def _main(self):
        return self.MAIN_JS.read_text(encoding="utf-8")

    def test_state_rescrape_file_exists(self):
        """state-rescrape.js 必須存在於 shared/（供 showcase + search 共用）。"""
        assert self.STATE_RESCRAPE_JS.exists(), \
            f"state-rescrape.js missing at {self.STATE_RESCRAPE_JS!s}"

    def test_exports_rescrape_state_factory(self):
        """必須 export function rescrapeState（factory，rescrapeState.call(this) 接入 mergeState）。"""
        src = self._src()
        assert re.search(r"export\s+function\s+rescrapeState\s*\(", src), \
            "state-rescrape.js missing: export function rescrapeState()"

    def test_defines_all_methods(self):
        """6 個 partial 引用的 method + openRescrape（62b-1 呼叫）必須揭露。"""
        src = self._src()
        for method in (
            "openRescrape", "rescrapeWithSource", "rescrapeConfirm",
            "rescrapeBackToPick", "closeRescrape", "rescrapeBuiltinSources",
            "rescrapeMetatubeSources",
        ):
            assert method in src, f"state-rescrape.js missing method: {method}"

    def test_commit_contract(self):
        """commit 契約：POST /api/enrich-single + mode refresh_full + overwrite_existing。"""
        src = self._src()
        assert "'/api/enrich-single'" in src, "missing POST /api/enrich-single"
        assert "refresh_full" in src, "missing mode: refresh_full（CD-62-0/4）"
        assert "overwrite_existing" in src, "missing overwrite_existing（CD-62-4）"
        assert "true" in src, "overwrite_existing 必須為 true"

    def test_preview_contract(self):
        """preview 契約：POST /api/rescrape/preview。"""
        src = self._src()
        assert "'/api/rescrape/preview'" in src, "missing POST /api/rescrape/preview"

    def test_no_current_lightbox_video(self):
        """CD-62-2 transient 守衛：mixin 絕不讀寫 currentLightboxVideo（用私有 _rescrapeVideo）。"""
        src = self._src()
        assert "currentLightboxVideo" not in src, \
            "state-rescrape.js 違反 CD-62-2：不得引用 currentLightboxVideo，應用私有 _rescrapeVideo"

    def test_main_js_imports_and_merges_rescrape_state(self):
        """main.js 必須 import rescrapeState 並插入 mergeState 鏈。"""
        src = self._main()
        assert "from '@/shared/state-rescrape.js'" in src, \
            "main.js missing: import { rescrapeState } from '@/shared/state-rescrape.js'"
        assert "rescrapeState.call(this)" in src, \
            "main.js mergeState chain missing: rescrapeState.call(this)"

    def test_open_rescrape_reads_video_number(self):
        """62b-2 #1：openRescrape 內 rescrapeNumber 預填來源必須 = video.number（前端 prefill 持久化連結）。

        鎖住「commit 修正 number → refreshVideoData 突變 video.number → 再開彈窗預填新值」鏈的前端端點。
        若 refactor 把預填改成讀別處（如固定 '' 或 video.code），此守衛 RED。
        """
        src = self._src()
        # 寬鬆匹配：rescrapeNumber = (... video.number ...) ；允許 =、&&、() 周圍空白變動
        assert re.search(r"rescrapeNumber\s*=.*video\s*&&\s*video\.number", src), \
            "openRescrape 必須將 rescrapeNumber 預填自 video.number（前端 prefill 連結，62b-2 #6）"

    def test_close_rescrape_clears_longpress_flag(self):
        """74c-T3（翻轉）：longPressReset?.() 呼叫已隨長壓基礎設施退役移除；state-rescrape.js 不得再含此呼叫。"""
        src = self._src()
        assert "longPressReset" not in src, \
            "74c-T3 違規：closeRescrape 仍含 longPressReset（長壓基礎設施已退役，此呼叫應移除）"

    def test_rescrape_metatube_sources_has_routable_gate(self):
        """Codex PR#47 round-2 P2-B：rescrapeMetatubeSources() 必須同時 filter
        type === 'metatube' AND routable === true（element-bound regex，防空字串假測試）。

        metatube sources 目前後端無路由（validate_source_id 只認 auto + builtin SOURCE_ORDER）；
        B3 才接 metatube route/validator，屆時後端揭露 routable=true 後 pill 才長出。
        直到 B3 前，缺 routable gate 的 metatube pill 點下去 → not-found；本守衛確保回歸會 RED。
        """
        src = self._src()
        # element-bound regex：匹配 rescrapeMetatubeSources 函式體，確認同時含兩個 filter 條件
        m = re.search(
            r"rescrapeMetatubeSources\s*\(\s*\)\s*\{[^}]*\.filter\s*\([^)]*"
            r"s\.type\s*===\s*['\"]metatube['\"][^)]*&&[^)]*s\.routable\s*===\s*true[^)]*\)",
            src,
            re.DOTALL,
        )
        assert m, (
            "rescrapeMetatubeSources() 必須 filter s.type === 'metatube' && s.routable === true "
            "（缺 routable gate：metatube pill 在後端無路由前點下去 → not-found，Codex PR#47 round-2 P2-B）"
        )


class TestServerModeToggleGuard:
    """80a-T3: settings.html + state-config.js server-mode toggle/banner 靜態守衛。

    每個 assertion 都是 mutation-sensitive：刪除對應實作即 RED。
    使用 BeautifulSoup DOM 解析（attribute 順序無關）+ substring 雙重策略，
    鏡照既有 settings 守衛慣例（SETTINGS_HTML / SETTINGS_CONFIG_JS path 常數）。
    """

    def _html(self):
        return SETTINGS_HTML.read_text(encoding="utf-8")

    def _js(self):
        return SETTINGS_CONFIG_JS.read_text(encoding="utf-8")

    # ── HTML guards ────────────────────────────────────────────────────────────

    def test_settings_root_has_data_lan_ip(self):
        """#settings-components root div 含 data-lan-ip 屬性（傳 lanIp 到 Alpine）。
        移除此屬性 → lanIp 永遠空字串，URL 顯示錯誤。"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(self._html(), "html.parser")
        root = soup.find(id="settings-components")
        assert root is not None, "settings.html 找不到 #settings-components"
        assert root.has_attr("data-lan-ip"), \
            "#settings-components 缺少 data-lan-ip 屬性（80a-T3 lanIp 傳入點）"

    # ── JS guards ──────────────────────────────────────────────────────────────

    def test_set_server_mode_lan_ip_nullish_uses_null_not_stale(self):
        """P2-2: setServerMode() enable 成功分支用 `result.lan_ip ?? null`，不用 `?? this.lanIp`。
        用 `?? this.lanIp` → 後端返 null（IP 偵測失敗）時 banner 仍顯示舊 IP，指向失效 URL。
        必須用 `?? null` 讓 serverUrl() 返 null，正確顯示 no_lan_ip/listener_down 提示。"""
        js = self._js()
        assert "result.lan_ip ?? null" in js, (
            "state-config.js setServerMode() 須用 'result.lan_ip ?? null'（P2-2）；"
            "不可用 '?? this.lanIp'（保留舊 IP 會在 IP 偵測失敗時顯示死連結）"
        )
        assert "result.lan_ip ?? this.lanIp" not in js, (
            "state-config.js setServerMode() 不得用 'result.lan_ip ?? this.lanIp'（P2-2 stale IP bug）"
        )

    def test_load_config_lan_ip_nullish_uses_null_not_stale(self):
        """P2-2: loadConfig() GET lan-port 分支用 `j.lan_ip ?? null`，不用 `?? this.lanIp`。
        用 `?? this.lanIp` → 重載後 lan_ip=null（偵測失敗）時 banner 仍顯示舊 IP。
        必須用 `?? null` 讓 serverUrl() 返 null 觸發正確的 no_lan_ip 提示路徑。"""
        js = self._js()
        assert "j.lan_ip ?? null" in js, (
            "state-config.js loadConfig() 須用 'j.lan_ip ?? null'（P2-2）；"
            "不可用 '?? this.lanIp'（保留舊 IP 會在 IP 偵測失敗時顯示死連結）"
        )
        assert "j.lan_ip ?? this.lanIp" not in js, (
            "state-config.js loadConfig() 不得用 'j.lan_ip ?? this.lanIp'（P2-2 stale IP bug）"
        )


class TestScannerClearCache:
    """清除快取守衛 — scanner 頁面必要元素"""

    def test_scanner_clear_cache_js_contains(self):
        """scanner/state-scan.js 含 clearCache() + DELETE /api/gallery/cache"""
        js = (PROJECT_ROOT / 'web/static/js/pages/scanner/state-scan.js').read_text(encoding='utf-8')
        for expected in ['clearCache()', '/api/gallery/cache', 'DELETE']:
            assert expected in js, f"scanner/state-scan.js missing: {expected!r}"


class TestAliasLiveQueryGuard:
    """49a-T3: Actress Lightbox 別名即時查 guard

    驗證：
    - _fetchLiveAliases 方法存在
    - 200 分支以 Object.assign 覆蓋 aliases（CD-4 + §8.4 reactivity）
    - 404 / error / timeout 保留 snapshot（catch + 不覆蓋 fallback）
    """

    def _js(self):
        # _fetchLiveAliases / openActressLightbox / prevActressLightbox / nextActressLightbox → state-actress.js
        # openHeroCardLightbox → state-lightbox.js
        return (
            SHOWCASE_ACTRESS_JS.read_text(encoding="utf-8") + "\n" +
            SHOWCASE_LIGHTBOX_JS.read_text(encoding="utf-8")
        )

    def _extract_method_body(self, js, method_name):
        """抓取 Alpine state method 函式主體，大括號平衡（容忍 async 前綴）。"""
        pattern = re.compile(
            r'(?:^|\n)\s*(?:async\s+)?' + re.escape(method_name) + r'\s*\([^)]*\)\s*\{',
            re.DOTALL,
        )
        m = pattern.search(js)
        assert m is not None, f"showcase/core.js 找不到 {method_name} 方法"
        start = m.end()
        depth = 1
        i = start
        while i < len(js) and depth > 0:
            c = js[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            i += 1
        return js[start:i - 1]

    def test_fetch_live_aliases_method_exists(self):
        """core.js 含 async _fetchLiveAliases 方法定義"""
        js = self._js()
        assert re.search(r'async\s+_fetchLiveAliases\s*\([^)]*\)\s*\{', js), \
            "showcase/core.js 缺少 async _fetchLiveAliases(...) 方法定義"
        # 必須呼叫 /api/actress-aliases/ 端點
        body = self._extract_method_body(js, '_fetchLiveAliases')
        assert "/api/actress-aliases/" in body, \
            "_fetchLiveAliases 函數體缺少 /api/actress-aliases/ 端點呼叫"

    def test_200_branch_uses_object_assign(self):
        """200 分支用 Object.assign 覆蓋 currentLightboxActress.aliases（§8.4 Alpine reactivity）"""
        js = self._js()
        body = self._extract_method_body(js, '_fetchLiveAliases')
        # 必須有 200 status 分支
        assert re.search(r'(?:resp|response)\.status\s*===\s*200', body), \
            "_fetchLiveAliases 缺少 resp.status === 200 分支"
        # 必須用 Object.assign 建立新物件以觸發 Alpine deep watch（§8.4）
        assert re.search(r'Object\.assign\s*\(', body), \
            "_fetchLiveAliases 200 分支應用 Object.assign 建立新物件以觸發 Alpine reactivity（§8.4）"
        # 覆蓋的目標必須是 aliases
        assert re.search(r'aliases\s*:', body), \
            "_fetchLiveAliases Object.assign 應指定 aliases 屬性"

    def test_fallback_preserves_snapshot_on_error(self):
        """error / timeout / 404 分支保留 snapshot（catch 區塊不覆蓋 aliases）"""
        js = self._js()
        body = self._extract_method_body(js, '_fetchLiveAliases')
        # 必須有 try / catch 區塊（fallback contract）
        assert re.search(r'\btry\s*\{', body), \
            "_fetchLiveAliases 缺少 try 區塊（error fallback contract）"
        assert re.search(r'\bcatch\s*\(', body), \
            "_fetchLiveAliases 缺少 catch 區塊（error fallback contract）"
        # 200 分支應用 if 包裹（亦即 404/其他狀態落入 implicit fallback：不執行覆蓋）
        # 實作必須讓「非 200」 + 「catch」 不執行 Object.assign
        # 用結構驗證：Object.assign 必須出現在 if (resp.status === 200) { ... } 區塊內
        pattern = re.compile(
            r'if\s*\(\s*(?:resp|response)\.status\s*===\s*200\s*\)\s*\{[^}]*?Object\.assign',
            re.DOTALL,
        )
        assert pattern.search(body), \
            "_fetchLiveAliases Object.assign 應位於 if (resp.status === 200) {...} 區塊內，避免非 200 分支誤覆蓋 snapshot"

    def test_callsites_in_open_actress_and_hero(self):
        """openActressLightbox（兩分支）+ openHeroCardLightbox 皆 fire-and-forget 呼叫 _fetchLiveAliases"""
        js = self._js()
        actress_body = self._extract_method_body(js, 'openActressLightbox')
        # 至少 2 處（首次進入 + 切換女優）
        actress_calls = re.findall(r'_fetchLiveAliases\s*\(', actress_body)
        assert len(actress_calls) >= 2, \
            f"openActressLightbox 應至少 2 處呼叫 _fetchLiveAliases（首次進入 + 切換女優），目前 {len(actress_calls)} 處"

        hero_body = self._extract_method_body(js, 'openHeroCardLightbox')
        assert re.search(r'_fetchLiveAliases\s*\(', hero_body), \
            "openHeroCardLightbox 缺少 _fetchLiveAliases 呼叫"

    def test_prev_next_actress_lightbox_refetch_aliases(self):
        """Codex P2: prev/nextActressLightbox 在切換 index 後也須呼叫 _fetchLiveAliases，
        否則方向鍵切換時 SSOT 心智模型破功（看到 stale snapshot）。"""
        js = self._js()
        for method in ('prevActressLightbox', 'nextActressLightbox'):
            body = self._extract_method_body(js, method)
            assert re.search(r'_fetchLiveAliases\s*\(', body), (
                f"{method} 缺少 _fetchLiveAliases 呼叫（Codex P2 fix）— "
                "方向鍵切換時不重抓 alias，違反 T3 SSOT 設計"
            )


class TestJellyfinCheckManualGuard:
    """40c-T2: 守衛 Jellyfin check 改為手動觸發的所有前端不變式"""

    def _html(self):
        return SCANNER_HTML.read_text(encoding="utf-8")

    def _js(self):
        return SCANNER_SCAN_JS.read_text(encoding="utf-8")

    def test_no_auto_trigger_in_init(self):
        """init() 後的 loadStats 呼叫後，不應緊接 checkJellyfinImages()"""
        # 確認 checkJellyfinImages() 只透過 @click 觸發，不在 init() 或 loadStats 後出現
        js = self._js()
        assert "this.loadStats();\n        this.checkJellyfinImages();" not in js, \
            "scanner.js init() 仍含自動觸發 checkJellyfinImages()"

    def test_trigger_button_click_handler(self):
        """觸發按鈕 @click 呼叫 checkJellyfinImages()"""
        html = self._html()
        assert '@click="checkJellyfinImages()"' in html, \
            "scanner.html 缺少 @click=\"checkJellyfinImages()\" 觸發按鈕"

    def test_no_auto_trigger_after_generate(self):
        """generate SSE done 事件後無自動呼叫 checkJellyfinImages()"""
        js = self._js()
        # loadStats 後面不應接 checkJellyfinImages（generate 路徑）
        assert "this.loadStats();\n                    this.checkJellyfinImages();" not in js, \
            "scanner.js generate done 路徑仍自動呼叫 checkJellyfinImages()"

    def test_trigger_row_xshow_uses_jellyfin_image_visible(self):
        """T3(40c) / T-d4 / 72d-codexP2: 觸發列 x-show 用正向白名單 gate（fail-closed，含 kodi）"""
        from bs4 import BeautifulSoup
        html = self._html()
        soup = BeautifulSoup(html, "html.parser")
        # There are multiple nfo-update-row divs; the jellyfin trigger row is the one
        # whose x-show references jellyfinImageVisible (not nfoUpdateVisible etc.)
        rows = soup.find_all("div", class_="nfo-update-row")
        jellyfin_row = next(
            (r for r in rows if "jellyfinImageVisible" in r.get("x-show", "") and "config" in r.get("x-show", "")),
            None
        )
        assert jellyfin_row is not None, \
            "scanner.html 找不到含 jellyfinImageVisible + config 的 nfo-update-row element"
        xshow = jellyfin_row.get("x-show", "")
        # 正向白名單（fail-closed）：config={} / undefined 時 gate 為 false，不顯示
        assert "['jellyfin', 'emby', 'kodi'].includes(config?.scraper?.external_manager)" in xshow, \
            f"nfo-update-row x-show 應使用正向白名單 .includes() gate（fail-closed），實際: {xshow!r}"
        assert "!jellyfinImageVisible" in xshow, \
            f"nfo-update-row x-show 應含 !jellyfinImageVisible，實際: {xshow!r}"
        # forbidden：舊 jellyfin_emby gate 與 interim !='off'（fail-open）皆不得殘留
        assert "=== 'jellyfin_emby'" not in html, \
            "scanner.html 仍殘留舊 === 'jellyfin_emby' gate"
        assert "config?.scraper?.external_manager !== 'off' && !jellyfinImageVisible" not in html, \
            "scanner.html 觸發列仍用 interim !== 'off' gate（undefined 會 fail-open，須改正向白名單）"
        assert "config?.scraper?.jellyfin_mode && !jellyfinImageVisible" not in html, \
            "scanner.html 觸發列 x-show 仍使用舊的 jellyfin_mode 讀取點（應已 repoint 為 external_manager）"

    def test_check_jellyfin_method_gate_is_fail_closed(self):
        """72d-codexP2: checkJellyfinImages() 方法端 gate 用正向白名單，config 未載入時 fail-closed 不打 API"""
        js = self._js()
        assert "async checkJellyfinImages()" in js, "state-scan.js 找不到 checkJellyfinImages() 方法"
        # 正向白名單 early-return（fail-closed）；此字串為該 gate 獨有
        assert "!['jellyfin', 'emby', 'kodi'].includes(this.config?.scraper?.external_manager)" in js, \
            "checkJellyfinImages() 應以正向白名單 early-return（fail-closed），不可用 === 'off'（undefined fail-open）"
        # forbidden：舊 fail-open gate（undefined === 'off' 為 false → 不 return → 打 /jellyfin-check）
        assert "this.config?.scraper?.external_manager === 'off'" not in js, \
            "state-scan.js 仍殘留 external_manager === 'off' gate（undefined 會 fail-open）"

    def test_trigger_row_done_state_text_present(self):
        """T3(40c) Codex fix: 觸發列包含 done 狀態顯示文字"""
        html = self._html()
        assert "jellyfinCheckState === 'done'" in html, \
            "scanner.html 觸發列缺少 done 狀態文字顯示"
        assert "jellyfin_check_done_ok" in html, \
            "scanner.html 觸發列缺少 jellyfin_check_done_ok i18n key 引用"
