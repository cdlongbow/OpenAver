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
