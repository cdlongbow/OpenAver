// TASK-140-T5：wishlist 狀態分片 ＋ listMode 對帳表 ＋ membership hydration
//
// 覆蓋 DoD：
//   - loadMore 白名單化（M1）
//   - _persistableListMode（M2）
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
const { searchStatePersistence } = await import('../persistence.js');
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

// ─── 對帳表 #5：_persistableListMode（mutation M2）────────────────────────

test('_persistableListMode: wishlist→null、file/search/null 原樣', () => {
    const p = searchStatePersistence();
    assert.equal(p._persistableListMode('wishlist'), null);
    assert.equal(p._persistableListMode('file'), 'file');
    assert.equal(p._persistableListMode('search'), 'search');
    assert.equal(p._persistableListMode(null), null);
});

test('saveState: listMode="wishlist" 寫入 sessionStorage 時轉成 null', () => {
    const store = {};
    globalThis.sessionStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => store[k] ?? null,
        removeItem: (k) => { delete store[k]; },
    };

    const fakeThis = {
        ...searchStatePersistence(),
        STATE_KEY: 'test-wishlist-persist',
        _searchSnapshot: null,
        pageState: 'result',
        searchResults: [],
        currentIndex: 0,
        currentQuery: '',
        currentOffset: 0,
        hasMoreResults: false,
        fileList: [],
        currentFileIndex: 0,
        listMode: 'wishlist',
        searchQuery: '',
        displayMode: 'grid',
        currentMode: '',
        actressProfile: null,
    };

    searchStatePersistence().saveState.call(fakeThis);
    const saved = JSON.parse(store['test-wishlist-persist']);
    assert.equal(saved.listMode, null, 'wishlist 不得寫進 snapshot');
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
