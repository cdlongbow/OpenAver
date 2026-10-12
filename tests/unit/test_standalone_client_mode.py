# [lint-guard: pytest-justified]  啟動流程呼叫序列（client 分岔／重啟順序／接縫註冊）＋ launcher AST 順序
"""TASK-168b-T5b: standalone／launcher 把 shell_boot 與 restart 接進啟動流程。

以記錄呼叫序列的假件驗證順序與零呼叫；不比行號、不碰真網路、不 patch 全域 os.path.exists。
"""
import ast
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core import client_connect, client_settings
from core.client_connect import Preflight

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = REPO_ROOT / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

import standalone  # noqa: E402
from tray import CMD_QUIT  # noqa: E402

SERVER = "http://192.168.1.180:8000"
TOKEN = "TKN-SENTINEL-T5B"


class _FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in list(self.handlers):
            fn()


class _FakeWindow:
    def __init__(self, events):
        self._ev = events
        self.events = types.SimpleNamespace(closing=_FakeEvent(), loaded=_FakeEvent())
        self.exposed = None
        self.maximize_error = None

    def expose(self, *fns):
        self.exposed = fns

    def destroy(self):
        self._ev.append("window.destroy")

    def maximize(self):
        self._ev.append("maximize")
        if self.maximize_error:
            raise self.maximize_error


class _FakeLifecycle:
    def __init__(self, events):
        self._ev = events
        self.on_window_closing = lambda *a: None
        self.quitting = False

    def handle_tray_command(self, cmd):
        self._ev.append(("handle_tray_command", cmd))

    def shutdown_after_loop(self):
        self._ev.append("shutdown_after_loop")

    def replace_state(self, live):
        self._ev.append(("replace_state", live))

    def start_tray(self):
        self._ev.append("start_tray")


SAVED = {"width": 1000, "height": 700, "x": None, "y": None, "maximized": False}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """共用假件：事件序列 events、窗口、lifecycle、api 接縫旗標；結束後還原全域狀態。"""
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    events = []
    win = _FakeWindow(events)
    lifecycle = _FakeLifecycle(events)
    e = types.SimpleNamespace(events=events, win=win, lifecycle=lifecycle, create_calls=[],
                              marks=[], logger=MagicMock())

    monkeypatch.setattr(standalone.pywebview_api, "_restart_handler", None)
    monkeypatch.setattr(standalone.pywebview_api, "_offline_text_provider", None)
    monkeypatch.setattr(standalone.restart, "_state", {"requested": False, "spawned": False})

    monkeypatch.setattr(standalone.api, "_set_trusted_origin",
                        lambda o: events.append(("trusted", o)))
    monkeypatch.setattr(standalone.api, "_set_offline_state",
                        lambda r, u: events.append(("offline_state", r, u)))
    monkeypatch.setattr(standalone.api, "_expect_offline",
                        lambda: events.append("expect_offline"))

    def fake_create_window(title, url, **kw):
        e.create_calls.append((title, url, kw))
        events.append(("create_window", url))
        return win

    monkeypatch.setattr(standalone.webview, "create_window", fake_create_window)
    monkeypatch.setattr(standalone, "_setup_windows_lifecycle", lambda *a: lifecycle)
    monkeypatch.setattr(standalone.startup_trace, "mark", lambda k, *a, **kw: e.marks.append(k))

    fake_ws = types.SimpleNamespace(
        load_state=lambda: dict(SAVED),
        attach=lambda w, saved: {"maximized": bool(saved["maximized"])},
    )
    monkeypatch.setitem(sys.modules, "window_state", fake_ws)
    monkeypatch.setattr(standalone, "bind_events", lambda w: events.append("bind_events"))

    spawn = Mock(side_effect=lambda **kw: events.append("spawn") or False)
    monkeypatch.setattr(standalone.restart, "spawn_if_requested", spawn)
    e.spawn = spawn

    boom = Mock(side_effect=AssertionError("client mode must not start local server"))
    for name in ("find_free_port", "run_server", "_build_cf_windows", "_maybe_autostart_lan_listener"):
        monkeypatch.setattr(standalone, name, boom)
    monkeypatch.setattr(standalone.threading.Thread, "start", boom)
    e.boom = boom
    return e


def _client_json():
    client_settings.save_client_settings({"version": 1, "server": {"url": SERVER, "token": TOKEN}})


def _fake_start(env, in_loop=None):
    def start(startup, window, **kw):
        env.events.append("gui_loop_enter")
        startup(window)
        if in_loop:
            in_loop()
        env.events.append("gui_loop_exit")
    return start


def _ok_preflight(monkeypatch):
    monkeypatch.setattr(client_connect, "preflight", lambda url, token: Preflight("ok", None, {}))


# ---------- client 模式流程 ----------

def test_client_mode_ok_starts_no_local_server_and_no_cf_windows(monkeypatch, env):
    _client_json()
    _ok_preflight(monkeypatch)
    monkeypatch.setattr(standalone.webview, "start", _fake_start(env))
    standalone._run_client_mode(env.logger)

    env.boom.assert_not_called()
    assert len(env.create_calls) == 1
    title, url, kw = env.create_calls[0]
    assert "192.168.1.180" in title
    assert url.startswith(SERVER) and "oa_token=" in url
    assert kw["js_api"] is None
    messages = [str(c) for c in env.logger.info.call_args_list]
    assert not any("啟動伺服器" in m or "等待伺服器就緒" in m for m in messages)
    assert ("trusted", SERVER) in env.events
    assert env.events.index(("trusted", SERVER)) < env.events.index(
        ("create_window", url))
    assert "expect_offline" not in env.events


def test_client_mode_marks_exactly_two_new_marks_and_no_server_marks(monkeypatch, env):
    _client_json()
    _ok_preflight(monkeypatch)

    def start(startup, window, **kw):
        startup(window)
        window.events.loaded.fire()

    monkeypatch.setattr(standalone.webview, "start", start)
    standalone._run_client_mode(env.logger)
    assert env.marks[:2] == ["client_preflight_done", "main_window_created"]
    assert "first_page_loaded" in env.marks
    for forbidden in ("server_thread_started", "server_ready", "cf_windows_created"):
        assert forbidden not in env.marks


def test_offline_boot_expects_offline_before_create_window(monkeypatch, env):
    _client_json()
    monkeypatch.setattr(client_connect, "preflight",
                        lambda url, token: Preflight("offline", "unreachable", {}))
    flag = {"expected_at_create": None}
    orig = standalone.webview.create_window

    def create(title, url, **kw):
        flag["expected_at_create"] = "expect_offline" in env.events
        flag["state_at_create"] = [x for x in env.events if isinstance(x, tuple) and x[0] == "offline_state"]
        return orig(title, url, **kw)

    monkeypatch.setattr(standalone.webview, "create_window", create)
    monkeypatch.setattr(standalone.webview, "start", _fake_start(env))
    standalone._run_client_mode(env.logger)

    from windows.shell_boot import OFFLINE_PAGE
    print("EVENTS:", [x for x in env.events if x in ("expect_offline",) or isinstance(x, tuple)])  # noqa: T201
    assert flag["expected_at_create"] is True
    assert flag["state_at_create"] == [("offline_state", "unreachable", SERVER)]
    assert env.create_calls[0][1] == OFFLINE_PAGE
    assert TOKEN not in str(flag["state_at_create"])
    env.boom.assert_not_called()


# ---------- 重啟 ----------

def test_restart_quit_goes_through_lifecycle_quit_path(env):
    quit_app = standalone._make_quit_app(env.win, env.lifecycle)
    quit_app()
    assert env.events == [("handle_tray_command", CMD_QUIT)]
    assert env.lifecycle.quitting is False   # 不手設 quitting，否則 shutdown_after_loop 會被略過


def test_make_quit_app_without_lifecycle_is_window_destroy(env):
    assert standalone._make_quit_app(env.win, None) == env.win.destroy


def test_shutdown_helper_spawns_restart_after_lifecycle_shutdown(env):
    standalone._shutdown_and_maybe_restart(env.lifecycle)
    assert env.events == ["shutdown_after_loop", "spawn"]
    env.spawn.assert_called_once()
    assert env.spawn.call_args.kwargs["notify_error"] is standalone._restart_failed_notice


def test_shutdown_helper_without_lifecycle_still_spawns(env):
    standalone._shutdown_and_maybe_restart(None)
    assert env.events == ["spawn"]


def test_restart_sequence_in_client_mode(monkeypatch, env):
    _client_json()
    _ok_preflight(monkeypatch)

    def trigger():
        assert standalone.pywebview_api._request_restart() is True
        assert "spawn" not in env.events      # 迴圈返回前零 spawn

    monkeypatch.setattr(standalone.webview, "start", _fake_start(env, in_loop=trigger))
    standalone._run_client_mode(env.logger)
    seq = [x for x in env.events if x in ("gui_loop_enter", "gui_loop_exit", "shutdown_after_loop", "spawn")
           or (isinstance(x, tuple) and x[0] == "handle_tray_command")]
    print("EVENTS:", seq)  # noqa: T201  事件序列供 -s 目視
    assert seq == ["gui_loop_enter", ("handle_tray_command", CMD_QUIT), "gui_loop_exit",
                   "shutdown_after_loop", "spawn"]
    assert env.spawn.call_count == 1
    assert standalone.restart._state["requested"] is True


def test_client_mode_lifecycle_none_restart_uses_window_destroy(monkeypatch, env):
    _client_json()
    _ok_preflight(monkeypatch)
    monkeypatch.setattr(standalone, "_setup_windows_lifecycle", lambda *a: None)
    monkeypatch.setattr(standalone.webview, "start",
                        _fake_start(env, in_loop=lambda: standalone.pywebview_api._request_restart()))
    standalone._run_client_mode(env.logger)
    assert "window.destroy" in env.events
    assert env.events[-1] == "spawn"
    assert "shutdown_after_loop" not in env.events


def test_client_mode_wires_close_handler_and_lifecycle_args(monkeypatch, env):
    _client_json()
    _ok_preflight(monkeypatch)
    captured = {}
    monkeypatch.setattr(standalone, "_setup_windows_lifecycle", lambda *a: captured.setdefault("a", a) and env.lifecycle)
    monkeypatch.setattr(standalone.webview, "start", _fake_start(env))
    standalone._run_client_mode(env.logger)
    assert captured["a"][1:3] == (None, None) and captured["a"][4] is None
    assert env.lifecycle.on_window_closing in env.win.events.closing.handlers


def test_restart_failed_notice_win32_uses_message_box(monkeypatch):
    box, err = Mock(), Mock()
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "_win_message_box", box)
    monkeypatch.setattr(standalone, "show_error", err)
    standalone._restart_failed_notice("msg")
    box.assert_called_once_with("msg", "OpenAver", yes_no=False)
    err.assert_not_called()


def test_restart_failed_notice_win32_box_failure_falls_back_to_show_error(monkeypatch):
    box, err = Mock(side_effect=OSError("no ui")), Mock()
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "_win_message_box", box)
    monkeypatch.setattr(standalone, "show_error", err)
    standalone._restart_failed_notice("msg")
    box.assert_called_once()
    err.assert_called_once()
    assert err.call_args.args[:2] == ("OpenAver", "msg")


def test_restart_failed_notice_non_win32_uses_show_error_only(monkeypatch):
    box, err = Mock(), Mock()
    monkeypatch.setattr(standalone.sys, "platform", "linux")
    monkeypatch.setattr(standalone, "_win_message_box", box)
    monkeypatch.setattr(standalone, "show_error", err)
    standalone._restart_failed_notice("msg")
    box.assert_not_called()
    err.assert_called_once()


def test_restart_failed_notice_never_raises(monkeypatch):
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "_win_message_box", Mock(side_effect=OSError("x")))
    monkeypatch.setattr(standalone, "show_error", Mock(side_effect=RuntimeError("x")))
    standalone._restart_failed_notice("msg")


# ---------- 接縫註冊 ----------

@pytest.mark.parametrize("lifecycle_on", [True, False])
def test_register_bridge_seams_registers_both(env, lifecycle_on):
    lifecycle = env.lifecycle if lifecycle_on else None
    standalone._register_bridge_seams(env.win, lifecycle)
    assert standalone.pywebview_api._offline_text_provider is standalone.shell_boot.offline_texts
    assert standalone.pywebview_api._restart_handler is not None
    assert standalone.pywebview_api._request_restart() is True
    expected = ("handle_tray_command", CMD_QUIT) if lifecycle_on else "window.destroy"
    assert env.events == [expected]
    assert standalone.restart._state["requested"] is True


def test_local_main_path_also_registers_seams():
    src = (WINDOWS_DIR / "standalone.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    names = {c.func.id for c in ast.walk(main) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert {"_register_bridge_seams", "_create_main_window", "_shutdown_and_maybe_restart",
            "_attach_window_state", "_run_client_mode"} <= names


# ---------- main() 分岔與順序 ----------

def _patch_main_prelude(monkeypatch, events):
    monkeypatch.setattr(standalone, "setup_logging", lambda **k: None)
    monkeypatch.setattr(standalone, "get_logger", lambda name: MagicMock())
    monkeypatch.setattr(standalone, "bootstrap_data_layout", lambda: MagicMock(status="already_complete"))
    monkeypatch.setattr(standalone.restart, "wait_for_parent_exit",
                        lambda *a, **k: events.append("wait_for_parent_exit"))
    monkeypatch.setattr(standalone.shell_boot, "install_webview_token_filter",
                        lambda: events.append("install_filter"))

    def ensure(logger):
        events.append("ensure_webview2")
        raise SystemExit(0)

    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", ensure)


def test_main_waits_for_restart_parent_before_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    events = []
    _patch_main_prelude(monkeypatch, events)
    with pytest.raises(SystemExit):
        standalone.main()
    assert "wait_for_parent_exit" in events and "ensure_webview2" in events
    assert events.index("wait_for_parent_exit") < events.index("ensure_webview2")


def test_token_filter_installed_before_resolve_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    events = []
    _patch_main_prelude(monkeypatch, events)
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone, "_bootstrap_data_layout_or_exit", lambda logger: None)
    monkeypatch.setattr(standalone, "_run_client_mode", lambda logger: events.append("client_mode"))
    monkeypatch.setattr(client_settings, "mode", lambda: "client")

    def resolve(*a, **k):
        events.append("resolve_boot")
        raise SystemExit(0)

    monkeypatch.setattr(standalone.shell_boot, "resolve_boot", resolve)
    standalone.main()
    assert "install_filter" in events
    assert events.index("install_filter") < events.index("client_mode")

    # 本機路徑：resolve_boot 之前 filter 已裝
    events.clear()
    monkeypatch.setattr(client_settings, "mode", lambda: "local")
    monkeypatch.setattr(standalone, "find_free_port", lambda *a, **k: 49152)
    monkeypatch.setattr(standalone.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(standalone, "_wait_for_server_or_exit", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "web.app", types.SimpleNamespace(app=object()))
    ll = types.SimpleNamespace(lan_listener=MagicMock())
    monkeypatch.setitem(sys.modules, "web.lan_listener", ll)
    monkeypatch.setattr(standalone, "_maybe_autostart_lan_listener", lambda *a: None)
    monkeypatch.setitem(sys.modules, "window_state", types.SimpleNamespace(load_state=lambda: dict(SAVED)))
    with pytest.raises(SystemExit):
        standalone.main()
    assert "resolve_boot" in events
    assert events.index("install_filter") < events.index("resolve_boot")


def test_main_client_mode_branches_before_port_and_returns(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    events = []
    _patch_main_prelude(monkeypatch, events)
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone, "_bootstrap_data_layout_or_exit", lambda logger: None)
    monkeypatch.setattr(client_settings, "mode", lambda: "client")
    monkeypatch.setattr(standalone, "_run_client_mode", lambda logger: events.append("client_mode"))
    boom = Mock(side_effect=AssertionError("main must not continue in client mode"))
    monkeypatch.setattr(standalone, "find_free_port", boom)
    monkeypatch.setattr(standalone, "run_server", boom)
    standalone.main()
    assert "client_mode" in events
    boom.assert_not_called()


def test_main_local_mode_finally_goes_through_shutdown_helper(monkeypatch, env, tmp_path):
    """本機模式 main()：GUI 迴圈返回後走 _shutdown_and_maybe_restart（shutdown 先於 spawn）。"""
    events = env.events
    # env 把本機服務換成自爆件；此測試要的是本機路徑，改回無害假件
    monkeypatch.setattr(standalone, "find_free_port", lambda *a, **k: 49152)
    monkeypatch.setattr(standalone, "run_server", lambda *a, **k: None)
    monkeypatch.setattr(standalone.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(standalone, "_wait_for_server_or_exit", lambda *a, **k: None)
    monkeypatch.setattr(standalone, "_maybe_autostart_lan_listener", lambda *a: None)
    monkeypatch.setattr(standalone, "_build_cf_windows", lambda logger: (None, None))
    monkeypatch.setattr(standalone, "setup_logging", lambda **k: None)
    monkeypatch.setattr(standalone, "get_logger", lambda name: MagicMock())
    monkeypatch.setattr(standalone, "bootstrap_data_layout", lambda: MagicMock(status="already_complete"))
    monkeypatch.setattr(standalone, "_ensure_webview2_runtime", lambda logger: None)
    monkeypatch.setattr(standalone.restart, "wait_for_parent_exit", lambda *a, **k: None)
    monkeypatch.setattr(standalone.shell_boot, "install_webview_token_filter", lambda: None)
    monkeypatch.setitem(sys.modules, "web.app", types.SimpleNamespace(app=object()))
    monkeypatch.setitem(sys.modules, "web.lan_listener", types.SimpleNamespace(lan_listener=MagicMock()))
    monkeypatch.setattr(standalone.webview, "start", _fake_start(env))
    standalone.main()
    assert events[-2:] == ["shutdown_after_loop", "spawn"]
    # 本機模式：兩個接縫也註冊了
    assert standalone.pywebview_api._restart_handler is not None
    assert standalone.pywebview_api._offline_text_provider is not None
    assert "client_preflight_done" not in env.marks
    assert env.marks.index("main_window_created") < env.marks.index("cf_windows_created")


# ---------- lifecycle / window state ----------

def test_setup_windows_lifecycle_lan_listener_none(monkeypatch):
    captured = {}

    class FakeLifecycle:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def attach_tray(self, tray):
            pass

        def handle_tray_command(self, *a):
            pass

        def get_close_action(self):
            return "ask"

    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "DesktopLifecycle", FakeLifecycle)
    monkeypatch.setattr(standalone, "NativeTrayIcon", lambda *a, **k: object())
    monkeypatch.setitem(sys.modules, "window_state", types.SimpleNamespace(save_state=lambda s: None))
    standalone._setup_windows_lifecycle(object(), None, None, {}, None)
    assert captured["on_quit_cleanup"] is None
    ll = types.SimpleNamespace(shutdown=lambda: None)
    standalone._setup_windows_lifecycle(object(), None, None, {}, ll)
    assert captured["on_quit_cleanup"] == ll.shutdown


def test_attach_window_state_equivalent_to_old_startup(monkeypatch, env):
    saved = dict(SAVED, maximized=True)
    live_box = {}

    def attach(w, s):
        live_box["live"] = {"maximized": True}
        return live_box["live"]

    monkeypatch.setitem(sys.modules, "window_state", types.SimpleNamespace(attach=attach))
    standalone._attach_window_state(env.win, saved, env.lifecycle, env.logger)
    assert env.events == ["bind_events", ("replace_state", live_box["live"]), "start_tray", "maximize"]
    assert live_box["live"]["maximized"] is True


def test_attach_window_state_maximize_failure_clears_live_flag(monkeypatch, env):
    env.win.maximize_error = RuntimeError("no")
    live = {"maximized": True}
    monkeypatch.setitem(sys.modules, "window_state", types.SimpleNamespace(attach=lambda w, s: live))
    standalone._attach_window_state(env.win, dict(SAVED, maximized=True), None, env.logger)
    assert live["maximized"] is False
    assert not any(isinstance(x, tuple) for x in env.events)   # lifecycle 為 None 時不碰


# ---------- launcher AST ----------

def _launcher_tree():
    path = WINDOWS_DIR / "launcher.py"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _calls(tree, dotted):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _chain(n.func) == dotted]


def test_launcher_installs_filter_before_resolve_boot():
    tree = _launcher_tree()
    filt = _calls(tree, "shell_boot.install_webview_token_filter")
    resolve = _calls(tree, "shell_boot.resolve_boot")
    assert len(filt) == 1 and len(resolve) == 1
    assert filt[0].lineno < resolve[0].lineno
    assert len(_calls(tree, "restart.wait_for_parent_exit")) == 1


def test_launcher_spawns_restart_after_gui_loop():
    tree = _launcher_tree()
    spawns = _calls(tree, "restart.spawn_if_requested")
    assert len(spawns) == 1
    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)
             and any(_chain(c.func) == "webview.start" for b in n.body for c in ast.walk(b)
                     if isinstance(c, ast.Call))]
    assert len(tries) == 1
    final_calls = [c for b in tries[0].finalbody for c in ast.walk(b) if isinstance(c, ast.Call)]
    assert spawns[0] in final_calls


def test_launcher_expect_offline_before_create_window():
    tree = _launcher_tree()
    expect = _calls(tree, "api._expect_offline")
    state = _calls(tree, "api._set_offline_state")
    cw = _calls(tree, "webview.create_window")
    assert len(expect) == len(state) == len(cw) == 1
    assert state[0].lineno < cw[0].lineno and expect[0].lineno < cw[0].lineno
