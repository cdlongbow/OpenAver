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


// ---- 168e-T14: retry button ----
const NOT_READY = { state: 'not_ready', reason: 'unreachable', proxy_note: null };
const READY = { state: 'ready', reason: null, proxy_note: null, sites: [] };

async function started(cf = NOT_READY, shellKind = 'windows') {
    const page = mk({ cf }, shellKind);
    await page.start();
    return page;
}

function withRetry(page, impl) {
    const calls = [];
    window.pywebview.api.cf_retry = async (...a) => { calls.push(a); return impl(); };
    return calls;
}

test('retry button shows only for not_ready', async () => {
    const page = await started(NOT_READY);
    assert.equal(page.actions().showRetryCf, true);
    assert.equal(page.actions().canRetryCf, true);
    for (const reason of ['shell_old', 'webview2_failed', 'starting']) {
        page.cf = { state: 'not_ready', reason };
        assert.equal(page.actions().showRetryCf, true, reason);
    }
    page.cf = READY;
    assert.equal(page.actions().showRetryCf, false);
    assert.equal(page.actions().canRetryCf, false);
    page.cf = { state: 'unsupported' };
    assert.equal(page.actions().showRetryCf, false);
    // loading: bridge not ready and cf null must not flash the button
    const loading = mk({});
    assert.equal(loading.bridge, 'pending');
    assert.equal(loading.cf, null);
    assert.equal(loading.actions().showRetryCf, false);
    assert.equal(loading.actions().canRetryCf, false);
});


test('retry reply replaces this.cf with the shell\'s answer', async () => {
    const page = await started(NOT_READY);
    withRetry(page, () => ({ ok: true, cf: READY }));
    await page.retryCf();
    assert.deepEqual(page.cf, READY);
    assert.equal(page.cfText(), 'connect.cf_ready');
    assert.equal(page.cfRetryError, '');
    assert.equal(page.cfRetryErrorText(), '');
    // a still-not-ready answer also lands (new reason shown)
    const page2 = await started(NOT_READY);
    const nr = { state: 'not_ready', reason: 'webview2_failed' };
    withRetry(page2, () => ({ ok: true, cf: nr }));
    await page2.retryCf();
    assert.deepEqual(page2.cf, nr);
    assert.ok(page2.cfText().includes('connect.cf_reason_webview2_failed'));
});


test('retry failures set cfRetryError and leave cf untouched', async () => {
    const cases = [
        [{ ok: false, reason: 'busy' }, 'busy', 'connect.cf_retry_busy'],
        [{ ok: false, reason: 'unavailable' }, 'unavailable', 'connect.cf_retry_unavailable'],
        [{ ok: false, reason: 'failed' }, 'failed', 'connect.error_generic'],
        [{ ok: false, reason: 'error' }, 'failed', 'connect.error_generic'],
        [{ ok: true }, 'failed', 'connect.error_generic'],
        [{ ok: true, cf: 'x' }, 'failed', 'connect.error_generic'],
        [null, 'failed', 'connect.error_generic'],
    ];
    for (const [reply, code, key] of cases) {
        const page = await started(NOT_READY);
        withRetry(page, () => reply);
        const before = page.cf;
        await page.retryCf();
        assert.equal(page.cf, before, JSON.stringify(reply));
        assert.equal(page.cfRetryError, code, JSON.stringify(reply));
        assert.equal(page.cfRetryErrorText(), key.startsWith('connect.cf') ? key : 'connect.error_generic');
        assert.equal(page.cfBusy, false);
    }
});


test('untrusted retry reply marks bridge unavailable and writes nothing', async () => {
    const page = await started(NOT_READY);
    withRetry(page, () => ({ ok: false, reason: 'untrusted' }));
    const before = page.cf;
    await page.retryCf();
    assert.equal(page.bridge, 'unavailable');
    assert.equal(page.cf, before);
    assert.equal(page.cfRetryError, '');
    assert.equal(page.cfBusy, false);
});

