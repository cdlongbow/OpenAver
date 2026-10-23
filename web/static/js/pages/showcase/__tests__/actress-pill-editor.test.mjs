// TASK-116b-T2 / 116c-T2: 浮層狀態機（_pillEditor / 斷點閘 / 三顆鈕即點即套 / 三態操作數 /
// ✓ 的單邊委派 / 對調保留）。零 markup、零 CSS。
//
// 116c-T2：夾回／種子／_setEditorMode／_pillRangeBounds 整組刪除（CD-116c-4）。
// 提交模型改為「三顆運算子鈕即點即套（_applyPillOp）＋ 自訂區間列的 ✓（_commitPillEditor 委派）」。
//
// state-actress.js / state-base.js 用瀏覽器 importmap 別名；plain node --test 不認得。
// 比照 actress-pill-state.test.mjs，本檔自帶 resolve hook（FE-GUARD-11）。

import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.Alpine = globalThis.Alpine || {
    store: () => ({ toolbarOpen: false, showcaseHasSearch: false }),
};
if (typeof globalThis.localStorage === 'undefined') {
    const _store = Object.create(null);
    globalThis.localStorage = {
        getItem: (k) => (k in _store ? _store[k] : null),
        setItem: (k, v) => { _store[k] = String(v); },
        removeItem: (k) => { delete _store[k]; },
    };
}
if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
}
// init() 註冊 scroll listener；toggleActressMode 的 flipAndFadeIn 讀 document
if (typeof globalThis.window.addEventListener !== 'function') {
    globalThis.window.addEventListener = () => {};
    globalThis.window.removeEventListener = () => {};
}
// TASK-138-T6：searchActressFilms / flipAndFadeIn 呼叫 window.scrollTo(0, 0)
if (typeof globalThis.window.scrollTo !== 'function') {
    globalThis.window.scrollTo = () => {};
}
if (typeof globalThis.document === 'undefined') {
    globalThis.document = {
        querySelector: () => null,
        body: { classList: { add() {}, remove() {} } },
    };
}
if (typeof globalThis.window.scrollY === 'undefined') {
    globalThis.window.scrollY = 0;
}

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
// 本檔：web/static/js/pages/showcase/__tests__/ → 上三層 = web/static/js/
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
const { stateBase, _setActresses } = await import('../state-base.js');
const { stateVideos } = await import('../state-videos.js');

// ── matchMedia stub（可控 matches ＋ 記錄 handler 參考）────────────────────

/**
 * @param {boolean} initialMatches  max-width:480px 的初始 matches
 * @returns {{ setMatches: (m: boolean) => void }}
 */
function installMatchMedia(initialMatches) {
    const handlersByQuery = new Map();
    const mqsByQuery = new Map();

    function makeMq(query, matches) {
        const listeners = [];
        const mq = {
            matches,
            media: query,
            addEventListener(type, handler) {
                if (type === 'change') {
                    listeners.push(handler);
                    handlersByQuery.get(query)?.add.push(handler);
                }
            },
            removeEventListener(type, handler) {
                if (type === 'change') {
                    handlersByQuery.get(query)?.remove.push(handler);
                    const i = listeners.indexOf(handler);
                    if (i >= 0) listeners.splice(i, 1);
                }
            },
            _listeners: listeners,
            _dispatch(newMatches) {
                this.matches = newMatches;
                for (const h of listeners.slice()) {
                    h({ matches: newMatches, media: query });
                }
            },
        };
        return mq;
    }

    // 預建常見 query 的 mq 實例（init 會對 480 / 899 / 960 各呼叫一次）
    function mqFor(query) {
        if (!mqsByQuery.has(query)) {
            let matches = false;
            if (query.includes('max-width: 480') || query.includes('max-width:480')) {
                matches = initialMatches;
            }
            handlersByQuery.set(query, { add: [], remove: [] });
            mqsByQuery.set(query, makeMq(query, matches));
        }
        return mqsByQuery.get(query);
    }

    globalThis.window.matchMedia = (query) => mqFor(query);

    return {
        setMatches(m) {
            // 更新所有 480px mq 並 dispatch
            for (const [q, mq] of mqsByQuery) {
                if (q.includes('480')) {
                    mq._dispatch(m);
                }
            }
        },
    };
}

// 預設桌機（>480）
let mm = installMatchMedia(false);

beforeEach(() => {
    mm = installMatchMedia(false);
});

/**
 * 合併 stateBase + stateActress + stateVideos 的 harness。
 * $persist stub 比照 actress-pill-state.test.mjs。
 */
function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const actress = stateActress();
    const videos = stateVideos();
    const c = Object.assign({}, base, actress, videos, {
        actressSearch: '',
        actressSort: 'video_count',
        actressOrder: 'desc',
        sortFlipCalls: 0,
        lightboxOpen: false,
        closeLightbox() {},
        saveState() {},
        _clearPreciseMatch() {},
        _reconcileHeroCard() {},
        _animateFilter() {},
        _getActiveGrid() { return null; },
        _resetPicker() {},
        _resetMask() {},
        $nextTick(fn) { if (typeof fn === 'function') fn(); },
        $watch() {},
        _sortWithFlip(fn) {
            c.sortFlipCalls++;
            if (typeof fn === 'function') fn();
        },
    }, overrides);
    if (!Array.isArray(c.actressPills)) c.actressPills = [];
    if (!Array.isArray(c.pills)) c.pills = [];
    _setActresses([
        { name: 'full', age: 37, height: '160cm', cup: 'B' },
        { name: 'tall', age: 25, height: '170cm', cup: 'C' },
        { name: 'short', age: 40, height: '155cm', cup: 'A' },
    ]);
    return c;
}


// ── DoD #2：✗ 不刪除不修改（CD-116b-5 / spec §5.6）────────────────────────


// ── DoD #6：提交映射（116c-T2 改寫：_setEditorMode 已刪除，改走新提交路徑）──

test('DoD#6 自訂區間列 ✓，兩格都填 → { value: lo, value2: hi }', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '150';
    c._pillEditor.rangeHi = '170';
    c._commitPillEditor();
    assert.equal(c._pillEditor, null);
    assert.deepEqual(c.actressPills[0], {
        dim: 'height', op: 'range', value: '150', value2: '170',
    });
});

// ── DoD #7：lo > hi 提交自動對調（spec-116 §5.5，116c-T2 明文保留）─────────

test('DoD#7 lo>hi 提交自動對調：175/160 → value=160 value2=175', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '175';
    c._pillEditor.rangeHi = '160';
    c._commitPillEditor();
    assert.equal(c.actressPills[0].value, '160');
    assert.equal(c.actressPills[0].value2, '175');
    assert.equal(c.actressPills[0].op, 'range');
});

// ── DoD #8：對調單一所有者——predicate 不再對調（CD-116b-13）──────────────


// ── DoD #11：_togglePillEditor 在 disabled 時不開啟（第二層防禦）──────────

test('DoD#11 _togglePillEditor 桌機可開、再點同 dim 關閉', () => {
    const c = makeComponent();
    c._pillPopoverEnabled = true;
    c.addActressPill('age', 37);
    c._togglePillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    assert.equal(c._pillEditor.dim, 'age');
    c._togglePillEditor(c.actressPills[0]);
    assert.equal(c._pillEditor, null);
});

// ── DoD #12：matchMedia change → teardown（CD-116b-8b）────────────────────


// ── DoD #13：toggleActressMode 無條件 teardown（CD-116b-8b）───────────────


// ── DoD #14：removeActressPill dim 命中 teardown（CD-116b-8b）──────────────


// ── DoD #15：clearAllFilters 無條件 teardown（CD-116b-8b）─────────────────

// 129-T1b：clearAllFilters 依分頁分流之後，這條拆成兩個分支各驗一次。
// teardown 仍是**無條件**（CD-116b-8b 不變），所以兩邊的 `_pillEditor === null` 都要成立；

// ── 116c-T2 改寫：兩格皆空按 ✓ →（防禦性 return）不寫入、不關閉 ───────────


// ── Review fix：searchActressFilms 繞過 toggleActressMode 的 teardown ─────


// ═══════════════════════════════════════════════════════════════════════════
// 116c-T2 新增：三顆鈕即點即套 ＋ 三態操作數 ＋ ✓ 委派 ＋ 不改寫 ＋ fail-safe
// ═══════════════════════════════════════════════════════════════════════════

/** 開啟 age dim 編輯器並直接設 rangeLo/rangeHi（不經 _setEditorMode，已刪除） */
function openAgeEditor(c, value, rangeLo, rangeHi) {
    c.addActressPill('age', value);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = rangeLo;
    c._pillEditor.rangeHi = rangeHi;
    return c._pillEditor;
}

// ── 三態操作數（CD-116c-2 表 × 三顆鈕，表驅動）────────────
// mutation 自驗目標：態③的 '<=' 若被改成取左，表中唯一一列會轉紅。

test('三態操作數表（CD-116c-2：①都空／②只填一格／③兩格都填 × 三顆鈕）→ 取哪一格的值', () => {
    // [pill 目前的值, 左格, 右格, op, 期望操作數]；期望值手寫字面
    const cases = [
        [30, null, null, '=', '30'], [30, null, null, '<=', '30'], [30, null, null, '>=', '30'],
        [30, '25', null, '=', '25'], [30, '25', null, '<=', '25'], [30, '25', null, '>=', '25'],
        [30, '25', '35', '=', '25'], [30, '25', '35', '<=', '35'], [30, '25', '35', '>=', '25'],
        [30, null, '35', '=', '35'], [30, null, '35', '<=', '35'], [30, null, '35', '>=', '35'],
    ];
    for (const [v, lo, hi, op, want] of cases) {
        const c = makeComponent();
        openAgeEditor(c, v, lo, hi);
        assert.equal(c._pillOperandFor(op), want, `lo=${lo} hi=${hi} op=${op}`);
    }
});

// 補強（review finding）：cup 是唯一沒有自訂區間列的維度，恆走態①，且 _pillOperandOk
// 對它刻意跳過 Number.isFinite（'B' 不是數字）。那條分支破了的症狀是：按 ≤ 罩杯完全沒
// 反應、浮層不關、畫面零回饋——而 9-grid 全走 age，抓不到。
test('cup 態①：三顆鈕各自套用「pill 目前的值」並關閉編輯器（_pillOperandOk 不得對 B 跑 Number.isFinite）', () => {
    for (const op of ['=', '<=', '>=']) {
        const c = makeComponent();
        c.addActressPill('cup', 'B');
        c._openPillEditor(c.actressPills[0]);
        assert.equal(c._pillOperandFor(op), 'B', `cup 態① 操作數應為 'B'（op=${op}）`);
        c._applyPillOp(op);
        assert.deepEqual(c.actressPills, [{ dim: 'cup', op: op, value: 'B', value2: null }]);
        assert.equal(c._pillEditor, null, '套用後應關閉浮層');
    }
});

// ── AC-C7：✓ 的單邊語意與直接按運算子鈕逐欄位相同（CD-116c-3 委派）────────
// mutation 自驗目標：_commitPillEditor 若不再委派而自組 { op:'range', value2:null }，
// 這兩條必須轉紅。

test('AC-C7：單邊填入按 ✓ 與直接按對應運算子（同一編輯器狀態）產出逐欄位相同 pill', () => {
    // [填的格, 值, 對應運算子, 期望 pill]
    const cases = [
        ['rangeLo', '155', '>=', { dim: 'height', op: '>=', value: '155', value2: null }],
        ['rangeHi', '165', '<=', { dim: 'height', op: '<=', value: '165', value2: null }],
    ];
    for (const [field, val, op, want] of cases) {
        const c1 = makeComponent();
        c1.addActressPill('height', '160cm');
        c1._openPillEditor(c1.actressPills[0]);
        c1._pillEditor[field] = val;
        c1._commitPillEditor();

        const c2 = makeComponent();
        c2.addActressPill('height', '160cm');
        c2._openPillEditor(c2.actressPills[0]);
        c2._pillEditor[field] = val;
        c2._applyPillOp(op);

        assert.deepEqual(c1.actressPills[0], c2.actressPills[0], field);
        assert.deepEqual(c1.actressPills[0], want, field);
    }
});

// ── AC-C10 / AC-C11：不夾回、逐字寫入 ──────────────────────────────────────


// ── Codex PR review P2（#132）：科學記法不得被 parseInt 吃成數量級錯誤的值 ──
// `<input type="number">` 接受 `1e2`（badInput=false、Number() 得 100），
// 但 parseInt('1e2') 在 e 就停 → 1。最惡的是 ≥：牆上一個人都不會少，
// 使用者以為篩選沒作用，而他打的 100 已經變成 1。

test('P2-#132：height ≥ 鈕，1e2 → value 100（不得是 1）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '1e2';
    c._applyPillOp('>=');
    assert.equal(c.actressPills[0].op, '>=');
    assert.equal(c.actressPills[0].value, '100', '1e2 是 100，不是 1');
    assert.notEqual(c.actressPills[0].value, '1');
    // 區間對稱：value2 走同一支正規化
    const c2 = makeComponent();
    c2.addActressPill('height', '160cm');
    c2._openPillEditor(c2.actressPills[0]);
    c2._pillEditor.rangeLo = '1e2';
    c2._pillEditor.rangeHi = '1.5e2';
    c2._commitPillEditor();
    assert.equal(c2.actressPills[0].value, '100');
    assert.equal(c2.actressPills[0].value2, '150', 'value2 對稱');
});


// ── AC-C11b fail-safe：1e999（Infinity）在被選中的那一格 → 不寫入、不關閉 ──
// 四條路徑各驗一次（=／≤／≥／✓）。


// ── Codex PR review P2-2：badInput（1e999 等 <input type="number"> 無法解析）
// 不得被誤判為「這格是空的」。四種結果對照表（見 review 附的契約表）。
// _pillEditor.badLo/badHi 由 markup @input="$event.target.validity.badInput" 寫入；
// 單元測試無真實 DOM validity，直接設定該布林欄位模擬同樣的狀態。


// ── _pillDimRangeHint：庫內實際範圍 ────────────


// ── 提示絕不參與比對（spec-116c §3.5 末句可證偽形式）───────────────────────

test('提示絕不參與比對：掛 ≤100cm 超出庫內範圍的 pill → 結果為空集合', () => {
    const c = makeComponent();
    c._setActressPill({ dim: 'height', op: '<=', value: '100', value2: null });
    assert.equal(c.filteredActressCount, 0, '若提示值偷偷被拿去夾回，這裡會篩出 146cm 那群人');
});
