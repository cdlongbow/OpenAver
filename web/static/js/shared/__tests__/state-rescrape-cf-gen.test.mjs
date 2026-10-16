// TASK-168e-T11：preview / poll / confirm 三個 await 之後窗已換 → 新窗不被動（_rescrapeOpenGen）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
if (typeof globalThis.window.t !== 'function') {
    globalThis.window.t = (k) => k;
}

register(
  new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);
const { rescrapeState } = await import('../state-rescrape.js');

function gate() {
    let release;
    const p = new Promise((r) => { release = r; });
    return { p, release };
}

async function withGlobals({ fetchImpl, setIntervalImpl }, fn) {
    const origFetch = globalThis.fetch;
    const origSet = globalThis.setInterval;
    const origClear = globalThis.clearInterval;
    const origAdv = globalThis.window.__ADVANCED_SEARCH__;
    globalThis.window.__ADVANCED_SEARCH__ = { sources: [{ id: 'javbus' }], cf_transport_available: true, cf_sites: ['javlibrary'], cf_preparing: [] };
    if (fetchImpl) globalThis.fetch = fetchImpl;
    globalThis.setInterval = setIntervalImpl || (() => 7);   // 永不啟動真計時器（mutation 下 cf_needed 路徑會呼叫）
    globalThis.clearInterval = () => {};
    try {
        return await fn();
    } finally {
        globalThis.fetch = origFetch;
        globalThis.setInterval = origSet;
        globalThis.clearInterval = origClear;
        globalThis.window.__ADVANCED_SEARCH__ = origAdv;
    }
}

function mkCtx() {
    const ctx = rescrapeState();
    ctx.toasts = [];
    ctx.showToast = (m, k) => ctx.toasts.push([m, k]);
    ctx.refreshed = [];
    ctx.refreshVideoData = async (v) => { ctx.refreshed.push(v); };
    return ctx;
}

const reply = (data) => ({ ok: true, json: async () => data });

test('I-12 gen: preview landing after reopen leaves the new window untouched', async () => {
    const g = gate();
    await withGlobals({ fetchImpl: async () => { await g.p; return reply({ success: true, number: 'AAA-111', title: 't' }); } }, async () => {
        const ctx = mkCtx();
        ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
        const pending = ctx.rescrapeWithSource('javbus');
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
        g.release();
        await pending;
        assert.equal(ctx.rescrapePreview, null);
        assert.equal(ctx.rescrapeStep, 'pick');
        assert.equal(ctx.rescrapeNotFound, false);
        assert.equal(ctx.rescrapeCfWaiting, false);
        assert.equal(ctx.rescrapeOpen, true);
    });
});

test('I-12 gen: preview fetch rejecting after reopen does not mark the new window not-found', async () => {
    const g = gate();
    await withGlobals({ fetchImpl: async () => { await g.p; throw new Error('boom'); } }, async () => {
        const ctx = mkCtx();
        ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
        const pending = ctx.rescrapeWithSource('javbus');
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
        g.release();
        await pending;
        assert.equal(ctx.rescrapeNotFound, false);
        assert.equal(ctx.rescrapePreview, null);
    });
});

test('I-12 gen: stale preview does not clear the new window\'s loading state', async () => {
    const g = gate();
    await withGlobals({ fetchImpl: async () => { await g.p; return reply({ success: false }); } }, async () => {
        const ctx = mkCtx();
        ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
        const pending = ctx.rescrapeWithSource('javbus');
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
        ctx.rescrapeLoadingSource = 'javdb';              // 新窗自己的載入態
        g.release();
        await pending;
        assert.equal(ctx.rescrapeLoadingSource, 'javdb');
    });
});

test('I-12 gen: cf poll callback in flight after reopen does not retry', async () => {
    const g = gate();
    let intervalFn = null;
    await withGlobals({
        setIntervalImpl: (fn) => { intervalFn = fn; return 7; },
        fetchImpl: async () => { await g.p; return reply({ ready: true }); },
    }, async () => {
        const ctx = mkCtx();
        const retried = [];
        ctx.rescrapeWithSource = async (id) => { retried.push(id); };
        ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
        ctx._pollCfThenRetry('AAA-111', 'javlibrary');
        const p = intervalFn();
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
        g.release();
        await p;
        assert.equal(retried.length, 0);
        assert.equal(ctx.rescrapeCfWaiting, false);
    });
});

function confirmCtx(ctx) {
    ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
    ctx.rescrapePreview = { url: 'u' };
    ctx.rescrapeStep = 'preview';
    ctx._rescrapeCommitSource = 'javbus';
}

for (const [name, body] of [['success', { success: true }], ['cf_needed', { cf_needed: true }]]) {
    test(`I-12 gen: confirm landing after reopen does not toast or close the new window (${name})`, async () => {
        const g = gate();
        await withGlobals({ fetchImpl: async () => { await g.p; return reply(body); } }, async () => {
            const ctx = mkCtx();
            confirmCtx(ctx);
            const pending = ctx.rescrapeConfirm();
            ctx.closeRescrape();
            ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
            g.release();
            await pending;
            assert.equal(ctx.toasts.length, 0);
            assert.equal(ctx.rescrapeOpen, true);
            assert.equal(ctx.rescrapeCfWaiting, false);
            assert.equal(ctx._cfPollHandle, null);
        });
    });
}

test('I-12 gen: refresh landing after reopen does not toast or close the new window', async () => {
    const g = gate();
    await withGlobals({ fetchImpl: async () => reply({ success: true }) }, async () => {
        const ctx = mkCtx();
        const r = gate();
        ctx.refreshVideoData = async (v) => { ctx.refreshed.push(v); await r.p; };
        confirmCtx(ctx);
        const pending = ctx.rescrapeConfirm();
        await g.release();
        while (ctx.refreshed.length === 0) await Promise.resolve();   // 停在 refresh 的 await
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
        r.release();
        await pending;
        assert.equal(ctx.toasts.length, 0);
        assert.equal(ctx.rescrapeOpen, true);
    });
});

for (const [name, impl] of [
    ['success:false', async () => reply({ success: false, error: 'write failed' })],
    ['fetch rejects', async () => { throw new Error('boom'); }],
]) {
    test(`I-12 gen: confirm failure landing after reopen still toasts once, new window untouched (${name})`, async () => {
        const g = gate();
        await withGlobals({ fetchImpl: async () => { await g.p; return impl(); } }, async () => {
            const ctx = mkCtx();
            confirmCtx(ctx);
            const pending = ctx.rescrapeConfirm();
            ctx.closeRescrape();
            ctx.openRescrape({ number: 'BBB-222', path: '/x/b.mp4' });
            g.release();
            await pending;
            assert.equal(ctx.toasts.length, 1);
            assert.equal(ctx.toasts[0][1], 'error');
            assert.equal(ctx.rescrapeOpen, true);
            assert.equal(ctx.rescrapeNotFound, false);
            assert.equal(ctx.rescrapeCfWaiting, false);
            assert.equal(ctx.refreshed.length, 0);
        });
    });
}
