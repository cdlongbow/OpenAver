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


def test_window_set_reports_proxy_spec_and_ok(env, monkeypatch):
    spec = CfWindowProxy(server='http://127.0.0.1:7890', username=None, password=None, usable=True)
    monkeypatch.setattr(cf_windows, 'cf_window_proxy', lambda s: spec)
    ws = cf_windows.build_cf_windows(_Logger(), 's')
    assert ws.proxy_spec == spec and ws.proxy_ok is True
    monkeypatch.setattr(cf_windows, 'install_webview2_proxy', lambda *a, **k: False)
    ws = cf_windows.build_cf_windows(_Logger(), 's')
    assert ws.proxy_ok is False and ws.jl_win is None and ws.javten_win is None
    assert ws.transport.available_sites() == []


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


# ---- 168e-T15 E44：驗證視窗標題跟隨托盤語系 ----

def _fake_en_titles(monkeypatch):
    import core.i18n as i18n
    real = i18n.load_locale
    monkeypatch.setattr(i18n, "load_locale", lambda lang: (
        {"desktop": {"cf_window": {"jl_title": "EN-JL", "javten_title": "EN-JT"}}}
        if lang == "en" else real(lang)))


@pytest.mark.parametrize('loc', ['en'])
def test_cf_window_titles_and_title_to_key_are_same_strings(env, monkeypatch, loc):
    from core import client_settings
    _fake_en_titles(monkeypatch)
    monkeypatch.setattr(client_settings, 'tray_locale', lambda: loc)
    seen = {}

    def _install(proxy, udf_root, title_to_key, holder):
        seen['map'] = dict(title_to_key)
        return True

    created = []

    class _WV:
        def create_window(self, title, url, **kw):
            created.append((title, kw))
            return _Win(title, url)

    monkeypatch.setattr(cf_windows, 'install_webview2_proxy', _install)
    monkeypatch.setattr(cf_windows, 'webview', _WV())
    cf_windows.build_cf_windows(_Logger(), 's')
    assert [t for t, _ in created] == [k for k in seen['map']]
    assert seen['map'][created[0][0]] == 'javlibrary' and seen['map'][created[1][0]] == 'fc-javten'
    if loc == 'en':
        assert [t for t, _ in created] == ['EN-JL', 'EN-JT']
    assert created[0][1] == {'width': 1200, 'height': 820, 'hidden': True}
    assert 'focus' not in created[1][1]
