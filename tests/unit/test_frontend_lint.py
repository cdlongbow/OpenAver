"""前端靜態守衛 — 確保 template 包含必要的 Alpine 綁定"""
from pathlib import Path


NAVIGATION_JS = Path(__file__).parent.parent.parent / "web" / "static" / "js" / "pages" / "search" / "state" / "navigation.js"


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

    # 162c 模糊留：二審未定（A：抄進 showFavoriteActresses gate → 手機滑詳情靜默失效；B：未複判）
    def test_dt_touch_end_no_actress_gate(self):
        """負向守衛：_dtTouchEnd 不含 showFavoriteActresses（CD-3，detail 純導航不分流）"""
        block = self._dt_touch_end_block()
        assert "showFavoriteActresses" not in block, \
            "_dtTouchEnd 不可含 showFavoriteActresses（detail 純導航不分流，CD-3）"

    # 162c 模糊留：二審未定（A：誤呼叫燈箱 prev/next → 滑詳情作用在錯對象；B：未複判）
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
