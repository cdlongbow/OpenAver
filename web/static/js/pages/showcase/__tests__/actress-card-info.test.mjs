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

test('_isNarrow=true ＋ 五欄全有值 → 長度 5，key 順序 [count, age, height, cup, bwh]', () => {
    assert.deepEqual(keysOf(FULL_ACTRESS, true), ['count', 'age', 'height', 'cup', 'bwh']);
});

test('_isNarrow=false ＋ 五欄全有值 → 長度 4，key 順序 [age, height, cup, bwh]（作品數不出現，年齡出現）', () => {
    assert.deepEqual(keysOf(FULL_ACTRESS, false), ['age', 'height', 'cup', 'bwh']);
});

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
    const actress = Object.assign({}, FULL_ACTRESS, { height: null });
    assert.deepEqual(keysOf(actress, true), ['count', 'age', 'cup', 'bwh']);
});

test('缺 cup（undefined）→ 該 part 不出現，其餘不受影響', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { cup: undefined });
    assert.deepEqual(keysOf(actress, true), ['count', 'age', 'height', 'bwh']);
});

test('缺 height（空字串）→ 該 part 不出現，其餘不受影響', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { height: '' });
    assert.deepEqual(keysOf(actress, true), ['count', 'age', 'cup', 'bwh']);
});

test('三圍缺一格（bust 為 null）→ 三圍整個 part 不出現', () => {
    const actress = Object.assign({}, FULL_ACTRESS, { bust: null });
    assert.deepEqual(keysOf(actress, true), ['count', 'age', 'height', 'cup']);
});

test('actress 全空欄位（五欄皆 null）→ 回傳 []（窄寬皆然：整塊資訊區不渲染）', () => {
    const actress = {
        video_count: null, age: null, height: null, cup: null,
        bust: null, waist: null, hip: null,
    };
    assert.deepEqual(partsOf(actress, true), []);
    assert.deepEqual(partsOf(actress, false), []);
});

test('actress 本身為 null → 回傳 []', () => {
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

test('clickable：寬螢幕下三格同樣可點、bwh 同樣不可點（無斷點分支）', () => {
    const m = byKey(FULL_ACTRESS, false);
    assert.equal(m.age.clickable, true);
    assert.equal(m.height.clickable, true);
    assert.equal(m.cup.clickable, true);
    assert.equal(m.bwh.clickable, false);
    assert.equal(m.count, undefined, '寬螢幕作品數整格不出現');
});

// ── fail-closed：值解析不出來就不可點，但文字仍在 ─────────────────────

test("fail-closed：height:'不明' → clickable=false，text 仍是 '不明'", () => {
    const m = byKey(Object.assign({}, FULL_ACTRESS, { height: '不明' }), true);
    assert.equal(m.height.clickable, false);
    assert.equal(m.height.text, '不明');
});

test("fail-closed：cup:'AA'（多字元）→ clickable=false，text 仍在", () => {
    const m = byKey(Object.assign({}, FULL_ACTRESS, { cup: 'AA' }), true);
    assert.equal(m.cup.clickable, false);
    assert.equal(m.cup.text, 'AAsearch.unit.cup');
});

test("fail-closed：cup:'b'（小寫）→ clickable=false", () => {
    assert.equal(byKey(Object.assign({}, FULL_ACTRESS, { cup: 'b' }), true).cup.clickable, false);
});

test("fail-closed：age:'' → part 仍出現（!= null，CD-124b-12）、clickable=false、text 是單獨的單位字", () => {
    const m = byKey(Object.assign({}, FULL_ACTRESS, { age: '' }), true);
    assert.equal(m.age.clickable, false);
    assert.equal(m.age.text, 'search.unit.age', '既有行為逐字保留：空字串年齡會印出孤零零的單位');
});

test("fail-closed：age:'不詳'（非數字）→ clickable=false", () => {
    assert.equal(byKey(Object.assign({}, FULL_ACTRESS, { age: '不詳' }), true).age.clickable, false);
});

// ── dim / value 傳原始欄位值，不是顯示字串 ────────────────────────────

test('dim/value：height 傳原始 \'160cm\'（單位由 _setActressPill 剝），不是 160', () => {
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.height.dim, 'height');
    assert.equal(m.height.value, '160cm');
});

test('dim/value：cup 傳原始 \'C\'，不是顯示字串 \'C罩杯\'', () => {
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.cup.dim, 'cup');
    assert.equal(m.cup.value, 'C');
    assert.notEqual(m.cup.value, m.cup.text, 'value 不得等於顯示字串');
});

test('dim/value：age 傳原始數值 25', () => {
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.age.dim, 'age');
    assert.equal(m.age.value, 25);
});

test('不可點的 part 不帶 dim/value（避免誤用）', () => {
    const m = byKey(FULL_ACTRESS, true);
    assert.equal(m.count.dim, undefined);
    assert.equal(m.count.value, undefined);
    assert.equal(m.bwh.dim, undefined);
    assert.equal(m.bwh.value, undefined);
});

// =====================================================================
// _onActressCardMetadataClick（124b-T4 / CD-124b-15）
// =====================================================================

test('_onActressCardMetadataClick：只呼叫 addActressPill(dim, value)，不呼叫 closeLightbox', () => {
    const calls = [];
    const c = Object.assign({}, stateActress(), {
        addActressPill: (dim, value) => calls.push(['addActressPill', dim, value]),
        closeLightbox: () => calls.push(['closeLightbox']),
    });
    _uiStore.toolbarOpen = false;
    c._onActressCardMetadataClick('height', '160cm');
    assert.deepEqual(calls, [['addActressPill', 'height', '160cm']]);
});

test('_onActressCardMetadataClick：產生 pill 後 toolbarOpen=true（手機摸得到 pill）', () => {
    const c = Object.assign({}, stateActress(), { addActressPill: () => {} });
    _uiStore.toolbarOpen = false;
    c._onActressCardMetadataClick('cup', 'C');
    assert.equal(Alpine.store('ui').toolbarOpen, true);
});

test('_onActressCardMetadataClick：不讀 actressLightboxSource（卡片路徑沒有燈箱來源殘值問題）', () => {
    const calls = [];
    const c = Object.assign({}, stateActress(), {
        actressLightboxSource: 'hero',   // 上一次開燈箱留下的殘值
        addActressPill: (dim, value) => calls.push([dim, value]),
    });
    _uiStore.toolbarOpen = false;
    c._onActressCardMetadataClick('age', 25);
    assert.deepEqual(calls, [['age', 25]], '殘值不得吞掉卡片點擊');
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
