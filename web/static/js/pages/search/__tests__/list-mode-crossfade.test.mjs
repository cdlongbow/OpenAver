// TASK-141b-T2：playListModeCrossfade 五種分支單元測試
//
// animations.js 是純 IIFE（`window.SearchAnimations = ...`），零 import/export，
// plain `node --test` 可直接 `import()`，手法照 grid-motion-delegate.test.mjs。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.document = {
    addEventListener() {},
};

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: { DURATION: { fast: 0.15, medium: 0.333, emphasis: 0.5 } },
};

function makeGsapMock() {
    const calls = { timeline: [], to: [], fromTo: [] };
    const gsap = {
        timeline() {
            const tl = {
                to(el, vars) {
                    calls.to.push({ el, vars });
                    if (vars && typeof vars.onComplete === 'function') vars.onComplete();
                    return this;
                },
                fromTo(el, from, to) {
                    calls.fromTo.push({ el, from, to });
                    return this;
                },
            };
            calls.timeline.push(tl);
            return tl;
        },
    };
    return { gsap, calls };
}

const { gsap, calls } = makeGsapMock();
globalThis.gsap = gsap;

await import('../animations.js');
const SearchAnimations = globalThis.window.SearchAnimations;

function resetCalls() {
    calls.timeline.length = 0;
    calls.to.length = 0;
    calls.fromTo.length = 0;
}

test('T2-DoD-playListModeCrossfade-oldEl-with-cb', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = false;
    const oldEl = { id: 'old' };
    let cbCount = 0;
    const result = SearchAnimations.playListModeCrossfade(oldEl, null, {
        onOldFadeComplete() { cbCount += 1; },
    });
    assert.notEqual(result, null, '正常路徑必須回傳 timeline');
    assert.equal(calls.to.length, 1, 'oldEl 有值必須淡出');
    assert.equal(calls.to[0].el, oldEl);
    assert.equal(calls.to[0].vars.duration, OpenAver.motion.DURATION.fast);
    assert.equal(calls.to[0].vars.ease, 'fluent-accel');
    assert.equal(cbCount, 1, 'oldEl 淡出完成必須呼叫 onOldFadeComplete');
    assert.equal(calls.fromTo.length, 0, 'newEl 為 null 時不淡入');
});

test('T2-DoD-playListModeCrossfade-oldEl-without-cb', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = false;
    const oldEl = { id: 'old' };
    assert.doesNotThrow(() => {
        SearchAnimations.playListModeCrossfade(oldEl, null, {});
    });
    assert.equal(calls.to.length, 1, '無 cb 時 oldEl 仍必須淡出');
    assert.equal(calls.to[0].vars.onComplete, undefined, '無 cb 時 onComplete 不得掛函式');
});

test('T2-DoD-playListModeCrossfade-oldEl-null-with-cb', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = false;
    let cbCount = 0;
    SearchAnimations.playListModeCrossfade(null, null, {
        onOldFadeComplete() { cbCount += 1; },
    });
    assert.equal(calls.to.length, 0, 'oldEl 為 null 時不播淡出');
    assert.equal(cbCount, 1, 'oldEl 為 null 時仍必須立即呼叫 onOldFadeComplete');
});

test('T2-DoD-playListModeCrossfade-newEl-fade-in', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = false;
    const newEl = { id: 'new' };
    SearchAnimations.playListModeCrossfade(null, newEl, {});
    assert.equal(calls.fromTo.length, 1, 'newEl 有值必須淡入');
    assert.equal(calls.fromTo[0].el, newEl);
    assert.deepEqual(calls.fromTo[0].from, { opacity: 0 });
    assert.equal(calls.fromTo[0].to.opacity, 1);
    assert.equal(calls.fromTo[0].to.duration, OpenAver.motion.DURATION.fast);
    assert.equal(calls.fromTo[0].to.ease, 'fluent-decel');
});

test('T2-DoD-playListModeCrossfade-shouldSkip-still-calls-cb', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = true;
    let cbCount = 0;
    const result = SearchAnimations.playListModeCrossfade({ id: 'old' }, { id: 'new' }, {
        onOldFadeComplete() { cbCount += 1; },
    });
    assert.equal(result, null, 'shouldSkip 必須回傳 null');
    assert.equal(calls.timeline.length, 0, 'shouldSkip 不得建立 timeline');
    assert.equal(cbCount, 1, 'shouldSkip 時 onOldFadeComplete 仍必須被呼叫');
    globalThis.OpenAver.prefersReducedMotion = false;
});

test('T2-DoD-playListModeCrossfade-gsap-undefined-still-calls-cb', () => {
    resetCalls();
    globalThis.OpenAver.prefersReducedMotion = false;
    const prev = globalThis.gsap;
    delete globalThis.gsap;
    let cbCount = 0;
    try {
        const result = SearchAnimations.playListModeCrossfade({ id: 'old' }, { id: 'new' }, {
            onOldFadeComplete() { cbCount += 1; },
        });
        assert.equal(result, null, 'gsap 未定義必須回傳 null');
        assert.equal(cbCount, 1, 'gsap 未定義時 onOldFadeComplete 仍必須被呼叫');
    } finally {
        globalThis.gsap = prev;
    }
});
