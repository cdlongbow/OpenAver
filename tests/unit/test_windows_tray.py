from unittest.mock import MagicMock
from pathlib import Path

import pytest

from windows.tray import (
    CLOSE_ASK,
    CLOSE_CANCEL,
    CLOSE_EXIT,
    CLOSE_TRAY,
    CMD_CLOSE_ASK,
    CMD_CLOSE_EXIT,
    CMD_CLOSE_TRAY,
    CMD_CONFIRM,
    CMD_OPEN,
    CMD_QUIT,
    IDCANCEL,
    CloseDecision,
    DesktopLifecycle,
    _map_dialog_result,
    load_desktop_texts,
)


@pytest.fixture
def desktop():
    window = MagicMock()
    jl_window = MagicMock()
    tray = MagicMock()
    saved = []
    # close_action store: injected dict-backed read/write (feature/82 T4)
    close_action_store = {"value": CLOSE_ASK}
    close_action_writes = []  # record each write for assertions

    def _read_ca():
        return close_action_store["value"]

    def _write_ca(action):
        close_action_store["value"] = action
        close_action_writes.append(action)

    state = {
        "width": 1200,
        "height": 800,
        "x": None,
        "y": None,
        "maximized": False,
    }
    lifecycle = DesktopLifecycle(
        window, {'javlibrary': jl_window}, state,
        lambda value: saved.append(dict(value)),
        read_close_action=_read_ca,
        write_close_action=_write_ca,
    )
    lifecycle.attach_tray(tray)
    tray.start.return_value = True
    lifecycle.start_tray()
    return lifecycle, window, jl_window, tray, saved, close_action_store, close_action_writes


def test_prompt_tray_remember_hides_and_cancels_close(desktop):
    lifecycle, window, jl_window, tray, saved, ca_store, ca_writes = desktop
    lifecycle.prompt = lambda: CloseDecision(CLOSE_TRAY, remember=True)

    assert lifecycle.on_window_closing() is False
    window.hide.assert_called_once_with()
    jl_window.destroy.assert_not_called()
    tray.stop.assert_not_called()
    assert lifecycle.get_close_action() == CLOSE_TRAY
    # close_action now written via injected write_close_action (not geometry saved[])
    assert ca_store["value"] == CLOSE_TRAY
    assert ca_writes[-1] == CLOSE_TRAY


def test_prompt_cancel_keeps_window_open(desktop):
    lifecycle, window, jl_window, tray, saved, ca_store, ca_writes = desktop
    lifecycle.prompt = lambda: CloseDecision(CLOSE_CANCEL, remember=True)

    assert lifecycle.on_window_closing() is False
    window.hide.assert_not_called()
    jl_window.destroy.assert_not_called()
    assert lifecycle.get_close_action() == CLOSE_ASK
    assert ca_writes == []


def test_remembered_tray_skips_prompt(desktop):
    lifecycle, window, _jl_window, _tray, _saved, ca_store, _ca_writes = desktop
    # inject tray action directly into the store (injected path)
    ca_store["value"] = CLOSE_TRAY
    lifecycle.prompt = MagicMock(side_effect=AssertionError("prompt must not run"))

    assert lifecycle.on_window_closing() is False
    window.hide.assert_called_once_with()
    lifecycle.prompt.assert_not_called()


def test_remembered_exit_stops_tray_and_allows_close(desktop):
    lifecycle, _window, jl_window, tray, saved, ca_store, _ca_writes = desktop
    # inject exit action directly into the store (injected path)
    ca_store["value"] = CLOSE_EXIT

    assert lifecycle.on_window_closing() is None
    assert lifecycle.quitting is True
    tray.stop.assert_called_once_with()
    jl_window.destroy.assert_called_once_with()
    assert saved  # geometry state is still saved on quit


def test_tray_commands_open_change_preference_and_quit(desktop):
    lifecycle, window, jl_window, tray, saved, ca_store, ca_writes = desktop

    lifecycle.handle_tray_command(CMD_OPEN)
    window.show.assert_called_once_with()

    lifecycle.handle_tray_command(CMD_CLOSE_TRAY)
    assert lifecycle.get_close_action() == CLOSE_TRAY
    lifecycle.handle_tray_command(CMD_CLOSE_EXIT)
    assert lifecycle.get_close_action() == CLOSE_EXIT
    lifecycle.handle_tray_command(CMD_CLOSE_ASK)
    assert lifecycle.get_close_action() == CLOSE_ASK
    # close_action writes go to injected store, not geometry saved[]
    assert ca_writes[:3] == [CLOSE_TRAY, CLOSE_EXIT, CLOSE_ASK]

    lifecycle.handle_tray_command(CMD_QUIT)
    assert lifecycle.quitting is True
    tray.stop.assert_called_once_with()
    jl_window.destroy.assert_called_once_with()
    window.destroy.assert_called_once_with()


def test_begin_quit_destroys_all_cf_windows():
    """
    CD-118a-4b: the quit path must destroy EVERY window in cf_windows, not just
    the first key — the exact failure shape that produced the 0.9.9 zombie
    process (a window left un-destroyed keeps pywebview's instance count > 0).

    mutation: make _begin_quit() only destroy the first window in cf_windows
    → this test must go red (win_b/win_c would never see destroy() called).
    """
    window = MagicMock()
    win_a = MagicMock()
    win_b = MagicMock()
    win_c = MagicMock()
    lc = DesktopLifecycle(
        window, {'a': win_a, 'b': win_b, 'c': win_c},
        {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
        lambda v: None,
    )

    lc._begin_quit()

    win_a.destroy.assert_called_once_with()
    win_b.destroy.assert_called_once_with()
    win_c.destroy.assert_called_once_with()


def test_register_cf_windows_adds_late_built_windows_and_quit_destroys_them():
    """168e-T13：連線頁「重試」補建的驗證視窗登記進來後，托盤「結束」也要銷毀它們
    （沒登記＝殼行程殘留）。None 值（建窗失敗）不登記；既有視窗不被覆蓋。"""
    early = MagicMock()
    late_a, late_b = MagicMock(), MagicMock()
    lc = DesktopLifecycle(
        MagicMock(), {'javlibrary': early},
        {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
        lambda v: None,
    )
    lc.register_cf_windows({'fc-javten': late_a, 'extra': late_b, 'none-site': None})
    assert 'none-site' not in lc.cf_windows and lc.cf_windows['javlibrary'] is early

    lc._begin_quit()

    for win in (early, late_a, late_b):
        win.destroy.assert_called_once_with()


def _bare_lifecycle():
    return DesktopLifecycle(
        MagicMock(), {},
        {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
        lambda v: None,
    )


def test_dialog_result_mapping():
    assert _map_dialog_result(CMD_CONFIRM, CMD_CLOSE_TRAY, True) == CloseDecision(CLOSE_TRAY, True)
    assert _map_dialog_result(CMD_CONFIRM, CMD_CLOSE_EXIT, False) == CloseDecision(CLOSE_EXIT, False)
    assert _map_dialog_result(IDCANCEL, CMD_CLOSE_TRAY, True) == CloseDecision(CLOSE_CANCEL, False)
    assert _map_dialog_result(CMD_CONFIRM, 9999, True) == CloseDecision(CLOSE_CANCEL, False)


@pytest.mark.parametrize("locale", ["en"])
def test_desktop_texts_are_complete_for_every_supported_locale(monkeypatch, locale):
    monkeypatch.setattr("core.client_settings.tray_locale", lambda: locale)

    texts = load_desktop_texts()

    assert texts.locale == locale
    for name, value in vars(texts).items():
        if name != "locale":
            assert value
            assert not value.startswith("[desktop.")


def test_unavailable_tray_remembered_downgrades_to_prompt_exit(desktop):
    """Remembered CLOSE_TRAY with tray unavailable must downgrade to prompt; exit path works."""
    lifecycle, window, _jl_window, _tray, _saved, ca_store, _ca_writes = desktop
    ca_store["value"] = CLOSE_TRAY
    _tray.start.return_value = False
    lifecycle.start_tray()
    lifecycle.prompt = lambda: CloseDecision(CLOSE_EXIT)

    result = lifecycle.on_window_closing()
    assert result is None
    assert lifecycle.quitting is True
    window.hide.assert_not_called()


def test_unavailable_tray_picked_in_prompt_notifies_and_cancels(desktop, monkeypatch):
    """User insisting on CLOSE_TRAY in prompt while tray is unavailable → notice shown, window not hidden."""
    lifecycle, window, _jl_window, _tray, _saved, ca_store, _ca_writes = desktop
    ca_store["value"] = CLOSE_TRAY
    _tray.start.return_value = False
    lifecycle.start_tray()
    lifecycle.prompt = lambda: CloseDecision(CLOSE_TRAY)
    unavailable = MagicMock()
    monkeypatch.setattr("windows.tray.show_tray_unavailable", unavailable)

    result = lifecycle.on_window_closing()
    assert result is False
    unavailable.assert_called_once_with(window)
    window.hide.assert_not_called()


def test_native_tray_has_taskbar_created_recovery():
    """AST guard: tray.py must call RegisterWindowMessageW with 'TaskbarCreated'.

    # [lint-guard: pytest-justified] 守 Python 源碼語意（AST 掃 win32 RegisterWindowMessageW 呼叫）——
    # 非前端靜態字串守衛，永久留 pytest（CD-96a-8c / CD-96-2）。
    """
    import ast as _ast

    source = (Path(__file__).parents[2] / "windows" / "tray.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)

    def _func_name(node):
        if isinstance(node, _ast.Name):
            return node.id
        if isinstance(node, _ast.Attribute):
            return node.attr
        return None

    found = any(
        isinstance(node, _ast.Call)
        and _func_name(node.func) == "RegisterWindowMessageW"
        and node.args
        and isinstance(node.args[0], _ast.Constant)
        and node.args[0].value == "TaskbarCreated"
        for node in _ast.walk(tree)
    )
    assert found, "tray.py must call RegisterWindowMessageW('TaskbarCreated') for explorer-restart recovery"


# ---------------------------------------------------------------------------
# feature/82 T4: injected read/write close_action store tests
# ---------------------------------------------------------------------------


def test_standalone_registers_tray_on_win32():
    """AST guard: NativeTrayIcon(...) must appear inside an 'if sys.platform == win32' body."""
    import ast as _ast

    source = (Path(__file__).parents[2] / "windows" / "standalone.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)

    def _is_win32_check(test_node):
        """Return True if test_node is `sys.platform == 'win32'`."""
        if not isinstance(test_node, _ast.Compare):
            return False
        left = test_node.left
        if not (isinstance(left, _ast.Attribute) and left.attr == "platform"):
            return False
        if not (isinstance(left.value, _ast.Name) and left.value.id == "sys"):
            return False
        if len(test_node.ops) != 1 or not isinstance(test_node.ops[0], _ast.Eq):
            return False
        if len(test_node.comparators) != 1:
            return False
        comp = test_node.comparators[0]
        return isinstance(comp, _ast.Constant) and comp.value == "win32"

    def _func_name(node):
        if isinstance(node, _ast.Name):
            return node.id
        if isinstance(node, _ast.Attribute):
            return node.attr
        return None

    found = False
    for node in _ast.walk(tree):
        if isinstance(node, _ast.If) and _is_win32_check(node.test):
            # Walk the body of this if-node for a NativeTrayIcon(...) call
            for child in _ast.walk(node):
                if (
                    isinstance(child, _ast.Call)
                    and _func_name(child.func) == "NativeTrayIcon"
                ):
                    found = True
                    break
        if found:
            break

    assert found, "standalone.py must instantiate NativeTrayIcon(...) inside 'if sys.platform == win32'"


# ---------------------------------------------------------------------------
# T2 regression tests: on_quit_cleanup DI
# ---------------------------------------------------------------------------

def _make_lifecycle_with_cleanup(cleanup_cb):
    """Build a DesktopLifecycle with a mock tray + cleanup callback."""
    window = MagicMock()
    jl_window = MagicMock()
    tray = MagicMock()
    state = {"close_action": CLOSE_ASK}
    lc = DesktopLifecycle(
        window, {'javlibrary': jl_window}, state,
        lambda value: None,
        on_quit_cleanup=cleanup_cb,
    )
    lc.attach_tray(tray)
    tray.start.return_value = True
    lc.start_tray()
    return lc, window, jl_window, tray


def test_begin_quit_invokes_quit_cleanup():
    """on_quit_cleanup must be called exactly once when _begin_quit() runs."""
    cleanup = MagicMock()
    lc, _, _, _ = _make_lifecycle_with_cleanup(cleanup)
    lc._begin_quit()
    cleanup.assert_called_once_with()


def test_minimize_path_does_not_run_cleanup():
    """close_action=='tray' (minimize) must NOT invoke the cleanup callback."""
    cleanup = MagicMock()
    lc, _, _, _ = _make_lifecycle_with_cleanup(cleanup)
    lc.tray_available = True  # simulate tray running
    lc.state["close_action"] = CLOSE_TRAY
    lc.on_window_closing()
    cleanup.assert_not_called()


# ---------------------------------------------------------------------------
# P1 regression: set_close_action / on_window_closing best-effort persistence
# ---------------------------------------------------------------------------


def test_on_window_closing_remember_best_effort_with_raising_write():
    """on_window_closing() must NOT raise when remember=True and write_close_action raises;
    returns False (hides window), AND the session-local value survives for this session."""
    def _raising_write(action):
        raise RuntimeError("sync-software lock")

    window = MagicMock()
    lc = DesktopLifecycle(
        window, {'javlibrary': MagicMock()},
        {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
        lambda v: None,
        read_close_action=lambda: CLOSE_ASK,
        write_close_action=_raising_write,
    )
    lc.prompt = lambda: CloseDecision(CLOSE_TRAY, remember=True)
    lc.tray_available = True

    result = lc.on_window_closing()
    # Must not raise; window is hidden (returns False) and write failure is swallowed
    assert result is False
    window.hide.assert_called_once_with()
    # Session-local fallback: preference change must survive for the rest of this session
    assert lc.get_close_action() == CLOSE_TRAY


def test_successful_write_does_not_shadow_external_config_change():
    """A successful set_close_action must pop any session-local override so that a later
    external Settings change (PUT /api/config) is visible via get_close_action (no shadow)."""
    store = {"value": CLOSE_ASK}

    window = MagicMock()
    lc = DesktopLifecycle(
        window, {'javlibrary': MagicMock()},
        {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
        lambda v: None,
        read_close_action=lambda: store["value"],
        write_close_action=lambda a: store.__setitem__("value", a),
    )

    # Successful write: set to CLOSE_TRAY
    lc.set_close_action(CLOSE_TRAY)
    assert store["value"] == CLOSE_TRAY
    assert "close_action" not in lc.state  # override was popped — config is authoritative

    # External Settings change (e.g. PUT /api/config while app runs)
    store["value"] = CLOSE_EXIT

    # get_close_action must see the external change (NOT a stale self.state value)
    assert lc.get_close_action() == CLOSE_EXIT
