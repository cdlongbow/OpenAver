// TASK-116a-T1: actress-metric.js 純函式取值契約
// 零 import 依賴的模組，不需要 importmap resolve hook / window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const metricMod = await import('../actress-metric.js');
const { actressAgeValue, actressHeightValue, actressCupValue, actressMetricRange } = metricMod;

// ── CUP_RANK 已刪除（120-C1：改字元碼推導，不留第二張真實來源）────────────────

test('CUP_RANK export 已刪除（AC-4）', () => {
    assert.equal(metricMod.CUP_RANK, undefined);
});

// ── actressAgeValue ────────────────────────────────────────────────────────

test('actressAgeValue 有值（數字）→ 回傳數字', () => {
    assert.equal(actressAgeValue({ age: 37 }), 37);
});

test('actressAgeValue 有值（字串）→ 回傳同一個數字 37（Number 型別收斂）', () => {
    const fromStr = actressAgeValue({ age: '37' });
    const fromNum = actressAgeValue({ age: 37 });
    assert.equal(fromStr, 37);
    assert.equal(fromNum, 37);
    assert.equal(fromStr, fromNum); // === 相等
    assert.equal(typeof fromStr, 'number');
});

test('actressAgeValue null → null', () => {
    assert.equal(actressAgeValue({ age: null }), null);
});

test('actressAgeValue undefined（缺欄）→ null', () => {
    assert.equal(actressAgeValue({}), null);
});

test('actressAgeValue 非數字字串 "unknown" → null（fail-closed，不回 NaN）', () => {
    assert.equal(actressAgeValue({ age: 'unknown' }), null);
});

test('actressAgeValue 空字串 → null（不回 0）', () => {
    assert.equal(actressAgeValue({ age: '' }), null);
});

test('actressAgeValue 全空白字串 "  " → null', () => {
    assert.equal(actressAgeValue({ age: '  ' }), null);
});

test('actressAgeValue NaN → null', () => {
    assert.equal(actressAgeValue({ age: NaN }), null);
});

// Codex PR review P3：isNaN(Infinity) 是 false，用 isNaN 會讓 '1e999' 漏成 Infinity 通過。
// 這一條鎖住「fail-closed」名實相符——Infinity 無法與任何女優的數值比大小。
test("actressAgeValue 溢位寫法 '1e999' / Infinity → null（不得回 Infinity）", () => {
    assert.equal(actressAgeValue({ age: '1e999' }), null);
    assert.equal(actressAgeValue({ age: Infinity }), null);
    assert.equal(actressAgeValue({ age: -Infinity }), null);
});

// ── actressHeightValue ─────────────────────────────────────────────────────

test('actressHeightValue 有值（"160cm"）→ 160', () => {
    assert.equal(actressHeightValue({ height: '160cm' }), 160);
});

test('actressHeightValue 純數字字串 → 數字', () => {
    assert.equal(actressHeightValue({ height: '155' }), 155);
});

test('actressHeightValue null → null', () => {
    assert.equal(actressHeightValue({ height: null }), null);
});

test('actressHeightValue undefined（缺欄）→ null', () => {
    assert.equal(actressHeightValue({}), null);
});

test('actressHeightValue 空字串 → null', () => {
    assert.equal(actressHeightValue({ height: '' }), null);
});

test('actressHeightValue 非數字前綴字串 → null', () => {
    assert.equal(actressHeightValue({ height: 'tall' }), null);
});

// ── actressCupValue ────────────────────────────────────────────────────────

test('actressCupValue 有值 B → 2', () => {
    assert.equal(actressCupValue({ cup: 'B' }), 2);
});

test('actressCupValue 有值 A → 1、K → 11', () => {
    assert.equal(actressCupValue({ cup: 'A' }), 1);
    assert.equal(actressCupValue({ cup: 'K' }), 11);
});

test('actressCupValue L → 12（AC-1）', () => {
    assert.equal(actressCupValue({ cup: 'L' }), 12);
});

test('actressCupValue Z → 26（AC-1）', () => {
    assert.equal(actressCupValue({ cup: 'Z' }), 26);
});

test('actressCupValue null → null', () => {
    assert.equal(actressCupValue({ cup: null }), null);
});

test('actressCupValue 小寫 b → null（大小寫敏感）', () => {
    assert.equal(actressCupValue({ cup: 'b' }), null);
});

test('actressCupValue undefined（缺欄）→ null', () => {
    assert.equal(actressCupValue({}), null);
});

test('actressCupValue 空字串 → null（AC-3）', () => {
    assert.equal(actressCupValue({ cup: '' }), null);
});

test("actressCupValue 'AA' → null（AC-3，非單一字母）", () => {
    assert.equal(actressCupValue({ cup: 'AA' }), null);
});

test('actressCupValue 非字串 123 → null（AC-3）', () => {
    assert.equal(actressCupValue({ cup: 123 }), null);
});

test("actressCupValue 'toString' → null（AC-3，不得 fail-open 回函式）", () => {
    assert.equal(actressCupValue({ cup: 'toString' }), null);
});

test("actressCupValue 'constructor' / '__proto__' / 'valueOf' → null（AC-3）", () => {
    assert.equal(actressCupValue({ cup: 'constructor' }), null);
    assert.equal(actressCupValue({ cup: '__proto__' }), null);
    assert.equal(actressCupValue({ cup: 'valueOf' }), null);
});

test('actressCupValue 全形 Ａ → null（AC-3）', () => {
    assert.equal(actressCupValue({ cup: 'Ａ' }), null);
});

test("actressCupValue '['（Z+1）→ null（AC-3）", () => {
    assert.equal(actressCupValue({ cup: '[' }), null);
});

test("actressCupValue '@'（A-1）→ null（AC-3）", () => {
    assert.equal(actressCupValue({ cup: '@' }), null);
});

// ── actressMetricRange（116c-T2，CD-116c-6）─────────────────────────────────

test('actressMetricRange 正常 list → { min, max }（age）', () => {
    const list = [{ age: 37 }, { age: 25 }, { age: 40 }];
    assert.deepEqual(actressMetricRange(list, actressAgeValue), { min: 25, max: 40 });
});

test('actressMetricRange 正常 list → { min, max }（height）', () => {
    const list = [{ height: '160cm' }, { height: '170cm' }, { height: '155cm' }];
    assert.deepEqual(actressMetricRange(list, actressHeightValue), { min: 155, max: 170 });
});

test('actressMetricRange 混入缺值／怪格式 → 只計得出值的那些', () => {
    const list = [
        { height: '160cm' },
        { height: null },
        { height: 'tall' },     // actressHeightValue 回 null
        {},                     // 缺欄
        { height: '146cm' },
    ];
    assert.deepEqual(actressMetricRange(list, actressHeightValue), { min: 146, max: 160 });
});

test('actressMetricRange 混入怪格式 age（unknown/空字串/NaN）→ 只計得出值的那些', () => {
    const list = [
        { age: 37 },
        { age: 'unknown' },   // actressAgeValue 回 null
        { age: '' },          // actressAgeValue 回 null
        { age: NaN },         // actressAgeValue 回 null
        { age: 25 },
    ];
    assert.deepEqual(actressMetricRange(list, actressAgeValue), { min: 25, max: 37 });
});

test('actressMetricRange 全部取不到值 → null', () => {
    const list = [{ height: null }, {}, { height: 'tall' }];
    assert.equal(actressMetricRange(list, actressHeightValue), null);
});

test('actressMetricRange 空 list → null', () => {
    assert.equal(actressMetricRange([], actressHeightValue), null);
});

test('actressMetricRange 單一元素 list → min === max', () => {
    assert.deepEqual(actressMetricRange([{ age: 30 }], actressAgeValue), { min: 30, max: 30 });
});

test('actressMetricRange cup 含 Z → max = 26（AC-6）', () => {
    const list = [{ cup: 'A' }, { cup: 'K' }, { cup: 'Z' }, { cup: null }];
    assert.deepEqual(actressMetricRange(list, actressCupValue), { min: 1, max: 26 });
});
