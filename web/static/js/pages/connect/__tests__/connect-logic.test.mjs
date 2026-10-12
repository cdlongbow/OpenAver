// 168b-T6a: connect-logic pure functions (I-U truth table and code maps).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { connectActions, probeCode, dotState, kindCode, forgotCode } =
    await import('../connect-logic.js');

const URL_A = 'http://good.test:8765';
const okProbe = (over = {}) => ({
    ok: true, reason: null, version: '0.17.10', kind: 'linux',
    auth_required: true, authed: false,
    compat: { status: 'ok', hint: '' }, url: URL_A, ...over,
});
const withStatus = (status, over = {}) => okProbe({ compat: { status, hint: '' }, ...over });
const downProbe = (reason) => ({
    ok: false, reason, version: '', kind: '',
    compat: { status: 'unparseable', hint: '' }, url: '',
});
const legacyProbe = () => ({
    ok: false, reason: null, version: '0.16.9', kind: '',
    compat: { status: 'server_old', hint: '' }, url: URL_A,
});
function st(over = {}) {
    return {
        bridge: 'ready', mode: 'local', busy: null, restarting: false,
        urlText: URL_A, savedUrl: '', probedText: URL_A, probe: okProbe(),
        phase: 'probed', pin: '', ...over,
    };
}

test('test_incompatible_server_locks_login_and_apply', () => {
    const bad = [
        withStatus('server_old'), withStatus('client_old'), withStatus('unparseable'),
        legacyProbe(),
    ];
    for (const probe of bad) {
        const a = connectActions(st({ probe, pin: '4827', phase: 'authed' }));
        assert.equal(a.probeFresh, true);
        assert.equal(a.connectable, false);
        assert.equal(a.passwordField, 'disabled');
        assert.equal(a.canLogin, false);
        assert.equal(a.canApply, false);
        assert.equal(a.authOk, false);
    }
    for (const probe of [withStatus('ok'), withStatus('patch_diff')]) {
        assert.equal(connectActions(st({ probe })).connectable, true);
    }
});

test('unreachable class hides the password field', () => {
    for (const r of ['unreachable', 'timeout', 'tls', 'lan_forbidden', 'not_openaver']) {
        const a = connectActions(st({ probe: downProbe(r), pin: '1234' }));
        assert.equal(a.passwordField, 'hidden', r);
        assert.equal(a.canLogin, false);
        assert.equal(a.canApply, false);
    }
    const none = connectActions(st({ probe: null, probedText: '' }));
    assert.equal(none.passwordField, 'hidden');
    assert.equal(none.probeFresh, false);
});

test('test_no_password_server_can_apply_without_login', () => {
    const a = connectActions(st({ probe: okProbe({ auth_required: false }) }));
    assert.equal(a.passwordField, 'none');
    assert.equal(a.authOk, true);
    assert.equal(a.canLogin, false);
    assert.equal(a.canApply, true);
    assert.equal(a.applyKind, 'switch');
});

test('test_password_server_blocks_apply_until_authed', () => {
    let a = connectActions(st());
    assert.equal(a.passwordField, 'input');
    assert.equal(a.authOk, false);
    assert.equal(a.canApply, false);
    a = connectActions(st({ phase: 'authed' }));
    assert.equal(a.canApply, true);
    a = connectActions(st({ probe: okProbe({ authed: true }) }));
    assert.equal(a.canApply, true);
});

test('canLogin needs a non-empty pin and an idle ready bridge', () => {
    assert.equal(connectActions(st({ pin: '' })).canLogin, false);
    assert.equal(connectActions(st({ pin: '4827' })).canLogin, true);
    assert.equal(connectActions(st({ pin: '4827', busy: 'login' })).canLogin, false);
});

test('test_forgot_password_sentence_follows_server_kind', () => {
    assert.equal(forgotCode('synology'), 'synology');
    assert.equal(forgotCode('linux'), 'linux');
    assert.equal(forgotCode('windows'), 'desktop');
    assert.equal(forgotCode('mac'), 'desktop');
    assert.equal(forgotCode('toaster'), null);
    assert.equal(forgotCode(''), null);
});

test('kindCode maps known kinds and unknown to null', () => {
    for (const k of ['synology', 'linux', 'windows', 'mac']) assert.equal(kindCode(k), k);
    assert.equal(kindCode('nas'), null);
    assert.equal(kindCode(undefined), null);
});

test('test_switch_local_never_blocked_by_probe', () => {
    const probes = [null, okProbe(), withStatus('server_old'), withStatus('client_old'),
        downProbe('unreachable'), legacyProbe()];
    for (const probe of probes) {
        assert.equal(connectActions(st({ mode: 'client', probe, savedUrl: URL_A })).canSwitchLocal, true);
        assert.equal(connectActions(st({ mode: 'local', probe })).canSwitchLocal, false);
    }
    assert.equal(connectActions(st({ mode: 'client', bridge: 'unavailable' })).canSwitchLocal, false);
    assert.equal(connectActions(st({ mode: 'client', busy: 'apply' })).canSwitchLocal, false);
    assert.equal(connectActions(st({ mode: 'client', restarting: true })).canSwitchLocal, false);
});

test('test_edited_url_invalidates_tested_result', () => {
    let a = connectActions(st());
    assert.equal(a.probeFresh, true);
    a = connectActions(st({ urlText: 'http://good.test:8766', phase: 'authed' }));
    assert.equal(a.probeFresh, false);
    assert.equal(a.connectable, false);
    assert.equal(a.passwordField, 'hidden');
    assert.equal(a.canApply, false);
    a = connectActions(st({ urlText: '  ' + URL_A + ' ' }));
    assert.equal(a.probeFresh, true);
});

test('client mode apply only when changed or re-authed', () => {
    const base = { mode: 'client', savedUrl: URL_A, probe: okProbe({ authed: true }) };
    assert.equal(connectActions(st(base)).canApply, false);
    assert.equal(connectActions(st({ ...base, phase: 'authed' })).canApply, true);
    const other = 'http://other.test:8765';
    assert.equal(connectActions(st({
        ...base, urlText: other, probedText: other, probe: okProbe({ authed: true, url: other }),
    })).canApply, true);
    assert.equal(connectActions(st(base)).applyKind, 'apply');
});

test('bridge not ready or busy or restarting disables every action', () => {
    const live = { mode: 'client', savedUrl: 'http://old.test:8765', pin: '4827', phase: 'authed',
        probe: okProbe({ auth_required: true }) };
    const base = connectActions(st(live));
    assert.equal(base.canProbe, true);
    assert.equal(base.canLogin, true);
    assert.equal(base.canApply, true);
    assert.equal(base.canSwitchLocal, true);
    for (const over of [{ bridge: 'pending' }, { bridge: 'unavailable' },
        { busy: 'probe' }, { restarting: true }]) {
        const a = connectActions(st({ ...live, ...over }));
        assert.equal(a.canProbe, false);
        assert.equal(a.canLogin, false);
        assert.equal(a.canApply, false);
        assert.equal(a.canSwitchLocal, false);
    }
    assert.equal(connectActions(st({ urlText: '   ' })).canProbe, false);
    assert.equal(connectActions(st()).canProbe, true);
});

test('probeCode maps reasons and compat statuses', () => {
    assert.equal(probeCode(okProbe()), 'ok');
    assert.equal(probeCode(withStatus('patch_diff')), 'patch_diff');
    assert.equal(probeCode(withStatus('server_old')), 'server_old');
    assert.equal(probeCode(withStatus('client_old')), 'client_old');
    assert.equal(probeCode(withStatus('unparseable')), 'unparseable');
    assert.equal(probeCode(legacyProbe()), 'server_old');
    for (const r of ['unreachable', 'timeout', 'tls', 'lan_forbidden', 'not_openaver']) {
        assert.equal(probeCode(downProbe(r)), r);
    }
    assert.equal(probeCode(downProbe('weird')), 'unreachable');
    assert.equal(probeCode(null), 'unreachable');
});

test('dotState maps codes to three states', () => {
    for (const c of ['ok', 'patch_diff']) assert.equal(dotState(c), 'ok');
    for (const c of ['server_old', 'client_old', 'unparseable', 'not_openaver']) {
        assert.equal(dotState(c), 'blocked');
    }
    for (const c of ['unreachable', 'timeout', 'tls', 'lan_forbidden', 'zzz']) {
        assert.equal(dotState(c), 'unreachable');
    }
});
