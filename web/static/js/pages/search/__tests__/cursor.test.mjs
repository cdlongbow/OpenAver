// TASK-175d-T7：搜尋狀態欄位 currentCursor（存、送、還原續頁 token；CD-175d-11）
//
// 守住的行為（前端只存、只送、不解析）：
//   - loadMore：URL 逐字＝既有 URL ＋ &cursor=<token>；成功後換成回應 token；沒有 cursor ⇒ null；
//     失敗／晚到回應不改欄位
//   - 第一頁寫入：stream result（無 seed／seed→result-complete→result）與 fallbackSearch；
//     doSearch 起手、clearAll ⇒ null；cancelSearch 還原 snapshot 的值
//   - 持久化：saveState 兩條分支、缺欄位還原 ⇒ null、存→還原→載入更多送同一個 token
//   - _commitSearchResults（無 cursor 的 payload）⇒ null
//
// buildSearchUrl 的 cursor 組合表在 search-url.test.mjs（URL 單一出口的家），此檔不重複。
// 假 fetch 刻意忽略 signal（FE-GUARD-40）：不因 abort 自行 reject，否則世代守衛變死碼、拿掉照綠。
// 回應一律由測試手動放行，flush() 在 finally 放行。
// merge() 用 descriptor 版（FE-ALPINE-21：Object.assign／spread 會把 getter 凍結）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {}, querySelector() { return null; } };
window.t = (k, p) => (p ? k + JSON.stringify(p) : k);

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateBase } = await import('../state/base.js');
const { searchStateSearchFlow } = await import('../state/search-flow.js');
const { searchStateNavigation } = await import('../state/navigation.js');
const { searchStatePersistence } = await import('../state/persistence.js');


class FakeES {
    static instances = [];
    constructor(url) {
        this.url = url;
        this.closed = false;
        this.onmessage = null;
        this.onerror = null;
        FakeES.instances.push(this);
    }
    close() { this.closed = true; }
}
FakeES.CLOSED = 2;
globalThis.EventSource = FakeES;

function makeFetch() {
    const f = {
        calls: [],
        pending: [],
        fn(url, opts) {
            f.calls.push({ url, opts });
            return new Promise((resolve, reject) => f.pending.push({ resolve, reject }));
        },
        flush() {
            for (const p of f.pending.splice(0)) {
                p.resolve({ ok: false, json: async () => ({ success: false }) });
            }
        },
    };
    return f;
}

const tick = () => new Promise((r) => setImmediate(r));

function merge(...parts) {
    const target = {};
    for (const part of parts) {
        Object.defineProperties(target, Object.getOwnPropertyDescriptors(part));
    }
    return target;
}

const STUBS = {
    $nextTick() {},
    checkLocalStatus() {},
    preloadImages() {},
    _resetCoverState() {},
};

function makePage(overrides = {}) {
    return merge(searchStateBase(), searchStateSearchFlow(), searchStateNavigation(), STUBS, overrides);
}

async function withEnv(fn, overrides = {}) {
    FakeES.instances.length = 0;
    const fetchFake = makeFetch();
    const realFetch = globalThis.fetch;
    globalThis.fetch = (u, o) => fetchFake.fn(u, o);
    const page = makePage(overrides);
    try {
        await fn({ page, fetchFake });
    } finally {
        fetchFake.flush();
        clearTimeout(page.streamBurstTimer);
        clearTimeout(page._coverSwapTimer);
        globalThis.fetch = realFetch;
    }
}

function body(n, { cursor, hasMore = true } = {}) {
    const b = { success: true, has_more: hasMore, data: Array.from({ length: n }, (_, i) => ({ number: `NEW-${i}` })) };
    if (cursor !== undefined) b.cursor = cursor;
    return { ok: true, json: async () => b };
}


function primeKeyword(page, overrides = {}) {
    Object.assign(page, {
        pageState: 'result',
        listMode: 'search',
        currentMode: 'actress',
        currentMaker: null,
        currentQuery: '三上悠亜',
        searchQuery: '三上悠亜',
        searchResults: [{ number: 'SONE-205' }],
        currentOffset: 0,
        hasMoreResults: true,
    }, overrides);
}

const KW_URL = '/api/search?q=%E4%B8%89%E4%B8%8A%E6%82%A0%E4%BA%9C&offset=20&limit=20';

// ─── loadMore：送出 ───────────────────────────────────────────────────
test('cursor-load-more-sends-cursor: 關鍵字結果按載入更多 ⇒ URL 逐字＝既有 URL ＋ &cursor=<token>', async () => {
    // why: 女優清單按「載入更多」，請求沒帶續頁 token，後端認不得是哪份清單 → 第一頁以後的作品永遠載不出來
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: 'tok-1' });
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[0].url, `${KW_URL}&cursor=tok-1`);
        fetchFake.pending.shift().resolve(body(20, { cursor: 'tok-2' }));
        await p;
    });
});


// ─── loadMore：寫回 ───────────────────────────────────────────────────


test('cursor-load-more-writes-back: 連按兩次 ⇒ 第二次送出的是第一次回應的 token', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: 'tok-1' });
        const p1 = page.loadMore();
        await tick();
        fetchFake.pending.shift().resolve(body(20, { cursor: 'tok-2' }));
        await p1;
        const p2 = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[1].url, `${KW_URL.replace('offset=20', 'offset=40')}&cursor=tok-2`);
        assert.ok(!fetchFake.calls[1].url.includes('tok-1'));
        fetchFake.pending.shift().resolve(body(20, { cursor: 'tok-3' }));
        await p2;
        assert.equal(page.currentCursor, 'tok-3');
    });
});


// ─── loadMore：晚到回應（FE-TIMING-08 / FE-GUARD-40） ────────────────

// ─── 第一頁寫入：stream result ───────────────────────────────────────
const send = (es, obj) => es.onmessage({ data: JSON.stringify(obj) });
const lastES = () => FakeES.instances[FakeES.instances.length - 1];

test('cursor-first-page-stream-result: 無 seed 的關鍵字路徑 result ⇒ 欄位＝回應的 cursor', async () => {
    // why: 搜女優名（串流出結果）→ 第一頁出來但 token 沒存下 → 按「載入更多」後端收不到 token 回「沒有更多」→ 每份清單只能看第一頁
    await withEnv(async ({ page }) => {
        page.currentCursor = 'stale';
        await page.doSearch('x');
        const es = lastES();
        send(es, { type: 'result', success: true, data: [{ number: 'A-1' }], has_more: true, cursor: 'tokR', mode: 'actress' });
        assert.equal(page.currentCursor, 'tokR');
        assert.equal(page.hasMoreResults, true);
    });
});


test('cursor-load-more-opens-with-token: result-complete 時按鈕不開，result 到達時 token 與按鈕一起開', async () => {
    // why: 按鈕先開、token 後到 → 兩事件之間點「載入更多」送出沒有 token 的續頁 → 後端回「沒有更多」→ 按鈕消失、剩下的結果看不到
    await withEnv(async ({ page }) => {
        await page.doSearch('x');
        const es = lastES();
        send(es, { type: 'seed', slots: ['A-1', 'A-2'] });
        send(es, { type: 'result-complete', has_more: true, cursor: 'tokC' });
        assert.equal(page.hasMoreResults, false, 'result-complete 後按鈕尚未開放');
        assert.equal(page.currentCursor, null);
        send(es, { type: 'result', success: true, data: [{ number: 'A-1' }, { number: 'A-2' }], has_more: true, cursor: 'tokC', mode: 'actress' });
        assert.equal(page.hasMoreResults, true);
        assert.equal(page.currentCursor, 'tokC');
    });
});


// ─── 重置與還原 ──────────────────────────────────────────────────────


// ─── 持久化 ──────────────────────────────────────────────────────────
function mockSessionStorage(initial = {}) {
    const store = { ...initial };
    globalThis.sessionStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => store[k] ?? null,
        removeItem: (k) => { delete store[k]; },
    };
    return store;
}


test('cursor-restore-roundtrip: 存→還原（真 saveState／restoreState）→ 載入更多送出同一個 token', async () => {
    const KEY = 'test-175d-t7-roundtrip';
    mockSessionStorage();
    const persist = () => merge(searchStatePersistence(), { STATE_KEY: KEY, switchToWishlist() {} });
    await withEnv(async ({ page: before, fetchFake }) => {
        primeKeyword(before, { currentCursor: 'tok-9' });
        before.saveState();

        const after = makePage(persist());
        after.currentCursor = 'stale';
        after.restoreState();
        assert.equal(after.currentCursor, 'tok-9');
        assert.equal(after.hasMoreResults, true, '前提：還原確實發生');

        const p = after.loadMore();
        await tick();
        assert.equal(fetchFake.calls.length, 1);
        assert.equal(fetchFake.calls[0].url, `${KW_URL}&cursor=tok-9`);
        fetchFake.pending.shift().resolve(body(1, { hasMore: false }));
        await p;
    }, persist());
});

// ─── 高階搜尋／rescrape 提交 ─────────────────────────────────────────
