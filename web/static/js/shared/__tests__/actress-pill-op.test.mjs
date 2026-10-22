// TASK-116b-T1: 四 op × 三維度 predicate 矩陣 ＋ fail-closed（含 op 原型鏈）。
// 只 import shared/actress-pill-filter.js → actress-metric.js；plan §4 FE-GUARD-11 仍要求 window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

// FE-GUARD-11：T1–T4 全部新測試檔都加（即使本檔理論上不需要）
globalThis.window = globalThis;

const { buildActressPillPredicate } = await import('../actress-pill-filter.js');

// Fixture：三維度皆有值 + 邊界鄰近值（正向／反向共用）
const A_FULL = { name: 'full', age: 37, height: '160cm', cup: 'B' };
const A_YOUNG = { name: 'young', age: 25, height: '155cm', cup: 'A' };
const A_TALL = { name: 'tall', age: 40, height: '170cm', cup: 'D' };
const A_MID = { name: 'mid', age: 35, height: '165cm', cup: 'C' };
const ALL = [A_FULL, A_YOUNG, A_TALL, A_MID];

function namesMatching(pills) {
    const pred = buildActressPillPredicate(pills);
    return ALL.filter(pred).map((a) => a.name);
}

function assertNoThrow(fn, label) {
    assert.doesNotThrow(fn, label);
}

// ── age ────────────────────────────────────────────────────────────────────

test('age + = ：正向命中恰等、反向不等不命中', () => {
    const names = namesMatching([{ dim: 'age', op: '=', value: '37', value2: null }]);
    assert.deepEqual(names, ['full']);
});

test('age + <= ：正向 age<=lo、反向 age>lo 不命中', () => {
    const names = namesMatching([{ dim: 'age', op: '<=', value: '37', value2: null }]);
    // full=37, young=25, mid=35 命中；tall=40 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'young'].sort());
});


test('age + range ：正向 lo<=age<=hi（含邊界）、反向超出不命中', () => {
    const names = namesMatching([{ dim: 'age', op: 'range', value: '35', value2: '40' }]);
    // mid=35, full=37, tall=40 命中；young=25 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'tall'].sort());
});

// ── height ─────────────────────────────────────────────────────────────────


// ── cup ────────────────────────────────────────────────────────────────────


// ── fail-closed ────────────────────────────────────────────────────────────


