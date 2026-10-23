"""core/source_probe.py — 判讀／合併／並行／預算／快照／skipped／不洩漏（TASK-163b-T1）。

全用假 scraper 類別（注入 scraper_class_for）與假 send，不打網路。
"""
import io
import json
import threading
import time

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from core import source_probe as sp
from core.proxy_policy import ProxySettings
from core.source_probe import (
    ProbeOutcome, ProbePlan, ProbeTarget, classify_exception,
    merge_outcomes, run_probes,
)

PROXY = 'http://jp.example:8080'
SIX_KEYS = {'state', 'reason', 'host', 'status', 'via_proxy', 'advice'}


def make_resp(status=200, headers=None, body=b'<html>ok</html>'):
    r = requests.Response()
    r.status_code = status
    r.headers = CaseInsensitiveDict(headers or {})
    r.raw = io.BytesIO(body)
    r.url = 'https://x.example/'
    return r


def _t(host='h.example', send=None, **kw):
    return ProbeTarget(host=host, send=send or (lambda: make_resp()), **kw)


class FakeScraper:
    """只需 __init__(config) 與 probe_plan(timeout)；不繼承 BaseScraper。"""
    plans = {}
    seen = {}
    source_id = None

    def __init__(self, config):
        type(self).seen[type(self).source_id] = config.proxy_settings

    def probe_plan(self, timeout):
        return type(self).plans.get(type(self).source_id)


@pytest.fixture
def fake_classes(monkeypatch):
    """回 (plans, seen)；scraper_class_for 依 id 回各自的假類別。"""
    plans, seen = {}, {}

    def _cls(sid):
        return type('Fake_' + sid, (FakeScraper,), {'source_id': sid, 'plans': plans, 'seen': seen})

    monkeypatch.setattr('core.source_probe.scraper_class_for', _cls)
    return plans, seen


# ------------------------------------------------------------ 判讀


def _conn_err_with(reason):
    inner = type('Inner', (Exception,), {'reason': reason})()
    return requests.exceptions.ConnectionError(inner)


@pytest.mark.parametrize('exc,expect', [
    (requests.exceptions.ProxyError('boom'), 'proxy'),
    (requests.exceptions.ConnectTimeout('t'), 'timeout'),
    (_conn_err_with(sp.NameResolutionError('h', None, 'x')), 'dns'),
])
def test_classify_exception_by_exception_type(exc, expect):
    assert classify_exception(exc) == expect


def O(state, host='h'):
    return ProbeOutcome(state, state, host, None)


@pytest.mark.parametrize('mode,states,expect_state,expect_host', [
    ('any', ['unreachable', 'blocked', 'ok'], 'ok', 'h2'),
    ('all', ['ok', 'blocked', 'unreachable'], 'unreachable', 'h2'),
])
def test_merge_outcomes_any_takes_best_all_takes_worst(mode, states, expect_state, expect_host):
    outs = [O(s, f'h{i}') for i, s in enumerate(states)]
    merged = merge_outcomes(mode, outs)
    assert (merged.state, merged.host) == (expect_state, expect_host)


# ------------------------------------------------------------ 讀取 / check


class _BrokenBody(io.BytesIO):
    def read(self, *a, **k):
        raise OSError('body broke')


def _broken_resp(status, headers=None):
    r = make_resp(status, headers)
    r.raw = _BrokenBody(b'x')
    return r


class _EndlessBody:
    """永不結束的 body，並記錄被讀了幾次。"""
    def __init__(self):
        self.reads = 0

    def read(self, n=-1, *a, **k):
        self.reads += 1
        if self.reads > 50:
            raise AssertionError('讀超過上限仍不停')
        return b'x' * 8192

    def stream(self, amt=8192, decode_content=None):
        while True:
            yield self.read(amt)

    def close(self):
        pass

    def release_conn(self):
        pass


def _run_one(fake_classes, send):
    plans, _ = fake_classes
    plans['dmm'] = ProbePlan([ProbeTarget('d.example', send)])
    return run_probes(ProxySettings(), ['dmm'])['dmm']


# ------------------------------------------------------------ 並行 / 預算


def test_run_probes_budget_bounds_response_time(fake_classes, monkeypatch):
    plans, _ = fake_classes
    monkeypatch.setattr('core.source_probe.PROBE_BUDGET_S', 1)
    gate = threading.Event()

    def slow():
        gate.wait(3)
        return make_resp()

    ids = ['dmm', 'javbus', 'jav321', 'javdb', 'd2pass', 'heyzo', 'fc2', 'avsox']
    for sid in ids:
        plans[sid] = ProbePlan([ProbeTarget(sid + '.example', slow)])
    t0 = time.monotonic()
    rows = run_probes(ProxySettings(), ids)
    assert time.monotonic() - t0 < 2
    assert set(rows) == set(ids)
    assert {(r['state'], r['reason']) for r in rows.values()} == {('unreachable', 'timeout')}


# ------------------------------------------------------------ 快照 / via_proxy / advice / skipped

def test_run_probes_gives_every_scraper_the_request_snapshot(fake_classes):
    plans, seen = fake_classes
    snap = ProxySettings(url=PROXY, scope='all')
    for sid in ('dmm', 'javbus'):
        plans[sid] = ProbePlan([ProbeTarget(sid, lambda: make_resp())])
    run_probes(snap, ['dmm', 'javbus'])
    assert seen == {'dmm': snap, 'javbus': snap}


@pytest.mark.parametrize('snap,expect', [
    (ProxySettings(url=PROXY, scope='dmm'), {'dmm': True, 'javbus': False}),
])
def test_run_probes_via_proxy_follows_policy(fake_classes, snap, expect):
    plans, _ = fake_classes
    for sid in expect:
        plans[sid] = ProbePlan([ProbeTarget(sid, lambda: make_resp())])
    rows = run_probes(snap, list(expect))
    assert {sid: rows[sid]['via_proxy'] for sid in expect} == expect


def test_run_probes_advice_only_when_blocked_and_source_needs_jp_ip(fake_classes):
    plans, _ = fake_classes
    for sid in ('dmm', 'javbus'):
        plans[sid] = ProbePlan([ProbeTarget(sid, lambda: make_resp(403))])
    plans['jav321'] = ProbePlan([ProbeTarget('jav321', lambda: make_resp())])
    plans['javdb'] = ProbePlan([ProbeTarget('javdb', lambda: (_ for _ in ()).throw(
        requests.exceptions.ConnectionError('x')))])
    plans['d2pass'] = ProbePlan([ProbeTarget('d2pass', lambda: (_ for _ in ()).throw(
        requests.exceptions.ConnectionError('x')))])
    rows = run_probes(ProxySettings(url=PROXY), ['dmm', 'javbus', 'jav321', 'javdb'])
    assert rows['dmm']['advice'] == 'jp_ip'
    assert rows['javbus']['state'] == 'blocked' and rows['javbus']['advice'] is None
    assert rows['jav321']['advice'] is None
    assert rows['javdb']['state'] == 'unreachable' and rows['javdb']['advice'] is None


def test_run_probes_skips_manual_only_and_metatube(fake_classes, monkeypatch):
    """dev／NAS（desktop_kind 為 None）：兩家驗證視窗來源恆 skipped/windows_verifier。"""
    monkeypatch.setattr('core.source_probe.desktop_kind', lambda: None)
    ids = ['javlibrary', 'fc-javten', 'metatube:x', 'zzz', 'dmm']
    rows = run_probes(ProxySettings(url=PROXY, scope='all'), ids)  # dmm: 假類別無 plan
    assert {i: (rows[i]['state'], rows[i]['reason']) for i in ids} == {
        'javlibrary': ('skipped', 'windows_verifier'),
        'fc-javten': ('skipped', 'windows_verifier'),
        'metatube:x': ('skipped', 'self_hosted'),
        'zzz': ('skipped', 'unknown'),
        'dmm': ('skipped', 'unprobeable'),
    }
    for r in rows.values():
        assert set(r) == SIX_KEYS
        assert (r['host'], r['status'], r['via_proxy'], r['advice']) == (None, None, False, None)


# ------------------------------------------------------------ 驗證視窗來源：skipped 環境表／判讀

class _FakeTransport:
    def __init__(self, sites):
        self._sites = sites

    def available_sites(self):
        return list(self._sites)


class _NoSitesTransport:
    """沒有 available_sites 屬性：get_cf_available_sites() 回 None（判不出來）。"""


@pytest.fixture
def transport_env(monkeypatch):
    """造 get_cf_available_sites() 的 []／部分／全／None；結束還原模組全域。"""
    import core.cf_transport as cft
    saved = cft._transport

    def _set(transport):
        cft._transport = transport

    try:
        yield _set
    finally:
        cft._transport = saved


BOTH = ('javlibrary', 'fc-javten')
SNAP_ALL = ProxySettings(url=PROXY, scope='all')
SNAP_DMM = ProxySettings(url=PROXY, scope='dmm')
SNAP_AUTH_ALL = ProxySettings(url='socks5://u:p@h.example:1', scope='all')
SNAP_AUTH_DMM = ProxySettings(url='socks5://u:p@h.example:1', scope='dmm')
SNAP_NOSCHEME_ALL = ProxySettings(url='h.example:1', scope='all')
SNAP_SOCKS_ALL = ProxySettings(url='socks5://h.example:1', scope='all')


@pytest.mark.parametrize('label,kind,transport,snap,expect', [
    ('mac_all_sites', 'mac', _FakeTransport(BOTH), SNAP_ALL, ('mac_system_proxy',) * 2),
    ('win_empty', 'windows', _FakeTransport(()), SNAP_ALL, ('verifier_not_started',) * 2),
    ('win_all_http', 'windows', _FakeTransport(BOTH), SNAP_ALL, (None, None)),
    ('win_all_socks_auth', 'windows', _FakeTransport(BOTH), SNAP_AUTH_ALL,
     ('proxy_auth_unsupported',) * 2),
])
def test_skip_reason_environment_table(monkeypatch, transport_env, label, kind, transport, snap, expect):
    monkeypatch.setattr('core.source_probe.desktop_kind', lambda: kind)
    transport_env(transport)
    got = tuple(sp.skip_reason(sid, snap) for sid in BOTH)
    assert got == expect, label


# ------------------------------------------------------------ 不洩漏

def test_run_probes_response_never_contains_exception_text(fake_classes):
    plans, _ = fake_classes
    secret = 'http://user:pass@127.0.0.1:1'

    def send():
        raise requests.exceptions.ProxyError(f'Cannot connect to proxy {secret}')

    plans['dmm'] = ProbePlan([ProbeTarget('d.example', send)])
    rows = run_probes(ProxySettings(url=secret), ['dmm'])
    blob = json.dumps(rows)
    assert rows['dmm']['reason'] == 'proxy'
    assert 'pass' not in blob and 'Cannot connect' not in blob and '127.0.0.1' not in blob
    assert rows['dmm']['reason'] in sp.REASON_CODES
