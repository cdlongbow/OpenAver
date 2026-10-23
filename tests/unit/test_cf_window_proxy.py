"""TASK-163b-T7a A1：驗證視窗的代理規格（core 層，純 Linux 可測）。"""
import pytest

from core import proxy_policy
from core.proxy_policy import (
    CfWindowProxy,
    ProxySettings,
    cf_window_proxy,
    cf_window_proxy_restart_needed,
)


def _spec(server, username=None, password=None, usable=True):
    return CfWindowProxy(server=server, username=username, password=password, usable=usable)


# (url, scope, expected)
_TABLE = [
    ('http://h:1', 'all', _spec('http://h:1')),
    ('https://u:p%40ss@h:3', 'all', _spec('https://h:3', 'u', 'p@ss')),
    ('socks5://u:p@h:6', 'all', _spec('socks5://h:6', 'u', 'p', usable=False)),
    # 無法解析：fail-closed，server 為空字串、usable=False
    ('127.0.0.1:7890', 'all', _spec('http://127.0.0.1:7890')),
    ('h', 'all', _spec('', usable=False)),  # 無 scheme 也無 port：不猜 80
    # 沒被選到
    ('http://h:1', 'dmm', None),
    ('', 'all', None),
]


@pytest.mark.parametrize('url,scope,expected', _TABLE)
def test_cf_window_proxy_scope_and_credentials_table(url, scope, expected):
    got = cf_window_proxy(ProxySettings(url=url, scope=scope))
    assert got == expected
    if got is not None:
        assert '@' not in got.server
        assert 'p%40ss' not in got.server and 'p@ss' not in got.server


def test_cf_window_proxy_repr_hides_credentials():
    got = cf_window_proxy(ProxySettings(url='https://zeduser:secretpw@h:1', scope='all'))
    assert 'secretpw' not in repr(got)
    assert 'zeduser' not in repr(got)


@pytest.fixture
def windows_desktop(monkeypatch):
    monkeypatch.setattr(proxy_policy, 'desktop_kind', lambda: 'windows')


def _set_state(monkeypatch, start, url, scope):
    monkeypatch.setattr(proxy_policy, '_cf_window_proxy_at_start', start)
    monkeypatch.setattr(proxy_policy, 'current_settings',
                        lambda: ProxySettings(url=url, scope=scope))


def test_restart_needed_follows_effective_spec(monkeypatch, windows_desktop):
    # ① 啟動時沒套用，現在存成「所有來源＋位址」
    _set_state(monkeypatch, None, 'http://h:1', 'all')
    assert cf_window_proxy_restart_needed() is True
    # ② 啟動時套用 X，存成同一個位址（先改別的再改回也是同一個有效規格）
    x = cf_window_proxy(ProxySettings(url='http://h:1', scope='all'))
    _set_state(monkeypatch, x, 'http://other:9', 'all')
    assert cf_window_proxy_restart_needed() is True
    _set_state(monkeypatch, x, 'http://h:1', 'all')
    assert cf_window_proxy_restart_needed() is False
    # ③ 「僅 DMM」與「欄位空白」之間切換：有效規格都是 None
    _set_state(monkeypatch, None, 'http://h:1', 'dmm')
    assert cf_window_proxy_restart_needed() is False
    _set_state(monkeypatch, None, '', 'all')
    assert cf_window_proxy_restart_needed() is False
    # 啟動時套用 X，之後改成「僅 DMM」→ 要重開才會移除
    _set_state(monkeypatch, x, 'http://h:1', 'dmm')
    assert cf_window_proxy_restart_needed() is True


