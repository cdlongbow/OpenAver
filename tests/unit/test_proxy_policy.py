"""core/proxy_policy.py — 單一代理選擇點（TASK-163a-T1 / CD-163a-1）。"""
from unittest.mock import patch

import pytest

from core.image_host_policy import is_metatube_relay_url
from core.metatube.state import metatube_state
from core.proxy_policy import (
    ProxySettings,
    new_session,
    proxy_for,
    proxy_kwargs,
    settings_from_config,
)

PROXY = 'http://jp.example:8080'
RELAY = 'http://127.0.0.1:8900/v1/images/primary/ABC-123?url=https%3A%2F%2Fcdn.example.com%2Fa.jpg'
PLAIN_IMG = 'https://pics.dmm.co.jp/a.jpg'


def _s(scope, url=PROXY):
    return ProxySettings(url=url, scope=scope)


@pytest.fixture
def metatube_connected():
    metatube_state.connect('http://127.0.0.1:8900', '', [])
    try:
        yield
    finally:
        metatube_state.disconnect()


# conn, source_id, url, settings, expected
MATRIX = [
    # 空位址（含純空白）→ 任何連線皆 None
    ('source_query', 'dmm', None, _s('all', ''), None),
    ('source_query', 'dmm', None, _s('all', '   '), None),
    ('image', None, PLAIN_IMG, _s('all', ''), None),
    ('actress', None, None, _s('all', ' '), None),
    # source_query：dmm 兩種 scope 都走；javbus 只有 all
    ('source_query', 'dmm', None, _s('dmm'), PROXY),
    ('source_query', 'dmm', None, _s('all'), PROXY),
    ('source_query', 'javbus', None, _s('dmm'), None),
    ('source_query', 'javbus', None, _s('all'), PROXY),
    # image / actress：只有 all
    ('image', None, PLAIN_IMG, _s('dmm'), None),
    ('image', None, PLAIN_IMG, _s('all'), PROXY),
    ('actress', None, None, _s('dmm'), None),
    ('actress', None, None, _s('all'), PROXY),
    # metatube 中轉圖：永遠不走
    ('image', None, RELAY, _s('all'), None),
    ('image', None, RELAY, _s('dmm'), None),
]


@pytest.mark.parametrize('conn,source_id,url,settings,expected', MATRIX)
def test_proxy_for_matrix(metatube_connected, conn, source_id, url, settings, expected):
    assert proxy_for(conn, source_id=source_id, url=url, settings=settings) == expected


def test_relay_exception_only_when_metatube_connected():
    # 未連線 → 同一個 URL 不是中轉，scope=all 照走代理
    metatube_state.disconnect()
    assert proxy_for('image', url=RELAY, settings=_s('all')) == PROXY


def test_snapshot_beats_live_config():
    live = {'search': {'proxy_url': 'http://live.example:1', 'proxy_scope': 'all'}}
    with patch('core.config.load_config', return_value=live):
        # settings=A 對 live B → A
        assert proxy_for('source_query', source_id='dmm', settings=_s('dmm')) == PROXY
        # 未帶 settings → 讀 live
        assert proxy_for('source_query', source_id='dmm') == 'http://live.example:1'
    # 帶 settings= 的路徑一次 load_config 都不准碰
    with patch('core.config.load_config', side_effect=AssertionError('read live')):
        assert proxy_for('image', url=PLAIN_IMG, settings=_s('all')) == PROXY
        assert proxy_kwargs('actress', settings=_s('all'))['proxies']['https'] == PROXY
        assert new_session('dmm', settings=_s('dmm')) is not None


def test_new_session_applies_selected_proxy_per_request(monkeypatch):
    # 隔離環境代理：開發機設了 HTTP(S)_PROXY／ALL_PROXY 不應影響結果
    for var in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    captured = {}

    def fake_send(self, request, **kw):
        captured.update(kw)
        raise RuntimeError('stop')

    import requests
    with patch.object(requests.Session, 'send', fake_send):
        for sid, scope, caller, want in [
            ('dmm', 'dmm', None, {'http': PROXY, 'https': PROXY}),
            ('javbus', 'dmm', None, None),
            ('dmm', 'dmm', {'http': 'x', 'https': 'x'}, {'http': 'x', 'https': 'x'}),
        ]:
            captured.clear()
            sess = new_session(sid, settings=_s(scope))
            kw = {'proxies': caller} if caller else {}
            with pytest.raises(RuntimeError):
                sess.get('http://example.invalid/', **kw)
            if want is None:
                assert captured.get('proxies') in (None, {})
            else:
                got = captured['proxies']
                assert (got['http'], got['https']) == (want['http'], want['https'])


@pytest.mark.parametrize('config,expected', [
    ({}, ('', 'dmm')),
    ({'search': {'proxy_url': ' http://p:1 '}}, ('http://p:1', 'dmm')),  # 舊 config 無 proxy_scope
    ({'search': {'proxy_url': 'http://p:1', 'proxy_scope': 'all'}}, ('http://p:1', 'all')),
    ({'search': {'proxy_url': 'http://p:1', 'proxy_scope': 'bogus'}}, ('http://p:1', 'dmm')),
    ({'search': {'proxy_url': None}}, ('', 'dmm')),
])
def test_settings_from_config(config, expected):
    s = settings_from_config(config)
    assert (s.url, s.scope) == expected


@pytest.mark.parametrize('url,connected,expected', [
    ('http://127.0.0.1:8900/v1/images/primary/ABC-123', True, True),
    ('http://127.0.0.1:8900/other/path', True, False),   # 同主機非 images 路徑
    ('http://127.0.0.1:9999/v1/images/primary/ABC-123', True, False),  # port 不符
    ('https://127.0.0.1:8900/v1/images/primary/ABC-123', True, False),  # scheme 不符
    ('http://other.example:8900/v1/images/primary/ABC-123', True, False),  # host 不符
    ('http://127.0.0.1:8900/v1/images/primary/ABC-123', False, False),  # 未連線
    ('http://127.0.0.1:abc/v1/images/x', True, False),  # 畸形 port 不 raise
])
def test_metatube_relay_judgement(url, connected, expected):
    metatube_state.disconnect()
    if connected:
        metatube_state.connect('http://127.0.0.1:8900', '', [])
    try:
        assert is_metatube_relay_url(url) is expected
    finally:
        metatube_state.disconnect()


@pytest.mark.parametrize('raw,expected', [
    ('localhost:7890', 'http://localhost:7890'),
    ('127.0.0.1:7890', 'http://127.0.0.1:7890'),
    (' 127.0.0.1:7890 ', 'http://127.0.0.1:7890'),
    ('http://h:1', 'http://h:1'),
    ('socks5://h:1', 'socks5://h:1'),
    ('', ''),
])
def test_schemeless_address_is_http_for_every_consumer(raw, expected):
    s = _s('all', raw)
    assert s.url == expected
    assert proxy_kwargs('source_query', source_id='javdb', settings=s).get('proxies', {}).get('https', '') == expected
    assert settings_from_config({'search': {'proxy_url': raw, 'proxy_scope': 'all'}}).url == expected


# ---- 168d-T1：client_cf_settings／cf_window_proxy_fingerprint／is_remote_origin ----

from core.proxy_policy import (  # noqa: E402
    CfWindowProxy,
    cf_window_proxy_fingerprint,
    client_cf_settings,
    is_remote_origin,
)


@pytest.mark.parametrize("remote,url,direct", [
    (True, 'http://127.0.0.1:7890', True),
    (True, 'http://127.0.0.2:7890', True),
    (True, 'http://localhost:7890', True),
    (True, 'socks5://[::1]:1080', True),
    (True, 'http://[::ffff:127.0.0.1]:7890', True),
    (True, 'http://192.168.1.5:7890', False),
    (True, 'http://proxy.example:7890', False),
    (True, '', False),
    (True, 'http://[bad:1', False),
    (False, 'http://127.0.0.1:7890', False),     # 本機模式：不轉直連
    (False, 'http://192.168.1.5:7890', False),
])
def test_client_cf_settings_truth_table(remote, url, direct):
    s = ProxySettings(url=url, scope='all')
    out, local_direct = client_cf_settings(s, remote)
    assert local_direct is direct
    if direct:
        assert out.url == '' and out.scope == 'all'
    else:
        assert out is s


@pytest.mark.parametrize("origin,remote", [
    ('http://127.0.0.1:8000', False),
    ('http://localhost:8000', False),
    ('http://[::1]:8000', False),
    ('http://[::ffff:127.0.0.1]:8000', False),
    ('http://192.168.1.190:8765', True),
    ('https://nas.example.com', True),
    ('', False),
    ('http://[bad:1', False),
])
def test_is_remote_origin(origin, remote):
    assert is_remote_origin(origin) is remote


def _fp_spec(**kw):
    base = dict(server='http://h:1', username='u', password='secret', usable=True)
    base.update(kw)
    return CfWindowProxy(**base)


def test_fingerprint_none_and_equality_and_no_plaintext():
    assert cf_window_proxy_fingerprint(None) is None
    fp = cf_window_proxy_fingerprint(_fp_spec())
    assert fp == cf_window_proxy_fingerprint(_fp_spec())
    assert 'secret' not in fp and 'h:1' not in fp and 'u' != fp


@pytest.mark.parametrize("change", [
    dict(server='http://h:2'), dict(username='v'), dict(password='other'), dict(usable=False),
    dict(username=None), dict(password=None),
])
def test_fingerprint_differs_on_any_field(change):
    assert cf_window_proxy_fingerprint(_fp_spec(**change)) != cf_window_proxy_fingerprint(_fp_spec())
