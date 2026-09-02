"""T5: Search 搜尋列 icon 互斥守衛"""
from pathlib import Path


class TestSearchIconMutex:

    def _read_search_html(self):
        return Path("web/templates/search.html").read_text()

    # [lint-guard: migrate→96b] isComposing HTML 半邊待 96b 承接
    # （CSS 半邊 test_btn_icon_has_flex_shrink 已遷 css-guard CG-SB-03）
    def test_grid_toggle_has_is_composing_guard(self):
        """Grid toggle x-show 必須含 !isComposing() 條件"""
        content = self._read_search_html()
        assert "isComposing()" in content
        # TASK-141a-T7：切換鈕的顯示條件從模式白名單（actress/prefix）改成問
        # 「有沒有第二張卡」，所以那一行不再含 actress/prefix。本測試守的是
        # **與來源膠囊的互斥沒有被拿掉**，錨點改用同一顆鈕穩定的 @click 目標。
        # 表達式本身的完整契約由 static_guard_lint 的 [lint-guard 141a-T7] 那條鎖著
        # （單檔字面契約只寫 lint、不在這裡重複一份 —— CLAUDE.md lint north-star）。
        lines = content.split('\n')
        idx = [i for i, l in enumerate(lines) if 'toggleDisplayMode()' in l]
        assert idx, "找不到 Grid toggle 那顆按鈕的 @click"
        window = '\n'.join(lines[max(0, idx[0] - 5):idx[0] + 1])
        assert 'isComposing' in window, "Grid toggle 的顯示條件必須仍含 !isComposing()（與來源膠囊互斥）"
