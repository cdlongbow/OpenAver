# [lint-guard: pytest-justified]  AST 源碼語意（殼接線形狀）＋ lifecycle 接線
"""TASK-168a-T6: launcher / standalone 的載入網址、信任 origin、bridge 派送、關閉行為接線。"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = REPO_ROOT / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

SHELL_FILES = ["launcher.py", "standalone.py"]


def _tree(name):
    path = WINDOWS_DIR / name
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _attr_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _main_create_window(tree):
    """以第一個位置參數字面 'OpenAver' 辨識主視窗（不看順序）。"""
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and _attr_chain(node.func) == "webview.create_window"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "OpenAver"):
            found.append(node)
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("name", SHELL_FILES)
def test_shells_load_url_and_trusted_origin_share_one_source(name):
    tree = _tree(name)
    cw = _main_create_window(tree)
    url = cw.args[1]
    assert isinstance(url, ast.Call) and _attr_chain(url.func) == "client_settings.shell_entry_url"
    origin_var = url.args[0]
    assert isinstance(origin_var, ast.Name)

    trusted = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _attr_chain(node.func) == "api._set_trusted_origin":
            arg = node.args[0]
            if (isinstance(arg, ast.Call) and _attr_chain(arg.func) == "client_settings.server_origin"
                    and isinstance(arg.args[0], ast.Name) and arg.args[0].id == origin_var.id):
                trusted.append(node)
    assert len(trusted) == 1
    assert trusted[0].lineno < cw.lineno


@pytest.mark.parametrize("name", SHELL_FILES)
def test_shells_pass_no_js_api_and_expose_whitelist(name):
    tree = _tree(name)
    cw = _main_create_window(tree)

    js_api_values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "js_api":
            js_api_values.append(node.value)
    assert js_api_values, "js_api=None 必須明寫"
    assert all(isinstance(v, ast.Constant) and v.value is None for v in js_api_values)

    expose = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _attr_chain(n.func) == "window.expose"
        and len(n.args) == 1 and isinstance(n.args[0], ast.Starred)
        and isinstance(n.args[0].value, ast.Call)
        and _attr_chain(n.args[0].value.func) == "pywebview_api.exposed_functions"
    ]
    assert len(expose) == 1
    assert expose[0].lineno > cw.lineno


def test_lifecycle_close_action_wired_to_client_settings(monkeypatch):
    import standalone

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

    class FakeTray:
        def __init__(self, *args, **kwargs):
            pass

    written = []
    monkeypatch.setattr(standalone.sys, "platform", "win32")
    monkeypatch.setattr(standalone, "DesktopLifecycle", FakeLifecycle)
    monkeypatch.setattr(standalone, "NativeTrayIcon", FakeTray)
    monkeypatch.setattr("core.client_settings.close_action", lambda: "tray")
    monkeypatch.setattr("core.client_settings.set_close_action", lambda a: written.append(a))

    class _LL:
        def shutdown(self):
            pass

    standalone._setup_windows_lifecycle(object(), None, None, {}, _LL())

    assert captured["read_close_action"]() == "tray"
    captured["write_close_action"]("exit")
    assert written == ["exit"]


def test_local_mode_entry_url_golden(monkeypatch, tmp_path):
    from core import client_settings
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    assert (client_settings.shell_entry_url("http://127.0.0.1:49152", "windows")
            == "http://127.0.0.1:49152/?oa_shell=windows&oa_mode=local")
    assert client_settings.server_origin("http://127.0.0.1:49152") == "http://127.0.0.1:49152"


def test_client_mode_entry_url_and_trusted_origin_same_origin(monkeypatch, tmp_path):
    from core import client_settings
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    client_settings.save_client_settings(
        {"version": 1, "server": {"url": "http://192.168.1.180:8000", "token": ""}})
    local = "http://localhost:8000"
    assert client_settings.server_origin(local) == "http://192.168.1.180:8000"
    assert client_settings.shell_entry_url(local, "mac") == "http://192.168.1.180:8000/?oa_shell=mac&oa_mode=client"
