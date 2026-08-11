// TASK-117-T4: 片庫加入女優面板 —— 載入 / 排序 / 過濾 / 分批
//
// 範本：actress-sort.test.mjs（FE-GUARD-11：window stub + importmap resolve hook）
// 一律 method、Object.assign 建元件（FE-ALPINE-03 不得用 getter）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage。FE-GUARD-11：第一段就要有。
globalThis.window = globalThis;
globalThis.window.t = (key, params) => {
    if (!params) return key;
    return key + JSON.stringify(params);
};
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
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

const { stateActress } = await import('../state-actress.js');
// 117-T5：_actresses 是 module-level 共享陣列（測試間互相污染）——涉及女優牆的測試
// 必須先 _setActresses([]) 才能斷言。
const { _actresses, _setActresses } = await import('../state-base.js');

// 形狀照 T1 真實回應（含 names / total）；別名與正式名必須分歧（AC-5.2 零訊號陷阱）
const LIBRARY_FIXTURE = [
    { primary_name: '明里つむぎ', names: ['明里つむぎ'], video_count: 68, is_favorite: true },
    { primary_name: '三上悠亜', names: ['三上悠亜'], video_count: 50, is_favorite: false },
    { primary_name: '橋本ありな', names: ['橋本ありな', '新ありな'], video_count: 40, is_favorite: false },
    { primary_name: 'ＲＩＯＮ', names: ['ＲＩＯＮ', 'RION'], video_count: 30, is_favorite: false },
];

function makeLibraryRows(n) {
    const rows = [];
    for (let i = 0; i < n; i++) {
        rows.push({
            primary_name: `女優${String(i).padStart(3, '0')}`,
            names: [`女優${String(i).padStart(3, '0')}`],
            video_count: n - i,
            is_favorite: i % 10 === 0,
        });
    }
    return rows;
}

function makeComponent(overrides = {}) {
    return Object.assign({}, stateActress(), {
        showToast() {},
        ...overrides,
    });
}

function mockFetchOk(payload) {
    const prev = globalThis.fetch;
    globalThis.fetch = async () => ({
        ok: true,
        status: 200,
        json: async () => payload,
    });
    return () => { globalThis.fetch = prev; };
}

function mockFetchSequence(handlers) {
    const prev = globalThis.fetch;
    let i = 0;
    globalThis.fetch = async (...args) => {
        const h = handlers[Math.min(i, handlers.length - 1)];
        i++;
        return h(...args);
    };
    return () => { globalThis.fetch = prev; };
}

function flushMicrotasks() {
    return new Promise((r) => setImmediate(r));
}

// ── AC-1.3 / AC-1.6：開啟即載入、不等網路 ─────────────────────────────────

test('AC-1.6：openActressAddPanel 同步 return 後 actressAddPanelOpen === true（不 await）', () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        // 故意不 await：同步路徑必須立刻開殼
        c.openActressAddPanel();
        assert.equal(c.actressAddPanelOpen, true);
        assert.equal(c._libQuery, '');
        assert.equal(c._libVisibleCount, 40);
        assert.equal(c._libLoading, true);
    } finally {
        restore();
    }
});

test('AC-1.3：開啟即載入；關閉再開重新載入（fetch 兩次、query/visibleCount 歸零）', async () => {
    let fetchCount = 0;
    const restore = mockFetchSequence([
        async () => {
            fetchCount++;
            return {
                ok: true,
                status: 200,
                json: async () => ({ success: true, actresses: LIBRARY_FIXTURE, total: 4 }),
            };
        },
    ]);
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        assert.equal(fetchCount, 1);
        assert.equal(c._libRows.length, 4);
        assert.equal(c._libTotal, 4);
        assert.equal(c._libLoading, false);

        c._libQuery = '橋本';
        c._libVisibleCount = 80;
        c.closeActressAddPanel();
        assert.equal(c.actressAddPanelOpen, false);
        assert.equal(c._libQuery, '');
        assert.equal(c._libVisibleCount, 40);
        // close 不清 _libRows
        assert.equal(c._libRows.length, 4);

        c.openActressAddPanel();
        // open 立即清空再載入
        assert.equal(c._libRows.length, 0);
        assert.equal(c._libTotal, 0);
        await flushMicrotasks();
        assert.equal(fetchCount, 2);
        assert.equal(c._libRows.length, 4);
    } finally {
        restore();
    }
});

// ── 載入失敗 / 空庫 / gen guard ────────────────────────────────────────────

test('端點失敗：_libError=true、rows 空、面板不關；直接新增仍可用', async () => {
    const restore = mockFetchSequence([
        async () => ({ ok: false, status: 500, json: async () => ({}) }),
    ]);
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        assert.equal(c.actressAddPanelOpen, true);
        assert.equal(c._libError, true);
        assert.equal(c._libRows.length, 0);
        assert.equal(c._libTotal, 0);
        assert.equal(c._libLoading, false);
        // 降級：_libError 時直接新增仍可用
        c._libQuery = '不存在的人';
        assert.equal(c.libShowDirectAdd(), true);
    } finally {
        restore();
    }
});

test('空庫 total=0：progress 用 ?? 顯示共 0 位（FE-JS-01）', async () => {
    const calls = [];
    const prevT = globalThis.window.t;
    globalThis.window.t = (key, params) => {
        calls.push({ key, params });
        return key;
    };
    const restore = mockFetchOk({ success: true, actresses: [], total: 0 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        assert.equal(c._libTotal, 0);
        const text = c.libProgressText();
        assert.equal(text, 'showcase.actress.panel.progress_all');
        assert.deepEqual(calls[calls.length - 1], {
            key: 'showcase.actress.panel.progress_all',
            params: { m: 0 },
        });
    } finally {
        restore();
        globalThis.window.t = prevT;
    }
});

test('stale response guard：舊 gen 的 response 不覆寫新清單；舊 finally 不關新 loading', async () => {
    let resolveFirst;
    let resolveSecond;
    const firstPromise = new Promise((r) => { resolveFirst = r; });
    const secondPromise = new Promise((r) => { resolveSecond = r; });
    let call = 0;
    const prev = globalThis.fetch;
    globalThis.fetch = async () => {
        call++;
        if (call === 1) {
            await firstPromise;
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    success: true,
                    actresses: [{ primary_name: '舊', names: ['舊'], video_count: 1, is_favorite: false }],
                    total: 1,
                }),
            };
        }
        await secondPromise;
        return {
            ok: true,
            status: 200,
            json: async () => ({
                success: true,
                actresses: [{ primary_name: '新', names: ['新'], video_count: 9, is_favorite: false }],
                total: 1,
            }),
        };
    };
    try {
        const c = makeComponent();
        c.openActressAddPanel(); // gen=1, loading=true
        assert.equal(c._libLoadGen, 1);
        c.openActressAddPanel(); // gen=2, loading=true again
        assert.equal(c._libLoadGen, 2);
        assert.equal(c._libLoading, true);

        // 先放行第二次（新）
        resolveSecond();
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c._libRows[0]?.primary_name, '新');
        assert.equal(c._libLoading, false);

        // 再放行第一次（舊）——不得覆寫，也不得把 loading 弄髒
        resolveFirst();
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c._libRows[0]?.primary_name, '新');
        assert.equal(c._libLoading, false);
    } finally {
        globalThis.fetch = prev;
        resolveFirst();
        resolveSecond();
    }
});

// 既有 stale test 先 resolve 新輪再 resolve 舊輪：舊 finally 跑到時 loading 已是 false，
// 拿掉 finally 的 gen guard 仍全綠。本支讓舊輪先落地、新輪仍飛，才鎖得住「舊 finally 不得關新 loading」。
test('stale finally guard：舊輪先 resolve、新輪仍飛時 _libLoading 必須仍 true', async () => {
    let resolveFirst;
    let resolveSecond;
    const firstPromise = new Promise((r) => { resolveFirst = r; });
    const secondPromise = new Promise((r) => { resolveSecond = r; });
    let call = 0;
    const prev = globalThis.fetch;
    globalThis.fetch = async () => {
        call++;
        if (call === 1) {
            await firstPromise;
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    success: true,
                    actresses: [{ primary_name: '舊', names: ['舊'], video_count: 1, is_favorite: false }],
                    total: 1,
                }),
            };
        }
        await secondPromise;
        return {
            ok: true,
            status: 200,
            json: async () => ({
                success: true,
                actresses: [{ primary_name: '新', names: ['新'], video_count: 9, is_favorite: false }],
                total: 1,
            }),
        };
    };
    try {
        const c = makeComponent();
        c.openActressAddPanel(); // gen=1
        c.openActressAddPanel(); // gen=2
        assert.equal(c._libLoadGen, 2);
        assert.equal(c._libLoading, true);

        // 先放行第一次（舊）——新輪仍在飛；finally 有 gen guard 則 loading 必須仍 true
        resolveFirst();
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c._libLoading, true, '舊輪 finally 不得把新輪 _libLoading 關掉');
        assert.equal(c._libRows.length, 0, '舊 response 不得寫入（gen 已過期）');

        // 再放行第二次（新）
        resolveSecond();
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c._libRows[0]?.primary_name, '新');
        assert.equal(c._libLoading, false);
    } finally {
        globalThis.fetch = prev;
        resolveFirst();
        resolveSecond();
    }
});

// ── AC-2.1 / AC-2.2 / AC-3.2 ───────────────────────────────────────────────

test('AC-2.1：is_favorite:true 的列仍在 libVisibleRows() 內', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        const names = c.libVisibleRows().map((r) => r.primary_name);
        assert.ok(names.includes('明里つむぎ'));
        assert.equal(c.libVisibleRows()[0].is_favorite, true);
    } finally {
        restore();
    }
});

test('AC-2.2：前端零重排——可見列順序 === 回應順序', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        assert.deepEqual(
            c.libVisibleRows().map((r) => r.primary_name),
            LIBRARY_FIXTURE.map((r) => r.primary_name),
        );
        // 方法體內不得 .sort(——以行為證明：過濾後次序仍是原相對次序
        c._libQuery = 'ありな';
        assert.deepEqual(
            c.libFilteredRows().map((r) => r.primary_name),
            ['橋本ありな'],
        );
    } finally {
        restore();
    }
});

test('AC-3.2：libRowFavorited(row) 吃 row.is_favorite', () => {
    const c = makeComponent();
    assert.equal(c.libRowFavorited({ is_favorite: true }), true);
    assert.equal(c.libRowFavorited({ is_favorite: false }), false);
    assert.equal(c.libRowFavorited(null), false);
});

// ── AC-5.x 過濾 ────────────────────────────────────────────────────────────

test('AC-5.1：即時過濾——改 _libQuery 立刻影響 libVisibleRows', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        c._libQuery = '三上';
        assert.deepEqual(c.libVisibleRows().map((r) => r.primary_name), ['三上悠亜']);
    } finally {
        restore();
    }
});

test('AC-5.2：過濾涵蓋別名——打「新ありな」命中顯示「橋本ありな」的那一列', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        c._libQuery = '新ありな';
        const rows = c.libFilteredRows();
        assert.equal(rows.length, 1);
        assert.equal(rows[0].primary_name, '橋本ありな');
        // primary_name 本身不含「新ありな」——證明掃的是 names[]
        assert.ok(!rows[0].primary_name.includes('新'));
    } finally {
        restore();
    }
});

test('AC-5.2b：NFKC 正規化——半形 RION 命中全形 ＲＩＯＮ', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();
        c._libQuery = 'RION';
        assert.equal(c.libFilteredRows()[0].primary_name, 'ＲＩＯＮ');
    } finally {
        restore();
    }
});

test('AC-5.3：比對完整資料集——相符者在第 100 名、可見窗只有 40 仍查得到', () => {
    const rows = makeLibraryRows(120);
    // 把目標放在 index 99（第 100 名）
    rows[99] = {
        primary_name: '目標さん',
        names: ['目標さん', '別名ターゲット'],
        video_count: 1,
        is_favorite: false,
    };
    const c = makeComponent({
        _libRows: rows,
        _libTotal: 120,
        _libVisibleCount: 40,
        _libQuery: '別名ターゲット',
    });
    // 可見窗 slice(0,40) 本來看不到 index 99，但過濾後它應在 filtered 結果裡
    assert.equal(c.libFilteredRows().length, 1);
    assert.equal(c.libVisibleRows()[0].primary_name, '目標さん');
});

test('AC-5.4：無相符時 libShowDirectAdd；libDirectAdd 走 addFavoriteActress 且送原字', async () => {
    const restore = mockFetchOk({ success: true, actresses: LIBRARY_FIXTURE, total: 4 });
    let postedBody = null;
    try {
        const c = makeComponent();
        c.openActressAddPanel();
        await flushMicrotasks();

        assert.equal(c.libShowDirectAdd(), false);
        c._libQuery = '  完全不存在的女優  ';
        assert.equal(c.libShowDirectAdd(), true);
        assert.equal(c.libDirectAddName(), '完全不存在的女優'); // trim 後原字

        // 載入中不顯示
        c._libLoading = true;
        assert.equal(c.libShowDirectAdd(), false);
        c._libLoading = false;

        // mock POST for addFavoriteActress
        const prev = globalThis.fetch;
        globalThis.fetch = async (url, opts) => {
            if (String(url).includes('/favorite')) {
                postedBody = JSON.parse(opts.body);
                return { ok: true, status: 200, json: async () => ({ success: true, actress: { name: postedBody.name } }) };
            }
            return { ok: true, status: 200, json: async () => ({ success: true, actresses: [], total: 0 }) };
        };
        try {
            await c.libDirectAdd();
        } finally {
            globalThis.fetch = prev;
        }
        assert.equal(postedBody.name, '完全不存在的女優');
        // 不清 query、不關面板
        assert.equal(c._libQuery, '  完全不存在的女優  ');
        assert.equal(c.actressAddPanelOpen, true);
    } finally {
        restore();
    }
});

test('AC-5.5：清空輸入框回到原清單與原展開列數', () => {
    const rows = makeLibraryRows(50);
    const c = makeComponent({
        _libRows: rows,
        _libTotal: 50,
        _libVisibleCount: 40,
        _libQuery: '女優000', // 完整 primary_name，避免子字串命中 000–009
    });
    assert.equal(c.libFilteredRows().length, 1);
    c._libQuery = '';
    assert.equal(c.libFilteredRows().length, 50);
    assert.equal(c.libVisibleRows().length, 40);
    assert.equal(c._libVisibleCount, 40);
});

// ── AC-6.x 分批 ────────────────────────────────────────────────────────────

test('AC-6.1/6.2/6.3：首批 40、展開 +40、已顯示不收起、到底鈕消失', () => {
    const rows = makeLibraryRows(100);
    const c = makeComponent({
        _libRows: rows,
        _libTotal: 100,
        _libVisibleCount: 40,
    });
    assert.equal(c.libVisibleRows().length, 40);
    assert.equal(c.libHasMore(), true);

    c.libExpandMore();
    assert.equal(c._libVisibleCount, 80);
    assert.equal(c.libVisibleRows().length, 80);
    assert.equal(c.libHasMore(), true);

    c.libExpandMore();
    assert.equal(c._libVisibleCount, 120);
    assert.equal(c.libVisibleRows().length, 100); // 只有 100 筆
    assert.equal(c.libHasMore(), false);
});

test('AC-6.4：append-only + primary_name 唯一 + 前 N 列同物件參考', () => {
    const rows = makeLibraryRows(90);
    const c = makeComponent({
        _libRows: rows,
        _libTotal: 90,
        _libVisibleCount: 40,
    });
    const before = c.libVisibleRows();
    const first40 = before.slice();

    // key 唯一
    const keys = c.libFilteredRows().map((r) => r.primary_name);
    assert.equal(new Set(keys).size, keys.length);

    c.libExpandMore();
    const after = c.libVisibleRows();
    assert.equal(after.length, 80);
    // 前 40 列逐項 === 同一物件參考
    for (let i = 0; i < 40; i++) {
        assert.equal(after[i], first40[i]);
    }
});

test('AC-6.5：底部進度 key + params；到底改 progress_all', () => {
    const calls = [];
    const prevT = globalThis.window.t;
    globalThis.window.t = (key, params) => {
        calls.push({ key, params });
        return key;
    };
    try {
        const rows = makeLibraryRows(50);
        const c = makeComponent({
            _libRows: rows,
            _libTotal: 50,
            _libVisibleCount: 40,
            _libQuery: '',
        });
        c.libProgressText();
        assert.deepEqual(calls[calls.length - 1], {
            key: 'showcase.actress.panel.progress',
            params: { n: 40, m: 50 },
        });

        c._libVisibleCount = 80;
        c.libProgressText();
        assert.deepEqual(calls[calls.length - 1], {
            key: 'showcase.actress.panel.progress_all',
            params: { m: 50 },
        });

        // 有過濾字時分母用相符筆數
        c._libQuery = '女優000';
        c._libVisibleCount = 40;
        c.libProgressText();
        assert.deepEqual(calls[calls.length - 1], {
            key: 'showcase.actress.panel.progress_all',
            params: { m: 1 },
        });
    } finally {
        globalThis.window.t = prevT;
    }
});

test('libProgressText：載入中／失敗時回空字串（不說謊「共 0 位」）', () => {
    const c = makeComponent({
        _libLoading: true,
        _libError: null,
        _libRows: [],
        _libTotal: 0,
        _libVisibleCount: 40,
        _libQuery: '',
    });
    assert.equal(c.libProgressText(), '');

    c._libLoading = false;
    c._libError = true;
    assert.equal(c.libProgressText(), '');
});

test('空白 query 視同無過濾；libDirectAdd 在 _addingActress 時 no-op', () => {
    const c = makeComponent({
        _libRows: LIBRARY_FIXTURE,
        _libTotal: 4,
        _libQuery: '   ',
    });
    assert.equal(c.libFilteredRows().length, 4);
    assert.equal(c.libShowDirectAdd(), false);

    c._libQuery = 'ghost';
    c._addingActress = true;
    c._addActressName = '';
    c.libDirectAdd();
    assert.equal(c._addActressName, ''); // 沒寫入
});

// ══ T5：收藏 queue ══
//
// INV-1（≤2 in-flight）／INV-2（同 group 不重複入隊）／INV-3（排空保證）——見 TASK-117-T5.md
// §技術要點 2。§4.1b T4-①：同步斷言測不出「全部同時發」的壞法，INV-1 直接數 fetch 呼叫次數，
// 不數 _libRowState。§4.1b T4-②：finally guard 測試必須讓第 1 支先 resolve、第 2 支仍在飛。

// 逐次 fetch 呼叫都會被記錄，且回傳一個由呼叫者手動 resolve 的 Promise——藉此量測
// 「已送出但尚未落地」的即時數量（INV-1 的 oracle），並能精準控制「哪一支先 resolve」
// （finally 順序測試的 oracle）。
function mockFetchManual() {
    const prev = globalThis.fetch;
    const calls = [];
    let concurrent = 0;
    let maxConcurrent = 0;
    globalThis.fetch = (url, opts) => {
        concurrent++;
        maxConcurrent = Math.max(maxConcurrent, concurrent);
        const body = opts && opts.body ? JSON.parse(opts.body) : {};
        return new Promise((resolve) => {
            calls.push({
                url,
                method: opts && opts.method,
                body,
                name: body.name,
                resolve: (respLike) => {
                    concurrent--;
                    resolve(respLike);
                },
            });
        });
    };
    return {
        restore() { globalThis.fetch = prev; },
        calls,
        get maxConcurrent() { return maxConcurrent; },
    };
}

// POST /api/actresses/favorite 200 回應的標準形狀（〈現況分析 D〉）；覆寫 covered_names
// 時要注意 T1 端點已聯集過 req.name，這裡的預設值同型。
function libFavoritePayload(name, overrides = {}) {
    return Object.assign({
        success: true,
        actress: { name, age: null, height: null, cup: null, photo_url: null, video_count: 0, is_favorite: true },
        photo_downloaded: false,
        skipped_aliases: [],
        covered_names: [name],
    }, overrides);
}

function makeQueueRows(n) {
    const rows = [];
    for (let i = 0; i < n; i++) {
        rows.push({
            primary_name: `Q優${String(i).padStart(3, '0')}`,
            names: [`Q優${String(i).padStart(3, '0')}`],
            video_count: 10 + i,
            is_favorite: false,
        });
    }
    return rows;
}

// 1. INV-1
test('INV-1：連點 5 列 → 同時未 resolve 的 fetch 數最大值 === 2；後 3 列 queued 且 fetch 呼叫數 === 2', () => {
    const rows = makeQueueRows(5);
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        rows.forEach((row) => c.libEnqueueFavorite(row));

        assert.equal(mock.calls.length, 2, '同一時間只能有 2 個 fetch 被送出');
        assert.equal(mock.maxConcurrent, 2);
        assert.equal(c.libRowState(rows[0]), 'loading');
        assert.equal(c.libRowState(rows[1]), 'loading');
        assert.equal(c.libRowState(rows[2]), 'queued');
        assert.equal(c.libRowState(rows[3]), 'queued');
        assert.equal(c.libRowState(rows[4]), 'queued');
        assert.equal(c._libInFlight, 2);
    } finally {
        mock.restore();
    }
});

// 2. finally 順序（§4.1b T4-②）
test('finally 順序：第 1 支先 resolve、第 2 支仍在飛 → 第 3 支這時才發 POST，且該瞬間 _libInFlight === 2', async () => {
    const rows = makeQueueRows(3);
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        rows.forEach((row) => c.libEnqueueFavorite(row));
        assert.equal(mock.calls.length, 2);
        assert.equal(c._libQueue.length, 1);

        // 第 1 支落地，第 2 支仍在飛
        mock.calls[0].resolve({ status: 200, json: async () => libFavoritePayload(rows[0].primary_name) });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(mock.calls.length, 3, '第 3 支此時才發出 POST');
        assert.equal(c._libInFlight, 2, '第 1 支落地讓出額度，第 3 支立刻補上，仍是 2 個在飛');
        assert.equal(c.libRowState(rows[2]), 'loading');
        assert.equal(c.libRowState(rows[1]), 'loading', '第 2 支仍在飛，狀態不受影響');
    } finally {
        mock.restore();
    }
});

// 3. INV-2a
test('INV-2a：同一列連點 5 次 → POST 1 次、_libQueue.length 不增', () => {
    const rows = makeQueueRows(1);
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        for (let i = 0; i < 5; i++) c.libEnqueueFavorite(rows[0]);
        assert.equal(mock.calls.length, 1);
        assert.equal(c._libQueue.length, 0);
        assert.equal(c.libRowState(rows[0]), 'loading');
    } finally {
        mock.restore();
    }
});

// 4. INV-2b：出隊重檢（enqueue 檢查擋不住——B 入隊時 A 還沒回）
test('INV-2b：A 的回應涵蓋 B → B 出隊時被丟棄（POST 總數 2）', async () => {
    _setActresses([]);
    const rowA = { primary_name: 'A優', names: ['A優'], video_count: 1, is_favorite: false };
    const rowB = { primary_name: 'B優', names: ['B優'], video_count: 1, is_favorite: false };
    const rowC = { primary_name: 'C優', names: ['C優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(rowA);
        c.libEnqueueFavorite(rowC);
        c.libEnqueueFavorite(rowB);   // 額度已滿（2），B 排隊

        assert.equal(mock.calls.length, 2);
        assert.equal(c._libQueue.length, 1);

        mock.calls[0].resolve({
            status: 200,
            json: async () => libFavoritePayload('A優', { covered_names: ['A優', 'B優'] }),
        });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(mock.calls.length, 2, 'B 出隊被丟棄，不應再發第 3 支 POST');
        assert.equal(c.libRowFavorited(rowB), true);
        assert.equal(c.libRowState(rowB), 'idle');
    } finally {
        mock.restore();
    }
});

// 5. INV-3：排空保證（全失敗也要歸零）
test('INV-3：5 列全部 reject → 皆 error、_libInFlight === 0、_libQueue.length === 0', async () => {
    const rows = makeQueueRows(5);
    const prev = globalThis.fetch;
    globalThis.fetch = async () => { throw new Error('network down'); };
    try {
        const c = makeComponent();
        rows.forEach((row) => c.libEnqueueFavorite(row));
        for (let i = 0; i < 8; i++) await flushMicrotasks();

        rows.forEach((row) => {
            assert.equal(c.libRowState(row), 'error');
            assert.equal(c.libRowErrorText(row), 'showcase.actress.panel.add_failed');
        });
        assert.equal(c._libInFlight, 0);
        assert.equal(c._libQueue.length, 0);
    } finally {
        globalThis.fetch = prev;
    }
});

// 6. AC-4.6：covered_names 涵蓋整組別名
test('AC-4.6：covered_names 涵蓋整組別名——兩列都變實心，再點被涵蓋列 no-op（POST 不增）', async () => {
    _setActresses([]);
    const rowHashimoto = { primary_name: '橋本ありな', names: ['橋本ありな', '新ありな'], video_count: 1, is_favorite: false };
    const rowArina = { primary_name: '新ありな', names: ['新ありな'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(rowHashimoto);
        assert.equal(mock.calls.length, 1);

        mock.calls[0].resolve({
            status: 200,
            json: async () => libFavoritePayload('橋本ありな', {
                covered_names: ['橋本ありな', '新ありな', 'はしもとありな'],
            }),
        });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowFavorited(rowHashimoto), true);
        assert.equal(c.libRowFavorited(rowArina), true);

        c.libEnqueueFavorite(rowArina);
        assert.equal(mock.calls.length, 1, '被 covered 的列再點不得產生新 POST');
    } finally {
        mock.restore();
    }
});

// 7. AC-4.6b：.some 掃 names[] 的 this 綁定（釘住「this 正確但掃描邏輯寫錯」的綠殼）
test('AC-4.6b：libRowFavorited 用 .some 掃 names[]——primary 未 covered、別名被 covered 仍算實心', () => {
    const c = makeComponent();
    c._libCovered = { '別名B': true };
    const row = { primary_name: '正式名A', names: ['正式名A', '別名B'], is_favorite: false };
    assert.equal(c.libRowFavorited(row), true);
});

// 8. 409 視為成功
test('409 視為成功：body 無 success 欄 → 實心、無 error、狀態 idle、covered_names 被吃', async () => {
    _setActresses([]);
    const row = { primary_name: '重複優', names: ['重複優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({
            status: 409,
            json: async () => ({
                error: 'already_exists',
                actress: { name: '重複優', video_count: 0, is_favorite: true },
                covered_names: ['重複優'],
            }),
        });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowFavorited(row), true);
        assert.equal(c.libRowState(row), 'idle');
        assert.equal(c.libRowErrorText(row), '');
    } finally {
        mock.restore();
    }
});

// 9. 404：可重試
test('404：libRowState 為 error、libRowErrorText 走 addNotFound；再點一次可重試（再發一次 POST）', async () => {
    const row = { primary_name: '查無優', names: ['查無優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({ status: 404, json: async () => ({ error: 'not_found', message: '查無此女優' }) });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowState(row), 'error');
        assert.equal(c.libRowErrorText(row), 'showcase.actress.addNotFound');

        c.libEnqueueFavorite(row);
        assert.equal(mock.calls.length, 2, '404 後可重試，允許再發一次 POST');
    } finally {
        mock.restore();
    }
});

// 10. 504
test('504：error key 為 addTimeout', async () => {
    const row = { primary_name: '逾時優', names: ['逾時優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({ status: 504, json: async () => ({ error: 'timeout', message: 'Scraper 超時' }) });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowState(row), 'error');
        assert.equal(c.libRowErrorText(row), 'showcase.actress.addTimeout');
    } finally {
        mock.restore();
    }
});

// 11. 其他（500 / success:false / fetch reject）→ add_failed
test('其他失敗（500 / success:false / fetch reject）→ error key 一律 add_failed', async () => {
    {
        const row = { primary_name: 'X優1', names: ['X優1'], video_count: 1, is_favorite: false };
        const mock = mockFetchManual();
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({ status: 500, json: async () => ({}) });
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c.libRowErrorText(row), 'showcase.actress.panel.add_failed');
        mock.restore();
    }
    {
        const row = { primary_name: 'X優2', names: ['X優2'], video_count: 1, is_favorite: false };
        const mock = mockFetchManual();
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({ status: 200, json: async () => ({ success: false }) });
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c.libRowErrorText(row), 'showcase.actress.panel.add_failed');
        mock.restore();
    }
    {
        const row = { primary_name: 'X優3', names: ['X優3'], video_count: 1, is_favorite: false };
        const prev = globalThis.fetch;
        globalThis.fetch = async () => { throw new Error('boom'); };
        const c = makeComponent();
        c.libEnqueueFavorite(row);
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c.libRowErrorText(row), 'showcase.actress.panel.add_failed');
        globalThis.fetch = prev;
    }
});

// 12. AC-4.4：重套篩選，不強制顯示
test('AC-4.4：加入女優牆後重套目前篩選——不符合條件則卡片不出現', async () => {
    _setActresses([]);
    const row = { primary_name: '篩選優', names: ['篩選優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.actressSearch = '絕不相符的字串';
        c.applyActressFilterAndSort();

        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({ status: 200, json: async () => libFavoritePayload('篩選優') });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.ok(_actresses.some((a) => a.name === '篩選優'), '_actresses 仍含她');
        assert.ok(!c.paginatedActresses.some((a) => a.name === '篩選優'), 'paginatedActresses 不含她（不強制顯示）');
    } finally {
        mock.restore();
    }
});

// 13. 牆去重
test('牆去重：她已在 _actresses → 成功後長度不變', async () => {
    _setActresses([{ name: '已收藏優', video_count: 5, is_favorite: true }]);
    const row = { primary_name: '已收藏優', names: ['已收藏優'], video_count: 5, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.applyActressFilterAndSort();
        const before = _actresses.length;

        c.libEnqueueFavorite(row);
        mock.calls[0].resolve({
            status: 409,
            json: async () => ({
                error: 'already_exists',
                actress: { name: '已收藏優', video_count: 0, is_favorite: true },
                covered_names: ['已收藏優'],
            }),
        });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(_actresses.length, before);
    } finally {
        mock.restore();
    }
});

// 14. 面板不被鎖住（AC-4.3③）
test('面板不被鎖住：入隊 3 列時 _addingActress 仍 false、直接新增仍可用、未入隊列仍 idle', () => {
    const rows = makeQueueRows(4);
    const mock = mockFetchManual();
    try {
        const c = makeComponent({ _libRows: rows, _libQuery: '不存在的人啦啦啦' });
        c.libEnqueueFavorite(rows[0]);
        c.libEnqueueFavorite(rows[1]);
        c.libEnqueueFavorite(rows[2]);

        assert.equal(c._addingActress, false);
        assert.equal(c.libShowDirectAdd(), true);
        assert.equal(c.libRowState(rows[3]), 'idle');
    } finally {
        mock.restore();
    }
});

// 15. 關閉面板不取消
test('關閉面板不取消：enqueue 3 列後 closeActressAddPanel()，仍全部完成並進女優牆', async () => {
    _setActresses([]);
    const rows = makeQueueRows(3);
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        rows.forEach((row) => c.libEnqueueFavorite(row));
        c.closeActressAddPanel();
        assert.equal(c.actressAddPanelOpen, false);
        assert.equal(mock.calls.length, 2);

        mock.calls[0].resolve({ status: 200, json: async () => libFavoritePayload(rows[0].primary_name) });
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(mock.calls.length, 3, '關閉面板不取消排隊中的請求，額度讓出後照常補上');

        mock.calls[1].resolve({ status: 200, json: async () => libFavoritePayload(rows[1].primary_name) });
        mock.calls[2].resolve({ status: 200, json: async () => libFavoritePayload(rows[2].primary_name) });
        await flushMicrotasks();
        await flushMicrotasks();

        rows.forEach((row) => {
            assert.equal(c.libRowFavorited(row), true);
            assert.ok(_actresses.some((a) => a.name === row.primary_name));
        });
        assert.equal(c._libInFlight, 0);
        assert.equal(c._libQueue.length, 0);
    } finally {
        mock.restore();
    }
});

// 16. 重開清 error、保留 queued/loading/covered
test('重開面板：error 列變 idle，queued/loading 列與 _libCovered/_libInFlight 不受影響', async () => {
    const restore = mockFetchOk({ success: true, actresses: [], total: 0 });
    try {
        const c = makeComponent({
            _libRowState: { '失敗優': 'error', '排隊優': 'queued', '進行優': 'loading' },
            _libRowError: { '失敗優': 'showcase.actress.addNotFound' },
            _libCovered: { '涵蓋優': true },
            _libQueue: ['排隊優'],
            _libInFlight: 1,
        });
        c.openActressAddPanel();
        await flushMicrotasks();

        assert.equal(c._libRowState['失敗優'], 'idle');
        assert.equal(c._libRowState['排隊優'], 'queued');
        assert.equal(c._libRowState['進行優'], 'loading');
        assert.equal(c._libCovered['涵蓋優'], true);
        assert.equal(c._libQueue.length, 1);
        assert.equal(c._libInFlight, 1);
    } finally {
        restore();
    }
});

// 17. 打字過濾不影響 queue
test('打字過濾不影響 queue：enqueue 後把 _libQuery 設成排除該列，仍正常完成', async () => {
    _setActresses([]);
    const rowA = { primary_name: '過濾優', names: ['過濾優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(rowA);
        c._libQuery = '絕不相符的過濾字';

        mock.calls[0].resolve({ status: 200, json: async () => libFavoritePayload('過濾優') });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowFavorited(rowA), true);
    } finally {
        mock.restore();
    }
});

// 18. covered 的列不在可見 40 內
test('covered 的列不在可見 40 內：仍算實心，展開後出現時也是實心', () => {
    const rows = makeLibraryRows(200);
    // 第 100 列（0-based index 99；避開 makeLibraryRows 的 i%10===0 天然 is_favorite）
    const c = makeComponent({ _libRows: rows, _libTotal: 200, _libVisibleCount: 40 });
    c._libCovered[rows[99].primary_name] = true;

    assert.equal(c.libRowFavorited(rows[99]), true);
    assert.ok(!c.libVisibleRows().includes(rows[99]));

    c.libExpandMore();
    c.libExpandMore();
    assert.equal(c._libVisibleCount, 120);
    assert.ok(c.libVisibleRows().includes(rows[99]));
    assert.equal(c.libRowFavorited(c.libVisibleRows()[99]), true);
});

// 19. 重載後狀態仍對得上（鍵一律用 primary_name 字串，不用物件參考）
test('重載後狀態仍對得上：_libRows 換成新物件、同名字，libRowState 仍讀得到', () => {
    const rowA = { primary_name: '重載優', names: ['重載優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(rowA);
        assert.equal(c.libRowState(rowA), 'loading');

        const newRowA = { primary_name: '重載優', names: ['重載優'], video_count: 1, is_favorite: false };
        c._libRows = [newRowA];

        assert.equal(c.libRowState(newRowA), 'loading');
    } finally {
        mock.restore();
    }
});

// 20（reviewer①，MAJOR）：連線契約——URL / method / body 欄位名。mockFetchManual 早已把
// body.name 解析出來存進 calls[]，但先前沒有任何一支測試讀它；把 URL 打錯／method 打錯／
// body 欄位名打錯（如 actress_name）在此之前 39/39 全綠、1098 條 lint 也全綠，因為兩邊都
// 只鎖「有沒有打 fetch」，沒人鎖「打去哪裡、帶什麼」。這是整個 feature 唯一真正對外的那一行。
test('連線契約：POST /api/actresses/favorite，body { name: row.primary_name }（不是 GET／不是 actress_name）', () => {
    const row = { primary_name: '契約優', names: ['契約優'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();
        c.libEnqueueFavorite(row);

        assert.equal(mock.calls.length, 1);
        assert.equal(mock.calls[0].url, '/api/actresses/favorite');
        assert.equal(mock.calls[0].method, 'POST');
        assert.equal(mock.calls[0].body.name, row.primary_name);
        assert.equal(mock.calls[0].body.actress_name, undefined, '欄位名必須是 name，不是 actress_name');
    } finally {
        mock.restore();
    }
});

// 21（reviewer②③，MINOR）：被 covered 涵蓋的列，錯誤訊息與錯誤列都不得留下。
// A 404 失敗 → 改點 B，B 的回應 covered_names 涵蓋 A → A 變實心的同時，_libRowError[A] 必須
// 被清空（不只是被 x-show 擋住看不見；資料本身要乾淨，否則之後任何一處直接讀
// _libRowErrorText(A) 而不經過 libRowFavorited 閘門的畫面都會露出殘留紅字）。
test('reviewer②③：A 失敗後被 B 的 covered_names 涵蓋 → A 實心且錯誤訊息／錯誤列都清空', async () => {
    _setActresses([]);
    const rowA = { primary_name: '新ありな', names: ['新ありな'], video_count: 1, is_favorite: false };
    const rowB = { primary_name: '橋本ありな', names: ['橋本ありな', '新ありな'], video_count: 1, is_favorite: false };
    const mock = mockFetchManual();
    try {
        const c = makeComponent();

        // A 先失敗
        c.libEnqueueFavorite(rowA);
        mock.calls[0].resolve({ status: 404, json: async () => ({ error: 'not_found', message: '查無此女優' }) });
        await flushMicrotasks();
        await flushMicrotasks();
        assert.equal(c.libRowState(rowA), 'error');
        assert.equal(c.libRowErrorText(rowA), 'showcase.actress.addNotFound');

        // 改點 B，成功且 covered_names 涵蓋 A
        c.libEnqueueFavorite(rowB);
        mock.calls[1].resolve({
            status: 200,
            json: async () => libFavoritePayload('橋本ありな', { covered_names: ['橋本ありな', '新ありな'] }),
        });
        await flushMicrotasks();
        await flushMicrotasks();

        assert.equal(c.libRowFavorited(rowA), true);
        assert.equal(c.libRowErrorText(rowA), '', '被涵蓋後錯誤訊息必須清空，不能只靠 x-show 擋');
        // 錯誤列 x-show 的兩個條件之一（!libRowFavorited）已為 false，不會顯示——
        // 這裡直接鎖住背後資料，防止未來有人拿掉 template 的 !libRowFavorited 閘門時無聲露餡
        assert.equal(c._libRowError[rowA.primary_name], '');
    } finally {
        mock.restore();
    }
});
