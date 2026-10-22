// TASK-115-T7 / 129-T1a: clearAllFilters 唯一擁有者。
// 覆蓋：清除只清當前分頁（另一分頁的搜尋字／pill／精準比對狀態不動）、影片牆清除重置 hero card、
// 清除後存檔；另有捲動守衛的原始碼結構檢查（node-justified 暫留）。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑
// （importmap 實際指到 `pages/showcase/`）。比照 pill-state.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync } from 'node:fs';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;

// clearAllFilters 寫 Alpine.store('ui').toolbarOpen
const uiStore = { toolbarOpen: true, showcaseHasSearch: false };
globalThis.Alpine = {
    store: (name) => (name === 'ui' ? uiStore : {}),
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
const { stateBase } = await import('../state-base.js');

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const STATE_BASE_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-base.js'),
    'utf8',
);

/** 清除路徑用 harness：預設 spy _animateFilter；saveState 路徑另有專用測試。 */
function makeClearComponent(overrides) {
    uiStore.toolbarOpen = true;
    uiStore.showcaseHasSearch = false;
    const c = Object.assign({}, stateVideos(), {
        pills: [],
        actressPills: [],
        search: '',
        actressSearch: '',
        page: 1,
        sort: 'date',
        order: 'desc',
        mode: 'table',
        animateCalls: 0,
        heroCalls: 0,
        preciseClearCalls: 0,
        actressFilterCalls: 0,
        saveCalls: 0,
        _isPreciseActressMatch: false,
        _matchedActress: null,
        _clearPreciseMatch() {
            c.preciseClearCalls++;
            c._isPreciseActressMatch = false;
            c._matchedActress = null;
        },
        _checkPreciseActressMatch() {},
        applyActressFilterAndSort() { c.actressFilterCalls++; },
        applyFilterAndSort() {},
        saveState() { c.saveCalls++; },
        $nextTick(fn) { fn(); },
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    c._reconcileHeroCard = function () { c.heroCalls++; };
    return c;
}

// ===== clearAllFilters 清空正確性 =====

test('clearAllFilters：影片牆清除不得清掉 actressSearch／actressPills', () => {
    const c = makeClearComponent({
        showFavoriteActresses: false,
        search: 'hello',
        actressSearch: '三上悠亜',
        pills: [{ dim: 'maker', value: 'S1' }],
        actressPills: [{ dim: 'age', op: '=', value: '37' }],
    });
    c.clearAllFilters();
    assert.equal(c.actressSearch, '三上悠亜', '影片牆清除不得清掉 actressSearch');
    assert.deepEqual(c.actressPills, [{ dim: 'age', op: '=', value: '37' }], '影片牆清除不得清掉 actressPills');
    assert.equal(c.search, '', '影片牆 search 應清空');
    assert.equal(c.pills.length, 0, '影片牆 pills 應清空');
});


// TASK-115-T8（RULING 3）：T7 留下的直接 `this._clearPreciseMatch()` 呼叫已移除——
// pills=[]、search='' 之後，_reconcileHeroCard() 的「無 pill 分支」本來就會走到同一個
// _clearPreciseMatch() 呼叫（單一判斷點，不再由 clearAllFilters() 自己宣稱一次權威）。
// 這裡改用 _reconcileHeroCard 真身（仍計數）取代純 spy，證明「清除的工作只做一次、
// 且真的透過 _reconcileHeroCard 達成」，而不是弱化斷言去掩蓋這次合併。

// ===== call-count：一次 clear 各副作用恰好 1 次 =====


test('clearAllFilters：女優牆一次點擊恰好 1 次 saveState', () => {
    uiStore.toolbarOpen = true;
    const c = makeClearComponent({
        showFavoriteActresses: true,
        actressSearch: '三上悠亜',
        actressPills: [{ dim: 'age', op: '=', value: '37' }],
    });
    c.clearAllFilters();
    assert.equal(c.saveCalls, 1, '女優牆 saveState 必須恰好 1 次（=== 1，不是 >= 1）');
    assert.equal(c.actressFilterCalls, 1);
    assert.equal(c.animateCalls, 0);
    assert.equal(c.heroCalls, 0);
});

/** stateBase 在 factory 內用 this.$persist；node harness 需 stub（比照 pill-entry / pill-persist）。 */
function makeBase() {
    return stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
}

// ===== _hasActiveFilterForCurrentTab 判準（129-T1a：依分頁二選一）=====

test('_hasActiveFilterForCurrentTab：影片牆只看 search/pills，女優牆狀態不得讓它為真', () => {
    const pred = makeBase()._hasActiveFilterForCurrentTab;
    assert.equal(typeof pred, 'function');

    const base = { showFavoriteActresses: false, search: '', actressSearch: '', pills: [], actressPills: [] };
    assert.equal(pred.call({ ...base, search: 'x' }), true, '影片牆僅 search');
    assert.equal(
        pred.call({ ...base, pills: [{ dim: 'maker', value: 'M' }] }),
        true,
        '影片牆僅 pills',
    );
    assert.equal(pred.call({ ...base, actressSearch: 'y' }), false, '影片牆有 actressSearch 不得為真');
    assert.equal(
        pred.call({ ...base, actressPills: [{ dim: 'age', op: '=', value: '37' }] }),
        false,
        '影片牆有 actressPills 不得為真',
    );
    assert.equal(pred.call(base), false, '影片牆全空');
});


// ===== 捲動自動收合守衛（PR#131 P3 回歸鎖；129-T1a 改用分頁感知判準）=====

// [lint-guard: node-justified] 162e 暫留：缺 block-comment 剝除欄位（只有 stripLineComments 不剝 /* */），required 會被區塊註解餵飽；混合子斷言不拆
