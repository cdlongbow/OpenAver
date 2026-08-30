// TASK-138-T6 CD-F5：searchActressFilms() 同步段順序——
// window.scrollTo(0, 0) 必須發生在 showFavoriteActresses = false 之前。
// lint 只守字面在不在；這支守的是 CD-F1 的「順序」。
//
// FE-GUARD-11：import 頁面 state 模組前先 stub window。
// FE-GUARD-13：本檔不碰 state-base 單例；每次 test() 自建 context。
// loader：比照 actress-cup-sort.test.mjs 共用 alias-loader（不另寫 resolve hook）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.localStorage = { getItem: () => null, removeItem: () => {} };
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

register(new URL('../../search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { stateActress } = await import('../state-actress.js');

function buildContext(order) {
    let showFav = true;
    const ctx = Object.assign({}, stateActress(), {
        lightboxOpen: false,
        _animGeneration: 0,
        _ghostFlyInFlight: false,
        search: '',
        actressSearch: '',
        mode: 'grid',
        $nextTick: (cb) => cb(),
        _teardownPillEditors: () => {},
        _animateFilter: () => {},
        _reconcileHeroCard: () => {},
        _getActiveGrid: () => null,
    });
    Object.defineProperty(ctx, 'showFavoriteActresses', {
        get() { return showFav; },
        set(v) {
            order.push(['showFavoriteActresses', v]);
            showFav = v;
        },
        configurable: true,
        enumerable: true,
    });
    return ctx;
}

test('searchActressFilms()：scrollTo(0,0) 發生在 showFavoriteActresses=false 之前（CD-F5 順序）', async () => {
    const order = [];
    const prevScrollTo = window.scrollTo;
    window.scrollTo = function (...args) {
        order.push(['scrollTo', ...args]);
    };

    try {
        const ctx = buildContext(order);
        // fromEl=null → 跳過 fromRect 擷取與 Ghost Fly，走 fallback 早退；
        // 仍會走過 wasActressMode 旗標翻轉同步段（CD-F5 要驗的那段）。
        await ctx.searchActressFilms('TestActress', null);

        const scrollIdx = order.findIndex((e) => e[0] === 'scrollTo');
        const flagIdx = order.findIndex(
            (e) => e[0] === 'showFavoriteActresses' && e[1] === false,
        );
        assert.ok(scrollIdx >= 0, `scrollTo 未被呼叫；order=${JSON.stringify(order)}`);
        assert.ok(flagIdx >= 0, `showFavoriteActresses=false 未被設定；order=${JSON.stringify(order)}`);
        assert.ok(
            scrollIdx < flagIdx,
            `歸零必須早於旗標翻轉；scrollIdx=${scrollIdx} flagIdx=${flagIdx} order=${JSON.stringify(order)}`,
        );
        assert.deepEqual(order[scrollIdx], ['scrollTo', 0, 0]);
    } finally {
        window.scrollTo = prevScrollTo;
    }
});
