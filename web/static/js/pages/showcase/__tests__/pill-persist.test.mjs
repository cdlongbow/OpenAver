// TASK-115-T3: pill 持久化（serializePills / deserializePills + saveState/restoreState wiring）。
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

// ===== Layer 1: release pill 序列化 round-trip（TASK-124a-T1） =====

test('TASK-124a-T1：round-trip — serializePills → deserializePills 帶 op/value2 逐欄位相等', () => {
    // 併入原「op === "range" 的 pill 帶 value2」案例：單值 pill 與 range pill 各自逐欄位相等
    const pills = [
        { dim: 'release', op: '=', value: '2024-09' },
        { dim: 'release', op: 'range', value: '2023', value2: '2024-06' },
    ];
    assert.deepEqual(deserializePills(serializePills(pills)), pills);
});

// ===== Layer 2: wiring via stateBase saveState / restoreState =====

test('saveState：replaceState 捕捉到的 URL 字串不含 pills', () => {
    const stub = stubWindow({ pathname: '/showcase', search: '' });
    const c = makeComponent({
        pills: [{ dim: 'maker', value: 'Moodyz' }],
        search: 'hello',
        sort: 'title',
        order: 'asc',
        page: 2,
        mode: 'table',
    });
    c.saveState();
    const url = stub.lastReplaceUrl;
    assert.equal(typeof url, 'string');
    assert.ok(!url.includes('pills'), `URL must not contain pills, got: ${url}`);
});

test('restoreState：缺 pills 鍵（舊格式）→ this.pills=[]，不 throw，其餘欄位照常還原', () => {
    // T2 hydrate 從 config 覆寫 showTableList；僅 makeComponent override 撐不過 restoreState
    stubWindow({ search: '', config: { show_table_list: true } });
    // 模擬 $persist 整包取代：舊 showcase_state 沒有 pills 屬性
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
    // 刻意不帶 pills
    assert.equal(Object.prototype.hasOwnProperty.call(oldState, 'pills'), false);

    const c = makeComponent({
        _persistedShowcase: oldState,
        pills: [{ dim: 'maker', value: 'should-be-cleared' }],
        sort: 'date',
        order: 'desc',
        page: 1,
        search: '',
        mode: 'grid',
        showTableList: true,
    });
    assert.doesNotThrow(() => c.restoreState());
    assert.deepEqual(c.pills, []);
    assert.equal(c.sort, 'title');
    assert.equal(c.order, 'asc');
    assert.equal(c.page, 3);
    assert.equal(c.mode, 'list');
});

test('URL 含 ?pills=... 不產生任何 pill', () => {
    stubWindow({ search: '?pills=maker%3A%3AMoodyz&sort=title' });
    const c = makeComponent({
        _persistedShowcase: {
            sort: 'date',
            order: 'desc',
            page: 1,
            search: '',
            mode: 'grid',
            // no pills key — old format
        },
        pills: [{ dim: 'tag', value: 'pre-existing' }],
    });
    c.restoreState();
    // URL pills param is ignored; only deserializePills(state.pills) applies
    assert.deepEqual(c.pills, []);
    // URL sort still wins for sort
    assert.equal(c.sort, 'title');
});

test('reload 模擬：saveState → 新 stateBase 實例 restoreState → pills 深相等', () => {
    // T2 hydrate 從 config 覆寫 showTableList；僅 makeComponent override 撐不過 restoreState
    stubWindow({ search: '', config: { show_table_list: true } });
    const originalPills = [
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'series', value: 'Madonna' },
    ];
    const c1 = makeComponent({
        pills: originalPills.slice(),
        sort: 'title',
        order: 'asc',
        page: 2,
        search: 'hello',
        mode: 'table',
    });
    c1.saveState();
    const savedBlob = c1._persistedShowcase;

    // 模擬 reload：全新元件，_persistedShowcase 帶著上一輪存下的內容
    const c2 = makeComponent({
        _persistedShowcase: savedBlob,
        pills: [],
        sort: 'date',
        order: 'desc',
        page: 1,
        search: '',
        mode: 'grid',
        showTableList: true,
    });
    c2.restoreState();
    assert.deepEqual(c2.pills, originalPills);
    assert.equal(c2.sort, 'title');
    assert.equal(c2.order, 'asc');
    assert.equal(c2.page, 2);
    assert.equal(c2.mode, 'table');
});
