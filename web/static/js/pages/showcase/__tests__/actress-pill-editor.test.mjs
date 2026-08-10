// TASK-116b-T2: 浮層狀態機（_pillEditor / 斷點閘 / 提交與取消 / 區間對調與種子值）。
// 零 markup、零 CSS。16 條 DoD 行為斷言。
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

// ── DoD #3：首次切入 range 種子值 ＋ value 不改 ＋ 夾回（CD-116b-5/12）─────

test('DoD#3 _setEditorMode(range) 首次：age 種子 ±3 且 value 不改', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.equal(c._pillEditor.value, '37');
    c._setEditorMode('range');
    assert.equal(c._pillEditor.op, 'range');
    assert.equal(c._pillEditor.value, '37', 'value 本身不被改寫');
    assert.equal(c._pillEditor.rangeLo, '34'); // 37-3
    assert.equal(c._pillEditor.rangeHi, '40'); // 37+3
});

test('DoD#3 height 種子 ±5', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    assert.equal(c._pillEditor.rangeLo, '155');
    assert.equal(c._pillEditor.rangeHi, '165');
    assert.equal(c._pillEditor.value, '160');
});

test('DoD#3 種子值夾回：age 79 → 76–80（max=80）', () => {
    const c = makeComponent();
    c._setActressPill({ dim: 'age', op: '=', value: '79', value2: null });
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    assert.equal(c._pillEditor.rangeLo, '76');
    assert.equal(c._pillEditor.rangeHi, '80');
});

test('DoD#3 種子值夾回：age 19 → 18–22（min=18）', () => {
    const c = makeComponent();
    c._setActressPill({ dim: 'age', op: '=', value: '19', value2: null });
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    assert.equal(c._pillEditor.rangeLo, '18');
    assert.equal(c._pillEditor.rangeHi, '22');
});

test('DoD#3 cup+range fail-closed：不種子、不拋錯', () => {
    const c = makeComponent();
    c.addActressPill('cup', 'B');
    c._openPillEditor(c.actressPills[0]);
    assert.doesNotThrow(() => c._setEditorMode('range'));
    assert.equal(c._pillEditor.op, 'range');
    assert.equal(c._pillEditor.rangeLo, null);
    assert.equal(c._pillEditor.rangeHi, null);
    assert.equal(c._pillEditor.value, 'B');
});

// ── DoD #4：冪等 range → = → range（不重新種子）──────────────────────────

test('DoD#4 range→=→range：第二次 rangeLo/Hi 與第一次相同', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    // 使用者改過邊界
    c._pillEditor.rangeLo = '150';
    c._pillEditor.rangeHi = '170';
    const firstLo = c._pillEditor.rangeLo;
    const firstHi = c._pillEditor.rangeHi;
    c._setEditorMode('=');
    c._setEditorMode('range');
    assert.equal(c._pillEditor.rangeLo, firstLo);
    assert.equal(c._pillEditor.rangeHi, firstHi);
});

// ── DoD #5：冪等 = → range → =（value 不被下界覆寫）───────────────────────

test('DoD#5 =→range→=：最終 value 與開啟時逐字相同', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    const openValue = c._pillEditor.value;
    assert.equal(openValue, '160');
    c._setEditorMode('range');
    assert.equal(c._pillEditor.rangeLo, '155');
    c._setEditorMode('=');
    assert.equal(c._pillEditor.value, openValue, 'value 不得被 rangeLo 覆寫');
    assert.equal(c._pillEditor.op, '=');
});

// ── DoD #6：提交映射 ──────────────────────────────────────────────────────

test('DoD#6 提交 range → { value: lo, value2: hi }', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    c._pillEditor.rangeLo = '150';
    c._pillEditor.rangeHi = '170';
    c._commitPillEditor();
    assert.equal(c._pillEditor, null);
    assert.deepEqual(c.actressPills[0], {
        dim: 'height', op: 'range', value: '150', value2: '170',
    });
});

test('DoD#6 提交非 range → { value, value2: null }', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('<=');
    c._commitPillEditor();
    assert.deepEqual(c.actressPills[0], {
        dim: 'age', op: '<=', value: '37', value2: null,
    });
});

// ── DoD #7：lo > hi 提交自動對調（CD-116b-3）──────────────────────────────

test('DoD#7 lo>hi 提交自動對調：175/160 → value=160 value2=175', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
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

// ── DoD #9：四模式互斥 ────────────────────────────────────────────────────

test('DoD#9 四模式互斥：切換後 op 只會是四值之一', () => {
    const c = makeComponent();
    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    const modes = ['=', '<=', '>=', 'range'];
    for (const op of modes) {
        c._setEditorMode(op);
        assert.equal(c._pillEditor.op, op);
        assert.ok(modes.includes(c._pillEditor.op));
    }
    // 切回 =：不殘留 range 欄位以外的額外狀態欄位
    c._setEditorMode('=');
    assert.equal(c._pillEditor.op, '=');
    assert.deepEqual(
        Object.keys(c._pillEditor).sort(),
        ['dim', 'op', 'rangeHi', 'rangeLo', 'value'].sort(),
    );
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

test('DoD#15 clearAllFilters 後 _pillEditor=null', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    c._openPillEditor(c.actressPills[0]);
    assert.ok(c._pillEditor);
    c.clearAllFilters();
    assert.equal(c._pillEditor, null);
    assert.deepEqual(c.actressPills, []);
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

// ── Review fix：range 邊界非有限數 → fail-safe 不寫入、不關編輯器 ─────────

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

test('range 兩邊界空字串 → _commitPillEditor fail-safe：不寫入、_pillEditor 仍開', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    c._pillEditor.rangeLo = '';
    c._pillEditor.rangeHi = '';
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before, 'actressPills 不得被改寫');
    assert.ok(c._pillEditor, '_pillEditor 必須維持開啟（fail-safe）');
    assert.equal(c._pillEditor.op, 'range');
    assertNoNullOrEmptyPillValues(c.actressPills);
});

test("dim=cup 走 _setEditorMode('range') 後 _commitPillEditor → fail-safe 不寫入", () => {
    const c = makeComponent();
    c.addActressPill('cup', 'B');
    const before = structuredClone(c.actressPills);
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    // cup 無 range：rangeLo/Hi 維持 null
    assert.equal(c._pillEditor.rangeLo, null);
    assert.equal(c._pillEditor.rangeHi, null);
    c._commitPillEditor();
    assert.deepEqual(c.actressPills, before, 'actressPills 不得被改寫');
    assert.ok(c._pillEditor, '_pillEditor 必須維持開啟（fail-safe）');
    assertNoNullOrEmptyPillValues(c.actressPills);
});

test("range 合法值 '155'/'165' 仍照常寫入", () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills[0]);
    c._setEditorMode('range');
    c._pillEditor.rangeLo = '155';
    c._pillEditor.rangeHi = '165';
    c._commitPillEditor();
    assert.equal(c._pillEditor, null, '合法提交後應關閉編輯器');
    assert.deepEqual(c.actressPills[0], {
        dim: 'height', op: 'range', value: '155', value2: '165',
    });
});

// ── Review fix：_pillRangeBounds 與種子常數同一所有者 ─────────────────────

test('_pillRangeBounds：age / height / cup / null editor', () => {
    const c = makeComponent();
    assert.equal(c._pillRangeBounds(), null, '_pillEditor 為 null → null');

    c.addActressPill('age', 30);
    c._openPillEditor(c.actressPills[0]);
    assert.deepEqual(c._pillRangeBounds(), { min: 18, max: 80 });

    c.addActressPill('height', '160cm');
    c._openPillEditor(c.actressPills.find((p) => p.dim === 'height'));
    assert.deepEqual(c._pillRangeBounds(), { min: 130, max: 200 });

    c.addActressPill('cup', 'C');
    c._openPillEditor(c.actressPills.find((p) => p.dim === 'cup'));
    assert.equal(c._pillRangeBounds(), null, 'cup 無 range → null');
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
