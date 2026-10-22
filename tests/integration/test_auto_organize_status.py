"""TASK-144-T7: GET /api/search/auto-organize/status schema ＋ 唯讀性（D8 / M4）。"""

from core import auto_organize_state


EXPECTED_KEYS = {
    "running",
    "current_number",
    "enabled",
    "folder",
    "folder_is_set",
    "resolved_folder",
}


def test_get_auto_organize_status_reflects_real_running_state(client):
    """M4：回應如實反映 _running，防止恆真退化。"""
    auto_organize_state.exit_cron()
    idle = client.get("/api/search/auto-organize/status").json()
    assert idle["running"] is False
    assert idle["current_number"] is None

    assert auto_organize_state.enter_cron("run_now") is True
    try:
        auto_organize_state.set_current_number("ABC-123")
        busy = client.get("/api/search/auto-organize/status").json()
        assert busy["running"] is True
        assert busy["current_number"] == "ABC-123"
    finally:
        auto_organize_state.exit_cron()

    after = client.get("/api/search/auto-organize/status").json()
    assert after["running"] is False
    assert after["current_number"] is None


