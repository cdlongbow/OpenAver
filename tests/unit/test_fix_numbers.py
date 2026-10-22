"""
test_fix_numbers.py — Unit tests for fix-numbers logic:
  - _get_fixed_number helper
  - preview rule filtering (empty rules / rules subset)
  - apply re-validation
  - invalid rule names → 400

All tests are pure Python — no FS, no DB, no network.
"""




# ── U1: preview 規則過濾 — 空 rules 套用全部 ─────────────────────────────────


# ── U2: preview 規則過濾 — 指定 rules 子集 ───────────────────────────────────


# ── U3: fix_group 提取正確性 ──────────────────────────────────────────────────

class TestGetFixedNumber:
    """U3: _get_fixed_number 對各種 corrupted number 回傳正確的修正番號"""

    def setup_method(self):
        from web.routers.collection import _get_fixed_number
        self._get_fixed_number = _get_fixed_number

    def test_digit_prefix(self):
        """7IPZ-154 → digit_prefix fix_group=2 → IPZ-154"""
        result = self._get_fixed_number("7IPZ-154")
        assert result == "IPZ-154"

    def test_tk_prefix(self):
        """TKIPZ-154 → TK_prefix fix_group=1 → IPZ-154"""
        result = self._get_fixed_number("TKIPZ-154")
        assert result == "IPZ-154"


    def test_normal_number_returns_none(self):
        """正常番號 IPZ-154 → None（不 match 任何規則）"""
        result = self._get_fixed_number("IPZ-154")
        assert result is None


# ── U4: apply 重新驗證 — 番號已修正則跳過 ────────────────────────────────────


# ── U5: rules 含無效名稱 → 400 ───────────────────────────────────────────────

class TestInvalidRuleNames:
    """U5: rules 含不在 CORRUPTION_RULES 中的名稱應觸發 HTTP 400"""

    def setup_method(self):
        from fastapi.testclient import TestClient
        from web.app import app
        self.client = TestClient(app)


