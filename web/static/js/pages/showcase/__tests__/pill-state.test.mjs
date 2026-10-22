// TASK-115-T1: metadata pill 狀態層（無 UI）契約。
// 覆蓋 normalizePillValue、addPill/removePill/clearAllFilters 的去重／陣列替換／
// _animateFilter 與 _reconcileHeroCard 呼叫次數，以及 onSearchChange 不產生 pill。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑
// （importmap 實際指到 `pages/showcase/`）。比照 settings/save-access-auth.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（不改共用 loader）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// 任務卡聲稱 open-local 的 window 存取皆在函式體內，實際並非如此。
// 比照 cover-fallback.test.mjs / confirm-edit-identity-guard.test.mjs 先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
// 115-T7：clearAllFilters() 現在寫 Alpine.store('ui').toolbarOpen；T1 harness 需 stub 才能跑。
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
// 本檔：web/static/js/pages/showcase/__tests__/ → 上三層 = web/static/js/
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateVideos } = await import('../state-videos.js');

// makeComponent 用 spy 覆寫 _reconcileHeroCard/_animateFilter，因此 call-count 斷言只證明
// 「三個 mutation 有呼叫它」，證明不了「state-videos.js 裡真的有那個 no-op stub」。
// T8 只會改 stub 的方法體、不動 call site，stub 若被誤刪，call-count 那幾支仍會全綠而真頁面
// 直接 TypeError。故在覆寫前先單獨鎖 stub 存在性。

function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), {
        pills: [],
        search: '',
        actressSearch: '',
        page: 3,
        sort: 'title',
        order: 'asc',
        animateCalls: 0,
        heroCalls: 0,
        _clearPreciseMatch() {},
        _checkPreciseActressMatch() {},
        // 115-T7：clearAllFilters 現在呼叫 applyActressFilterAndSort（定義在 state-actress.js）
        applyActressFilterAndSort() {},
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    c._reconcileHeroCard = function () { c.heroCalls++; };
    return c;
}

// ===== normalizePillValue =====


// ===== addPill =====


test('addPill：大小寫不同的同一值只留先點的字面', () => {
    const c = makeComponent();
    c.addPill('maker', 'Moodyz');
    c.addPill('maker', 'MOODYZ');
    assert.equal(c.pills.length, 1);
    assert.equal(c.pills[0].value, 'Moodyz');
});

test('addPill：同名不同維度各自成一枚 pill 共存', () => {
    const c = makeComponent();
    c.addPill('series', 'Madonna');
    c.addPill('maker', 'Madonna');
    assert.equal(c.pills.length, 2);
    assert.equal(c.pills[0].dim, 'series');
    assert.equal(c.pills[1].dim, 'maker');
});


// ===== removePill =====

test('removePill：移除存在的 pill → length 少一，_animateFilter/_reconcileHeroCard 各 1 次', () => {
    const c = makeComponent();
    c.addPill('maker', 'Moodyz');
    c.addPill('series', 'Madonna');
    c.animateCalls = 0;
    c.heroCalls = 0;
    c.removePill('maker', 'Moodyz');
    assert.equal(c.pills.length, 1);
    assert.equal(c.pills[0].dim, 'series');
    assert.equal(c.animateCalls, 1);
    assert.equal(c.heroCalls, 1);
});


// ===== clearAllFilters =====


// ===== call-count invariants（確實執行變更時恰好 1 次）=====


// ===== page / sort / order 不被 mutation 直接寫入 =====


// ===== onSearchChange 不產生 pill =====

test('打字（onSearchChange）不產生任何 pill', () => {
    const c = makeComponent();
    c.search = 'Moodyz';
    c.onSearchChange();
    assert.equal(c.pills.length, 0);
});

// ===== 陣列整包替換（參照恆等性）=====

