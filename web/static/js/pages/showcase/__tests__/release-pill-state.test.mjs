// TASK-124a-T2: 發售日 pill 浮層狀態機（_releaseEditor / _releaseEndpoint / 三顆鈕即點即套 /
// 自訂區間 ✓✗ / 對調 / 四個跨切面 teardown 點 / 持久化鏈）。零 markup、零 CSS。
//
// 鏡射 actress-pill-editor.test.mjs 的 harness（importmap resolve hook + globalThis.window
// stub，FE-GUARD-11）。與該檔不同之處：本檔的 makeComponent() **不** stub _animateFilter /
// saveState / applyFilterAndSort 為空函式——CD-124a-14 持久化鏈測試需要真的 _animateFilter()
// 內部呼叫真的 applyFilterAndSort() + saveState()。只 stub DOM／動畫相關依賴
// （_getActiveGrid 恆回 null 即可短路 _animateFilter 的動畫分支）。

import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。在任何 import 之前先 stub（FE-GUARD-11）。
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
// saveState() 讀 window.location / window.history（CD-124a-14 持久化鏈需要真的 saveState()）。
globalThis.window.location = { pathname: '/showcase', search: '' };
globalThis.window.history = { replaceState() {} };

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
const { stateBase, _setActresses, _setVideos } = await import('../state-base.js');
const { stateVideos } = await import('../state-videos.js');

// ── matchMedia stub（可控 matches ＋ 記錄 handler 參考，逐字比照 actress-pill-editor.test.mjs）──

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
            for (const [q, mq] of mqsByQuery) {
                if (q.includes('480')) mq._dispatch(m);
            }
        },
    };
}

let mm = installMatchMedia(false); // 預設桌機（>480）

beforeEach(() => {
    mm = installMatchMedia(false);
});

/**
 * 合併 stateBase + stateActress + stateVideos。與 actress-pill-editor.test.mjs 的關鍵差異：
 * _animateFilter / saveState / applyFilterAndSort 保留真身（CD-124a-14 持久化鏈需要），
 * 只 stub DOM／動畫相關依賴。
 */
function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const actress = stateActress();
    const videos = stateVideos();
    const c = Object.assign({}, base, actress, videos, {
        actressSearch: '',
        actressSort: 'video_count',
        actressOrder: 'desc',
        lightboxOpen: false,
        closeLightbox() {},
        _getActiveGrid() { return null; },   // 短路 _animateFilter 的動畫分支
        _resetPicker() {},
        _resetMask() {},
        $nextTick(fn) { if (typeof fn === 'function') fn(); },
        $watch() {},
        _sortWithFlip(fn) { if (typeof fn === 'function') fn(); },
    }, overrides);
    if (!Array.isArray(c.pills)) c.pills = [];
    if (!Array.isArray(c.actressPills)) c.actressPills = [];
    // 至少一筆女優種子，避免 _reconcileHeroCard() 內部 _checkPreciseActressMatch()
    // 因 _actresses.length===0 而觸發真的 loadActresses()（網路呼叫）。
    _setActresses([{ name: 'seed', is_favorite: false }]);
    _setVideos([]);
    return c;
}

/** 跑 init() 到 matchMedia 註冊完成（stub 掉網路與 Alpine 依賴），比照 actress-pill-editor.test.mjs */
async function runInit(c) {
    globalThis.window.__registerPage = () => {};
    const origFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
        ok: true,
        json: async () => ({ success: true, videos: [], groups: [] }),
    });
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

/** 直接構造一枚 release pill（不透過 addPill），供 _toggleReleaseEditor 開啟用 */
function releasePill(op, value, value2) {
    return { dim: 'release', op, value, value2: value2 == null ? null : value2 };
}

// ═══════════════════════════════════════════════════════════════════════════
// _toggleReleaseEditor：開啟映射 ／ 同枚再點關閉 ／ 第二層防禦
// ═══════════════════════════════════════════════════════════════════════════

test('_toggleReleaseEditor：開啟非 range pill，四格全空（不像女優版種子 value±寬度）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2023'));
    assert.ok(c._releaseEditor);
    assert.equal(c._releaseEditor.op, '=');
    assert.equal(c._releaseEditor.value, '2023');
    assert.equal(c._releaseEditor.loYear, null);
    assert.equal(c._releaseEditor.loMonth, null);
    assert.equal(c._releaseEditor.hiYear, null);
    assert.equal(c._releaseEditor.hiMonth, null);
});

test('_toggleReleaseEditor：開啟 range pill，四格映射自 value/value2，月份 zero-pad', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('range', '2023-09', '2024'));
    assert.equal(c._releaseEditor.loYear, '2023');
    assert.equal(c._releaseEditor.loMonth, '09');
    assert.equal(c._releaseEditor.hiYear, '2024');
    assert.equal(c._releaseEditor.hiMonth, null);
});

test('_toggleReleaseEditor：同一枚再點 → 關閉（release pill 恆 0/1 枚，不比對 dim）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2023'));
    assert.ok(c._releaseEditor);
    c._toggleReleaseEditor(releasePill('=', '2023'));
    assert.equal(c._releaseEditor, null);
});

test('_toggleReleaseEditor：_pillPopoverEnabled=false 時早退，_releaseEditor 呼叫前後不變', () => {
    const c = makeComponent();
    c._pillPopoverEnabled = false;
    c._toggleReleaseEditor(releasePill('=', '2023'));
    assert.equal(c._releaseEditor, null);
});

// ═══════════════════════════════════════════════════════════════════════════
// spec §5.2 三態表逐列 × 三顆鈕（12 組合，_releaseOperandFor）
// ═══════════════════════════════════════════════════════════════════════════

for (const op of ['=', '<=', '>=']) {
    test(`三態①兩端皆空（原 pill 非 range）：_releaseOperandFor('${op}') → 照抄 d.value`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2023'));
        assert.equal(c._releaseOperandFor(op), '2023');
    });

    // ⚠ 原 pill 是 range 且端點值本身可解析時，_toggleReleaseEditor 會把 loYear/hiYear
    // 一併帶入草稿（技術要點 1：四格映射），此時已落在「兩端都填」狀態，不是「兩端皆空」。
    // 真正能測到「原 pill 是 range 但兩端皆空」的前提，是端點值本身不可解析（parseEndpoint
    // 回 null），loYear/hiYear 因此仍是 null——這正是「value 一律照抄、不論原 op」唯一能
    // 獨立於「兩端是否有字」被驗證的前情。
    test(`三態①兩端皆空（原 pill 是 range，端點值不可解析）：_releaseOperandFor('${op}') → 照抄 d.value（不論原 op）`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('range', 'garbage', 'also-garbage'));
        assert.equal(c._releaseOperandFor(op), 'garbage');
    });
}

for (const op of ['=', '<=', '>=']) {
    test(`三態②只填左端（合法）：_releaseOperandFor('${op}') → 左端 token（op 不影響）`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = '2023';
        c._releaseEditor.loMonth = '09';
        assert.equal(c._releaseOperandFor(op), '2023-09');
    });

    test(`三態②只填左端（token 為 null，13 月）：_releaseOperandFor('${op}') → null（不寫入不關閉）`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = '2023';
        c._releaseEditor.loMonth = '13';
        assert.equal(c._releaseOperandFor(op), null);
    });

    test(`三態②只填右端（合法）：_releaseOperandFor('${op}') → 右端 token`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.hiYear = '2024';
        assert.equal(c._releaseOperandFor(op), '2024');
    });

    test(`三態②只填右端（token 為 null）：_releaseOperandFor('${op}') → null`, () => {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.hiYear = '250'; // <1000，數值範圍不合法
        assert.equal(c._releaseOperandFor(op), null);
    });
}

test("三態③兩端都填：_releaseOperandFor('=') → 取左端", () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2022';
    c._releaseEditor.hiYear = '2024';
    assert.equal(c._releaseOperandFor('='), '2022');
});

test("三態③兩端都填：_releaseOperandFor('<=') → 取右端", () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2022';
    c._releaseEditor.hiYear = '2024';
    assert.equal(c._releaseOperandFor('<='), '2024');
});

test("三態③兩端都填：_releaseOperandFor('>=') → 取左端", () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2022';
    c._releaseEditor.hiYear = '2024';
    assert.equal(c._releaseOperandFor('>='), '2022');
});

// ═══════════════════════════════════════════════════════════════════════════
// _applyReleaseOp：三顆鈕唯一提交路徑（成功寫入且關閉 ／ 失敗 early return 不寫不關）
// ═══════════════════════════════════════════════════════════════════════════

test('_applyReleaseOp 成功路徑：寫入 pills 且 _releaseEditor 變 null（AC8）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._applyReleaseOp('>=');
    assert.equal(c._releaseEditor, null);
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: '>=', value: '2023' });
});

test('_applyReleaseOp 失敗路徑：operand 為 null → 不寫入、不關閉（AC12）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._releaseEditor.loMonth = '13'; // 不合法
    c._applyReleaseOp('=');
    assert.ok(c._releaseEditor, '_releaseEditor 必須維持開啟');
    assert.equal(c.pills.length, 0, 'pills 不得被改寫');
});

test('_applyReleaseOp：_releaseEditor 為 null 時安全早退（this.pills 不變）', () => {
    const c = makeComponent();
    const before = c.pills.slice();
    assert.doesNotThrow(() => c._applyReleaseOp('='));
    assert.deepEqual(c.pills, before);
});

// ═══════════════════════════════════════════════════════════════════════════
// AC10：✓ 單邊委派逐欄位相等（結構驗證，非巧合驗證）
// ═══════════════════════════════════════════════════════════════════════════

test('AC10：只填左端，✓ 與直接按 ≥（同一草稿狀態）逐欄位相同', () => {
    const c1 = makeComponent();
    c1._toggleReleaseEditor(releasePill('=', '2020'));
    c1._releaseEditor.loYear = '2023';
    c1._commitReleaseEditor();

    const c2 = makeComponent();
    c2._toggleReleaseEditor(releasePill('=', '2020'));
    c2._releaseEditor.loYear = '2023';
    c2._applyReleaseOp('>=');

    const p1 = c1.pills.find((x) => x.dim === 'release');
    const p2 = c2.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p1, p2);
    assert.deepEqual(p1, { dim: 'release', op: '>=', value: '2023' });
});

test('AC10：只填右端，✓ 與直接按 ≤（同一草稿狀態）逐欄位相同', () => {
    const c1 = makeComponent();
    c1._toggleReleaseEditor(releasePill('=', '2020'));
    c1._releaseEditor.hiYear = '2024';
    c1._commitReleaseEditor();

    const c2 = makeComponent();
    c2._toggleReleaseEditor(releasePill('=', '2020'));
    c2._releaseEditor.hiYear = '2024';
    c2._applyReleaseOp('<=');

    const p1 = c1.pills.find((x) => x.dim === 'release');
    const p2 = c2.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p1, p2);
    assert.deepEqual(p1, { dim: 'release', op: '<=', value: '2024' });
});

test('AC10 結構鎖：✓ 單邊是「委派給 _applyReleaseOp」，不是自己組同樣的物件', () => {
    // T2 review 命中：上面兩條「逐欄位相同」在單邊合法值下無法區分「真委派」與
    // 「另寫一份剛好答案一樣的邏輯」——把 _commitReleaseEditor 改成自組 {op,value}
    // 物件時它們仍然全綠。這一條直接鎖住呼叫本身：單邊提交必須經過 _applyReleaseOp，
    // 且帶的 op 就是那一側對應的運算子。
    const c = makeComponent();
    const calls = [];
    const orig = c._applyReleaseOp;
    c._applyReleaseOp = function (op) { calls.push(op); return orig.call(this, op); };

    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._commitReleaseEditor();
    assert.deepEqual(calls, ['>=']);

    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.hiYear = '2024';
    c._commitReleaseEditor();
    assert.deepEqual(calls, ['>=', '<=']);
});

// ═══════════════════════════════════════════════════════════════════════════
// AC11：lo>hi 對調
// ═══════════════════════════════════════════════════════════════════════════

test('AC11：年份不同的 lo>hi 對調 → value/value2 交換', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '06';
    c._releaseEditor.hiYear = '2023'; c._releaseEditor.hiMonth = '01';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2023-01', value2: '2024-06' });
});

test('AC11：年份相同、只有月份需要對調', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023'; c._releaseEditor.loMonth = '09';
    c._releaseEditor.hiYear = '2023'; c._releaseEditor.hiMonth = '03';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2023-03', value2: '2023-09' });
});

test('AC11 反向鎖：lo 本來就 < hi，不需要對調時 token 不被意外交換', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2020'; c._releaseEditor.loMonth = '01';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '12';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2020-01', value2: '2024-12' });
});

test('AC11 年份-only 上端不誤判反轉：lo=2024-06、hi=2024（月份留空代表整年結尾）→ 不對調', () => {
    // 迴歸鎖：hiKey 若誤用 .lo 展開，'2024'（年份-only）會被讀成 202401（1 月）而非
    // 202412（12 月結尾），202406 > 202401 觸發錯誤對調，pill 變成 2024~2024-06 展開後
    // 只剩 1~6 月，正好是使用者原意（6~12 月）的反面。
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '06';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2024-06', value2: '2024' });
});

test('AC11 年份-only 下端不誤判反轉：lo=2024、hi=2024-06（下端整年起點 1 月 <= 6 月）→ 不對調', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '06';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2024', value2: '2024-06' });
});

test('AC11 年份-only 真反轉仍須對調：lo=2025、hi=2023', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2025'; c._releaseEditor.loMonth = '';
    c._releaseEditor.hiYear = '2023'; c._releaseEditor.hiMonth = '';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2023', value2: '2025' });
});

test('AC11 同年月反轉仍須對調：lo=2024-09、hi=2024-03', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '09';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '03';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2024-03', value2: '2024-09' });
});

test('AC11 下端月份 ＝ 上端整年結尾：lo=2024-12、hi=2024 → 不對調（12 月單月）', () => {
    // 這是本次修正**行為確實改變**的那一格，故獨立鎖住：改動前兩側都用 .lo，
    // 202412 > 202401 觸發對調 → pill 變成 2024~2024-12 → 展開成整年；改動後
    // 202412 <= 202412（上端整年結尾）不對調 → 2024-12~2024 → 展開成 12 月單月。
    // 後者才是使用者填的意思（起點已經指定到 12 月，上端只是說「到這年結束」）。
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '12';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2024-12', value2: '2024' });
});

test('AC11 端點相等不對調：lo=2024、hi=2024', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2024'; c._releaseEditor.loMonth = '';
    c._releaseEditor.hiYear = '2024'; c._releaseEditor.hiMonth = '';
    c._commitReleaseEditor();
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: 'range', value: '2024', value2: '2024' });
});

// ═══════════════════════════════════════════════════════════════════════════
// 四格全空 ／ 有月無年 ／ 13/0 月 ／ 非四位年（含 '0230'/'0002'）／ 1800/9999 ／ badInput
// ═══════════════════════════════════════════════════════════════════════════

test('四格全空：_releaseEditorHasInput() 為 false；✓ 不寫入、_releaseEditor 仍開（防禦性 return）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    assert.equal(c._releaseEditorHasInput(), false);
    c._commitReleaseEditor();
    assert.ok(c._releaseEditor, '_releaseEditor 必須維持開啟');
    assert.equal(c.pills.length, 0);
});

test('有月無年：_releaseEndpoint 回 {has:true, token:null}；唯一填的一端 → 不寫入不關閉', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loMonth = '09'; // loYear 仍是 null
    const lo = c._releaseEndpoint('lo');
    assert.deepEqual(lo, { has: true, token: null });
    c._applyReleaseOp('=');
    assert.ok(c._releaseEditor);
    assert.equal(c.pills.length, 0);
    c._commitReleaseEditor();
    assert.ok(c._releaseEditor);
    assert.equal(c.pills.length, 0);
});

test('13 月 / 0 月：token 皆為 null', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._releaseEditor.loMonth = '13';
    assert.equal(c._releaseEndpoint('lo').token, null);
    c._releaseEditor.loMonth = '00';
    assert.equal(c._releaseEndpoint('lo').token, null);
});

test("非四位年：'2'/'250'/'20244' → token 皆為 null", () => {
    const c = makeComponent();
    for (const y of ['2', '250', '20244']) {
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = y;
        assert.equal(c._releaseEndpoint('lo').token, null, `年份 '${y}' 應形不成條件`);
        c._releaseEditor = null;
    }
});

test("⚠ 落差鎖：'0230'/'0002' 這類四字元但數值 <1000 的年份 → token:null（composeEndpoint 數值檢查，非 parseEndpoint 字元數檢查）", () => {
    const c = makeComponent();
    for (const y of ['0230', '0002']) {
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = y;
        assert.equal(c._releaseEndpoint('lo').token, null, `年份 '${y}' 在 _releaseEndpoint() 這一層必須被拒`);
        c._releaseEditor = null;
    }
});

// Codex PR review P2（2026-08-21）：質疑 composeEndpoint() 只驗數值範圍（Number() 之後
// 1000–9999），不驗字元形狀 ^\d{4}$，所以 '1e3'、'1000.0' 這類指數／多餘小數點記法會被
// Number() 正規化成 1000 後照樣套用。實測重現（真 <input type="number"> 逐字打入）：能真
// 的打進去的只有這幾種指數/多小數點寫法，且正規化後永遠是「同一個數字的另一種寫法」
// （1e3 就是 1000），composeEndpoint() 的輸出仍滿足 deserializePills 的嚴格 regex，寫得進
// 讀得回，沒有暗坑。Opus 裁決：accepted residual，不改行為——這正是 CD-124a-10 允許的
// 「同一個數字的另一種寫法」正規化，不是夾回；CD-124a-15 要擋的「打字中途的短數字」
// （'2'/'250'/'20244'/'0230'）不受影響，仍然被拒。
//
// 本測試同時鎖住「接受什麼」與「仍然拒絕什麼」。⚠ 如果未來有人把 _releaseEndpoint() 的
// 年份判準從「數值範圍」改成「字元形狀 ^\d{4}$」，這支測試裡的指數/小數點案例會轉紅——
// 那是提醒你先回去讀 CD-124a-10 / CD-124a-15 的定義再動，不是叫你把測試改掉。
test("刻意接受的記法正規化：指數/多餘小數點年月（'1e3'、'1000.0'、'9.999e3'、'0.9e1'）正規化後照樣套用；短數字對照組仍拒（Codex P2 accepted residual）", () => {
    const c = makeComponent();

    // 接受組①：'1e3' → 1000，✓ 套用、浮層關閉
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '1e3';
    assert.equal(c._releaseEndpoint('lo').token, '1000', "'1e3' 應正規化為 1000");
    c._applyReleaseOp('=');
    assert.equal(c._releaseEditor, null, '浮層應關閉');
    assert.deepEqual(c.pills.find((x) => x.dim === 'release'), { dim: 'release', op: '=', value: '1000' });

    // 接受組②：'1000.0' → 1000，同上
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '1000.0';
    assert.equal(c._releaseEndpoint('lo').token, '1000', "'1000.0' 應正規化為 1000");
    c._applyReleaseOp('=');
    assert.equal(c._releaseEditor, null, '浮層應關閉');
    assert.deepEqual(c.pills.find((x) => x.dim === 'release'), { dim: 'release', op: '=', value: '1000' });

    // 接受組③：'9.999e3' → 9999（只驗 token，不重複驗提交路徑）
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '9.999e3';
    assert.equal(c._releaseEndpoint('lo').token, '9999', "'9.999e3' 應正規化為 9999");
    c._releaseEditor = null;

    // 接受組④：月格 '0.9e1' → 09（配一個合法年）
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._releaseEditor.loMonth = '0.9e1';
    assert.equal(c._releaseEndpoint('lo').token, '2023-09', "月份 '0.9e1' 應正規化為 09");
    c._releaseEditor = null;

    // 對照組：CD-124a-15 要擋的「打字中途的短數字」仍然被拒——token:null、不寫入、浮層不關。
    // pills 快照鎖「不寫入」：接受組已把 release pill 寫成 '1000'，對照組跑完必須原封不動。
    const pillsBefore = JSON.parse(JSON.stringify(c.pills));
    for (const y of ['2', '250', '20244', '0230']) {
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = y;
        assert.equal(c._releaseEndpoint('lo').token, null, `年份 '${y}' 仍應被拒`);
        c._applyReleaseOp('=');
        assert.ok(c._releaseEditor, `年份 '${y}'：浮層必須維持開啟`);
        assert.deepEqual(c.pills, pillsBefore, `年份 '${y}'：pills 不得被改寫`);
        c._releaseEditor = null;
    }
});

test('1800/9999 照常套用（AC13，零結果是比對層的事，不是本層的事）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '1800';
    assert.equal(c._releaseEndpoint('lo').token, '1800');
    c._releaseEditor.hiYear = '9999';
    c._releaseEditor.hiMonth = '12';
    assert.equal(c._releaseEndpoint('hi').token, '9999-12');
});

test('badInput：badLoY=true 時一律 token:null，即使 loYear 文字看起來合法', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._releaseEditor.badLoY = true;
    assert.deepEqual(c._releaseEndpoint('lo'), { has: true, token: null });
});

// ═══════════════════════════════════════════════════════════════════════════
// _releaseEditor 為 null 時七支 helper 的安全回傳
// ═══════════════════════════════════════════════════════════════════════════

test('_releaseEditor=null 時七支 helper 安全回傳', () => {
    const c = makeComponent();
    assert.deepEqual(c._releaseEndpoint('lo'), { has: false, token: null });
    assert.deepEqual(c._releaseEndpoint('hi'), { has: false, token: null });
    assert.equal(c._releaseOperandFor('='), null);
    const before = c.pills.slice();
    assert.doesNotThrow(() => c._applyReleaseOp('='));
    assert.deepEqual(c.pills, before);
    assert.doesNotThrow(() => c._commitReleaseEditor());
    assert.deepEqual(c.pills, before);
    assert.doesNotThrow(() => c._cancelReleaseEditor());
    assert.equal(c._releaseEditor, null);
    assert.equal(c._releaseEditorHasInput(), false);
    assert.equal(c._releaseYearHint(), '');
});

// ═══════════════════════════════════════════════════════════════════════════
// _cancelReleaseEditor：✗ 取消，不碰 pills
// ═══════════════════════════════════════════════════════════════════════════

test('_cancelReleaseEditor：只丟棄草稿，pills 逐位元組不變', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: '=', value: '2020' });
    const before = c.pills.slice();
    c._toggleReleaseEditor(c.pills[0]);
    c._releaseEditor.loYear = '2099';
    c._cancelReleaseEditor();
    assert.equal(c._releaseEditor, null);
    assert.deepEqual(c.pills, before);
});

// ═══════════════════════════════════════════════════════════════════════════
// releasePillText / pillLabel（AC21，spec §5.4）
// ═══════════════════════════════════════════════════════════════════════════

test('releasePillText：range 用 ~ 連接，不加空白、不展開', () => {
    const c = makeComponent();
    assert.equal(c.releasePillText({ op: 'range', value: '2023-01', value2: '2024-06' }), '2023-01~2024-06');
});

test('releasePillText：= 前綴，年-only 不得被展開成 年-01~年-12', () => {
    const c = makeComponent();
    assert.equal(c.releasePillText({ op: '=', value: '2023' }), '=2023');
    assert.notEqual(c.releasePillText({ op: '=', value: '2023' }), '=2023-01~2023-12');
});

test('releasePillText：≤／≥ 前綴', () => {
    const c = makeComponent();
    assert.equal(c.releasePillText({ op: '<=', value: '2023-09' }), '≤2023-09');
    assert.equal(c.releasePillText({ op: '>=', value: '2020' }), '≥2020');
});

test('pillLabel：release 維度分派到 releasePillText，pick/其餘維度不受影響（回歸）', () => {
    const c = makeComponent();
    assert.equal(c.pillLabel({ dim: 'release', op: '=', value: '2023' }), '=2023');
    assert.equal(c.pillLabel({ dim: 'pick', value: '1' }), 'showcase.pick.chip_label');
    assert.equal(c.pillLabel({ dim: 'maker', value: 'Moodyz' }), 'Moodyz');
});

// ═══════════════════════════════════════════════════════════════════════════
// _releaseYearHint（spec §4.9，全庫不是 _filteredVideos）
// ═══════════════════════════════════════════════════════════════════════════

test('_releaseYearHint：_releaseEditor=null → ""', () => {
    const c = makeComponent();
    assert.equal(c._releaseYearHint(), '');
});

test('_releaseYearHint：全庫可解析年月 → "（min ~ max）"', () => {
    const c = makeComponent();
    _setVideos([
        { release_date: '2020-05-01' },
        { release_date: '2023-11-02' },
        { release_date: 'bad-date' },
    ]);
    c._toggleReleaseEditor(releasePill('=', '2020'));
    assert.equal(c._releaseYearHint(), '（2020 ~ 2023）');
});

test('_releaseYearHint：一部片都解析不出年月 → ""', () => {
    const c = makeComponent();
    _setVideos([{ release_date: 'bad-date' }, { release_date: null }]);
    c._toggleReleaseEditor(releasePill('=', '2020'));
    assert.equal(c._releaseYearHint(), '');
});

// ═══════════════════════════════════════════════════════════════════════════
// _isReleaseClickable（T3 引用的入口判準）
// ═══════════════════════════════════════════════════════════════════════════

test('_isReleaseClickable：可解析 release_date → true；不可解析／缺欄位 → false', () => {
    const c = makeComponent();
    assert.equal(c._isReleaseClickable({ release_date: '2024-09-09' }), true);
    assert.equal(c._isReleaseClickable({ release_date: 'bad' }), false);
    assert.equal(c._isReleaseClickable({}), false);
    assert.equal(c._isReleaseClickable(null), false);
});

// ═══════════════════════════════════════════════════════════════════════════
// _setReleasePill：唯一寫入者、AC4 取代語意、value2 不對稱防呆
// ═══════════════════════════════════════════════════════════════════════════

test('_setReleasePillFromDate：可解析 → 產生 = op、value 為前 7 字', () => {
    const c = makeComponent();
    c._setReleasePillFromDate('2024-09-09');
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: '=', value: '2024-09' });
});

test('_setReleasePillFromDate：不可解析 → 不產生 pill（spec §4.4）', () => {
    const c = makeComponent();
    c._setReleasePillFromDate('bad-date');
    assert.equal(c.pills.length, 0);
});

test('AC4 取代語意：第二次呼叫後 release 維度仍恰 1 枚且值是新的；其他維度 pill 不受影響（參照與順序皆不變）', () => {
    const c = makeComponent();
    const actressPill = { dim: 'actress', value: 'Foo' };
    const pickPill = { dim: 'pick', value: '1' };
    c.pills = [actressPill, pickPill];
    c._setReleasePill({ dim: 'release', op: '=', value: '2020' });
    c._setReleasePill({ dim: 'release', op: '=', value: '2023' });

    const releasePills = c.pills.filter((p) => p.dim === 'release');
    assert.equal(releasePills.length, 1, 'release 維度恰 1 枚');
    assert.equal(releasePills[0].value, '2023', '值是新的');

    // 其他維度：物件參照與順序皆不變
    assert.equal(c.pills[0], actressPill, 'actress pill 參照不變');
    assert.equal(c.pills[1], pickPill, 'pick pill 參照不變');
});

test('value2 不對稱防呆：非 range op 傳入的物件即使帶 value2 鍵，寫入 pills 的物件不含 value2 鍵', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: '=', value: '2025', value2: 'stale-should-be-dropped' });
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(Object.keys(p).sort(), ['dim', 'op', 'value']);
});

test('value2 不對稱防呆：range→= 連續呼叫，第二枚不殘留 value2 鍵（plan §8.1 陷阱）', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: 'range', value: '2023', value2: '2024-06' });
    c._setReleasePill({ dim: 'release', op: '=', value: '2025' });
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(Object.keys(p).sort(), ['dim', 'op', 'value']);
});

test('range op 寫入的物件含 value2 鍵', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: 'range', value: '2023', value2: '2024-06' });
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(Object.keys(p).sort(), ['dim', 'op', 'value', 'value2']);
});

test('_setReleasePill 呼叫後 _reconcileHeroCard 被呼叫一次', () => {
    const c = makeComponent();
    let calls = 0;
    const orig = c._reconcileHeroCard.bind(c);
    c._reconcileHeroCard = function (...args) { calls++; return orig(...args); };
    c._setReleasePill({ dim: 'release', op: '=', value: '2024-09' });
    assert.equal(calls, 1);
});

// ═══════════════════════════════════════════════════════════════════════════
// 移除 release pill 時的浮層 teardown（§3.3）
// ═══════════════════════════════════════════════════════════════════════════

test('removePill(release, 該值)：正在編輯它時 → _releaseEditor 變 null', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: '=', value: '2023' });
    c._toggleReleaseEditor(c.pills.find((p) => p.dim === 'release'));
    assert.ok(c._releaseEditor);
    c.removePill('release', '2023');
    assert.equal(c._releaseEditor, null);
});

test('removePill(其他維度)：_releaseEditor 正在編輯時不受影響', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: '=', value: '2023' });
    c.pills = [...c.pills, { dim: 'actress', value: 'Foo' }];
    c._toggleReleaseEditor(c.pills.find((p) => p.dim === 'release'));
    assert.ok(c._releaseEditor);
    c.removePill('actress', 'Foo');
    assert.ok(c._releaseEditor, '_releaseEditor 不應受無關維度的 removePill 影響');
});

// ═══════════════════════════════════════════════════════════════════════════
// §3.5 不變式：四個跨切面 teardown 點各走一次，兩個 slot 皆 null
// hero 橋接（state-actress.js:1271）不寫測試——由 git diff 兩行機械自證（Opus 裁決）。
// ═══════════════════════════════════════════════════════════════════════════

function seedBothEditors(c) {
    c._pillEditor = { dim: 'age', op: '=', value: '30', rangeLo: null, rangeHi: null, badLo: false, badHi: false };
    c._releaseEditor = { op: '=', value: '2020', value2: null, loYear: null, loMonth: null, hiYear: null, hiMonth: null, badLoY: false, badLoM: false, badHiY: false, badHiM: false };
}

test('§3.5 跨切面點①：state-base.js 斷點 handler（matchMedia 跨進 ≤480）→ 雙 slot 皆 null', async () => {
    mm = installMatchMedia(false); // 先桌機
    const c = makeComponent();
    await runInit(c);
    seedBothEditors(c);
    mm.setMatches(true); // 模擬跨進 ≤480
    assert.equal(c._pillEditor, null);
    assert.equal(c._releaseEditor, null);
});

test('§3.5 跨切面點②：toggleActressMode() → 雙 slot 皆 null', () => {
    const c = makeComponent();
    seedBothEditors(c);
    try {
        c.toggleActressMode();
    } catch (_) {
        // flipAndFadeIn 的 DOM/動畫副作用不在本 task 範圍；teardown 已在函式開頭無條件執行
    }
    assert.equal(c._pillEditor, null);
    assert.equal(c._releaseEditor, null);
});

test('§3.5 跨切面點③：_teardownPillEditors() 本身冪等且雙清空', () => {
    const c = makeComponent();
    seedBothEditors(c);
    c._teardownPillEditors();
    assert.equal(c._pillEditor, null);
    assert.equal(c._releaseEditor, null);
    // 冪等：兩個 slot 已是 null 時再呼叫一次仍安全
    assert.doesNotThrow(() => c._teardownPillEditors());
    assert.equal(c._pillEditor, null);
    assert.equal(c._releaseEditor, null);
});

test('§3.5 跨切面點④：clearAllFilters() → 雙 slot 皆 null', () => {
    const c = makeComponent();
    seedBothEditors(c);
    c.clearAllFilters();
    assert.equal(c._pillEditor, null);
    assert.equal(c._releaseEditor, null);
});

// ═══════════════════════════════════════════════════════════════════════════
// 持久化鏈（CD-124a-14）
// ═══════════════════════════════════════════════════════════════════════════

test('持久化鏈：_setReleasePill() 走完 _animateFilter() 後 _persistedShowcase.pills 含該枚 release pill', () => {
    const c = makeComponent();
    c._setReleasePill({ dim: 'release', op: '=', value: '2024-09' });
    const persisted = c._persistedShowcase.pills.find((p) => p.dim === 'release');
    assert.deepEqual(persisted, { dim: 'release', value: '2024-09', op: '=' });
});

test('持久化鏈：改運算子後再讀一次，_persistedShowcase.pills 存的是新條件不是舊條件', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._applyReleaseOp('>=');
    let persisted = c._persistedShowcase.pills.find((p) => p.dim === 'release');
    assert.deepEqual(persisted, { dim: 'release', value: '2023', op: '>=' });

    c._toggleReleaseEditor(c.pills.find((p) => p.dim === 'release'));
    c._releaseEditor.loYear = '2025';
    c._applyReleaseOp('<=');
    persisted = c._persistedShowcase.pills.find((p) => p.dim === 'release');
    assert.deepEqual(persisted, { dim: 'release', value: '2025', op: '<=' });
});

// ═══════════════════════════════════════════════════════════════════════════
// 女優模式回歸：既有女優浮層測試檔全綠且未改動（用 npm test 整體跑一次即可交叉驗證，
// 本檔不重複跑 actress-pill-*.test.mjs 的內容——那些檔案本身逐字不動）。
// ═══════════════════════════════════════════════════════════════════════════
