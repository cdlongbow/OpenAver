// libraryInsightsState 契約（預覽開關、年表點擊、選取條件、去瀏覽頁）。
// state.js 會連帶載入 charts.js，故先掛最小 window／document stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
});
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};
globalThis.document = globalThis.document || {
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    getElementById() { return null; },
    createElement() {
        return {
            style: {},
            appendChild() {},
        };
    },
    body: {
        appendChild() {},
        classList: { add() {}, remove() {}, contains() { return false; } },
    },
};

const { libraryInsightsState } = await import('../state.js');
const { setRecords } = await import('../aggregate.js');

// 測試用手組 sel（三條件，預設全空）
function selOf(over) {
    return { period: { type: 'all' }, actress: null, maker: null, ...over };
}

function rec(opts) {
    return {
        year: opts.year === undefined ? 2020 : opts.year,
        month: opts.month === undefined ? null : opts.month,
        actresses: opts.actresses === undefined ? ['Alice'] : opts.actresses,
        maker: opts.maker === undefined ? 'SOD' : opts.maker,
        tags: opts.tags === undefined ? [] : opts.tags,
        date: opts.date === undefined ? null : opts.date,
        duration: opts.duration === undefined ? null : opts.duration,
    };
}

test('openPreview: hasPhoto=false 時不開預覽（spec §3.4.1「不出現預覽」）', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '無圖女優': { photoName: '無圖女優', hasPhoto: false, auto_focal: '', crop_mode: 'auto' },
        },
    };
    state.openPreview('無圖女優', null);
    assert.equal(state.previewActress, null);
});

test('openPreview: hasPhoto=true 時正常開預覽', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '有圖女優': { photoName: '有圖女優', hasPhoto: true, auto_focal: '', crop_mode: 'auto' },
        },
    };
    state.openPreview('有圖女優', null);
    assert.equal(state.previewActress, '有圖女優');
});

test('scheduleOpenPreview: touch 事件不排程預覽，mouse／pen／缺省照常排程', () => {
    const state = libraryInsightsState();
    state.snapshot = {
        actressFavorites: {
            '有圖女優': { photoName: '有圖女優', hasPhoto: true, auto_focal: '', crop_mode: 'auto' },
        },
    };
    const originalSetTimeout = globalThis.setTimeout;
    let scheduled = 0;
    globalThis.setTimeout = () => { scheduled += 1; return scheduled; };
    try {
        const counts = [];
        for (const pointerType of ['touch', 'mouse', 'pen', '']) {
            scheduled = 0;
            state.scheduleOpenPreview('有圖女優', null, { pointerType });
            counts.push(scheduled);
            state.cancelOpenPreview();
        }
        scheduled = 0;
        state.scheduleOpenPreview('有圖女優', null);
        counts.push(scheduled);
        assert.deepEqual(counts, [0, 1, 1, 1, 1]);
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        state.cancelOpenPreview();
    }
});

// TASK-161b-T6：以 setter 計算整份 sel 提交次數。
function ganttClickState() {
    const state = libraryInsightsState();
    state.sel = { period: { type: 'all' }, actress: null, maker: null };
    let current = state.sel;
    let commits = 0;
    Object.defineProperty(state, 'sel', {
        get: () => current,
        set: (value) => { current = value; commits += 1; },
    });
    return { state, commits: () => commits };
}

test('ganttCellClick: 無片格或年齡軸且她已被選中，完全無動作（不飛行、sel 零次提交、預覽收掉）', () => {
    for (const [cell, axis] of [
        [{ year: 2022, state: 'empty', filmCount: 0 }, 'year'],
        [{ age: 25, state: 'main', filmCount: 2 }, 'age'],
    ]) {
        const { state, commits } = ganttClickState();
        state.sel.actress = '她';
        state.previewActress = 'x';
        const before = structuredClone(state.sel);
        const calls = [];
        state.flyAndFocusActress = (...args) => calls.push(args);
        state.ganttCellClick('她', cell, axis, { currentTarget: { closest: () => ({}) } });
        assert.deepEqual(calls, []);
        assert.equal(commits(), 0);
        assert.deepEqual(state.sel, before);
        assert.equal(state.previewActress, null);
    }
});

test('ganttCellClick: 有片格且她已被選中，不飛行、sel 恰提交一次；再點同格只取消年份、片商不變', () => {
    const { state, commits } = ganttClickState();
    state.sel.actress = '她';
    state.sel.maker = '片商';
    state.sel.period = { type: 'range', from: 2019, to: 2023 };
    const calls = [];
    state.flyAndFocusActress = (...args) => calls.push(args);
    const cell = { year: 2021, state: 'main', filmCount: 3 };
    const event = { currentTarget: { closest: () => ({}) } };
    state.ganttCellClick('她', cell, 'year', event);
    assert.equal(commits(), 1);
    assert.deepEqual(state.sel, { actress: '她', period: { type: 'year', year: 2021 }, maker: '片商' });
    state.ganttCellClick('她', cell, 'year', event);
    assert.equal(commits(), 2);
    assert.deepEqual(state.sel, { actress: '她', period: { type: 'all' }, maker: '片商' });
    assert.deepEqual(calls, []);
});

test('ganttCellClick: 有片格且未選她，一次提交女優＋年份；來源頭像不存在時仍正確提交一次', () => {
    for (const maker of [null, '片商']) {
        const { state, commits } = ganttClickState();
        state.sel.maker = maker;
        const fakeRow = { matches: (s) => s === '.gantt-row', querySelector: () => null };
        const event = { currentTarget: { closest: () => fakeRow } };
        state.ganttCellClick('她', { year: 2021, state: 'main', filmCount: 3 }, 'year', event);
        assert.equal(commits(), 1);
        assert.deepEqual(state.sel, { actress: '她', period: { type: 'year', year: 2021 }, maker });
    }
});

test('flyAndFocusActress: 帶 nextSel 時清除分支與找不到來源的提前返回都提交 nextSel', () => {
    for (const actress of ['她', null]) {
        const { state, commits } = ganttClickState();
        state.sel.actress = actress;
        const nextSel = { actress: '她', period: { type: 'year', year: 2021 }, maker: '片商' };
        state.flyAndFocusActress('她', null, nextSel);
        assert.deepEqual(state.sel, nextSel);
        assert.equal(commits(), 1);
    }
});

test('_onPageShow: bfcache 還原時快照仍未載入完成（離頁前 fetch 被丟棄）→ 重新 fetch 並填入資料', async () => {
    // Finding 2：真實流程是 sidebar 點擊觸發 page-lifecycle.js 的 leavePage() →
    // 同步呼叫這裡註冊的 cleanup（_pageAlive=false），發生在快照 fetch 尚未回應時；
    // 之後瀏覽器把這頁存進 bfcache，使用者按上一頁回來只會收到 pageshow(persisted)，
    // 不會重跑 init()——若這裡不重新 fetch，畫面永遠停在空的。
    let cleanupFn = null;
    globalThis.window.__registerPage = (handlers) => {
        cleanupFn = handlers.cleanup;
    };

    let fetchCalls = 0;
    let resolveFirst;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = () => {
        fetchCalls += 1;
        if (fetchCalls === 1) {
            return new Promise((resolve) => {
                resolveFirst = resolve;
            });
        }
        return Promise.resolve({
            ok: true,
            json: async () => ({
                records: [],
                logicalTitles: 5,
                physicalRows: 5,
                years: [],
                actressFavorites: {},
            }),
        });
    };

    const state = libraryInsightsState();
    state.$watch = () => {};
    const initPromise = state.init(); // 發起 fetch #1（掛著不回）

    assert.equal(typeof cleanupFn, 'function', 'init() 應註冊 __registerPage cleanup');
    cleanupFn(); // 模擬使用者在快照載完前離頁

    // 離頁前的 fetch #1 這時才回來（fetch 不會因為 cleanup 被取消）
    resolveFirst({
        ok: true,
        json: async () => ({
            records: [{ maker: 'stale' }],
            logicalTitles: 999,
            physicalRows: 999,
            years: [],
            actressFavorites: {},
        }),
    });
    await initPromise;

    assert.equal(state.snapshot, null, '離頁後才回來的回應不該寫入 snapshot');
    assert.equal(state.snapshotError, null);

    // bfcache 還原：pageshow(persisted) 觸發，此時快照仍是 null 且非 snapshotError
    await state._onPageShow({ persisted: true });

    assert.equal(fetchCalls, 2, '應重新發起一次 fetch，不是停在空畫面等不到的舊回應');
    assert.ok(state.snapshot, 'bfcache 還原後應該有 snapshot 資料');
    assert.equal(state.snapshot.logicalTitles, 5);

    globalThis.fetch = originalFetch;
    delete globalThis.window.__registerPage;
});

test('totalCountLabel: 用 logicalTitles（全庫片數）而非 scopedCount（目前範圍片數）', () => {
    // Finding 3：spec §3.1 片數格下方小字固定顯示「全庫 N 部」，不隨期間／焦點縮。
    const state = libraryInsightsState();
    state.snapshot = { logicalTitles: 2103 };
    state.scopedCount = 12; // 目前範圍（期間 ∩ 焦點）片數，不應影響這個小字
    globalThis.window.t = (key, params) => {
        assert.equal(key, 'insights.total_count');
        return '全庫 ' + params.n + ' 部';
    };
    assert.equal(state.totalCountLabel(), '全庫 2,103 部');
    globalThis.window.t = (key) => key;
});

test('totalCountLabel: snapshot 未載入時回 0（不拋錯）', () => {
    const state = libraryInsightsState();
    state.snapshot = null;
    globalThis.window.t = (key, params) => '全庫 ' + params.n + ' 部';
    assert.equal(state.totalCountLabel(), '全庫 0 部');
    globalThis.window.t = (key) => key;
});

test('ganttView: 快取鍵認整個 sel，只換片商或只換期間也必須重算', () => {
    setRecords([rec({ year: 2020, actresses: ['Alice'] }), rec({ year: 2021, actresses: ['Alice'] })]);
    try {
        const state = libraryInsightsState();
        state.snapshot = { actressFavorites: {} };
        state.ganttRows = [{ name: 'Alice' }];
        state.sel = selOf({ actress: 'Alice' });
        const first = state.ganttView('year');
        assert.equal(state.ganttView('year'), first, 'sel 沒變時命中快取');
        state.sel = { ...state.sel, maker: 'SOD' };
        const afterMaker = state.ganttView('year');
        assert.notEqual(afterMaker, first, '只換片商必須重算');
        state.sel = { ...state.sel, period: { type: 'year', year: 2020 } };
        const afterPeriod = state.ganttView('year');
        assert.notEqual(afterPeriod, afterMaker, '只換期間必須重算');
    } finally {
        setRecords([]);
    }
});

test('toggleMakerFocus／toggleActressFocus: 疊加不互斥，期間與另一條件保留', () => {
    const state = libraryInsightsState();
    const period = { type: 'range', from: 2019, to: 2023 };
    state.sel = selOf({ period, actress: 'A' });
    state.toggleMakerFocus('S1');
    assert.deepEqual(state.sel, { period, actress: 'A', maker: 'S1' });
    state.toggleActressFocus('A');
    assert.deepEqual(state.sel, { period, actress: null, maker: 'S1' });
    state.toggleActressFocus('B');
    assert.deepEqual(state.sel, { period, actress: 'B', maker: 'S1' });
    state.toggleActressFocus('B');
    state.toggleMakerFocus('S1');
    assert.deepEqual(state.sel, { period, actress: null, maker: null });
});

test('clearActress／clearMaker: 各自只清自己那一條件，期間保留', () => {
    const state = libraryInsightsState();
    const period = { type: 'year', year: 2021 };
    state.sel = selOf({ period, actress: 'A', maker: 'S1' });
    state.clearActress();
    assert.deepEqual(state.sel, { period, actress: null, maker: 'S1' });
    state.sel = selOf({ period, actress: 'A', maker: 'S1' });
    state.clearMaker();
    assert.deepEqual(state.sel, { period, actress: 'A', maker: null });
});

// ── topDisplayCount (TASK-156e-T3) ───────────────────────────────────

test('topDisplayCount: displayMap 有對應 key → 回傳該值', () => {
    const state = libraryInsightsState();
    state.boardDisplayCounts = { Alice: 7 };
    assert.equal(state.topDisplayCount({ name: 'Alice', count: 12 }), 7);
});

test('topDisplayCount: 沒有 key → fallback row.count', () => {
    const state = libraryInsightsState();
    state.boardDisplayCounts = {};
    assert.equal(state.topDisplayCount({ name: 'Alice', count: 12 }), 12);
});

// ── canGoBrowse / goBrowse (TASK-161a-T7) ────────────────────────────

// 安裝 localStorage／location／console.warn 的記錄器，回傳 { calls, warns, restore }
function installBrowseStubs({ stored = null, setItemThrows = false } = {}) {
    const calls = [];
    const warns = [];
    const lsDesc = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    const locDesc = Object.getOwnPropertyDescriptor(globalThis, 'location');
    const origWarn = console.warn;
    const fake = {
        getItem(k) { calls.push(['getItem', k]); return stored; },
        setItem(k, v) {
            if (setItemThrows) throw new Error('quota');
            calls.push(['setItem', k, v]);
        },
    };
    Object.defineProperty(globalThis, 'localStorage', { value: fake, configurable: true, writable: true });
    Object.defineProperty(globalThis, 'location', {
        value: { assign(url) { calls.push(['assign', url]); } },
        configurable: true,
        writable: true,
    });
    console.warn = (...args) => { warns.push(args); };
    const restore = () => {
        console.warn = origWarn;
        if (lsDesc) Object.defineProperty(globalThis, 'localStorage', lsDesc);
        else delete globalThis.localStorage;
        if (locDesc) Object.defineProperty(globalThis, 'location', locDesc);
        else delete globalThis.location;
    };
    return { calls, warns, restore };
}

test('goBrowse: 片數為 0 或快照失敗時不寫入也不導航', () => {
    // canGoBrowse：尚未載入 false、有片 true、片數 0 false、快照失敗 false
    const fresh = libraryInsightsState();
    assert.equal(fresh.canGoBrowse, false);
    const gate = libraryInsightsState();
    gate.snapshotError = null;
    gate.scopedCount = 5;
    assert.equal(gate.canGoBrowse, true);
    gate.scopedCount = 0;
    assert.equal(gate.canGoBrowse, false);
    gate.snapshotError = true;
    gate.scopedCount = 5;
    assert.equal(gate.canGoBrowse, false);

    const stub = installBrowseStubs();
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 0;
        state.goBrowse();
        assert.deepEqual(stub.calls, []);
        state.snapshotError = true;
        state.scopedCount = 5;
        state.goBrowse();
        assert.deepEqual(stub.calls, []);
    } finally {
        stub.restore();
    }
});

test('goBrowse: 寫入失敗時不導航', () => {
    const stub = installBrowseStubs({ setItemThrows: true });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 5;
        assert.doesNotThrow(() => state.goBrowse());
        assert.equal(stub.calls.filter((c) => c[0] === 'assign').length, 0);
        assert.equal(stub.warns.length, 1);
    } finally {
        stub.restore();
    }
});

test('goBrowse: 先寫入 showcase_state 再導向 /showcase，保留既有排序與卡型、整組換成目前條件', () => {
    const old = JSON.stringify({
        sort: 'x', cardShape: 'poster', infoVisible: true, search: 'abc',
        pills: [{ dim: 'actress', value: '舊' }],
    });
    const stub = installBrowseStubs({ stored: old });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 12;
        state.sel = { period: { type: 'year', year: 2023 }, actress: 'A', maker: 'M' };
        state.goBrowse();
        const writes = stub.calls.filter((c) => c[0] === 'setItem' || c[0] === 'assign');
        assert.equal(writes.length, 2);
        assert.equal(writes[0][0], 'setItem');
        assert.equal(writes[0][1], 'showcase_state');
        assert.deepEqual(writes[1], ['assign', '/showcase']);
        const saved = JSON.parse(writes[0][2]);
        assert.equal(saved.pills.length, 3);
        const dims = saved.pills.map((p) => p.dim).sort();
        assert.deepEqual(dims, ['actress', 'maker', 'release']);
        const rel = saved.pills.find((p) => p.dim === 'release');
        assert.equal(rel.op, '=');
        assert.equal(rel.value, '2023');
        assert.equal(saved.search, '');
        assert.equal(saved.page, 1);
        assert.equal(saved.showFavoriteActresses, false);
        assert.equal(saved.sort, 'x');
        assert.equal(saved.cardShape, 'poster');
        assert.equal(saved.infoVisible, true);
    } finally {
        stub.restore();
    }

    // 無條件也能跳
    const stub2 = installBrowseStubs({ stored: old });
    try {
        const state = libraryInsightsState();
        state.snapshotError = null;
        state.scopedCount = 2103;
        state.sel = selOf({});
        state.goBrowse();
        const set = stub2.calls.find((c) => c[0] === 'setItem');
        assert.deepEqual(JSON.parse(set[2]).pills, []);
        assert.equal(stub2.calls.filter((c) => c[0] === 'assign').length, 1);
    } finally {
        stub2.restore();
    }
});
