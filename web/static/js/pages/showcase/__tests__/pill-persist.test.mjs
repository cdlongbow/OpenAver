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

// ===== Layer 1: pure serializePills / deserializePills =====

test('serializePills：非陣列/nullish 輸入 → []', () => {
    assert.deepEqual(serializePills(undefined), []);
    assert.deepEqual(serializePills(null), []);
    assert.deepEqual(serializePills('maker::Moodyz'), []);
    assert.deepEqual(serializePills(42), []);
    assert.deepEqual(serializePills({ dim: 'maker', value: 'Moodyz' }), []);
});

test('serializePills：deep-copy identity（陣列與元素皆非同一參照）', () => {
    const input = [
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'series', value: 'Madonna' },
    ];
    const out = serializePills(input);
    assert.deepEqual(out, input);
    assert.notEqual(out, input);
    assert.notEqual(out[0], input[0]);
    assert.notEqual(out[1], input[1]);
});

test('deserializePills：undefined（舊格式鍵不存在）→ []，不 throw', () => {
    assert.deepEqual(deserializePills(undefined), []);
});

test('deserializePills：null/字串/數字/物件（非陣列）→ []，不 throw', () => {
    assert.deepEqual(deserializePills(null), []);
    assert.deepEqual(deserializePills('maker::Moodyz'), []);
    assert.deepEqual(deserializePills(0), []);
    assert.deepEqual(deserializePills({ dim: 'maker', value: 'Moodyz' }), []);
});

test('deserializePills：元素為 null/undefined/字串/數字/陣列（非 plain object）→ 丟棄', () => {
    const out = deserializePills([
        null,
        undefined,
        'maker',
        7,
        ['maker', 'Moodyz'],
        { dim: 'maker', value: 'Moodyz' },
    ]);
    assert.deepEqual(out, [{ dim: 'maker', value: 'Moodyz' }]);
});

test('deserializePills：缺 dim/value、非字串型別、trim 後空字串 → 丟棄', () => {
    const out = deserializePills([
        { value: 'Moodyz' },
        { dim: 'maker' },
        { dim: 1, value: 'Moodyz' },
        { dim: 'maker', value: 2 },
        { dim: true, value: 'Moodyz' },
        { dim: 'maker', value: false },
        { dim: ['maker'], value: 'Moodyz' },
        { dim: 'maker', value: ['Moodyz'] },
        { dim: { a: 1 }, value: 'Moodyz' },
        { dim: 'maker', value: { a: 1 } },
        { dim: '   ', value: 'Moodyz' },
        { dim: 'maker', value: '   ' },
        { dim: '', value: 'Moodyz' },
        { dim: 'maker', value: '' },
        { dim: ' maker ', value: ' Moodyz ' },
    ]);
    assert.deepEqual(out, [{ dim: 'maker', value: 'Moodyz' }]);
});

test('deserializePills：混合合法與非法元素 → 只保留合法、相對順序不變', () => {
    const out = deserializePills([
        { dim: 'maker', value: 'Moodyz' },
        null,
        { dim: 'series', value: 'Madonna' },
        { dim: '', value: 'x' },
        { dim: 'tag', value: '女仆' },
    ]);
    assert.deepEqual(out, [
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'series', value: 'Madonna' },
        { dim: 'tag', value: '女仆' },
    ]);
});

test('deserializePills：回傳元素物件與 raw 原始物件非同一參照', () => {
    const raw0 = { dim: 'maker', value: 'Moodyz' };
    const raw = [raw0];
    const out = deserializePills(raw);
    assert.deepEqual(out, [{ dim: 'maker', value: 'Moodyz' }]);
    assert.notEqual(out, raw);
    assert.notEqual(out[0], raw0);
});

// ===== TASK-124a-T1：release pill 序列化 round-trip ＋ CD-124a-11 fail-safe =====

test('TASK-124a-T1：serializePills 對非 release pill 的輸出逐鍵逐值不變（恰兩鍵，不多不少）', () => {
    const out = serializePills([{ dim: 'actress', value: 'x' }]);
    assert.deepEqual(out, [{ dim: 'actress', value: 'x' }]);
    assert.deepEqual(Object.keys(out[0]), ['dim', 'value']);
});

test('TASK-124a-T1：serializePills 對 release pill 帶出 op（非 range 不帶 value2）', () => {
    const out = serializePills([{ dim: 'release', op: '=', value: '2024-09' }]);
    assert.deepEqual(out, [{ dim: 'release', value: '2024-09', op: '=' }]);
    assert.deepEqual(new Set(Object.keys(out[0])), new Set(['dim', 'value', 'op']));
});

test('TASK-124a-T1：serializePills 對 range release pill 帶出 op + value2', () => {
    const out = serializePills([{ dim: 'release', op: 'range', value: '2023', value2: '2024-06' }]);
    assert.deepEqual(out, [{ dim: 'release', value: '2023', op: 'range', value2: '2024-06' }]);
    assert.deepEqual(new Set(Object.keys(out[0])), new Set(['dim', 'value', 'op', 'value2']));
});

test('TASK-124a-T1：round-trip — serializePills → deserializePills 帶 op/value2 逐欄位相等', () => {
    const pills = [{ dim: 'release', op: '=', value: '2024-09' }];
    assert.deepEqual(deserializePills(serializePills(pills)), pills);
});

test('TASK-124a-T1：round-trip — op === "range" 的 pill 帶 value2', () => {
    const pills = [{ dim: 'release', op: 'range', value: '2023', value2: '2024-06' }];
    assert.deepEqual(deserializePills(serializePills(pills)), pills);
});

test('TASK-124a-T1：CD-124a-11 四種畸形各丟棄一枚，不影響同陣列其他 pill', () => {
    const out = deserializePills([
        { dim: 'release', op: '=', value: '2024-09' },          // 合法 1：release
        { dim: 'actress', value: 'x' },                          // 合法 2：非 release
        { dim: 'release', op: '!=', value: '2024' },             // 畸形 1：op 不在白名單
        { dim: 'release', op: 'range', value: '2023' },          // 畸形 2：range 缺 value2
        { dim: 'release', op: '=', value: '09/2023' },           // 畸形 3：value 形狀不合法
        { dim: 'release', op: 'range', value: '2023', value2: '2023/09' }, // 畸形 4：value2 形狀不合法
    ]);
    assert.deepEqual(out, [
        { dim: 'release', value: '2024-09', op: '=' },
        { dim: 'actress', value: 'x' },
    ]);
});

// ===== Layer 2: wiring via stateBase saveState / restoreState =====

test('saveState：_persistedShowcase.pills 深相等但陣列與元素皆非同一參照', () => {
    const stub = stubWindow();
    const pills = [
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'series', value: 'Madonna' },
    ];
    const c = makeComponent({ pills });
    c.saveState();
    assert.deepEqual(c._persistedShowcase.pills, pills);
    assert.notEqual(c._persistedShowcase.pills, c.pills);
    assert.notEqual(c._persistedShowcase.pills[0], c.pills[0]);
    assert.notEqual(c._persistedShowcase.pills[1], c.pills[1]);
    // capture used so unused-var lint doesn't fire if lint ever covers tests
    assert.ok(stub);
});

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

test('CD-3 端到端：saveState 後改 this.pills 不再 save → _persistedShowcase 仍是存檔當下', () => {
    stubWindow();
    const saved = [{ dim: 'maker', value: 'Moodyz' }];
    const c = makeComponent({ pills: saved });
    c.saveState();
    const snapshot = c._persistedShowcase.pills;
    // (1) 整包替換 this.pills（T1 正規路徑）— 即使 serialize 偷懶回同一陣列，整包替換也不會污染已存檔
    c.pills = [{ dim: 'series', value: 'Madonna' }, { dim: 'tag', value: '女仆' }];
    assert.deepEqual(c._persistedShowcase.pills, [{ dim: 'maker', value: 'Moodyz' }]);
    assert.equal(c._persistedShowcase.pills, snapshot);
    // (2) 元素物件原地 mutate（CD-3 真正要防的未文件化行為）— 必須切斷元素參照才擋得住
    //    重新 save 一次，再用存檔當下那份陣列裡的元素物件做原地改寫
    c.pills = [{ dim: 'maker', value: 'Moodyz' }];
    c.saveState();
    const afterSave = c._persistedShowcase.pills;
    c.pills[0].value = 'CHANGED-IN-PLACE';
    assert.deepEqual(afterSave, [{ dim: 'maker', value: 'Moodyz' }]);
    assert.notEqual(afterSave[0], c.pills[0]);
});

test('restoreState：缺 pills 鍵（舊格式）→ this.pills=[]，不 throw，其餘欄位照常還原', () => {
    stubWindow({ search: '' });
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
    });
    assert.doesNotThrow(() => c.restoreState());
    assert.deepEqual(c.pills, []);
    assert.equal(c.sort, 'title');
    assert.equal(c.order, 'asc');
    assert.equal(c.page, 3);
    assert.equal(c.mode, 'list');
});

test('restoreState：_persistedShowcase.pills 混雜垃圾 → 不 throw，只保留合法 {dim,value}', () => {
    stubWindow({ search: '' });
    const junk = [
        { dim: 'maker', value: 'Moodyz' },
        null,
        'bad',
        { dim: '', value: 'x' },
        { dim: 'series', value: 'Madonna' },
        { dim: 1, value: 'nope' },
        { dim: 'tag', value: '女仆' },
    ];
    const c = makeComponent({
        _persistedShowcase: {
            sort: 'date',
            order: 'desc',
            page: 1,
            search: '',
            mode: 'grid',
            pills: junk,
        },
        pills: [],
    });
    assert.doesNotThrow(() => c.restoreState());
    assert.deepEqual(c.pills, [
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'series', value: 'Madonna' },
        { dim: 'tag', value: '女仆' },
    ]);
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
    stubWindow({ search: '' });
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
    });
    c2.restoreState();
    assert.deepEqual(c2.pills, originalPills);
    assert.equal(c2.sort, 'title');
    assert.equal(c2.order, 'asc');
    assert.equal(c2.page, 2);
    assert.equal(c2.mode, 'table');
});
