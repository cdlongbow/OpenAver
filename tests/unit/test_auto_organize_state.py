"""tests/unit/test_auto_organize_state.py - 自動整理狀態模組單元測試

覆蓋 TASK-144-T4a DoD 1-5, 8, 10 與生命週期驗證。
"""

import pytest
from core import auto_organize_state


@pytest.fixture(autouse=True)
def reset_state():
    """每個測試前後重置 auto_organize_state 的模組狀態。"""
    with auto_organize_state._lock:
        auto_organize_state._running = False
        auto_organize_state._current_number = None
        auto_organize_state._abort_requested = False
        auto_organize_state._last_manual_at = float("-inf")
    yield
    with auto_organize_state._lock:
        auto_organize_state._running = False
        auto_organize_state._current_number = None
        auto_organize_state._abort_requested = False
        auto_organize_state._last_manual_at = float("-inf")


def test_schedule_blocked_by_recent_manual_activity():
    """DoD-1 / mutation M2: enter_cron('schedule') 最近 10 分鐘有人動過時拒絕。"""
    auto_organize_state.mark_manual_activity(now=1000.0)
    # 500 秒 < 600 秒，應被擋下
    assert auto_organize_state.enter_cron("schedule", now=1500.0) is False
    # 邊界值：剛好 600 秒（1600 - 1000 == 600，not < 600），應成功進場
    assert auto_organize_state.enter_cron("schedule", now=1600.0) is True


def test_run_now_blocked_only_by_running_cron():
    """DoD-2: enter_cron('run_now') 另一輪在跑時拒絕。"""
    assert auto_organize_state.enter_cron("run_now", now=1000.0) is True
    assert auto_organize_state.enter_cron("run_now", now=2000.0) is False


def test_run_now_not_blocked_by_recent_manual_activity():
    """DoD-2 / mutation M1: enter_cron('run_now') 不受最近手動操作影響。"""
    auto_organize_state.mark_manual_activity(now=1000.0)
    # 10 秒前才剛動過手動操作，run_now 仍應成功進場
    assert auto_organize_state.enter_cron("run_now", now=1010.0) is True


