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
const { searchStateAdvancedPicker } = await import('../state/advanced-picker.js');

const MAKER_A = { key: 'moodyz', label: 'MOODYZ', spellings: ['MOODYZ', 'Moodyz'] };
const MAKER_B = { key: 's1', label: 'S1', spellings: ['S1'] };

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
const FAIL_BODY = { ok: true, json: async () => ({ success: false, data: [], cursor: 'from-failure' }) };

function primeMaker(page, overrides = {}) {
    Object.assign(page, {
        pageState: 'result',
        listMode: 'search',
        currentMode: 'maker',
        currentMaker: { ...MAKER_A },
        currentQuery: '',
        searchQuery: '',
        searchResults: [{ number: 'MIDV-001' }, { number: 'MIDV-002' }],
        currentOffset: 0,
        hasMoreResults: true,
    }, overrides);
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
const MAKER_URL = '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=30';

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

test('cursor-load-more-sends-cursor: 片商結果按載入更多 ⇒ URL 逐字＝既有 URL ＋ &cursor=<token>', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeMaker(page, { currentCursor: 'tok-1' });
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[0].url, `${MAKER_URL}&cursor=tok-1`);
        fetchFake.pending.shift().resolve(body(30, { cursor: 'tok-2' }));
        await p;
    });
});

test('cursor-load-more-sends-cursor: token 含 = & 空白 非 ASCII ⇒ 經 searchParams 往返相等', async () => {
    const raw = 'a=b&c d日本/+%';
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: raw });
        const p = page.loadMore();
        await tick();
        const sp = new URL(fetchFake.calls[0].url, 'http://x').searchParams;
        assert.equal(sp.get('cursor'), raw);
        assert.equal(sp.get('offset'), '20');
        fetchFake.pending.shift().resolve(body(1, { hasMore: false }));
        await p;
    });
});

test('cursor-null-url-unchanged: currentCursor 為 null ⇒ 載入更多 URL 與今日逐字相同、不含 cursor', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page);
        assert.equal(page.currentCursor, null, '預設值是 null');
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[0].url, KW_URL);
        fetchFake.pending.shift().resolve(body(20));
        await p;
        primeMaker(page);
        const p2 = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[1].url, MAKER_URL);
        fetchFake.pending.shift().resolve(body(1, { hasMore: false }));
        await p2;
    });
});

// ─── loadMore：寫回 ───────────────────────────────────────────────────
test('cursor-load-more-writes-back: 成功後欄位換成回應的 token（與送出的不同）', async () => {
    // why: 連按兩次「載入更多」→ 第二次仍送第一頁的 token → 第三頁是第二頁的重複封面，翻不到更後面的作品
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: 'tok-1' });
        const p = page.loadMore();
        await tick();
        fetchFake.pending.shift().resolve(body(20, { cursor: 'tok-2' }));
        await p;
        assert.equal(page.currentCursor, 'tok-2');
    });
});

test('cursor-load-more-writes-back: 回應成功但沒有 cursor ⇒ null（不保留舊 token）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeMaker(page, { currentCursor: 'tok-1' });
        const p = page.loadMore();
        await tick();
        fetchFake.pending.shift().resolve(body(30));
        await p;
        assert.equal(page.currentCursor, null);
    });
});

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

test('cursor-load-more-failure-keeps: 失敗回應（success:false）與 fetch 拒絕不改欄位', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: 'tok-1' });
        const p = page.loadMore();
        await tick();
        fetchFake.pending.shift().resolve(FAIL_BODY);
        assert.equal(await p, null);
        assert.equal(page.currentCursor, 'tok-1');

        primeKeyword(page, { currentCursor: 'tok-1' });
        const p2 = page.loadMore();
        await tick();
        const origErr = console.error;
        console.error = () => {};
        try {
            fetchFake.pending.shift().reject(new TypeError('network down'));
            assert.equal(await p2, null);
        } finally {
            console.error = origErr;
        }
        assert.equal(page.currentCursor, 'tok-1');
    });
});

// ─── loadMore：晚到回應（FE-TIMING-08 / FE-GUARD-40） ────────────────
test('cursor-late-load-more-no-overwrite: 取消並重開後，舊搜尋的載入更多成功回應晚到不得覆寫新搜尋的 token', async () => {
    // why: 載入更多還在飛時使用者開了新搜尋 → 舊回應晚到蓋掉新清單的 token → 新清單按載入更多會接上舊清單的位置
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentCursor: 'old-tok' });
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.pending.length, 1);
        page.cancelSearch();
        page.doSearch('', { maker: MAKER_B });
        page.currentCursor = 'new-search-token';
        try {
            fetchFake.pending.shift().resolve(body(5, { cursor: 'late-resp' }));
            const r = await p;
            assert.equal(r, null);
            assert.equal(page.currentCursor, 'new-search-token');
        } finally {
            fetchFake.flush();
        }
    });
});

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

test('cursor-first-page-stream-result: seed→result-complete→result ⇒ 以 result 的 cursor 為準（result-complete 不寫）', async () => {
    await withEnv(async ({ page }) => {
        page.currentCursor = 'stale';
        await page.doSearch('x');
        assert.equal(page.currentCursor, null, 'doSearch 起手已重置（斷言放在任何事件之前）');
        const es = lastES();
        send(es, { type: 'seed', slots: ['A-1', 'A-2'] });
        send(es, { type: 'result-complete', has_more: true, cursor: 'tokC' });
        assert.equal(page.currentCursor, null, 'result-complete 不寫 currentCursor（主 session 裁：只在 result 開頭寫）');
        send(es, { type: 'result', success: true, data: [{ number: 'A-1' }], has_more: true, cursor: 'tokR', mode: 'actress' });
        assert.equal(page.currentCursor, 'tokR');
    });
});

test('cursor-first-page-stream-result: result 沒有 cursor ⇒ null（兩條路徑）', async () => {
    await withEnv(async ({ page }) => {
        await page.doSearch('x');
        page.currentCursor = 'mid';
        send(lastES(), { type: 'result', success: true, data: [{ number: 'A-1' }], has_more: false, mode: 'exact' });
        assert.equal(page.currentCursor, null);
    });
    await withEnv(async ({ page }) => {
        await page.doSearch('x');
        const es = lastES();
        send(es, { type: 'seed', slots: ['A-1'] });
        send(es, { type: 'result-complete', has_more: false });
        page.currentCursor = 'mid';
        send(es, { type: 'result', success: true, data: [{ number: 'A-1' }], has_more: false, mode: 'exact' });
        assert.equal(page.currentCursor, null);
    });
});

test('cursor-first-page-fallback: fallbackSearch 成功 ⇒ 欄位＝回應的 cursor；沒有 cursor ⇒ null', async () => {
    await withEnv(async ({ page }) => {
        const resp = (extra) => ({
            ok: true,
            json: async () => ({ success: true, data: [{ number: 'A-1' }], has_more: true, mode: 'exact', ...extra }),
        });
        globalThis.fetch = async () => resp({ cursor: 'tokF' });
        page.currentCursor = 'stale';
        await page.fallbackSearch('x', page.requestId);
        assert.equal(page.currentCursor, 'tokF');

        globalThis.fetch = async () => resp({});
        page.currentCursor = 'stale';
        await page.fallbackSearch('x', page.requestId);
        assert.equal(page.currentCursor, null);
    });
});

// ─── 重置與還原 ──────────────────────────────────────────────────────
test('cursor-do-search-start-resets: doSearch 起手 ⇒ null（片商入口同）', async () => {
    await withEnv(async ({ page }) => {
        page.currentCursor = 'stale';
        await page.doSearch('x');
        assert.equal(page.currentCursor, null);
        page.currentCursor = 'stale';
        await page.doSearch('', { maker: MAKER_A });
        assert.equal(page.currentCursor, null);
    });
});

test('cursor-cancel-restores: cancelSearch 還原 snapshot 的值；snapshot 缺欄位 ⇒ null', async () => {
    await withEnv(async ({ page }) => {
        primeKeyword(page, { currentCursor: 'old-tok' });
        await page.doSearch('x');
        assert.equal(page.currentCursor, null, '新搜尋已重置（前提）');
        page.cancelSearch();
        assert.equal(page.currentCursor, 'old-tok', '取消後回到上一份清單的 token');
    });
    await withEnv(async ({ page }) => {
        primeKeyword(page);
        page._searchSnapshot = {
            searchResults: [], currentIndex: 0, fileList: [], currentFileIndex: 0, listMode: 'search',
            hasMoreResults: true, currentQuery: 'q', currentOffset: 0, pageState: 'result',
            actressProfile: null, displayMode: 'detail', currentMode: 'exact', currentMaker: null,
        };
        page.currentCursor = 'stale';
        page.cancelSearch();
        assert.equal(page.currentCursor, null, '舊 snapshot 缺欄位 ⇒ null');
    });
});

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

// fake this：刻意不含 currentCursor（驗 ?? null 的容錯）
function persistThis(STATE_KEY, overrides = {}) {
    return merge(
        searchStatePersistence(),
        { activeMaker: searchStateSearchFlow().activeMaker },
        {
            STATE_KEY,
            searchResults: [{ number: 'MIDV-001' }],
            currentIndex: 0,
            currentQuery: 'q',
            currentOffset: 0,
            hasMoreResults: true,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'search',
            searchQuery: 'q',
            displayMode: 'detail',
            _preWishlistDisplayMode: null,
            _preWishlistListMode: null,
            currentMode: 'exact',
            currentMaker: null,
            actressProfile: null,
            pageState: 'result',
            _searchSnapshot: null,
            lightboxOpen: false,
            lightboxIndex: 0,
            _heroCardImageError: false,
            _heroLightboxImageError: false,
            _resetCoverState: () => {},
            switchToWishlist: () => {},
        },
        overrides,
    );
}

test('cursor-save-snapshot-branch: 搜尋中（loading）存的是上一輪 snapshot 的 token，不是 live 的', () => {
    // why: 新搜尋還在載入時重新整理 → 還原回上一份清單但續頁 token 被丟掉 → 按「載入更多」變「沒有更多」
    const KEY = 'test-175d-t7-snapshot';
    const store = mockSessionStorage();
    const page = persistThis(KEY, {
        pageState: 'loading',
        currentCursor: 'new-tok',
        _searchSnapshot: {
            searchResults: [{ number: 'MIDV-001' }],
            currentIndex: 0,
            currentQuery: 'q',
            currentOffset: 0,
            hasMoreResults: true,
            fileList: [],
            currentFileIndex: 0,
            listMode: 'search',
            displayMode: 'grid',
            currentMode: 'exact',
            currentMaker: null,
            actressProfile: null,
            currentCursor: 'old-tok',
        },
    });
    searchStatePersistence().saveState.call(page);
    assert.equal(JSON.parse(store[KEY]).currentCursor, 'old-tok');

    // snapshot 缺欄位（舊 snapshot）⇒ null，不退回 live 值
    page._searchSnapshot = { ...page._searchSnapshot };
    delete page._searchSnapshot.currentCursor;
    searchStatePersistence().saveState.call(page);
    assert.equal(JSON.parse(store[KEY]).currentCursor, null);
});

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
test('cursor-commit-resets: _commitSearchResults（payload 沒有 cursor）⇒ null', () => {
    // why: 翻開女優清單後改用進階搜尋重搜 → 新結果不得殘留舊清單的 token（目前進階搜尋 has_more 恆假，此為防殘留）
    const page = merge(searchStateBase(), searchStateAdvancedPicker(), STUBS, { currentCursor: 'stale' });
    page._commitSearchResults({ data: [{ number: 'A-1' }], mode: 'exact', has_more: false });
    assert.equal(page.currentCursor, null);
    assert.equal(page.searchResults.length, 1, '前提：提交確實發生');
});
