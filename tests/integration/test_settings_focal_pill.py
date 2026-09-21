"""tests/integration/test_settings_focal_pill.py — F3/F4 settings 頁人臉自動對焦狀態列
（feature/152c TASK-9，CD-152c-19）。

`client` fixture 與 config 隔離（`_isolate_config` autouse）都來自
`tests/integration/conftest.py`；每個測試在該隔離設定檔上用
`core_config.mutate_config` 覆寫 `focal_device`，不直接用 `save_config`
整份取代（會漏掉 AppConfig 其他欄位，讓 /settings 渲染其他區塊時噴錯）。
"""
from __future__ import annotations

from core import config as core_config
from core.version import VERSION


def _seed_focal_device(*, disabled: bool, judged_at_version: str, consecutive_timeout_count: int = 2) -> None:
    def _mutator(cfg: dict) -> None:
        cfg["focal_device"] = {
            "disabled": disabled,
            "consecutive_timeout_count": consecutive_timeout_count,
            "judged_at_version": judged_at_version,
        }
    core_config.mutate_config(_mutator)


def _extract_focal_input_tag(html: str) -> str:
    """抓出人臉自動對焦那顆 <input> 的完整開始標籤（不含其他 toggle）。

    不能用文案定位：文案定位會被「前面任何含相同字串的元素或註解」搶走，reviewer 實測可假綠。
    改以 data-focal-auto-pill 錨點屬性定位：
    html.index("data-focal-auto-pill") 找到屬性位置 →
    html.rindex("<input", 0, idx) 往回找標籤開頭 →
    html.index(">", input_start) 找標籤結尾。
    """
    idx = html.index("data-focal-auto-pill")
    input_start = html.rindex("<input", 0, idx)
    input_end = html.index(">", input_start)
    return html[input_start:input_end + 1]


class TestSettingsFocalAutoPill:
    def test_version_mismatch_lazy_reset_renders_enabled(self, client):
        """F3 核心驗收（CD-152c-19）：舊版本判定的 disabled=True，執行版本已不同
        → /settings 渲染出「啟用」。若前端／模板改成直接讀 config.focal_device.disabled，
        這條會紅（那正是它存在的理由）。
        """
        assert "0.16.3" != VERSION, "測試前提：judged_at_version 需與目前 VERSION 不同"
        _seed_focal_device(disabled=True, judged_at_version="0.16.3")

        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.text
        input_tag = _extract_focal_input_tag(html)

        # [lint-guard: pytest-justified] 以下對 html／input_tag 的字面斷言驗的是
        # 「同一份模板在不同 focal_device 狀態下渲染出不同結果」。static_guard_lint
        # 讀的是模板檔本身的靜態字面，表達不了「後端狀態 X ⇒ 輸出必須含 A 且不得含 B」
        # 這個跨層條件契約——兩種狀態的文案都寫在同一個模板檔裡，靜態掃描永遠同時看得到。
        assert "checked" in input_tag, f"版本已變更，預期渲染成啟用（checked），實際標籤：{input_tag}"
        assert "會自動關閉這個功能" in html, "啟用態浮層文字應包含啟用態說明（會自動關閉這個功能）"
        assert "已自動關閉這台機器的人臉自動對焦" not in html, "停用態說明文字不得出現在啟用態"

    def test_matching_version_disabled_renders_unchecked_with_reason(self, client):
        """disabled=True 且 judged_at_version == 目前 VERSION → 維持停用，
        ? 浮層含原因文字。
        """
        _seed_focal_device(disabled=True, judged_at_version=VERSION)

        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.text
        input_tag = _extract_focal_input_tag(html)

        # [lint-guard: pytest-justified] 以下對 html／input_tag 的字面斷言驗的是
        # 「同一份模板在不同 focal_device 狀態下渲染出不同結果」。static_guard_lint
        # 讀的是模板檔本身的靜態字面，表達不了「後端狀態 X ⇒ 輸出必須含 A 且不得含 B」
        # 這個跨層條件契約——兩種狀態的文案都寫在同一個模板檔裡，靜態掃描永遠同時看得到。
        assert "checked" not in input_tag, f"版本相同、仍停用，不應 checked，實際標籤：{input_tag}"
        assert "偵測連續兩次超過 5 秒沒算完" in html, "停用原因文字（只講「超過 5 秒」與「已自動關閉」兩件事實，不含實測耗時數字）應出現在 ? 浮層"
        assert "燈箱裡自己拖曳" in html, "原因文字必須寫出逃生口：燈箱手動拖曳對焦"
        assert "已自動關閉" in html
        assert "會自動關閉這個功能" not in html, "啟用態說明不得出現在停用態"

    def test_focal_pill_anchor_is_unique(self, client):
        """防止錨點哪天變得不唯一、讓 _extract_focal_input_tag 定位又開始抓錯。"""
        # [lint-guard: pytest-justified DOM 錨點唯一性契約]
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert resp.text.count("data-focal-auto-pill") == 1

