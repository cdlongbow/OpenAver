// TASK-156b-T3: charts.js 純函式分支（resolveYearBarColorMode / shouldAnimate）。
// 不碰 DOM／ECharts 實例。

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

const {
    resolveYearBarColorMode,
    shouldAnimate,
    formatRgbaChannels,
} = await import('../charts.js');

// ── resolveYearBarColorMode ──────────────────────────────────────────

test('resolveYearBarColorMode: 無焦點 → neutral', () => {
    assert.equal(resolveYearBarColorMode(null), 'neutral');
    assert.equal(resolveYearBarColorMode(undefined), 'neutral');
});

test('resolveYearBarColorMode: 片商焦點仍是中性計數色（不得誤判為女優焦點才有的分類色）', () => {
    assert.equal(
        resolveYearBarColorMode({ type: 'maker', value: 'SOD' }),
        'neutral',
    );
});

test('resolveYearBarColorMode: 女優焦點 → byMaker', () => {
    assert.equal(
        resolveYearBarColorMode({ type: 'actress', value: 'Alice' }),
        'byMaker',
    );
});

// ── shouldAnimate ────────────────────────────────────────────────────

test('shouldAnimate: 系統未開「減少動態效果」時回傳 true（播放動畫）', () => {
    assert.equal(shouldAnimate(false), true);
});

test('shouldAnimate: 系統開啟「減少動態效果」時回傳 false（不播放動畫）', () => {
    assert.equal(shouldAnimate(true), false);
});

// ── formatRgbaChannels ───────────────────────────────────────────────

test('formatRgbaChannels: a===255 時回傳 rgb()（不帶 alpha）', () => {
    assert.equal(formatRgbaChannels(128, 149, 170, 255), 'rgb(128, 149, 170)');
});

test('formatRgbaChannels: a<255 時回傳 rgba()，alpha 為 a/255', () => {
    assert.equal(
        formatRgbaChannels(10, 20, 30, 128),
        'rgba(10, 20, 30, ' + (128 / 255) + ')',
    );
});
