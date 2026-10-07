// TASK-124b-T1: _actressInfoTokens / _actressCardMiddle 恆回作品數 / infoVisible 持久化 / S 鍵 gate。
// TASK-124b-T4: _actressInfoTokens → _actressInfoParts（parts 物件 ＋ clickable）
//               ＋ _onActressCardMetadataClick（卡片路徑的 pill handler）。
//
// state-actress.js / state-base.js / state-lightbox.js 用瀏覽器 importmap 別名
// `@/showcase/...` 與 `@/shared/...`，plain `node --test` 不認得。比照
// card-shape-persist.test.mjs / presentation-wiring.test.mjs，本檔自帶與 base.html
// importmap 對齊的 resolve hook（不改共用 loader，FE-GUARD-11）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// state-base.js 模組頂層讀 localStorage（清壞值）。比照既有 showcase 測試先 stub window。
globalThis.window = globalThis;
globalThis.window.t = (key) => key;

// 124b-T4：_onActressCardMetadataClick 會寫 Alpine.store('ui').toolbarOpen。
// 單一 mutable store（鏡射 actress-core-metadata.test.mjs:18-19）——每次 new 一個新物件
// 會讓寫入值丟失，斷言就永遠讀到初值。
const _uiStore = { toolbarOpen: false, showcaseHasSearch: false };
globalThis.Alpine = { store: () => _uiStore };

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
const { stateBase } = await import('../state-base.js');
const { stateLightbox } = await import('../state-lightbox.js');

// =====================================================================
// _actressInfoParts（124b-T4 取代 _actressInfoTokens）
// =====================================================================

const FULL_ACTRESS = {
    video_count: 12,
    age: 25,
    height: '160cm',
    cup: 'C',
    bust: 88,
    waist: 58,
    hip: 88,
};

function partsOf(actress, isNarrow) {
    const c = Object.assign({}, stateActress(), { _isNarrow: isNarrow });
    return c._actressInfoParts(actress);
}

function keysOf(actress, isNarrow) {
    return partsOf(actress, isNarrow).map((p) => p.key);
}

function textsOf(actress, isNarrow) {
    return partsOf(actress, isNarrow).map((p) => p.text);
}

function byKey(actress, isNarrow) {
    return Object.fromEntries(partsOf(actress, isNarrow).map((p) => [p.key, p]));
}

// ── 收留規則（CD-124b-13）──────────────────────────────────────────────

test('text 逐字不變（124b-T1 視覺零回歸）：窄螢幕五個 token 的文字與改動前相同', () => {
    assert.deepEqual(textsOf(FULL_ACTRESS, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        '160cm',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

test('缺 height（null）→ 該 part 不出現，其餘不受影響', () => {
    // 162a：缺 cup（undefined）、缺 height（空字串）、三圍缺一格併入同一支（同一失敗原因：缺值不顯示殘缺欄）
    const cases = [
        [{ height: null }, ['count', 'age', 'cup', 'bwh']],
        [{ cup: undefined }, ['count', 'age', 'height', 'bwh']],
        [{ height: '' }, ['count', 'age', 'cup', 'bwh']],
        [{ bust: null }, ['count', 'age', 'height', 'cup']],
    ];
    for (const [override, expected] of cases) {
        assert.deepEqual(keysOf(Object.assign({}, FULL_ACTRESS, override), true), expected);
    }
});

test('actress 全空欄位（五欄皆 null）→ 回傳 []（窄寬皆然：整塊資訊區不渲染）', () => {
    const actress = {
        video_count: null, age: null, height: null, cup: null,
        bust: null, waist: null, hip: null,
    };
    assert.deepEqual(partsOf(actress, true), []);
    assert.deepEqual(partsOf(actress, false), []);
    // 162a：actress 本身為 null 併入同一支
    assert.deepEqual(partsOf(null, true), []);
});

test('CD-124b-12 紅線：video_count:0 → text \'0showcase.unit.films\'；age:0 → text \'0search.unit.age\' 且 clickable=true', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { video_count: 0, age: 0 });
    assert.deepEqual(textsOf(actress, true), [
        '0showcase.unit.films',
        '0search.unit.age',
        '160cm',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
    assert.equal(byKey(actress, true).age.clickable, true, 'age:0 篩得到她自己，必須可點');
});

// ── clickable（CD-124b-13：可點的三格 ＋ 恆不可點的兩格）──────────────

test('clickable：age/height/cup 值可解析 → true；count/bwh 恆 false（窄螢幕）', () => {
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.age.clickable, true);
    assert.equal(m.height.clickable, true);
    assert.equal(m.cup.clickable, true);
    assert.equal(m.count.clickable, false, '作品數無對應 pill 維度，恆不可點');
    assert.equal(m.bwh.clickable, false, '三圍無對應 pill 維度，恆不可點');
});

// ── fail-closed：值解析不出來就不可點，但文字仍在 ─────────────────────

test("fail-closed：height:'不明' → clickable=false，text 仍是 '不明'", () => {
    // 162a：罩杯 AA／小寫 b、年齡空字串／「不詳」併入同一支（同一失敗原因：解析不出來的值不得可點）
    const cases = [
        { over: { height: '不明' }, key: 'height', text: '不明' },
        { over: { cup: 'AA' }, key: 'cup', text: 'AAsearch.unit.cup' },
        { over: { cup: 'b' }, key: 'cup' },
        { over: { age: '' }, key: 'age', text: 'search.unit.age' },
        { over: { age: '不詳' }, key: 'age' },
    ];
    for (const c of cases) {
        const m = byKey(Object.assign({}, FULL_ACTRESS, c.over), true);
        assert.equal(m[c.key].clickable, false, JSON.stringify(c.over));
        if (c.text !== undefined) assert.equal(m[c.key].text, c.text, JSON.stringify(c.over));
    }
});

// ── dim / value 傳原始欄位值，不是顯示字串 ────────────────────────────

test('dim/value：height 傳原始 \'160cm\'（單位由 _setActressPill 剝），不是 160', () => {
    // 162a：cup 原始 'C'、age 原始 25 併入同一支（同一失敗原因：pill 值為顯示字串）
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.height.dim, 'height');
    assert.equal(m.height.value, '160cm');
    assert.equal(m.cup.dim, 'cup');
    assert.equal(m.cup.value, 'C');
    assert.notEqual(m.cup.value, m.cup.text, 'value 不得等於顯示字串');
    assert.equal(m.age.dim, 'age');
    assert.equal(m.age.value, 25);
});

// =====================================================================
// _onActressCardMetadataClick（124b-T4 / CD-124b-15）
// =====================================================================

test('_onActressCardMetadataClick：只呼叫 addActressPill(dim, value)，不呼叫 closeLightbox', () => {
    // 162a：toolbarOpen=true（手機摸得到 pill）與「不讀 actressLightboxSource 殘值」併入同一支
    const calls = [];
    const c = Object.assign({}, stateActress(), {
        actressLightboxSource: 'hero',   // 上一次開燈箱留下的殘值
        addActressPill: (dim, value) => calls.push(['addActressPill', dim, value]),
        closeLightbox: () => calls.push(['closeLightbox']),
    });
    _uiStore.toolbarOpen = false;
    c._onActressCardMetadataClick('height', '160cm');
    assert.deepEqual(calls, [['addActressPill', 'height', '160cm']], '殘值不得吞掉卡片點擊');
    assert.equal(Alpine.store('ui').toolbarOpen, true);
});

// =====================================================================
// _actressCardMiddle
// =====================================================================

function cardMiddle(actress, sort) {
    const c = Object.assign({}, stateActress(), { actressSort: sort });
    return c._actressCardMiddle(actress);
}

test('_actressCardMiddle：video_count:0 → 回傳非空字串 \'0showcase.unit.films\'', () => {
    // 162a：actress 為 null、video_count 缺欄位併入同一支
    const result = cardMiddle({ video_count: 0 }, 'video_count');
    assert.notEqual(result, '');
    assert.equal(result, '0showcase.unit.films');
    assert.equal(cardMiddle(null, 'video_count'), '');
    const missing = cardMiddle({ name: 'x' }, 'video_count');
    assert.equal(missing, '0showcase.unit.films');
    assert.ok(!missing.includes('undefined'));
});

// =====================================================================
// infoVisible 持久化
// =====================================================================

function makeBaseComponent(overrides) {
    const c = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    return Object.assign(c, overrides);
}

function stubWindow(opts) {
    const pathname = (opts && opts.pathname) || '/showcase';
    const search = (opts && opts.search) || '';
    globalThis.window.location = { pathname, search };
    globalThis.window.history = {
        replaceState() {},
    };
    globalThis.window.__SHOWCASE_CONFIG__ = (opts && opts.config) || {};
}

const RESTORE_CASES = [
    { input: true, expected: true, label: 'true → true' },
    { input: false, expected: false, label: 'false → false' },
    { input: undefined, expected: false, label: 'undefined（缺鍵）→ false' },
    { input: 'true', expected: false, label: "'true'（字串）→ false" },
    { input: 1, expected: false, label: '1（數字）→ false' },
];

for (const { input, expected, label } of RESTORE_CASES) {
    test(`restoreState()：infoVisible ${label}`, () => {
        stubWindow({ search: '' });
        const persisted = {
            sort: 'date',
            order: 'desc',
            page: 1,
            search: '',
            mode: 'grid',
            cardShape: 'cover',
        };
        if (input !== undefined) persisted.infoVisible = input;
        const c = makeBaseComponent({ _persistedShowcase: persisted, infoVisible: !expected });
        c.restoreState();
        assert.equal(c.infoVisible, expected);
    });
}

// =====================================================================
// S 鍵 gate
// =====================================================================

function makeKeydownComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const c = Object.assign({}, base, stateLightbox(), {
        mode: 'grid',
        showFavoriteActresses: false,
        infoVisible: false,
        _persistedShowcase: { infoVisible: false },
        // handleKeydown 在第 6 段之前的 guard 全部關死，讓按鍵落到第 6 段
        _pillEditor: null,
        _releaseEditor: null,
        similarModeOpen: false,
        similarModeMobileOpen: false,
        removeActressModalOpen: false,
        actressAddPanelOpen: false,
        _pickerOpen: false,
        rescrapeOpen: false,
        deleteVideoModalOpen: false,
        sampleGalleryOpen: false,
        lightboxOpen: false,
    }, overrides);
    // toggleInfo 定義在 state-base，Object.assign 展開的是自身屬性快照，
    // 但物件方法皆為一般函式屬性，assign 後仍指向同一份 this-bound-free 實作，
    // 呼叫時 this 綁定到 c 本身，行為與原本一致。
    return c;
}

function pressS(c) {
    c.handleKeydown({
        key: 'S',
        target: { tagName: 'BODY' },
        preventDefault() {},
        stopPropagation() {},
        ctrlKey: false,
        altKey: false,
        shiftKey: false,
        metaKey: false,
    });
}

test("S 鍵：mode='table' + showFavoriteActresses=true → toggleInfo 有被呼叫", () => {
    const c = makeKeydownComponent({ mode: 'table', showFavoriteActresses: true });
    const before = c.infoVisible;
    pressS(c);
    assert.notEqual(c.infoVisible, before);
    // 162a：影片牆（grid ＋ 非女優模式）按 S 照常切換併入同一支
    const g = makeKeydownComponent({ mode: 'grid', showFavoriteActresses: false });
    const gBefore = g.infoVisible;
    pressS(g);
    assert.notEqual(g.infoVisible, gBefore);
});

// T1 review 補測：gate 放寬成 `|| this.showFavoriteActresses` 之後，「女優燈箱開著時
// 按 S 不得切換資訊區」靠的是 handleKeydown 第 5 段（lightboxOpen 分支，
// state-lightbox.js:2476-2494）在第 6 段之前 return —— 保護來自**順序**而非旗標，
// 所以用測試把那個順序釘住（排序優先於旗標守衛）。
test('S 鍵：女優燈箱開啟時（lightboxOpen + currentLightboxActress + 女優模式）不得觸發 toggleInfo', () => {
    // 162a：影片燈箱開啟時同樣不得切換併入同一支
    const cases = [
        { mode: 'table', showFavoriteActresses: true, lightboxOpen: true, currentLightboxActress: { name: 'x' } },
        { mode: 'grid', showFavoriteActresses: false, lightboxOpen: true, currentLightboxActress: null },
    ];
    for (const over of cases) {
        const c = makeKeydownComponent(over);
        const before = c.infoVisible;
        pressS(c);
        assert.equal(c.infoVisible, before);
    }
});
