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


function confirmCtx(ctx) {
    ctx.openRescrape({ number: 'AAA-111', path: '/x/a.mp4' });
    ctx.rescrapePreview = { url: 'u' };
    ctx.rescrapeStep = 'preview';
    ctx._rescrapeCommitSource = 'javbus';
}

for (const [name, body] of [['success', { success: true }], ['cf_needed', { cf_needed: true }]]) {
}


for (const [name, impl] of [
    ['success:false', async () => reply({ success: false, error: 'write failed' })],
    ['fetch rejects', async () => { throw new Error('boom'); }],
]) {
}
