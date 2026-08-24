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
import { readFileSync } from 'node:fs';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。比照既有 showcase 測試先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
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
const { _setActresses } = await import('../state-base.js');

const STATE_BASE_SRC = readFileSync(new URL('../state-base.js', import.meta.url), 'utf8');

/** 抽「<sig> 起的下一個 `{` 開始 brace-match 到對應 `}`」的函式 body。 */
function extractFnBody(code, sig, label) {
    const sigIdx = code.indexOf(sig);
    assert.ok(sigIdx >= 0, `原始碼應含 \`${sig}\`（${label}）`);
    const open = code.indexOf('{', sigIdx);
    assert.ok(open >= 0, `${label} 應有 {`);
    let depth = 0;
    for (let i = open; i < code.length; i++) {
        const ch = code[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return code.slice(open + 1, i);
        }
    }
    throw new Error(`${label} 大括號未閉合（brace-match 失敗）`);
}

function countOccurrences(haystack, needle) {
    let count = 0;
    let idx = 0;
    while ((idx = haystack.indexOf(needle, idx)) !== -1) {
        count++;
        idx += needle.length;
    }
    return count;
}

/**
 * 從 init() 體內 applyFilterAndSort(true)～page=savedPage 之間抽出含
 * `_reconcileHeroCard` 的那一行（剝行尾註解），以 component 為 this 執行。
 * 行為契約必須跑產品碼那一行本身，否則 mutation 拿掉 guard／讓呼叫失效時測不到。
 */
function runInitReconcileLine(c) {
    const body = extractFnBody(STATE_BASE_SRC, 'async init()', 'init');
    const applyIdx = body.indexOf('this.applyFilterAndSort(true)');
    const pageIdx = body.indexOf('this.page = savedPage');
    assert.ok(applyIdx >= 0 && pageIdx >= 0, 'init() 應含 applyFilterAndSort(true) 與 page = savedPage');
    assert.ok(applyIdx < pageIdx, 'applyFilterAndSort(true) 應在 page = savedPage 之前');
    const between = body.slice(applyIdx, pageIdx);
    const lineMatch = between.match(/[^\n]*_reconcileHeroCard[^\n]*/);
    assert.ok(lineMatch, 'init() 在 applyFilterAndSort(true) 與 page = savedPage 之間應含 _reconcileHeroCard');
    const line = lineMatch[0].replace(/\/\/[^\n]*$/, '').trim();
    return (function () { return eval(line); }).call(c);
}

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

// ===== _shouldShowHeroCard 真值表 =====

test('_shouldShowHeroCard 真值表：pills.length / dim / search 六種組合', () => {
    const c = makeComponent();
    c.pills = []; c.search = 'anything';
    assert.equal(c._shouldShowHeroCard(), true, '無 pill：完全不限制（交給既有邏輯判斷）');
    c.pills = []; c.search = '';
    assert.equal(c._shouldShowHeroCard(), true, '無 pill：完全不限制');
    c.pills = [{ dim: 'actress', value: 'Foo' }]; c.search = '';
    assert.equal(c._shouldShowHeroCard(), true, '1 枚女優 pill ＋ 空文字 → 允許顯示');
    c.pills = [{ dim: 'actress', value: 'Foo' }]; c.search = 'x';
    assert.equal(c._shouldShowHeroCard(), false, '1 枚女優 pill ＋ 非空文字 → 不顯示');
    c.pills = [{ dim: 'actress', value: 'Foo' }, { dim: 'maker', value: 'M' }]; c.search = '';
    assert.equal(c._shouldShowHeroCard(), false, '≥2 pill → 不顯示');
    c.pills = [{ dim: 'maker', value: 'M' }]; c.search = '';
    assert.equal(c._shouldShowHeroCard(), false, '1 枚非女優 pill → 不顯示');
});

// ===== _reconcileHeroCard 整合真值表（透過真身 _checkPreciseActressMatch/_clearPreciseMatch）=====

test('無 pill ＋ 命中收藏女優的自由文字 → 顯示（回歸保護，spec AC8）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [], search: 'Foo' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress.name, 'Foo');
});

test('無 pill ＋ 無文字 → 不顯示', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [], search: '' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, false);
});

test('1 枚女優 pill ＋ 空文字 → 顯示', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [{ dim: 'actress', value: 'Foo' }], search: '' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress.name, 'Foo');
});

test('1 枚女優 pill ＋ 非空文字 → 不顯示（pill 加自由文字不顯示）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [{ dim: 'actress', value: 'Foo' }], search: 'bar' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, false);
});

test('2 枚 pill（其一女優）＋ 命中收藏女優的自由文字 → 不顯示（predicate 必須真的擋下，' +
    '不能只是巧合般都導向清空——見本檔「突變自驗 #1」）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        pills: [{ dim: 'actress', value: 'Foo' }, { dim: 'maker', value: 'Moodyz' }],
        search: 'Foo',
    });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, false);
});

test('1 枚非女優 pill → 不顯示', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [{ dim: 'maker', value: 'Moodyz' }], search: '' });
    await c._reconcileHeroCard();
    assert.equal(c._isPreciseActressMatch, false);
});

// ===== 可逆性（CD-8 的核心要求：不是只在「加」的時候判斷）=====

test('可逆性：加第二枚 pill → 隱藏；移除該 pill → 卡重新出現', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [], search: '' });

    c.addPill('actress', 'Foo');
    await null;
    assert.equal(c._isPreciseActressMatch, true, '第一枚女優 pill 應顯示卡');
    assert.equal(c._matchedActress?.name, 'Foo');

    c.addPill('maker', 'Moodyz');
    await null;
    assert.equal(c._isPreciseActressMatch, false, '加第二枚 pill 後應隱藏');

    c.removePill('maker', 'Moodyz');
    await null;
    assert.equal(c._isPreciseActressMatch, true, '移除第二枚 pill 後應重新顯示（CD-8 可逆性）');
    assert.equal(c._matchedActress?.name, 'Foo');
});

// ===== 七個既有觸發點 =====

test('call site 1/9 — onSearchChange() 觸發 _reconcileHeroCard', () => {
    const c = makeComponent({ search: 'Foo' });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c.onSearchChange();
    assert.equal(calls, 1);
});

test('call site 2/9 — toggleActressMode() 切回影片模式分支無條件觸發 _reconcileHeroCard', () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ showFavoriteActresses: true, search: '' });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c.toggleActressMode();
    assert.equal(calls, 1);
});

test('call site 3/9 — confirmRemoveActress() 移除成功且仍在檢視該女優時觸發 _reconcileHeroCard', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        _pendingRemoveActressName: 'Foo',
        currentLightboxActress: { name: 'Foo' },
        search: '',
    });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    const prevFetch = globalThis.fetch;
    globalThis.fetch = async () => ({ json: async () => ({ success: true }) });
    try {
        await c.confirmRemoveActress();
    } finally {
        globalThis.fetch = prevFetch;
    }
    assert.equal(calls, 1);
});

test('call site 4/9 — addPill() 觸發 _reconcileHeroCard', () => {
    const c = makeComponent();
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c.addPill('maker', 'Moodyz');
    assert.equal(calls, 1);
});

test('call site 5/9 — removePill() 觸發 _reconcileHeroCard', () => {
    const c = makeComponent({ pills: [{ dim: 'maker', value: 'Moodyz' }] });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c.removePill('maker', 'Moodyz');
    assert.equal(calls, 1);
});

test('call site 6/9 — clearAllFilters() 觸發 _reconcileHeroCard', () => {
    const c = makeComponent({ search: 'x', pills: [{ dim: 'maker', value: 'Moodyz' }] });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c.clearAllFilters();
    assert.equal(calls, 1);
});

test('call site 7/9 — searchActressFilms()（RULING 1 併入的第 7 個呼叫點）觸發 _reconcileHeroCard', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ showFavoriteActresses: false, pills: [], search: '' });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    await c.searchActressFilms('Foo', null);
    assert.equal(calls, 1);
});

// 129-T3 補登記：_setReleasePill()（v0.14.4 / 124a 加的發售日 pill 寫入者）從當時起就會
// 呼叫 _reconcileHeroCard()，但一直沒被登記進這組編號契約——分母從那時候起就是錯的。
// 這組契約存在的目的正是「誰會觸發它，一個都不能漏」，所以本 task 把分母補正成 9 並補上這條。
test('call site 9/9 — _setReleasePill() 觸發 _reconcileHeroCard（124a 起就漏登記的那一個）', () => {
    const c = makeComponent({ search: '', pills: [] });
    let calls = 0;
    c._reconcileHeroCard = () => { calls++; };
    c._setReleasePill({ dim: 'release', op: '=', value: '2024-09' });
    assert.equal(calls, 1);
    assert.equal(c.pills.length, 1, '_setReleasePill 應真的寫進一枚 release pill');
    assert.equal(c.pills[0].dim, 'release');
});

// ===== 129-T3：call site 8/9 — init() 回頁重算大卡（S2）=====

test('init() 源碼形狀：_reconcileHeroCard 帶 showFavoriteActresses guard，位於 applyFilterAndSort(true) 之後、page = savedPage 之前', () => {
    const body = extractFnBody(STATE_BASE_SRC, 'async init()', 'init');
    const applyLit = 'this.applyFilterAndSort(true)';
    const pageLit = 'this.page = savedPage';
    const reconcileLit = '_reconcileHeroCard()';
    assert.equal(countOccurrences(body, applyLit), 1, 'init() 體內 applyFilterAndSort(true) 應恰好一次');
    assert.equal(countOccurrences(body, pageLit), 1, 'init() 體內 page = savedPage 應恰好一次');
    assert.equal(countOccurrences(body, reconcileLit), 1, 'init() 體內 _reconcileHeroCard() 應恰好一次');
    assert.ok(
        /if\s*\(\s*!this\.showFavoriteActresses\s*\)\s*this\._reconcileHeroCard\(\)/.test(body),
        'init() 的 _reconcileHeroCard 呼叫必須帶 !this.showFavoriteActresses guard',
    );
    const applyIdx = body.indexOf(applyLit);
    const pageIdx = body.indexOf(pageLit);
    const reconcileIdx = body.indexOf(reconcileLit);
    assert.ok(
        applyIdx < reconcileIdx && reconcileIdx < pageIdx,
        '_reconcileHeroCard() 必須在 applyFilterAndSort(true) 之後、page = savedPage 之前',
    );
});

test('call site 8/9 — init() 回頁重算大卡（S2）：影片牆＋女優 pill 觸發 _reconcileHeroCard（真身）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        showFavoriteActresses: false,
        pills: [{ dim: 'actress', value: 'Foo' }],
        search: '',
    });
    let calls = 0;
    const real = c._reconcileHeroCard.bind(c);
    c._reconcileHeroCard = function (...args) {
        calls++;
        return real(...args);
    };
    await runInitReconcileLine(c);
    assert.equal(calls, 1);
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress?.name, 'Foo');
});

test('女優牆：init() 回頁不得呼叫 _reconcileHeroCard，狀態不得被污染', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        showFavoriteActresses: true,
        pills: [{ dim: 'actress', value: 'Foo' }],
        search: '',
        _isPreciseActressMatch: false,
        _matchedActress: null,
    });
    let calls = 0;
    const real = c._reconcileHeroCard.bind(c);
    c._reconcileHeroCard = function (...args) {
        calls++;
        return real(...args);
    };
    await runInitReconcileLine(c);
    assert.equal(calls, 0, '女優牆不得呼叫 _reconcileHeroCard');
    assert.equal(c._isPreciseActressMatch, false, '女優牆不得污染 _isPreciseActressMatch');
    assert.equal(c._matchedActress, null, '女優牆不得污染 _matchedActress');
});

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

test('無 pill 時 searchActressFilms() 仍能顯示 hero card（既有行為不回歸）', async () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ showFavoriteActresses: false, pills: [], search: '' });
    await c.searchActressFilms('Foo', null);
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress?.name, 'Foo');
});

// ===== spec §4.10：模式來回切換，pills 不變且 hero card 狀態依當下組合正確 =====

test('spec §4.10：切到女優模式再切回，pills 內容不變、hero card 狀態依當下組合正確', () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({
        showFavoriteActresses: false,
        pills: [{ dim: 'actress', value: 'Foo' }],
        search: '',
    });
    const pillsBefore = c.pills;
    c.toggleActressMode();   // 進入女優模式
    assert.equal(c.showFavoriteActresses, true);
    assert.deepEqual(c.pills, pillsBefore, 'pills 內容不變');
    c.toggleActressMode();   // 切回影片模式
    assert.equal(c.showFavoriteActresses, false);
    assert.deepEqual(c.pills, pillsBefore, 'pills 內容仍不變');
    assert.equal(c._isPreciseActressMatch, true, '切回後仍是「1 枚女優 pill + 空文字」組合，應顯示');
    assert.equal(c._matchedActress?.name, 'Foo');
});

// ===== staleness guard 修復（本 task 最容易漏掉的一步；沒修好會是靜默 no-op，call-count 斷言驗不到）=====

test('staleness guard：pill 驅動時 this.search 為空，比對仍能通過（不會被誤判為過期而擋下）', () => {
    _setActresses([{ name: 'Foo', is_favorite: true }]);
    const c = makeComponent({ pills: [{ dim: 'actress', value: 'Foo' }], search: '' });
    // 直接呼叫 _checkPreciseActressMatch，繞過 _reconcileHeroCard，鎖定 staleness guard 本身
    // ——若 guard 沿用舊的 `this.search.trim() !== capturedTerm` 單一比較式，
    // this.search=''、capturedTerm='Foo' 必然不相等，函式會提前 return，此斷言就會失敗。
    c._checkPreciseActressMatch('Foo', 'pill');
    assert.equal(c._isPreciseActressMatch, true);
    assert.equal(c._matchedActress?.name, 'Foo');
});

test("_isExpectedHeroCardTerm：'manual'/'metadata' 兩條既有路徑逐位元組不變（比對 this.search）", () => {
    const c = makeComponent({ search: 'Foo', pills: [] });
    assert.equal(c._isExpectedHeroCardTerm('Foo', 'manual'), true);
    assert.equal(c._isExpectedHeroCardTerm('Bar', 'manual'), false);
    assert.equal(c._isExpectedHeroCardTerm('Foo', 'metadata'), true);
});

test('_isExpectedHeroCardTerm：pill 分支用 normalizePillValue 比對（大小寫/半形差異也算符合）', () => {
    const c = makeComponent({ pills: [{ dim: 'actress', value: 'FOO' }], search: '' });
    assert.equal(c._isExpectedHeroCardTerm('foo', 'pill'), true);
});

// ===== source === 'pill' 找不到本地收藏記錄仍放行（與 'metadata' 行為等價）=====

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
