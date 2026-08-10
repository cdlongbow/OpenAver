// TASK-116a-T1: actress-metric.js 純函式取值契約
// 零 import 依賴的模組，不需要 importmap resolve hook / window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { CUP_RANK, actressAgeValue, actressHeightValue, actressCupValue } = await import('../actress-metric.js');

// ── CUP_RANK 表 ────────────────────────────────────────────────────────────

test('CUP_RANK 與現況 cupRank 逐字相同：A=1…K=11', () => {
    assert.deepEqual(CUP_RANK, {
        A: 1, B: 2, C: 3, D: 4, E: 5, F: 6, G: 7, H: 8, I: 9, J: 10, K: 11,
    });
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

test('actressCupValue null → null', () => {
    assert.equal(actressCupValue({ cup: null }), null);
});

test('actressCupValue 未知字母 Z → null', () => {
    assert.equal(actressCupValue({ cup: 'Z' }), null);
});

test('actressCupValue 小寫 b → null（大小寫敏感）', () => {
    assert.equal(actressCupValue({ cup: 'b' }), null);
});

test('actressCupValue undefined（缺欄）→ null', () => {
    assert.equal(actressCupValue({}), null);
});
