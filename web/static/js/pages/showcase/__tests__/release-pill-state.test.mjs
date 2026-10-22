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


// ═══════════════════════════════════════════════════════════════════════════
// spec §5.2 三態表 × 三顆鈕（表驅動，_releaseOperandFor）
// ═══════════════════════════════════════════════════════════════════════════

test('三態操作數表（spec §5.2：①兩端皆空／②只填一端／③兩端都填 × 三顆鈕）→ 取哪一端的值', () => {
    // 預設原 pill 為 = 2020；setup 可覆寫草稿。期望值手寫字面。
    // ①：原 pill 是 range 且端點值不可解析時，四格仍是 null → value 一律照抄、不論原 op
    for (const op of ['=', '<=', '>=']) {
        let c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2023'));
        assert.equal(c._releaseOperandFor(op), '2023', `①非 range op=${op}`);
        c = makeComponent();
        c._toggleReleaseEditor(releasePill('range', 'garbage', 'also-garbage'));
        assert.equal(c._releaseOperandFor(op), 'garbage', `①range 不可解析 op=${op}`);
    }
    // ②只填一端：合法 → 該端 token（op 不影響）；token 為 null（13 月／年 <1000）→ null
    const oneSide = [
        [{ loYear: '2023', loMonth: '09' }, '2023-09'],
        [{ loYear: '2023', loMonth: '13' }, null],
        [{ hiYear: '2024' }, '2024'],
        [{ hiYear: '250' }, null],
    ];
    for (const [draft, want] of oneSide) {
        for (const op of ['=', '<=', '>=']) {
            const c = makeComponent();
            c._toggleReleaseEditor(releasePill('=', '2020'));
            Object.assign(c._releaseEditor, draft);
            assert.equal(c._releaseOperandFor(op), want, `②${JSON.stringify(draft)} op=${op}`);
        }
    }
    // ③兩端都填：= 取左、<= 取右、>= 取左
    for (const [op, want] of [['=', '2022'], ['<=', '2024'], ['>=', '2022']]) {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = '2022';
        c._releaseEditor.hiYear = '2024';
        assert.equal(c._releaseOperandFor(op), want, `③ op=${op}`);
    }
});

// ═══════════════════════════════════════════════════════════════════════════
// _applyReleaseOp：三顆鈕唯一提交路徑（成功寫入且關閉 ／ 失敗 early return 不寫不關）
// ═══════════════════════════════════════════════════════════════════════════


test('_applyReleaseOp 失敗路徑：operand 為 null → 不寫入、不關閉（AC12）', () => {
    const c = makeComponent();
    c._toggleReleaseEditor(releasePill('=', '2020'));
    c._releaseEditor.loYear = '2023';
    c._releaseEditor.loMonth = '13'; // 不合法
    c._applyReleaseOp('=');
    assert.ok(c._releaseEditor, '_releaseEditor 必須維持開啟');
    assert.equal(c.pills.length, 0, 'pills 不得被改寫');
});

// ═══════════════════════════════════════════════════════════════════════════
// AC10：✓ 單邊委派逐欄位相等（結構驗證，非巧合驗證）
// ═══════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════
// AC11：lo>hi 對調
// ═══════════════════════════════════════════════════════════════════════════

test('AC11 對調表：lo>hi 才對調；年份-only 端點（月份留空）不誤判反轉；端點相等不對調', () => {
    // [loY, loM, hiY, hiM, 期望 value, 期望 value2]；期望值手寫字面
    // 年份-only 上端＝該年 12 月結尾、下端＝該年 1 月起點（hiKey/loKey 不得混用 .lo）
    const cases = [
        ['2024', '06', '2023', '01', '2023-01', '2024-06'],   // 年份不同：對調
        ['2023', '09', '2023', '03', '2023-03', '2023-09'],   // 年份相同、月份對調
        ['2020', '01', '2024', '12', '2020-01', '2024-12'],   // 本來就 lo<hi：不動
        ['2024', '06', '2024', '',   '2024-06', '2024'],      // 上端年份-only：不對調
        ['2024', '',   '2024', '06', '2024',    '2024-06'],   // 下端年份-only：不對調
        ['2025', '',   '2023', '',   '2023',    '2025'],      // 年份-only 真反轉：對調
        ['2024', '09', '2024', '03', '2024-03', '2024-09'],   // 同年月反轉：對調
        ['2024', '12', '2024', '',   '2024-12', '2024'],      // 12 月單月：不對調
        ['2024', '',   '2024', '',   '2024',    '2024'],      // 端點相等：不對調
    ];
    for (const [loY, loM, hiY, hiM, v1, v2] of cases) {
        const c = makeComponent();
        c._toggleReleaseEditor(releasePill('=', '2020'));
        c._releaseEditor.loYear = loY; c._releaseEditor.loMonth = loM;
        c._releaseEditor.hiYear = hiY; c._releaseEditor.hiMonth = hiM;
        c._commitReleaseEditor();
        const p = c.pills.find((x) => x.dim === 'release');
        assert.deepEqual(p, { dim: 'release', op: 'range', value: v1, value2: v2 }, `${loY}-${loM} ~ ${hiY}-${hiM}`);
    }
});

// ═══════════════════════════════════════════════════════════════════════════
// 四格全空 ／ 有月無年 ／ 不合法端點 ／ 指數記法 ／ 1800/9999 ／ badInput
// ═══════════════════════════════════════════════════════════════════════════


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


// ═══════════════════════════════════════════════════════════════════════════
// _releaseEditor 為 null 時七支 helper 的安全回傳
// ═══════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════
// _cancelReleaseEditor：✗ 取消，不碰 pills
// ═══════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════
// _releaseYearHint（spec §4.9，全庫不是 _filteredVideos）
// ═══════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════
// _setReleasePill：唯一寫入者、AC4 取代語意、value2 不對稱防呆
// ═══════════════════════════════════════════════════════════════════════════

test('_setReleasePillFromDate：可解析 → 產生 = op、value 為前 7 字', () => {
    const c = makeComponent();
    c._setReleasePillFromDate('2024-09-09');
    const p = c.pills.find((x) => x.dim === 'release');
    assert.deepEqual(p, { dim: 'release', op: '=', value: '2024-09' });
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


// ═══════════════════════════════════════════════════════════════════════════
// 移除 release pill 時的浮層 teardown（§3.3）
// ═══════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════
// §3.5 不變式：四個跨切面 teardown 點各走一次，兩個 slot 皆 null
// hero 橋接（state-actress.js:1271）不寫測試——由 git diff 兩行機械自證（Opus 裁決）。
// ═══════════════════════════════════════════════════════════════════════════

function seedBothEditors(c) {
    c._pillEditor = { dim: 'age', op: '=', value: '30', rangeLo: null, rangeHi: null, badLo: false, badHi: false };
    c._releaseEditor = { op: '=', value: '2020', value2: null, loYear: null, loMonth: null, hiYear: null, hiMonth: null, badLoY: false, badLoM: false, badHiY: false, badHiM: false };
}


// ═══════════════════════════════════════════════════════════════════════════
// 持久化鏈（CD-124a-14）
// ═══════════════════════════════════════════════════════════════════════════


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
