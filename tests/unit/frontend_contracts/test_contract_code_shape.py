"""前端契約守衛（KEEP，跨檔 contract）— 由 test_frontend_lint.py 拆出（96e T1，純搬移零行為變更）。

module-level 路徑常數為源檔複製（CD-96e-2：源檔殘留 class 仍引用同名常數，故複製非剪走）。
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # /home/peace/OpenAver
GRID_MODE_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "grid-mode.js"
SETTINGS_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "settings.html"
SETTINGS_CONFIG_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "settings" / "state-config.js"
LOCALES_ROOT = Path(__file__).parent.parent.parent.parent / "locales"


class TestLightboxStateFirstGuard:
    # [lint-guard: pytest-justified] method-body 順序 — prevLightboxVideo/nextLightboxVideo/
    # openLightbox 抽方法體驗 lightboxIndex 更新位置 < playLightboxSwitch 位置（state-first）；
    # 另含 onMidpoint 負向斷言 + _lightboxGeneration 存在性
    """B19 守衛：Lightbox 導航必須 state-first（lightboxIndex 在 playLightboxSwitch 之前更新）"""

    SEARCH_GRID_MODE = PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'search' / 'state' / 'grid-mode.js'
    SHOWCASE_CORE = PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'showcase' / 'state-lightbox.js'

    @staticmethod
    def _read_file(path):
        return path.read_text(encoding='utf-8')

    @staticmethod
    def _read_showcase():
        """合併 state-base.js + state-lightbox.js 覆蓋 B19 guard 範圍（cleanup 在 base，lightbox nav 在 lightbox）"""
        return (
            (PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'showcase' / 'state-base.js').read_text(encoding='utf-8') + "\n" +
            (PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'showcase' / 'state-lightbox.js').read_text(encoding='utf-8')
        )

    @staticmethod
    def _extract_function(content, func_name):
        """粗略擷取函數內容（從函數名到下一個同級函數或檔案結尾）"""
        pattern = re.compile(r'^\s*(?:async\s+)?' + re.escape(func_name) + r'\s*\(', re.MULTILINE)
        match = pattern.search(content)
        if not match:
            return ''
        start = match.start()
        return content[start:start + 3000]

    def test_open_lightbox_switch_state_first(self):
        """B19: openLightbox 的 switch 路徑也必須 state-first"""
        for path, filename in [
            (self.SEARCH_GRID_MODE, 'search/state/grid-mode.js'),
            (self.SHOWCASE_CORE, 'showcase/core.js'),
        ]:
            content = self._read_file(path)
            body = self._extract_function(content, 'openLightbox')
            assert body, f"openLightbox 函數未找到 in {filename}"
            switch_section_start = body.find('lightboxIndex !== index')
            assert switch_section_start != -1, f"{filename} openLightbox 缺少 switch 路徑"
            switch_section = body[switch_section_start:]
            switch_pos = switch_section.find('playLightboxSwitch')
            # F1: _setLightboxIndex(index) 也是合法的 state-first 更新
            update_pos = switch_section.find('lightboxIndex = index')
            if update_pos == -1:
                update_pos = switch_section.find('_setLightboxIndex(index)')
            assert update_pos != -1 and switch_pos != -1, (
                f"{filename} openLightbox switch 路徑缺少 lightboxIndex 更新或 playLightboxSwitch 呼叫"
            )
            assert update_pos < switch_pos, (
                f"B19 違規：{filename} openLightbox switch 路徑的 lightboxIndex 更新必須在 playLightboxSwitch 之前"
            )

    def test_lightbox_nexttick_has_generation_guard(self):
        """B19: 所有 lightbox $nextTick 動畫 callback 必須有 _lightboxGeneration 失效檢查"""
        SEARCH_NAV = PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'search' / 'state' / 'navigation.js'
        for path, filename in [
            (self.SEARCH_GRID_MODE, 'search/state/grid-mode.js'),
            (self.SHOWCASE_CORE, 'showcase/core.js'),
        ]:
            content = self._read_file(path)
            for func in ['prevLightboxVideo', 'nextLightboxVideo', 'openLightbox']:
                body = self._extract_function(content, func)
                if 'playLightboxSwitch' not in body and 'playLightboxOpen' not in body:
                    continue
                assert '_lightboxGeneration' in body, (
                    f"B19 違規：{filename} {func} 的 $nextTick callback 缺少 _lightboxGeneration 失效檢查 — "
                    "close/ESC 後 stale callback 會重設 _lightboxAnimating = true 造成 input lock"
                )

    def test_lightbox_close_increments_generation(self):
        """B19: closeLightbox / ESC / searchFromMetadata / page cleanup 必須 increment _lightboxGeneration"""
        # Search closeLightbox
        content = self._read_file(self.SEARCH_GRID_MODE)
        body = self._extract_function(content, 'closeLightbox')
        assert body, "closeLightbox 函數未找到 in grid-mode.js"
        assert '_lightboxGeneration++' in body, (
            "B19 違規：search closeLightbox 缺少 _lightboxGeneration++ — "
            "pending $nextTick callback 不會被 invalidate"
        )

        # Showcase closeLightbox
        content = self._read_file(self.SHOWCASE_CORE)
        body = self._extract_function(content, 'closeLightbox')
        assert body, "closeLightbox 函數未找到 in showcase/core.js"
        assert '_lightboxGeneration++' in body, (
            "B19 違規：showcase closeLightbox 缺少 _lightboxGeneration++ — "
            "pending $nextTick callback 不會被 invalidate"
        )

        # Showcase searchFromMetadata
        body = self._extract_function(content, 'searchFromMetadata')
        assert body, "searchFromMetadata 函數未找到 in showcase/core.js"
        assert '_lightboxGeneration++' in body, (
            "B19 違規：showcase searchFromMetadata 缺少 _lightboxGeneration++ — "
            "pending $nextTick callback 不會被 invalidate"
        )

        # Page lifecycle cleanup — search (index.js 已由 main.js 取代，54e)
        SEARCH_MAIN = PROJECT_ROOT / 'web' / 'static' / 'js' / 'pages' / 'search' / 'main.js'
        search_main_content = SEARCH_MAIN.read_text(encoding='utf-8')
        assert '_lightboxGeneration++' in search_main_content, (
            "B19 違規：search main.js cleanup 缺少 _lightboxGeneration++ — "
            "離頁時 pending $nextTick lightbox callback 不會被 invalidate"
        )

        # Page lifecycle cleanup — showcase (init is async, extract manually)
        showcase_content = self._read_showcase()
        cleanup_start = showcase_content.find('cleanup: ()')
        assert cleanup_start != -1, "showcase/state-base.js 缺少 cleanup callback"
        cleanup_section = showcase_content[cleanup_start:cleanup_start + 500]
        assert '_lightboxGeneration++' in cleanup_section, (
            "B19 違規：showcase init() cleanup 缺少 _lightboxGeneration++ — "
            "離頁時 pending $nextTick lightbox callback 不會被 invalidate"
        )


class TestShowcaseReactiveScopeGuard:
    # [lint-guard: pytest-justified] brace-depth 解析 — _get_return_block 逐字元
    # brace-balance 抽取全部 return {...} block（naive forbidden-string 會誤判巢狀邊界）；
    # 另含 _find_statement_end brace/paren nesting 追蹤賦值語句範圍
    """F1: videos/filteredVideos 移出 Alpine reactive scope — 守衛測試"""

    CORE_JS = PROJECT_ROOT / "web/static/js/pages/showcase/state-base.js"
    SHOWCASE_HTML = PROJECT_ROOT / "web/templates/showcase.html"

    # 149a：state-lightbox.js 拆成 5 片後，燈箱家族的 return {...} 散在 5 個檔。
    # F1 守衛的斷言是「大陣列不得進 Alpine reactive scope」，掃描範圍少一個檔
    # 就等於那個檔可以自由宣告 videos:／filteredVideos: 而不會被擋（實測：注入
    # 拆前檔 2 failed，注入四個新分片全綠）。⇒ 清單必須涵蓋全部 8 個模組。
    F1_SCOPE_MODULES = (
        "state-base.js",
        "state-videos.js",
        "state-actress.js",
        "state-lightbox.js",
        "state-lightbox-mask.js",
        "state-lightbox-picker.js",
        "state-lightbox-samples.js",
        "state-lightbox-tags.js",
    )

    def _read_js(self):
        """合併讀取全部 8 個 showcase state ESM 模組覆蓋 F1 守衛範圍。"""
        base = PROJECT_ROOT / "web/static/js/pages/showcase"
        return "\n".join(
            (base / name).read_text(encoding='utf-8') for name in self.F1_SCOPE_MODULES
        )

    def _get_return_block(self):
        """Extract and concatenate all 'return { ... }' blocks from the merged showcase state modules."""
        content = self._read_js()
        blocks = []
        pos = 0
        while True:
            start = content.find('return {', pos)
            if start == -1:
                break
            brace_depth = 0
            end = start
            for i in range(start, len(content)):
                if content[i] == '{':
                    brace_depth += 1
                elif content[i] == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        end = i + 1
                        break
            blocks.append(content[start:end])
            pos = end
        assert blocks, "Cannot find any 'return {' block in ESM state modules"
        return '\n'.join(blocks)

    def test_guard1_no_videos_in_return_object(self):
        """Guard 1: showcaseState() return object 不包含 videos: 或 filteredVideos: 屬性"""
        block = self._get_return_block()
        lines = block.split('\n')
        for i, line in enumerate(lines, 1):
            assert not re.search(r'^\s*videos\s*:', line), (
                f"F1 違規：return object 第 {i} 行仍包含 'videos:' 屬性 — "
                "應移至閉包變數 _videos"
            )
            assert not re.search(r'^\s*filteredVideos\s*:', line), (
                f"F1 違規：return object 第 {i} 行仍包含 'filteredVideos:' 屬性 — "
                "應移至閉包變數 _filteredVideos"
            )

    def test_guard2_has_count_scalars(self):
        """Guard 2: return object 包含 videoCount: 和 filteredCount:"""
        block = self._get_return_block()
        assert re.search(r'^\s*videoCount\s*:', block, re.MULTILINE), (
            "F1 違規：return object 缺少 'videoCount:' — "
            "需要 scalar reactive 給 template 綁定"
        )
        assert re.search(r'^\s*filteredCount\s*:', block, re.MULTILINE), (
            "F1 違規：return object 缺少 'filteredCount:' — "
            "需要 scalar reactive 給 template 綁定"
        )

    def test_guard3_no_getter_currentLightboxVideo(self):
        """Guard 3: currentLightboxVideo 不是 getter，應為 reactive property"""
        block = self._get_return_block()
        assert 'get currentLightboxVideo()' not in block, (
            "F1 違規：return object 仍有 'get currentLightboxVideo()' getter — "
            "應改為 'currentLightboxVideo: null' reactive property"
        )
        assert re.search(r'^\s*currentLightboxVideo\s*:', block, re.MULTILINE), (
            "F1 違規：return object 缺少 'currentLightboxVideo:' property — "
            "應為手動更新的 reactive property"
        )

    def test_guard4_no_videos_length_in_template(self):
        """Guard 4: showcase.html 不包含 videos.length 或 filteredVideos.length"""
        content = self.SHOWCASE_HTML.read_text(encoding='utf-8')
        assert 'videos.length' not in content, (
            "F1 違規：showcase.html 仍引用 'videos.length' — "
            "應改用 videoCount"
        )
        assert 'filteredVideos.length' not in content, (
            "F1 違規：showcase.html 仍引用 'filteredVideos.length' — "
            "應改用 filteredCount"
        )

    def test_guard5_no_bare_videos_in_template(self):
        """Guard 5: showcase.html 不引用 bare videos 或 filteredVideos"""
        content = self.SHOWCASE_HTML.read_text(encoding='utf-8')
        # Match 'videos' or 'filteredVideos' but exclude allowed compounds
        for i, line in enumerate(content.split('\n'), 1):
            # Remove allowed patterns first, then check for bare references
            cleaned = line
            for allowed in ['paginatedVideos', 'currentLightboxVideo', 'videoCount', 'filteredCount',
                            'fetchVideos', 'prevLightboxVideo', 'nextLightboxVideo',
                            'openLightbox', 'closeLightbox', 'playVideo',
                            'showcase.unit.videos']:
                cleaned = cleaned.replace(allowed, '')
            # Now check for bare 'videos' (word boundary)
            if re.search(r'\bvideos\b', cleaned):
                pytest.fail(
                    f"F1 違規：showcase.html L{i} 引用 bare 'videos' — "
                    f"應改用 videoCount 或 paginatedVideos: {line.strip()}"
                )

    def _find_statement_end(self, lines, start_idx):
        """Find the end line of a statement starting at start_idx.

        For multi-line statements (e.g., _filteredVideos = _videos.filter(video => { ... })),
        track brace/paren nesting to find the actual end of the statement.
        Returns the index of the last line of the statement.
        """
        depth = 0
        for j in range(start_idx, min(start_idx + 50, len(lines))):
            for ch in lines[j]:
                if ch in '({':
                    depth += 1
                elif ch in ')}':
                    depth -= 1
            # Statement ends when we return to depth 0 (or never went deeper)
            if depth <= 0 and j > start_idx:
                return j
            if depth == 0 and ';' in lines[j]:
                return j
        return start_idx


class TestExternalManagerSwitchModeGuard:
    # [lint-guard: pytest-justified] method-body 語意 — confirmSwitchMode 抽方法體驗
    # savedState.externalManager 單-key 同步 + 負守衛（不得整份 re-snapshot）；bs4 掃
    # dialog :class 屬性；HTML 骨架 + i18n 半邊隨 class 留置（不拆）
    """90c-T5: settings.html + state-config.js 全域模式切換破壞性 confirm 靜態守衛。

    四顆 external_manager segmented button 改攔截式 requestExternalManagerChange；
    有離線來源時跳破壞性 confirm modal → 確認呼叫 T4 endpoint → 三處同步。
    每個 assertion mutation-sensitive；element-bound（anchor external-manager row）。
    """

    def _html(self):
        return SETTINGS_HTML.read_text(encoding="utf-8")

    def _js(self):
        return SETTINGS_CONFIG_JS.read_text(encoding="utf-8")

    def _seg_block(self):
        """anchor 到 settings-form-row--external-manager 再抓其 segmented 容器
        （settings.html 有 ≥3 個 settings-sources-segmented、其中 header 膠囊也帶
        role=group，故不可全文 substring — element-bound）。"""
        import re
        content = self._html()
        anchor = content.find("settings-form-row--external-manager")
        assert anchor != -1, "settings.html 缺少 settings-form-row--external-manager 區塊"
        m = re.search(
            r'class="settings-sources-segmented" role="group".*?</div>',
            content[anchor:], re.DOTALL,
        )
        assert m, "settings.html 缺少 .settings-sources-segmented[role=group]（外部管理器）"
        return m.group(0)

    # ── HTML: segmented buttons 改攔截式 ────────────────────────────────────────

    def test_segmented_buttons_call_request_method(self):
        """四顆 button @click 呼叫 requestExternalManagerChange('x')，不再直寫 form。"""
        seg = self._seg_block()
        for val in ("off", "jellyfin", "emby", "kodi"):
            assert f"@click=\"requestExternalManagerChange('{val}')\"" in seg, \
                f"segmented 缺少 @click=\"requestExternalManagerChange('{val}')\""
            assert f"@click=\"form.externalManager = '{val}'\"" not in seg, \
                f"segmented 不應殘留舊 @click 直寫 form.externalManager='{val}'"

    # ── HTML: confirm modal ─────────────────────────────────────────────────────

    def test_switch_mode_confirm_modal_exists(self):
        """存在 switch-mode confirm <dialog>：btn-error（破壞性語氣）+ modal-open 綁定 +
        Esc 鏈 + confirmSwitchMode/cancelSwitchMode 呼叫 + {mode}/{count} 插值 body +
        CD-90b-11a 多分頁提醒句 + 不含「風味」。"""
        from bs4 import BeautifulSoup
        html = self._html()
        soup = BeautifulSoup(html, "html.parser")
        dialog = None
        for d in soup.find_all("dialog"):
            if "switchModeConfirmOpen" in (d.get(":class") or ""):
                dialog = d
                break
        assert dialog is not None, \
            "settings.html 缺少 switch-mode confirm <dialog>（:class 綁 switchModeConfirmOpen）"
        block = str(dialog)
        # modal-open 綁定
        assert "modal-open" in (dialog.get(":class") or ""), \
            "switch-mode dialog :class 缺 'modal-open': switchModeConfirmOpen"
        # 破壞性語氣：btn-error 確認鈕
        assert "btn-error" in block, \
            "switch-mode modal 缺 btn-error 確認鈕（破壞性語氣，CD-90b-13）"
        assert "btn-primary" not in block, \
            "switch-mode modal 不應用 btn-primary（破壞性須 btn-error）"
        # Esc 鏈（modal 級）— 讀 attr 值（避免 BS4 re-serialize 把 && → &amp;&amp;）
        esc = dialog.get("@keydown.escape.window", "")
        assert "switchModeConfirmOpen" in esc and "cancelSwitchMode()" in esc, \
            "switch-mode modal 缺 @keydown.escape.window Esc 鏈"
        # confirm / cancel 呼叫
        assert "confirmSwitchMode()" in block, "switch-mode modal 缺 confirmSwitchMode() 呼叫"
        assert "cancelSwitchMode()" in block, "switch-mode modal 缺 cancelSwitchMode() 呼叫"
        # {mode}/{count} 插值 body（走 i18n key）
        assert "settings.switch_mode_confirm.body" in block, \
            "switch-mode modal 缺 settings.switch_mode_confirm.body i18n 引用"
        assert "pendingOfflineCount" in block, \
            "switch-mode modal body 缺 count: pendingOfflineCount 插值"
        # 不出現「風味」
        assert "風味" not in block, "switch-mode modal 不應出現「風味」（白話模式名）"

    # ── JS: 三方法 + stub ───────────────────────────────────────────────────────

    def test_request_method_realtime_fetch_and_guard(self):
        """requestExternalManagerChange 即時 fetch /api/config（非快取）+ 同值 guard return。"""
        import re
        js = self._js()
        m = re.search(
            r"requestExternalManagerChange\s*\([^)]*\)\s*\{.*?\n        \},",
            js, re.DOTALL,
        )
        assert m, "state-config.js 找不到 requestExternalManagerChange 方法體"
        body = m.group(0)
        assert "this.form.externalManager === val" in body, \
            "requestExternalManagerChange 缺同值 guard return"
        assert "fetch('/api/config')" in body, \
            "requestExternalManagerChange 缺即時 fetch('/api/config')（CD-90b-11 ②）"
        assert "readonly === true" in body, \
            "requestExternalManagerChange 缺 readonly 離線來源枚舉"

    def test_confirm_syncs_three_places_single_key_savedstate(self):
        """confirmSwitchMode 同步三處：form.externalManager + savedState.externalManager（單 key）
        + scannerDirectories 回填；不得整份 re-snapshot savedState。"""
        import re
        js = self._js()
        m = re.search(
            r"confirmSwitchMode\s*\([^)]*\)\s*\{.*?\n        \},",
            js, re.DOTALL,
        )
        assert m, "state-config.js 找不到 confirmSwitchMode 方法體"
        body = m.group(0)
        assert "switch-external-manager" in body, \
            "confirmSwitchMode 缺 POST /api/config/switch-external-manager"
        assert "this.form.externalManager = val" in body, \
            "confirmSwitchMode 缺 form.externalManager 同步"
        assert "this.savedState.externalManager = val" in body, \
            "confirmSwitchMode 缺 savedState.externalManager 單 key 同步"
        assert "this.scannerDirectories" in body, \
            "confirmSwitchMode 缺 scannerDirectories 回填"
        # 負守衛：不可整份 re-snapshot（會清掉其他未存 form dirty 態）
        assert "savedState = JSON.parse" not in body, \
            "confirmSwitchMode 不應整份 re-snapshot savedState（須單 key 同步）"

    def test_confirm_generate_in_progress_specific_toast(self):
        """Finding 2：confirmSwitchMode 失敗時依 reason 分流——generate_in_progress
        顯示專屬提示 key（非只泛用 failed），指路使用者等產生完成。"""
        import re
        js = self._js()
        m = re.search(r"confirmSwitchMode\s*\([^)]*\)\s*\{.*?\n        \},", js, re.DOTALL)
        assert m, "state-config.js 找不到 confirmSwitchMode 方法體"
        body = m.group(0)
        assert "generate_in_progress" in body, \
            "confirmSwitchMode 失敗分流缺 generate_in_progress reason 判斷"
        assert "settings.switch_mode_confirm.generate_in_progress" in body, \
            "confirmSwitchMode 缺 generate_in_progress 專屬 toast i18n key"

    # ── i18n: zh_TW only ────────────────────────────────────────────────────────

    def test_zh_tw_switch_mode_confirm_keys(self):
        """zh_TW.json 含 settings.switch_mode_confirm.{title,body,cancel,confirm}，body 非空
        且含 {mode}/{count} 插值（zh_TW only，不做四語 parity）。"""
        import json
        data = json.loads((LOCALES_ROOT / "zh_TW.json").read_text(encoding="utf-8"))
        node = data.get("settings", {}).get("switch_mode_confirm")
        assert node is not None, "zh_TW.json 缺 settings.switch_mode_confirm 節點"
        for key in ("title", "body", "cancel", "confirm", "generate_in_progress"):
            assert node.get(key), f"zh_TW.json settings.switch_mode_confirm.{key} 缺或空"
        assert "{mode}" in node["body"] and "{count}" in node["body"], \
            "settings.switch_mode_confirm.body 缺 {mode}/{count} 插值"
        assert "風味" not in node["body"], "switch_mode_confirm.body 不應出現「風味」"


# [lint-guard: pytest-justified] scanner.py / gallery_media.py Python-source 安全字串弱代理
# （option-b，CD-96e-5〔c〕；TASK-150a 搬遷後拆成 test_scanner_py_safety_strings /
# test_gallery_media_py_safety_strings 兩支 method，各守一個檔）——get_video/video_player/
# normpath/get_proxy_extensions/is_path_under_dir 是否真的組成安全的路徑校驗邏輯，屬 Python
# 源碼語意，字串存在性只是弱代理，non-AST 機械掃描無法驗證邏輯正確，留 pytest。
class TestVideoApiSafetyStrings:
    """96e-T5 relocate（from TestVideoPlaybackGuard.test_video_api_files_contain
    scanner.py 半邊）：video proxy 安全守衛字串。

    TASK-150a-T1：get_video() 搬到 gallery_media.py 後，原本「讀一個檔案、跑一個
    for-loop」的形狀不再成立——`def get_video(`／`os.path.normpath`／
    `get_proxy_extensions` 隨 get_video 搬到 gallery_media.py。
    TASK-150a-T2：`def video_player(` 也隨 `_render_player_html` 一起搬到
    gallery_media.py，scanner.py 這半邊只剩 `is_path_under_dir`；`is_path_under_dir`
    兩邊都留（scanner.py 的 generate_avlist pipeline 仍在用，gallery_media.py 的
    get_image/get_video/video_player 也在用），維持原掃描粒度與正負極性，不刪不
    放寬（plan-150a.md CD-150a-1 mutation 點表格 #1）。
    """

    def test_scanner_py_safety_strings(self):
        """TASK-150a-T2：video_player() 搬到 gallery_media.py 後，scanner.py 仍保留的安全字串。"""
        content = (PROJECT_ROOT / "web" / "routers" / "scanner.py").read_text(encoding="utf-8")
        for expected in ['is_path_under_dir']:
            assert expected in content, f"scanner.py missing: {expected!r}"

    def test_gallery_media_py_safety_strings(self):
        """get_video() 隨 TASK-150a-T1、video_player() 隨 TASK-150a-T2 搬到 gallery_media.py 後的安全字串。"""
        content = (PROJECT_ROOT / "web" / "routers" / "gallery_media.py").read_text(encoding="utf-8")
        for expected in [
            'def get_video(', 'os.path.normpath',
            'get_proxy_extensions', 'is_path_under_dir', 'def video_player(',
        ]:
            assert expected in content, f"gallery_media.py missing: {expected!r}"


class TestWishlistLightboxDispatchOrderGuard:
    # [lint-guard: pytest-justified] method-body ordering ——
    # handleKeydown()/handleWheel() 內三個 overlay 分支（sampleGalleryOpen →
    # wishlistLightboxOpen → lightboxOpen）的出現順序是方法內的執行優先序契約，
    # lint 的字串存在檢查表達不了「A 分支在 B 分支之前」，需要 AST/字串位置比較。
    """TASK-140-T11b：書籤燈箱分派鏈必須插在 sampleGalleryOpen 之後、lightboxOpen 之前"""

    NAVIGATION_JS = PROJECT_ROOT / "web" / "static" / "js" / "pages" / "search" / "state" / "navigation.js"

    # 🔴 CodeRabbit PR#175 P3：原本是 `content[start:start + 4000]` 固定字元窗口。本 branch
    # 在 `handleWheel` 插入書籤燈箱分支後，該函式從 3874 字漲到 4807 字——**首次超出窗口**，
    # 最後一個 `if (this.lightboxOpen) {` 落在第 3632 字，離切斷點只剩 368 字。再多寫約 370 字
    # 那行就被切在窗口外，測試會報「缺少三個分支之一」——**而三個分支明明都在**，下一個改
    # navigation.js 的人得先不信任這句訊息，才找得到真因。
    #
    # 單純把 4000 調大**方向更錯**：`handleKeydown` 在 `handleWheel` **之前**，窗口一放大就
    # 吃進後面那支，而 handleWheel 裡有同樣三個字面、同樣的順序 ⇒ `test_handle_keydown_order`
    # 會綠，但綠的是 handleWheel 的順序。那是把「假紅（吵人）」換成「假綠（放行真 bug）」。
    #
    # ⇒ 魔術數字整個拿掉，改為大括號配對抓完整主體，截斷與溢出兩個失效方向同時消滅。
    # 殘留風險：函式內若出現單邊大括號（註解／字串裡），計數會失衡——但那會炸出明確的
    # 「大括號不平衡」，不是騙人的「缺少分支」。
    @staticmethod
    def _extract_function(content, func_name):
        pattern = re.compile(r'^\s*(?:async\s+)?' + re.escape(func_name) + r'\s*\(', re.MULTILINE)
        match = pattern.search(content)
        assert match, f"{func_name} 函數未找到"
        start = match.start()
        depth = 0
        for j in range(content.index('{', start), len(content)):
            if content[j] == '{':
                depth += 1
            elif content[j] == '}':
                depth -= 1
                if depth == 0:
                    return content[start:j + 1]
        raise AssertionError(f"{func_name} 大括號不平衡，無法擷取完整函式主體")

    def _js(self):
        return self.NAVIGATION_JS.read_text(encoding="utf-8")

    def test_handle_keydown_order(self):
        """比對分支開頭字面，理由同 test_handle_wheel_order 的 docstring。"""
        body = self._extract_function(self._js(), "handleKeydown")
        sg = body.find("if (this.sampleGalleryOpen) {")
        wl = body.find("if (this.wishlistLightboxOpen) {")
        lb = body.find("if (this.lightboxOpen) {")
        assert sg != -1 and wl != -1 and lb != -1, \
            "handleKeydown 缺少 sampleGalleryOpen/wishlistLightboxOpen/lightboxOpen 三個分支之一"
        assert sg < wl < lb, \
            "handleKeydown: wishlistLightboxOpen 分支必須插在 sampleGalleryOpen 之後、lightboxOpen 之前"

    def test_handle_wheel_order(self):
        """⚠️ 比對的是 `if (this.xxxOpen) {` 這個**分支開頭**字面，不是裸的識別字。

        Opus 2026-09-02 抽驗發現：用裸識別字（`body.find("this.sampleGalleryOpen")`）在
        handleWheel 裡是**空殼**——三個 find 全部落在同一行
        `const isOverlay = this.sampleGalleryOpen || this.wishlistLightboxOpen || this.lightboxOpen;`
        上（實測 offset 741 / 767 / 796），`sg < wl < lb` 恆成立，與真正的分支位置無關。
        改比對分支開頭字面之後，把書籤分支整段搬到 lightbox 之後才會轉紅。
        """
        body = self._extract_function(self._js(), "handleWheel")
        sg = body.find("if (this.sampleGalleryOpen) {")
        wl = body.find("if (this.wishlistLightboxOpen) {")
        lb = body.find("if (this.lightboxOpen) {")
        assert sg != -1 and wl != -1 and lb != -1, \
            "handleWheel 缺少 sampleGalleryOpen/wishlistLightboxOpen/lightboxOpen 三個分支之一"
        assert sg < wl < lb, \
            "handleWheel: wishlistLightboxOpen 分支必須插在 sampleGalleryOpen 之後、lightboxOpen 之前"
