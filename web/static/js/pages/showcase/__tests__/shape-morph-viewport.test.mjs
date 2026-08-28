// TASK-133a-T1：captureShapeState / playShapeMorph 視野分流契約
//
// 真的 import() animations.js，用假 DOM／假 gsap／假 Flip 驅動——不是源碼字串斷言。
// Stub 形狀照 pick-star-motion.test.mjs:20-60。

import { test } from 'node:test';
import assert from 'node:assert/strict';

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

globalThis.OpenAver = {
    prefersReducedMotion: false,
    motion: { DURATION: { medium: 0.333 } },
};

await import('../animations.js');
const ShowcaseAnimations = globalThis.window.ShowcaseAnimations;

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
            // NodeList-ish：帶 length，可被 Array.from / forEach 消費
            const list = Object.assign(cards.slice(), { length: cards.length });
            list.forEach = Array.prototype.forEach;
            return list;
        },
        getQueryCount() { return queryCount; },
        resetQueryCount() { queryCount = 0; },
    };
}

/** 91 張假卡，top 從 -1000 均勻鋪到 +8000；高度固定 180。 */
function buildSpreadCards() {
    const cards = [];
    const n = 91;
    const topMin = -1000;
    const topMax = 8000;
    for (let i = 0; i < n; i++) {
        const top = topMin + ((topMax - topMin) * i) / (n - 1);
        const bottom = top + 180;
        cards.push(makeCard({ top, bottom, left: 0, right: 100, width: 100, height: 180 }));
    }
    return cards;
}

function expectedPicked(cards, viewportH) {
    return cards.filter((c) => {
        const rect = c._rect;
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

test('captureShapeState：只收視野 ±200px 內的卡', () => {
    resetCalls();
    const cards = buildSpreadCards();
    const gridEl = makeGrid(cards);
    const expected = expectedPicked(cards, VIEWPORT_H);
    assert.ok(expected.length > 0, 'fixture 必須含至少一張視野內卡');
    assert.ok(expected.length < cards.length, 'fixture 必須含視野外卡');

    const result = ShowcaseAnimations.captureShapeState(gridEl);

    assert.ok(result && Array.isArray(result.cards), '必須回傳 { state, cards }');
    assert.equal(result.cards.length, expected.length);
    assert.deepEqual(result.cards, expected);
    assert.equal(flipCalls.getState.length, 1);
    assert.deepEqual(flipCalls.getState[0][0], expected);
});

test('captureShapeState：帶 simple 快速路徑，且不帶 props', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
        makeCard({ top: 200, bottom: 380, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);

    ShowcaseAnimations.captureShapeState(gridEl);

    assert.equal(flipCalls.getState.length, 1);
    const opts = flipCalls.getState[0][1];
    assert.ok(opts, 'Flip.getState 必須帶第二引數');
    assert.equal(opts.simple, true);
    assert.equal(opts.props, undefined);
});

test('captureShapeState：量測前先停掉進場動畫並清乾淨', () => {
    resetCalls();
    const cards = [
        makeCard({ top: 50, bottom: 230, left: 0, right: 100, width: 100, height: 180 }, { animating: true }),
        makeCard({ top: 80, bottom: 260, left: 0, right: 100, width: 100, height: 180 }, { animating: true }),
    ];
    const gridEl = makeGrid(cards);

    // 用呼叫序：把 getState 發生時的 kill/set 次數記下來
    let killCountAtGetState = -1;
    let setCountAtGetState = -1;
    const origGetState = globalThis.Flip.getState;
    globalThis.Flip.getState = (...args) => {
        killCountAtGetState = gsapCalls.killTweensOf.length;
        setCountAtGetState = gsapCalls.set.length;
        return origGetState(...args);
    };

    try {
        ShowcaseAnimations.captureShapeState(gridEl);
    } finally {
        globalThis.Flip.getState = origGetState;
    }

    assert.ok(killCountAtGetState >= 1, 'gsap.killTweensOf 必須在 Flip.getState 之前被呼叫');
    assert.ok(setCountAtGetState >= 1, 'gsap.set(clearProps) 必須在 Flip.getState 之前被呼叫');

    const clearCall = gsapCalls.set.find((args) => args[1] && args[1].clearProps);
    assert.ok(clearCall, '必須呼叫 gsap.set 帶 clearProps');
    assert.equal(clearCall[1].clearProps, 'transform,opacity');

    for (const c of cards) {
        assert.ok(c._removed.includes('gsap-animating'), '每張卡的 gsap-animating 必須被 remove');
    }
});

test('playShapeMorph：只吃 captureShapeState 交回的那批卡，不得重新挑卡', () => {
    resetCalls();
    const allCards = buildSpreadCards();
    const gridEl = makeGrid(allCards);

    // 模擬 capture 已完成後的收據形狀（本測重點在 play，不依賴 capture 新介面）
    const picked = expectedPicked(allCards, VIEWPORT_H);
    const fakeState = { __captured: true };
    const captured = { state: fakeState, cards: picked };
    // 先讓 grid 被 query 一次（模擬呼叫端／舊 capture），再量 play 期間增量
    gridEl.querySelectorAll('.av-card-preview');
    const queriesAfterCapture = gridEl.getQueryCount();
    flipCalls.killFlipsOf.length = 0;
    flipCalls.from.length = 0;

    const tl = ShowcaseAnimations.playShapeMorph(captured, gridEl);

    assert.ok(tl, '正常路徑必須回傳 timeline');
    assert.equal(
        gridEl.getQueryCount(),
        queriesAfterCapture,
        'playShapeMorph 期間不得再呼叫 gridEl.querySelectorAll',
    );
    assert.equal(flipCalls.killFlipsOf.length, 1);
    assert.equal(flipCalls.killFlipsOf[0][0], captured.cards);
    assert.equal(flipCalls.from.length, 1);
    assert.equal(flipCalls.from[0][0], captured.state);
});

test('playShapeMorph：reduced-motion 時回 null 且不建動畫', () => {
    resetCalls();
    globalThis.window.OpenAver.prefersReducedMotion = true;

    const cards = [
        makeCard({ top: 100, bottom: 280, left: 0, right: 100, width: 100, height: 180 }),
    ];
    const gridEl = makeGrid(cards);
    const captured = { state: { __fake: true }, cards };

    const result = ShowcaseAnimations.playShapeMorph(captured, gridEl);

    assert.equal(result, null);
    assert.equal(flipCalls.from.length, 0, 'reduced-motion 時 Flip.from 零呼叫');
});

test('captureShapeState / playShapeMorph：沒有卡或快照殘缺時 fail-closed 回 null', () => {
    resetCalls();

    const emptyGrid = makeGrid([]);
    assert.equal(ShowcaseAnimations.captureShapeState(emptyGrid), null);

    // cards: []／null captured → null。grid 用空集合：mutation「重挑卡」對空 grid
    // 仍 length=0，不會把本支一併染紅（「不得重新挑卡」那支才是該 mutation 的 lone red）。
    assert.equal(
        ShowcaseAnimations.playShapeMorph({ state: {}, cards: [] }, emptyGrid),
        null,
    );
    assert.equal(ShowcaseAnimations.playShapeMorph(null, emptyGrid), null);
});
