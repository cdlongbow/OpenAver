// TASK-156b-T5: computePreviewPosition 契約（浮層定位不變式）。
// 純函式；錨點貼近四緣各自一條。state.js 會連帶載入 charts.js，故先掛最小 window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;
globalThis.window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
});
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};
globalThis.document = globalThis.document || {
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    getElementById() { return null; },
    createElement() {
        return {
            style: {},
            appendChild() {},
        };
    },
    body: {
        appendChild() {},
        classList: { add() {}, remove() {}, contains() { return false; } },
    },
};

const { computePreviewPosition, libraryInsightsState } = await import('../state.js');

const POPUP = { width: 160, height: 224 };
const VIEWPORT = { width: 1440, height: 900 };
const GAP = 8;

function assertInside(pos, viewport, popup) {
    assert.ok(pos.left >= 0, 'left >= 0');
    assert.ok(pos.top >= 0, 'top >= 0');
    assert.ok(pos.left + popup.width <= viewport.width, 'right edge inside');
    assert.ok(pos.top + popup.height <= viewport.height, 'bottom edge inside');
}

test('computePreviewPosition: 錨點正常（右側空間足夠）時貼在錨點右側', () => {
    const anchor = { top: 100, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.equal(pos.left, anchor.left + anchor.width + GAP);
    assert.equal(pos.top, anchor.top);
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗右緣時，改貼左側且仍完全落在視窗內', () => {
    const anchor = { top: 100, left: 1400, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.ok(pos.left < anchor.left, 'flips to left of anchor');
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗左緣時，left 不得為負', () => {
    const anchor = { top: 100, left: 4, width: 32, height: 32 };
    // 右側也放不下（窄視窗模擬）
    const narrow = { width: 180, height: 900 };
    const pos = computePreviewPosition(anchor, narrow, POPUP);
    assert.ok(pos.left >= 0);
    assertInside(pos, narrow, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗下緣時，浮層仍完全落在視窗內', () => {
    const anchor = { top: 850, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.ok(pos.top + POPUP.height <= VIEWPORT.height);
    assert.ok(pos.top >= 0);
    assertInside(pos, VIEWPORT, POPUP);
});

test('computePreviewPosition: 錨點貼近視窗上緣時，top 不得為負', () => {
    const anchor = { top: 2, left: 200, width: 32, height: 32 };
    const pos = computePreviewPosition(anchor, VIEWPORT, POPUP);
    assert.equal(pos.top, 2);
    assert.ok(pos.top >= 0);
    assertInside(pos, VIEWPORT, POPUP);
});

test('previewPositionStyle: viewport 以 clientWidth 為準（不含捲軸）', () => {
    // 模擬 390 視窗、捲軸佔 15px：innerWidth=390、clientWidth=375（CDP #19 實況）
    globalThis.window.innerWidth = 390;
    globalThis.window.innerHeight = 844;
    globalThis.document.documentElement = {
        clientWidth: 375,
        clientHeight: 844,
    };
    const state = libraryInsightsState();
    // 錨點靠右：若誤用 innerWidth=390，會貼右側 left=225、right=385 > clientWidth=375
    state.previewAnchorRect = { top: 600, left: 193, width: 32, height: 32 };
    const style = state.previewPositionStyle();
    const left = parseFloat(style.left);
    assert.ok(Number.isFinite(left), 'left is a number');
    assert.ok(left + POPUP.width <= 375, `right edge within clientWidth; left=${left}`);
    // 證明不是誤用 innerWidth：若用 390 夾限，此錨點會得到 left=225
    assert.notEqual(left, 225);
});
