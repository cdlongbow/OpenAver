// TASK-119-T4 / TASK-133a-T2: selectPresentation() 協調器 ＋ animations.js 兩階段 Flip API
// （captureShapeState / playShapeMorph）。覆蓋 plan-119 §0.2 行為表七列、CD-133a-2 同一工作單元
// 契約（capture → 同步切 class → 同步 morph → 最後寫 state；該分支零 $nextTick）、
// §0.4 CD-119-14（換模式一律委派 switchMode()，selectPresentation 內零 this.mode = 賦值）。
//
// state-videos.js 用瀏覽器 importmap 別名 `@/showcase/...` 與 `@/shared/...`，
// plain `node --test` 不認得。比照既有 pill-clear.test.mjs / pill-match.test.mjs，
// 本檔自帶與 base.html importmap 對齊的 resolve hook（FE-GUARD-11，不改共用 loader）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync } from 'node:fs';

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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const STATE_VIDEOS_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/state-videos.js'),
    'utf8',
);
const ANIMATIONS_SRC = readFileSync(
    path.join(REPO_ROOT, 'web/static/js/pages/showcase/animations.js'),
    'utf8',
);

// ===== helpers =====

/**
 * 抽出函式本體（比照 pill-clear.test.mjs 讀 STATE_VIDEOS_SRC 對源碼下斷言的先例）。
 * 同時支援方法簡寫 `name(...) {` 與 animations.js 慣用的 `name: function (...) {`。
 */
function extractFnBody(src, name) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(escaped + '\\s*(?::\\s*function)?\\s*\\([^)]*\\)\\s*\\{');
    const m = re.exec(src);
    if (!m) return null;
    const open = src.indexOf('{', m.index);
    let depth = 0;
    for (let i = open; i < src.length; i++) {
        const ch = src[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return src.slice(open + 1, i);
        }
    }
    return null;
}

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

test('§0.2 行1：grid+cover 點「直式海報」→ mode 不變、cardShape=poster、播 morph、saveState 恰一次', () => {
    let captureCalls = 0;
    let morphCalls = 0;
    let morphGridArg = null;
    withAnimStub({
        captureShapeState() { captureCalls++; return 'SNAP'; },
        playShapeMorph(_captured, gridEl) { morphCalls++; morphGridArg = gridEl; },
    }, () => {
        const c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        c.selectPresentation('poster');
        assert.equal(c.mode, 'grid');
        assert.equal(c.cardShape, 'poster');
        assert.equal(captureCalls, 1);
        assert.equal(morphCalls, 1);
        assert.equal(c.saveCalls, 1);
        assert.equal(morphGridArg, FAKE_GRID);
    });
});

test('§0.2 行2（反向，§0.1 的洞）：grid+poster 點「完整封面」→ mode 不變、cardShape=cover、播 morph', () => {
    let captureCalls = 0;
    let morphCalls = 0;
    withAnimStub({
        captureShapeState() { captureCalls++; return 'SNAP'; },
        playShapeMorph() { morphCalls++; },
    }, () => {
        const c = makeComponent({ mode: 'grid', cardShape: 'poster' });
        c.selectPresentation('cover');
        assert.equal(c.mode, 'grid');
        assert.equal(c.cardShape, 'cover');
        assert.equal(captureCalls, 1);
        assert.equal(morphCalls, 1);
        assert.equal(c.saveCalls, 1);
    });
});

for (const target of ['table', 'list']) {
    test(`§0.2 行3：grid+poster 點「${target}」→ mode 變、cardShape 不變、不播 morph、走 switchMode()`, () => {
        let captureCalls = 0;
        let morphCalls = 0;
        withAnimStub({
            captureShapeState() { captureCalls++; return 'SNAP'; },
            playShapeMorph() { morphCalls++; },
        }, () => {
            const c = makeComponent({ mode: 'grid', cardShape: 'poster', perPage: 60 });
            let switchModeCalls = 0;
            const realSwitchMode = c.switchMode.bind(c);
            c.switchMode = function (m) { switchModeCalls++; return realSwitchMode(m); };
            c.selectPresentation(target);
            assert.equal(c.mode, target);
            assert.equal(c.cardShape, 'poster');
            assert.equal(captureCalls, 0);
            assert.equal(morphCalls, 0);
            assert.equal(switchModeCalls, 1);
            assert.equal(c.saveCalls, 1, 'saveState 是 switchMode() 自己做的，selectPresentation 不得額外呼叫');
        });
    });
}

for (const startMode of ['table', 'list']) {
    test(`§0.2 行4：${startMode} 點「完整封面」→ mode=grid、cardShape=cover、不播 morph`, () => {
        let captureCalls = 0;
        let morphCalls = 0;
        withAnimStub({
            captureShapeState() { captureCalls++; return 'SNAP'; },
            playShapeMorph() { morphCalls++; },
        }, () => {
            const c = makeComponent({ mode: startMode, cardShape: 'poster', perPage: 60 });
            c.selectPresentation('cover');
            assert.equal(c.mode, 'grid');
            assert.equal(c.cardShape, 'cover');
            assert.equal(captureCalls, 0);
            assert.equal(morphCalls, 0);
        });
    });
}

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

test('§0.2 行7：點自己（grid+cover 點「完整封面」）→ 零副作用', () => {
    let captureCalls = 0;
    let morphCalls = 0;
    withAnimStub({
        captureShapeState() { captureCalls++; return 'SNAP'; },
        playShapeMorph() { morphCalls++; },
    }, () => {
        const c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        let switchModeCalls = 0;
        const realSwitchMode = c.switchMode.bind(c);
        c.switchMode = function (m) { switchModeCalls++; return realSwitchMode(m); };
        c.selectPresentation('cover');
        assert.equal(c.saveCalls, 0, '點自己不得呼叫 saveState（否則每次點自己都寫一次 localStorage）');
        assert.equal(captureCalls, 0);
        assert.equal(morphCalls, 0);
        assert.equal(switchModeCalls, 0);
    });
});

// =====================================================================
// 契約
// =====================================================================

test('契約：selectPresentation() body 內零 this.mode = 賦值（CD-119-14，源碼斷言）', () => {
    const body = extractFnBody(STATE_VIDEOS_SRC, 'selectPresentation');
    assert.ok(body, 'selectPresentation 必須存在於 state-videos.js');
    assert.equal(
        /this\.mode\s*=(?!=)/.test(body),
        false,
        `不得出現 this.mode = 賦值（換模式一律委派 switchMode()），實際 body：${body}`,
    );
});

test('契約：selectPresentation() body 不含 scrollTo / scrollIntoView（AC-8.4，源碼斷言）', () => {
    const body = extractFnBody(STATE_VIDEOS_SRC, 'selectPresentation');
    assert.ok(body);
    assert.equal(body.includes('scrollTo'), false);
    assert.equal(body.includes('scrollIntoView'), false);
});

test('契約（順序）：captureShapeState 必須在 cardShape 寫入之前呼叫（呼叫序記錄，非回傳值）', () => {
    const events = [];
    let c;
    withAnimStub({
        captureShapeState() {
            events.push({ event: 'capture', cardShapeAtCallTime: c.cardShape });
            return 'SNAP';
        },
        playShapeMorph() {
            events.push({ event: 'morph', cardShapeAtCallTime: c.cardShape });
        },
    }, () => {
        c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        c.selectPresentation('poster');
        assert.equal(events.length, 2);
        assert.equal(events[0].event, 'capture');
        assert.equal(events[0].cardShapeAtCallTime, 'cover', 'capture 當下必須讀到舊值（寫入前）');
        assert.equal(events[1].event, 'morph');
        assert.equal(events[1].cardShapeAtCallTime, 'cover',
            'morph 必須在 cardShape 寫入之前呼叫（CD-133a-2：state 最後寫）');
        assert.equal(c.cardShape, 'poster', '回傳後 cardShape 必須已經是新值');
    });
});

test('契約（同一工作單元）：playShapeMorph 必須同步呼叫，該分支不得排 $nextTick', () => {
    let morphCalls = 0;
    withAnimStub({
        captureShapeState() { return 'SNAP'; },
        playShapeMorph() { morphCalls++; },
    }, () => {
        const ticks = [];
        const c = makeComponent({ mode: 'grid', cardShape: 'cover', $nextTick(fn) { ticks.push(fn); } });
        c.selectPresentation('poster');
        assert.equal(morphCalls, 1, 'playShapeMorph 必須在回傳前就被呼叫（同一工作單元）');
        assert.equal(ticks.length, 0, 'grid→grid 分支不得再排任何 $nextTick');
    });
});

test('契約（同一工作單元）：新版面的 class 必須在 playShapeMorph 之前就切成新值', () => {
    const events = [];
    withAnimStub({
        captureShapeState() {
            events.push({ event: 'capture', classOpsLen: FAKE_GRID._classOps.length });
            return 'SNAP';
        },
        playShapeMorph() {
            events.push({
                event: 'morph',
                classOpsLen: FAKE_GRID._classOps.length,
                classOpsSnapshot: FAKE_GRID._classOps.slice(),
            });
        },
    }, () => {
        // cover → poster
        const c1 = makeComponent({ mode: 'grid', cardShape: 'cover' });
        c1.selectPresentation('poster');
        assert.equal(events.length, 2);
        assert.equal(events[0].event, 'capture');
        assert.equal(events[1].event, 'morph');
        assert.ok(
            events[1].classOpsLen > events[0].classOpsLen,
            'class toggle 必須發生在 morph 之前（capture 後、morph 前）',
        );
        assert.deepEqual(
            events[1].classOpsSnapshot,
            [['shape-poster', true]],
            'cover→poster 必須 toggle shape-poster 為 true',
        );

        // poster → cover
        events.length = 0;
        const c2 = makeComponent({ mode: 'grid', cardShape: 'poster' });
        c2.selectPresentation('cover');
        assert.equal(events.length, 2);
        assert.equal(events[0].event, 'capture');
        assert.equal(events[1].event, 'morph');
        assert.ok(
            events[1].classOpsLen > events[0].classOpsLen,
            'class toggle 必須發生在 morph 之前（反向）',
        );
        assert.deepEqual(
            events[1].classOpsSnapshot,
            [['shape-poster', false]],
            'poster→cover 必須 toggle shape-poster 為 false',
        );
    });
});

test('契約：selectPresentation() body 內零 $nextTick（CD-133a-2，源碼斷言）', () => {
    const body = extractFnBody(STATE_VIDEOS_SRC, 'selectPresentation');
    assert.ok(body);
    // 剝註解再掃：技術要點 A 的說明註解必須保留「$nextTick」字樣（作廢理由），
    // 契約鎖的是可執行碼不得再排 $nextTick（比照 pill-clear / actress-pill-backspace）。
    const code = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    assert.equal(code.includes('$nextTick'), false,
        '同一工作單元完成套版面＋建動畫，不得再排 $nextTick（會多畫一幀舊版面）');
});

test('契約：_getActiveGrid() 在 morph 路徑被呼叫（證明沒有自己 querySelector，CD-119-15 ⑤）', () => {
    withAnimStub({
        captureShapeState() { return 'SNAP'; },
        playShapeMorph() {},
    }, () => {
        let getActiveGridCalls = 0;
        const c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        c._getActiveGrid = function () { getActiveGridCalls++; return FAKE_GRID; };
        c.selectPresentation('poster');
        assert.equal(getActiveGridCalls, 1);
    });
});

const UNKNOWN_TARGETS = ['foo', undefined, null, '', 0];
for (const target of UNKNOWN_TARGETS) {
    test(`契約：未知 target (${JSON.stringify(target)}) → 零副作用早退`, () => {
        let captureCalls = 0;
        let morphCalls = 0;
        withAnimStub({
            captureShapeState() { captureCalls++; return 'SNAP'; },
            playShapeMorph() { morphCalls++; },
        }, () => {
            const c = makeComponent({ mode: 'grid', cardShape: 'cover', perPage: 60 });
            let switchModeCalls = 0;
            const realSwitchMode = c.switchMode.bind(c);
            c.switchMode = function (m) { switchModeCalls++; return realSwitchMode(m); };
            c.selectPresentation(target);
            assert.equal(c.mode, 'grid');
            assert.equal(c.cardShape, 'cover');
            assert.equal(c.saveCalls, 0);
            assert.equal(captureCalls, 0);
            assert.equal(morphCalls, 0);
            assert.equal(switchModeCalls, 0);
        });
    });
}

test('契約：window.ShowcaseAnimations 不存在時狀態仍正確切換、不拋錯', () => {
    const prev = globalThis.window.ShowcaseAnimations;
    delete globalThis.window.ShowcaseAnimations;
    try {
        const c = makeComponent({ mode: 'grid', cardShape: 'cover' });
        assert.doesNotThrow(() => c.selectPresentation('poster'));
        assert.equal(c.cardShape, 'poster');
        assert.equal(c.mode, 'grid');
    } finally {
        if (prev !== undefined) globalThis.window.ShowcaseAnimations = prev;
    }
});

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
// animations.js：captureShapeState / playShapeMorph（源碼斷言，行為由 T8 CDP 驗）
// =====================================================================

test('animations.js：captureShapeState 存在，且與 captureFlipState 刻意分立（不共用實作）', () => {
    const body = extractFnBody(ANIMATIONS_SRC, 'captureShapeState');
    assert.ok(body, 'captureShapeState 必須存在於 animations.js');
    assert.equal(
        /captureFlipState/.test(body),
        false,
        'captureShapeState 必須與 captureFlipState 分立，不共用實作（技術要點②：共用會讓兩個用途互相綁架）',
    );
});

test('animations.js 契約：playShapeMorph 在 shouldSkip() 為 true 時回 null（AC-8.2，源碼斷言）', () => {
    const body = extractFnBody(ANIMATIONS_SRC, 'playShapeMorph');
    assert.ok(body, 'playShapeMorph 必須存在於 animations.js');
    assert.ok(
        /shouldSkip\(\)\s*\)\s*return null/.test(body),
        `必須有 shouldSkip() 早退回 null，實際 body：${body}`,
    );
});

test('animations.js 契約：playShapeMorph 的 absolute 未被設成 true（CD-119-8，源碼斷言）', () => {
    const body = extractFnBody(ANIMATIONS_SRC, 'playShapeMorph');
    assert.ok(body);
    assert.equal(
        /absolute\s*:\s*true/.test(body),
        false,
        'absolute 不得設成 true（CD-119-8：一次 morph 整頁卡片，全開會讓 grid 容器高度在動畫期間歸零）',
    );
    assert.ok(
        /absolute\s*:\s*false/.test(body),
        'absolute 應顯式寫成 false（CD-119-8：依賴預設值但不寫死會失去這條契約的可讀性）',
    );
});
