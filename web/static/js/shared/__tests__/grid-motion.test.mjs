// TASK-148b-T1：GridMotion.playEntry / playFlipFilter.onEnter 的 stagger
 // 從「每張固定間隔」改成「總延遲預算」＋網格感知物件語意。
 //
// 直接 import 真正的 ../grid-motion.js（不是 stub 掉 window.GridMotion）。
// gsap stub 必須記錄傳入 vars，才能斷言 stagger 物件形狀。
//
// 跑：node --test web/static/js/shared/__tests__/grid-motion.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';

// ── stub 骨架（照 grid-motion-delegate.test.mjs），但 gsap 會記錄呼叫參數 ──

const WALL_MOTION = {
    STAGGER_ORIGIN: 'center',
    STAGGER_ORIGIN_COLLAPSE: 'center',
    ENTRY_STAGGER_AMOUNT: 0.3,
    FILTER_ENTER_STAGGER_AMOUNT: 0.2,
    INFO_EXPAND_DURATION: 0.2,
    INFO_EXPAND_STAGGER_AMOUNT: 0.13,
};

const DURATION = {
    fast: 0.167,
    medium: 0.333,
    emphasis: 0.5,
};

/** @type {Array<{targets: unknown, vars: Record<string, unknown>}>} */
const timelineToCalls = [];
/** @type {Array<{fromVars: unknown, toVars: Record<string, unknown>}>} */
const fromToCalls = [];
/** @type {Array<unknown>} */
const flipFromCalls = [];

globalThis.window = globalThis;
globalThis.window.innerHeight = 900;
globalThis.window.innerWidth = 1200;
globalThis.document = {
    addEventListener() {},
    querySelectorAll() {
        return { length: 0 };
    },
};

globalThis.gsap = {
    killTweensOf() {},
    set() {},
    timeline() {
        return {
            to(targets, vars) {
                timelineToCalls.push({ targets, vars });
                return this;
            },
            fromTo() { return this; },
            eventCallback() { return this; },
        };
    },
    fromTo(targets, fromVars, toVars) {
        fromToCalls.push({ targets, fromVars, toVars });
        return { __fromTo: true };
    },
    to() { return {}; },
    registerPlugin() {},
};

globalThis.Flip = {
    getState() { return { __fakeState: true }; },
    killFlipsOf() {},
    from(state, opts) {
        flipFromCalls.push({ state, opts });
        return { __fakeTimeline: true };
    },
};

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: { DURATION, WALL_MOTION },
};

await import('../grid-motion.js');
const GridMotion = globalThis.window.GridMotion;

function makeCard(top = 10) {
    return {
        getBoundingClientRect() {
            return { top, left: 0, right: 100, bottom: top + 180, width: 100, height: 180 };
        },
        classList: { add() {}, remove() {} },
        getAttribute() { return null; },
    };
}

/** display:none / x-cloak hero 等無版面框的卡（0×0 @ (0,0)） */
function makeZeroSizeCard() {
    return {
        getBoundingClientRect() {
            return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
        },
        classList: { add() {}, remove() {} },
        getAttribute() { return null; },
    };
}

function makeGrid(cards) {
    return {
        querySelectorAll() {
            const list = Object.assign(cards.slice(), { length: cards.length });
            list.forEach = Array.prototype.forEach;
            return list;
        },
        classList: { remove() {}, add() {} },
    };
}

function resetCalls() {
    timelineToCalls.length = 0;
    fromToCalls.length = 0;
    flipFromCalls.length = 0;
}

// ── playEntry：預設 stagger 物件語意 ──────────────────────────────────────

test('playEntry passes object stagger with amount semantics, not a raw number', () => {
    resetCalls();
    const grid = makeGrid([makeCard(), makeCard(20), makeCard(30)]);
    GridMotion.playEntry(grid);

    assert.equal(timelineToCalls.length, 1, 'playEntry 必須呼叫 timeline().to 一次');
    const { vars } = timelineToCalls[0];
    assert.equal(typeof vars.stagger, 'object', 'stagger 必須是物件，不是純數字');
    assert.notEqual(vars.stagger, null);
    assert.equal(vars.stagger.amount, WALL_MOTION.ENTRY_STAGGER_AMOUNT);
    assert.equal(vars.stagger.from, WALL_MOTION.STAGGER_ORIGIN);
    assert.equal(vars.stagger.grid, 'auto');
});

test('playEntry keeps duration = DURATION.emphasis when params omitted', () => {
    resetCalls();
    const grid = makeGrid([makeCard(), makeCard(20)]);
    GridMotion.playEntry(grid);

    assert.equal(timelineToCalls.length, 1);
    assert.equal(timelineToCalls[0].vars.duration, DURATION.emphasis);
});

test('playEntry params.stagger override still wins over WALL_MOTION default', () => {
    resetCalls();
    const grid = makeGrid([makeCard(), makeCard(20)]);
    const custom = 0.07;
    GridMotion.playEntry(grid, { stagger: custom });

    assert.equal(timelineToCalls.length, 1);
    assert.equal(timelineToCalls[0].vars.stagger, custom,
        '呼叫端傳自訂 stagger 時必須直接用那個值，不套 WALL_MOTION 預設');
});

test('playEntry excludes zero-size cards from timeline().to targets', () => {
    resetCalls();
    const zero = makeZeroSizeCard();
    const a = makeCard(10);
    const b = makeCard(20);
    GridMotion.playEntry(makeGrid([zero, a, b]));

    assert.equal(timelineToCalls.length, 1, 'playEntry 必須呼叫 timeline().to 一次');
    const targets = timelineToCalls[0].targets;
    assert.equal(Array.isArray(targets) ? targets.includes(zero) : [...targets].includes(zero), false,
        '0×0 卡不得進入 timeline().to 目標集合（會污染 grid:auto）');
    assert.equal(Array.isArray(targets) ? targets.includes(a) : [...targets].includes(a), true);
    assert.equal(Array.isArray(targets) ? targets.includes(b) : [...targets].includes(b), true);
});

// ── onEnter（els.length > 10）：FILTER_ENTER 物件語意（三階梯第①階採用）──

test('onEnter (>10) passes object stagger with FILTER_ENTER amount semantics', () => {
    resetCalls();
    const cards = Array.from({ length: 12 }, (_, i) => makeCard(i * 10));
    const grid = makeGrid(cards);
    const state = { __flipState: true };

    GridMotion.playFlipFilter(grid, state);
    assert.equal(flipFromCalls.length, 1, '必須呼叫 Flip.from 一次');

    const { opts } = flipFromCalls[0];
    assert.equal(typeof opts.onEnter, 'function');

    const enterEls = cards.slice(0, 12);
    opts.onEnter(enterEls);

    assert.equal(fromToCalls.length, 1, 'onEnter (>10) 必須呼叫 gsap.fromTo 一次');
    const { toVars } = fromToCalls[0];
    assert.equal(typeof toVars.stagger, 'object', 'onEnter stagger 必須是物件，不是純數字');
    assert.notEqual(toVars.stagger, null);
    assert.equal(toVars.stagger.amount, WALL_MOTION.FILTER_ENTER_STAGGER_AMOUNT);
    assert.equal(toVars.stagger.from, WALL_MOTION.STAGGER_ORIGIN);
    assert.equal(toVars.stagger.grid, 'auto');
});

test('onEnter (>10) stagger budget is fixed (FILTER_ENTER_STAGGER_AMOUNT), not linear in els.length', () => {
    resetCalls();
    const cards = Array.from({ length: 24 }, (_, i) => makeCard(i * 10));
    const grid = makeGrid(cards);
    GridMotion.playFlipFilter(grid, { __flipState: true });

    const { opts } = flipFromCalls[0];
    opts.onEnter(cards.slice(0, 12));
    opts.onEnter(cards.slice(0, 24));

    assert.equal(fromToCalls.length, 2);
    const s12 = fromToCalls[0].toVars.stagger;
    const s24 = fromToCalls[1].toVars.stagger;
    assert.equal(typeof s12, 'object');
    assert.equal(typeof s24, 'object');
    assert.equal(s12.amount, WALL_MOTION.FILTER_ENTER_STAGGER_AMOUNT);
    assert.equal(s24.amount, WALL_MOTION.FILTER_ENTER_STAGGER_AMOUNT);
    assert.equal(s12.amount, s24.amount,
        '總延遲預算不隨 els.length 線性增長');
});
