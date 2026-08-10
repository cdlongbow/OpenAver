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

test('age + >= ：正向 age>=lo、反向 age<lo 不命中', () => {
    const names = namesMatching([{ dim: 'age', op: '>=', value: '37', value2: null }]);
    // full=37, tall=40 命中；young=25, mid=35 不命中
    assert.deepEqual(names.sort(), ['full', 'tall'].sort());
});

test('age + range ：正向 lo<=age<=hi（含邊界）、反向超出不命中', () => {
    const names = namesMatching([{ dim: 'age', op: 'range', value: '35', value2: '40' }]);
    // mid=35, full=37, tall=40 命中；young=25 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'tall'].sort());
});

// ── height ─────────────────────────────────────────────────────────────────

test('height + = ：正向命中恰等、反向不等不命中', () => {
    const names = namesMatching([{ dim: 'height', op: '=', value: '160', value2: null }]);
    assert.deepEqual(names, ['full']);
});

test('height + <= ：正向 height<=lo、反向 height>lo 不命中', () => {
    const names = namesMatching([{ dim: 'height', op: '<=', value: '160', value2: null }]);
    // full=160, young=155 命中；tall=170, mid=165 不命中
    assert.deepEqual(names.sort(), ['full', 'young'].sort());
});

test('height + >= ：正向 height>=lo、反向 height<lo 不命中', () => {
    const names = namesMatching([{ dim: 'height', op: '>=', value: '160', value2: null }]);
    // full=160, tall=170, mid=165 命中；young=155 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'tall'].sort());
});

test('height + range ：正向 lo<=height<=hi（含邊界）、反向超出不命中', () => {
    const names = namesMatching([{ dim: 'height', op: 'range', value: '155', value2: '165' }]);
    // young=155, full=160, mid=165 命中；tall=170 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'young'].sort());
});

// ── cup ────────────────────────────────────────────────────────────────────

test('cup + = ：正向命中恰等、反向不等不命中', () => {
    const names = namesMatching([{ dim: 'cup', op: '=', value: 'B', value2: null }]);
    assert.deepEqual(names, ['full']);
});

test('cup + <= ：正向 cup<=lo、反向 cup>lo 不命中', () => {
    const names = namesMatching([{ dim: 'cup', op: '<=', value: 'B', value2: null }]);
    // full=B, young=A 命中；mid=C, tall=D 不命中
    assert.deepEqual(names.sort(), ['full', 'young'].sort());
});

test('cup + >= ：正向 cup>=lo、反向 cup<lo 不命中', () => {
    const names = namesMatching([{ dim: 'cup', op: '>=', value: 'B', value2: null }]);
    // full=B, mid=C, tall=D 命中；young=A 不命中
    assert.deepEqual(names.sort(), ['full', 'mid', 'tall'].sort());
});

// ── fail-closed ────────────────────────────────────────────────────────────

test('fail-closed：cup + range 恆不符合（即使 value/value2 合法）', () => {
    const pred = buildActressPillPredicate([
        { dim: 'cup', op: 'range', value: 'A', value2: 'D' },
    ]);
    assertNoThrow(() => {
        for (const a of ALL) {
            assert.equal(pred(a), false, `cup+range 對 ${a.name} 必須 fail-closed`);
        }
    }, 'cup+range 不得拋錯');
});

test('fail-closed：未知 op（~=）對任何 dim 不符合、不拋錯', () => {
    for (const dim of ['age', 'height', 'cup']) {
        const pred = buildActressPillPredicate([
            { dim, op: '~=', value: '37', value2: null },
        ]);
        assertNoThrow(() => {
            for (const a of ALL) {
                assert.equal(pred(a), false, `op~= dim=${dim} 對 ${a.name} 必須 fail-closed`);
            }
        }, `未知 op dim=${dim} 不得拋錯`);
    }
});

test('fail-closed：range 缺 value2（null / undefined / 空字串）→ 不符合、不拋錯', () => {
    const cases = [null, undefined, ''];
    for (const value2 of cases) {
        const pred = buildActressPillPredicate([
            { dim: 'age', op: 'range', value: '30', value2 },
        ]);
        assertNoThrow(() => {
            for (const a of ALL) {
                assert.equal(
                    pred(a),
                    false,
                    `value2=${JSON.stringify(value2)} 對 ${a.name} 必須 fail-closed`,
                );
            }
        }, `value2=${JSON.stringify(value2)} 不得拋錯`);
    }
});

test('fail-closed：op 為 Object.prototype key 一律不符合且不拋錯', () => {
    // 鏡射 116a-T2 對 dim 的手法；if/else 鏈天生沒有 bracket 查表洞，但仍要顯式覆蓋
    ['toString', 'constructor', '__proto__', 'hasOwnProperty', 'valueOf'].forEach((op) => {
        const pred = buildActressPillPredicate([
            { dim: 'height', op, value: '160', value2: null },
        ]);
        assertNoThrow(() => {
            for (const a of ALL) {
                assert.equal(pred(a), false, `op=${op} 對 ${a.name} 必須 fail-closed`);
            }
        }, `op=${op} 不得拋錯`);
    });
});
