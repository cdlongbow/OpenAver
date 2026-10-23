// TASK-116a-T2: actressPills 狀態層 — add/remove、型別正規化、不持久化、不走 _sortWithFlip。
//
// state-actress.js / state-base.js 用瀏覽器 importmap 別名；plain node --test 不認得。
// 比照 actress-sort.test.mjs / pill-clear.test.mjs，本檔自帶 resolve hook（FE-GUARD-11）。

import { test } from 'node:test';
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


/**
 * 合併 stateBase + stateActress 的 harness。
 * $persist stub 比照 pill-persist.test.mjs:55-58。
 */
function makeComponent(overrides) {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const actress = stateActress();
    const c = Object.assign({}, base, actress, {
        actressSearch: '',
        actressSort: 'video_count',
        actressOrder: 'desc',
        sortFlipCalls: 0,
        _sortWithFlip(fn) {
            c.sortFlipCalls++;
            if (typeof fn === 'function') fn();
        },
    }, overrides);
    // 確保 actressPills 有預設（stateBase 已宣告；overrides 可覆寫）
    if (!Array.isArray(c.actressPills)) c.actressPills = [];
    _setActresses([
        { name: 'full', age: 37, height: '160cm', cup: 'B' },
        { name: 'tall', age: 25, height: '170cm', cup: 'C' },
    ]);
    return c;
}

// ── addActressPill 物件形狀（CD-116b-1：恆四欄位、height 剝單位）────────────

test('addActressPill(height, "160cm")：完整物件 deepEqual 四欄位 value 剝單位', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    assert.equal(c.actressPills.length, 1);
    assert.deepEqual(c.actressPills[0], { dim: 'height', op: '=', value: '160', value2: null });
});


// ── 型別正規化（產品真實型別：age 是 number）──────────────────────────────


test('removeActressPill(age, 37 number) 能移除 number 新增的 pill', () => {
    const c = makeComponent();
    c.addActressPill('age', 37);
    assert.equal(c.actressPills.length, 1);
    c.removeActressPill('age', 37);
    assert.equal(c.actressPills.length, 0);
});


// ── 同維度取代 ─────────────────────────────────────────────────────────────

test('同維度取代：add age 30 再 add age 32 → length 1 且 value "32"', () => {
    const c = makeComponent();
    c.addActressPill('age', '30');
    c.addActressPill('age', '32');
    assert.equal(c.actressPills.length, 1);
    assert.deepEqual(c.actressPills[0], { dim: 'age', op: '=', value: '32', value2: null });
});

// ── removeActressPill ──────────────────────────────────────────────────────


// ── _setActressPill 直呼契約（CD-116b-1b）──────────────────────────────────


// ── 116b review 修正：height 剝單位 fail-closed / value2 對稱 ───────────────


// ── 過濾效果 ───────────────────────────────────────────────────────────────

test('addActressPill 後 applyActressFilterAndSort 真的過濾', () => {
    const c = makeComponent();
    c.addActressPill('height', '160cm');
    assert.equal(c.filteredActressCount, 1);
    assert.equal(c.paginatedActresses[0].name, 'full');
});

// ── CD-116a-9：不走 _sortWithFlip ──────────────────────────────────────────


// ── 不持久化（CD-116a-5）───────────────────────────────────────────────────


// ── 持久化（129-T2 / CD-129-6）──────────────────────────────────────────────

function stubWindow(opts) {
    const pathname = (opts && opts.pathname) || '/showcase';
    const search = (opts && opts.search) || '';
    globalThis.window.location = { pathname, search };
    globalThis.window.history = {
        replaceState() {},
    };
}


test('持久化：restoreState() 能把 actressSearch 讀回，無值時預設為空字串', () => {
    stubWindow({ search: '' });
    const c = makeComponent({
        _persistedShowcase: {
            actressSearch: '三上悠亞',
        },
        actressSearch: '',
    });
    c.restoreState();
    assert.equal(c.actressSearch, '三上悠亞');

    const cEmpty = makeComponent({
        _persistedShowcase: {},
        actressSearch: '既有殘留',
    });
    cEmpty.restoreState();
    assert.equal(cEmpty.actressSearch, '');
});


// ── 129-T2：光是欄位進了 _persistedShowcase 還不夠，得有人呼叫 saveState() ──
//
// Why 這條存在：影片側 onSearchChange() 的 saveState() 是搭 _animateFilter() 的便車
// （state-videos.js:517），女優側刻意不走 _animateFilter，所以打字這條路**沒有**
// 任何 saveState()。上面那三條契約（欄位存在／saveState 寫入／restoreState 讀回）
// 全綠的情況下，使用者打字仍然不會被存下來——這個洞只有真的跑一次打字流程才看得到。
// （129-T2 的 CDP 驗收就是這樣抓到的。）


// 同一條回歸的黑盒版本（sonnet review 建議）：不 stub 任何東西，直接看「打完字之後
// _persistedShowcase 裡有沒有東西」。好處是——把 saveState() 的呼叫搬進
// applyActressFilterAndSort()（行為不變的重構）時這條仍然綠，而上面那條會無謂變紅。
// 兩條一起留：上面那條鎖「呼叫次數契約」（卡片 AC-6 的字面），這條鎖「使用者要的結果」。
test('打字：onActressSearchChange() 之後 _persistedShowcase.actressSearch 真的有值（黑盒）', () => {
    stubWindow();
    const c = makeComponent();
    c.actressSearch = '三上';
    c.onActressSearchChange();
    assert.equal(c._persistedShowcase.actressSearch, '三上',
        '打字之後值必須已經進到 _persistedShowcase（不然重整就不見了）');
});
