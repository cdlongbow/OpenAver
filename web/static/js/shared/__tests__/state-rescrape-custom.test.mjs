// TASK-165-T10：重刮視窗自訂來源接線（第三組膠囊、番號格式灰化、三種自訂失敗句）。
// 判斷全在後端；這裡只驗前端的世代守衛、過濾、擋點、互斥與時序。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (k, p) => (p && p.source ? k + '|' + p.source : k);

register(
  new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);
const { rescrapeState } = await import('../state-rescrape.js');

const SOURCES = [
    { id: 'javbus', type: 'builtin', routable: true, order: 1 },
    { id: 'mt:x', type: 'metatube', routable: true, order: 2 },
    { id: 'custom:b', type: 'custom', routable: true, order: 2, display_name_raw: 'B' },
    { id: 'custom:a', type: 'custom', routable: true, order: 1, display_name_raw: 'A' },
    { id: 'custom:off', type: 'custom', routable: false, order: 3 },
];

function makeCtx(sources = SOURCES) {
    const ctx = rescrapeState();
    ctx.rescrapeSources = sources;
    ctx.rescrapeNumber = 'ABC-123';
    return ctx;
}

function errCount(ctx) {
    return [ctx.rescrapeNotFound, ctx.rescrapeAccessError, ctx.rescrapeCustomError].filter(Boolean).length;
}

/** 可手動 resolve 的 fetch stub。 */
function installFetch() {
    const calls = [];
    globalThis.fetch = (url, opts) => {
        let resolve;
        const p = new Promise(r => { resolve = r; });
        calls.push({
            url, body: opts && opts.body ? JSON.parse(opts.body) : null,
            respond(map, ok = true) {
                resolve({ ok, json: async () => ({ success: true, applicable: map }) });
            },
            respondRaw(obj) { resolve({ ok: true, json: async () => obj }); },
        });
        return p;
    };
    return calls;
}


test('rescrapeCustomSources excludes routable false and other types', () => {
    const ctx = makeCtx();
    assert.deepEqual(ctx.rescrapeCustomSources().map(s => s.id), ['custom:a', 'custom:b']);
});


test('click on a not-applicable custom pill sends no preview request', async () => {
    const ctx = makeCtx();
    const calls = installFetch();
    ctx.rescrapeCustomApplicable = { 'custom:a': false };
    const p = ctx.rescrapeWithSource('custom:a');
    const sent = calls.length;
    calls.forEach(c => c.respondRaw({ success: false }));
    await p;
    assert.equal(sent, 0);
    assert.equal(ctx.rescrapeLoadingSource, null);
    assert.equal(errCount(ctx), 0);
});


test('parse_empty shows the site-changed sentence not the unreachable one', () => {
    const ctx = makeCtx();
    ctx._applyRescrapeFailure({ success: false, custom_error: 'parse_empty', source: 'custom:a' }, 'custom:a');
    const msg = ctx.rescrapeCustomMessage(ctx.rescrapeCustomError);
    assert.ok(msg.includes('custom_parse_failed'));
    assert.ok(!msg.includes('access_unreachable'));
    assert.ok(msg.includes('A'));
});


