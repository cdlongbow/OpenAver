// TASK-168d-fix-T2：灰化 CF 膠囊按下時向伺服器重查（onCfPillClick）。
// harness 照 state-rescrape-cf-availability.test.mjs 檔頭。

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

const JL = { id: 'javlibrary', manual_only: true, is_beta: true };
const JT = { id: 'fc-javten', manual_only: true, is_beta: true };

async function scenario(snapshot, fetchImpl, pill, fn) {
    const origAdv = globalThis.window.__ADVANCED_SEARCH__;
    const origFetch = globalThis.fetch;
    globalThis.window.__ADVANCED_SEARCH__ = snapshot;
    const fetchCalls = [];
    globalThis.fetch = (url, opts) => { fetchCalls.push([url, opts]); return fetchImpl(url, opts); };
    const ctx = rescrapeState();
    const toasts = [];
    const rescrapes = [];
    ctx.showToast = (msg, kind) => toasts.push([msg, kind]);
    ctx.rescrapeWithSource = (id) => { rescrapes.push(id); };
    try {
        await ctx.onCfPillClick(pill);
        return await fn({ ctx, toasts, rescrapes, fetchCalls, adv: globalThis.window.__ADVANCED_SEARCH__ });
    } finally {
        globalThis.window.__ADVANCED_SEARCH__ = origAdv;
        globalThis.fetch = origFetch;
    }
}

const ok = (data) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
const SRC = [{ id: 'javlibrary' }];

test('I-12 recheck success reassigns rescrapeCfAvail and leaves the global untouched', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: [] },
        ok({ available: true, sites: ['javlibrary'], preparing: [] }), JL,
        ({ ctx, toasts, rescrapes, adv, fetchCalls }) => {
            assert.equal(fetchCalls.length, 1);
            assert.equal(fetchCalls[0][0], '/api/cf/availability');
            assert.deepEqual(rescrapes, ['javlibrary']);
            assert.equal(toasts.length, 0);
            assert.deepEqual(ctx.rescrapeCfAvail, { available: true, sites: ['javlibrary'], preparing: [], inShell: false });
            assert.deepEqual(adv.cf_sites, []);                   // 全域 cf 三欄逐字不變
            assert.equal(adv.cf_transport_available, true);
            assert.deepEqual(adv.cf_preparing, []);
            assert.equal(adv.sources, SRC);                       // 不整包重指派
            assert.equal(ctx.isJlUnavailable(JL), false);
            assert.equal(ctx.isJlUnavailable(JT), true);          // 另一站依新快照重算
        });
});


test('I-4 cell3: recheck says no shell -> desktop only', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: [] },
        ok({ available: false, sites: [], preparing: [] }), JL,
        ({ toasts, rescrapes }) => {
            assert.deepEqual(toasts, [['showcase.rescrape.jl_desktop_only', 'warning']]);
            assert.equal(rescrapes.length, 0);
        });
});


