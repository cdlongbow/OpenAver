// TASK-141b-T1：ShowcaseAnimations 三支委派殼（playEntry / playFlipFilter /
// captureFlipState）對 window.GridMotion 的轉發與降級契約。
//
// animations.js 是純 IIFE（`window.ShowcaseAnimations = ...`），零 import/export，
// plain `node --test` 可直接 `import()`，手法照 pick-star-motion.test.mjs /
// shape-morph-viewport.test.mjs。

import { test } from 'node:test';
import assert from 'node:assert/strict';

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
        return { to() { return this; }, fromTo() { return this; }, eventCallback() { return this; } };
    },
    fromTo() { return {}; },
    to() { return {}; },
    registerPlugin() {},
};

globalThis.Flip = {
    getState() { return { __fakeState: true }; },
    killFlipsOf() {},
    from() { return { __fakeTimeline: true }; },
};

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: { DURATION: { emphasis: 0.5, medium: 0.333 } },
};

await import('../animations.js');
const ShowcaseAnimations = globalThis.window.ShowcaseAnimations;

function makeCard() {
    return {
        getBoundingClientRect() { return { top: 10, left: 0, right: 100, bottom: 190, width: 100, height: 180 }; },
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

function withGridMotion(stub, fn) {
    const prev = globalThis.window.GridMotion;
    if (stub === undefined) {
        delete globalThis.window.GridMotion;
    } else {
        globalThis.window.GridMotion = stub;
    }
    try {
        fn();
    } finally {
        if (prev === undefined) delete globalThis.window.GridMotion;
        else globalThis.window.GridMotion = prev;
    }
}

// ===== DoD 3：window.GridMotion 缺失時三支殼安全降級 =====

test('T1-DoD3-playEntry-degrade', () => {
    withGridMotion(undefined, () => {
        const grid = makeGrid([makeCard()]);
        let result;
        assert.doesNotThrow(() => {
            result = ShowcaseAnimations.playEntry(grid, { duration: 0.4 });
        });
        assert.equal(result, null, 'GridMotion 缺失時 playEntry 殼必須降級回 null');
    });
});

test('T1-DoD3-playFlipFilter-degrade', () => {
    withGridMotion(undefined, () => {
        const grid = makeGrid([makeCard()]);
        const state = { __state: true };
        let result;
        assert.doesNotThrow(() => {
            result = ShowcaseAnimations.playFlipFilter(grid, state, { duration: 0.3 });
        });
        assert.equal(result, null, 'GridMotion 缺失時 playFlipFilter 殼必須降級回 null');
    });
});

test('T1-DoD3-captureFlipState-degrade', () => {
    withGridMotion(undefined, () => {
        const grid = makeGrid([makeCard()]);
        let result;
        assert.doesNotThrow(() => {
            result = ShowcaseAnimations.captureFlipState(grid);
        });
        assert.equal(result, null, 'GridMotion 缺失時 captureFlipState 殼必須降級回 null');
    });
});

// ===== DoD 4：三支殼參數原樣同序轉發、回傳值原樣透傳 =====

test('T1-DoD4-playEntry-forward', () => {
    const calls = [];
    const sentinel = { __tl: 'entry' };
    withGridMotion({
        playEntry(...args) {
            calls.push(args);
            return sentinel;
        },
    }, () => {
        const grid = makeGrid([makeCard()]);
        const params = { duration: 0.42, stagger: 0.01 };
        const result = ShowcaseAnimations.playEntry(grid, params);
        assert.equal(calls.length, 1, '必須恰好轉發一次給 GridMotion.playEntry');
        assert.equal(calls[0].length, 2);
        assert.equal(calls[0][0], grid);
        assert.equal(calls[0][1], params);
        assert.equal(result, sentinel, '回傳值必須原樣透傳');
    });
});

test('T1-DoD4-playFlipFilter-forward', () => {
    const calls = [];
    const sentinel = { __tl: 'flip-filter' };
    withGridMotion({
        playFlipFilter(...args) {
            calls.push(args);
            return sentinel;
        },
    }, () => {
        const grid = makeGrid([makeCard()]);
        const state = { __flipState: true };
        const params = { duration: 0.3 };
        const result = ShowcaseAnimations.playFlipFilter(grid, state, params);
        assert.equal(calls.length, 1, '必須恰好轉發一次給 GridMotion.playFlipFilter');
        assert.equal(calls[0].length, 3);
        assert.equal(calls[0][0], grid);
        assert.equal(calls[0][1], state, '第二參數必須是 state（不可與 params 調換）');
        assert.equal(calls[0][2], params, '第三參數必須是 params');
        assert.equal(result, sentinel, '回傳值必須原樣透傳');
    });
});

test('T1-DoD4-captureFlipState-forward', () => {
    const calls = [];
    const sentinel = { __captured: true };
    withGridMotion({
        captureFlipState(...args) {
            calls.push(args);
            return sentinel;
        },
    }, () => {
        const grid = makeGrid([makeCard()]);
        const result = ShowcaseAnimations.captureFlipState(grid);
        assert.equal(calls.length, 1, '必須恰好轉發一次給 GridMotion.captureFlipState');
        assert.equal(calls[0].length, 1);
        assert.equal(calls[0][0], grid);
        assert.equal(result, sentinel, '回傳值必須原樣透傳');
    });
});
