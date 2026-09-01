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
    const fakeThis = {
        ...searchStateWishlist(),
        listMode: 'search',
        displayMode: 'detail',
        wishlistLoaded: true,
        wishlistItems: [],
    };

    await searchStateWishlist().switchToWishlist.call(fakeThis);
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
        wishlistItems: [{ number: 'OLD-001', _owned: false }],
        async loadWishlist() { loadCalls++; },
    };

    await searchStateWishlist().switchToWishlist.call(fakeThis);
    assert.equal(loadCalls, 1, '已載入過仍必須重新對帳一次');
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
    const items = [{ number: 'A-1', _owned: false }, { number: 'B-2', _owned: true }];
    mockFetch(() => jsonResponse(items));
    const fakeThis = { ...searchStateWishlist() };
    await searchStateWishlist().loadWishlist.call(fakeThis);
    assert.deepEqual(fakeThis.wishlistItems, items);
    assert.equal(fakeThis.wishlistLoaded, true);
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
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 5,
        wishlistLoaded: true,
        wishlistItems: [{ number: 'KEEP-1' }],
    };

    await searchStateWishlist().addToWishlist.call(fakeThis, result);
    assert.equal(result._wishlisted, false, '失敗應回滾 _wishlisted');
    assert.equal(fakeThis.wishlistCount, 5, '失敗應回滾 wishlistCount');
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
    const state = { ...searchStateWishlist(), listMode: 'search', displayMode: 'detail', wishlistLoaded: true };

    state.switchToWishlist.call(state);
    assert.equal(state.listMode, 'wishlist');
    assert.equal(state.displayMode, 'grid', 'wishlist 下 displayMode 不得為 detail');

    state.switchToSearchList.call(state);
    assert.equal(state.listMode, 'search');
    assert.equal(state.displayMode, 'detail', '切回來要回到原本的 detail');
    assert.equal(state._preWishlistDisplayMode, null, '還原後要清掉，不得殘留');
});

test('switchToWishlist: 重複點同一段不得把 grid 記成「切進來之前的值」', () => {
    // 已經在 wishlist 時再點一次書籤段，若無條件覆寫 _preWishlistDisplayMode，
    // 記住的會變成 'grid'，切回搜尋段就再也回不到 detail。
    const state = { ...searchStateWishlist(), listMode: 'search', displayMode: 'detail', wishlistLoaded: true };
    state.switchToWishlist.call(state);
    state.switchToWishlist.call(state);   // 重複點
    state.switchToSearchList.call(state);
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

// ─── TASK-140-T12：F7 批次清理（DoD 5a–5d）────────────────────────────────

// 技術要點 §4：plain spread 會在展開當下求值 getter 並凍結成 0，必須保留 descriptor。
function makeWishlistThis(overrides = {}) {
    const target = {};
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(searchStateWishlist()));
    Object.assign(target, overrides);
    return target;
}

// DoD 5a（mutation 圍欄 expect_fail 字串必須逐字相等）
test('ownedWishlistCount：3 筆 _owned:true 加 2 筆 false ⇒ 回 3', () => {
    const state = makeWishlistThis({
        wishlistItems: [
            { number: 'A-1', _owned: true },
            { number: 'A-2', _owned: true },
            { number: 'A-3', _owned: true },
            { number: 'B-1', _owned: false },
            { number: 'B-2', _owned: false },
        ],
    });
    assert.equal(state.ownedWishlistCount, 3);
});

// DoD 5b
test('cleanupOwnedWishlist() 成功：wishlistCount 減掉 deleted_count、wishlistItems 只剩未入手項目、showToast 帶 success', async () => {
    mockFetch(() => jsonResponse({ deleted_count: 3 }));
    const toasts = [];
    globalThis.window.t = (key, params) => `${key}:${JSON.stringify(params ?? {})}`;
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 5,
        wishlistItems: [
            { number: 'OWN-1', _owned: true },
            { number: 'OWN-2', _owned: true },
            { number: 'OWN-3', _owned: true },
            { number: 'KEEP-1', _owned: false },
            { number: 'KEEP-2', _owned: false },
        ],
        showToast(msg, type) { toasts.push({ msg, type }); },
    };

    await searchStateWishlist().cleanupOwnedWishlist.call(fakeThis);

    assert.equal(fakeThis.wishlistCount, 2, 'wishlistCount 必須減掉 deleted_count=3');
    assert.deepEqual(
        fakeThis.wishlistItems.map((i) => i.number),
        ['KEEP-1', 'KEEP-2'],
        'wishlistItems 只剩未入手項目',
    );
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0].type, 'success');
});

// DoD 5c
test('cleanupOwnedWishlist() 失敗（resp.ok===false）：wishlistCount 不變、wishlistItems 不變、toast 是 error', async () => {
    mockFetch(() => jsonResponse({}, { ok: false, status: 500 }));
    const toasts = [];
    globalThis.window.t = (key) => key;
    const items = [
        { number: 'OWN-1', _owned: true },
        { number: 'KEEP-1', _owned: false },
    ];
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 2,
        wishlistItems: items,
        showToast(msg, type) { toasts.push({ msg, type }); },
    };

    await searchStateWishlist().cleanupOwnedWishlist.call(fakeThis);

    assert.equal(fakeThis.wishlistCount, 2, '失敗時 wishlistCount 不得變');
    assert.equal(fakeThis.wishlistItems, items, '失敗時 wishlistItems 陣列參考不得被替換');
    assert.equal(fakeThis.wishlistItems.length, 2, '失敗時一筆都沒少');
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0].type, 'error');
});

// sonnet review P2（Opus 2026-09-02 補）：resp.json() 本身會 throw（2xx 但 body 不是合法
// JSON）。不包 try 的話那條路徑是 unhandled rejection ⇒ 使用者按完清理鈕**什麼提示都沒有**，
// 不知道成功還是失敗。
test('cleanupOwnedWishlist() 回應解析失敗（resp.json() throw）：wishlistCount 不變、wishlistItems 不變、toast 是 error', async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token < in JSON'); } }));
    const toasts = [];
    globalThis.window.t = (key) => key;
    const items = [
        { number: 'OWN-1', _owned: true },
        { number: 'KEEP-1', _owned: false },
    ];
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 2,
        wishlistItems: items,
        showToast(msg, type) { toasts.push({ msg, type }); },
    };

    await searchStateWishlist().cleanupOwnedWishlist.call(fakeThis);

    assert.equal(fakeThis.wishlistCount, 2, '解析失敗時 wishlistCount 不得變');
    assert.equal(fakeThis.wishlistItems, items, '解析失敗時 wishlistItems 陣列參考不得被替換');
    assert.equal(fakeThis.wishlistItems.length, 2, '解析失敗時一筆都沒少');
    assert.equal(toasts.length, 1, '解析失敗必須出一個 toast——不出的話使用者完全不知道發生了什麼');
    assert.equal(toasts[0].type, 'error');
});

// DoD 5d
test('cleanupOwnedWishlist() 成功後未入手的一筆都沒被動到（spec F7 驗收4）', async () => {
    mockFetch(() => jsonResponse({ deleted_count: 2 }));
    globalThis.window.t = (key, params) => `${key}:${JSON.stringify(params ?? {})}`;
    const unowned = [
        { number: 'KEEP-A', _owned: false },
        { number: 'KEEP-B', _owned: false },
    ];
    const fakeThis = {
        ...searchStateWishlist(),
        wishlistCount: 4,
        wishlistItems: [
            { number: 'OWN-X', _owned: true },
            { number: 'OWN-Y', _owned: true },
            ...unowned,
        ],
        showToast() {},
    };

    await searchStateWishlist().cleanupOwnedWishlist.call(fakeThis);

    const remaining = new Set(fakeThis.wishlistItems.map((i) => i.number));
    assert.deepEqual(
        [...remaining].sort(),
        ['KEEP-A', 'KEEP-B'].sort(),
        '剩下的 number 集合必須與原本未入手的集合逐值相同',
    );
});
