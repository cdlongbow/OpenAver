"""前端契約守衛（KEEP，跨檔 contract）— 由 test_frontend_lint.py 拆出（96c T5，純搬移零行為變更）。

module-level 路徑常數為源檔複製（CD-96c-7：源檔殘留 class 仍引用同名常數，故複製非剪走）。
"""
import re
from pathlib import Path

from tests.unit.frontend_contracts._showcase_css import read_showcase_css_full

SHOWCASE_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "showcase.html"
SHOWCASE_VIDEOS_JS   = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-videos.js"
SHOWCASE_ACTRESS_JS  = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-actress.js"
SHOWCASE_LIGHTBOX_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
SHOWCASE_LIGHTBOX_PICKER_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox-picker.js"
SHOWCASE_ANIMATIONS_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "animations.js"
)
GHOST_FLY_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "shared" / "ghost-fly.js"
STATE_LIGHTBOX_JS = Path(__file__).parent.parent.parent.parent / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
_T2_SHOWCASE_HTML = Path(__file__).parent.parent.parent.parent / "web" / "templates" / "showcase.html"
_T2_SIMILAR_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-similar.js"
)
_T2_LIGHTBOX_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-lightbox.js"
)
_T2_BASE_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "pages" / "showcase" / "state-base.js"
)
_T2_BURST_PICKER_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "shared" / "burst-picker.js"
)
_T3_GHOST_FLY_JS = (
    Path(__file__).parent.parent.parent.parent
    / "web" / "static" / "js" / "shared" / "ghost-fly.js"
)


class TestGhostFlyGuards:
    """T8: Ghost Fly architecture guards (method folded)"""

    # ── 71b-T3: both-restore guard（hide/restore 目標皆為 .lightbox-cover 容器）──
    # element-bound：regex 抽 OPEN(playGridToLightbox) / CLOSE(playLightboxToGrid)
    # 各自 function body，斷言兩路 hide + restore 都指向 coverEl 容器（非僅單一 img）。
    # 非檔案層級的 '.lightbox-cover' 字串存在性檢查（comment 留字串無法騙過）。

    GHOST_FLY_JS = Path("web/static/js/shared/ghost-fly.js")

    def _extract_method_body(self, js, method_name):
        """抓 `methodName: function (...) {` 物件方法的 body（大括號平衡匹配）。"""
        pattern = re.compile(
            re.escape(method_name) + r'\s*:\s*function\s*\([^)]*\)\s*\{',
            re.DOTALL,
        )
        m = pattern.search(js)
        assert m is not None, f"ghost-fly.js 找不到 {method_name} 方法"
        start = m.end()  # 位於 { 之後
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

    def test_open_hide_and_restore_target_is_cover_container(self):
        """OPEN(playGridToLightbox) body：coverEl 取自 .lightbox-cover 容器，
        hide（data-ghost-hidden + opacity:0）與 cleanupGhost restore 皆指向 coverEl，
        而非僅單一 lbImg。"""
        js = self.GHOST_FLY_JS.read_text(encoding="utf-8")
        body = self._extract_method_body(js, "playGridToLightbox")
        # coverEl 由 .lightbox-cover 容器取得（closest / querySelector 任一）
        assert re.search(r'var\s+coverEl\s*=', body), \
            "playGridToLightbox body 缺少 coverEl 宣告（應隱 .lightbox-cover 容器而非單一 img）"
        assert "closest('.lightbox-cover')" in body or "querySelector('.lightbox-cover')" in body, \
            "playGridToLightbox coverEl 必須取自 .lightbox-cover 容器"
        # hide 目標是 coverEl（attribute + opacity:0）
        assert re.search(r"coverEl\.setAttribute\(\s*'data-ghost-hidden'", body), \
            "playGridToLightbox hide 必須對 coverEl 掛 data-ghost-hidden（容器，非僅 lbImg）"
        assert re.search(r"gsap\.set\(\s*coverEl\s*,\s*\{\s*opacity:\s*0", body), \
            "playGridToLightbox hide 必須對 coverEl 設 opacity:0（容器，非僅 lbImg）"
        # restore 目標是 coverEl（cleanupGhost 帶 coverEl）
        assert re.search(r"cleanupGhost\(\s*ghost\s*,\s*coverEl", body), \
            "playGridToLightbox cleanupGhost restore 必須帶 coverEl（容器），非僅 lbImg"

    def test_close_hide_and_restore_target_is_cover_container(self):
        """CLOSE(playLightboxToGrid) body：coverEl 取自 .lightbox-cover 容器，
        hide 補掛 data-ghost-hidden + opacity:0，abort 還原 coverEl，
        normal-complete 的 cleanupGhost restore 參數含 coverEl（與 OPEN 對稱）。"""
        js = self.GHOST_FLY_JS.read_text(encoding="utf-8")
        body = self._extract_method_body(js, "playLightboxToGrid")
        # coverEl 由 .lightbox-cover 容器取得
        assert re.search(r'var\s+coverEl\s*=', body), \
            "playLightboxToGrid body 缺少 coverEl 宣告（應隱 .lightbox-cover 容器而非單一 fromImg）"
        assert "closest('.lightbox-cover')" in body or "querySelector('.lightbox-cover')" in body, \
            "playLightboxToGrid coverEl 必須取自 .lightbox-cover 容器"
        # hide 目標是 coverEl（補上 attribute，舊版漏掛）+ opacity:0
        assert re.search(r"coverEl\.setAttribute\(\s*'data-ghost-hidden'", body), \
            "playLightboxToGrid hide 必須對 coverEl 掛 data-ghost-hidden（舊版漏掛 → stale-cleanup 兜不到）"
        assert re.search(r"gsap\.set\(\s*coverEl\s*,\s*\{\s*opacity:\s*0", body), \
            "playLightboxToGrid hide 必須對 coverEl 設 opacity:0（容器，非僅 fromImg）"
        # abort 還原 coverEl
        assert re.search(r"gsap\.set\(\s*coverEl\s*,\s*\{\s*opacity:\s*1", body), \
            "playLightboxToGrid abort 必須還原 coverEl opacity:1（容器，非僅 fromImg）"
        # normal-complete restore 含 coverEl（對稱還原來源容器，修舊不對稱）
        assert re.search(r"cleanupGhost\(\s*ghost\s*,\s*targetImg\s*,\s*coverEl", body), \
            "playLightboxToGrid cleanupGhost restore 參數必須含 coverEl（對稱還原來源容器，非僅 targetImg）"


class TestModeToggleFadeOutGuard:
    """T1: 模式切換動畫補 fade-out（playModeCrossfade 4-arg + toggleActressMode callback 延遲翻轉）"""

    def _core_js(self):
        # toggleActressMode / searchActressFilms → state-actress.js
        # switchMode → state-videos.js
        return (
            SHOWCASE_ACTRESS_JS.read_text(encoding="utf-8") + "\n" +
            SHOWCASE_VIDEOS_JS.read_text(encoding="utf-8")
        )

    def _anim_js(self):
        return SHOWCASE_ANIMATIONS_JS.read_text(encoding="utf-8")

    def _extract_method_body(self, js, method_name):
        """抓取 Alpine state method（methodName(...) { ... }）函式主體，大括號平衡（容忍 async 前綴）。"""
        pattern = re.compile(
            r'(?:^|\n)\s*(?:async\s+)?' + re.escape(method_name) + r'\s*\([^)]*\)\s*\{',
            re.DOTALL,
        )
        m = pattern.search(js)
        assert m is not None, f"找不到 {method_name} 方法"
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

    def _extract_property_function_body(self, js, prop_name):
        """抓取 propName: function (...) { ... } 形式的函式主體，大括號平衡。"""
        pattern = re.compile(
            r'\b' + re.escape(prop_name) + r'\s*:\s*function\s*\([^)]*\)\s*\{',
            re.DOTALL,
        )
        m = pattern.search(js)
        assert m is not None, f"找不到 {prop_name} property function"
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

    def test_play_mode_crossfade_has_callbacks_param(self):
        """animations.js playModeCrossfade 簽名包含 4 個參數 (oldMode, newMode, params, callbacks)"""
        js = self._anim_js()
        assert re.search(
            r'playModeCrossfade\s*:\s*function\s*\(\s*oldMode\s*,\s*newMode\s*,\s*params\s*,\s*callbacks\s*\)',
            js,
        ), "showcase/animations.js playModeCrossfade 缺少 callbacks 第 4 參數"

    def test_toggle_actress_mode_animgen_guard(self):
        """toggleActressMode 函數體內 _animGeneration 出現 ≥ 2 次（外層 gen + 內層 gen2 race guard）"""
        js = self._core_js()
        body = self._extract_method_body(js, 'toggleActressMode')
        count = len(re.findall(r'_animGeneration', body))
        assert count >= 2, \
            f"toggleActressMode 函數體 _animGeneration 出現次數應 ≥ 2 (外 gen + 內 gen2)，實際 {count}"

    def test_toggle_actress_mode_handles_animations_unavailable(self):
        """Codex P1: animations.js 不可用時 toggleActressMode 必須有 fallback path（不能讓 callback 永不觸發）"""
        js = self._core_js()
        body = self._extract_method_body(js, 'toggleActressMode')
        # callback body 應抽成 named function（給 onOldFadeComplete 用、也給 fallback path 用）
        assert re.search(
            r'(?:function\s+\w*FadeIn\w*|var\s+\w*FadeIn\w*\s*=\s*function|\w*FadeIn\w*\s*=\s*function)',
            body,
        ), "toggleActressMode 應將 callback body 抽成 named function（如 flipAndFadeIn）以便 fallback 重用"
        # 必須顯式檢查 playModeCrossfade 是否存在（不能單靠 optional chaining 短路）
        assert re.search(
            r'(?:typeof\s+\w+\s*===\s*[\'"]function[\'"]|window\.ShowcaseAnimations\s*&&\s*window\.ShowcaseAnimations\.playModeCrossfade)',
            body,
        ), "toggleActressMode 應顯式檢查 playModeCrossfade 是否可用（不能單靠 optional chaining）"
        # 抽出來的 named function 應在函數體內被引用 ≥ 2 次（一次給 onOldFadeComplete、一次 fallback 直接呼叫）
        # 找出第一個 *FadeIn* 識別字
        m = re.search(r'\b(\w*[Ff]adeIn\w*)\b', body)
        assert m is not None, "toggleActressMode 找不到 FadeIn 命名函數"
        fname = m.group(1)
        count = len(re.findall(r'\b' + re.escape(fname) + r'\b', body))
        assert count >= 3, (
            f"toggleActressMode 內 {fname} 應出現 ≥ 3 次"
            f"（宣告 1 + onOldFadeComplete 引用 1 + fallback 同步呼叫 1），實際 {count}"
        )

    def test_toggle_actress_mode_reduced_motion_guard_on_fade_in(self):
        """Codex P2: toggleActressMode 內 newEl fade-in 必須有 reduced-motion 防護。

        49a-T4 起：原本的 inline `gsap.fromTo` 已重構為呼叫
        `window.ShowcaseAnimations.playContainerFadeIn`，該 helper 內部的
        `shouldSkip()` 已涵蓋 reduced-motion。本 test 接受兩種寫法擇一：
        (a) inline guard（舊架構）— 函數體內含 `prefersReducedMotion` 檢查
        (b) helper 委派（新架構）— 函數體內呼叫 `playContainerFadeIn`
        """
        js = self._core_js()
        body = self._extract_method_body(js, 'toggleActressMode')
        has_inline_guard = 'prefersReducedMotion' in body
        has_helper_delegation = 'playContainerFadeIn' in body
        assert has_inline_guard or has_helper_delegation, (
            "toggleActressMode newEl fade-in 應走 inline prefersReducedMotion guard，"
            "或委派 ShowcaseAnimations.playContainerFadeIn helper（後者 shouldSkip 已涵蓋）"
        )


class TestPickerIntegrationGuard:
    """49b-T4cd: 守衛 Actress Photo Picker 在 Showcase Lightbox 的 UI + Alpine + SSE 整合（method folded）

    149a-T3 拆檔後 picker 狀態/方法已搬到 state-lightbox-picker.js，本 class 的 _core_js()
    跟著 repoint（149a-T5 修：T3 引入的回歸，見 T5-AUDIT.md §8）。
    """

    def _html(self):
        return SHOWCASE_HTML.read_text(encoding="utf-8")

    def _core_js(self):
        return SHOWCASE_LIGHTBOX_PICKER_JS.read_text(encoding="utf-8")

    def _css(self):
        return read_showcase_css_full(
            Path(__file__).parent.parent.parent.parent / "web" / "static",
        )

    def test_picker_js_contains(self):
        """core.js 含 picker state、methods、params、SSE handler 等必要字串"""
        js = self._core_js()
        for expected in [
            # state
            "_pickerOpen: false",
            "_pickerRunId: 0",
            "_candidates: []",
            "_pickerSelected: false",
            # methods
            "openActressPicker(",
            "_startPickerSSE(",
            "_closePicker(",
            "_resetPicker(",
            "_fadeMetadataPanel(",
            "_cancelPicker",
            # params
            "_PICKER_PARAMS",
            "arcOvershoot: 1.3",
            # burst picker animations
            "playPickerFlipReplace",
            "playPickerExitAll",
            "typeof window.BurstPicker",
            "playPickerReverseAll",
            # SSE defer-burst
            "_burstAllPickerCandidates",
            # i18n
            "showcase.actress.picker.replaced",
            "showcase.actress.picker.error",
            "showToast(",
            # reduced motion
            "prefers-reduced-motion",
            "matchMedia",
            # lightbox teardown
            "_pickerOpen",
            "_closePicker",
            # stale name capture
            "capturedName",
            "currentLightboxActress",
        ]:
            assert expected in js, f"core.js missing: {expected!r}"
        # arcDuration
        assert ("arcDuration:  0.75" in js or "arcDuration: 0.75" in js), \
            "core.js missing: 'arcDuration: 0.75' in _PICKER_PARAMS"
        # _burstAllPickerCandidates ≥ 4 occurrences
        assert js.count("_burstAllPickerCandidates") >= 4, \
            "_burstAllPickerCandidates must appear ≥4 times (def + done/timeout/error)"

    # ── 4. closeMobilePanel is async ────────────────────────────────────────

    # ── 5. PRM fallback branches exist ──────────────────────────────────────

    # ── 5b. closeMobilePanel kills in-flight enter timeline (P1-T3fix) ───────

    # ── 6. Desktop constellation anchor not in mobile enter ─────────────────
