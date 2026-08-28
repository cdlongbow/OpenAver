// TASK-119-T3: cardShape 狀態與持久化（reactive 屬性 + restoreState/saveState wiring）。
//
// state-base.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。既有 search/__tests__/alias-loader.mjs 只做
// `@/` → `web/static/js/` 字首轉譯，對 `@/showcase/` 會解成錯誤路徑
// （importmap 實際指到 `pages/showcase/`）。比照 settings/save-access-auth.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（不改共用 loader）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay；
// 任務卡聲稱 open-local 的 window 存取皆在函式體內，實際並非如此。
// 比照 cover-fallback.test.mjs / confirm-edit-identity-guard.test.mjs 先 stub window。
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

const { serializePills, deserializePills } = await import('../../../shared/pill-filter.js');
const { stateBase } = await import('../state-base.js');

// ===== helpers =====

function makeComponent(overrides) {
    const c = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    return Object.assign(c, overrides);
}

function stubWindow(opts) {
    const pathname = (opts && opts.pathname) || '/showcase';
    const search = (opts && opts.search) || '';
    let lastReplaceUrl = null;
    globalThis.window.location = { pathname, search };
    globalThis.window.history = {
        replaceState(_state, _title, url) {
            lastReplaceUrl = url;
        },
    };
    globalThis.window.__SHOWCASE_CONFIG__ = (opts && opts.config) || {};
    return {
        get lastReplaceUrl() { return lastReplaceUrl; },
    };
}

// ===== cardShape persist / restore =====

// capture used so unused-var lint doesn't fire if lint ever covers tests
void serializePills;
void deserializePills;

test('無既存 localStorage → cardShape 為 cover', () => {
    stubWindow({ search: '' });
    const c = makeComponent();
    c.restoreState();
    assert.equal(c.cardShape, 'cover');
});

test('舊格式（_persistedShowcase 沒有 cardShape 鍵）→ cover，不拋錯', () => {
    stubWindow({ search: '' });
    const oldState = {
        sort: 'title',
        order: 'asc',
        page: 3,
        search: 'query',
        mode: 'list',
        showFavoriteActresses: false,
        actressSort: 'name',
        actressOrder: 'asc',
    };
    assert.equal(Object.prototype.hasOwnProperty.call(oldState, 'cardShape'), false);

    const c = makeComponent({
        _persistedShowcase: oldState,
        cardShape: 'poster',
        sort: 'date',
        order: 'desc',
        page: 1,
        search: '',
        mode: 'grid',
    });
    assert.doesNotThrow(() => c.restoreState());
    assert.equal(c.cardShape, 'cover');
});

const BAD_CARD_SHAPES = ['POSTER', 123, null, '', 'grid', {}, []];

for (const bad of BAD_CARD_SHAPES) {
    const label = typeof bad === 'string' ? JSON.stringify(bad) : Object.prototype.toString.call(bad) === '[object Array]' ? '[]' : (bad === null ? 'null' : (typeof bad === 'object' ? '{}' : String(bad)));
    test(`壞值 ${label} → cover`, () => {
        stubWindow({ search: '' });
        const c = makeComponent({
            _persistedShowcase: {
                sort: 'date',
                order: 'desc',
                page: 1,
                search: '',
                mode: 'grid',
                cardShape: bad,
            },
            cardShape: 'poster',
        });
        c.restoreState();
        assert.equal(c.cardShape, 'cover');
    });
}

test("'poster' → 'poster'", () => {
    stubWindow({ search: '' });
    const c = makeComponent({
        _persistedShowcase: {
            sort: 'date',
            order: 'desc',
            page: 1,
            search: '',
            mode: 'grid',
            cardShape: 'poster',
        },
        cardShape: 'cover',
    });
    c.restoreState();
    assert.equal(c.cardShape, 'poster');
});

test('saveState() 後 _persistedShowcase.cardShape === this.cardShape', () => {
    stubWindow();
    const c = makeComponent({ cardShape: 'poster' });
    c.saveState();
    assert.equal(c._persistedShowcase.cardShape, c.cardShape);
    assert.equal(c._persistedShowcase.cardShape, 'poster');
});

test('saveState：replaceState 捕捉到的 URL 字串不含 cardShape', () => {
    const stub = stubWindow({ pathname: '/showcase', search: '' });
    const c = makeComponent({
        cardShape: 'poster',
        search: 'hello',
        sort: 'title',
        order: 'asc',
        page: 2,
        mode: 'table',
    });
    c.saveState();
    const url = stub.lastReplaceUrl;
    assert.equal(typeof url, 'string');
    assert.ok(!url.includes('cardShape'), `URL must not contain cardShape, got: ${url}`);
});

test('reload 模擬：saveState → 新 stateBase 實例 restoreState → cardShape 一致', () => {
    // T2 hydrate 從 config 覆寫 showTableList；僅 makeComponent override 撐不過 restoreState
    stubWindow({ search: '', config: { show_table_list: true } });
    const c1 = makeComponent({
        cardShape: 'poster',
        sort: 'title',
        order: 'asc',
        page: 2,
        search: 'hello',
        mode: 'table',
    });
    c1.saveState();
    const savedBlob = c1._persistedShowcase;

    const c2 = makeComponent({
        _persistedShowcase: savedBlob,
        cardShape: 'cover',
        sort: 'date',
        order: 'desc',
        page: 1,
        search: '',
        mode: 'grid',
        showTableList: true,
    });
    c2.restoreState();
    assert.equal(c2.cardShape, 'poster');
    assert.equal(c2.sort, 'title');
    assert.equal(c2.order, 'asc');
    assert.equal(c2.page, 2);
    assert.equal(c2.mode, 'table');
});
