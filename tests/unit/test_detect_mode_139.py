"""
test_detect_mode_139.py - _detect_mode 路由標籤單元測試 (TASK-139-T9, DoD-3 / DoD-7)
"""

from web.routers.search import _detect_mode


def test_detect_mode_bracket_wrapped_returns_exact():
    """DoD-7: [ABC-123] 帶包裝字串經 _detect_mode 判為 exact（改前為 actress）。"""
    assert _detect_mode("[ABC-123]") == "exact"


