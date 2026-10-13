// 168d-T6: cfView pure table + connectPage wiring for the CF line.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const captured = {};
globalThis.window = globalThis;
globalThis.document = { addEventListener(type, cb) { captured[type] = cb; } };
window.t = (key, params) => key + (params ? JSON.stringify(params) : '');
globalThis.setTimeout = () => 1;
window.addEventListener = () => {};

const { connectPage } = await import('../main.js');
const { cfView } = await import('../connect-logic.js');

const REASONS = ['starting', 'no_windows', 'proxy_unusable', 'server_old', 'unreachable', 'unauthorized', 'offline_boot'];
const OLD = { state: 'not_ready', reason: 'shell_old', proxy: null };

test('cfView treats null cf (old shell) as not_ready shell_old', () => {
    for (const bad of [null, undefined, 'x', 3, {}, { state: 'weird' }, { state: 7 }]) {
        assert.deepEqual(cfView(bad, 'windows'), OLD, JSON.stringify(bad));
        assert.deepEqual(cfView(bad, 'mac'), OLD);
    }
});

test('cfView ignores proxy_note on mac shell', () => {
    for (const state of ['ready', 'not_ready']) {
        const cf = { state, reason: state === 'ready' ? null : 'starting', proxy_note: 'applied' };
        assert.equal(cfView(cf, 'mac').proxy, null);
        assert.equal(cfView(cf, 'windows').proxy, 'applied');
    }
});

test('cfView state/reason/proxy table', () => {
    assert.deepEqual(cfView({ state: 'ready', reason: 'junk', proxy_note: 'server_local_direct' }, 'windows'),
        { state: 'ready', reason: null, proxy: 'server_local_direct' });
    assert.deepEqual(cfView({ state: 'ready', proxy_note: 'bogus' }, 'windows'),
        { state: 'ready', reason: null, proxy: null });
    for (const r of REASONS) {
        assert.deepEqual(cfView({ state: 'not_ready', reason: r, proxy_note: null }, 'windows'),
            { state: 'not_ready', reason: r, proxy: null });
    }
    for (const r of [undefined, null, 'brand_new', 'shell_old']) {
        assert.deepEqual(cfView({ state: 'not_ready', reason: r }, 'windows'),
            { state: 'not_ready', reason: 'shell_old', proxy: null });
    }
    for (const kind of ['windows', 'mac']) {
        assert.deepEqual(cfView({ state: 'unsupported', reason: 'x', proxy_note: 'applied' }, kind),
            { state: 'unsupported', reason: null, proxy: null });
    }
});

function mk(cfReply, shellKind = 'windows') {
    const page = connectPage();
    page.$el = { dataset: { mode: 'local', shellKind } };
    const base = { mode: 'local', url: '', host: '', has_token: false, path_map: [], version: '0.17.7', last_ok: null };
    window.pywebview = { api: { connect_get_state: async () => ({ ...base, ...cfReply }) } };
    window.__oaBridgeKind = 'server';
    page.shellKind = shellKind;
    page._syncSources = async () => {};
    return page;
}

test('wiring: cf lands, texts follow, cf set before bridge ready', async () => {
    const page = mk({ cf: { state: 'ready', reason: null, proxy_note: 'applied', sites: [] } });
    let seen = 'unset';
    let b = page.bridge;
    Object.defineProperty(page, 'bridge', {
        get() { return b; },
        set(v) { if (v === 'ready') seen = page.cf; b = v; },
    });
    assert.equal(page.cf, null);
    await page.start();
    assert.equal(seen && seen.state, 'ready');
    assert.equal(page.cfText(), 'connect.cf_ready');
    assert.equal(page.cfNoteText(), 'connect.cf_proxy_applied');
    page.cf = { state: 'ready', proxy_note: 'server_local_direct' };
    assert.equal(page.cfNoteText(), 'connect.cf_proxy_local_direct');
    page.cf = { state: 'not_ready', reason: 'proxy_unusable' };
    assert.equal(page.cfText(), 'connect.cf_not_ready{"reason":"connect.cf_reason_proxy_unusable"}');
    assert.equal(page.cfNoteText(), '');
    page.cf = { state: 'unsupported' };
    assert.equal(page.cfText(), 'connect.cf_mac');
});

test('wiring: reply without cf key is old shell', async () => {
    const page = mk({});
    await page.start();
    assert.equal(page.cf, null);
    assert.ok(page.cfText().includes('connect.cf_not_ready'));
    assert.ok(page.cfText().includes('connect.cf_reason_shell_old'));
    assert.equal(page.cfNoteText(), '');
});

test('wiring: every reason maps to its own key', async () => {
    const page = mk({});
    for (const r of [...REASONS, 'shell_old']) {
        page.cf = { state: 'not_ready', reason: r };
        assert.ok(page.cfText().includes(`connect.cf_reason_${r}`), r);
    }
});
