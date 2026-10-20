// TASK-173-T9：片商入口 doSearch(query,{maker})＋fallbackSearch URL＋_applyMakerError
//
// 守住的行為（CD-173-9 oracle 6–7、CD-173-11 A 類 oracle 1–5、CD-173-13）：
//   - 片商入口同步設 currentMode='maker'／currentMaker 複本／currentQuery=''／searchQuery=''
//   - 入口沿用同一份起手式：舊 streamBurstTimer／_coverSwapTimer 被清且 callback 不再觸發
//   - SSE 與 REST fallback 的 URL 都帶片商（經 buildSearchUrl／activeMaker()）
//   - 取消（僅取消／取消並重開）後，A 的 SSE message／onerror／REST 回應／REST 拒絕晚到
//     不改 searchResults、currentMaker、hasMoreResults、currentOffset、errorText、pageState
//   - 連點同一顆膠囊：第一條連線被關、_activeConnections 只剩第二條
//   - _applyMakerError：maker_not_found ⇒ 片商錯誤頁＋隱藏膠囊；其他 code／無 code ⇒ no_data、不隱藏
//
// 假 fetch 刻意忽略 signal（不因 abort 自行 reject），否則 requestId 守衛會變死碼。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {}, querySelector() { return null; } };
window.t = (k, p) => (p ? k + JSON.stringify(p) : k);

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);

const { searchStateBase } = await import('../state/base.js');
const { searchStateSearchFlow } = await import('../state/search-flow.js');
const { buildSearchUrl } = await import('../search-url.js');
const { searchPage } = await import('../main.js');

const MAKER_A = { key: 'moodyz', label: 'MOODYZ', spellings: ['MOODYZ', 'Moodyz'] };
const MAKER_B = { key: 's1', label: 'S1', spellings: ['S1'] };

// ─── 假 EventSource／假 fetch ──────────────────────────────────────────
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
    emit(obj) { this.onmessage({ data: JSON.stringify(obj) }); }
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
        // 放行全部 pending（在 finally 呼叫，FE-GUARD-39）
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
    return merge(searchStateBase(), searchStateSearchFlow(), {
        $nextTick() {},
        checkLocalStatus() {},
        preloadImages() {},
    }, overrides);
}

// 每支測試的環境：重置 ES 列表、安裝假 fetch；finally 放行
async function withEnv(fn) {
    FakeES.instances.length = 0;
    const fetchFake = makeFetch();
    const realFetch = globalThis.fetch;
    globalThis.fetch = (u, o) => fetchFake.fn(u, o);
    const page = makePage();
    try {
        await fn({ page, fetchFake });
    } finally {
        fetchFake.flush();
        clearTimeout(page.streamBurstTimer);
        clearTimeout(page._coverSwapTimer);
        globalThis.fetch = realFetch;
    }
}

const lastES = () => FakeES.instances[FakeES.instances.length - 1];

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

const LATE_STREAM = [
    { type: 'seed', slots: ['AAA-001', 'AAA-002'] },
    { type: 'result-item', slot: 0, data: { number: 'AAA-001' } },
    { type: 'result-complete', has_more: true },
    { type: 'result', success: true, data: [{ number: 'AAA-001' }], has_more: true },
];

function primeKeywordResult(page) {
    page.pageState = 'result';
    page.searchResults = [{ number: 'OLD-1' }];
    page.currentMode = 'exact';
    page.currentQuery = 'OLD-1';
    page.listMode = 'search';
}

// ─── 入口（oracle 6） ────────────────────────────────────────────────
test('entry-mode-maker: doSearch(\'\', {maker}) 同步設 currentMode／currentMaker 複本／currentQuery', async () => {
    await withEnv(async ({ page }) => {
        page.currentMode = 'exact';
        page.currentQuery = 'xyz';
        const maker = { ...MAKER_A, spellings: [...MAKER_A.spellings] };
        page.doSearch('', { maker });
        assert.equal(page.currentMode, 'maker');
        assert.equal(page.currentQuery, '');
        assert.equal(page.activeMaker().key, 'moodyz');
        assert.deepEqual(page.currentMaker, MAKER_A);
        assert.notEqual(page.currentMaker, maker, '純物件複本，不是同一個參照');
        assert.notEqual(page.currentMaker.spellings, maker.spellings);
        assert.equal(page.pageState, 'loading');
    });
});

test('entry-clears-search-box: 搜尋框有字再點膠囊 ⇒ searchQuery 清空，不被當關鍵字', async () => {
    await withEnv(async ({ page }) => {
        page.searchQuery = 'abc';
        page.currentMode = 'exact';
        page.currentQuery = 'xyz';
        page.doSearch('', { maker: MAKER_A });
        assert.equal(page.searchQuery, '');
        assert.equal(page.currentQuery, '');
        assert.equal(FakeES.instances.length, 1);
    });
});

test('entry-sse-url-maker: EventSource URL＝buildSearchUrl({stream:true,maker})', async () => {
    await withEnv(async ({ page }) => {
        page.searchQuery = 'abc';
        page.doSearch('', { maker: MAKER_A });
        assert.equal(lastES().url, buildSearchUrl({ stream: true, maker: MAKER_A }));
        assert.ok(lastES().url.startsWith('/api/search/stream?maker_key=moodyz'));
    });
});

test('entry: 關鍵字入口 URL 逐字不變，順手清 currentMaker', async () => {
    await withEnv(async ({ page }) => {
        page.currentMode = 'maker';
        page.currentMaker = { ...MAKER_A };
        page.doSearch('SONE-205');
        assert.equal(lastES().url, '/api/search/stream?q=SONE-205');
        assert.equal(page.currentMaker, null);
        assert.equal(page.activeMaker(), null);
    });
});

test('entry: 舊 streamBurstTimer／_coverSwapTimer 被清、callback 不再觸發（沿用同一份起手式）', async () => {
    await withEnv(async ({ page }) => {
        let fired = 0;
        page.streamBurstTimer = setTimeout(() => { fired++; }, 20);
        page._coverSwapTimer = setTimeout(() => { fired++; }, 20);
        page.doSearch('', { maker: MAKER_A });
        assert.equal(page.streamBurstTimer, null);
        assert.equal(page._coverSwapTimer, null);
        await new Promise((r) => setTimeout(r, 60));
        assert.equal(fired, 0);
    });
});

test('entry-snapshot-cancel: 搜尋前是關鍵字結果 ⇒ 入口載入中取消 ⇒ activeMaker()===null', async () => {
    await withEnv(async ({ page }) => {
        primeKeywordResult(page);
        page.doSearch('', { maker: MAKER_A });
        assert.equal(page.activeMaker().key, 'moodyz');
        page.cancelSearch();
        assert.equal(page.activeMaker(), null);
        assert.equal(page.currentMode, 'exact');
        assert.equal(page.currentQuery, 'OLD-1');
        assert.deepEqual(page.searchResults, [{ number: 'OLD-1' }]);
    });
});

test('entry-snapshot-cancel: 搜尋前是片商 A 結果、現搜 B ⇒ 取消還原成 A', async () => {
    await withEnv(async ({ page }) => {
        page.pageState = 'result';
        page.searchResults = [{ number: 'AAA-001' }];
        page.currentMode = 'maker';
        page.currentMaker = { ...MAKER_A };
        page.currentQuery = '';
        page.doSearch('', { maker: MAKER_B });
        assert.equal(page.activeMaker().key, 's1');
        page.cancelSearch();
        assert.equal(page.activeMaker().key, 'moodyz');
        assert.equal(page.currentMode, 'maker');
        assert.deepEqual(page.searchResults, [{ number: 'AAA-001' }]);
    });
});

test('A5 連點同一顆膠囊：第一條連線 close()、_activeConnections 只剩第二條', async () => {
    await withEnv(async ({ page }) => {
        page.doSearch('', { maker: MAKER_A });
        const first = lastES();
        page.doSearch('', { maker: MAKER_A });
        const second = lastES();
        assert.notEqual(first, second);
        assert.equal(first.closed, true);
        assert.equal(second.closed, false);
        assert.deepEqual(page._activeConnections, [second]);
    });
});

// ─── A1：SSE message 晚到 ───────────────────────────────────────────
async function a1Setup(page) {
    primeKeywordResult(page);
    page.doSearch('', { maker: MAKER_A });
    return lastES();
}

test('a1-sse-message-late 對照：未取消時同一串事件確實改了 state', async () => {
    await withEnv(async ({ page }) => {
        const es = await a1Setup(page);
        const before = six(page);
        for (const ev of LATE_STREAM) es.emit(ev);
        assert.notDeepEqual(six(page), before);
        assert.equal(page.pageState, 'result');
        assert.equal(page.hasMoreResults, true);
    });
});

test('a1-sse-message-late cancelled-only: 僅取消後 A 的 SSE message 晚到，六項不變', async () => {
    await withEnv(async ({ page }) => {
        const es = await a1Setup(page);
        page.cancelSearch();
        const before = six(page);
        for (const ev of LATE_STREAM) es.emit(ev);
        assert.deepEqual(six(page), before);
    });
});

test('a1-sse-message-late reopen: 取消並重開 B 後 A 的 SSE message 晚到，六項不變', async () => {
    await withEnv(async ({ page }) => {
        const es = await a1Setup(page);
        page.cancelSearch();
        page.doSearch('', { maker: MAKER_B });
        const before = six(page);
        assert.equal(before.maker, 's1');
        assert.equal(before.pageState, 'loading');
        for (const ev of LATE_STREAM) es.emit(ev);
        assert.deepEqual(six(page), before);
    });
});

test('clear-all-late: 點膠囊後 clearAll() ⇒ A 的 SSE message 晚到，六項不變', async () => {
    await withEnv(async ({ page }) => {
        const es = await a1Setup(page);
        page.clearAll();
        const before = six(page);
        assert.equal(before.pageState, 'empty');
        for (const ev of LATE_STREAM) es.emit(ev);
        assert.deepEqual(six(page), before);
    });
});

// ─── A2：onerror 晚到 ───────────────────────────────────────────────
test('a2-sse-onerror-late 對照：未取消時 onerror 會改走 REST fallback', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const es = await a1Setup(page);
        es.onerror();
        assert.equal(fetchFake.calls.length, 1);
        assert.equal(es.closed, true);
    });
});

test('a2-sse-onerror-late cancelled-only: 僅取消後舊連線 onerror 晚到，不觸發 fetch', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const es = await a1Setup(page);
        page.cancelSearch();
        const before = six(page);
        es.onerror();
        assert.equal(fetchFake.calls.length, 0);
        assert.deepEqual(six(page), before);
    });
});

test('a2-sse-onerror-late reopen: 取消並重開 B 後 A 的 onerror 晚到，不觸發 fetch、不關掉 B', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const esA = await a1Setup(page);
        page.cancelSearch();
        page.doSearch('', { maker: MAKER_B });
        const esB = lastES();
        const before = six(page);
        esA.onerror();
        assert.equal(fetchFake.calls.length, 0);
        assert.equal(esB.closed, false);
        assert.deepEqual(page._activeConnections, [esB]);
        assert.deepEqual(six(page), before);
    });
});

// ─── A3／A4：REST fallback 回應／拒絕晚到 ────────────────────────────
const REST_OK = { ok: true, json: async () => ({ success: true, mode: 'maker', has_more: true, data: [{ number: 'AAA-001' }] }) };

async function restSetup(page, fetchFake) {
    const es = await a1Setup(page);
    es.onerror();
    assert.equal(fetchFake.calls.length, 1);
    return fetchFake.pending[0];
}

test('fallback-url-maker: fallback 的 REST URL 帶片商（經 activeMaker()）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        await restSetup(page, fetchFake);
        assert.equal(fetchFake.calls[0].url, buildSearchUrl({ maker: MAKER_A }));
        assert.ok(fetchFake.calls[0].url.startsWith('/api/search?maker_key=moodyz'));
    });
});

test('fallback: 關鍵字 fallback URL 逐字不變', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        page.doSearch('SONE-205');
        lastES().onerror();
        assert.equal(fetchFake.calls[0].url, '/api/search?q=SONE-205');
    });
});

test('a3-rest-response-late 對照：未取消時 REST 回應確實改了 state', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        const before = six(page);
        p.resolve(REST_OK);
        await tick();
        assert.notDeepEqual(six(page), before);
        assert.equal(page.pageState, 'result');
    });
});

test('a3-rest-response-late cancelled-only: 僅取消後 REST 回應晚到，六項不變', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        page.cancelSearch();
        const before = six(page);
        p.resolve(REST_OK);
        await tick();
        assert.deepEqual(six(page), before);
    });
});

test('a3-rest-response-late reopen: 取消並重開 B 後 REST 回應晚到，六項不變', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        page.cancelSearch();
        page.doSearch('', { maker: MAKER_B });
        const before = six(page);
        p.resolve(REST_OK);
        await tick();
        assert.deepEqual(six(page), before);
    });
});

test('a4-rest-reject-late 對照：未取消時 REST 網路失敗確實改了 state', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        p.reject(new Error('net down'));
        await tick();
        assert.equal(page.pageState, 'error');
        assert.equal(page.errorKind, 'network_error');
    });
});

test('a4-rest-reject-late cancelled-only: 僅取消後 REST 拒絕晚到，六項不變', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        page.cancelSearch();
        const before = six(page);
        p.reject(new Error('net down'));
        await tick();
        assert.deepEqual(six(page), before);
    });
});

test('a4-rest-reject-late reopen: 取消並重開 B 後 REST 拒絕晚到，六項不變', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const p = await restSetup(page, fetchFake);
        page.cancelSearch();
        page.doSearch('', { maker: MAKER_B });
        const before = six(page);
        p.reject(new Error('net down'));
        await tick();
        assert.deepEqual(six(page), before);
    });
});

// ─── _applyMakerError（CD-173-13） ──────────────────────────────────
function sseFail(page, code) {
    page.doSearch('', { maker: MAKER_A });
    const ev = { type: 'result', success: false, data: [] };
    if (code) ev.error_code = code;
    lastES().emit(ev);
}

async function restFail(page, fetchFake, code) {
    page.doSearch('', { maker: MAKER_A });
    lastES().onerror();
    const body = { success: false, error: '後端原文', mode: 'maker' };
    if (code) body.error_code = code;
    fetchFake.pending[0].resolve({ ok: false, json: async () => body });
    await tick();
}

test('error-not-found-hides error-sse-routes-maker: SSE 失敗 maker_not_found ⇒ 片商錯誤頁＋隱藏膠囊', async () => {
    await withEnv(async ({ page }) => {
        const hidden = [];
        page.hideMakerCapsule = (k) => hidden.push(k);
        sseFail(page, 'maker_not_found');
        assert.equal(page.errorText, 'search.error.maker_not_found{"maker":"MOODYZ"}');
        assert.equal(page.errorKind, 'maker_not_found');
        assert.equal(page.pageState, 'error');
        assert.deepEqual(hidden, ['moodyz']);
    });
});

test('error-not-found-hides error-fallback-routes-maker: REST 失敗 maker_not_found ⇒ 片商錯誤頁＋隱藏膠囊（不顯示後端原文）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        const hidden = [];
        page.hideMakerCapsule = (k) => hidden.push(k);
        await restFail(page, fetchFake, 'maker_not_found');
        assert.equal(page.errorText, 'search.error.maker_not_found{"maker":"MOODYZ"}');
        assert.equal(page.errorKind, 'maker_not_found');
        assert.equal(page.pageState, 'error');
        assert.deepEqual(hidden, ['moodyz']);
    });
});

for (const code of ['maker_unreachable', 'maker_no_sample', 'maker_empty', null]) {
    test(`error-other-codes-keep SSE（${code}）: no_data、不隱藏膠囊`, async () => {
        await withEnv(async ({ page }) => {
            const hidden = [];
            page.hideMakerCapsule = (k) => hidden.push(k);
            sseFail(page, code);
            assert.equal(page.errorText, 'search.error.no_data');
            assert.equal(page.errorKind, 'no_data');
            assert.equal(page.pageState, 'error');
            assert.deepEqual(hidden, []);
        });
    });
    test(`error-other-codes-keep REST（${code}）: no_data、不隱藏膠囊`, async () => {
        await withEnv(async ({ page, fetchFake }) => {
            const hidden = [];
            page.hideMakerCapsule = (k) => hidden.push(k);
            await restFail(page, fetchFake, code);
            assert.equal(page.errorText, 'search.error.no_data');
            assert.equal(page.errorKind, 'no_data');
            assert.equal(page.pageState, 'error');
            assert.deepEqual(hidden, []);
        });
    });
}

test('error-not-found-hides: hideMakerCapsule 未定義時不拋錯（SSE／REST 都照樣進錯誤頁）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        assert.equal(page.hideMakerCapsule, undefined);
        sseFail(page, 'maker_not_found');
        assert.equal(page.errorKind, 'maker_not_found');
        assert.equal(page.pageState, 'error');
        await restFail(page, fetchFake, 'maker_not_found');
        assert.equal(page.errorKind, 'maker_not_found');
        assert.equal(page.pageState, 'error');
    });
});

test('error: 關鍵字搜尋失敗分支行為不變（no_data／REST 用後端 error 原文）', async () => {
    await withEnv(async ({ page, fetchFake }) => {
        page.doSearch('NOPE-1');
        lastES().emit({ type: 'result', success: false, data: [], error_code: 'maker_not_found' });
        assert.equal(page.errorText, 'search.error.no_data');
        assert.equal(page.errorKind, 'no_data');
        page.doSearch('NOPE-2');
        lastES().onerror();
        fetchFake.pending[0].resolve({ ok: false, json: async () => ({ success: false, error: '後端原文' }) });
        await tick();
        assert.equal(page.errorText, '後端原文');
        assert.equal(page.errorKind, 'no_data');
    });
});

// ─── 真 searchPage() 接線 ───────────────────────────────────────────
test('searchPage(): doSearch opts／activeMaker／progressQueryText／_applyMakerError 接線', async () => {
    FakeES.instances.length = 0;
    const page = searchPage();
    page.$nextTick = () => {};
    page.checkLocalStatus = () => {};
    page.preloadImages = () => {};
    try {
        assert.equal(typeof page.doSearch, 'function');
        assert.equal(typeof page._applyMakerError, 'function');
        page.searchQuery = 'abc';
        page.doSearch('', { maker: MAKER_A });
        assert.equal(page.searchQuery, '');
        assert.equal(page.currentMode, 'maker');
        assert.equal(page.activeMaker().key, 'moodyz');
        assert.equal(page.progressQueryText(), 'MOODYZ');
        assert.ok(lastES().url.startsWith('/api/search/stream?maker_key='));
        lastES().emit({ type: 'result', success: false, data: [], error_code: 'maker_not_found' });
        assert.equal(page.errorKind, 'maker_not_found');
    } finally {
        page.cancelSearch();
        clearTimeout(page.streamBurstTimer);
        clearTimeout(page._coverSwapTimer);
    }
});
