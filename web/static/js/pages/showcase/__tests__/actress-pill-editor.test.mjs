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
import { readFileSync } from 'node:fs';
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
const { buildActressPillPredicate } = await import('../../../shared/actress-pill-filter.js');

// ── matchMedia stub（可控 matches ＋ 記錄 handler 參考）────────────────────

/**
 * @param {boolean} initialMatches  max-width:480px 的初始 matches
 * @returns {{ setMatches: (m: boolean) => void, getPillMq: () => object|null, handlers: {add: Function[], remove: Function[]} }}
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
        getPillMq() {
            for (const [q, mq] of mqsByQuery) {
                if (q.includes('480')) return mq;
            }
            return null;
        },
        getHandlers(queryPart) {
            for (const [q, h] of handlersByQuery) {
                if (q.includes(queryPart)) return h;
            }
            return { add: [], remove: [] };
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

/** 跑 init() 到 matchMedia 註冊完成（stub 掉網路與 Alpine 依賴） */
async function runInit(c, registerCapture) {
    if (registerCapture) {
        globalThis.window.__registerPage = ({ cleanup }) => {
            registerCapture.cleanup = cleanup;
        };
    } else {
        globalThis.window.__registerPage = () => {};
    }
    const origFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
        ok: true,
        json: async () => ({ success: true, videos: [], groups: [] }),
    });
    // 覆寫會打網路／DOM 的方法
    c.restoreState = () => {};
    c.fetchVideos = async () => {};
    c.applyFilterAndSort = () => {};
    c.updatePagination = () => {};
    c.loadActresses = () => {};
    try {
        await c.init();
    } finally {
        globalThis.fetch = origFetch;
        delete globalThis.window.__registerPage;
    }
}

// ── DoD #1：淺拷貝不共享參考（CD-116b-5）──────────────────────────────────

test('DoD#1 _openPillEditor 淺拷貝：改草稿 op 不影響 actressPills[0]', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    const before = { ...c.actressPills[0] };
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor, '草稿應開啟');
    c._pillEditor.op = 'range';
    assert.deepEqual(c.actressPills[0], before, '已套用 pill 逐欄位不變');
    assert.notEqual(c._pillEditor, c.actressPills[0], '草稿不得是同一參考');
});

// ── DoD #2：✗ 不刪除不修改（CD-116b-5 / spec §5.6）────────────────────────

test('DoD#2 開啟→改草稿→_cancelPillEditor → actressPills deepEqual 開啟前', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.op = '<=';
    c._pillEditor.rangeLo = '30';
    c._pillEditor.rangeHi = '40';
    c._cancelPillEditor();
    assert.equal(c._pillEditor, null);
    assert.deepEqual(c.actressPills, before);
});

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

test('DoD#6 _applyPillOp（運算子鈕）→ { value, value2: null }', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    c._applyPillOp('<=');
    assert.deepEqual(c.actressPills[0], {
        dim: 'age', op: '<=', value: '37', value2: null,
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

test('DoD#8 直接餵 lo>hi 的 range pill 給 predicate → 空集合', () => {
    const actresses = [
        { name: 'a', age: 37, height: '160cm', cup: 'B' },
        { name: 'b', age: 25, height: '170cm', cup: 'C' },
        { name: 'c', age: 40, height: '165cm', cup: 'D' },
    ];
    const pred = buildActressPillPredicate([
        { dim: 'height', op: 'range', value: '175', value2: '160' },
    ]);
    const hits = actresses.filter(pred);
    assert.equal(hits.length, 0, 'predicate 不得偷偷對調；lo>hi 應得空集合');
});

// ── DoD #10：_pillPopoverEnabled 在 ≤480px 為 false（CD-116b-8）───────────

test('DoD#10 factory：matchMedia ≤480 matches=true → _pillPopoverEnabled=false', () => {
    installMatchMedia(true); // ≤480
    const c = makeComponent();
    assert.equal(c._pillPopoverEnabled, false);
});

test('DoD#10 factory：matchMedia ≤480 matches=false → _pillPopoverEnabled=true', () => {
    installMatchMedia(false);
    const c = makeComponent();
    assert.equal(c._pillPopoverEnabled, true);
});

// ── DoD #11：_togglePillEditor 在 disabled 時不開啟（第二層防禦）──────────

test('DoD#11 _togglePillEditor 在 _pillPopoverEnabled=false 時不開啟', () => {
    const c = makeComponent();
    c._pillPopoverEnabled = false;
    c.addActressPill('age', 37);
    c._togglePillEditor(c.actressPills[0]);
    assert.equal(c._pillEditor, null);
});

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

test('DoD#12 matchMedia 跨進 ≤480：_pillEditor=null 且 _pillPopoverEnabled=false', async () => {
    mm = installMatchMedia(false); // 先桌機
    const c = makeComponent();
    c._pillPopoverEnabled = true;
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);

    await runInit(c);
    // 模擬跨界
    mm.setMatches(true);
    assert.equal(c._pillPopoverEnabled, false);
    assert.equal(c._pillEditor, null);
});

// ── DoD #13：toggleActressMode 無條件 teardown（CD-116b-8b）───────────────

test('DoD#13 toggleActressMode 後 _pillEditor 恆 null', () => {
    const c = makeComponent({
        showFavoriteActresses: true,
    });
    // teardown 在函式開頭無條件執行；動畫路徑可能觸 DOM，但草稿必須已清
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    try {
        c.toggleActressMode();
    } catch (_) {
        // flipAndFadeIn 的 DOM/動畫副作用不在本 task 範圍；teardown 已在開頭完成
    }
    assert.equal(c._pillEditor, null);
});

// ── DoD #14：removeActressPill dim 命中 teardown（CD-116b-8b）──────────────

test('DoD#14 removeActressPill 移除編輯中 dim → _pillEditor=null', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills.find((p) => p.dim === 'age'));
    assert.equal(c._pillEditor.dim, 'age');
    c.removeActressPill('age', '37');
    assert.equal(c._pillEditor, null);
});

test('DoD#14 removeActressPill 移除其他 dim → _pillEditor 不受影響', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills.find((p) => p.dim === 'age'));
    c.removeActressPill('height', '160');
    assert.ok(c._pillEditor);
    assert.equal(c._pillEditor.dim, 'age');
});

// ── DoD #15：clearAllFilters 無條件 teardown（CD-116b-8b）─────────────────

// 129-T1b：clearAllFilters 依分頁分流之後，這條拆成兩個分支各驗一次。
// teardown 仍是**無條件**（CD-116b-8b 不變），所以兩邊的 `_pillEditor === null` 都要成立；
// 差別在 actressPills——只有女優牆那條會清它，影片牆那條**不准碰**（spec-129 S1）。
test('DoD#15 clearAllFilters 後 _pillEditor=null（女優牆：連 actressPills 一起清）', () => {
    // harness 補 showFavoriteActresses:true —— 這才是可達的真實情境
    //（影片牆上不可能開著女優 pill 浮層）。
    const c = makeComponent({ showFavoriteActresses: true });
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    c.clearAllFilters();
    assert.equal(c._pillEditor, null);
    assert.deepEqual(c.actressPills, []);
});

test('DoD#15b clearAllFilters 後 _pillEditor=null（影片牆：actressPills 不受影響）', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    c.clearAllFilters();
    assert.equal(c._pillEditor, null, 'teardown 無條件：影片牆按 ✕ 也要收掉草稿');
    assert.equal(c.actressPills.length, 1, '影片牆清除不得清掉 actressPills');
});

// ── DoD #16：lifecycle 對稱——同一 handler 參考（plan §2）──────────────────

test('DoD#16 init addEventListener 與 cleanup removeEventListener 用同一 handler 參考', async () => {
    mm = installMatchMedia(false);
    const c = makeComponent();
    const capture = { cleanup: null };
    await runInit(c, capture);

    assert.ok(c._pillMq, '_pillMq 應在 init 後存在');
    assert.ok(c._pillHandler, '_pillHandler 應在 init 後存在');
    assert.equal(typeof c._pillHandler, 'function');

    const pillHandlers = mm.getHandlers('480');
    assert.ok(pillHandlers.add.length >= 1, 'addEventListener 應被呼叫');
    // 最後一次（或唯一一次）註冊的 handler 必須是 this._pillHandler
    const added = pillHandlers.add[pillHandlers.add.length - 1];
    assert.equal(added, c._pillHandler, 'addEventListener 傳入的必須是 _pillHandler 參考');

    assert.ok(capture.cleanup, '__registerPage cleanup 應被註冊');
    capture.cleanup.call(c);

    assert.ok(pillHandlers.remove.length >= 1, 'cleanup 應呼叫 removeEventListener');
    const removed = pillHandlers.remove[pillHandlers.remove.length - 1];
    assert.equal(removed, c._pillHandler, 'removeEventListener 必須傳入與 add 相同的 handler 參考');
    assert.equal(removed, added, 'add 與 remove 的 handler 必須是同一參考');
});

// ── fail-safe：_commitPillEditor 在 null 時不拋錯 ─────────────────────────

test('_commitPillEditor 在 _pillEditor=null 時不拋錯、不寫入', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    const before = structuredClone(c.actressPills);
    assert.doesNotThrow(() => c._commitPillEditor());
    assert.deepEqual(c.actressPills, before);
});

/** 斷言 pill 陣列裡沒有 value/value2 為字面 'null' 或空字串的項目 */
function assertNoNullOrEmptyPillValues(pills, msg) {
    for (const p of pills) {
        assert.notEqual(p.value, 'null', msg || 'value 不得為字面 null');
        assert.notEqual(p.value, '', msg || 'value 不得為空字串');
        if (p.value2 != null) {
            assert.notEqual(p.value2, 'null', msg || 'value2 不得為字面 null');
            assert.notEqual(p.value2, '', msg || 'value2 不得為空字串');
        }
    }
}

// ── 116c-T2 改寫：兩格皆空按 ✓ →（防禦性 return）不寫入、不關閉 ───────────

test('兩格皆空按 ✓ → 不寫入、_pillEditor 仍開（防禦性 return）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '';
    c._pillEditor.rangeHi = '';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before, 'actressPills 不得被改寫');
    assert.ok(c._pillEditor, '_pillEditor 必須維持開啟');
    assertNoNullOrEmptyPillValues(c.actressPills);
});

test('dim=cup 兩格填入非數字（cup 恆走態①，理論路徑防禦）→ _commitPillEditor fail-safe 不寫入', () => {
    const c = makeComponent();
    c.addActressPill('cup', 'B');
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = 'B';
    c._pillEditor.rangeHi = 'C';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before, 'actressPills 不得被改寫（非有限數，兩格都填走 Number.isFinite 驗證）');
    assert.ok(c._pillEditor, '_pillEditor 必須維持開啟（fail-safe）');
    assertNoNullOrEmptyPillValues(c.actressPills);
});

// ── Review fix：searchActressFilms 繞過 toggleActressMode 的 teardown ─────

test('searchActressFilms teardown：呼叫前 _pillEditor 非 null → 呼叫後為 null', async () => {
    // wasActressMode 路徑直接翻旗標、不經 toggleActressMode；fromEl=null 走 early fallback，
    // 不碰 GhostFly / 輪詢 DOM——與 pill-hero 既有 call-site 測試同一可驅動面。
    const c = makeComponent({ showFavoriteActresses: true });
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    await c.searchActressFilms('Foo', null);
    assert.equal(c._pillEditor, null);
});

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

// ── 三態操作數逐格斷言（CD-116c-2 表 × 三顆鈕 ＝ 9 格）────────────────────
// mutation 自驗目標：態③的 '<=' 若被改成取左，這裡唯一一格會轉紅、其餘八格仍綠。

for (const op of ['=', '<=', '>=']) {
    test(`三態①都空：_pillOperandFor('${op}') → pill 目前的值`, () => {
        const c = makeComponent();
        openAgeEditor(c, 30, null, null);
        assert.equal(c._pillOperandFor(op), '30');
    });
}

for (const op of ['=', '<=', '>=']) {
    test(`三態②只填左格：_pillOperandFor('${op}') → 左格（無歧義，op 不影響）`, () => {
        const c = makeComponent();
        openAgeEditor(c, 30, '25', null);
        assert.equal(c._pillOperandFor(op), '25');
    });
}

test("三態③兩格都填：_pillOperandFor('=') → 取左", () => {
    const c = makeComponent();
    openAgeEditor(c, 30, '25', '35');
    assert.equal(c._pillOperandFor('='), '25');
});

test("三態③兩格都填：_pillOperandFor('<=') → 取右", () => {
    const c = makeComponent();
    openAgeEditor(c, 30, '25', '35');
    assert.equal(c._pillOperandFor('<='), '35');
});

test("三態③兩格都填：_pillOperandFor('>=') → 取左", () => {
    const c = makeComponent();
    openAgeEditor(c, 30, '25', '35');
    assert.equal(c._pillOperandFor('>='), '25');
});

// 補強：只填右格（非 9-grid 正式格，驗 hi-only 分支）
test('只填右格：_pillOperandFor 任一鈕 → 右格', () => {
    const c = makeComponent();
    openAgeEditor(c, 30, null, '35');
    for (const op of ['=', '<=', '>=']) {
        assert.equal(c._pillOperandFor(op), '35');
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

test('AC-C7：只左格按 ✓ 與直接按 ≥（同一編輯器狀態）產出逐欄位相同 pill', () => {
    const c1 = makeComponent();
    c1.addActressPill('height', '160cm');
    c1._openPillEditor(c1.actressPills[0]);
    c1._pillEditor.rangeLo = '155';
    c1._commitPillEditor();

    const c2 = makeComponent();
    c2.addActressPill('height', '160cm');
    c2._openPillEditor(c2.actressPills[0]);
    c2._pillEditor.rangeLo = '155';
    c2._applyPillOp('>=');

    assert.deepEqual(c1.actressPills[0], c2.actressPills[0]);
    assert.deepEqual(c1.actressPills[0], { dim: 'height', op: '>=', value: '155', value2: null });
});

test('AC-C7：只右格按 ✓ 與直接按 ≤（同一編輯器狀態）產出逐欄位相同 pill', () => {
    const c1 = makeComponent();
    c1.addActressPill('height', '160cm');
    c1._openPillEditor(c1.actressPills[0]);
    c1._pillEditor.rangeHi = '165';
    c1._commitPillEditor();

    const c2 = makeComponent();
    c2.addActressPill('height', '160cm');
    c2._openPillEditor(c2.actressPills[0]);
    c2._pillEditor.rangeHi = '165';
    c2._applyPillOp('<=');

    assert.deepEqual(c1.actressPills[0], c2.actressPills[0]);
    assert.deepEqual(c1.actressPills[0], { dim: 'height', op: '<=', value: '165', value2: null });
});

// ── AC-C7b：range pill 開啟時三顆鈕不亮（op 仍是 'range'，草稿層驗證）─────

test('AC-C7b：開啟既有 range pill → _pillEditor.op 仍是 range（三顆鈕一顆都不亮的資料前提）', () => {
    const c = makeComponent();
    c._setActressPill({ dim: 'height', op: 'range', value: '155', value2: '165' });
    c._openPillEditor(c.actressPills[0]);
    assert.equal(c._pillEditor.op, 'range');
});

// ── AC-C10 / AC-C11：不夾回、逐字寫入 ──────────────────────────────────────

test('AC-C10/AC-C11 不改寫：180~190（超出庫內範圍）逐字寫入', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '180';
    c._pillEditor.rangeHi = '190';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills[0], { dim: 'height', op: 'range', value: '180', value2: '190' });
});

test('AC-C11 不改寫：左格 250 按 ≤ → value === "250"（不得是 200 或任何館藏邊界）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeHi = '250';
    c._applyPillOp('<=');
    assert.equal(c.actressPills[0].value, '250');
    assert.notEqual(c.actressPills[0].value, '200');
    assert.notEqual(c.actressPills[0].value, '170');
    assert.notEqual(c.actressPills[0].value, '146');
});

// ── CD-116c-4b：正規化（同一數字的另一種寫法）不是夾回（換掉問題）─────────
// 兩者的界線寫在同一支測試裡：height 前導零被既有 parseInt 正規化，
// 但數值本身（250）絕不能被換成館藏邊界。

test('CD-116c-4b：height 0250~300 → value 正規化為 250（既有 parseInt），數值本身不被夾回換掉', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '0250';
    c._pillEditor.rangeHi = '300';
    c._commitPillEditor();
    // 正規化：0250 → 250（同一數字的另一種寫法，走既有 normalizeHeightPillValue/parseInt）
    assert.equal(c.actressPills[0].value, '250');
    assert.equal(c.actressPills[0].value2, '300', '上界逐字寫入，不夾回');
    // 反向鎖：數值本身不得被夾回／換成館藏邊界（200/170/146）
    assert.notEqual(c.actressPills[0].value, '200');
    assert.notEqual(c.actressPills[0].value, '170');
    assert.notEqual(c.actressPills[0].value, '146');
});

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
});

test('P2-#132：height 區間 1e2~1.5e2 → 100~150（value2 對稱）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '1e2';
    c._pillEditor.rangeHi = '1.5e2';
    c._commitPillEditor();
    assert.equal(c.actressPills[0].value, '100');
    assert.equal(c.actressPills[0].value2, '150', 'value2 走同一支正規化，不得只修 value');
});

test('P2-#132 回歸：刮削值 160cm 仍由 extractor 剝單位為 160', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    assert.equal(c.actressPills[0].value, '160', 'Number("160cm") 是 NaN → 原樣交給 extractor');
});

// ── AC-C11b fail-safe：1e999（Infinity）在被選中的那一格 → 不寫入、不關閉 ──
// 四條路徑各驗一次（=／≤／≥／✓）。

test('AC-C11b fail-safe：= 鈕，左格 1e999 → 不寫入、_pillEditor 仍非 null', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '1e999';
    c._applyPillOp('=');
    assert.deepEqual(c.actressPills, before);
    assert.ok(c._pillEditor);
});

test('AC-C11b fail-safe：≥ 鈕，左格 1e999 → 不寫入、_pillEditor 仍非 null', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '1e999';
    c._applyPillOp('>=');
    assert.deepEqual(c.actressPills, before);
    assert.ok(c._pillEditor);
});

test('AC-C11b fail-safe：≤ 鈕，右格 1e999 → 不寫入、_pillEditor 仍非 null', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeHi = '1e999';
    c._applyPillOp('<=');
    assert.deepEqual(c.actressPills, before);
    assert.ok(c._pillEditor);
});

test('AC-C11b fail-safe：✓（兩格都填，其中一格 1e999）→ 不寫入、_pillEditor 仍非 null', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '25';
    c._pillEditor.rangeHi = '1e999';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before);
    assert.ok(c._pillEditor);
});

test('只驗被選中的那一格：左格 1e999、右格合法，按 ≤（取右格）→ 照常套用', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    c._pillEditor.rangeLo = '1e999';
    c._pillEditor.rangeHi = '35';
    c._applyPillOp('<=');
    assert.equal(c._pillEditor, null, '未被選中格不合法不影響此次套用');
    assert.deepEqual(c.actressPills[0], { dim: 'age', op: '<=', value: '35', value2: null });
});

// ── Codex PR review P2-2：badInput（1e999 等 <input type="number"> 無法解析）
// 不得被誤判為「這格是空的」。四種結果對照表（見 review 附的契約表）。
// _pillEditor.badLo/badHi 由 markup @input="$event.target.validity.badInput" 寫入；
// 單元測試無真實 DOM validity，直接設定該布林欄位模擬同樣的狀態。

test('P2-2 表列①：左格壞、右格空，按 ≥/=/≤ → 不寫入、不關閉（不得靜默套用 pill 原值）', () => {
    for (const op of ['>=', '=', '<=']) {
        const c = makeComponent();
        c.addActressPill('height', '160cm');
        const before = structuredClone(c.actressPills);
        c._openPillEditor(c.actressPills[0]);
        // <input type="number"> 對無法解析的輸入把 .value 逼成空字串（真實瀏覽器行為，
        // x-model 綁的就是這個值）；validity.badInput 才是「使用者確實打了東西」的唯一線索。
        c._pillEditor.rangeLo = '';
        c._pillEditor.badLo = true;
        c._pillEditor.rangeHi = '';
        c._applyPillOp(op);
        assert.deepEqual(c.actressPills, before, `op=${op}：actressPills 不得被改寫`);
        assert.ok(c._pillEditor, `op=${op}：_pillEditor 必須維持開啟`);
    }
});

test('P2-2 表列②：左格壞、右格 165，按 ✓ → 不寫入、不關閉（不得誤判成「只有右格」而套用 ≤165）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    // <input type="number"> 對無法解析的輸入把 .value 逼成空字串（真實瀏覽器行為，
    // x-model 綁的就是這個值）；validity.badInput 才是「使用者確實打了東西」的唯一線索。
    c._pillEditor.rangeLo = '';
    c._pillEditor.badLo = true;
    c._pillEditor.rangeHi = '165';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before, 'actressPills 不得被改寫');
    assert.ok(c._pillEditor, '_pillEditor 必須維持開啟');
});

test('P2-2 表列③：左格壞、右格 165，按 ≤ → 照常套用 ≤165（取右格，合法；壞的左格不影響）', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    // <input type="number"> 對無法解析的輸入把 .value 逼成空字串（真實瀏覽器行為，
    // x-model 綁的就是這個值）；validity.badInput 才是「使用者確實打了東西」的唯一線索。
    c._pillEditor.rangeLo = '';
    c._pillEditor.badLo = true;
    c._pillEditor.rangeHi = '165';
    c._applyPillOp('<=');
    assert.equal(c._pillEditor, null, '取右格合法 → 應正常套用並關閉');
    assert.deepEqual(c.actressPills[0], { dim: 'height', op: '<=', value: '165', value2: null });
});

test('P2-2 表列④：左格壞、右格 165，按 =/≥ → 不寫入、不關閉（被選中的是壞的左格）', () => {
    for (const op of ['=', '>=']) {
        const c = makeComponent();
        c.addActressPill('height', '160cm');
        const before = structuredClone(c.actressPills);
        c._openPillEditor(c.actressPills[0]);
        // <input type="number"> 對無法解析的輸入把 .value 逼成空字串（真實瀏覽器行為，
        // x-model 綁的就是這個值）；validity.badInput 才是「使用者確實打了東西」的唯一線索。
        c._pillEditor.rangeLo = '';
        c._pillEditor.badLo = true;
        c._pillEditor.rangeHi = '165';
        c._applyPillOp(op);
        assert.deepEqual(c.actressPills, before, `op=${op}：actressPills 不得被改寫`);
        assert.ok(c._pillEditor, `op=${op}：_pillEditor 必須維持開啟`);
    }
});

test('P2-2：修好壞輸入後恢復正常套用（badLo 由 @input handler 每次覆寫，修正後應為 false）', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    // 先打壞
    // <input type="number"> 對無法解析的輸入把 .value 逼成空字串（真實瀏覽器行為，
    // x-model 綁的就是這個值）；validity.badInput 才是「使用者確實打了東西」的唯一線索。
    c._pillEditor.rangeLo = '';
    c._pillEditor.badLo = true;
    c._applyPillOp('=');
    assert.ok(c._pillEditor, '壞輸入時不應套用');
    // 修好：markup 的 @input 每次都寫當下的 validity.badInput，修好後應變回 false
    c._pillEditor.rangeLo = '28';
    c._pillEditor.badLo = false;
    c._applyPillOp('=');
    assert.equal(c._pillEditor, null, '修好後應正常套用並關閉');
    assert.deepEqual(c.actressPills[0], { dim: 'age', op: '=', value: '28', value2: null });
});

// ── _applyPillOp 之後 _pillEditor === null（AC-C3 的狀態層形式）───────────

test('_applyPillOp 之後 _pillEditor === null', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    c._applyPillOp('=');
    assert.equal(c._pillEditor, null);
});

// ── _pillEditorHasRangeInput：✓✗ 顯示條件，即時反映輸入內容 ────────────────

test('_pillEditorHasRangeInput：_pillEditor=null → false', () => {
    const c = makeComponent();
    assert.equal(c._pillEditorHasRangeInput(), false);
});

test('_pillEditorHasRangeInput：即時反映輸入內容（打字出現、刪光消失）', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    assert.equal(c._pillEditorHasRangeInput(), false, '開場空白 → false');
    c._pillEditor.rangeLo = '2';
    assert.equal(c._pillEditorHasRangeInput(), true, '左格有字 → true');
    c._pillEditor.rangeLo = '';
    assert.equal(c._pillEditorHasRangeInput(), false, '刪光 → 再次 false');
    c._pillEditor.rangeHi = '   ';
    assert.equal(c._pillEditorHasRangeInput(), false, '純空白視為空');
    c._pillEditor.rangeHi = '5';
    assert.equal(c._pillEditorHasRangeInput(), true, '右格有字 → true');
});

// ── _pillDimRangeHint：null 安全 ＋ cup 恆空 ＋ 庫內實際範圍 ────────────────

test('_pillDimRangeHint：_pillEditor=null 時回 "" 且不拋錯', () => {
    const c = makeComponent();
    assert.doesNotThrow(() => c._pillDimRangeHint());
    assert.equal(c._pillDimRangeHint(), '');
});

test('_pillDimRangeHint：cup 回 ""', () => {
    const c = makeComponent();
    c.addActressPill('cup', 'B');
    c._openPillEditor(c.actressPills[0]);
    assert.equal(c._pillDimRangeHint(), '');
});

test('_pillDimRangeHint：age/height 回「（min ~ max）」（庫內實際範圍）', () => {
    const c = makeComponent();
    // makeComponent 種子女優：full age37/height160、tall age25/height170、short age40/height155
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    assert.equal(c._pillDimRangeHint(), '（25 ~ 40）');

    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills.find((p) => p.dim === 'height'));
    assert.equal(c._pillDimRangeHint(), '（155 ~ 170）');
});

// ── 提示絕不參與比對（spec-116c §3.5 末句可證偽形式）───────────────────────

test('提示絕不參與比對：掛 ≤100cm 超出庫內範圍的 pill → 結果為空集合', () => {
    const c = makeComponent();
    c._setActressPill({ dim: 'height', op: '<=', value: '100', value2: null });
    assert.equal(c.filteredActressCount, 0, '若提示值偷偷被拿去夾回，這裡會篩出 146cm 那群人');
});

// ── 刪除的東西真的不在了（允許字面比對——驗死碼，不是契約）─────────────────

test('刪除的東西真的不在了：6 常數 ＋ _setEditorMode ＋ _pillRangeBounds 在 state-actress.js 全檔零出現', () => {
    const src = readFileSync(
        path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../state-actress.js'),
        'utf8',
    );
    const deletedTokens = [
        'AGE_MIN', 'AGE_MAX', 'AGE_SEED_WIDTH',
        'HEIGHT_MIN', 'HEIGHT_MAX', 'HEIGHT_SEED_WIDTH',
        '_setEditorMode', '_pillRangeBounds',
    ];
    for (const token of deletedTokens) {
        assert.ok(!src.includes(token), `${token} 不得殘留在 state-actress.js`);
    }
});
