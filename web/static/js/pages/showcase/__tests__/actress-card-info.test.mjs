// TASK-124b-T1: _actressInfoTokens / _actressCardMiddle 恆回作品數 / infoVisible 持久化 / S 鍵 gate。
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
// _actressInfoTokens
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

function tokensOf(actress, isNarrow) {
    const c = Object.assign({}, stateActress(), { _isNarrow: isNarrow });
    return c._actressInfoTokens(actress);
}

test('_isNarrow=true ＋ 五欄全有值 → 陣列長度 5，順序 [作品數, 年齡, 身高, 罩杯, 三圍]', () => {
    assert.deepEqual(tokensOf(FULL_ACTRESS, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        '160cm',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

test('_isNarrow=false ＋ 五欄全有值 → 陣列長度 3，順序 [身高, 罩杯, 三圍]（作品數/年齡不出現）', () => {
    assert.deepEqual(tokensOf(FULL_ACTRESS, false), [
        '160cm',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

test('缺 height（null）→ 該 token 不出現，其餘不受影響', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { height: null });
    assert.deepEqual(tokensOf(actress, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

test('缺 cup（undefined）→ 該 token 不出現，其餘不受影響', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { cup: undefined });
    assert.deepEqual(tokensOf(actress, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        '160cm',
        '88-58-88',
    ]);
});

test('缺 height（空字串）→ 該 token 不出現，其餘不受影響', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { height: '' });
    assert.deepEqual(tokensOf(actress, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

test('三圍缺一格（bust 為 null）→ 三圍整個 token 不出現', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { bust: null });
    assert.deepEqual(tokensOf(actress, true), [
        '12showcase.unit.films',
        '25search.unit.age',
        '160cm',
        'Csearch.unit.cup',
    ]);
});

test('actress 全空欄位（五欄皆 null）→ 回傳 []', () => {
    const actress = {
        video_count: null,
        age: null,
        height: null,
        cup: null,
        bust: null,
        waist: null,
        hip: null,
    };
    assert.deepEqual(tokensOf(actress, true), []);
});

test('actress 本身為 null → 回傳 []', () => {
    assert.deepEqual(tokensOf(null, true), []);
});

test('CD-124b-12 紅線：_isNarrow=true ＋ video_count:0 → 含字面 \'0showcase.unit.films\'；age:0 → 含字面 \'0search.unit.age\'', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { video_count: 0, age: 0 });
    assert.deepEqual(tokensOf(actress, true), [
        '0showcase.unit.films',
        '0search.unit.age',
        '160cm',
        'Csearch.unit.cup',
        '88-58-88',
    ]);
});

// =====================================================================
// _actressCardMiddle
// =====================================================================

function cardMiddle(actress, sort) {
    const c = Object.assign({}, stateActress(), { actressSort: sort });
    return c._actressCardMiddle(actress);
}

test('_actressCardMiddle：六種 actressSort 值下回傳字串完全相同（不再讀 this.actressSort）', () => {
    const actress = { video_count: 7 };
    const sorts = ['video_count', 'name', 'created_at', 'age', 'height', 'cup'];
    const results = sorts.map((sort) => cardMiddle(actress, sort));
    for (const r of results) {
        assert.equal(r, '7showcase.unit.films');
    }
});

test('_actressCardMiddle：video_count:0 → 回傳非空字串 \'0showcase.unit.films\'', () => {
    const result = cardMiddle({ video_count: 0 }, 'video_count');
    assert.notEqual(result, '');
    assert.equal(result, '0showcase.unit.films');
});

test('_actressCardMiddle：actress 為 null → 回傳 \'\'', () => {
    assert.equal(cardMiddle(null, 'video_count'), '');
});

// T1 review 補測（reviewer mutation ① 存活）：`|| 0` 這道防禦在改動前只有
// actressSort === 'video_count' 時跑得到，現在每張卡無條件跑。釘住它，避免日後
// 被當成冗餘刪掉後畫面印出 'undefined部作品'。
test('_actressCardMiddle：video_count 缺欄位（undefined）→ 回傳 \'0showcase.unit.films\'，不得出現 undefined', () => {
    const result = cardMiddle({ name: 'x' }, 'video_count');
    assert.equal(result, '0showcase.unit.films');
    assert.ok(!result.includes('undefined'));
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

test('toggleInfo()：false→true 後 _persistedShowcase.infoVisible 同步', () => {
    const c = makeBaseComponent({ infoVisible: false, _persistedShowcase: { infoVisible: false } });
    c.toggleInfo();
    assert.equal(c.infoVisible, true);
    assert.equal(c._persistedShowcase.infoVisible, true);
});

test('toggleInfo()：true→false 後 _persistedShowcase.infoVisible 同步', () => {
    const c = makeBaseComponent({ infoVisible: true, _persistedShowcase: { infoVisible: true } });
    c.toggleInfo();
    assert.equal(c.infoVisible, false);
    assert.equal(c._persistedShowcase.infoVisible, false);
});

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
});

test("S 鍵：mode='table' + showFavoriteActresses=false → toggleInfo 沒有被呼叫", () => {
    const c = makeKeydownComponent({ mode: 'table', showFavoriteActresses: false });
    const before = c.infoVisible;
    pressS(c);
    assert.equal(c.infoVisible, before);
});

test("S 鍵回歸：mode='grid' + showFavoriteActresses=false → 仍有反應（既有行為未被破壞）", () => {
    const c = makeKeydownComponent({ mode: 'grid', showFavoriteActresses: false });
    const before = c.infoVisible;
    pressS(c);
    assert.notEqual(c.infoVisible, before);
});

// T1 review 補測：gate 放寬成 `|| this.showFavoriteActresses` 之後，「女優燈箱開著時
// 按 S 不得切換資訊區」靠的是 handleKeydown 第 5 段（lightboxOpen 分支，
// state-lightbox.js:2476-2494）在第 6 段之前 return —— 保護來自**順序**而非旗標，
// 所以用測試把那個順序釘住（排序優先於旗標守衛）。
test('S 鍵：女優燈箱開啟時（lightboxOpen + currentLightboxActress + 女優模式）不得觸發 toggleInfo', () => {
    const c = makeKeydownComponent({
        mode: 'table',
        showFavoriteActresses: true,
        lightboxOpen: true,
        currentLightboxActress: { name: 'x' },
    });
    const before = c.infoVisible;
    pressS(c);
    assert.equal(c.infoVisible, before);
});

test('S 鍵：影片燈箱開啟時不得觸發 toggleInfo（既有行為，gate 放寬後仍成立）', () => {
    const c = makeKeydownComponent({
        mode: 'grid',
        showFavoriteActresses: false,
        lightboxOpen: true,
        currentLightboxActress: null,
    });
    const before = c.infoVisible;
    pressS(c);
    assert.equal(c.infoVisible, before);
});
