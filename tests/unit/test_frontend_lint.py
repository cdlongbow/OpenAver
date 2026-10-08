"""前端靜態守衛 — 確保 template 包含必要的 Alpine 綁定"""
import re
from pathlib import Path


SHOWCASE_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "showcase.html"


SEARCH_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "search.html"


SCANNER_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "scanner.html"


# theme-color 兩個白名單 hex，須與 CSS --color-base-100 token 換算一致
# （dim=[data-theme=dim] base-100、light=[data-theme=light] base-100）


NAVIGATION_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "navigation.js"


# TestShowcaseActressCRUD（Phase 44a-T5，9 條）已於 117-T6 等價遷入
# scripts/static_guard_lint.mjs [117-T6] R1–R9；#10/#11 由 [117-T4] R3/R4 承接。
# 對帳表見 feature/117-actress-add-panel/TASK-117-T6.md。


# ---------------------------------------------------------------------------
# T6: Scanner Alias UI v2 — 舊 token 移除 + 新 token 存在守衛
# ---------------------------------------------------------------------------
SCANNER_HTML = Path(__file__).parent.parent.parent / "web" / "templates" / "scanner.html"


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

# 專案根目錄（T55e: 從根目錄 tests/test_frontend_lint.py 搬移）


# ====================================================================
# D1 Guards: 錯誤訊息收斂 + console.log 清理
# ====================================================================


class TestCoverLoadingUx67Guard:
    """67 Cover Loading UX + Showcase Console 清零 守衛（HTML/CSS contract；JS 字串守衛走 eslint，CD-67-8）。

    全部依 G5：先 regex 抽出目標 tag/區塊再斷言其內容，不整檔裸 grep（showcase.html 別處仍有
    合法 <template x-for> 與多個 <img>）。每條皆可 RED→GREEN（破壞 contract 跑 RED、還原 GREEN）。
    """

    def _html(self):
        return SHOWCASE_HTML.read_text(encoding="utf-8")


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


# ── TASK-70-T6: CF flow 前端靜態守衛 ──


# ── CD-86-7 frontend guard: search 入口 JL pill gate 改用 isJlUnavailable ──


# ── 86-T4 frontend guard: 版本切換器 + i18n + entry-point gate ──


# ──────────────────────────────────────────────────────────────
# CD-70c-3: frontend CF poll unavailable contract guard
# ──────────────────────────────────────────────────────────────

STATE_RESCRAPE_JS = (
    Path(__file__).parent.parent.parent
    / "web" / "static" / "js" / "shared" / "state-rescrape.js"
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


# ============================================================================
# TASK-75b-T6：US1 搜尋詳情重排 + US5 影片卡 poster 格 守衛
# search.html DOM 結構 / search.css + showcase.css element-bound CSS read
# ============================================================================


# ============================================================================
# TASK-75b-T7（CD-75b-12）：≤480px poster 格 → lightbox ghost-fly 溶接守衛
# 跨檔契約：state-lightbox.js 計算並傳 posterCrop → ghost-fly.js 消費（對齊右裁 + 落地 crossfade）
# ============================================================================

GHOST_FLY_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "shared" / "ghost-fly.js"


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


# ─── TASK-81a-T5: Settings + Help 窄螢幕破版 / 長字串溢出（3 點純 CSS 補丁）───
# ── feature/81 T10 (US-10): 481–899px 影片 grid → 4-col 直式右裁 poster ────────
# ==================== TASK-81a-T11: posterCrop JS↔CSS 門檻對齊（US-10 / CD-10）====================
# 鎖死「posterCrop ghost-fly 門檻 == 燈箱封面貼合斷點 == CSS poster grid 斷點 == 899」跨 4+2 檔。
# 任一處未來漂移（只改一邊）即紅。比照 v0.10.2「JS bail 門檻對齊 CSS」防漂移前例。


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


# ============================================================================
# TASK-83b-T3: Mobile Similar Panel Transition Guards（6 條）
# 鎖住 T3 建立的封面飛行進 / 退場合約：helper 存在 / 不包裝禁區 / token 化 /
# async closeMobilePanel / PRM 分支 / 桌面禁區 anchor 不被 mobile helper 引用。
# ============================================================================


