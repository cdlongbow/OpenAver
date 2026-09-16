// TASK-149b-T3 ⓪′: loadActresses() 並行 dedup／重試／三個失敗出口清理契約（CD-149b-2）
//
// 修法背景：舊版 loadActresses() 每次呼叫都無條件發一次 fetch，且三個失敗出口各自複製貼上
// 清理邏輯、卻沒有清空 _lbActorAges（尚不存在的欄位）也沒有明確呼叫 _setActressesLoaded(false)。
// 149b-T3 把它改成：① module-level in-flight promise dedup ② _setActressesLoaded(true) 從
// finally 移到成功路徑 ③ 三個失敗出口統一清理 + 明確 _setActressesLoaded(false) + 清空
// this._lbActorAges。本檔驗這三件事的 runtime 語意（node:test，非 CDP）。
//
// 範本：actress-add-panel.test.mjs（FE-GUARD-11：window stub + importmap resolve hook）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage。FE-GUARD-11：第一段就要有。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
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
// 117-T5：_actresses / _filteredActresses 是 module-level 共享陣列（測試間互相污染）——
// 每個測試前都要重置。_actressesLoaded 走 setter；讀取用 live binding（同一模組實例）。
const stateBase = await import('../state-base.js');
const { _actresses, _filteredActresses, _setActresses } = stateBase;

function resetActresses() {
    _actresses.length = 0;
    _filteredActresses.length = 0;
}

/** 元件不合併 stateLightbox()（8+ 個既有測試檔的既有慣例，CD-149b-6：state-actress.js 的
 *  刷新點必須用 `?.`，不能裸呼叫，這裡故意不提供 _refreshLbActorAges 來驗證這一點）。
 *  $nextTick 給 no-op（不呼叫傳入的 fn）：production 進場動畫分支需要 requestAnimationFrame
 *  （Node 沒有）與 _getActiveGrid()（屬 state-videos.js，本測試不合併），與本檔驗證目標無關。
 *  _lbActorAges 預先塞一個「上一次成功算出的舊值」，驗證失敗出口會把它清空。 */
function makeComponent(overrides = {}) {
    return Object.assign({}, stateActress(), {
        showToast() {},
        showFavoriteActresses: false,
        $nextTick() {},
        _lbActorAges: { stale: 99 },
        ...overrides,
    });
}

// production loadActresses() 成功路徑會 await _loadAliasMap()（獨立 fetch('/api/actress-aliases')，
// state-base.js 冪等快取在 _aliasMapLoaded，跨測試殘留）。這支 mock 只序列化／計數 '/api/actresses'
// 那個目標端點，alias-map 端點另給一個固定的良性回應，不污染本檔要驗的計數斷言。
function mockFetchSequence(handlers) {
    const prev = globalThis.fetch;
    let i = 0;
    const calls = [];
    globalThis.fetch = async (url, opts) => {
        if (url === '/api/actress-aliases') {
            return { ok: true, status: 200, json: async () => ({ groups: [] }) };
        }
        calls.push([url, opts]);
        const h = handlers[Math.min(i, handlers.length - 1)];
        i += 1;
        return h(url, opts);
    };
    return { restore() { globalThis.fetch = prev; }, calls };
}

function okResp(actresses) {
    const list = actresses || [];
    return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, actresses: list, total: list.length }),
    };
}
function notOkResp() {
    return { ok: false, status: 500, json: async () => ({}) };
}
function successFalseResp() {
    return { ok: true, status: 200, json: async () => ({ success: false }) };
}

// ── 邊界條件 1：並行 dedup ──────────────────────────────────────────────

test('並行 dedup：連續同步呼叫兩次 loadActresses() → fetch 只發生 1 次，兩個呼叫方都拿到同一份結果', async () => {
    resetActresses();
    const mock = mockFetchSequence([() => okResp([{ name: 'A', birth: '1990-01-01' }])]);
    try {
        const c = makeComponent();
        const p1 = c.loadActresses();
        const p2 = c.loadActresses();
        await Promise.all([p1, p2]);
        assert.equal(mock.calls.length, 1, 'fetch 應只發生一次（in-flight promise dedup）');
        assert.equal(_actresses.length, 1);
    } finally {
        mock.restore();
    }
});

// ── 邊界條件 2：settle 後清回 null，第三次呼叫要真的重試 ──────────────────

test('loadActresses retries with a second fetch after the in-flight promise settles on failure', async () => {
    resetActresses();
    const mock = mockFetchSequence([
        () => notOkResp(),
        () => okResp([{ name: 'B', birth: '1990-01-01' }]),
    ]);
    try {
        const c = makeComponent();
        await c.loadActresses(); // 第一次：失敗並 settle
        await c.loadActresses(); // in-flight promise 已在 finally 清回 null → 必須是新的 fetch
        assert.equal(mock.calls.length, 2, '第二次呼叫必須產生第二次 fetch，不能卡在已 settle 的舊 promise');
        assert.equal(_actresses.length, 1);
        assert.equal(_actresses[0].name, 'B');
    } finally {
        mock.restore();
    }
});

// ── 邊界條件 3：三個失敗出口各自的清理契約 ────────────────────────────────

test('失敗出口 !resp.ok：_actressesLoaded===false、_actresses.length===0、_lbActorAges 清空', async () => {
    resetActresses();
    _setActresses([{ name: 'stale', birth: '1990-01-01' }]);
    const mock = mockFetchSequence([() => notOkResp()]);
    try {
        const c = makeComponent();
        await c.loadActresses();
        assert.equal(stateBase._actressesLoaded, false);
        assert.equal(_actresses.length, 0);
        assert.deepEqual(c._lbActorAges, {});
    } finally {
        mock.restore();
    }
});

test('失敗出口 !data.success：_actressesLoaded===false、_actresses.length===0、_lbActorAges 清空', async () => {
    resetActresses();
    _setActresses([{ name: 'stale', birth: '1990-01-01' }]);
    const mock = mockFetchSequence([() => successFalseResp()]);
    try {
        const c = makeComponent();
        await c.loadActresses();
        assert.equal(stateBase._actressesLoaded, false);
        assert.equal(_actresses.length, 0);
        assert.deepEqual(c._lbActorAges, {});
    } finally {
        mock.restore();
    }
});

test('失敗出口 catch（fetch throw）：_actressesLoaded===false、_actresses.length===0、_lbActorAges 清空', async () => {
    resetActresses();
    _setActresses([{ name: 'stale', birth: '1990-01-01' }]);
    const prev = globalThis.fetch;
    globalThis.fetch = async () => { throw new Error('network down'); };
    try {
        const c = makeComponent();
        await c.loadActresses();
        assert.equal(stateBase._actressesLoaded, false);
        assert.equal(_actresses.length, 0);
        assert.deepEqual(c._lbActorAges, {});
    } finally {
        globalThis.fetch = prev;
    }
});
