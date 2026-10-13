"""168d-T3：windows/cf_windows.py（CfWindowSet／attach_close_guards／cf_shell_supported，純 Linux 全假物件）。

build_cf_windows 的逐行等價由 test_webview2_proxy.py 的接線段負責；這裡只守 168d 新增的部分。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = str(REPO_ROOT / 'windows')
if WINDOWS_DIR not in sys.path:
    sys.path.insert(0, WINDOWS_DIR)

import cf_windows  # noqa: E402
from core.proxy_policy import CfWindowProxy  # noqa: E402


class _Evt:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


class _Win:
    def __init__(self, title='t', url='u'):
        self.title, self.url = title, url
        self.events = types.SimpleNamespace(closing=_Evt())
        self.hidden = 0

    def hide(self):
        self.hidden += 1


class _Webview:
    def create_window(self, title, url, **kw):
        return _Win(title, url)


class _Logger:
    def info(self, *a, **k):
        pass

    warning = error = debug = info


@pytest.fixture
def env(monkeypatch, tmp_path):
    import core.cf_transport as cft

    def _boom(t):
        raise AssertionError('build_cf_windows must not register a transport')

    monkeypatch.setattr(cft, 'register_cf_transport', _boom)
    monkeypatch.setattr(cf_windows, 'webview', _Webview())
    monkeypatch.setattr(cf_windows, 'get_data_root', lambda: tmp_path)
    monkeypatch.setattr(cf_windows, 'record_cf_window_proxy_at_start', lambda spec: None)
    monkeypatch.setattr(cf_windows, 'install_webview2_proxy', lambda *a, **k: True)
    monkeypatch.setattr(cf_windows, 'desktop_kind', lambda: 'windows')
    monkeypatch.setattr(cf_windows, 'cf_window_proxy', lambda s: None)
    return types.SimpleNamespace(tmp=tmp_path)


def test_local_direct_passes_through_to_window_set(env):
    assert cf_windows.build_cf_windows(_Logger(), 's').local_direct is False
    assert cf_windows.build_cf_windows(_Logger(), 's', local_direct=True).local_direct is True


def test_window_set_reports_proxy_spec_and_ok(env, monkeypatch):
    spec = CfWindowProxy(server='http://127.0.0.1:7890', username=None, password=None, usable=True)
    monkeypatch.setattr(cf_windows, 'cf_window_proxy', lambda s: spec)
    ws = cf_windows.build_cf_windows(_Logger(), 's')
    assert ws.proxy_spec == spec and ws.proxy_ok is True
    monkeypatch.setattr(cf_windows, 'install_webview2_proxy', lambda *a, **k: False)
    ws = cf_windows.build_cf_windows(_Logger(), 's')
    assert ws.proxy_ok is False and ws.jl_win is None and ws.javten_win is None
    assert ws.transport.available_sites() == []


def test_outer_failure_returns_empty_set_without_raising(env, monkeypatch):
    import cf_transport_impl

    def boom(*a, **k):
        raise RuntimeError('x')

    monkeypatch.setattr(cf_transport_impl, 'PyWebViewCfTransport', boom)
    ws = cf_windows.build_cf_windows(_Logger(), 's')
    assert ws.transport is None
    assert ws.jl_win is not None and ws.javten_win is not None


def test_window_set_defaults_are_all_optional():
    ws = cf_windows.CfWindowSet()
    assert (ws.transport, ws.jl_win, ws.javten_win, ws.proxy_ok, ws.proxy_spec, ws.local_direct) == \
        (None, None, None, True, None, False)


def test_cf_shell_supported_reads_platform_at_call_time(monkeypatch):
    for plat, expect in (('win32', True), ('darwin', True), ('linux', False)):
        monkeypatch.setattr(sys, 'platform', plat)
        assert cf_windows.cf_shell_supported() is expect


def test_close_guards_hide_and_cancel_unless_quitting():
    ws = cf_windows.CfWindowSet(jl_win=_Win(), javten_win=_Win())
    quitting = [False]
    cf_windows.attach_close_guards(ws, lambda: quitting[0])
    for w in (ws.jl_win, ws.javten_win):
        (handler,) = w.events.closing.handlers
        assert handler() is False and w.hidden == 1
        quitting[0] = True
        assert handler() is None and w.hidden == 1
        quitting[0] = False


def test_close_guards_skip_missing_windows():
    ws = cf_windows.CfWindowSet(jl_win=None, javten_win=_Win())
    cf_windows.attach_close_guards(ws, lambda: False)
    assert len(ws.javten_win.events.closing.handlers) == 1
