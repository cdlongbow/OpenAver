// TASK-133b-T3: restoreState 開頁還原時把表格／清單收斂回封面格。
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

// ===== DoD 3：收斂契約（table / list / grid；cardShape 原樣）=====

test('收斂：mode=table＋旗標關 → mode 變 grid，cardShape 原樣', () => {
    stubWindow({ search: '' });
    const c = makeComponent({
        _persistedShowcase: {
            mode: 'table',
            cardShape: 'poster',
        },
        mode: 'grid',
        cardShape: 'cover',
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
});

test('收斂：mode=list＋旗標關 → mode 變 grid，cardShape 原樣', () => {
    stubWindow({ search: '' });
    const c = makeComponent({
        _persistedShowcase: {
            mode: 'list',
            cardShape: 'cover',
        },
        mode: 'grid',
        cardShape: 'poster',
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'cover');
});

test('收斂：mode=grid＋旗標關 → mode 原樣 grid，cardShape 原樣', () => {
    stubWindow({ search: '' });
    const c = makeComponent({
        _persistedShowcase: {
            mode: 'grid',
            cardShape: 'poster',
        },
        mode: 'table',
        cardShape: 'cover',
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
});

// DoD 2 的第二條還原路徑：網址參數（書籤／分頁還原走同一條）。
// state-base.js:512 `urlParams.get('mode') || state.mode || 'grid'` ⇒ URL 優先於 localStorage，
// 兩條路徑都必須被收斂擋下（Opus 於 review 前補，plan §4 T3 DoD 2 的 node 對應）。
test('收斂：?mode=table（網址參數）＋旗標關 → mode 變 grid', () => {
    stubWindow({ search: '?mode=table' });
    const c = makeComponent({
        _persistedShowcase: { mode: 'grid', cardShape: 'poster' },
        mode: 'grid',
        cardShape: 'cover',
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
});

test('反向鎖：?mode=table（網址參數）＋旗標開 → 仍是 table', () => {
    stubWindow({ search: '?mode=table', config: { show_table_list: true } });
    const c = makeComponent({
        _persistedShowcase: { mode: 'grid', cardShape: 'cover' },
        mode: 'grid',
        cardShape: 'cover',
        showTableList: true,
    });
    c.restoreState();
    assert.equal(c.mode, 'table');
});

// ===== DoD 4：順序不變式（收斂在 perPage 降級閘上游）=====

test('收斂順序不變式：mode=table＋items_per_page=0＋旗標關 → mode===grid 且 perPage===120', () => {
    stubWindow({ search: '', config: { items_per_page: 0 } });
    const c = makeComponent({
        _persistedShowcase: {
            mode: 'table',
            cardShape: 'cover',
        },
        mode: 'grid',
        perPage: 90,
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c.perPage, 120);
});

// ===== DoD 5：反向鎖（旗標開不收斂）=====

test('反向鎖：旗標開＋mode=table → 仍是 table（不收斂）', () => {
    stubWindow({ search: '', config: { show_table_list: true } });
    const c = makeComponent({
        _persistedShowcase: {
            mode: 'table',
            cardShape: 'poster',
        },
        mode: 'grid',
        cardShape: 'cover',
        showTableList: true,
    });
    c.restoreState();
    assert.equal(c.mode, 'table');
    assert.equal(c.cardShape, 'poster');
});

// ===== DoD 6：不寫回（收斂後 _persistedShowcase.mode 仍是 table）=====

test('不寫回：收斂發生後 _persistedShowcase.mode 仍是 table', () => {
    stubWindow({ search: '' });
    const persisted = {
        mode: 'table',
        cardShape: 'poster',
    };
    const c = makeComponent({
        _persistedShowcase: persisted,
        mode: 'grid',
        cardShape: 'cover',
        showTableList: false,
    });
    c.restoreState();
    assert.equal(c.mode, 'grid');
    assert.equal(c._persistedShowcase.mode, 'table');
});
