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
const { normalizePillValue } = await import('../../../shared/pill-filter.js');

// makeComponent 用 spy 覆寫 _reconcileHeroCard/_animateFilter，因此 call-count 斷言只證明
// 「三個 mutation 有呼叫它」，證明不了「state-videos.js 裡真的有那個 no-op stub」。
// T8 只會改 stub 的方法體、不動 call site，stub 若被誤刪，call-count 那幾支仍會全綠而真頁面
// 直接 TypeError。故在覆寫前先單獨鎖 stub 存在性。
test('state-videos.js 真的定義了 _reconcileHeroCard stub（spy 覆寫前的存在性鎖）', () => {
    assert.equal(typeof stateVideos()._reconcileHeroCard, 'function');
});

function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), {
        pills: [],
        search: '',
        page: 3,
        sort: 'title',
        order: 'asc',
        animateCalls: 0,
        heroCalls: 0,
        _clearPreciseMatch() {},
        _checkPreciseActressMatch() {},
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    c._reconcileHeroCard = function () { c.heroCalls++; };
    return c;
}

// ===== normalizePillValue =====

test('normalizePillValue：trim → NFKC → toLowerCase；null/undefined/純空白回傳空字串', () => {
    assert.equal(normalizePillValue(null), '');
    assert.equal(normalizePillValue(undefined), '');
    assert.equal(normalizePillValue(''), '');
    assert.equal(normalizePillValue('   '), '');
    assert.equal(normalizePillValue('  Moodyz  '), 'moodyz');
    assert.equal(normalizePillValue('MOODYZ'), 'moodyz');
    // 全形 → 半形（NFKC）後再小寫
    assert.equal(normalizePillValue('Ｍｏｏｄｙｚ'), 'moodyz');
});

// ===== addPill =====

test('addPill：重複呼叫同一（維度, 值）後 pills.length 不變', () => {
    const c = makeComponent();
    c.addPill('maker', 'Moodyz');
    c.addPill('maker', 'Moodyz');
    assert.equal(c.pills.length, 1);
});

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

test('addPill：dim/value 為 null/undefined/空字串/純空白 → pills 不變且不呼叫副作用', () => {
    const c = makeComponent();
    const cases = [
        [null, 'Moodyz'],
        [undefined, 'Moodyz'],
        ['', 'Moodyz'],
        ['maker', null],
        ['maker', undefined],
        ['maker', ''],
        ['maker', '   '],
    ];
    for (const [dim, value] of cases) {
        c.addPill(dim, value);
    }
    assert.equal(c.pills.length, 0);
    assert.equal(c.animateCalls, 0);
    assert.equal(c.heroCalls, 0);
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

test('removePill：不存在的（維度, 值）→ pills 不變且不呼叫副作用', () => {
    const c = makeComponent();
    c.addPill('maker', 'Moodyz');
    c.animateCalls = 0;
    c.heroCalls = 0;
    const before = c.pills;
    c.removePill('maker', 'S1');
    c.removePill('series', 'Moodyz');
    assert.equal(c.pills, before);
    assert.equal(c.pills.length, 1);
    assert.equal(c.animateCalls, 0);
    assert.equal(c.heroCalls, 0);
});

// ===== clearAllFilters =====

test('clearAllFilters：清 search 與 pills，即使已空仍執行 _animateFilter/_reconcileHeroCard 各 1 次', () => {
    // 已有內容
    const c1 = makeComponent({ search: 'hello', pills: [{ dim: 'maker', value: 'Moodyz' }] });
    c1.clearAllFilters();
    assert.equal(c1.search, '');
    assert.equal(c1.pills.length, 0);
    assert.equal(c1.animateCalls, 1);
    assert.equal(c1.heroCalls, 1);

    // 已空仍執行
    const c2 = makeComponent();
    c2.clearAllFilters();
    assert.equal(c2.search, '');
    assert.equal(c2.pills.length, 0);
    assert.equal(c2.animateCalls, 1);
    assert.equal(c2.heroCalls, 1);
});

// ===== call-count invariants（確實執行變更時恰好 1 次）=====

test('三個 mutation 在確實執行變更時，各自呼叫 _reconcileHeroCard 恰好 1 次', () => {
    const cAdd = makeComponent();
    cAdd.addPill('maker', 'Moodyz');
    assert.equal(cAdd.heroCalls, 1);

    const cRm = makeComponent({ pills: [{ dim: 'maker', value: 'Moodyz' }] });
    cRm.removePill('maker', 'Moodyz');
    assert.equal(cRm.heroCalls, 1);

    const cClr = makeComponent({ search: 'x', pills: [{ dim: 'maker', value: 'Moodyz' }] });
    cClr.clearAllFilters();
    assert.equal(cClr.heroCalls, 1);
});

test('三個 mutation 在確實執行變更時，各自呼叫 _animateFilter 恰好 1 次', () => {
    const cAdd = makeComponent();
    cAdd.addPill('maker', 'Moodyz');
    assert.equal(cAdd.animateCalls, 1);

    const cRm = makeComponent({ pills: [{ dim: 'maker', value: 'Moodyz' }] });
    cRm.removePill('maker', 'Moodyz');
    assert.equal(cRm.animateCalls, 1);

    const cClr = makeComponent({ search: 'x', pills: [{ dim: 'maker', value: 'Moodyz' }] });
    cClr.clearAllFilters();
    assert.equal(cClr.animateCalls, 1);
});

// ===== page / sort / order 不被 mutation 直接寫入 =====

test('addPill/removePill/clearAllFilters 不直接寫 page/sort/order', () => {
    const c = makeComponent();
    c.addPill('maker', 'Moodyz');
    assert.equal(c.page, 3);
    assert.equal(c.sort, 'title');
    assert.equal(c.order, 'asc');

    c.removePill('maker', 'Moodyz');
    assert.equal(c.page, 3);
    assert.equal(c.sort, 'title');
    assert.equal(c.order, 'asc');

    c.addPill('series', 'Madonna');
    c.search = 'hello';
    c.clearAllFilters();
    assert.equal(c.page, 3);
    assert.equal(c.sort, 'title');
    assert.equal(c.order, 'asc');
});

// ===== onSearchChange 不產生 pill =====

test('打字（onSearchChange）不產生任何 pill', () => {
    const c = makeComponent();
    c.search = 'Moodyz';
    c.onSearchChange();
    assert.equal(c.pills.length, 0);
});

// ===== 陣列整包替換（參照恆等性）=====

test('addPill/removePill 使用陣列整包替換（this.pills 與呼叫前非同一參照）', () => {
    const c = makeComponent();
    const beforeAdd = c.pills;
    c.addPill('maker', 'Moodyz');
    assert.notEqual(c.pills, beforeAdd);

    const beforeRm = c.pills;
    c.removePill('maker', 'Moodyz');
    assert.notEqual(c.pills, beforeRm);
});
