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

test('I-3b: recheck sites:null + available -> fail-open, rescrape', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: false, cf_sites: [], cf_preparing: [] },
        ok({ available: true, sites: null, preparing: [] }), JT,
        ({ ctx, toasts, rescrapes, adv }) => {
            assert.deepEqual(rescrapes, ['fc-javten']);
            assert.equal(toasts.length, 0);
            assert.equal(ctx.rescrapeCfAvail.sites, null);        // null 原樣保留
            assert.equal(ctx.rescrapeCfAvail.available, true);
            assert.deepEqual(adv.cf_sites, []);                   // 全域不再被寫
        });
});

test('I-3c: non-gray pill does not fetch, rescrapes directly', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: ['javlibrary'], cf_preparing: [] },
        () => { throw new Error('should not fetch'); }, JL,
        ({ rescrapes, fetchCalls }) => {
            assert.deepEqual(rescrapes, ['javlibrary']);
            assert.equal(fetchCalls.length, 0);
        });
});

test('I-4 cell1: recheck says preparing -> toast preparing', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: ['javlibrary'], cf_preparing: [] },
        ok({ available: true, sites: ['javlibrary'], preparing: ['fc-javten'] }), JT,
        ({ ctx, toasts, rescrapes, adv }) => {
            assert.deepEqual(toasts, [['showcase.rescrape.cf_window_preparing', 'warning']]);
            assert.equal(rescrapes.length, 0);
            assert.deepEqual(ctx.rescrapeCfAvail.preparing, ['fc-javten']);
            assert.deepEqual(adv.cf_preparing, []);               // 全域不再被寫
        });
});

test('I-4 cell2: recheck says shell exists but site not in sites/preparing -> restart', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: [] },
        ok({ available: true, sites: ['javlibrary'], preparing: [] }), JT,
        ({ toasts, rescrapes }) => {
            assert.deepEqual(toasts, [['showcase.rescrape.cf_window_restart', 'warning']]);
            assert.equal(rescrapes.length, 0);
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

test('I-4 cell4: snapshot has preparing + fetch rejects -> toast preparing', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: ['javlibrary'] },
        () => Promise.reject(new Error('timeout')), JL,
        ({ toasts, rescrapes }) => {
            assert.deepEqual(toasts, [['showcase.rescrape.cf_window_preparing', 'warning']]);
            assert.equal(rescrapes.length, 0);
        });
});

test('I-4 cell5: cfUnavailableMessageKey without siteId keeps legacy behaviour', () => {
    globalThis.window.__ADVANCED_SEARCH__ = { cf_transport_available: true, cf_preparing: ['javlibrary'] };
    const ctx = rescrapeState();
    assert.equal(ctx.cfUnavailableMessageKey(), 'showcase.rescrape.cf_window_restart');
    assert.equal(ctx.cfUnavailableMessageKey('javlibrary'), 'showcase.rescrape.cf_window_preparing');
});

test('I-6: window reopened during recheck -> no rescrape, no toast, availability still updated', async () => {
    const origAdv = globalThis.window.__ADVANCED_SEARCH__;
    const origFetch = globalThis.fetch;
    globalThis.window.__ADVANCED_SEARCH__ = { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: [] };
    let release;
    globalThis.fetch = () => new Promise((resolve) => {
        release = () => resolve({ ok: true, json: () => Promise.resolve({ available: true, sites: ['javlibrary'], preparing: [] }) });
    });
    const ctx = rescrapeState();
    const toasts = [];
    const rescrapes = [];
    ctx.showToast = (msg, kind) => toasts.push([msg, kind]);
    ctx.rescrapeWithSource = (id) => { rescrapes.push(id); };
    try {
        ctx.openRescrape({ number: 'AAA-111' });             // A 開窗
        const pending = ctx.onCfPillClick(JL);               // 按灰膠囊，重查未回
        ctx.closeRescrape();
        ctx.openRescrape({ number: 'BBB-222' });             // 關窗並開 B
        release();
        await pending;
        assert.equal(rescrapes.length, 0);
        assert.equal(toasts.length, 0);
        assert.ok(ctx.rescrapeCfAvail.sites.includes('javlibrary'));   // 可用性是全域事實，窗換了仍更新
        assert.deepEqual(globalThis.window.__ADVANCED_SEARCH__.cf_sites, []);
    } finally {
        globalThis.window.__ADVANCED_SEARCH__ = origAdv;
        globalThis.fetch = origFetch;
    }
});

test('I-12 seed: rescrapeCfAvail seeds from the SSR global; missing global gives defaults', () => {
    const orig = globalThis.window.__ADVANCED_SEARCH__;
    try {
        globalThis.window.__ADVANCED_SEARCH__ = { cf_transport_available: true, cf_sites: ['javlibrary'], cf_preparing: [] };
        assert.deepEqual(rescrapeState().rescrapeCfAvail, { available: true, sites: ['javlibrary'], preparing: [], inShell: false });
        globalThis.window.__ADVANCED_SEARCH__ = {};
        assert.deepEqual(rescrapeState().rescrapeCfAvail, { available: false, sites: null, preparing: [], inShell: false });
        globalThis.window.__ADVANCED_SEARCH__ = undefined;
        assert.deepEqual(rescrapeState().rescrapeCfAvail, { available: false, sites: null, preparing: [], inShell: false });
    } finally {
        globalThis.window.__ADVANCED_SEARCH__ = orig;
    }
});

test('I-12 recheck failure leaves rescrapeCfAvail unchanged', async () => {
    await scenario(
        { sources: SRC, cf_transport_available: true, cf_sites: [], cf_preparing: [] },
        () => Promise.reject(new Error('timeout')), JL,
        ({ ctx }) => {
            assert.deepEqual(ctx.rescrapeCfAvail, { available: true, sites: [], preparing: [], inShell: false });
        });
});
