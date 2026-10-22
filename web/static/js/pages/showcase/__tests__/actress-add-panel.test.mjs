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


function flushMicrotasks() {
    return new Promise((r) => setImmediate(r));
}

// ── AC-1.3 / AC-1.6：開啟即載入、不等網路 ─────────────────────────────────


// ── 載入失敗 / 空庫 / gen guard ────────────────────────────────────────────


// 既有 stale test 先 resolve 新輪再 resolve 舊輪：舊 finally 跑到時 loading 已是 false，
// 拿掉 finally 的 gen guard 仍全綠。本支讓舊輪先落地、新輪仍飛，才鎖得住「舊 finally 不得關新 loading」。

// ── AC-2.1 / AC-2.2 / AC-3.2 ───────────────────────────────────────────────


// ── AC-5.x 過濾 ────────────────────────────────────────────────────────────

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

// ── AC-6.x 分批 ────────────────────────────────────────────────────────────


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

// 4. INV-2b：出隊重檢（enqueue 檢查擋不住——B 入隊時 A 還沒回）

// 5. INV-3：排空保證（全失敗也要歸零）

// 6. AC-4.6：covered_names 涵蓋整組別名

// 8. 409 視為成功

// 9. 404：可重試

// 11. 其他（500 / success:false / fetch reject）→ add_failed

// 12. AC-4.4：重套篩選，不強制顯示

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

// 16a. 重開清 error、保留 queued/loading（_libCovered 的行為拆到 16b，見 CD-117-9）

// 16b. CD-117-9（Codex PR review P2，已查證屬實並修正）：_libCovered 必須隨重開回到空心。
// 舊版本這裡曾釘住「_libCovered 重開後仍是 true」（相反行為），與 plan-117.md CD-117-9
// 明文承諾的「關閉再開回到空心」矛盾——只靠 ∪{req.name} 聯集覆蓋、alias 表根本不認得的
// 名字，會在整個分頁存活期間永久顯示實心、使用者永遠點不到那個收藏入口。
test('CD-117-9：重開面板後 _libCovered 回到空心，僅靠聯集覆蓋的名字可以再次點擊', () => {
    const restore = mockFetchOk({ success: true, actresses: [], total: 0 });
    try {
        const row = { primary_name: '涵蓋優', names: ['涵蓋優'], video_count: 1, is_favorite: false };
        const c = makeComponent({ _libCovered: { '涵蓋優': true } });
        assert.equal(c.libRowFavorited(row), true, '重開前：僅靠聯集覆蓋仍算實心');

        c.openActressAddPanel();

        assert.deepEqual(c._libCovered, {}, 'openActressAddPanel 必須同步清空 _libCovered');
        assert.equal(c.libRowFavorited(row), false, '重開後：磁碟真相判定，允許再次點擊');
    } finally {
        restore();
    }
});

// 16c. 迴歸守衛：重開清空 _libCovered 之後，「重開前」就已送出、還沒收到回應的收藏請求，
// 落地時仍要能正確把名字標進（重開後的）_libCovered——reset 不得吃掉隨後才到的合法回應。

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

// ── 117b-T10：libAddBtnVisible 顯示條件（CD-117b-8 / AC-10.3 / AC-10.8）──

test('libAddBtnVisible：顯示條件表（全空／有打字有結果／有打字無結果／有 pill 有結果／影片模式）', () => {
    const cases = [
        // [說明, 狀態, 期望]
        ['女優模式 ＋ 搜尋列全空', { showFavoriteActresses: true, actressSearch: '', actressPills: [], filteredActressCount: 12 }, true],
        ['女優模式 ＋ 有打字 ＋ 有結果', { showFavoriteActresses: true, actressSearch: '三上', actressPills: [], filteredActressCount: 3 }, false],
        ['女優模式 ＋ 有打字 ＋ 結果 0', { showFavoriteActresses: true, actressSearch: '庫裡沒有的名字', actressPills: [], filteredActressCount: 0 }, true],
        ['女優模式 ＋ 有 pill ＋ 有結果', { showFavoriteActresses: true, actressSearch: '', actressPills: [{ dim: 'age', op: '=', value: '28', value2: null }], filteredActressCount: 5 }, false],
        ['影片模式（無打字）', { showFavoriteActresses: false, actressSearch: '', actressPills: [], filteredActressCount: 0 }, false],
        ['影片模式（有打字、結果 0）', { showFavoriteActresses: false, actressSearch: 'x', actressPills: [], filteredActressCount: 0 }, false],
    ];
    for (const [label, state, expected] of cases) {
        assert.equal(makeComponent(state).libAddBtnVisible(), expected, label);
    }
});

