// TASK-148b-T2：captureInfoState / playInfoExpand 兩階段 Flip 機制
// TASK-148b-T3：toggleInfo() capture-before-write ＋ 世代閘契約
//
// 真的 import() animations.js／state-base.js，用假 DOM／假 gsap／假 Flip 驅動——不是源碼字串斷言。
// Stub 形狀照 shape-morph-viewport.test.mjs；@/ importmap loader 照 pill-hero.test.mjs。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {},
    querySelectorAll() {
        return { length: 0 };
    },
};

const gsapCalls = { killTweensOf: [], set: [] };
globalThis.gsap = {
    killTweensOf(...args) { gsapCalls.killTweensOf.push(args); },
    set(...args) { gsapCalls.set.push(args); },
    registerPlugin() {},
};

const flipCalls = { getState: [], killFlipsOf: [], from: [] };
globalThis.Flip = {
    getState(...args) {
        flipCalls.getState.push(args);
        return { __fakeState: true, args };
    },
    killFlipsOf(...args) { flipCalls.killFlipsOf.push(args); },
    from(...args) {
        flipCalls.from.push(args);
        return { __fakeTimeline: true };
    },
};

// T1 WALL_MOTION 6 keys 原樣抄自 motion-adapter.js（本測不 import 真檔）
const WALL_MOTION = {
    STAGGER_ORIGIN: 'center',
    STAGGER_ORIGIN_COLLAPSE: 'center',
    ENTRY_STAGGER_AMOUNT: 0.3,
    FILTER_ENTER_STAGGER_AMOUNT: 0.2,
    INFO_EXPAND_DURATION: 0.2,
    INFO_EXPAND_STAGGER_AMOUNT: 0.13,
};

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: {
        DURATION: { medium: 0.333 },
        WALL_MOTION,
    },
};

// state-base.js 用 @/shared/... 別名；plain node --test 需要 importmap resolve hook。
const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
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

await import('../animations.js');
const ShowcaseAnimations = globalThis.window.ShowcaseAnimations;

const { stateBase } = await import('../state-base.js');

const VIEWPORT_H = 900;
const MARGIN = 200;

function makeCard(rect, { animating = false } = {}) {
    const removed = [];
    const classList = {
        _hasAnimating: animating,
        remove(name) {
            removed.push(name);
            if (name === 'gsap-animating') classList._hasAnimating = false;
        },
        add() {},
        contains(name) {
            return name === 'gsap-animating' && classList._hasAnimating;
        },
    };
    return {
        getBoundingClientRect: () => rect,
        classList,
        _removed: removed,
        _rect: rect,
    };
}

function makeGrid(cards) {
    let queryCount = 0;
    return {
        querySelectorAll(sel) {
            queryCount += 1;
            const list = Object.assign(cards.slice(), { length: cards.length });
            list.forEach = Array.prototype.forEach;
            return list;
        },
        getQueryCount() { return queryCount; },
        resetQueryCount() { queryCount = 0; },
    };
}

/**
 * 120 張假卡：視窗內／視窗外（遠超過 ±200px）／0×0（hero）三類都出現。
 * 索引 0–39：視窗內；40–79：視窗外；80–119：0×0。
 */
function build120Cards() {
    const cards = [];
    for (let i = 0; i < 40; i++) {
        const top = 50 + i * 15;
        cards.push(makeCard({
            top, bottom: top + 180, left: 0, right: 100, width: 100, height: 180,
        }, { animating: i < 3 }));
    }
    for (let i = 0; i < 40; i++) {
        // 遠超過 viewportH + MARGIN（900+200=1100）與 -MARGIN
        const top = i % 2 === 0 ? 5000 + i * 20 : -3000 - i * 20;
        cards.push(makeCard({
            top, bottom: top + 180, left: 0, right: 100, width: 100, height: 180,
        }));
    }
    for (let i = 0; i < 40; i++) {
        cards.push(makeCard({
            top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0,
        }));
    }
    return cards;
}

function expectedPicked(cards, viewportH) {
    return cards.filter((c) => {
        const rect = c._rect;
        if (rect.width === 0 && rect.height === 0) return false;
        return rect.bottom > -MARGIN && rect.top < viewportH + MARGIN;
    });
}

function resetCalls() {
    gsapCalls.killTweensOf.length = 0;
    gsapCalls.set.length = 0;
    flipCalls.getState.length = 0;
    flipCalls.killFlipsOf.length = 0;
    flipCalls.from.length = 0;
    globalThis.window.OpenAver.prefersReducedMotion = false;
    globalThis.window.innerHeight = VIEWPORT_H;
}

function restoreGsapFlip(savedGsap, savedFlip) {
    if (savedGsap === undefined) {
        delete globalThis.gsap;
    } else {
        globalThis.gsap = savedGsap;
    }
    if (savedFlip === undefined) {
        delete globalThis.Flip;
    } else {
        globalThis.Flip = savedFlip;
    }
}

// ── I-148b-1 純算式 ──────────────────────────────────────────────

test('I-148b-1: INFO_EXPAND_DURATION + INFO_EXPAND_STAGGER_AMOUNT <= DURATION.medium', () => {
    const { WALL_MOTION: wm, DURATION } = globalThis.OpenAver.motion;
    assert.ok(
        wm.INFO_EXPAND_DURATION + wm.INFO_EXPAND_STAGGER_AMOUNT <= DURATION.medium,
        `expected ${wm.INFO_EXPAND_DURATION} + ${wm.INFO_EXPAND_STAGGER_AMOUNT} <= ${DURATION.medium}`,
    );
});

// ── captureInfoState：120 卡過濾 ─────────────────────────────────

test('captureInfoState: 120 張卡只收視窗內且非 0×0 的子集', () => {
    resetCalls();
    const cards = build120Cards();
    const gridEl = makeGrid(cards);
    const expected = expectedPicked(cards, VIEWPORT_H);

    assert.equal(cards.length, 120);
    assert.ok(expected.length > 0, 'fixture 必須含視窗內非零尺寸卡');
    assert.ok(expected.length < cards.length, 'fixture 必須含被過濾掉的卡');
    // 三類都必須出現
    assert.ok(cards.some((c) => c._rect.width > 0 && c._rect.bottom > -MARGIN && c._rect.top < VIEWPORT_H + MARGIN));
    assert.ok(cards.some((c) => c._rect.width > 0 && !(c._rect.bottom > -MARGIN && c._rect.top < VIEWPORT_H + MARGIN)));
    assert.ok(cards.some((c) => c._rect.width === 0 && c._rect.height === 0));
    assert.equal(expected.length, 40, '剛好 40 張視窗內非 0×0');

    const result = ShowcaseAnimations.captureInfoState(gridEl);

    assert.ok(result && Array.isArray(result.cards), '必須回傳 { state, cards }');
    assert.equal(result.cards.length, expected.length);
    assert.deepEqual(result.cards, expected);
    assert.equal(flipCalls.getState.length, 1);
    assert.deepEqual(flipCalls.getState[0][0], expected);
    assert.equal(flipCalls.getState[0][1].simple, true);
});

test('captureInfoState excludes zero-size (display:none) cards from picked/Flip.getState', () => {
    resetCalls();
    const visible = makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 });
    const zero = makeCard({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 });
    const gridEl = makeGrid([visible, zero]);

    const result = ShowcaseAnimations.captureInfoState(gridEl);

    assert.ok(result);
    assert.equal(result.cards.length, 1);
    assert.equal(result.cards[0], visible);
    assert.deepEqual(flipCalls.getState[0][0], [visible]);
    assert.ok(!result.cards.includes(zero));
});

// ── capture 四步驟呼叫序 ─────────────────────────────────────────

test('captureInfoState step 3 clears transform,opacity explicitly (killTweensOf alone does not clear these two props)', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 50, bottom: 230, left: 0, right: 100, width: 100, height: 180 }, { animating: true }),
        makeCard({ top: 80, bottom: 260, left: 0, right: 100, width: 100, height: 180 }, { animating: true }),
    ];
    const gridEl = makeGrid(cards);

    let killCountAtGetState = -1;
    let setCountAtGetState = -1;
    let killArgAtGetState = null;
    let setArgAtGetState = null;
    const origGetState = globalThis.Flip.getState;
    globalThis.Flip.getState = (...args) => {
        killCountAtGetState = gsapCalls.killTweensOf.length;
        setCountAtGetState = gsapCalls.set.length;
        killArgAtGetState = gsapCalls.killTweensOf[0] && gsapCalls.killTweensOf[0][0];
        setArgAtGetState = gsapCalls.set[0] && gsapCalls.set[0][0];
        return origGetState(...args);
    };

    try {
        ShowcaseAnimations.captureInfoState(gridEl);
    } finally {
        globalThis.Flip.getState = origGetState;
    }

    assert.ok(killCountAtGetState >= 1, 'gsap.killTweensOf 必須在 Flip.getState 之前');
    assert.ok(setCountAtGetState >= 1, 'gsap.set(clearProps) 必須在 Flip.getState 之前');

    // killTweensOf / clearProps 吃完整 cards，getState 吃 picked
    assert.equal(killArgAtGetState.length, cards.length, 'killTweensOf 吃完整 cards');
    assert.equal(setArgAtGetState.length, cards.length, 'clearProps 吃完整 cards');
    assert.deepEqual(flipCalls.getState[0][0], cards, '本 fixture 全部視窗內，picked === cards');

    const clearCall = gsapCalls.set.find((args) => args[1] && args[1].clearProps);
    assert.ok(clearCall, '必須呼叫 gsap.set 帶 clearProps');
    assert.equal(
        clearCall[1].clearProps,
        'transform,opacity',
        'captureInfoState step 3 clears transform,opacity explicitly (killTweensOf alone does not clear these two props)',
    );

    for (const c of cards) {
        assert.ok(c._removed.includes('gsap-animating'), '每張卡的 gsap-animating 必須被 remove');
    }
});

test('captureInfoState: killTweensOf(完整) → remove class → clearProps → getState(picked)', () => {
    resetCalls();
    const cards = build120Cards();
    const gridEl = makeGrid(cards);
    const expected = expectedPicked(cards, VIEWPORT_H);

    const order = [];
    const origKill = globalThis.gsap.killTweensOf;
    const origSet = globalThis.gsap.set;
    const origGetState = globalThis.Flip.getState;

    globalThis.gsap.killTweensOf = (...args) => {
        order.push({ step: 'killTweensOf', argLen: args[0].length });
        return origKill(...args);
    };
    globalThis.gsap.set = (...args) => {
        order.push({ step: 'set', clearProps: args[1] && args[1].clearProps, argLen: args[0].length });
        return origSet(...args);
    };
    globalThis.Flip.getState = (...args) => {
        order.push({ step: 'getState', argLen: args[0].length, simple: args[1] && args[1].simple });
        return origGetState(...args);
    };

    try {
        ShowcaseAnimations.captureInfoState(gridEl);
    } finally {
        globalThis.gsap.killTweensOf = origKill;
        globalThis.gsap.set = origSet;
        globalThis.Flip.getState = origGetState;
    }

    assert.equal(order.length, 3);
    assert.equal(order[0].step, 'killTweensOf');
    assert.equal(order[0].argLen, 120);
    assert.equal(order[1].step, 'set');
    assert.equal(order[1].clearProps, 'transform,opacity');
    assert.equal(order[1].argLen, 120);
    assert.equal(order[2].step, 'getState');
    assert.equal(order[2].argLen, expected.length);
    assert.equal(order[2].simple, true);
});

// ── playInfoExpand ───────────────────────────────────────────────

test('playInfoExpand kills flips of the actual cards collection, not an empty array', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
        makeCard({ top: 200, bottom: 380, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    const tl = ShowcaseAnimations.playInfoExpand(captured, gridEl, true);

    assert.ok(tl && tl.__fakeTimeline, '正常路徑必須回傳 Timeline（不得恆回 null）');
    assert.equal(flipCalls.killFlipsOf.length, 1);
    assert.equal(flipCalls.killFlipsOf[0][0], cards);
    assert.notDeepEqual(flipCalls.killFlipsOf[0][0], []);
});

test('Flip.from is called with absolute:false, not true', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    ShowcaseAnimations.playInfoExpand(captured, gridEl, true);

    assert.equal(flipCalls.from.length, 1);
    const vars = flipCalls.from[0][1];
    assert.equal(vars.absolute, false, 'Flip.from is called with absolute:false, not true');
    assert.equal(vars.duration, WALL_MOTION.INFO_EXPAND_DURATION);
    assert.equal(vars.ease, 'fluent');
    assert.equal(vars.prune, true);
    assert.equal(typeof vars.onComplete, 'function');
    assert.ok(vars.stagger);
    assert.equal(vars.stagger.amount, WALL_MOTION.INFO_EXPAND_STAGGER_AMOUNT);
    assert.equal(vars.stagger.grid, 'auto');
});

test('playInfoExpand: onComplete clears transform,width,height', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    ShowcaseAnimations.playInfoExpand(captured, gridEl, true);

    const vars = flipCalls.from[0][1];
    const setBefore = gsapCalls.set.length;
    vars.onComplete();
    assert.ok(gsapCalls.set.length > setBefore, 'onComplete 必須呼叫 gsap.set');
    const clearCall = gsapCalls.set.find((args) => args[1] && args[1].clearProps === 'transform,width,height');
    assert.ok(clearCall, 'onComplete 必須 gsap.set({ clearProps: transform,width,height })');
    assert.equal(clearCall[0], cards);
});

test('playInfoExpand: stagger.from 依 toVisible / options.origin', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    ShowcaseAnimations.playInfoExpand(captured, gridEl, true);
    assert.equal(flipCalls.from[0][1].stagger.from, WALL_MOTION.STAGGER_ORIGIN);

    resetCalls();
    ShowcaseAnimations.playInfoExpand(captured, gridEl, false);
    assert.equal(flipCalls.from[0][1].stagger.from, WALL_MOTION.STAGGER_ORIGIN_COLLAPSE);

    resetCalls();
    ShowcaseAnimations.playInfoExpand(captured, gridEl, true, { origin: 'start' });
    assert.equal(flipCalls.from[0][1].stagger.from, 'start');

    resetCalls();
    ShowcaseAnimations.playInfoExpand(captured, gridEl, false, { origin: 'end' });
    assert.equal(flipCalls.from[0][1].stagger.from, 'end');
});

test('playInfoExpand: 120 卡 capture→play 呼叫鏈可執行', () => {
    resetCalls();
    const cards = build120Cards();
    const gridEl = makeGrid(cards);
    const expected = expectedPicked(cards, VIEWPORT_H);

    const captured = ShowcaseAnimations.captureInfoState(gridEl);
    assert.ok(captured);
    assert.equal(captured.cards.length, expected.length);

    flipCalls.killFlipsOf.length = 0;
    flipCalls.from.length = 0;

    const tl = ShowcaseAnimations.playInfoExpand(captured, gridEl, true);
    assert.ok(tl && tl.__fakeTimeline);
    assert.equal(flipCalls.killFlipsOf.length, 1);
    assert.equal(flipCalls.killFlipsOf[0][0], captured.cards);
    assert.equal(flipCalls.from.length, 1);
    assert.equal(flipCalls.from[0][0], captured.state);
});

// ── guard 各自獨立（FE-REVIEW-08）────────────────────────────────

test('captureInfoState / playInfoExpand：只缺 gsap（保留 Flip）→ 皆回 null', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };
    const saved = globalThis.gsap;
    delete globalThis.gsap;
    try {
        assert.equal(ShowcaseAnimations.captureInfoState(gridEl), null);
        assert.equal(ShowcaseAnimations.playInfoExpand(captured, gridEl, true), null);
        assert.equal(flipCalls.from.length, 0);
        assert.equal(flipCalls.getState.length, 0);
    } finally {
        restoreGsapFlip(saved, globalThis.Flip);
    }
});

test('captureInfoState / playInfoExpand：只缺 Flip（保留 gsap）→ 皆回 null', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };
    const saved = globalThis.Flip;
    delete globalThis.Flip;
    try {
        assert.equal(ShowcaseAnimations.captureInfoState(gridEl), null);
        assert.equal(ShowcaseAnimations.playInfoExpand(captured, gridEl, true), null);
        assert.equal(gsapCalls.killTweensOf.length, 0);
    } finally {
        restoreGsapFlip(globalThis.gsap, saved);
    }
});

// ── 邊界 ─────────────────────────────────────────────────────────

test('captureInfoState / playInfoExpand：邊界回 null', () => {
    resetCalls();

    assert.equal(ShowcaseAnimations.captureInfoState(null), null);
    assert.equal(ShowcaseAnimations.captureInfoState(makeGrid([])), null);

    // 全部視窗外
    const far = [
        makeCard({ top: 5000, bottom: 5180, left: 0, right: 100, width: 100, height: 180 }),
        makeCard({ top: -3000, bottom: -2820, left: 0, right: 100, width: 100, height: 180 }),
    ];
    assert.equal(ShowcaseAnimations.captureInfoState(makeGrid(far)), null);

    // 全部 0×0
    const zeros = [
        makeCard({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }),
        makeCard({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }),
    ];
    assert.equal(ShowcaseAnimations.captureInfoState(makeGrid(zeros)), null);

    const gridEl = makeGrid([
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ]);
    assert.equal(ShowcaseAnimations.playInfoExpand(null, gridEl, true), null);
    assert.equal(
        ShowcaseAnimations.playInfoExpand({ state: {}, cards: [] }, gridEl, true),
        null,
    );
    assert.equal(
        ShowcaseAnimations.playInfoExpand(
            { state: {}, cards: [makeCard({ top: 1, bottom: 2, left: 0, right: 1, width: 1, height: 1 })] },
            null,
            true,
        ),
        null,
    );
});

test('playInfoExpand：shouldSkip() 成立時回 null 且不呼叫 Flip.from', () => {
    resetCalls();
    globalThis.window.OpenAver.prefersReducedMotion = true;

    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    const result = ShowcaseAnimations.playInfoExpand(captured, gridEl, true);

    assert.equal(result, null);
    assert.equal(flipCalls.from.length, 0, 'reduced-motion 時 Flip.from 零呼叫');
});

// ── TASK-148b-T3：toggleInfo() capture-before-write ＋ 世代閘 ─────

/**
 * $nextTick / rAF 必須「排入佇列、由測試手動 flush」——不可同步立即執行，
 * 否則世代閘 mutation（拿掉 ++）測不出「多份 pending 工作同時存在」的窗口。
 */
function makeToggleInfoCtx() {
    const nextTickQueue = [];
    const rafQueue = [];
    const fakeGrid = { __fakeGrid: true };
    // stateBase factory 內用 this.$persist；node harness 需 stub（比照 pill-persist / pill-clear）
    const ctx = Object.assign(
        stateBase.call({ $persist: (obj) => ({ as: () => obj }) }),
        {
            infoVisible: false,
            _persistedShowcase: {},
            _animGeneration: 0,
            _getActiveGrid: () => fakeGrid,
            $nextTick(cb) { nextTickQueue.push(cb); },
        },
    );
    return { ctx, fakeGrid, nextTickQueue, rafQueue };
}

function flushOne(nextTickQueue, rafQueue) {
    const tick = nextTickQueue.shift();
    tick();
    const raf = rafQueue.shift();
    raf();
}

test('toggleInfo()：captureInfoState 呼叫必須在 infoVisible 寫入之前（capture-before-write 契約）', () => {
    const { ctx, fakeGrid, nextTickQueue, rafQueue } = makeToggleInfoCtx();
    const origRaf = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = (cb) => { rafQueue.push(cb); };

    let capturedAtInfoVisible;
    const savedSA = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = {
        captureInfoState(gridEl) {
            // 呼叫當下立刻讀——不要延後；mutation 把寫入插到 capture 前後時，這裡必須抓到翻轉後的值才會紅
            capturedAtInfoVisible = ctx.infoVisible;
            assert.equal(gridEl, fakeGrid);
            return { state: { __captured: true }, cards: [] };
        },
        playInfoExpand() {},
    };

    try {
        assert.equal(ctx.infoVisible, false);
        ctx.toggleInfo();

        assert.equal(
            capturedAtInfoVisible,
            false,
            'captureInfoState 呼叫當下 infoVisible 必須仍是舊值 false（capture-before-write）',
        );
        // 既有兩行：同步翻轉不受動畫影響
        assert.equal(ctx.infoVisible, true);
        assert.equal(ctx._persistedShowcase.infoVisible, true);
        assert.equal(nextTickQueue.length, 1, '應排入一份 $nextTick 延後工作');
    } finally {
        globalThis.requestAnimationFrame = origRaf;
        globalThis.window.ShowcaseAnimations = savedSA;
    }
});

test('toggleInfo()：連續三次呼叫，只有最後一次通過世代核對並呼叫 playInfoExpand（I-148b-3）', () => {
    const { ctx, fakeGrid, nextTickQueue, rafQueue } = makeToggleInfoCtx();
    const origRaf = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = (cb) => { rafQueue.push(cb); };

    const captureCalls = [];
    const playCalls = [];
    const savedSA = globalThis.window.ShowcaseAnimations;
    globalThis.window.ShowcaseAnimations = {
        captureInfoState(gridEl) {
            const captured = { state: { n: captureCalls.length }, cards: [{ n: captureCalls.length }] };
            captureCalls.push({ gridEl, captured });
            return captured;
        },
        playInfoExpand(capturedState, gridEl, toVisible) {
            playCalls.push({ capturedState, gridEl, toVisible });
        },
    };

    try {
        // 三次都先 push，全部呼叫完才 flush——製造「多份 pending 工作同時存在」的窗口
        ctx.toggleInfo(); // false → true
        ctx.toggleInfo(); // true → false
        ctx.toggleInfo(); // false → true

        assert.equal(nextTickQueue.length, 3, '三次呼叫應留下三份 pending $nextTick');
        assert.equal(rafQueue.length, 0, 'rAF 尚未排入（等 $nextTick flush）');
        assert.equal(captureCalls.length, 3);
        assert.equal(playCalls.length, 0, 'flush 前 playInfoExpand 零呼叫');
        assert.equal(ctx.infoVisible, true, '三次翻轉後 infoVisible 為 true');
        assert.equal(ctx._persistedShowcase.infoVisible, true);

        flushOne(nextTickQueue, rafQueue);
        flushOne(nextTickQueue, rafQueue);
        flushOne(nextTickQueue, rafQueue);

        assert.equal(
            playCalls.length,
            1,
            '只有最後一次通過世代核對並呼叫 playInfoExpand（I-148b-3）',
        );
        assert.equal(playCalls[0].gridEl, fakeGrid);
        assert.equal(playCalls[0].toVisible, true, '第三次呼叫結束時 toVisible === true');
        assert.equal(
            playCalls[0].capturedState,
            captureCalls[2].captured,
            'play 參數對應第三次 capture 的 capturedInfoState',
        );
    } finally {
        globalThis.requestAnimationFrame = origRaf;
        globalThis.window.ShowcaseAnimations = savedSA;
    }
});

test('toggleInfo()：缺 _getActiveGrid 與 $nextTick 時不得 throw，狀態機仍翻轉（AC-6）', () => {
    // 故意不提供 _getActiveGrid / $nextTick——動畫前導不得挾持狀態機（AC-6）
    const ctx = Object.assign(
        stateBase.call({ $persist: (obj) => ({ as: () => obj }) }),
        {
            infoVisible: false,
            _persistedShowcase: {},
            _animGeneration: 0,
        },
    );
    delete ctx._getActiveGrid;
    delete ctx.$nextTick;
    assert.equal(typeof ctx._getActiveGrid, 'undefined');
    assert.equal(typeof ctx.$nextTick, 'undefined');

    assert.doesNotThrow(() => ctx.toggleInfo());
    assert.equal(ctx.infoVisible, true);
    assert.equal(ctx._persistedShowcase.infoVisible, true);

    assert.doesNotThrow(() => ctx.toggleInfo());
    assert.equal(ctx.infoVisible, false);
    assert.equal(ctx._persistedShowcase.infoVisible, false);
});
