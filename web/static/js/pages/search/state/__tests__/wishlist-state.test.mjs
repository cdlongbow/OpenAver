// TASK-140-T5：wishlist 狀態分片 ＋ listMode 對帳表 ＋ membership hydration
// TASK-140-T10：listMode/displayMode 還原不變式
//
// 覆蓋 DoD：
//   - loadMore 白名單化（M1）
//   - saveState live 取值／restoreState switchToWishlist／resolveVisibleDisplayMode（T10）
//   - addToWishlist I3 回滾（M3）
//   - switchToWishlist 設 displayMode='grid'
//   - membership hydration 三條
//   - main.js init() 呼叫 loadWishlistCount()

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };

if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
}

// state/__tests__ → 上一層 __tests__/alias-loader.mjs（鏡射 pages/search/__tests__ 慣例）
register(new URL('../../__tests__/alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateWishlist, cardActionState } = await import('../wishlist.js');
const { searchStatePersistence, resolveVisibleDisplayMode } = await import('../persistence.js');
const { searchStateNavigation } = await import('../navigation.js');
const { searchStateBase } = await import('../base.js');
const { searchStateSearchFlow } = await import('../search-flow.js');
const { searchPage } = await import('../../main.js');

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

// DoD 4b

// DoD 4c

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

// DoD 4f（mutation M3）

// DoD 4f 接線：restoreState 必須真的呼叫 resolveVisibleDisplayMode（純函式測不到這層）

// ─── hydration ①：init() 呼叫 loadWishlistCount ───────────────────────────


// ─── P2-2：兩張卡交錯時計數用增量、不用快照還原 ───────────────────────────


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


// ─── switchToWishlist displayMode ─────────────────────────────────────────


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

// ─── loadWishlistCount / loadWishlist ─────────────────────────────────────


// branch review P2（2026-09-02）：對帳在伺服器端自動刪書籤之後，前端唯一能感知
// 「權威狀態變了」的通道就是這支 GET 的回應。它以前只寫清單不寫計數 ⇒ badge 會停在
// 舊數字直到整頁重新整理。


// ─── TASK-141b-T10／CD-19：封面載入狀態不得掛在 wishlistItems 元素物件上 ───
// 不變式：同一番號、同一封面 URL，loadWishlist() 跑第二次（回傳等值但全新的物件陣列）
// 之後，該卡的封面仍為可見狀態（_wishlistCoverLoaded[番號] 仍為 true）。
// 候選 (a)：狀態掛在 wishlist.js state 上的番號→bool map，loadWishlist() 完全不碰。

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


// ─── TASK-140-T6：cardActionState 四態（mutation M1/M2）───────────────────


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

// DoD 4c（mutation M2）— 測試名必須逐字等於 mutation expect_fail

// DoD 4e

// T11a 第 2 輪：破圖 flag 殘留——看過一張 404 封面後再開別張會一直顯示占位

// Opus 2026-09-02 補（grok 自報偏離 #2）：箭頭換片也要重設，否則先看到一部沒封面的片、
// 再按箭頭切到有封面的那部，封面不會出現——畫面停在「無圖」占位。

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


// Codex 二審 P2（改指向 T4）：對帳觸發點改成 GET /api/wishlist 後，仍要守住
// switchToSearchList → switchToWishlist 這條 tab 切換路徑上的 abort registry。

// branch review P2-1：POST 回 added:false（那個番號本來就在）時，樂觀 +1 必須收回。
// 到達路徑：切換版本把整顆結果物件換掉 ⇒ `_wishlisted` 一起沒了 ⇒ 卡片變回「加入書籤」
// ⇒ 再按一次。與 removeFromWishlist 的 success:false 是同一組對稱處置。

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


// ─── TASK-141b-T2：書籤牆進場 ＋ 分頁切換 crossfade ─────────────────────────
//
// 閘控路徑測試會臨時掛 window.SearchAnimations / document.querySelector /
// window.GridMotion；測完必須還原，否則污染同檔既有 stub。

function withCrossfadeEnv({ queryMap, fadeImpl }, fn) {
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

// ⚠️ `.wishlist-grid` 這一筆**沒有 `classList`**（見 gotchas FE-TIMING-11 同期的 T6 紀錄）。
// T6 之所以沒炸純粹是巧合：用到本 fixture 的那支測試 `wishlistItems` 初值是空陣列
// ⇒ `goneItems` 恆空 ⇒ 走不到 `grid.classList.add('flip-guard')`。
// **下一支動 `loadWishlist()` 或改本 fixture 的 task，只要讓那支測試的清單非空就會炸在
// `classList` undefined 上，而錯誤訊息完全不會指向真正的原因。** 動之前先補 `classList` stub。
// 附帶：node:test 的零-DOM 環境**沒有 `requestAnimationFrame`**——未來在 `wishlist.js` 加
// 巢狀 `$nextTick(() => requestAnimationFrame(...))` 都會撞到，沿用 T6 的 guarded stub。
const T2_ELS = {
    '#resultCard': { id: 'resultCard' },
    '#emptyState': { id: 'emptyState' },
    '#loadingState': { id: 'loadingState' },
    '#errorState': { id: 'errorState' },
    '.wishlist-panel': { className: 'wishlist-panel' },
    '.wishlist-grid': { className: 'wishlist-grid' },
};


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


// TASK-141b-T4：closeWishlistLightbox 需要 lbEl 能查到 .lightbox-cover img，
// T3 的 makeT3LightboxEl() 只有 classList，沒有 querySelector——純追加一個新 helper，
// 不修改 makeT3LightboxEl 本體（DoD 7：既有測試零改動）。
function makeT4CoverImg(rect, src) {
    return {
        src: src,
        getBoundingClientRect() { return rect; },
    };
}

function makeT4LightboxEl(coverImg) {
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
        querySelector(sel) {
            return (sel === '.lightbox-cover img') ? coverImg : null;
        },
    };
}


// ===== TASK-141b-T5: 書籤燈箱觸控滑動 =====

function makeSwipeSpies(overrides = {}) {
    const nextCalls = [];
    const prevCalls = [];
    return {
        nextCalls,
        prevCalls,
        nextWishlistLightbox() { nextCalls.push(true); },
        prevWishlistLightbox() { prevCalls.push(true); },
        ...overrides,
    };
}

test('T5-DoD1-swipe-left-calls-next-not-prev', () => {
    // 座標刻意挑選（見「技術要點」5）：同時覆蓋 DoD1（方向）與 DoD2（順序不變式）——
    // 若實作把 dir 算在「清空 state 之後」讀，detectSwipe(null, null, 100, 150, 50) 回 null，
    // 兩個 spy 都不會被呼叫，下面的 assert.equal(nextCalls.length, 1) 會失敗。
    const spies = makeSwipeSpies();
    const state = makeWishlistThis({ ...spies, wishlistLightboxOpen: true });
    searchStateWishlist()._wishlistLbTouchStart.call(state, { touches: [{ clientX: 500, clientY: 100 }] });
    searchStateWishlist()._wishlistLbTouchEnd.call(state, { changedTouches: [{ clientX: 100, clientY: 150 }] });
    assert.equal(spies.nextCalls.length, 1, '左滑必須呼叫 nextWishlistLightbox 恰好一次');
    assert.equal(spies.prevCalls.length, 0, '左滑不得呼叫 prevWishlistLightbox');
    assert.equal(state._wishlistLbTouchStartX, null, 'touchend 之後座標必須清回 null（DoD 7）');
    assert.equal(state._wishlistLbTouchStartY, null);
});


// ─── TASK-141b-T6：F8.1/F8.2 FLIP 收攏 ─────────────────────────────────────
//
// 閘控路徑會臨時掛 window.GridMotion（captureFlipState/playFlipFilter）、
// document.querySelector、requestAnimationFrame；測完必須還原，否則污染同檔既有 stub。
//
// requestAnimationFrame 用「佇列，呼叫端手動 flush」而不是全域那顆 setTimeout(fn,0) 版本
// ——DoD 4（世代收攏）需要精準控制「call A 的 tick 與 frame」跟「call B 的 tick 與 frame」
// 之間的交錯順序，用 setTimeout 的話時序不受控。

function makeFlipGridEl() {
    const classes = new Set();
    return {
        className: 'wishlist-grid ds-gallery-composition',
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
        },
        offsetHeight: 100,
        _classes: classes,   // 測試內部直接讀，不當作 DOM API 的一部分
    };
}

function withFlipEnv({ queryMap, captureImpl, playImpl } = {}, fn) {
    const prevGM = globalThis.window.GridMotion;
    const prevQS = globalThis.document.querySelector;
    const prevRAF = globalThis.requestAnimationFrame;

    const captureCalls = [];
    const playCalls = [];
    const pendingTicks = [];
    const pendingFrames = [];

    globalThis.document.querySelector = (sel) => (queryMap && Object.prototype.hasOwnProperty.call(queryMap, sel))
        ? queryMap[sel] : null;

    globalThis.window.GridMotion = {
        captureFlipState(gridEl) {
            captureCalls.push({ gridEl });
            return (typeof captureImpl === 'function') ? captureImpl(gridEl) : { __mockFlipState: true };
        },
        playFlipFilter(gridEl, state) {
            playCalls.push({ gridEl, state });
            return (typeof playImpl === 'function') ? playImpl(gridEl, state) : { fake: 'timeline' };
        },
    };

    globalThis.requestAnimationFrame = (cb) => { pendingFrames.push(cb); return pendingFrames.length; };

    const api = {
        captureCalls, playCalls,
        attachNextTick(state) {
            state.$nextTick = (cb) => { pendingTicks.push(cb); };
        },
        flushTicks() {
            const q = pendingTicks.splice(0, pendingTicks.length);
            for (const cb of q) cb();
        },
        flushFrames() {
            const q = pendingFrames.splice(0, pendingFrames.length);
            for (const cb of q) cb();
        },
        flush() { api.flushTicks(); api.flushFrames(); },
    };

    const run = async () => {
        try {
            return await fn(api);
        } finally {
            if (prevGM === undefined) delete globalThis.window.GridMotion; else globalThis.window.GridMotion = prevGM;
            if (prevQS === undefined) delete globalThis.document.querySelector; else globalThis.document.querySelector = prevQS;
            if (prevRAF === undefined) delete globalThis.requestAnimationFrame; else globalThis.requestAnimationFrame = prevRAF;
        }
    };
    return run();
}


// ─── TASK-141b-T7：書籤燈箱移除鈕 ＋ 索引收斂 ──────────────────────────

function makeRemoveSpy(state) {
    // 薄封裝的測試手法：spy 取代真實 removeFromWishlist，但仍做等價的同步過濾，
    // 讓 DoD1-3 的索引收斂邏輯可以在不牽動 fetch/FLIP 的情況下被獨立驗證。
    const calls = [];
    state.removeFromWishlist = function (number, context) {
        calls.push({ number, context });
        this.wishlistItems = this.wishlistItems.filter((i) => i.number !== number);
        return Promise.resolve();
    };
    return calls;
}

test('T7-DoD1-remove-middle-keeps-index-not-close', () => {
    const state = makeWishlistThis({
        wishlistItems: [{ number: 'A' }, { number: 'B' }, { number: 'C' }, { number: 'D' }, { number: 'E' }],
        wishlistLightboxOpen: true,
        wishlistLightboxIndex: 2,
        _wishlistLbImgError: true,
    });
    const removeCalls = makeRemoveSpy(state);
    const closeCalls = [];
    state.closeWishlistLightbox = () => { closeCalls.push(1); };

    searchStateWishlist().removeFromWishlistInLightbox.call(state);

    assert.equal(removeCalls.length, 1, '必須呼叫既有 removeFromWishlist 恰好一次');
    assert.deepEqual(removeCalls[0], { number: 'C', context: 'lightbox' },
        '移除的必須是 index=2 對應的那一筆（C），context 必須是 lightbox');
    assert.equal(closeCalls.length, 0, '非最後一筆時不得呼叫 closeWishlistLightbox');
    assert.equal(state.wishlistLightboxIndex, 2, '刪中間，索引維持原值（畫面顯示遞補上來的那張）');
    assert.equal(state._wishlistLbImgError, false, '收斂後必須重設破圖旗標');
    assert.equal(state.wishlistItems.length, 4);
});


// ─── TASK-141b-T8：F6 加入飛入（三入口）＋ F8.3 搜尋側移除回饋 ＋ badge ±1 反饋 ────

function withWishlistFlyEnv({ queryMap = {}, ghostFlyImpl, badgeShrinkImpl } = {}, fn) {
    const prevDoc = globalThis.document;
    const prevGF = globalThis.window.GhostFly;
    const prevSA = globalThis.window.SearchAnimations;
    const prevT = globalThis.window.t;
    globalThis.document = {
        addEventListener() {},
        querySelector: (sel) => (Object.prototype.hasOwnProperty.call(queryMap, sel) ? queryMap[sel] : null),
    };
    const flyCalls = [];
    globalThis.window.GhostFly = {
        playInboundFly: (opts) => { flyCalls.push(opts); return ghostFlyImpl ? ghostFlyImpl(opts) : null; },
    };
    const badgeCalls = [];
    globalThis.window.SearchAnimations = {
        ...prevSA,
        playWishlistBadgeShrink: (el) => { badgeCalls.push(el); return badgeShrinkImpl ? badgeShrinkImpl(el) : null; },
    };
    globalThis.window.t = (key) => key;
    const restore = () => {
        globalThis.document = prevDoc;
        if (prevGF === undefined) delete globalThis.window.GhostFly; else globalThis.window.GhostFly = prevGF;
        if (prevSA === undefined) delete globalThis.window.SearchAnimations; else globalThis.window.SearchAnimations = prevSA;
        if (prevT === undefined) delete globalThis.window.t; else globalThis.window.t = prevT;
    };
    return Promise.resolve()
        .then(() => fn({ flyCalls, badgeCalls }))
        .finally(restore);
}


// ─── TASK-141b-T9：wishlistAgingStage/wishlistAgingDays 在真實 mixin 上的委派 wiring ────
// 不 mock Date.now()——用真實 wall-clock 相對算出 created_at，證明消費端確實把 Date.now()
// 傳進純函式（而非讀取某個預存欄位）。

function toWishlistTimestamp(ms) {
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}


// ─── Codex PR review P2 ＋ delta review（Opus 2026-09-03）：燈箱刪除失敗的索引回滾 ───
//
// 🔴 不變式：**DELETE 失敗回滾不得改變畫面上當下那一片。**
//
// 為什麼會破：回滾是把那一筆 `unshift` 回**陣列開頭**（不是原位），開頭以後每個索引都
// 位移一格；而燈箱是唯一用裸陣列索引定位的消費端 ⇒ 使用者的索引沒動、底下那一片卻換了。
// 書籤牆不會有這個症狀：它是 `:key="item.number"`，重排只是換位置。
//
// ⚠️ 這裡刻意**不是**「回到被刪的那一片」（本輪第一版的寫法，delta review 推翻）：
//   ① 刪 B 時畫面早就樂觀切到 C，拉回 B 是多做一次使用者沒要求的換片；
//   ② DELETE 撞 DB 鎖是 5 秒 busy timeout，那 5 秒內使用者早已按到別張，
//      晚到的失敗回應會把他硬拉回去（下面第二支測試就是這個競態）。
//
// 真實觸發條件不是理論值：`web/routers/wishlist.py` 的 DELETE 沒有包 try/except，
// 掃描中 `upsert_batch()` 持著寫入鎖時，`conn.commit()` 撞 busy timeout 會拋成 HTTP 500
// （同一種鎖競爭該檔 :110 已經為 GET 記錄過一次）。


// ─── branch review P2-2（Opus 2026-09-03）：進場與差集收攏不得同時打同一批卡 ───
//
// 🔴 不變式：**同一批卡片、同一次載入，只能有一支動畫寫它的 opacity。**
//
// 情境：看過書籤牆 → 切走 → 掃描把其中幾片入庫 → 切回書籤牆（spec F8.2 驗收 4 那一幕）。
// `switchToWishlist()` 的 `loadPromise.then(playEntry)` 是 microtask，而 `loadWishlist()` 的
// FLIP 派發包在 `$nextTick → rAF` 裡 ⇒ playEntry 一定先跑，先 `gsap.set(opacity:0, y:20)` 再往 1 補；
// 一個 frame 之後 `Flip.from(state)` 帶著 `props:'opacity'` 對同一批卡再開一條 opacity tween。
// 兩條誰都沒 kill 誰（`Flip.killFlipsOf` 只殺 Flip、playEntry 的 `killTweensOf` 在 Flip 之前）。
//
// 既有測試照不到這條：`T2-DoD1` 用 `wishlistLoaded: false` ⇒ 無 FLIP；
// `T6-DoD3` 直接呼叫 `loadWishlist()` ⇒ 無 playEntry。兩條各驗一半，合起來的路徑沒有 oracle。

function withEntryAndFlipEnv({ queryMap }, fn) {
    const prevGM = globalThis.window.GridMotion;
    const prevSA = globalThis.window.SearchAnimations;
    const prevQS = globalThis.document.querySelector;
    const prevRAF = globalThis.requestAnimationFrame;

    const playEntryCalls = [];
    const captureCalls = [];
    const playFlipCalls = [];
    const pendingTicks = [];
    const pendingFrames = [];

    globalThis.document.querySelector = (sel) => (queryMap && Object.prototype.hasOwnProperty.call(queryMap, sel))
        ? queryMap[sel] : null;
    globalThis.window.SearchAnimations = {
        playListModeCrossfade(oldEl, newEl, options) {
            if (options && typeof options.onOldFadeComplete === 'function') options.onOldFadeComplete();
            return null;
        },
    };
    globalThis.window.GridMotion = {
        playEntry(el) { playEntryCalls.push(el); return null; },
        captureFlipState(gridEl) { captureCalls.push(gridEl); return { __mockFlipState: true }; },
        playFlipFilter(gridEl, state) { playFlipCalls.push({ gridEl, state }); return { fake: 'timeline' }; },
    };
    globalThis.requestAnimationFrame = (cb) => { pendingFrames.push(cb); return pendingFrames.length; };

    const api = {
        playEntryCalls, captureCalls, playFlipCalls,
        attachNextTick(state) { state.$nextTick = (cb) => { pendingTicks.push(cb); }; },
        flush() {
            for (const cb of pendingTicks.splice(0, pendingTicks.length)) cb();
            for (const cb of pendingFrames.splice(0, pendingFrames.length)) cb();
        },
    };
    const restore = () => {
        globalThis.window.GridMotion = prevGM;
        globalThis.window.SearchAnimations = prevSA;
        globalThis.document.querySelector = prevQS;
        globalThis.requestAnimationFrame = prevRAF;
    };
    const run = async () => { try { return await fn(api); } finally { restore(); } };
    return run();
}

// 這個 fixture 的 `.wishlist-grid` **必須有 classList**（flip-guard 會用到）——
// 見該 fixture 上方註解記的那條巧合。
const P22_ELS = {
    '#resultCard': { id: 'resultCard' },
    '.wishlist-panel': { className: 'wishlist-panel' },
    '.wishlist-grid': { className: 'wishlist-grid', classList: { add() {}, remove() {} }, offsetHeight: 0 },
};


// ─── branch review P3-8（Opus 2026-09-03）：燈箱沒開時觸控不得換片 ───
// 主燈箱有三條短路（`grid-mode.js:448-455`），T5 鏡射時漏抄第三條「燈箱沒開不換片」。
// 今天碰不到是因為 `.showcase-lightbox` 關著時 `pointer-events: none`（showcase.css:857）——
// 但那是**別的檔案的樣式**在替這支 handler 擋，不是 handler 自己守住的。

// ─── Codex PR#177 第 2 輪 P2（Opus 2026-09-03）：破圖旗標要有回得來的路 ───
//
// 🔴 不變式：**封面檔從「不存在」變成「存在」的那一刻，:src 必須變一次。**
//
// 為什麼：`add_wishlist()` 是**先 commit 那一列、才下載封面**
// （web/routers/wishlist.py:69 → :90）。使用者按下加入之後馬上點書籤分頁，
// GET 拿到的列已經有 created_at、封面檔卻還沒寫完 ⇒ 404 ⇒ `_wishlistCoverError`
// 永久（CD-19 刻意不讓 loadWishlist() 碰它）⇒ 那部片在牆上是灰底占位，只有 F5 才會好。
// **真瀏覽器實測：延遲 100ms 就撞得到。**
//
// ⚠️ 光把旗標清掉沒有用——實測清了 img 也不會重新請求（naturalWidth 仍 0、complete 仍 true），
// 只會把整齊的占位換成破圖 icon。唯一有效的手段是**讓 URL 變**，所以是 token 不是布林。
//
// 上一輪（同一 artifact）的修法只治了「不要發那個必定 404 的請求」；這一條是它的另一半。
// 依 CLAUDE.md 停損 ①，這不是在同一個機制上疊補丁——兩者合起來是一條規則：
// **請求只在檔案應該存在時發出；檔案剛變成存在時讓 URL 變一次。**


// ─── Codex PR#177 第 3 輪 P3（Opus 2026-09-03）：過期回呼不得拔掉現任世代的 flip-guard ───
//
// 🔴 不變式：**最新那一次 FLIP 開始播的當下，`flip-guard` 必須在 grid 上。**
//
// rAF 回呼依註冊順序執行，所以連按兩張卡的垃圾桶時是
// A(stale) 先跑 → `remove('flip-guard')` → B(current) 才跑 ⇒ **最新那次在沒有 guard 的
// 情況下開始播**，而那個 class 存在的唯一理由就是在動畫期間把 hover 的 transform
// 從 transition list 拿掉（theme.css B15）。
//
// ⚠️ 為什麼不是改成「stale 分支不要 remove」：那會讓
// 世代不符的 stale 分支就沒人接手清理 flip-guard——那條殘留範圍比本條更廣，
// 不該為了本條把它變弱。改用**冪等的重新宣告**：
// class 已在就沒事、被上一個世代拔掉就補回來，移除的責任完全沒有改變。
//
// 這個 race 的窗口在正常裝置上只有一個 frame（≈16.7ms），但 rAF 被推遲多久窗口就變寬多少
// （這段路徑每次都強制 reflow，弱裝置上會放大）。後果是純視覺：333ms 內、且滑鼠剛好停在
// 剩下的某張卡上時會看到一下抖動。


// ─── Codex PR#177 第 3 輪窮舉盤點（Opus 2026-09-03）：三張封面表必須整組動 ───
//
// 🔴 不變式：**三張表描述的是「`:src` 這一刻算出來的那條 URL」的載入結果，
//            不是「這個番號」的歷史 ⇒ 凡是 URL／資源身分改變的事件，三張一起動。**
//
// 前兩輪各補了一角（error 旗標、retry token），第三輪的 finding 是 `loaded` 沒被算進那一組：
// 移除書籤會把封面檔一起刪掉（routers/wishlist.py:141），之後重新加入拿到的是**全新的一份**，
// 而 `_wishlistCoverLoaded[n]` 還留著上一份的 true ⇒ 新卡片跳過骨架直接顯示。
//
// 下面第二支測的是**位置**：`cover_available` 區塊必須在 `already_owned` / `added:false`
// 兩個早退**之前**。後端在 `added:false` 時一樣算好了那個欄位（檔案存不存在），
// 早退會把它丟掉——那是「吃到 404 窗口 → 切版本 → 再按一次加入」永遠灰底無圖的成因。

test('P3-cover-state-cleared-as-a-group-on-successful-add', async () => {
    mockFetch((url, opts) => {
        if (opts.method === 'POST') return jsonResponse({ success: true, added: true, cover_available: true });
        return jsonResponse([]);
    });
    const state = makeWishlistThis({ wishlistLoaded: false, wishlistCount: 0, searchResults: [] });
    // 模擬「這個番號先前被移除過，而移除前它的封面已經載入成功」
    state._wishlistCoverLoaded['RE-1'] = true;
    state._wishlistCoverError['RE-1'] = true;

    await state.addToWishlist({ number: 'RE-1' });

    assert.equal(state._wishlistCoverLoaded['RE-1'], undefined,
        'loaded 必須一起作廢——移除會刪掉封面檔，重新加入拿到的是全新的一份');
    assert.equal(state._wishlistCoverError['RE-1'], undefined, 'error 一起作廢');
    assert.ok(state._wishlistCoverRetry['RE-1'], 'token 一起 bump（讓 URL 真的變一次）');
});

