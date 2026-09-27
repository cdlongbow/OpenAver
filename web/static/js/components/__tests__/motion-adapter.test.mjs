// TASK-156e-T1a：motion-adapter flipCapture / flipFrom
// stub 手法照 shared/__tests__/grid-motion.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';

/** @type {Array<{targets: unknown, opts: unknown}>} */
const getStateCalls = [];
/** @type {Array<{state: unknown, opts: unknown}>} */
const fromCalls = [];

globalThis.window = globalThis;
globalThis.window.addEventListener = function () {};
globalThis.document = {
    addEventListener() {},
};
globalThis.CustomEase = {
    create() {},
};
globalThis.gsap = {
    registerPlugin() {},
    set() {},
    killTweensOf() {},
    from() { return {}; },
    to() { return {}; },
    fromTo() { return {}; },
    timeline() {
        return {
            fromTo() { return this; },
            to() { return this; },
        };
    },
    context() {
        return {
            add() {},
            revert() {},
        };
    },
    globalTimeline: { timeScale() {} },
};
globalThis.Flip = {
    getState(targets, opts) {
        getStateCalls.push({ targets, opts });
        return { __fakeState: true, targets };
    },
    from(state, opts) {
        fromCalls.push({ state, opts });
        return { __fakeFlipTimeline: true };
    },
};
globalThis.OpenAver = {
    prefersReducedMotion: false,
};

await import('../motion-adapter.js');
const motion = globalThis.window.OpenAver.motion;

function resetCalls() {
    getStateCalls.length = 0;
    fromCalls.length = 0;
}

test('flipCapture: 呼叫 Flip.getState 並回傳其結果', () => {
    resetCalls();
    const targets = [{ id: 'a' }, { id: 'b' }];
    const state = motion.flipCapture(targets);
    assert.equal(getStateCalls.length, 1);
    assert.equal(getStateCalls[0].targets, targets);
    assert.deepEqual(state, { __fakeState: true, targets });
});

test('flipFrom: 呼叫端傳入的 opts（targets/duration/absolute 等）原樣透傳給 Flip.from', () => {
    resetCalls();
    const fakeState = { __fakeState: true };
    const opts = {
        targets: [{ id: 'x' }],
        duration: 0.4,
        absolute: true,
        fade: true,
        nested: true,
    };
    const tl = motion.flipFrom(fakeState, opts);
    assert.equal(fromCalls.length, 1);
    assert.equal(fromCalls[0].state, fakeState);
    assert.equal(fromCalls[0].opts, opts);
    assert.deepEqual(fromCalls[0].opts, {
        targets: [{ id: 'x' }],
        duration: 0.4,
        absolute: true,
        fade: true,
        nested: true,
    });
    assert.deepEqual(tl, { __fakeFlipTimeline: true });
});

test('flipCapture: PRM 時不呼叫 Flip.getState 並回傳 null', () => {
    resetCalls();
    const prev = globalThis.OpenAver.prefersReducedMotion;
    globalThis.OpenAver.prefersReducedMotion = true;
    try {
        const targets = [{ id: 'a' }];
        const state = motion.flipCapture(targets);
        assert.equal(getStateCalls.length, 0);
        assert.equal(state, null);
    } finally {
        globalThis.OpenAver.prefersReducedMotion = prev;
    }
});

test('flipFrom: state 為 null 時不呼叫 Flip.from 且呼叫 onComplete', () => {
    resetCalls();
    let completed = 0;
    const tl = motion.flipFrom(null, {
        onComplete() {
            completed += 1;
        },
    });
    assert.equal(fromCalls.length, 0);
    assert.equal(completed, 1);
    assert.equal(tl, null);
});
