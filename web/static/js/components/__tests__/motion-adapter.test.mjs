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

