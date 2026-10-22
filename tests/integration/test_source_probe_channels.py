"""八家內建來源的「測試連線」通道真實性（TASK-163b-T2）。

兩種 oracle，皆不打外站（BE-TEST-43）：
  1. recording proxy（真 TCP）：A＝請求體代理、B＝已儲存設定的代理、SYS＝系統代理。
     recorder 收到的 host 集合就是證據。
  2. 罐頭 adapter：patch 類別層 HTTPAdapter.send（Session 與 module-level requests.get/post
     都會經過），依 URL 回不同的狀態碼／header／body；未知 URL 一律 ConnectionError（fail closed）。
"""
import io
import json
import re
from urllib.parse import urlparse

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from tests.integration._recording_proxy import (
    clear_proxy_env, set_system_proxy, start_recording_proxy, write_search_config,
)

BUILTIN = ('dmm', 'javbus', 'jav321', 'javdb', 'd2pass', 'heyzo', 'fc2', 'avsox')
QUERY_HOSTS = {
    'api.video.dmm.co.jp', 'www.javbus.com', 'www.jav321.com', 'jdforrepam.com', 'javdb.com',
    'www.1pondo.tv', 'www.caribbeancom.com', 'www.10musume.com', 'en.heyzo.com',
    'adult.contents.fc2.com', 'avsox.click', 'avsox.monster', 'avsox.website',
}
HOSTS_OF = {
    'dmm': {'api.video.dmm.co.jp'}, 'javbus': {'www.javbus.com'}, 'jav321': {'www.jav321.com'},
    'javdb': {'jdforrepam.com', 'javdb.com'},
    'd2pass': {'www.1pondo.tv', 'www.caribbeancom.com', 'www.10musume.com'},
    'heyzo': {'en.heyzo.com'}, 'fc2': {'adult.contents.fc2.com'},
    'avsox': {'avsox.click', 'avsox.monster', 'avsox.website'},
}
OK_ENVELOPE = json.dumps({'success': 1, 'data': {}}).encode()


# ── recording proxy：host 集合是 oracle ──────────────────────────────────────

@pytest.fixture
def rec(monkeypatch):
    """A／B／SYS 三個 recorder；系統代理指向 SYS。"""
    clear_proxy_env(monkeypatch)
    a_url, a_hosts, a_stop = start_recording_proxy()
    b_url, b_hosts, b_stop = start_recording_proxy()
    s_url, s_hosts, s_stop = start_recording_proxy()
    set_system_proxy(monkeypatch, s_url)

    class _R:
        a, b, sys = a_url, b_url, s_url
        a_hosts_ = staticmethod(a_hosts)
        b_hosts_ = staticmethod(b_hosts)
        sys_hosts_ = staticmethod(s_hosts)

    try:
        yield _R
    finally:
        a_stop()
        b_stop()
        s_stop()


def _probe(client, proxy_url, scope, ids=BUILTIN):
    resp = client.post('/api/sources/probe', json={
        'proxy_url': proxy_url, 'proxy_scope': scope, 'source_ids': list(ids)})
    assert resp.status_code == 200
    return resp.json()['results']


def test_scope_all_probes_every_query_host_via_snapshot_proxy(client, rec):
    """所有來源＋請求體代理 A：只有十三個查詢 host 走 A；系統代理一筆都沒有，沒有圖床。"""
    _probe(client, rec.a, 'all')
    assert rec.a_hosts_() == QUERY_HOSTS, rec.a_hosts_() ^ QUERY_HOSTS
    assert rec.sys_hosts_() == set(), rec.sys_hosts_()
    assert rec.b_hosts_() == set()


def test_probe_uses_request_snapshot_not_saved_settings(client, rec):
    """已儲存的是代理 B、畫面上改成 A 就按測試：連線全到 A，B 一筆都沒有。"""
    write_search_config(proxy_url=rec.b, scope='all')
    _probe(client, rec.a, 'all')
    assert rec.a_hosts_() == QUERY_HOSTS, rec.a_hosts_() ^ QUERY_HOSTS
    assert rec.b_hosts_() == set(), rec.b_hosts_()
    assert rec.sys_hosts_() == set(), rec.sys_hosts_()


def test_scope_dmm_only_dmm_host_reaches_snapshot_proxy(client, rec):
    """僅 DMM：A 只收到 DMM；另外十二個 host 全部落在系統代理（證明它們真的有被發出去）。"""
    write_search_config(proxy_url=rec.b, scope='all')
    _probe(client, rec.a, 'dmm')
    assert rec.a_hosts_() == {'api.video.dmm.co.jp'}, rec.a_hosts_()
    assert rec.sys_hosts_() == QUERY_HOSTS - {'api.video.dmm.co.jp'}, rec.sys_hosts_()
    assert rec.b_hosts_() == set()


def test_blank_proxy_everything_goes_to_system_proxy(client, rec):
    """請求體代理空白：A 一筆都沒有，十三個查詢 host 全照系統代理。"""
    write_search_config(proxy_url=rec.b, scope='all')
    _probe(client, '', 'all')
    assert rec.a_hosts_() == set() and rec.b_hosts_() == set()
    assert rec.sys_hosts_() == QUERY_HOSTS, rec.sys_hosts_() ^ QUERY_HOSTS


# ── 罐頭 adapter ─────────────────────────────────────────────────────────────

class Canned:
    def __init__(self):
        self.responder = None
        self.seen = []

    def by_host(self, default=(200, {}, OK_ENVELOPE), **per_host):
        """per_host 的 key 用 host（'.' 以 '__' 代替）；值是 (status, headers, body) 或例外。"""
        table = {k.replace('__', '.'): v for k, v in per_host.items()}

        def _responder(request):
            return table.get(urlparse(request.url).hostname, default)

        self.responder = _responder

    def requests_to(self, host):
        return [r for r in self.seen if urlparse(r.url).hostname == host]


@pytest.fixture
def canned(monkeypatch):
    clear_proxy_env(monkeypatch)
    c = Canned()

    def fake_send(self, request, **kw):
        c.seen.append(request)
        out = c.responder(request) if c.responder else None
        if out is None:
            raise requests.exceptions.ConnectionError('unknown url')
        if isinstance(out, BaseException):
            raise out
        status, headers, body = out
        r = requests.Response()
        r.status_code = status
        r.headers = CaseInsensitiveDict(headers)
        r.raw = io.BytesIO(body)
        r.url = request.url
        r.request = request
        return r

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', fake_send)
    return c


def _one(client, sid):
    return _probe(client, '', 'dmm', [sid])[sid]


# ── 合併語意、D2Pass 站點、請求身分 ──────────────────────────────────────────

def test_d2pass_caribbeancom_probes_www_not_b_json(client, canned):
    canned.by_host()
    _one(client, 'd2pass')
    assert {urlparse(r.url).hostname for r in canned.seen} == HOSTS_OF['d2pass']
    carib = canned.requests_to('www.caribbeancom.com')
    assert [urlparse(r.url).path.endswith('/index.html') for r in carib] == [True]


def test_probe_requests_carry_the_real_search_identity(client, canned):
    canned.by_host()
    _probe(client, '', 'dmm', BUILTIN)

    sig = canned.requests_to('jdforrepam.com')[0].headers
    assert re.fullmatch(r'\d+\.\w+\.[0-9a-f]{32}', sig['jdsignature'])
    assert sig['user-agent'].startswith('Dart/3.4')
    assert 'Version/17.5 Safari' in canned.requests_to('www.javbus.com')[0].headers['User-Agent']
    assert canned.requests_to('www.10musume.com')[0].headers['Referer'] == 'https://www.1pondo.tv/'

    dmm = canned.requests_to('api.video.dmm.co.jp')[0]
    assert dmm.method == 'POST'
    assert 'application/json' in dmm.headers['Content-Type']
    assert b'__typename' in dmm.body

    j321 = canned.requests_to('www.jav321.com')[0]
    assert j321.method == 'POST' and 'sn=' in j321.body


# ── JavLibrary／FC2-javten（驗證視窗來源）────────────────────────────────────

VERIFIER = ('javlibrary', 'fc-javten')
VERIFIER_HOSTS = {'www.javlibrary.com', 'javten.com'}


class _Sites:
    def __init__(self, sites):
        self._sites = list(sites)

    def available_sites(self):
        return list(self._sites)


@pytest.fixture
def verifier_env(monkeypatch):
    """造桌面種類與視窗可用清單；結束還原 core.cf_transport 模組全域。"""
    import core.cf_transport as cft
    saved = cft._transport

    def _set(kind, sites=VERIFIER):
        monkeypatch.setattr('core.source_probe.desktop_kind', lambda: kind)
        cft._transport = _Sites(sites)

    try:
        yield _set
    finally:
        cft._transport = saved


def _vrow(client, sid, proxy_url='', scope='all'):
    return _probe(client, proxy_url, scope, [sid])[sid]


def test_verifier_probe_uses_search_route(client, rec, verifier_env):
    """Windows 視窗可用：所有來源＋請求體代理 A → 兩家 host 在 A；僅 DMM → 改走系統代理。"""
    verifier_env('windows')
    _probe(client, rec.a, 'all', VERIFIER)
    assert rec.a_hosts_() == VERIFIER_HOSTS, rec.a_hosts_()
    assert rec.sys_hosts_() == set() and rec.b_hosts_() == set()


def test_verifier_probe_scope_dmm_goes_system_proxy_not_snapshot_proxy(client, rec, verifier_env):
    verifier_env('windows')
    _probe(client, rec.a, 'dmm', VERIFIER)
    assert rec.a_hosts_() == set(), rec.a_hosts_()
    assert rec.sys_hosts_() == VERIFIER_HOSTS, rec.sys_hosts_()


def test_verifier_probe_mac_has_zero_connections(client, rec, verifier_env):
    """macOS 即使 transport 已註冊且兩家都列在可用清單：不連線、標未測。"""
    verifier_env('mac')
    results = _probe(client, rec.a, 'all', VERIFIER)
    assert {(r['state'], r['reason']) for r in results.values()} == {('skipped', 'mac_system_proxy')}
    assert rec.a_hosts_() == set() and rec.sys_hosts_() == set() and rec.b_hosts_() == set()


def test_verifier_probe_dev_env_is_skipped_windows_verifier(client, canned):
    canned.responder = None
    results = _probe(client, '', 'all', VERIFIER)
    assert {(r['state'], r['reason']) for r in results.values()} == {('skipped', 'windows_verifier')}
    assert canned.seen == []


def test_verifier_probe_auth_socks_is_skipped_without_connection(client, canned, verifier_env):
    verifier_env('windows')
    canned.by_host()
    results = _probe(client, 'socks5://u:p@h.example:1', 'all', VERIFIER)
    assert {(r['state'], r['reason']) for r in results.values()} == {('skipped', 'proxy_auth_unsupported')}
    assert canned.seen == []


def test_verifier_probe_unparseable_address_is_probed_not_auth_message(client, canned, verifier_env):
    """位址少打 scheme：不說「不支援帶帳密 socks5」，照常實測（和其他八家一樣由連線結果決定）。"""
    verifier_env('windows')
    canned.by_host()
    row = _vrow(client, 'javlibrary', 'h.example:1', 'all')
    assert row['state'] != 'skipped' and row['reason'] != 'proxy_auth_unsupported'
    assert canned.requests_to('www.javlibrary.com')
