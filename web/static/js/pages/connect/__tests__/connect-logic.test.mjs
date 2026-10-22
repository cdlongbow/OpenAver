// 168b-T6a: connect-logic pure functions (I-U truth table and code maps).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { connectActions } =
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


