// TASK-115-T8: hero card 兩情況規則 —— _shouldShowHeroCard() 單一判斷點 ＋
// _reconcileHeroCard() 真身 ＋ 七個既有觸發點（CD-8 六個 ＋ RULING 1 併入 searchActressFilms）。
//
// state-videos.js / state-actress.js 用瀏覽器 importmap 別名 `@/showcase/...` 與
// `@/shared/...`，plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑（importmap 實際指到
// `pages/showcase/`）。比照 pill-state.test.mjs / pill-clear.test.mjs，本檔自帶與 base.html
// importmap 對齊的 resolve hook（不改共用 loader，FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。比照既有 showcase 測試先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
// TASK-138-T6：searchActressFilms / flipAndFadeIn 呼叫 window.scrollTo(0, 0)
if (typeof globalThis.window.scrollTo !== 'function') {
    globalThis.window.scrollTo = () => {};
}
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
const { stateActress } = await import('../state-actress.js');
// namespace import：_awaitHeroCardWithTimeout 在產品碼尚未 export 時，具名解構會讓整檔載入失敗；
// 用 namespace 才能讓「產品碼還沒改」以斷言紅（而非 loader 炸）呈現。
const stateBaseMod = await import('../state-base.js');
const { _setActresses } = stateBaseMod;


/**
 * 合併 stateVideos()＋stateActress()（比照 main.js 的 mergeState），保留
 * `_shouldShowHeroCard`/`_reconcileHeroCard`/`_checkPreciseActressMatch`/`_clearPreciseMatch`/
 * `_isExpectedHeroCardTerm` 五個真身——本檔多數測試要驗證的正是這五個方法「合起來」的行為，
 * 不能全部 spy 掉。DOM／動畫／網路相關依賴另外 stub（本 task 不觸碰那些邊界）。
 */
function makeComponent(overrides) {
    const c = Object.assign({}, stateVideos(), stateActress(), {
        pills: [],
        search: '',
        actressSearch: '',
        mode: 'grid',
        showFavoriteActresses: false,
        lightboxOpen: false,
        _animGeneration: 0,
        _ghostFlyInFlight: false,
        page: 1,
        sort: 'date',
        order: 'desc',
        animateCalls: 0,
        actressFilterCalls: 0,
        saveCalls: 0,
        applyFilterAndSort() {},
        applyActressFilterAndSort() { c.actressFilterCalls++; },
        saveState() { c.saveCalls++; },
        showToast() {},
        closeLightbox() {},
        closeActressLightbox() {},
        $nextTick() {},   // no-op：本檔測試只驗證同步／await 得到的 state，不依賴 tick 後動畫
        $watch() {},
        _getActiveGrid() { return null; },
    }, overrides);
    c._animateFilter = function () { c.animateCalls++; };
    return c;
}

// ===== _reconcileHeroCard 整合真值表（透過真身 _checkPreciseActressMatch/_clearPreciseMatch）=====

test('無 pill ＋ 命中收藏女優的自由文字 → 顯示（回歸保護，spec AC8）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [], search: 'Foo' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress.name, 'Foo');
});

test('hero card 隱藏表：有 pill 時，只有「恰 1 枚女優 pill ＋ 空文字」才顯示，其餘（pill 加自由文字／2 枚 pill／非女優 pill）一律隱藏', async () => {
    // [pills, search]；皆預期 _isPreciseActressMatch === false（predicate 必須真的擋下，見本檔「突變自驗 #1」）
    const cases = [
        [[{ dim: 'actress', value: 'Foo' }], 'bar'],
        [[{ dim: 'actress', value: 'Foo' }, { dim: 'maker', value: 'Moodyz' }], 'Foo'],
        [[{ dim: 'maker', value: 'Moodyz' }], ''],
    ];
    for (const [pills, search] of cases) {
        _setActresses([{ name: 'Foo', is_favorite: true }]);
        const c = makeComponent({ pills, search });
        await c._reconcileHeroCard();
        assert.equal(c._isPreciseActressMatch, false, JSON.stringify({ pills, search }));
    }
});

// ===== 可逆性（CD-8 的核心要求：不是只在「加」的時候判斷）=====


// ===== 既有觸發點（斷言重算後的 hero 狀態，不數呼叫次數）=====

test('call site 6/9 — clearAllFilters() 後 hero 狀態依規則重算（清掉 pill 與文字 → 大卡收起）', () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        search: 'x',
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        _isPreciseActressMatch: true,
        _matchedActress: { name: 'Foo', is_favorite: true },
    });
    c.clearAllFilters();
    assert.equal(c.pills.length, 0);
    assert.equal(c._isPreciseActressMatch, false, '清除後無 pill 無文字 → 大卡必須收起，不得停在舊的顯示狀態');
    assert.equal(c._matchedActress, null);
});

// 129-T3 補登記：_setReleasePill()（v0.14.4 / 124a 加的發售日 pill 寫入者）從當時起就會
// 呼叫 _reconcileHeroCard()，但一直沒被登記進這組編號契約——分母從那時候起就是錯的。
// 這組契約存在的目的正是「誰會觸發它，一個都不能漏」，所以本 task 把分母補正成 9 並補上這條。

// ===== 129-T3：call site 8/9 — init() 回頁重算大卡（S2）=====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：切回影片牆掛著收藏女優 pill 時大卡要重新出現，不必再點一次

// ===== RULING 1：searchActressFilms() 必須尊重「有 pill」的 gating 規則 =====

test('RULING 1：帶著非女優 pill 點「查看她的作品」不應違規顯示 hero card', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        showFavoriteActresses: false,
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        search: '',
    });
    await c.searchActressFilms('Foo', null);
    assert.equal(c._isPreciseActressMatch, false, '有非女優 pill 時，即使文字命中收藏女優也不該顯示');
});


// ===== spec §4.10：模式來回切換，pills 不變且 hero card 狀態依當下組合正確 =====


// ===== staleness guard 修復（本 task 最容易漏掉的一步；沒修好會是靜默 no-op，call-count 斷言驗不到）=====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：大小寫／全半形不同的女優 pill 加入後大卡不得被當過期丟掉

// ===== source === 'pill' 找不到本地收藏記錄仍放行（與 'metadata' 行為等價）=====

// [lint-guard: node-justified] 162e 暫留：求值型行為測試（lint 無 JS 求值能力）；R1：尚未收藏的女優加 pill 後大卡仍要顯示以保留收藏入口
test("source === 'pill' 找不到本地收藏記錄仍放行，_matchedActress 為非收藏最小物件", () => {
    _setActresses([{ name: 'SomeoneElse', is_favorite: true }]);
    const c = makeComponent({ pills: [{ dim: 'actress', value: 'NotFavorited' }], search: '' });
    c._checkPreciseActressMatch('NotFavorited', 'pill');
    assert.equal(c._isPreciseActressMatch, true);
    assert.deepEqual(c._matchedActress, { name: 'NotFavorited', is_favorite: false });
});

// ===== Opus review 補洞：call site 1 與 3 原本只用 spy 驗「有沒有被呼叫」 =====
//
// 那兩支把 _reconcileHeroCard 整個換成計數器，於是「呼叫了，但算出來的
// _isPreciseActressMatch 是錯的」會全綠——DoD 要的是值斷言，不是 call-count。
// 其餘五個呼叫點在別處已有真身覆蓋，這裡把缺的兩個補齊（走真身，不 stub）。

test('call site 1/9（真身）— onSearchChange() 有 pill 時，hero 狀態必須被關掉', () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        search: 'Foo',
        pills: [{ dim: 'maker', value: 'Moodyz' }],   // 有 pill ＋ 有文字 → spec §4.8 不顯示
        _isPreciseActressMatch: true,                  // 先假設殘留為顯示中
        _matchedActress: { name: 'Foo', is_favorite: true },
    });
    c._animateFilter = () => {};
    c.onSearchChange();
    assert.equal(c._isPreciseActressMatch, false, '有 pill＋有文字時 onSearchChange 必須把 hero 關掉');
    assert.equal(c._matchedActress, null);
});

test('call site 3/9（真身）— confirmRemoveActress() 後 hero 狀態依規則重算，非只被呼叫', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        _pendingRemoveActressName: 'Foo',
        currentLightboxActress: { name: 'Foo' },
        search: '',
        pills: [{ dim: 'maker', value: 'Moodyz' }],   // 有非女優 pill → 不該顯示
        _isPreciseActressMatch: true,
        _matchedActress: { name: 'Foo', is_favorite: true },
    });
    const prevFetch = globalThis.fetch;
    globalThis.fetch = async () => ({ json: async () => ({ success: true }) });
    try {
        await c.confirmRemoveActress();
    } finally {
        globalThis.fetch = prevFetch;
    }
    assert.equal(c._isPreciseActressMatch, false, '移除最愛後仍須依 pill 規則重算，不得停在舊的顯示狀態');
    assert.equal(c._matchedActress, null);
});

// ===== TASK-138-T1：_awaitHeroCardWithTimeout 行為（import 真身，不 stub）=====
// HERO_CARD_RECONCILE_TIMEOUT_MS = 300（卡死保險）；四案例對應 card 補充段第 2 條。


test('_awaitHeroCardWithTimeout：promise 慢於逾時 → 包裝在逾時點 resolve，且原 promise 仍跑到完成', async () => {
    const fn = stateBaseMod._awaitHeroCardWithTimeout;
    assert.equal(typeof fn, 'function', '_awaitHeroCardWithTimeout 必須是 module-level export function');
    let originalFinished = false;
    const slow = new Promise((resolve) => {
        setTimeout(() => { originalFinished = true; resolve(); }, 500);
    });
    const t0 = Date.now();
    await fn(slow);
    const elapsed = Date.now() - t0;
    assert.ok(elapsed >= 250 && elapsed < 450, `應約在 300ms 逾時點 resolve，實際耗時 ${elapsed}ms`);
    assert.equal(originalFinished, false, '逾時點當下原 promise 尚未完成（證明包裝沒有空等它）');
    await slow;
    assert.equal(originalFinished, true, '原 promise 必須繼續跑到完成（CD-C3：不得取消 in-flight）');
});


test('_awaitHeroCardWithTimeout：傳入會 reject 的 promise → 包裝仍 resolve、不產生 unhandled rejection', async () => {
    const fn = stateBaseMod._awaitHeroCardWithTimeout;
    assert.equal(typeof fn, 'function', '_awaitHeroCardWithTimeout 必須是 module-level export function');
    const unhandled = [];
    const onUnhandled = (reason) => { unhandled.push(reason); };
    process.on('unhandledRejection', onUnhandled);
    try {
        await fn(Promise.reject(new Error('boom')));
        // 給 microtask 一個機會浮出 unhandled rejection
        await new Promise((r) => setImmediate(r));
        assert.equal(unhandled.length, 0, '不得產生 unhandled rejection');
    } finally {
        process.off('unhandledRejection', onUnhandled);
    }
});
