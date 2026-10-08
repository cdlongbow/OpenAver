"""前端靜態守衛 — 確保 template 包含必要的 Alpine 綁定"""
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


# ====================================================================
# D1 Guards: 錯誤訊息收斂 + console.log 清理
# ====================================================================


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
