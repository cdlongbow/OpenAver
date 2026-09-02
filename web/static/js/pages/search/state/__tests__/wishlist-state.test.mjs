// TASK-140-T5：wishlist 狀態分片 ＋ listMode 對帳表 ＋ membership hydration
// TASK-140-T10：listMode/displayMode 還原不變式
//
// 覆蓋 DoD：
//   - loadMore 白名單化（M1）
//   - saveState live 取值／restoreState switchToWishlist／resolveVisibleDisplayMode（T10）
//   - addToWishlist I3 回滾（M3）
//   - switchToWishlist 設 displayMode='grid'
//   - membership hydration 三條
//   - search.html Load More x-show 含 listMode === 'search'
//   - wishlist.js 不定義 init()；main.js init() 呼叫 loadWishlistCount()

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };

// state/__tests__ → 上一層 __tests__/alias-loader.mjs（鏡射 pages/search/__tests__ 慣例）
register(new URL('../../__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateWishlist, cardActionState } = await import('../wishlist.js');
const { searchStatePersistence, resolveVisibleDisplayMode } = await import('../persistence.js');
const { searchStateNavigation } = await import('../navigation.js');
const { searchStateBase } = await import('../base.js');
const { searchStateSearchFlow } = await import('../search-flow.js');
const { searchPage } = await import('../../main.js');

const __dirname = dirname(fileURLToPath(import.meta.url));
const SEARCH_HTML = resolve(__dirname, '../../../../../../templates/search.html');
const WISHLIST_JS = resolve(__dirname, '../wishlist.js');
const BASE_JS = resolve(__dirname, '../base.js');

function mockFetch(handler) {
    const calls = [];
    globalThis.fetch = async (url, opts = {}) => {
        calls.push({ url: String(url), opts });
        return handler(String(url), opts, calls);
    };
    return calls;
}

function jsonResponse(data, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => data,
    };
}

// ─── 對帳表 #2：loadMore 白名單化（mutation M1）───────────────────────────

test('loadMore: listMode="wishlist" → 立即回傳 null、不呼叫 fetch（白名單化）', async () => {
    let fetchCalls = 0;
    globalThis.fetch = async () => { fetchCalls++; return jsonResponse({}); };

    const fakeThis = {
        ...searchStateNavigation(),
        listMode: 'wishlist',
        isLoadingMore: false,
        hasMoreResults: true,
        currentQuery: 'ABC-123',
        searchResults: [{ number: 'ABC-001' }],
        currentOffset: 0,
        PAGE_SIZE: 20,
        _getAbortSignal: () => undefined,
        _clearAbort: () => {},
    };

    const result = await searchStateNavigation().loadMore.call(fakeThis, 'detail');
    assert.equal(result, null);
    assert.equal(fetchCalls, 0, 'wishlist 模式下 loadMore 不應觸發 /api/search');
});

test('loadMore: listMode=null → 立即回傳 null、不呼叫 fetch', async () => {
    let fetchCalls = 0;
    globalThis.fetch = async () => { fetchCalls++; return jsonResponse({}); };

    const fakeThis = {
        ...searchStateNavigation(),
        listMode: null,
        isLoadingMore: false,
        hasMoreResults: true,
        currentQuery: 'ABC-123',
        searchResults: [{ number: 'ABC-001' }],
        currentOffset: 0,
        PAGE_SIZE: 20,
        _getAbortSignal: () => undefined,
        _clearAbort: () => {},
    };

    const result = await searchStateNavigation().loadMore.call(fakeThis, 'detail');
    assert.equal(result, null);
    assert.equal(fetchCalls, 0);
});

test('loadMore: listMode="search" → 不因白名單提前 return（可繼續往下）', async () => {
    let fetchCalls = 0;
    globalThis.fetch = async () => {
        fetchCalls++;
        return jsonResponse({ success: true, data: [{ number: 'X-1' }], has_more: false });
    };

    const fakeThis = {
        ...searchStateNavigation(),
        listMode: 'search',
        isLoadingMore: false,
        hasMoreResults: true,
        currentQuery: 'ABC-123',
        searchResults: [{ number: 'ABC-001' }],
        currentOffset: 0,
        PAGE_SIZE: 20,
        _getAbortSignal: () => undefined,
        _clearAbort: () => {},
        _resetCoverState: () => {},
        preloadImages: () => {},
        checkLocalStatus: () => {},
    };

    await searchStateNavigation().loadMore.call(fakeThis, 'detail');
    assert.equal(fetchCalls, 1, 'search 模式應真正發 /api/search');
});

// ─── TASK-140-T10：listMode/displayMode 還原不變式（DoD 4a–4f）────────────

function mockSessionStorage(initial = {}) {
    const store = { ...initial };
    globalThis.sessionStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => store[k] ?? null,
        removeItem: (k) => { delete store[k]; },
    };
    return store;
}

function basePersistFields(overrides = {}) {
    return {
        searchResults: [],
        currentIndex: 0,
        currentQuery: '',
        currentOffset: 0,
        hasMoreResults: false,
        fileList: [],
        currentFileIndex: 0,
        listMode: null,
        searchQuery: '',
        displayMode: 'detail',
        _preWishlistDisplayMode: null,
        currentMode: '',
        actressProfile: null,
        pageState: 'result',
        ...overrides,
    };
}

// DoD 4a（mutation M1）
test("saveState: pageState===loading 且有 snapshot 時，寫出的 listMode 是 live 的 'wishlist'（不是 snap.listMode）", () => {
    const store = mockSessionStorage();
    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY: 'test-t10-loading',
        ...basePersistFields({
            pageState: 'loading',
            listMode: 'wishlist',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
            _searchSnapshot: {
                searchResults: [{ number: 'OLD-1' }],
                currentIndex: 0,
                currentQuery: 'OLD-1',
                currentOffset: 0,
                hasMoreResults: false,
                fileList: [],
                currentFileIndex: 0,
                listMode: 'search',
                displayMode: 'detail',
                currentMode: '',
                actressProfile: null,
            },
        }),
    };

    searchStatePersistence().saveState.call(fakeThis);
    const saved = JSON.parse(store['test-t10-loading']);
    assert.equal(saved.listMode, 'wishlist', 'loading 分支必須寫 live listMode，不是 snap.listMode');
    assert.notEqual(saved.listMode, 'search');
});

// DoD 4b
test("saveState: 正常分支寫出 listMode: 'wishlist'（不再是 null）", () => {
    const store = mockSessionStorage();
    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY: 'test-t10-normal',
        ...basePersistFields({
            _searchSnapshot: null,
            pageState: 'result',
            listMode: 'wishlist',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
        }),
    };

    searchStatePersistence().saveState.call(fakeThis);
    const saved = JSON.parse(store['test-t10-normal']);
    assert.equal(saved.listMode, 'wishlist', 'wishlist 必須原樣寫入，不得再淨化成 null');
});

// DoD 4c
test('saveState: 寫出 _preWishlistDisplayMode', () => {
    const store = mockSessionStorage();
    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY: 'test-t10-pre',
        ...basePersistFields({
            _searchSnapshot: null,
            pageState: 'result',
            listMode: 'wishlist',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
        }),
    };

    searchStatePersistence().saveState.call(fakeThis);
    const saved = JSON.parse(store['test-t10-pre']);
    assert.equal(saved._preWishlistDisplayMode, 'detail');
});

// DoD 4d（mutation M2）
test('restoreState: listMode恢復為wishlist時呼叫switchToWishlist並載入清單', () => {
    const STATE_KEY = 'test-t10-restore';
    mockSessionStorage({
        [STATE_KEY]: JSON.stringify({
            searchResults: [],
            currentIndex: 0,
            currentQuery: '',
            currentOffset: 0,
            hasMoreResults: false,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'wishlist',
            queryValue: '',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
            currentMode: '',
            actressProfile: null,
        }),
    });

    let switchCalls = 0;
    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY,
        ...basePersistFields(),
        lightboxOpen: false,
        lightboxIndex: 0,
        _heroCardImageError: false,
        _heroLightboxImageError: false,
        _resetCoverState: () => {},
        switchToWishlist() { switchCalls += 1; },
    };

    const ret = searchStatePersistence().restoreState.call(fakeThis);
    assert.equal(fakeThis.listMode, 'wishlist');
    assert.equal(fakeThis._preWishlistDisplayMode, 'detail');
    assert.equal(switchCalls, 1, 'restoreState 必須 fire-and-forget 呼叫 switchToWishlist 一次');
    assert.equal(ret instanceof Promise, false, 'restoreState 必須維持同步，回傳值不是 Promise');
});

// DoD 4e
test("restoreState: 還原 wishlist 後 _preWishlistDisplayMode 仍是存檔值（不被 switchToWishlist 覆寫）", () => {
    const STATE_KEY = 'test-t10-order';
    mockSessionStorage({
        [STATE_KEY]: JSON.stringify({
            searchResults: [],
            currentIndex: 0,
            currentQuery: '',
            currentOffset: 0,
            hasMoreResults: false,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'wishlist',
            queryValue: '',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
            currentMode: '',
            actressProfile: null,
        }),
    });

    const wishlist = searchStateWishlist();
    const fakeThis = {
        ...searchStatePersistence(),
        ...wishlist,
        STATE_KEY,
        ...basePersistFields({
            listMode: null,
            displayMode: 'detail',
            _preWishlistDisplayMode: null,
        }),
        lightboxOpen: false,
        lightboxIndex: 0,
        _heroCardImageError: false,
        _heroLightboxImageError: false,
        _resetCoverState: () => {},
        loadWishlist: async () => {},
    };

    searchStatePersistence().restoreState.call(fakeThis);
    assert.equal(fakeThis.listMode, 'wishlist');
    assert.equal(
        fakeThis._preWishlistDisplayMode,
        'detail',
        '必須先還原 listMode=wishlist 再呼叫 switchToWishlist，否則會被覆寫成 grid',
    );
});

// DoD 4f（mutation M3）
test('resolveVisibleDisplayMode: 不合法組合修正為detail、合法組合原樣不動', () => {
    assert.equal(resolveVisibleDisplayMode(null, 'grid'), 'detail');
    assert.equal(resolveVisibleDisplayMode('file', 'grid'), 'detail');
    assert.equal(resolveVisibleDisplayMode('wishlist', 'grid'), 'grid');
    assert.equal(resolveVisibleDisplayMode('search', 'grid'), 'grid');
    assert.equal(resolveVisibleDisplayMode(null, 'detail'), 'detail');
});

// DoD 4f 接線：restoreState 必須真的呼叫 resolveVisibleDisplayMode（純函式測不到這層）
test("restoreState: 讀到 (null,'grid') 這種沒有渲染器命中的組合時，實際套用守衛修正成 detail", () => {
    const STATE_KEY = 'test-t10-restore-guard';
    mockSessionStorage({
        [STATE_KEY]: JSON.stringify({
            searchResults: [{ number: 'SSIS-001' }],
            currentIndex: 0,
            currentQuery: 'SSIS-001',
            currentOffset: 0,
            hasMoreResults: false,
            fileList: [],
            currentFileIndex: 0,
            // listMode 缺省／null：沒有渲染器命中 grid
            displayMode: 'grid',
            _preWishlistDisplayMode: null,
            currentMode: '',
            actressProfile: null,
        }),
    });

    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY,
        ...basePersistFields({
            listMode: null,
            displayMode: 'detail',
            searchResults: [],
            pageState: 'empty',
        }),
        lightboxOpen: false,
        lightboxIndex: 0,
        _heroCardImageError: false,
        _heroLightboxImageError: false,
        _resetCoverState: () => {},
    };

    searchStatePersistence().restoreState.call(fakeThis);
    assert.equal(fakeThis.listMode, null);
    assert.equal(fakeThis.pageState, 'result');
    assert.equal(
        fakeThis.displayMode,
        'detail',
        'restoreState 必須經 resolveVisibleDisplayMode 把 (null, grid) 修正成 detail',
    );
});

// ─── search.html Load More x-show ──────────────────────────────────────────

test('search.html Load More 按鈕 x-show 含 listMode === \'search\'', () => {
    const html = readFileSync(SEARCH_HTML, 'utf8');
    const lines = html.split('\n');
    // 對帳表錨點：Load More 區塊的 x-show（含 hasMoreResults && displayMode === 'grid'）
    const hit = lines.find((ln) =>
        ln.includes('hasMoreResults') && ln.includes('displayMode === \'grid\'') && ln.includes('x-show')
    );
    assert.ok(hit, '應找得到 Load More 的 x-show 行');
    assert.match(hit, /listMode === 'search'/);
});

// ─── base.js 註解（文件性質）──────────────────────────────────────────────

test('base.js listMode 註解含 wishlist', () => {
    const src = readFileSync(BASE_JS, 'utf8');
    assert.match(src, /listMode:\s*null,\s*\/\/.*'wishlist'/);
});

// ─── wishlist.js 不定義 init() ─────────────────────────────────────────────

test('wishlist.js 不定義 init()', () => {
    const src = readFileSync(WISHLIST_JS, 'utf8');
    assert.equal(src.includes('init()'), false, 'wishlist.js 不得出現 init()');
    const shard = searchStateWishlist();
    assert.equal(Object.hasOwn(shard, 'init'), false);
});

// ─── hydration ①：init() 呼叫 loadWishlistCount ───────────────────────────

test('init() 呼叫 loadWishlistCount()', async () => {
    let loadCountCalls = 0;
    globalThis.window.addEventListener = () => {};
    const page = searchPage();
    page.loadAppConfig = async () => {};
    page.restoreState = () => {};
    page._initDragEvents = () => {};
    page.setupAutoSave = () => {};
    page.$watch = () => {};
    page.loadWishlistCount = async () => { loadCountCalls++; };

    await page.init();
    assert.equal(loadCountCalls, 1, 'init() 必須 await this.loadWishlistCount()');
});

// ─── P2-2：兩張卡交錯時計數用增量、不用快照還原 ───────────────────────────

test('addToWishlist: 兩張卡交錯、前者失敗時不得抹掉後者的成功計數（P2-2）', async () => {
    // 使用者連點兩張不同卡片的書籤鈕。A 先送出但失敗、B 後送出且成功。
    // 若回滾用「還原成自己捕捉的 prevCount」，A 會把 B 的 +1 一起抹掉，
    // badge 從此比實際少 1，直到重新整理才修正。
    let releaseA;
    globalThis.fetch = async (url, opts) => {
        const body = JSON.parse(opts.body);
        if (body.number === 'AAA-111') {
            return new Promise((resolve) => { releaseA = () => resolve({ ok: false, status: 500 }); });
        }
        return jsonResponse({ success: true });
    };

    const state = { ...searchStateWishlist(), wishlistCount: 5, wishlistLoaded: false, searchResults: [] };
    const cardA = { number: 'AAA-111' };
    const cardB = { number: 'BBB-222' };

    const pA = state.addToWishlist.call(state, cardA);   // 樂觀 → 6
    const pB = state.addToWishlist.call(state, cardB);   // 樂觀 → 7
    await pB;                                            // B 成功，維持 7
    releaseA();
    await pA;                                            // A 失敗，應回到 6（不是 5）

    assert.equal(state.wishlistCount, 6, 'A 失敗只該扣掉 A 自己那一筆，B 的成功要留著');
    assert.equal(cardA._wishlisted, undefined, 'A 的 icon 要回滾');
    assert.equal(cardB._wishlisted, true, 'B 的 icon 維持實心');
});

// ─── hydration ②：checkLocalStatus 平行 membership ───────────────────────

test('checkLocalStatus: 平行呼叫 POST /api/wishlist/membership 並寫回 _wishlisted', async () => {
    const calls = mockFetch((url) => {
        if (url.includes('/api/search/local-status')) {
            return jsonResponse({ 'SSIS-001': { exists: true } });
        }
        if (url.includes('/api/wishlist/membership')) {
            return jsonResponse({ 'SSIS-001': true, 'SSIS-002': false });
        }
        return jsonResponse({});
    });

    const results = [
        { number: 'SSIS-001' },
        { number: 'SSIS-002' },
    ];
    await searchStateBase().checkLocalStatus.call({}, results);

    const membershipCalls = calls.filter((c) => c.url.includes('/api/wishlist/membership'));
    const localCalls = calls.filter((c) => c.url.includes('/api/search/local-status'));
    assert.equal(membershipCalls.length, 1, '應呼叫 membership 一次');
    assert.equal(localCalls.length, 1, '既有 local-status 仍應呼叫');
    assert.equal(membershipCalls[0].opts.method, 'POST');
    const body = JSON.parse(membershipCalls[0].opts.body);
    assert.deepEqual(body.numbers, ['SSIS-001', 'SSIS-002']);

    assert.equal(results[0]._wishlisted, true);
    assert.equal(results[1]._wishlisted, false);
    assert.deepEqual(results[0]._localStatus, { exists: true });
});

test('checkLocalStatus: membership 卡住時 local-status 仍先發出（P2-1 平行性）', async () => {
    // sonnet review P2-1：原稿先 await membership 再打 local-status，membership
    // 卡住就會連帶壓住**既有功能**的「本地已有」紅框。這支測試釘住「兩個請求
    // 都已發出」這件事本身——membership 的 promise 永遠不 resolve，local-status
    // 仍必須在同一輪被呼叫，否則使用者會看不到本地已有的標記。
    const seen = [];
    let releaseMembership;
    globalThis.fetch = async (url) => {
        seen.push(String(url));
        if (String(url).includes('/api/wishlist/membership')) {
            return new Promise((resolve) => { releaseMembership = resolve; });  // 永遠掛著
        }
        return jsonResponse({ 'SSIS-001': { exists: true } });
    };

    const results = [{ number: 'SSIS-001' }];
    const pending = searchStateBase().checkLocalStatus.call({}, results);

    // 讓 microtask queue 跑完；membership 仍未 resolve
    await Promise.resolve();
    await Promise.resolve();

    assert.ok(
        seen.some((u) => u.includes('/api/search/local-status')),
        'membership 尚未回應時，local-status 必須已經發出（否則就是序列不是平行）',
    );

    // 🔴 Codex review P2：只斷言「有沒有發出」是**半套**——第一版就是兩個 fetch 都發出了、
    // 但寫 `_localStatus` 的那段串在 `await membershipPromise` 後面，membership 卡住時
    // 使用者一樣看不到「本地已有」的紅框。要斷言的是**結果有沒有被寫進去**。
    for (let i = 0; i < 5; i++) await Promise.resolve();
    assert.deepEqual(
        results[0]._localStatus,
        { exists: true },
        'membership 仍卡住時，local-status 的結果必須已經寫入（處理也要獨立，不只發出獨立）',
    );

    releaseMembership(jsonResponse({ 'SSIS-001': true }));
    await pending;
});

test('checkLocalStatus: membership 失敗不污染 _localStatus', async () => {
    mockFetch((url) => {
        if (url.includes('/api/search/local-status')) {
            return jsonResponse({ 'SSIS-001': { exists: true } });
        }
        if (url.includes('/api/wishlist/membership')) {
            return jsonResponse({}, { ok: false, status: 500 });
        }
        return jsonResponse({});
    });

    const results = [{ number: 'SSIS-001' }];
    await searchStateBase().checkLocalStatus.call({}, results);

    assert.equal(results[0]._wishlisted, undefined, 'membership 失敗不寫 _wishlisted');
    assert.deepEqual(results[0]._localStatus, { exists: true }, 'local-status 不受影響');
});

// ─── switchToWishlist displayMode ─────────────────────────────────────────

test('switchToWishlist: 設 listMode=wishlist 且 displayMode=grid', async () => {
    mockFetch(() => jsonResponse([]));
    const fakeThis = makeWishlistThis({
        listMode: 'search',
        displayMode: 'detail',
        wishlistLoaded: true,
        wishlistItems: [],
    });

    await fakeThis.switchToWishlist();
    assert.equal(fakeThis.listMode, 'wishlist');
    assert.equal(fakeThis.displayMode, 'grid');
});

test('switchToWishlist: 已載入過也要重新對帳（T8 review P2）', async () => {
    // spec F6 的對帳時機是「開啟書籤清單時」——每一次，不是只有第一次。
    // 只在 !wishlistLoaded 時載入的話：你把書籤裡的片掃描入庫 → 切回書籤分頁 →
    // 角標不會出現、卡片也不會沉底，除非整頁重新整理。
    let loadCalls = 0;
    const fakeThis = {
        ...searchStateWishlist(),
        listMode: 'search',
        displayMode: 'grid',
        wishlistLoaded: true,          // 已經載入過
        wishlistItems: [{ number: 'OLD-001' }],
        async loadWishlist() { loadCalls++; },
    };

    await searchStateWishlist().switchToWishlist.call(fakeThis);
    assert.equal(loadCalls, 1, '已載入過仍必須重新對帳一次');
});

test('T2-DoD6b-reentry-still-loads: listMode 已經是 wishlist 時（restoreState 路徑）仍必須呼叫 loadWishlist', async () => {
    // 🔴 這條守的是 persistence.js:171-178 的硬約束，Opus 2026-09-03 補。
    // restoreState() 會**先**把 this.listMode 設成 'wishlist'（為了不讓 switchToWishlist()
    // 內部的前置記錄覆寫掉剛還原的 _preWishlistDisplayMode），**再**呼叫 switchToWishlist()
    // ——它就是靠這一呼去 loadWishlist()，因為 wishlistItems 不進 sessionStorage。
    //
    // T2 為了不對「已經在書籤牆」的重入播 crossfade，加了一條
    // `if (this.listMode === 'wishlist') return doSwitch();` 的短路。
    // 那一行看起來像一顆多餘的重入守衛，**下一個人很容易把它「簡化」成 `return;`**——
    // 而那個簡化沒有任何既有測試會轉紅（實測：改掉之後 70/70 全綠）。
    //
    // 使用者流程：停在書籤分頁 → 重新整理（或關掉再打開）→ 整面書籤牆永久空白，
    // 直到手動切去搜尋結果再切回來。本測試就是為了讓那個簡化轉紅。
    let loadCalls = 0;
    const fakeThis = {
        ...searchStateWishlist(),
        listMode: 'wishlist',          // restoreState 已經先設好
        displayMode: 'grid',
        wishlistLoaded: false,
        wishlistItems: [],
        async loadWishlist() { loadCalls++; },
    };

    await searchStateWishlist().switchToWishlist.call(fakeThis);
    assert.equal(loadCalls, 1, 'listMode 已是 wishlist 的重入路徑仍必須載入清單（persistence.js restore 靠這一呼）');
});

test('switchToWishlist: wishlistLoaded=false 時呼叫 loadWishlist', async () => {
    let loadCalls = 0;
    const fakeThis = {
        ...searchStateWishlist(),
        listMode: 'search',
        displayMode: 'detail',
        wishlistLoaded: false,
        wishlistItems: [],
        async loadWishlist() { loadCalls++; this.wishlistLoaded = true; },
    };

    await searchStateWishlist().switchToWishlist.call(fakeThis);
    assert.equal(loadCalls, 1);
    assert.equal(fakeThis.wishlistLoaded, true);
});

// ─── loadWishlistCount / loadWishlist ─────────────────────────────────────

test('loadWishlistCount: 成功時寫入 wishlistCount', async () => {
    mockFetch(() => jsonResponse({ count: 7 }));
    const fakeThis = { ...searchStateWishlist(), wishlistCount: 0 };
    await searchStateWishlist().loadWishlistCount.call(fakeThis);
    assert.equal(fakeThis.wishlistCount, 7);
});

test('loadWishlistCount: 失敗時不歸零、不 throw', async () => {
    mockFetch(() => jsonResponse({}, { ok: false, status: 500 }));
    const fakeThis = { ...searchStateWishlist(), wishlistCount: 3 };
    await searchStateWishlist().loadWishlistCount.call(fakeThis);
    assert.equal(fakeThis.wishlistCount, 3);
});

test('loadWishlist: 寫入 wishlistItems 並設 wishlistLoaded=true', async () => {
    const items = [{ number: 'A-1' }, { number: 'B-2' }];
    mockFetch(() => jsonResponse(items));
    const fakeThis = makeWishlistThis();
    await fakeThis.loadWishlist();
    assert.deepEqual(fakeThis.wishlistItems, items);
    assert.equal(fakeThis.wishlistLoaded, true);
});

// branch review P2（2026-09-02）：對帳在伺服器端自動刪書籤之後，前端唯一能感知
// 「權威狀態變了」的通道就是這支 GET 的回應。它以前只寫清單不寫計數 ⇒ badge 會停在
// 舊數字直到整頁重新整理。
test('loadWishlist: 同時把 wishlistCount 對齊權威清單長度（伺服器端自動移除後 badge 不留舊值）', async () => {
    const items = [{ number: 'A-1' }, { number: 'B-2' }];
    mockFetch(() => jsonResponse(items));
    const fakeThis = makeWishlistThis();
    fakeThis.wishlistCount = 5;          // 掃描前是 5 筆
    await fakeThis.loadWishlist();
    assert.equal(fakeThis.wishlistCount, 2, 'badge 必須與清單一致，不得停在舊值');
});

test('loadWishlist: 請求失敗時不得把 wishlistCount 歸零（清單與計數一起不動）', async () => {
    mockFetch(() => new Response('boom', { status: 500 }));
    const fakeThis = makeWishlistThis();
    fakeThis.wishlistCount = 5;
    fakeThis.wishlistItems = [{ number: 'OLD-1' }];
    await fakeThis.loadWishlist();
    assert.equal(fakeThis.wishlistCount, 5);
    assert.deepEqual(fakeThis.wishlistItems, [{ number: 'OLD-1' }]);
});

// ─── hydration ③：wishlistLoaded 時同步 wishlistItems ─────────────────────

test('addToWishlist: wishlistLoaded=true 時新項目 unshift 到 wishlistItems[0]', async () => {
    mockFetch(() => jsonResponse({ success: true, cover_available: false }));
    const existing = { number: 'OLD-1' };
    const result = {
        number: 'NEW-1', title: 't', actors: [], tags: [], maker: '', director: '',
        series: '', label: '', duration: null, date: '', cover: '', preview_cover_url: '',
        sample_images: [], preview_sample_images: [], source: '', url: '',
    };
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 1,
        wishlistLoaded: true,
        wishlistItems: [existing],
    };

    await searchStateWishlist().addToWishlist.call(fakeThis, result);
    assert.equal(fakeThis.wishlistItems[0].number, 'NEW-1');
    assert.equal(fakeThis.wishlistItems[1], existing);
    assert.equal(result._wishlisted, true);
    assert.equal(fakeThis.wishlistCount, 2);
});

test('addToWishlist: wishlistLoaded=false 時不動 wishlistItems', async () => {
    mockFetch(() => jsonResponse({ success: true, cover_available: false }));
    const result = { number: 'NEW-1', title: '' };
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 0,
        wishlistLoaded: false,
        wishlistItems: [],
    };

    await searchStateWishlist().addToWishlist.call(fakeThis, result);
    assert.deepEqual(fakeThis.wishlistItems, []);
    assert.equal(result._wishlisted, true);
    assert.equal(fakeThis.wishlistCount, 1);
});

test('removeFromWishlist: wishlistLoaded=true 時從 wishlistItems 移除', async () => {
    mockFetch(() => jsonResponse({ success: true }));
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 2,
        wishlistLoaded: true,
        wishlistItems: [{ number: 'A-1' }, { number: 'B-2' }],
        searchResults: [{ number: 'A-1', _wishlisted: true }],
    };

    await searchStateWishlist().removeFromWishlist.call(fakeThis, 'A-1');
    assert.deepEqual(fakeThis.wishlistItems.map((i) => i.number), ['B-2']);
    assert.equal(fakeThis.wishlistCount, 1);
    assert.equal(fakeThis.searchResults[0]._wishlisted, false);
});

// ─── I3 不變式（mutation M3）──────────────────────────────────────────────

test('addToWishlist: POST 失敗時回滾 _wishlisted 與 wishlistCount（I3）', async () => {
    mockFetch(() => jsonResponse({}, { ok: false, status: 500 }));
    const result = { number: 'FAIL-1', title: 'x', _wishlisted: false };
    // PR#176 第 2 輪：原本 fixture 是 `wishlistCount: 5` 配 1 筆 wishlistItems，
    // 那是**生產環境不可能存在的狀態**——`loadWishlist()` 是全站唯一把 wishlistLoaded
    // 設為 true 的地方，而它整包同時寫入清單與計數，兩者必然相等。合成 fixture 把這條
    // 不變式抹平了，於是這支測試從來沒有真的驗到「計數與清單說同一件事」。
    // 改成自洽的 1／1 之後，斷言的意圖（失敗要回滾三件事）完全不變，且更嚴格。
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 1,
        wishlistLoaded: true,
        wishlistItems: [{ number: 'KEEP-1' }],
    };

    await searchStateWishlist().addToWishlist.call(fakeThis, result);
    assert.equal(result._wishlisted, false, '失敗應回滾 _wishlisted');
    assert.equal(fakeThis.wishlistCount, 1, '失敗應回滾 wishlistCount');
    assert.deepEqual(
        fakeThis.wishlistItems.map((i) => i.number),
        ['KEEP-1'],
        '失敗應回滾樂觀 unshift',
    );
});

test('addToWishlist: fetch reject 時回滾 _wishlisted 與 wishlistCount（I3）', async () => {
    globalThis.fetch = async () => { throw new Error('network down'); };
    const result = { number: 'FAIL-2', _wishlisted: undefined };
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 1,
        wishlistLoaded: false,
        wishlistItems: [],
    };

    await searchStateWishlist().addToWishlist.call(fakeThis, result);
    assert.equal(result._wishlisted, undefined);
    assert.equal(fakeThis.wishlistCount, 1);
});

test('removeFromWishlist: DELETE 失敗時回滾 count 與 _wishlisted（I3）', async () => {
    mockFetch(() => jsonResponse({}, { ok: false, status: 500 }));
    const item = { number: 'A-1' };
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 1,
        wishlistLoaded: true,
        wishlistItems: [item],
        searchResults: [{ number: 'A-1', _wishlisted: true }],
    };

    await searchStateWishlist().removeFromWishlist.call(fakeThis, 'A-1');
    assert.equal(fakeThis.wishlistCount, 1);
    assert.equal(fakeThis.searchResults[0]._wishlisted, true);
    assert.equal(fakeThis.wishlistItems.length, 1);
    assert.equal(fakeThis.wishlistItems[0].number, 'A-1');
});

test('addToWishlist: number 空值 → no-op', async () => {
    let fetchCalls = 0;
    globalThis.fetch = async () => { fetchCalls++; return jsonResponse({}); };
    const fakeThis = { ...searchStateWishlist(), wishlistCount: 0 };
    await searchStateWishlist().addToWishlist.call(fakeThis, { title: 'no number' });
    await searchStateWishlist().addToWishlist.call(fakeThis, null);
    assert.equal(fetchCalls, 0);
    assert.equal(fakeThis.wishlistCount, 0);
});

test('switchToWishlist→switchToSearchList: 還原切進來之前的 displayMode（T7 review P2）', () => {
    // 使用者在 detail 模式看著某一片 → 點書籤段 → 點回搜尋段。
    // 不還原的話那張卡會消失、變成整片 grid 牆，得自己重新找回那一筆。
    mockFetch(() => jsonResponse([]));
    const state = makeWishlistThis({ listMode: 'search', displayMode: 'detail', wishlistLoaded: true });

    state.switchToWishlist();
    assert.equal(state.listMode, 'wishlist');
    assert.equal(state.displayMode, 'grid', 'wishlist 下 displayMode 不得為 detail');

    state.switchToSearchList();
    assert.equal(state.listMode, 'search');
    assert.equal(state.displayMode, 'detail', '切回來要回到原本的 detail');
    assert.equal(state._preWishlistDisplayMode, null, '還原後要清掉，不得殘留');
});

test('switchToWishlist: 重複點同一段不得把 grid 記成「切進來之前的值」', () => {
    // 已經在 wishlist 時再點一次書籤段，若無條件覆寫 _preWishlistDisplayMode，
    // 記住的會變成 'grid'，切回搜尋段就再也回不到 detail。
    mockFetch(() => jsonResponse([]));
    const state = makeWishlistThis({ listMode: 'search', displayMode: 'detail', wishlistLoaded: true });
    state.switchToWishlist();
    state.switchToWishlist();   // 重複點
    state.switchToSearchList();
    assert.equal(state.displayMode, 'detail');
});

test('switchToSearchList: 只設 listMode=search', () => {
    const fakeThis = {
        ...searchStateWishlist(),
        listMode: 'wishlist',
        displayMode: 'grid',
    };
    searchStateWishlist().switchToSearchList.call(fakeThis);
    assert.equal(fakeThis.listMode, 'search');
    assert.equal(fakeThis.displayMode, 'grid', 'displayMode 不強制改動');
});

// ─── TASK-140-T6：cardActionState 四態（mutation M1/M2）───────────────────

test("cardActionState: 本地有且 count===1 → 'play'", () => {
    assert.equal(
        cardActionState({ _localStatus: { exists: true, count: 1 }, _wishlisted: false }),
        'play',
    );
});

test("cardActionState: 本地有且 count>1 → 'play+folder'", () => {
    assert.equal(
        cardActionState({ _localStatus: { exists: true, count: 2 }, _wishlisted: false }),
        'play+folder',
    );
});

test("cardActionState: 本地沒有且未加入 → 'bookmark-add'", () => {
    assert.equal(
        cardActionState({ _localStatus: { exists: false }, _wishlisted: false }),
        'bookmark-add',
    );
});

test("cardActionState: 本地沒有且已加入 → 'bookmark-remove'", () => {
    assert.equal(
        cardActionState({ _localStatus: { exists: false }, _wishlisted: true }),
        'bookmark-remove',
    );
});

// ─── TASK-140-T11a：書籤燈箱狀態機（DoD 4a–4e）────────────────────────────

function wishlistLightboxFixture(overrides = {}) {
    return {
        ...searchStateWishlist(),
        wishlistItems: [
            { number: 'WL-001', title: 'one' },
            { number: 'WL-002', title: 'two' },
            { number: 'WL-003', title: 'three' },
        ],
        wishlistLightboxOpen: false,
        wishlistLightboxIndex: -1,
        lightboxOpen: false,
        lightboxIndex: 0,
        ...overrides,
    };
}

// DoD 4a（mutation M1）— 測試名必須逐字等於 mutation expect_fail
test('openWishlistLightbox(2)：wishlistLightboxOpen===true 且 wishlistLightboxIndex===2', () => {
    const state = wishlistLightboxFixture();
    searchStateWishlist().openWishlistLightbox.call(state, 2);
    assert.equal(state.wishlistLightboxOpen, true);
    assert.equal(state.wishlistLightboxIndex, 2);
});

// DoD 4b
test('closeWishlistLightbox()：open===false 且 wishlistItems 陣列本身不被清空', () => {
    const items = [
        { number: 'WL-001', title: 'one' },
        { number: 'WL-002', title: 'two' },
        { number: 'WL-003', title: 'three' },
    ];
    const state = wishlistLightboxFixture({
        wishlistItems: items,
        wishlistLightboxOpen: true,
        wishlistLightboxIndex: 1,
    });
    searchStateWishlist().closeWishlistLightbox.call(state);
    assert.equal(state.wishlistLightboxOpen, false);
    assert.equal(state.wishlistItems, items, 'wishlistItems 陣列參考不得被替換或清空');
    assert.equal(state.wishlistItems.length, 3);
});

// DoD 4c（mutation M2）— 測試名必須逐字等於 mutation expect_fail
test('nextWishlistLightbox() 在最後一筆時 index 不超出 length-1；prevWishlistLightbox() 在第 0 筆時不變成 -1', () => {
    const state = wishlistLightboxFixture({
        wishlistLightboxOpen: true,
        wishlistLightboxIndex: 2,
    });
    searchStateWishlist().nextWishlistLightbox.call(state);
    assert.equal(state.wishlistLightboxIndex, 2, '最後一筆時 next 不得超出 length-1');

    state.wishlistLightboxIndex = 0;
    searchStateWishlist().prevWishlistLightbox.call(state);
    assert.equal(state.wishlistLightboxIndex, 0, '第 0 筆時 prev 不得變成 -1');
});

// DoD 4d
test('currentWishlistLightboxItem()：index 越界／陣列為空時回 undefined／null（不得拋例外）', () => {
    const state = wishlistLightboxFixture({ wishlistLightboxIndex: -1 });
    assert.equal(
        searchStateWishlist().currentWishlistLightboxItem.call(state),
        undefined,
    );

    state.wishlistLightboxIndex = 99;
    assert.equal(
        searchStateWishlist().currentWishlistLightboxItem.call(state),
        undefined,
    );

    state.wishlistItems = [];
    state.wishlistLightboxIndex = 0;
    assert.equal(
        searchStateWishlist().currentWishlistLightboxItem.call(state),
        undefined,
    );
});

// DoD 4e
test('開書籤燈箱不會動到 lightboxOpen／lightboxIndex（獨立狀態機正向鎖）', () => {
    const state = wishlistLightboxFixture({
        lightboxOpen: false,
        lightboxIndex: 7,
    });
    searchStateWishlist().openWishlistLightbox.call(state, 1);
    assert.equal(state.wishlistLightboxOpen, true);
    assert.equal(state.wishlistLightboxIndex, 1);
    assert.equal(state.lightboxOpen, false, '不得動到 lightboxOpen');
    assert.equal(state.lightboxIndex, 7, '不得動到 lightboxIndex');
});

// T11a 第 2 輪：破圖 flag 殘留——看過一張 404 封面後再開別張會一直顯示占位
test('openWishlistLightbox()：每次開啟都重設 _wishlistLbImgError（看過破圖後再開別張不會殘留占位）', () => {
    const state = wishlistLightboxFixture({ _wishlistLbImgError: true });
    searchStateWishlist().openWishlistLightbox.call(state, 1);
    assert.equal(state._wishlistLbImgError, false);
});

// Opus 2026-09-02 補（grok 自報偏離 #2）：箭頭換片也要重設，否則先看到一部沒封面的片、
// 再按箭頭切到有封面的那部，封面不會出現——畫面停在「無圖」占位。
test('prev/nextWishlistLightbox()：箭頭換片也重設 _wishlistLbImgError（不殘留到下一張）', () => {
    const w = searchStateWishlist();

    const next = wishlistLightboxFixture({ _wishlistLbImgError: true, wishlistLightboxIndex: 0 });
    w.nextWishlistLightbox.call(next);
    assert.equal(next._wishlistLbImgError, false, 'next 換片後仍是 true ⇒ 下一張的封面會被占位蓋掉');

    const prev = wishlistLightboxFixture({ _wishlistLbImgError: true, wishlistLightboxIndex: 2 });
    w.prevWishlistLightbox.call(prev);
    assert.equal(prev._wishlistLbImgError, false, 'prev 換片後仍是 true ⇒ 上一張的封面會被占位蓋掉');
});

// ─── 書籤載入與交錯（TASK-140-T12 起，141a-T4/T6 之後只剩載入端）──────────────

// 技術要點 §4：plain spread 會在展開當下求值 getter 並凍結成 0，必須保留 descriptor。
//
// Codex review P2 修正後，loadWishlist() 會用到 search-flow 的
// AbortController registry（_getAbortSignal／_clearAbort／_abortControllers）。照
// set-file-list-race.test.mjs 的既有手法**組真的 mixin**，不手抄 abort 邏輯——手抄的話
// 產品端改了機制測試不會紅。_abortControllers 由 base.js:118 宣告，這裡補上同一個初始值。
function makeWishlistThis(overrides = {}) {
    const target = {};
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(searchStateSearchFlow()));
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(searchStateWishlist()));
    target._abortControllers = {};
    Object.assign(target, overrides);
    return target;
}

// ─── Codex review P2（Opus 2026-09-02）：非同步 fetch 交錯 ─────────────────
//
// T12 的卡片把「背景 worker 交錯」勾成 N/A 是對的（沒有背景任務），但漏掉了另一種
// 交錯：`switchToSearchList()` 不清空 `wishlistItems`，所以切回書籤分頁的瞬間，畫面
// 會先用**上一次的舊資料**把卡片與垃圾桶鈕渲染出來，而新的 GET 還在飛。
// 使用者於是能在那個窗口裡按某張卡的垃圾桶。窗口不是理論值——
// `GET /api/wishlist` 現在**先對帳再回清單**（141a-T4），對帳要對每一筆書籤查一次片庫。
// （141a-T1 之前那支查詢的 `UPPER(number)` 吃不到索引、實測是 `SCAN videos`；
// 加了 `idx_videos_number_upper` 之後成本只跟書籤數有關，但窗口仍在：網路 ＋ 對帳 ＋ 刪封面檔。）
//
// 手法照 set-file-list-race.test.mjs：mock 尊重 AbortSignal（有 signal 才會在 abort 時
// reject），所以「產品端忘了把 signal 傳進 fetch」這個回歸也會被這兩條測出來。

function makeAbortError() {
    return new DOMException('The operation was aborted', 'AbortError');
}

test('deferred-fetch：連續兩次 loadWishlist，舊 GET 晚到不得覆蓋新結果', async () => {
    globalThis.window.t = (key) => key;
    let releaseGet1;
    const get1Released = new Promise((r) => { releaseGet1 = r; });
    const staleFromServer = [{ number: 'OWNED-1' }, { number: 'FREE-1' }];
    const freshFromServer = [{ number: 'FREE-1' }];

    let get1Signal;
    let getCall = 0;
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist') {
            getCall += 1;
            if (getCall === 1) {
                return new Promise((resolve, reject) => {
                    const { signal } = opts;
                    get1Signal = signal;
                    if (signal) {
                        if (signal.aborted) { reject(makeAbortError()); return; }
                        signal.addEventListener('abort', () => reject(makeAbortError()), { once: true });
                    }
                    get1Released.then(() => resolve(jsonResponse(staleFromServer)));
                });
            }
            return jsonResponse(freshFromServer);
        }
        throw new Error(`unexpected url: ${u}`);
    };

    const state = makeWishlistThis({
        wishlistCount: 2,
        wishlistLoaded: true,
        wishlistItems: staleFromServer.map((i) => ({ ...i })),
        showToast() {},
    });

    const pendingGet1 = state.loadWishlist();
    const pendingGet2 = state.loadWishlist();
    await pendingGet2;
    releaseGet1();
    await pendingGet1;

    assert.deepEqual(
        state.wishlistItems.map((i) => i.number),
        ['FREE-1'],
        '第一次那個晚到的回應不得覆蓋 wishlistItems',
    );
    assert.ok(get1Signal instanceof AbortSignal, 'GET 必須把 AbortSignal 傳進 fetch');
    assert.equal(get1Signal.aborted, true, '第二次 loadWishlist 必須 abort 掉第一次在飛的 GET');
});

test('deferred-fetch：loadWishlist 對帳先清掉該列、單筆 DELETE 後到拿 {success:false} ⇒ badge 跟伺服器重新對帳', async () => {
    globalThis.window.t = (key) => key;
    let releaseDelete;
    const deleteReleased = new Promise((r) => { releaseDelete = r; });
    let countCalls = 0;

    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist/OWN-1' && opts.method === 'DELETE') {
            await deleteReleased;
            return jsonResponse({ success: false });   // 開書籤時對帳已經先把這一列清掉了
        }
        if (u === '/api/wishlist') return jsonResponse([{ number: 'KEEP-1' }]);
        if (u === '/api/wishlist/count') { countCalls++; return jsonResponse({ count: 1 }); }
        throw new Error(`unexpected url: ${u}`);
    };

    const state = makeWishlistThis({
        wishlistCount: 3,
        wishlistLoaded: true,
        wishlistItems: [
            { number: 'OWN-1' },
            { number: 'OWN-2' },
            { number: 'KEEP-1' },
        ],
        searchResults: [],
        showToast() {},
    });

    const pendingRemove = state.removeFromWishlist('OWN-1');  // 樂觀扣掉一筆，DELETE 掛住
    await state.loadWishlist();                               // 開書籤對帳：伺服器已無 OWN-1
    releaseDelete();
    await pendingRemove;

    assert.equal(countCalls, 1, 'success:false 必須觸發一次跟伺服器的重新對帳');
    assert.equal(state.wishlistCount, 1, 'badge 不得停在少扣一筆的 0，要收斂到伺服器的權威值');
    assert.deepEqual(
        state.wishlistItems.map((i) => i.number),
        ['KEEP-1'],
        'success:false 不得把幽靈卡塞回畫面（那一列在伺服器上本來就已經不存在）',
    );
});

test('removeFromWishlist：HTTP 200 {success:false} ⇒ 重新對帳 badge，且不回滾樂觀移除', async () => {
    let countCalls = 0;
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist/GONE-1' && opts.method === 'DELETE') return jsonResponse({ success: false });
        if (u === '/api/wishlist/count') { countCalls++; return jsonResponse({ count: 9 }); }
        throw new Error(`unexpected url: ${u}`);
    };

    const state = makeWishlistThis({
        wishlistCount: 12,
        wishlistLoaded: true,
        wishlistItems: [{ number: 'GONE-1' }, { number: 'KEEP-1' }],
        searchResults: [{ number: 'GONE-1', _wishlisted: true }],
    });

    await state.removeFromWishlist('GONE-1');

    assert.equal(countCalls, 1);
    assert.equal(state.wishlistCount, 9, '本地計數已知與 DB 對不上 ⇒ 收伺服器權威值，不是 12-1=11');
    assert.deepEqual(state.wishlistItems.map((i) => i.number), ['KEEP-1'], '不得 unshift 回去');
    assert.equal(state.searchResults[0]._wishlisted, false, '搜尋卡的書籤態不得回滾成已收藏');
});

// Codex 二審 P2（改指向 T4）：對帳觸發點改成 GET /api/wishlist 後，仍要守住
// switchToSearchList → switchToWishlist 這條 tab 切換路徑上的 abort registry。
test('deferred-fetch：loadWishlist 進行中切到搜尋段再切回書籤段，舊 GET 不得覆蓋新結果', async () => {
    globalThis.window.t = (key) => key;
    let releaseGet1, releaseGet2;
    const get1Released = new Promise((r) => { releaseGet1 = r; });
    const get2Released = new Promise((r) => { releaseGet2 = r; });
    const staleFromServer = [{ number: 'OWNED-1' }, { number: 'FREE-1' }];
    const freshFromServer = [{ number: 'FREE-1' }];
    let get1Signal;
    let getCall = 0;

    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist') {
            getCall += 1;
            const callNum = getCall;
            return new Promise((resolve, reject) => {
                const { signal } = opts;
                if (callNum === 1) get1Signal = signal;
                if (signal) {
                    if (signal.aborted) { reject(makeAbortError()); return; }
                    signal.addEventListener('abort', () => reject(makeAbortError()), { once: true });
                }
                const released = callNum === 1 ? get1Released : get2Released;
                const payload = callNum === 1 ? staleFromServer : freshFromServer;
                released.then(() => resolve(jsonResponse(payload)));
            });
        }
        throw new Error(`unexpected url: ${u}`);
    };

    const state = makeWishlistThis({
        listMode: 'search',
        displayMode: 'grid',
        wishlistCount: 2,
        wishlistLoaded: true,
        wishlistItems: staleFromServer.map((i) => ({ ...i })),
        showToast() {},
    });

    const pendingGet1 = state.switchToWishlist();  // 第一次 loadWishlist，GET 掛住
    state.switchToSearchList();                    // 覺得慢 → 去看搜尋結果
    const pendingGet2 = state.switchToWishlist();  // 再切回書籤 ⇒ 同一個 key 會 abort 第一次
    releaseGet2();
    await pendingGet2;
    releaseGet1();
    await pendingGet1;

    assert.equal(get1Signal.aborted, true, '切回書籤時發出的第二次 GET 必須作廢第一次');
    assert.deepEqual(
        state.wishlistItems.map((i) => i.number),
        ['FREE-1'],
        '第一次那個晚到的回應不得把 OWNED-1 寫回 wishlistItems',
    );
});

// branch review P2-1：POST 回 added:false（那個番號本來就在）時，樂觀 +1 必須收回。
// 到達路徑：切換版本把整顆結果物件換掉 ⇒ `_wishlisted` 一起沒了 ⇒ 卡片變回「加入書籤」
// ⇒ 再按一次。與 removeFromWishlist 的 success:false 是同一組對稱處置。
test('addToWishlist：HTTP 200 {added:false} ⇒ 重新對帳 badge，並收回樂觀 unshift 的重複項', async () => {
    let countCalls = 0;
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist' && opts.method === 'POST') {
            return jsonResponse({ success: true, added: false, cover_available: true });
        }
        if (u === '/api/wishlist/count') { countCalls++; return jsonResponse({ count: 5 }); }
        throw new Error(`unexpected url: ${u}`);
    };

    const existing = { number: 'DUP-1' };
    const result = { number: 'DUP-1', title: 't' };
    const state = makeWishlistThis({
        wishlistCount: 5,
        wishlistLoaded: true,
        wishlistItems: [existing],
    });

    await state.addToWishlist(result);

    assert.equal(countCalls, 1, 'added:false 必須觸發一次跟伺服器的重新對帳');
    assert.equal(state.wishlistCount, 5, '本來就有的番號不得讓計數 +1（收伺服器權威值）');
    assert.deepEqual(state.wishlistItems, [existing],
        '樂觀 unshift 的那筆重複必須收回，只留原本那筆（否則 x-for 會有重複 :key）');
});

// Codex PR#175 P2：切進書籤前的 listMode 必須被記住並還原。
// 實測重現過：listMode:'file'（把影片檔拖進來比對）→ 點書籤 → 點回搜尋 ⇒ listMode 落在
// 'search'，fileList 資料還在記憶體裡但 #fileList 連同整理列／改番號控制項全部隱藏，
// 使用者的拖曳工作階段看起來整個不見了。
test('switchToWishlist→switchToSearchList：從 file 模式進書籤再回來，必須回到 file 而不是 search', async () => {
    mockFetch(() => jsonResponse([]));
    const state = makeWishlistThis({
        listMode: 'file',
        displayMode: 'detail',
        wishlistLoaded: true,
        fileList: [{ path: '/x/a.mp4', searchResults: [] }],
    });

    state.switchToWishlist();
    assert.equal(state.listMode, 'wishlist');

    state.switchToSearchList();
    assert.equal(state.listMode, 'file', '必須回到切進書籤前的 file 模式');
    assert.equal(state.displayMode, 'detail');
    assert.equal(state._preWishlistListMode, null, '還原後要清掉，不得殘留');
    assert.equal(state.fileList.length, 1, 'fileList 不得被動到');
});

test('switchToSearchList：沒記到前一個模式時落回 search（這顆鈕的預設語意）', () => {
    const state = makeWishlistThis({ listMode: 'wishlist', displayMode: 'grid' });
    state.switchToSearchList();
    assert.equal(state.listMode, 'search');
});

test('saveState/restoreState：_preWishlistListMode 與 _preWishlistDisplayMode 對稱持久化', () => {
    const store = mockSessionStorage();
    const saver = {
        ...searchStatePersistence(),
        ...basePersistFields({
            listMode: 'wishlist',
            displayMode: 'grid',
            _preWishlistDisplayMode: 'detail',
            _preWishlistListMode: 'file',
        }),
    };
    saver.saveState();

    const restorer = {
        ...searchStatePersistence(),
        ...basePersistFields(),
        switchToWishlist() {},
    };
    restorer.restoreState();

    assert.equal(restorer._preWishlistListMode, 'file',
        '不一起還原的話，在書籤頁重新整理再點回搜尋段仍會掉進 search 而不是 file');
    assert.equal(restorer._preWishlistDisplayMode, 'detail');
    assert.ok(store, 'sessionStorage mock 有被用到');
});

// ─── TASK-141a-T3：加入書籤寫入點守門（already_owned）──────────────────────

test('T3-DoD3：already_owned ⇒ 回滾三件事、設 _localStatus、info toast（非 error）', async () => {
    const localStatus = {
        exists: true,
        count: 1,
        paths: ['/lib/OWNED-1.mp4'],
    };
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist' && opts.method === 'POST') {
            return jsonResponse({
                success: false,
                already_owned: true,
                local_status: localStatus,
            });
        }
        throw new Error(`unexpected url: ${u}`);
    };
    globalThis.window.t = (key) => key;

    const toasts = [];
    const existing = { number: 'KEEP-1' };
    const result = { number: 'OWNED-1', title: 't', _wishlisted: false };
    // PR#176 第 2 輪：同上——wishlistLoaded:true 時計數必等於清單長度，原本的 3／1 不自洽。
    const state = makeWishlistThis({
        wishlistCount: 1,
        wishlistLoaded: true,
        wishlistItems: [existing],
        showToast(msg, type) { toasts.push({ msg, type }); },
    });

    await state.addToWishlist(result);

    assert.deepEqual(result._localStatus, localStatus,
        '_localStatus 必須等於回應的 local_status（逐欄位）');
    assert.equal(result._wishlisted, false, '_wishlisted 必須回滾成呼叫前的值');
    assert.equal(state.wishlistCount, 1, 'wishlistCount 必須回滾');
    assert.deepEqual(state.wishlistItems, [existing],
        'wishlistItems 不得含樂觀 unshift 的那筆');
    assert.equal(toasts.length, 1, '必須顯示 toast');
    assert.equal(toasts[0].type, 'info', 'toast 等級必須是 info，不是 error');
    assert.equal(toasts[0].msg, 'search.toast.wishlist_already_owned');
    assert.ok(!toasts.some((t) => t.type === 'error'), '不得顯示 error 等級 toast');
});

test("T3-DoD4a：already_owned count=1 ⇒ cardActionState(result) === 'play'", async () => {
    const localStatus = {
        exists: true,
        count: 1,
        paths: ['/lib/PLAY-1.mp4'],
    };
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist' && opts.method === 'POST') {
            return jsonResponse({
                success: false,
                already_owned: true,
                local_status: localStatus,
            });
        }
        throw new Error(`unexpected url: ${u}`);
    };
    globalThis.window.t = (key) => key;

    const result = { number: 'PLAY-1', title: 't', _wishlisted: false };
    const state = makeWishlistThis({
        wishlistCount: 0,
        wishlistLoaded: false,
        wishlistItems: [],
        showToast() {},
    });

    await state.addToWishlist(result);

    assert.equal(cardActionState(result), 'play');
});

test("T3-DoD4b：already_owned count=2 ⇒ cardActionState(result) === 'play+folder'", async () => {
    const localStatus = {
        exists: true,
        count: 2,
        paths: ['/lib/FOLDER-1a.mp4', '/lib/FOLDER-1b.mp4'],
    };
    globalThis.fetch = async (url, opts = {}) => {
        const u = String(url);
        if (u === '/api/wishlist' && opts.method === 'POST') {
            return jsonResponse({
                success: false,
                already_owned: true,
                local_status: localStatus,
            });
        }
        throw new Error(`unexpected url: ${u}`);
    };
    globalThis.window.t = (key) => key;

    const result = { number: 'FOLDER-1', title: 't', _wishlisted: false };
    const state = makeWishlistThis({
        wishlistCount: 0,
        wishlistLoaded: false,
        wishlistItems: [],
        showToast() {},
    });

    await state.addToWishlist(result);

    assert.equal(cardActionState(result), 'play+folder');
});

// ─── PR#176 第 2 輪：await 之後的計數回滾（不變式 oracle）─────────────────
//
// 這五支釘的是**同一條不變式**：`await` 之後不准用相對加減改 `wishlistCount`；
// `wishlistLoaded` 為真時計數必須等於權威清單長度。
//
// 交錯的形狀是實測出來的可達路徑（不是理論）：使用者一邊掃描一邊按「加入書籤」→
// `repo.add()` 撞上 `upsert_batch` 的寫鎖、5 秒後拋 `database is locked` → POST 回 500；
// 這期間使用者以為沒反應去點了書籤分頁，`GET /api/wishlist` 在同一個持鎖期間 1 ms 就
// 回來（WAL 讀不擋）並寫入權威值 → POST 才落地做回滾。
//
// 每支的真相都是「DB 有 5 筆」，所以收斂後 badge 一律必須是 5（remove 那支是 3）。

function makeInterleaveState(authoritative) {
    const state = makeWishlistThis({
        wishlistLoaded: true,
        wishlistItems: [],
        wishlistCount: authoritative.length,
        searchResults: [],
    });
    // 模擬 loadWishlist() 已經整包覆蓋落地（清單與計數同時寫入權威值）
    state.wishlistItems = authoritative.slice();
    state.wishlistCount = authoritative.length;
    return state;
}

const AUTHORITATIVE_5 = [
    { number: 'W-1' }, { number: 'W-2' }, { number: 'W-3' }, { number: 'W-4' }, { number: 'W-5' },
];

test('await 後回滾（already_owned）：loadWishlist 先落地時 badge 不得低估', async () => {
    const state = makeInterleaveState(AUTHORITATIVE_5);
    const card = { number: 'OWNED-1' };
    let landAdd;
    mockFetch(() => new Promise((r) => { landAdd = () => r(jsonResponse({
        success: false, already_owned: true,
        local_status: { exists: true, count: 1, paths: ['file:///x/OWNED-1.mp4'] },
    })); }));
    state.showToast = () => {};
    const p = state.addToWishlist(card);          // 樂觀 +1 → 6，unshift → 6 張
    state.wishlistItems = AUTHORITATIVE_5.slice();  // loadWishlist() 整包覆蓋落地
    state.wishlistCount = AUTHORITATIVE_5.length;
    landAdd();
    await p;
    assert.equal(state.wishlistCount, 5, 'badge 必須等於權威清單長度，不得被 -1 扣成 4');
    assert.equal(state.wishlistItems.length, 5);
});

test('await 後回滾（網路錯誤）：loadWishlist 先落地時 badge 不得低估', async () => {
    const state = makeInterleaveState(AUTHORITATIVE_5);
    const card = { number: 'NET-1' };
    let boom;
    mockFetch(() => new Promise((_, rej) => { boom = () => rej(new Error('network down')); }));
    const p = state.addToWishlist(card);
    state.wishlistItems = AUTHORITATIVE_5.slice();
    state.wishlistCount = AUTHORITATIVE_5.length;
    boom();
    await p;
    assert.equal(state.wishlistCount, 5);
});

test('await 後回滾（500，掃描持鎖那條可達路徑）：badge 不得低估', async () => {
    const state = makeInterleaveState(AUTHORITATIVE_5);
    const card = { number: 'LOCK-1' };
    let land500;
    mockFetch(() => new Promise((r) => { land500 = () => r({ ok: false, status: 500 }); }));
    const p = state.addToWishlist(card);
    state.wishlistItems = AUTHORITATIVE_5.slice();
    state.wishlistCount = AUTHORITATIVE_5.length;
    land500();
    await p;
    assert.equal(state.wishlistCount, 5);
});

test('await 後回滾（remove 失敗）：badge 不得高估、清單不得出現重複 number', async () => {
    const authoritative = [{ number: 'R-1' }, { number: 'R-2' }, { number: 'R-3' }];
    const state = makeInterleaveState(authoritative);
    let boom;
    mockFetch(() => new Promise((_, rej) => { boom = () => rej(new Error('network down')); }));
    const p = state.removeFromWishlist('R-2');     // 樂觀移除 → 2 張
    state.wishlistItems = authoritative.slice();   // loadWishlist() 落地：刪除失敗 ⇒ R-2 還在
    state.wishlistCount = authoritative.length;
    boom();
    await p;
    assert.equal(state.wishlistCount, 3, 'badge 不得被 +1 加成 4');
    const numbers = state.wishlistItems.map((i) => i.number);
    assert.equal(numbers.length, new Set(numbers).size, '不得出現同 number 的重複 :key');
});

test('await 後回滾（wishlistLoaded=false）：沒有權威清單時仍走相對回滾', async () => {
    const state = makeWishlistThis({ wishlistLoaded: false, wishlistItems: [], wishlistCount: 5, searchResults: [] });
    mockFetch(() => Promise.reject(new Error('network down')));
    await state.addToWishlist({ number: 'NL-1' });
    assert.equal(state.wishlistCount, 5, '沒開過書籤分頁 ⇒ 清單不權威，相對回滾仍是正確答案');
});

// ─── TASK-141b-T2：書籤牆進場 ＋ 分頁切換 crossfade ─────────────────────────
//
// 閘控路徑測試會臨時掛 window.SearchAnimations / document.querySelector /
// window.GridMotion；測完必須還原，否則污染同檔既有 stub。

function withCrossfadeEnv({ queryMap, fadeImpl, playEntryImpl }, fn) {
    const prevSA = globalThis.window.SearchAnimations;
    const prevGM = globalThis.window.GridMotion;
    const prevQS = globalThis.document.querySelector;
    const crossfadeCalls = [];
    const playEntryCalls = [];

    globalThis.document.querySelector = (sel) => (queryMap && Object.prototype.hasOwnProperty.call(queryMap, sel))
        ? queryMap[sel]
        : null;
    globalThis.window.SearchAnimations = {
        playListModeCrossfade(oldEl, newEl, options) {
            crossfadeCalls.push({ oldEl, newEl, options: options || {} });
            if (typeof fadeImpl === 'function') return fadeImpl(oldEl, newEl, options || {}, crossfadeCalls);
            if (options && typeof options.onOldFadeComplete === 'function') options.onOldFadeComplete();
            return null;
        },
    };
    globalThis.window.GridMotion = {
        playEntry(el) {
            playEntryCalls.push(el);
            if (typeof playEntryImpl === 'function') return playEntryImpl(el);
            return null;
        },
    };

    const api = { crossfadeCalls, playEntryCalls };
    const run = async () => {
        try {
            return await fn(api);
        } finally {
            if (prevSA === undefined) delete globalThis.window.SearchAnimations;
            else globalThis.window.SearchAnimations = prevSA;
            if (prevGM === undefined) delete globalThis.window.GridMotion;
            else globalThis.window.GridMotion = prevGM;
            if (prevQS === undefined) delete globalThis.document.querySelector;
            else globalThis.document.querySelector = prevQS;
        }
    };
    return run();
}

const T2_ELS = {
    '#resultCard': { id: 'resultCard' },
    '#emptyState': { id: 'emptyState' },
    '#loadingState': { id: 'loadingState' },
    '#errorState': { id: 'errorState' },
    '.wishlist-panel': { className: 'wishlist-panel' },
    '.wishlist-grid': { className: 'wishlist-grid' },
};

test('T2-DoD1-switchToWishlist-crossfade-then-playEntry', async () => {
    // DoD 1：oldEl 淡出 → listMode=wishlist → .wishlist-panel 淡入 → load 後 playEntry
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));
    await withCrossfadeEnv({ queryMap: T2_ELS }, async ({ crossfadeCalls, playEntryCalls }) => {
        const state = makeWishlistThis({
            listMode: 'search',
            displayMode: 'detail',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
        });

        await state.switchToWishlist();
        await Promise.resolve(); // flush loadPromise.then

        assert.equal(state.listMode, 'wishlist');
        assert.equal(state.displayMode, 'grid');
        assert.ok(crossfadeCalls.length >= 2, '必須先淡出舊容器、再淡入書籤面板');

        const fadeOut = crossfadeCalls[0];
        assert.equal(fadeOut.oldEl, T2_ELS['#resultCard'], 'oldEl 必須是 pageState 對應的可見容器');
        assert.equal(fadeOut.newEl, null);
        assert.equal(typeof fadeOut.options.onOldFadeComplete, 'function');

        const fadeIn = crossfadeCalls[1];
        assert.equal(fadeIn.oldEl, null);
        assert.equal(fadeIn.newEl, T2_ELS['.wishlist-panel']);

        assert.equal(playEntryCalls.length, 1, '有書籤時必須播 playEntry');
        assert.equal(playEntryCalls[0], T2_ELS['.wishlist-grid']);
    });
});

test('T2-DoD1-empty-pageState-fades-emptyState', async () => {
    // FE-ALPINE-12：從未搜尋過就點書籤，淡出的必須是 #emptyState，不是隱形的 #resultCard
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));
    await withCrossfadeEnv({ queryMap: T2_ELS }, async ({ crossfadeCalls }) => {
        const state = makeWishlistThis({
            listMode: 'search',
            displayMode: 'grid',
            pageState: 'empty',
            wishlistLoaded: false,
            wishlistItems: [],
        });
        await state.switchToWishlist();
        assert.equal(crossfadeCalls[0].oldEl, T2_ELS['#emptyState']);
    });
});

test('T2-DoD2-switchToSearchList-crossfade-no-playEntry', async () => {
    // DoD 2：回程對稱淡出／淡入；GridMotion.playEntry 零呼叫
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));
    await withCrossfadeEnv({ queryMap: T2_ELS }, async ({ crossfadeCalls, playEntryCalls }) => {
        const state = makeWishlistThis({
            listMode: 'search',
            displayMode: 'detail',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
        });
        await state.switchToWishlist();
        await Promise.resolve();
        playEntryCalls.length = 0;
        crossfadeCalls.length = 0;

        state.switchToSearchList();

        assert.equal(state.listMode, 'search');
        assert.equal(state.displayMode, 'detail');
        assert.ok(crossfadeCalls.length >= 2, '回程必須淡出書籤面板、再淡入搜尋容器');
        assert.equal(crossfadeCalls[0].oldEl, T2_ELS['.wishlist-panel']);
        assert.equal(crossfadeCalls[0].newEl, null);
        assert.equal(crossfadeCalls[1].oldEl, null);
        assert.equal(crossfadeCalls[1].newEl, T2_ELS['#resultCard']);
        assert.equal(playEntryCalls.length, 0, '切回搜尋結果不得重播 playEntry');
    });
});

test('T2-DoD3-empty-wishlist-no-playEntry', async () => {
    // DoD 3／mutation 點 2：空清單短路，容器淡入仍要有
    mockFetch(() => jsonResponse([]));
    await withCrossfadeEnv({ queryMap: T2_ELS }, async ({ crossfadeCalls, playEntryCalls }) => {
        const state = makeWishlistThis({
            listMode: 'search',
            displayMode: 'grid',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
        });
        await state.switchToWishlist();
        await Promise.resolve();

        assert.equal(state.listMode, 'wishlist');
        assert.ok(crossfadeCalls.some((c) => c.newEl === T2_ELS['.wishlist-panel']),
            '空清單仍要淡入 .wishlist-panel');
        assert.equal(playEntryCalls.length, 0, '空清單不得呼叫 GridMotion.playEntry');
    });
});

test('T2-DoD4-generation-guards-stale-playEntry', async () => {
    // DoD 4：連按後舊世代 loadPromise.then 不得觸發 playEntry
    const releases = [];
    mockFetch(() => new Promise((resolve) => {
        releases.push((items) => resolve(jsonResponse(items)));
    }));

    await withCrossfadeEnv({ queryMap: T2_ELS }, async ({ playEntryCalls }) => {
        // 直通路徑（fade 立即 cb）下世代遞增仍守住 loadPromise.then
        const state = makeWishlistThis({
            listMode: 'search',
            displayMode: 'grid',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
        });

        const p1 = state.switchToWishlist();
        state.switchToSearchList();
        const p3 = state.switchToWishlist();

        assert.ok(state._wishlistViewGeneration >= 3, '三次切換必須遞增世代');

        // 先放行第一輪（舊世代）load
        releases[0]([{ number: 'STALE-1' }]);
        await p1;
        await Promise.resolve();
        assert.equal(playEntryCalls.length, 0, '舊世代 load 落地不得播 playEntry');

        // 再放行最新一輪
        releases[1]([{ number: 'FRESH-1' }]);
        await p3;
        await Promise.resolve();
        assert.equal(playEntryCalls.length, 1, '只有當前世代的 load 落地才播 playEntry');
        assert.equal(playEntryCalls[0], T2_ELS['.wishlist-grid']);
    });
});

test('T2-DoD4b-stale-crossfade-no-residual-panel', async () => {
    // 🔴 DoD 4 的另一半（Opus 2026-09-03 補，sonnet review P2）：
    // 上一支測試只驗了「舊世代不播 playEntry」，但 DoD 4 字面要求的是
    // 「舊世代回呼沒有觸發任何 playEntry／playListModeCrossfade」。
    //
    // 這裡用**延遲**的 fadeImpl（把 onOldFadeComplete 收起來不立即呼叫）重現真實時序：
    // 淡出是 GSAP tween（DURATION.fast = 167ms），使用者在它跑完之前又點了另一顆分頁鈕，
    // 於是第一次的回呼會在第二次已經開始之後才落地——**這不是時序倒轉，是連按的正常情況**。
    //
    // 沒有世代守衛的話，那個遲到的回呼照樣會翻 listMode 並淡入 .wishlist-panel：
    // 使用者流程 = 在 167ms 內連點兩下分頁鈕 → 書籤面閃一下淡入再被蓋掉
    // → 就是 spec F7 驗收 3 明文禁止的「切換分頁時連按留下半透明的殘面」。
    const pendingCbs = [];
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));

    await withCrossfadeEnv({
        queryMap: T2_ELS,
        // 只把「有 onOldFadeComplete」的那一支（＝淡出）延遲；純淡入（無 cb）照常記錄
        fadeImpl: (oldEl, newEl, options) => {
            if (typeof options.onOldFadeComplete === 'function') pendingCbs.push(options.onOldFadeComplete);
            return null;
        },
    }, async ({ crossfadeCalls }) => {
        const state = makeWishlistThis({
            listMode: 'file',
            displayMode: 'grid',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
        });

        state.switchToWishlist();      // 第 1 次：淡出 #resultCard（cb0），回呼被收起來
        state.switchToSearchList();    // 第 2 次：使用者在 167ms 內又點了一下（cb1）
        state.switchToWishlist();      // 第 3 次：再點回來（cb2）—— 這下 cb0/cb1 都是舊世代

        assert.equal(pendingCbs.length, 3, '三次切換各自起了一支淡出（回呼都還沒落地）');

        // ── 依「自然完成順序」逐一放行（cb0 → cb1 → cb2）。
        //    不需要任何時序倒轉：第 3 次點擊發生的當下，cb0 與 cb1 就已經是舊世代了。──
        let before = crossfadeCalls.length;
        pendingCbs[0]();               // 舊世代（switchToWishlist 那一支）
        assert.notEqual(state.listMode, 'wishlist',
            '舊世代的 switchToWishlist 回呼不得把 listMode 翻成 wishlist');
        assert.equal(crossfadeCalls.length, before,
            '舊世代回呼不得淡入 .wishlist-panel（否則書籤面會閃一下再被蓋掉）');

        before = crossfadeCalls.length;
        const listModeBefore = state.listMode;
        pendingCbs[1]();               // 舊世代（switchToSearchList 那一支）
        assert.equal(state.listMode, listModeBefore,
            '舊世代的 switchToSearchList 回呼不得改動 listMode');
        assert.equal(crossfadeCalls.length, before,
            '舊世代回呼不得淡入搜尋結果容器（否則搜尋面會閃一下再被蓋掉）');

        // ── 最新那一輪照常生效 ──
        pendingCbs[2]();
        assert.equal(state.listMode, 'wishlist', '最新世代的回呼必須正常完成切換');
    });
});

test('T2-DoD5-reduced-motion-final-state-same', async () => {
    // DoD 5：shouldSkip 形狀（立即 onOldFadeComplete）下資料結果與有動畫時相同
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));
    await withCrossfadeEnv({
        queryMap: T2_ELS,
        fadeImpl(oldEl, newEl, options) {
            // 模擬 playListModeCrossfade 的 shouldSkip／gsap-undefined 分支：立刻呼叫 cb
            if (options && typeof options.onOldFadeComplete === 'function') options.onOldFadeComplete();
            return null;
        },
    }, async () => {
        const state = makeWishlistThis({
            listMode: 'file',
            displayMode: 'detail',
            pageState: 'result',
            wishlistLoaded: false,
            wishlistItems: [],
            fileList: [{ path: '/x/a.mp4' }],
        });
        await state.switchToWishlist();
        assert.equal(state.listMode, 'wishlist');
        assert.equal(state.displayMode, 'grid');
        assert.equal(state.wishlistItems.length, 1);

        state.switchToSearchList();
        assert.equal(state.listMode, 'file');
        assert.equal(state.displayMode, 'detail');
        assert.equal(state.fileList.length, 1);
    });
});

test('T2-DoD6-file-mode-restore-after-crossfade', async () => {
    // DoD 6／mutation 點 1：crossfade 閘控路徑上 file 模式必須還原
    mockFetch(() => jsonResponse([{ number: 'W-1' }]));
    await withCrossfadeEnv({ queryMap: T2_ELS }, async () => {
        const state = makeWishlistThis({
            listMode: 'file',
            displayMode: 'detail',
            pageState: 'result',
            wishlistLoaded: true,
            wishlistItems: [],
            fileList: [{ path: '/x/a.mp4', searchResults: [] }],
        });

        await state.switchToWishlist();
        assert.equal(state.listMode, 'wishlist');
        assert.equal(state._preWishlistListMode, 'file');

        state.switchToSearchList();
        assert.equal(state.listMode, 'file', 'crossfade 路徑還原必須回到 file，不是 grid/search');
        assert.equal(state.displayMode, 'detail');
        assert.equal(state._preWishlistListMode, null);
        assert.equal(state.fileList.length, 1, 'fileList 不得被動到');
    });
});

// ─── TASK-141b-T3：書籤燈箱開啟／換片動畫接線 ─────────────────────────────
//
// 閘控路徑會臨時掛 window.GhostFly / window.SearchAnimations / gsap /
// document.querySelector；測完必須還原，否則污染同檔既有 stub。

function withLightboxEnv({ queryMap, gsapImpl, nextTickMode = 'sync' } = {}, fn) {
    const prevSA = globalThis.window.SearchAnimations;
    const prevGF = globalThis.window.GhostFly;
    const prevGsap = globalThis.gsap;
    const prevQS = globalThis.document.querySelector;

    const flyCalls = [];
    const openCalls = [];
    const switchCalls = [];
    const killedIds = [];
    const pendingTicks = [];

    globalThis.document.querySelector = (sel) => (queryMap && Object.prototype.hasOwnProperty.call(queryMap, sel))
        ? queryMap[sel]
        : null;

    globalThis.window.GhostFly = {
        playGridToLightbox(fromRect, lightboxEl, options) {
            flyCalls.push({ fromRect, lightboxEl, options: options || {} });
            return null;
        },
    };
    globalThis.window.SearchAnimations = {
        playLightboxOpen(lightboxEl, options) {
            openCalls.push({ lightboxEl, options: options || {} });
            return null;
        },
        playLightboxSwitch(contentEl, direction, options) {
            switchCalls.push({ contentEl, direction, options: options || {} });
            return null;
        },
    };
    globalThis.gsap = gsapImpl || {
        getById(id) {
            return {
                kill() { killedIds.push(id); },
            };
        },
    };

    const api = {
        flyCalls,
        openCalls,
        switchCalls,
        killedIds,
        pendingTicks,
        attachNextTick(state) {
            if (nextTickMode === 'defer') {
                state.$nextTick = (cb) => { pendingTicks.push(cb); };
            } else if (nextTickMode === 'sync') {
                state.$nextTick = (cb) => { cb(); };
            }
            // nextTickMode === 'absent' → 不掛 $nextTick，驗 safeNextTick 降級
        },
        flushTicks() {
            const queue = pendingTicks.splice(0, pendingTicks.length);
            for (const cb of queue) cb();
        },
    };

    const run = async () => {
        try {
            return await fn(api);
        } finally {
            if (prevSA === undefined) delete globalThis.window.SearchAnimations;
            else globalThis.window.SearchAnimations = prevSA;
            if (prevGF === undefined) delete globalThis.window.GhostFly;
            else globalThis.window.GhostFly = prevGF;
            if (prevGsap === undefined) delete globalThis.gsap;
            else globalThis.gsap = prevGsap;
            if (prevQS === undefined) delete globalThis.document.querySelector;
            else globalThis.document.querySelector = prevQS;
        }
    };
    return run();
}

function makeWishlistCard(slot, rect, src) {
    const img = {
        complete: true,
        src,
        getBoundingClientRect() { return rect; },
    };
    return {
        querySelector(sel) {
            return (sel === '.av-card-preview-img img') ? img : null;
        },
    };
}

const T3_RECT_0 = { x: 10, y: 20, width: 100, height: 140, top: 20, left: 10, bottom: 160, right: 110 };
const T3_RECT_5 = { x: 520, y: 40, width: 100, height: 140, top: 40, left: 520, bottom: 180, right: 620 };

function makeT3WishlistGrid() {
    const card0 = makeWishlistCard(0, T3_RECT_0, 'cover-slot-0.jpg');
    const card5 = makeWishlistCard(5, T3_RECT_5, 'cover-slot-5.jpg');
    return {
        querySelector(sel) {
            if (sel === '[data-slot="0"]') return card0;
            if (sel === '[data-slot="5"]') return card5;
            return null;
        },
    };
}

function makeT3LightboxEl() {
    const removed = [];
    const added = [];
    return {
        className: 'showcase-lightbox wishlist-lightbox',
        classList: {
            add(c) { added.push(c); },
            remove(c) { removed.push(c); },
            contains(c) { return added.includes(c) && !removed.includes(c); },
        },
        _added: added,
        _removed: removed,
    };
}

test('T3-DoD1-fly-origin-is-clicked-card', async () => {
    // DoD 1／mutation 點 2：飛行起點必須是被點的那一張卡（data-slot=index），不是永遠 slot 0
    const grid = makeT3WishlistGrid();
    const lbEl = makeT3LightboxEl();
    await withLightboxEnv({
        queryMap: {
            '.wishlist-grid': grid,
            '.wishlist-lightbox': lbEl,
        },
    }, async ({ flyCalls, openCalls, attachNextTick }) => {
        const state = makeWishlistThis({
            wishlistItems: Array.from({ length: 6 }, (_, i) => ({ number: `W-${i}` })),
            wishlistLightboxOpen: false,
            wishlistLightboxIndex: -1,
        });
        attachNextTick(state);

        searchStateWishlist().openWishlistLightbox.call(state, 5);

        assert.equal(state.wishlistLightboxOpen, true);
        assert.equal(state.wishlistLightboxIndex, 5);
        assert.equal(flyCalls.length, 1, '有 fromRect 時必須播 playGridToLightbox');
        assert.equal(flyCalls[0].fromRect, T3_RECT_5, '飛行起點必須是 data-slot=5 那張卡的封面');
        assert.equal(flyCalls[0].options.coverSrc, 'cover-slot-5.jpg');
        assert.equal(flyCalls[0].lightboxEl, lbEl);
        assert.equal(openCalls.length, 1);
        assert.equal(openCalls[0].lightboxEl, lbEl);
        assert.equal(openCalls[0].options.skipCover, true, '有飛行時 playLightboxOpen 必須帶 skipCover:true');
    });
});

test('T3-DoD2-no-fromRect-opens-without-skipCover', async () => {
    // DoD 2：拿不到 fromRect（寬度 0／圖未載完／卡不在 DOM）→ 不飛，只開燈箱且不帶 skipCover
    const grid = {
        querySelector() { return null; },
    };
    const lbEl = makeT3LightboxEl();
    await withLightboxEnv({
        queryMap: {
            '.wishlist-grid': grid,
            '.wishlist-lightbox': lbEl,
        },
    }, async ({ flyCalls, openCalls, attachNextTick }) => {
        const state = makeWishlistThis({
            wishlistItems: [{ number: 'W-0' }, { number: 'W-1' }],
            wishlistLightboxOpen: false,
            wishlistLightboxIndex: -1,
        });
        attachNextTick(state);

        searchStateWishlist().openWishlistLightbox.call(state, 1);

        assert.equal(state.wishlistLightboxOpen, true);
        assert.equal(state.wishlistLightboxIndex, 1);
        assert.equal(flyCalls.length, 0, '無 fromRect 不得呼叫 playGridToLightbox');
        assert.equal(openCalls.length, 1);
        assert.equal(openCalls[0].options.skipCover, undefined, '降級路徑不得帶 skipCover');
        assert.deepEqual(openCalls[0].options, {});
    });
});

test('T3-DoD3-consecutive-switch-kills-prior-timeline', async () => {
    // DoD 3／mutation 點 1：連按換片必須每次 kill lightboxOpen + lightboxSwitch，
    // 並清掉 gsap-animating；舊世代 nextTick 回呼不得對過期索引播動畫。
    const lbEl = makeT3LightboxEl();
    const wishlistContent = { id: 'wishlist-lightbox-content' };
    await withLightboxEnv({
        nextTickMode: 'defer',
        queryMap: {
            '.wishlist-lightbox': lbEl,
            '.wishlist-lightbox .lightbox-content': wishlistContent,
            '.lightbox-content': { id: 'main-lightbox-content' },
        },
    }, async ({ switchCalls, killedIds, attachNextTick, flushTicks, pendingTicks }) => {
        const state = makeWishlistThis({
            wishlistItems: Array.from({ length: 8 }, (_, i) => ({ number: `W-${i}` })),
            wishlistLightboxOpen: true,
            wishlistLightboxIndex: 0,
            _wishlistLbImgError: true,
        });
        attachNextTick(state);

        const w = searchStateWishlist();
        for (let i = 0; i < 5; i++) w.nextWishlistLightbox.call(state);

        assert.equal(state.wishlistLightboxIndex, 5, '連按 5 次必須停在第 5 次的目標索引');
        assert.equal(state._wishlistLbImgError, false);

        const switchKills = killedIds.filter((id) => id === 'lightboxSwitch');
        const openKills = killedIds.filter((id) => id === 'lightboxOpen');
        assert.equal(switchKills.length, 5, '每次換片都必須 kill lightboxSwitch（mutation 點 1）');
        assert.equal(openKills.length, 5, '每次換片都必須 kill lightboxOpen（設計決策 2）');
        assert.ok(lbEl._removed.includes('gsap-animating'), '換片前必須移除 wishlist-lightbox 的 gsap-animating');

        assert.equal(pendingTicks.length, 5, '五次換片各自排了一支 nextTick');
        assert.equal(switchCalls.length, 0, 'nextTick 尚未 flush 前不得播換片動畫');

        flushTicks();
        assert.equal(switchCalls.length, 1, '舊世代回呼必須被 _wishlistLbGeneration 短路，只播最新一次');
        assert.equal(switchCalls[0].direction, 'next');
        assert.equal(switchCalls[0].contentEl, wishlistContent);
    });
});

test('T3-DoD5-switch-targets-wishlist-lightbox-content', async () => {
    // DoD 5：playLightboxSwitch 的目標必須是 .wishlist-lightbox .lightbox-content，不是主燈箱那個
    const lbEl = makeT3LightboxEl();
    const wishlistContent = { id: 'wishlist-lightbox-content' };
    const mainContent = { id: 'main-lightbox-content' };
    await withLightboxEnv({
        queryMap: {
            '.wishlist-lightbox': lbEl,
            '.wishlist-lightbox .lightbox-content': wishlistContent,
            '.lightbox-content': mainContent,
        },
    }, async ({ switchCalls, attachNextTick }) => {
        const state = makeWishlistThis({
            wishlistItems: [{ number: 'W-0' }, { number: 'W-1' }, { number: 'W-2' }],
            wishlistLightboxOpen: true,
            wishlistLightboxIndex: 1,
        });
        attachNextTick(state);

        searchStateWishlist().prevWishlistLightbox.call(state);
        assert.equal(state.wishlistLightboxIndex, 0);
        assert.equal(switchCalls.length, 1);
        assert.equal(switchCalls[0].contentEl, wishlistContent, '不得誤抓主搜尋燈箱的 .lightbox-content');
        assert.equal(switchCalls[0].direction, 'prev');
        assert.notEqual(switchCalls[0].contentEl, mainContent);
    });
});

test('T3-DoD6-reduced-motion-final-state-same', async () => {
    // DoD 6：動畫函式回 null（shouldSkip 形狀）時，資料結果與有動畫時完全相同
    const grid = makeT3WishlistGrid();
    const lbEl = makeT3LightboxEl();
    const wishlistContent = { id: 'wishlist-lightbox-content' };
    await withLightboxEnv({
        queryMap: {
            '.wishlist-grid': grid,
            '.wishlist-lightbox': lbEl,
            '.wishlist-lightbox .lightbox-content': wishlistContent,
        },
    }, async ({ attachNextTick }) => {
        // 覆寫成一律回 null，模擬 shouldSkip／gsap-undefined
        globalThis.window.GhostFly.playGridToLightbox = () => null;
        globalThis.window.SearchAnimations.playLightboxOpen = () => null;
        globalThis.window.SearchAnimations.playLightboxSwitch = () => null;

        const state = makeWishlistThis({
            wishlistItems: Array.from({ length: 6 }, (_, i) => ({ number: `W-${i}` })),
            wishlistLightboxOpen: false,
            wishlistLightboxIndex: -1,
            _wishlistLbImgError: true,
        });
        attachNextTick(state);

        const w = searchStateWishlist();
        w.openWishlistLightbox.call(state, 2);
        assert.equal(state.wishlistLightboxOpen, true);
        assert.equal(state.wishlistLightboxIndex, 2);
        assert.equal(state._wishlistLbImgError, false);

        state._wishlistLbImgError = true;
        w.nextWishlistLightbox.call(state);
        assert.equal(state.wishlistLightboxIndex, 3);
        assert.equal(state._wishlistLbImgError, false);

        state._wishlistLbImgError = true;
        w.prevWishlistLightbox.call(state);
        assert.equal(state.wishlistLightboxIndex, 2);
        assert.equal(state._wishlistLbImgError, false);
        assert.equal(state.wishlistLightboxOpen, true);
    });
});

test('T3-DoD1-already-open-routes-to-switch', async () => {
    // 設計決策 6：燈箱已開啟時點別張 → 走換片，不重播開啟動畫
    const lbEl = makeT3LightboxEl();
    const wishlistContent = { id: 'wishlist-lightbox-content' };
    await withLightboxEnv({
        queryMap: {
            '.wishlist-lightbox': lbEl,
            '.wishlist-lightbox .lightbox-content': wishlistContent,
            '.wishlist-grid': makeT3WishlistGrid(),
        },
    }, async ({ flyCalls, openCalls, switchCalls, attachNextTick }) => {
        const state = makeWishlistThis({
            wishlistItems: Array.from({ length: 6 }, (_, i) => ({ number: `W-${i}` })),
            wishlistLightboxOpen: true,
            wishlistLightboxIndex: 1,
        });
        attachNextTick(state);

        searchStateWishlist().openWishlistLightbox.call(state, 4);
        assert.equal(state.wishlistLightboxIndex, 4);
        assert.equal(flyCalls.length, 0, '已開啟時不得重播飛行');
        assert.equal(openCalls.length, 0, '已開啟時不得重播 playLightboxOpen');
        assert.equal(switchCalls.length, 1);
        assert.equal(switchCalls[0].direction, 'next');
        assert.equal(switchCalls[0].contentEl, wishlistContent);

        switchCalls.length = 0;
        searchStateWishlist().openWishlistLightbox.call(state, 2);
        assert.equal(switchCalls[0].direction, 'prev');
    });
});
