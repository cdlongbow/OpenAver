// TASK-173-T10：loadMore 守衛、頁大小、URL 出口、世代守衛（兩種模式共用）
//
// 守住的行為（CD-173-9 oracle 8–9、CD-173-11 B 類 oracle 6–8）：
//   - 片商結果按「載入更多」：搜尋框是空的也不被入口守衛擋掉，offset 以 30 為一頁
//   - 關鍵字結果按「載入更多」：URL 逐字等於今日（offset=20&limit=20）
//   - 惰性：currentMaker 殘留但 currentMode 不是 maker ⇒ 走關鍵字 URL
//   - 存→還原（真 saveState／restoreState）→ 載入更多 送出同一家片商的 URL
//   - 取消／取消並重開後，晚到的 loadMore 成功／失敗回應不改六項；晚到的拒絕亦不改
//
// 假 fetch 刻意忽略 signal（不因 abort 自行 reject），否則世代守衛會變死碼、測試照綠。
// 回應一律由測試手動放行，flush() 在 finally 放行（FE-GUARD-39）。

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

function makePage(overrides = {}) {
    return merge(searchStateBase(), searchStateSearchFlow(), searchStateNavigation(), {
        $nextTick() {},
        checkLocalStatus() {},
        preloadImages() {},
        _resetCoverState() {},
    }, overrides);
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

const OK_BODY = (n, hasMore = true) => ({
    ok: true,
    json: async () => ({ success: true, has_more: hasMore, data: Array.from({ length: n }, (_, i) => ({ number: `NEW-${i}` })) }),
});
const FAIL_BODY = { ok: true, json: async () => ({ success: false, data: [] }) };

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
        currentMode: 'exact',
        currentMaker: null,
        currentQuery: 'SONE-205',
        searchQuery: 'SONE-205',
        searchResults: [{ number: 'SONE-205' }],
        currentOffset: 0,
        hasMoreResults: true,
    }, overrides);
}

function six(page) {
    return JSON.parse(JSON.stringify({
        searchResults: page.searchResults,
        maker: page.currentMaker ? page.currentMaker.key : null,
        hasMoreResults: page.hasMoreResults,
        currentOffset: page.currentOffset,
        errorText: page.errorText,
        pageState: page.pageState,
    }));
}

// ─── URL／頁大小 ─────────────────────────────────────────────────────
test('maker-second-page-offset: 片商結果（搜尋框空）按載入更多 ⇒ 送出 offset=30 的片商 URL', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeMaker(page);
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls.length, 1, '搜尋框是空的也不得被入口守衛擋掉');
        assert.equal(
            fetchFake.calls[0].url,
            '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=30',
        );
        fetchFake.pending.shift().resolve(OK_BODY(30));
        const r = await p;
        assert.equal(r.loadedCount, 30);
        assert.equal(page.currentOffset, 30);
        assert.equal(page.searchResults.length, 32);
    });
});

test('maker-second-page-offset: 第三批 offset=60（currentOffset 以 30 累加）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeMaker(page, { currentOffset: 30 });
        const p = page.loadMore();
        await tick();
        assert.ok(fetchFake.calls[0].url.endsWith('&offset=60'));
        fetchFake.pending.shift().resolve(OK_BODY(1, false));
        await p;
        assert.equal(page.currentOffset, 60);
        assert.equal(page.hasMoreResults, false);
    });
});

test('keyword-url-unchanged: 關鍵字結果按載入更多 ⇒ /api/search?q=SONE-205&offset=20&limit=20 逐字', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page);
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[0].url, '/api/search?q=SONE-205&offset=20&limit=20');
        fetchFake.pending.shift().resolve(OK_BODY(20));
        await p;
        assert.equal(page.currentOffset, 20);
    });
});

test('inert-maker-keyword-url: currentMaker 殘留但 currentMode=exact ⇒ 送關鍵字 URL、offset 以 20 計', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentMaker: { ...MAKER_A } });
        const p = page.loadMore();
        await tick();
        assert.equal(fetchFake.calls[0].url, '/api/search?q=SONE-205&offset=20&limit=20');
        fetchFake.pending.shift().resolve(OK_BODY(20));
        await p;
        assert.equal(page.currentOffset, 20);
    });
});

test('loadMore guards: 非片商且無關鍵字 ⇒ 不發請求、回 null；listMode 非 search ⇒ null', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeKeyword(page, { currentQuery: '', currentMode: 'exact' });
        assert.equal(await page.loadMore(), null);
        primeMaker(page, { listMode: 'file' });
        assert.equal(await page.loadMore(), null);
        primeMaker(page, { hasMoreResults: false });
        assert.equal(await page.loadMore(), null);
        assert.equal(fetchFake.calls.length, 0);
    });
});

test('restore-then-load-more-same-maker: 存→還原（真 saveState／restoreState）→ 載入更多送出同一家片商 URL', async () => {
    const KEY = 'test-173-t10-restore';
    const store = {};
    globalThis.sessionStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => store[k] ?? null,
        removeItem: (k) => { delete store[k]; },
    };
    const persist = () => merge(searchStatePersistence(), { STATE_KEY: KEY, switchToWishlist() {} });
    await withEnv(async ({ page: before, fetchFake }) => {
        primeMaker(before);
        before.saveState();
        assert.ok(store[KEY], '真 saveState 有寫出');

        const after = makePage(persist());
        after.restoreState();
        assert.equal(after.activeMaker()?.key, 'moodyz', '還原後仍是同一家片商（先斷言，避免 restoreState 吞例外被誤判）');
        assert.equal(after.currentQuery, '');
        assert.equal(after.currentOffset, 0);
        assert.equal(after.hasMoreResults, true);

        const p = after.loadMore();
        await tick();
        assert.equal(fetchFake.calls.length, 1);
        assert.equal(
            fetchFake.calls[0].url,
            '/api/search?maker_key=moodyz&maker=MOODYZ&spellings=MOODYZ&spellings=Moodyz&offset=30',
        );
        fetchFake.pending.shift().resolve(OK_BODY(1, false));
        await p;
    }, persist());
});

// ─── 世代守衛（雙模式、雙變體） ─────────────────────────────────────
const MODES = [
    ['maker', primeMaker],
    ['keyword', primeKeyword],
];
const VARIANTS = ['cancelled-only', 'reopen'];

// 取消（或取消並重開）後取樣六項；變體 reopen 把 B 手動寫成「有結果、hasMore=true」
function cancelAndMaybeReopen(page, variant) {
    page.cancelSearch();
    if (variant === 'reopen') {
        page.doSearch('', { maker: MAKER_B });
        Object.assign(page, {
            pageState: 'result',
            searchResults: [{ number: 'S1-001' }],
            currentOffset: 0,
            hasMoreResults: true,
        });
    }
    return six(page);
}

for (const [modeName, prime] of MODES) {
    for (const variant of VARIANTS) {
        test(`late-success-dropped ${modeName} ${variant}: 取消後 A 的載入更多成功回應晚到，六項不變、回 null`, async () => {
            await withEnv(async ({ page, fetchFake }) => {
                prime(page);
                const p = page.loadMore();
                await tick();
                assert.equal(fetchFake.pending.length, 1);
                const before = cancelAndMaybeReopen(page, variant);
                let r;
                try {
                    fetchFake.pending.shift().resolve(OK_BODY(5));
                    r = await p;
                    assert.equal(r, null);
                    assert.deepEqual(six(page), before);
                } finally {
                    fetchFake.flush();
                }
            });
        });

        test(`late-failure-dropped ${modeName} ${variant}: 取消後 A 的失敗回應晚到，hasMoreResults 等六項不變、回 null`, async () => {
            await withEnv(async ({ page, fetchFake }) => {
                prime(page);
                const p = page.loadMore();
                await tick();
                const before = cancelAndMaybeReopen(page, variant);
                try {
                    fetchFake.pending.shift().resolve(FAIL_BODY);
                    const r = await p;
                    assert.equal(r, null);
                    assert.equal(page.hasMoreResults, variant === 'reopen' ? true : before.hasMoreResults);
                    assert.deepEqual(six(page), before);
                } finally {
                    fetchFake.flush();
                }
            });
        });

        test(`late-reject-ignored ${modeName} ${variant}: 取消後 A 的 fetch 拒絕晚到，六項不變、回 null`, async () => {
            await withEnv(async ({ page, fetchFake }) => {
                prime(page);
                const p = page.loadMore();
                await tick();
                const before = cancelAndMaybeReopen(page, variant);
                const origErr = console.error;
                console.error = () => {};
                try {
                    fetchFake.pending.shift().reject(new TypeError('network down'));
                    const r = await p;
                    assert.equal(r, null);
                    assert.deepEqual(six(page), before);
                } finally {
                    console.error = origErr;
                    fetchFake.flush();
                }
            });
        });
    }
}

test('late-success-dropped 對照：未取消時同一批回應確實接上結果', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        primeMaker(page);
        const p = page.loadMore();
        await tick();
        const before = six(page);
        fetchFake.pending.shift().resolve(OK_BODY(5));
        const r = await p;
        assert.equal(r.loadedCount, 5);
        assert.notDeepEqual(six(page), before);
    });
});
