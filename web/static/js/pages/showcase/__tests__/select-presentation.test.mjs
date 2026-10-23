// TASK-119-T4 / TASK-133a-T2: selectPresentation() 協調器 ＋ animations.js 兩階段 Flip API
// （captureShapeState / playShapeMorph）。覆蓋 plan-119 §0.2 行為表七列、CD-133a-2 同一工作單元
// 契約（capture → 同步切 class → 同步 morph → 最後寫 state）、
// §0.4 CD-119-14（換模式一律委派 switchMode()；零 this.mode = 賦值的源碼守衛已搬 lint）。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。比照既有 pill-clear.test.mjs / pill-match.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（FE-GUARD-11，不改共用 loader）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

// open-local.js → path-utils.js 在模組頂層寫 window.pathToDisplay。
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

const { stateVideos } = await import('../state-videos.js');
const { _setFilteredVideos } = await import('../state-base.js');

// ===== helpers =====

const FAKE_GRID = {
    id: 'fake-grid',
    _classOps: [],                                   // [[name, force], ...] 依序記錄
    classList: {
        toggle(name, force) { FAKE_GRID._classOps.push([name, force]); },
    },
};

function makeComponent(overrides) {
    FAKE_GRID._classOps.length = 0;
    const c = Object.assign({}, stateVideos(), {
        mode: 'grid',
        cardShape: 'cover',
        perPage: 60,
        page: 1,
        totalPages: 1,
        saveCalls: 0,
        saveState() { c.saveCalls++; },
        $nextTick(fn) { fn(); },
        _getActiveGrid() { return FAKE_GRID; },
    }, overrides);
    return c;
}

/** 暫時掛上 window.ShowcaseAnimations stub，測完還原（避免污染其他測試）。 */
function withAnimStub(stub, fn) {
    const prev = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = stub;
    try {
        fn();
    } finally {
        if (prev === undefined) delete globalThis.window.ShowcaseAnimations;
        else globalThis.window.ShowcaseAnimations = prev;
    }
}

// =====================================================================
// §0.2 行為表 —— 七列各至少一支測試
// =====================================================================


test('§0.2 行5（v1 P2-2 的洞）：table 點「直式海報」→ 同時斷言 mode===grid 且 cardShape===poster', () => {
    const c = makeComponent({ mode: 'table', cardShape: 'cover', perPage: 60 });
    c.selectPresentation('poster');
    assert.equal(c.mode, 'grid');
    assert.equal(c.cardShape, 'poster');
});

test('§0.2 行6（v2 P2 的洞）：table ＋ perPage=0 點「直式海報」→ perPage 降級 120、updatePagination 真跑、page clamp', () => {
    _setFilteredVideos(Array.from({ length: 500 }, (_, i) => ({ path: 'v' + i })));
    try {
        const c = makeComponent({ mode: 'table', cardShape: 'cover', perPage: 0, page: 50, totalPages: 1 });
        let upCalls = 0;
        const realUpdatePagination = c.updatePagination.bind(c);
        c.updatePagination = function () { upCalls++; return realUpdatePagination(); };
        c.selectPresentation('poster');
        assert.equal(c.mode, 'grid');
        assert.equal(c.cardShape, 'poster');
        assert.equal(c.perPage, 120);
        assert.equal(upCalls, 1, 'updatePagination() 必須真的被呼叫（走 switchMode 的降級路徑）');
        assert.equal(c.totalPages, Math.ceil(500 / 120));
        assert.equal(c.page, c.totalPages, 'page 必須被 clamp 到有效範圍內');
    } finally {
        _setFilteredVideos([]);
    }
});

// =====================================================================
// 契約
// =====================================================================


// TASK-133a-T2 review P3：morph 現在排在 cardShape/saveState **之前**（同一工作單元的重排）。
// 重排之前它在 $nextTick 回呼裡，拋錯天生擋不到 state 寫入；重排之後就擋得到了。
// 使用者流程：GSAP 載到一半／Flip 沒註冊成功 → playShapeMorph 拋錯 → 按海報鈕
// 「完全沒反應」（卡型沒變也沒存），而不是「切換了只是沒動畫」。
test('契約：playShapeMorph 拋錯時，卡型仍必須切換並持久化（不得吃掉 state 寫入）', () => {
    withAnimStub({
        captureShapeState() { return { state: {}, cards: [{}] }; },
        playShapeMorph() { throw new Error('boom'); },
    }, () => {
        const c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        assert.doesNotThrow(() => c.selectPresentation('poster'));
        assert.equal(c.cardShape, 'poster', '動畫拋錯不得吃掉 cardShape 寫入');
        assert.equal(c.saveCalls, 1, '動畫拋錯不得吃掉 saveState()');
        assert.deepEqual(
            FAKE_GRID._classOps,
            [['shape-poster', true]],
            '版面 class 在 morph 之前就切好了，拋錯不影響它',
        );
    });
});

// =====================================================================
// animations.js：captureShapeState / playShapeMorph（兩階段 Flip 順序；視覺行為由 T8 CDP 驗）
// =====================================================================

