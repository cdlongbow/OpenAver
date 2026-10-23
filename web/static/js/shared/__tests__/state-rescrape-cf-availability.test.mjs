// TASK-118a-T9：_cfSiteLive() / cfUnavailableMessageKey() 真值表 ＋ isJlUnavailable()
// 改用前者後的行為驗證。照抄 state-rescrape-cf-poll.test.mjs 檔頭的 harness。

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

function withAdvancedSearch(value, fn) {
    const orig = globalThis.window.__ADVANCED_SEARCH__;
    globalThis.window.__ADVANCED_SEARCH__ = value;
    try {
        return fn();
    } finally {
        globalThis.window.__ADVANCED_SEARCH__ = orig;
    }
}

// ── isJlUnavailable() 真值表（§4.4 表格 1–8）──────────────────────────────

test('#1 dev/區網（cf_sites:[]）：fc-javten → true（與 T9 之前逐字相同）', () => {
    withAdvancedSearch({ cf_transport_available: false, cf_sites: [] }, () => {
        const ctx = rescrapeState();
        const result = rescrapeState().isJlUnavailable.call(ctx, { id: 'fc-javten', manual_only: true, is_beta: true });
        assert.equal(result, true);
    });
});


test('#4 本 task 存在的理由（Codex P2）：javten 視窗建立失敗，cf_sites 只有 javlibrary → fc-javten true', () => {
    withAdvancedSearch({ cf_transport_available: true, cf_sites: ['javlibrary'] }, () => {
        const ctx = rescrapeState();
        const result = rescrapeState().isJlUnavailable.call(ctx, { id: 'fc-javten', manual_only: true, is_beta: true });
        assert.equal(result, true);
    });
});

test('#5 不得連坐（89239a16 的不變式）：cf_sites 只有 javlibrary → javlibrary 仍 false', () => {
    withAdvancedSearch({ cf_transport_available: true, cf_sites: ['javlibrary'] }, () => {
        const ctx = rescrapeState();
        const result = rescrapeState().isJlUnavailable.call(ctx, { id: 'javlibrary', manual_only: true, is_beta: true });
        assert.equal(result, false);
    });
});


test('#7 非 CF 來源永不受影響（manual_only:false）：false', () => {
    withAdvancedSearch({ cf_transport_available: true, cf_sites: ['javlibrary'] }, () => {
        const ctx = rescrapeState();
        const result = rescrapeState().isJlUnavailable.call(ctx, { id: 'javbus', manual_only: false, is_beta: false });
        assert.equal(result, false);
    });
});


// ── cfUnavailableMessageKey() 真值表（§4.4 表格 9–11）─────────────────────


// ---- 168e-T14: cfUnavailableMessageKey four-way split ----
function msgKey(adv, siteId) {
    return withAdvancedSearch(adv, () => {
        const ctx = rescrapeState();
        return rescrapeState().cfUnavailableMessageKey.call(ctx, siteId);
    });
}

test('preparing wins over available and inShell', () => {
    const adv = { cf_transport_available: true, cf_sites: [], cf_preparing: ['javlibrary'], in_shell: true };
    assert.equal(msgKey(adv, 'javlibrary'), 'showcase.rescrape.cf_window_preparing');
});

test('available transport in shell -> cf_window_restart wins over not_built', () => {
    const adv = { cf_transport_available: true, cf_sites: [], cf_preparing: [], in_shell: true };
    assert.equal(msgKey(adv, 'javlibrary'), 'showcase.rescrape.cf_window_restart');
});


test('not in shell (or field missing) -> jl_desktop_only', () => {
    assert.equal(msgKey({ cf_transport_available: false, cf_sites: [], in_shell: false }, 'javlibrary'),
        'showcase.rescrape.jl_desktop_only');
    assert.equal(msgKey({ cf_transport_available: false, cf_sites: [] }, 'javlibrary'),
        'showcase.rescrape.jl_desktop_only');
});


