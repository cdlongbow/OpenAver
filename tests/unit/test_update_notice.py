"""TASK-168c-T3: 啟動時更新提醒（顯示成功才記帳）。全部假件，不連網。"""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core import client_settings, self_update
from core import config as core_config

WINDOWS_DIR = Path(__file__).resolve().parents[2] / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

from windows import update_notice  # noqa: E402

SERVER = "http://192.168.1.180:8000"
TOKEN = "TKN-SENTINEL-T3-NOTICE"
NEWER = {"ok": True, "has_update": True, "current_version": "0.17.7", "latest_version": "9.9.9"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / ".layout.json").write_text(json.dumps({"version": 1, "complete": True}), encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(update_notice, "_state", {"pending": None, "page": None})
    monkeypatch.setattr(update_notice, "_run_async", lambda fn, *a: fn(*a))


def _client(**over):
    d = {"version": 1, "server": {"url": SERVER, "token": TOKEN}}
    d.update(over)
    client_settings.save_client_settings(d)


@pytest.fixture
def ctx(env, monkeypatch):
    c = MagicMock()
    c.check = Mock(return_value=dict(NEWER))
    monkeypatch.setattr(self_update, "check_latest", c.check)
    c.write = Mock(wraps=client_settings.update_local_settings)
    monkeypatch.setattr(client_settings, "update_local_settings", c.write)
    c.cur = {"v": True}
    c.is_current = lambda: c.cur["v"]
    c.win = MagicMock()
    return c


def _bytes(env):
    return {p.name: p.read_bytes() for p in env.iterdir() if p.is_file()}


@pytest.mark.parametrize("not_confirmed", [False, 1, "true", {"ok": True}])  # 只有精確 True 才算顯示過
def test_notice_not_recorded_until_page_confirms_display(env, ctx, not_confirmed):
    _client()
    ctx.win.evaluate_js = Mock(side_effect=[not_confirmed, True])
    update_notice.check_once()                       # 結果先到，尚無頁面
    ctx.win.evaluate_js.assert_not_called()
    update_notice.try_show(ctx.win, 1, ctx.is_current)   # load(F)：頁面沒有通知容器
    assert ctx.win.evaluate_js.call_count == 1
    ctx.write.assert_not_called()
    assert client_settings.last_notified_update_version() == ""
    update_notice.try_show(ctx.win, 2, ctx.is_current)   # load(T)
    assert ctx.win.evaluate_js.call_count == 2
    assert ctx.write.call_count == 1
    assert client_settings.last_notified_update_version() == "9.9.9"
    update_notice.try_show(ctx.win, 3, ctx.is_current)   # 已記帳，不再彈
    assert ctx.win.evaluate_js.call_count == 2
    assert ctx.write.call_count == 1


def test_notice_shows_immediately_when_page_arrived_before_result(env, ctx):
    _client()
    ctx.win.evaluate_js = Mock(return_value=True)
    update_notice.try_show(ctx.win, 1, ctx.is_current)   # load(T)，尚無 pending
    ctx.win.evaluate_js.assert_not_called()
    update_notice.check_once()
    assert ctx.win.evaluate_js.call_count == 1
    assert "9.9.9" in ctx.win.evaluate_js.call_args.args[0]
    assert ctx.write.call_count == 1
    assert client_settings.last_notified_update_version() == "9.9.9"


def test_notice_not_repeated_for_already_recorded_version(env, ctx):
    _client(last_notified_update_version="9.9.9")
    update_notice.check_once()
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    ctx.win.evaluate_js.assert_not_called()
    ctx.write.assert_not_called()


def test_notice_auto_check_off_makes_zero_requests(env, ctx):
    _client(auto_check_update=False)
    update_notice.check_once()
    update_notice.start_background_check()
    ctx.check.assert_not_called()
    ctx.win.evaluate_js.assert_not_called()


def test_notice_in_local_mode_is_inert(env, ctx):
    (env / "config.json").write_text(json.dumps({"general": {"auto_check_update": True}}), encoding="utf-8")
    assert client_settings.mode() == "local"
    before = _bytes(env)
    update_notice.check_once()
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    update_notice.start_background_check()
    ctx.check.assert_not_called()
    ctx.win.evaluate_js.assert_not_called()
    ctx.write.assert_not_called()
    assert _bytes(env) == before


def test_notice_stale_page_keeps_pending_and_shows_when_page_recovers(env, ctx):
    _client()
    ctx.win.evaluate_js = Mock(return_value=True)
    ctx.cur["v"] = False
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    update_notice.check_once()
    ctx.win.evaluate_js.assert_not_called()
    ctx.write.assert_not_called()
    assert update_notice._state["pending"] == "9.9.9"
    ctx.cur["v"] = True
    update_notice.try_show(ctx.win, 2, ctx.is_current)
    assert ctx.win.evaluate_js.call_count == 1
    assert ctx.write.call_count == 1


@pytest.mark.parametrize("bad", ["<script>alert(1)</script>", "1.2.x", "", "1.2\n", "v1.2", None, 12])
def test_notice_invalid_version_string_never_reaches_js(env, ctx, bad):
    _client()
    ctx.check.return_value = dict(NEWER, latest_version=bad)
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    update_notice.check_once()
    assert update_notice._state["pending"] is None
    ctx.win.evaluate_js.assert_not_called()
    ctx.write.assert_not_called()


@pytest.mark.parametrize("result", [{"ok": False, "reason": "network"},
                                    {"ok": True, "has_update": False, "current_version": "0.17.7"}])
def test_notice_no_update_or_failed_check_shows_nothing(env, ctx, result):
    _client()
    ctx.check.return_value = result
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    update_notice.check_once()
    ctx.win.evaluate_js.assert_not_called()


def test_notice_logs_never_contain_token(env, ctx, caplog):
    _client()
    caplog.set_level(logging.DEBUG)
    ctx.check.side_effect = RuntimeError(f"boom {TOKEN}")
    update_notice.check_once()
    ctx.check.side_effect = None
    ctx.win.evaluate_js = Mock(side_effect=RuntimeError(f"boom {TOKEN}"))
    update_notice.try_show(ctx.win, 1, ctx.is_current)
    update_notice.check_once()
    assert TOKEN not in caplog.text


def test_notice_stale_hook_registering_late_does_not_override_current_page(env, ctx):
    _client()
    ctx.win.evaluate_js = Mock(return_value=True)
    gen = {"v": 2}                                    # 現行頁是 gen 2
    update_notice.try_show(ctx.win, 2, lambda: gen["v"] == 2)   # 新頁先登記
    update_notice.try_show(ctx.win, 1, lambda: gen["v"] == 1)   # 舊 hook 延遲後才登記（已過期）
    update_notice.check_once()                        # 背景檢查此時完成
    assert ctx.win.evaluate_js.call_count == 1
    assert ctx.write.call_count == 1
