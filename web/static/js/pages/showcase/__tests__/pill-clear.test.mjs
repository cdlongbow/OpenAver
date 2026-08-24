// TASK-115-T7 / 129-T1a: clearAllFilters 唯一擁有者 ＋ showcaseHasSearch /
// _hasActiveFilterForCurrentTab 契約。
// 覆蓋：清除清掉 search/actressSearch/pills、toolbar 收合、precise-match reset、
// 一次 clear 恰好一次 _animateFilter／saveState、predicate 依分頁二選一、clearSearch 已刪、
// 五個 $watch + init 共用 _hasActiveFilterForCurrentTab、showcase.html 改接 clearAllFilters。
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
const STATE_VIDEOS_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-videos.js'),
    'utf8',
);
const SHOWCASE_HTML = readFileSync(
    path.join(REPO_ROOT, 'web/templates/showcase.html'),
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

test('clearAllFilters：僅有 pills（無文字）時清空 pills', () => {
    const c = makeClearComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }, { dim: 'series', value: 'Madonna' }],
        actressPills: [{ dim: 'age', op: '=', value: '37' }],
    });
    c.clearAllFilters();
    assert.equal(c.pills.length, 0);
    assert.equal(c.actressPills.length, 0);
    assert.equal(c.search, '');
    assert.equal(c.actressSearch, '');
});

test('clearAllFilters：同時清空 search 與 actressSearch（女優模式回歸）', () => {
    const c = makeClearComponent({
        search: 'hello',
        actressSearch: '三上悠亜',
        pills: [{ dim: 'maker', value: 'S1' }],
    });
    c.clearAllFilters();
    assert.equal(c.search, '');
    assert.equal(c.actressSearch, '');
    assert.equal(c.pills.length, 0);
});

test('clearAllFilters：收合 toolbar（Alpine.store ui.toolbarOpen = false）', () => {
    const c = makeClearComponent({ search: 'x' });
    uiStore.toolbarOpen = true;
    c.clearAllFilters();
    assert.equal(uiStore.toolbarOpen, false);
});

// TASK-115-T8（RULING 3）：T7 留下的直接 `this._clearPreciseMatch()` 呼叫已移除——
// pills=[]、search='' 之後，_reconcileHeroCard() 的「無 pill 分支」本來就會走到同一個
// _clearPreciseMatch() 呼叫（單一判斷點，不再由 clearAllFilters() 自己宣稱一次權威）。
// 這裡改用 _reconcileHeroCard 真身（仍計數）取代純 spy，證明「清除的工作只做一次、
// 且真的透過 _reconcileHeroCard 達成」，而不是弱化斷言去掩蓋這次合併。
test('clearAllFilters：重置 precise-actress-match／愛心狀態（經由 _reconcileHeroCard 真身收斂）', () => {
    const c = makeClearComponent({
        search: '三上悠亜',
        _isPreciseActressMatch: true,
        _matchedActress: { name: '三上悠亜', is_favorite: false },
    });
    const realReconcile = stateVideos()._reconcileHeroCard;
    c._reconcileHeroCard = function () { c.heroCalls++; return realReconcile.call(c); };
    c.clearAllFilters();
    assert.equal(c.preciseClearCalls, 1);
    assert.equal(c._isPreciseActressMatch, false);
    assert.equal(c._matchedActress, null);
});

// ===== call-count：一次 clear 各副作用恰好 1 次 =====

// TASK-115-T8（RULING 3）：同上——_reconcileHeroCard 改用真身（仍計數），
// preciseClearCalls 現在驗證的是「clearAllFilters → _reconcileHeroCard → _clearPreciseMatch」
// 這條間接鏈路恰好一次，不再是 clearAllFilters 直接呼叫。
test('clearAllFilters：一次點擊恰好 1 次 _animateFilter / applyActressFilterAndSort / _reconcileHeroCard / _clearPreciseMatch', () => {
    const c = makeClearComponent({
        search: 'x',
        actressSearch: 'y',
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        _isPreciseActressMatch: true,
    });
    const realReconcile = stateVideos()._reconcileHeroCard;
    c._reconcileHeroCard = function () { c.heroCalls++; return realReconcile.call(c); };
    c.clearAllFilters();
    assert.equal(c.animateCalls, 1);
    assert.equal(c.actressFilterCalls, 1);
    assert.equal(c.heroCalls, 1);
    assert.equal(c.preciseClearCalls, 1);
});

// TASK-115-T8（RULING 3）：同上——不再 stub _reconcileHeroCard 為純 spy，改保留
// stateVideos() 合併進來的真身（Object.assign 已含，這裡只加計數 wrapper），
// 讓 preciseClearCalls 真的驗到「clearAllFilters → _reconcileHeroCard → _clearPreciseMatch」
// 這條鏈路，而不是驗一個永遠不會呼叫 _clearPreciseMatch 的假 spy。
test('clearAllFilters：一次點擊恰好 1 次 saveState（真身 _animateFilter + mode:table）', () => {
    // 不 stub _animateFilter，改 stub 其內部依賴，讓真身跑到 saveState 那一行。
    // mode:'table' 避開 DOM capture 分支（querySelector / ShowcaseAnimations）。
    uiStore.toolbarOpen = true;
    const c = Object.assign({}, stateVideos(), {
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        search: 'hello',
        actressSearch: 'world',
        mode: 'table',
        page: 1,
        sort: 'date',
        order: 'desc',
        saveCalls: 0,
        preciseClearCalls: 0,
        actressFilterCalls: 0,
        heroCalls: 0,
        _clearPreciseMatch() { c.preciseClearCalls++; },
        applyActressFilterAndSort() { c.actressFilterCalls++; },
        applyFilterAndSort() {},
        saveState() { c.saveCalls++; },
        $nextTick(fn) { fn(); },
        _getActiveGrid() { return null; },
    });
    // 保留 stateVideos 的真身 _animateFilter 與 _reconcileHeroCard（後者只加計數 wrapper）
    assert.equal(typeof c._animateFilter, 'function');
    const realReconcile = c._reconcileHeroCard;
    c._reconcileHeroCard = function () { c.heroCalls++; return realReconcile.call(c); };
    c.clearAllFilters();
    assert.equal(c.saveCalls, 1, 'saveState 必須恰好 1 次（=== 1，不是 >= 1）');
    assert.equal(c.preciseClearCalls, 1);
    assert.equal(c.actressFilterCalls, 1);
    assert.equal(c.heroCalls, 1);
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

test('_hasActiveFilterForCurrentTab：女優牆只看 actressSearch/actressPills，影片牆狀態不得讓它為真', () => {
    const pred = makeBase()._hasActiveFilterForCurrentTab;
    assert.equal(typeof pred, 'function');

    const base = { showFavoriteActresses: true, search: '', actressSearch: '', pills: [], actressPills: [] };
    assert.equal(pred.call({ ...base, actressSearch: 'y' }), true, '女優牆僅 actressSearch');
    assert.equal(
        pred.call({ ...base, actressPills: [{ dim: 'age', op: '=', value: '37' }] }),
        true,
        '女優牆僅 actressPills',
    );
    assert.equal(pred.call({ ...base, search: 'x' }), false, '女優牆有 search 不得為真');
    assert.equal(
        pred.call({ ...base, pills: [{ dim: 'maker', value: 'M' }] }),
        false,
        '女優牆有 pills 不得為真',
    );
    assert.equal(pred.call(base), false, '女優牆全空');
});

// ===== clearSearch 已刪 =====

test('clearSearch 不再存在於 stateBase／stateVideos 合併元件', () => {
    const base = makeBase();
    assert.equal(typeof base.clearSearch, 'undefined');
    assert.equal(typeof stateVideos().clearSearch, 'undefined');
    // 合併後也不該有
    const merged = Object.assign({}, base, stateVideos());
    assert.equal(typeof merged.clearSearch, 'undefined');
    assert.equal(typeof merged.clearAllFilters, 'function');
    assert.equal(typeof merged._hasActiveFilterForCurrentTab, 'function');
});

test('全庫產品碼無 clearSearch 字面殘留（state-base / state-videos / showcase.html）', () => {
    assert.equal(STATE_BASE_SRC.includes('clearSearch'), false);
    assert.equal(STATE_VIDEOS_SRC.includes('clearSearch'), false);
    assert.equal(SHOWCASE_HTML.includes('clearSearch'), false);
});

// ===== 結構：五個 $watch + init 共用 _hasActiveFilterForCurrentTab；$watch('showFavoriteActresses') 存在 =====

test('state-base.js：$watch(search/actressSearch/pills/actressPills/showFavoriteActresses) 與 init sync 皆呼叫 _hasActiveFilterForCurrentTab', () => {
    assert.ok(
        /\$watch\(\s*['"]search['"]/.test(STATE_BASE_SRC),
        "必須有 $watch('search')",
    );
    assert.ok(
        /\$watch\(\s*['"]actressSearch['"]/.test(STATE_BASE_SRC),
        "必須有 $watch('actressSearch')",
    );
    // 突變自驗 #3 的錨點：僅 pills 變更時也要更新 showcaseHasSearch
    assert.ok(
        /\$watch\(\s*['"]pills['"]/.test(STATE_BASE_SRC),
        "必須有 $watch('pills')（僅 pills 變更時 predicate 才會更新）",
    );
    // 116a-T2：actressPills watcher（CD-116a-2d）
    assert.ok(
        /\$watch\(\s*['"]actressPills['"]/.test(STATE_BASE_SRC),
        "必須有 $watch('actressPills')",
    );
    // 129-T1a：切分頁本身也要重算（切分頁不會改動四個搜尋欄位）
    assert.ok(
        /\$watch\(\s*['"]showFavoriteActresses['"]/.test(STATE_BASE_SRC),
        "必須有 $watch('showFavoriteActresses')",
    );

    // 六次寫入 store 都必須經 _hasActiveFilterForCurrentTab（不是各自重寫兩欄位算式）
    const storeAssigns = STATE_BASE_SRC.match(
        /Alpine\.store\('ui'\)\.showcaseHasSearch\s*=\s*this\._hasActiveFilterForCurrentTab\(\)/g,
    ) || [];
    assert.equal(
        storeAssigns.length,
        6,
        `預期 5 個 $watch + 1 次 init sync = 6 次，實際 ${storeAssigns.length}`,
    );

    // 舊兩欄位字面不得再出現於 showcaseHasSearch 賦值（scroll handler 的不同語意不在此鎖）
    assert.equal(
        STATE_BASE_SRC.includes(
            "Alpine.store('ui').showcaseHasSearch = (this.search !== '' || this.actressSearch !== '')",
        ),
        false,
        'init sync 不得再使用舊兩欄位字面',
    );
});

test('_hasActiveFilterForCurrentTab 函式體含 pills.length 與 showFavoriteActresses（分頁化真的落地）', () => {
    // 錨定方法定義（不是 this._hasActiveFilterForCurrentTab() 呼叫點）
    const defRe = /_hasActiveFilterForCurrentTab\s*\(\s*\)\s*\{/;
    const m = defRe.exec(STATE_BASE_SRC);
    assert.ok(m, '必須定義 _hasActiveFilterForCurrentTab() 方法');
    const open = STATE_BASE_SRC.indexOf('{', m.index);
    let depth = 0;
    let body = '';
    for (let i = open; i < STATE_BASE_SRC.length; i++) {
        const ch = STATE_BASE_SRC[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) {
                body = STATE_BASE_SRC.slice(open + 1, i);
                break;
            }
        }
    }
    assert.ok(body.includes('pills.length'), `_hasActiveFilterForCurrentTab 體必須含 pills.length，實際：${body}`);
    assert.ok(
        body.includes('showFavoriteActresses'),
        `_hasActiveFilterForCurrentTab 體必須含 showFavoriteActresses（否則只改名沒分頁化），實際：${body}`,
    );
    assert.ok(body.includes('actressSearch'), `_hasActiveFilterForCurrentTab 體必須含 actressSearch`);
});

// ===== 捲動自動收合守衛（PR#131 P3 回歸鎖；129-T1a 改用分頁感知判準）=====

test('行動版捲動自動收合守衛用 _hasActiveFilterForCurrentTab()，不是只看兩個文字欄位', () => {
    // Why 這是回歸鎖而不是風格檢查：navbar 那顆鈕在 showcaseHasSearch 為真時變成 ✕，
    // 按下去是 clear-search 全清、不再是展開工具列（base.html:502-505）。手機上只用 pill
    // 篩選時，若本守衛仍只看文字欄位，捲動會把裝著 pill 的工具列收掉，而唯一的重開入口
    // 已變成「全部清掉」——使用者再也無法只移除其中一枚 pill。兩個判準必須同步放寬。
    const m = /_scrollHandler\s*=\s*\(\)\s*=>\s*\{/.exec(STATE_BASE_SRC);
    assert.ok(m, '必須有 _scrollHandler 箭頭函式定義');
    const open = STATE_BASE_SRC.indexOf('{', m.index);
    let depth = 0;
    let body = '';
    for (let i = open; i < STATE_BASE_SRC.length; i++) {
        const ch = STATE_BASE_SRC[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) {
                body = STATE_BASE_SRC.slice(open + 1, i);
                break;
            }
        }
    }
    // 剝註解後才比對，否則上面那段說明文字自己會讓守衛通過
    const code = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    assert.ok(
        code.includes('this._hasActiveFilterForCurrentTab()'),
        `_scrollHandler 必須用 _hasActiveFilterForCurrentTab() 當 early-return 守衛，實際：${code}`,
    );
    assert.equal(
        /this\.search\s*!==\s*''\s*\|\|\s*this\.actressSearch\s*!==\s*''/.test(code),
        false,
        '_scrollHandler 不得再用舊的兩欄位字面（漏掉 pills）',
    );
});

// ===== showcase.html 接線 =====

test('showcase.html：window listener 與搜尋列清除鈕皆呼叫 clearAllFilters', () => {
    assert.ok(
        /x-on:showcase:clear-search\.window="clearAllFilters\(\)"/.test(SHOWCASE_HTML)
            || /@showcase:clear-search\.window="clearAllFilters\(\)"/.test(SHOWCASE_HTML),
        'window listener 必須呼叫 clearAllFilters()',
    );
    assert.ok(
        /showcase:clear-search/.test(SHOWCASE_HTML),
        '事件名 showcase:clear-search 必須維持（base.html dispatch 端不改）',
    );
    assert.ok(
        /x-show="\$store\.ui\.showcaseHasSearch"/.test(SHOWCASE_HTML),
        '搜尋列清除鈕 x-show 必須讀 $store.ui.showcaseHasSearch',
    );
    assert.ok(
        /@click="clearAllFilters\(\)"/.test(SHOWCASE_HTML),
        '搜尋列清除鈕 @click 必須呼叫 clearAllFilters()',
    );
    // 舊的模式分流 inline 邏輯不得殘留
    assert.equal(
        SHOWCASE_HTML.includes('onActressSearchChange()') && SHOWCASE_HTML.includes("actressSearch = ''"),
        false,
        '搜尋列清除鈕不得再 inline 分流清 actressSearch',
    );
});

// ===== 115-T7 review P2：女優模式下 _animateFilter 不得碰 DOM 動畫 =====
//
// 成因：_animateFilter 是「影片側篩選」動畫，captureFlipState() 只認得 .av-card-preview。
// 女優模式下 _getActiveGrid() 回 .actress-grid → capture 回 null → 掉進 fallback 對整面
// 女優牆重播 playEntry。使用者看到每張女優卡在按清除時無故閃一下。
// 這是「任何呼叫端在女優模式走到 _animateFilter 都會中」的類別問題，故守在函式本身。

test('_animateFilter：女優模式下完全不查 grid、不播動畫（避免整面女優牆誤閃）', () => {
    let getActiveGridCalls = 0;
    let playEntryCalls = 0;
    const prevAnim = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = {
        captureFlipState: () => null,
        playFlipFilter: () => null,
        playEntry: () => { playEntryCalls++; },
    };
    try {
        const c = Object.assign({}, stateVideos(), {
            pills: [], search: '', actressSearch: '',
            mode: 'grid',
            showFavoriteActresses: true,      // ← 女優模式
            _animGeneration: 0,
            filteredCount: 0,
            applyFilterAndSort() {},
            saveState() {},
            $nextTick() {},                    // 不排 callback：本斷言只看同步的 capture 路徑
        });
        c._getActiveGrid = function () { getActiveGridCalls++; return null; };
        c._animateFilter();
        assert.equal(getActiveGridCalls, 0, '女優模式不得查 grid（查了就代表會進 capture/fallback 動畫路徑）');
        assert.equal(playEntryCalls, 0, '女優模式不得播 playEntry');
    } finally {
        globalThis.window.ShowcaseAnimations = prevAnim;
    }
});

test('_animateFilter：影片模式維持既有行為（仍會查 grid）', () => {
    let getActiveGridCalls = 0;
    const c = Object.assign({}, stateVideos(), {
        pills: [], search: '', actressSearch: '',
        mode: 'grid',
        showFavoriteActresses: false,     // ← 影片模式
        _animGeneration: 0,
        filteredCount: 0,
        applyFilterAndSort() {},
        saveState() {},
        $nextTick() {},
    });
    c._getActiveGrid = function () { getActiveGridCalls++; return null; };
    c._animateFilter();
    assert.equal(getActiveGridCalls, 1, '影片模式必須維持既有的 capture 路徑（行為零改變）');
});
