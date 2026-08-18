// TASK-116a-T2: actress-pill-filter.js 純函式 predicate 契約。
// 只 import shared/actress-pill-filter.js → actress-metric.js，零 Alpine / window 依賴。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const { buildActressPillPredicate } = await import('../actress-pill-filter.js');
const { actressHeightValue } = await import('../actress-metric.js');

// Fixture：三維度皆有值 + 各一缺值（fail-closed / 正向命中共用）
const A_FULL = { name: 'full', age: 37, height: '160cm', cup: 'B' };
const A_TALL = { name: 'tall', age: 25, height: '170cm', cup: 'C' };
const A_NO_HEIGHT = { name: 'noHt', age: 30, height: null, cup: 'D' };
const A_NO_AGE = { name: 'noAge', age: null, height: '155cm', cup: 'A' };
const A_NO_CUP = { name: 'noCup', age: 28, height: '150cm', cup: null };
const ALL = [A_FULL, A_TALL, A_NO_HEIGHT, A_NO_AGE, A_NO_CUP];

function namesMatching(pills) {
    const pred = buildActressPillPredicate(pills);
    return ALL.filter(pred).map((a) => a.name);
}

// ── 空陣列 / undefined 語意 ────────────────────────────────────────────────

test('buildActressPillPredicate([])：全部通過', () => {
    const pred = buildActressPillPredicate([]);
    assert.equal(typeof pred, 'function');
    for (const a of ALL) {
        assert.equal(pred(a), true, `${a.name} 應通過空 pill 條件`);
    }
});

test('buildActressPillPredicate(undefined)：全部通過（harness 未合併 stateBase 的安全 fallback）', () => {
    const pred = buildActressPillPredicate(undefined);
    assert.equal(typeof pred, 'function');
    for (const a of ALL) {
        assert.equal(pred(a), true, `${a.name} 應通過 undefined pill 條件`);
    }
});

// ── 三維度正向命中 ─────────────────────────────────────────────────────────

test('身高 pill =160cm 正向命中 full', () => {
    const names = namesMatching([{ dim: 'height', op: '=', value: '160cm' }]);
    assert.deepEqual(names, ['full']);
});

test('罩杯 pill =B 正向命中 full', () => {
    const names = namesMatching([{ dim: 'cup', op: '=', value: 'B' }]);
    assert.deepEqual(names, ['full']);
});

test('年齡 pill =37 正向命中 full', () => {
    const names = namesMatching([{ dim: 'age', op: '=', value: '37' }]);
    assert.deepEqual(names, ['full']);
});

// ── 罩杯是「有序分級」不是「類別」：≤／≥ 依 actressCupValue() 的名次比大小 ─────
// spec-116c §4.4／:197（`≥B罩杯` 是正常顯示形式）與 :272（罩杯沒有自訂區間的理由
// 正是「≤B／≥E 已涵蓋真實問題」）。spec-116 §1 的起點例子就是「B 罩杯以下」。
// 這三條是 Codex PR review #132 P2 打出來的覆蓋洞：在此之前罩杯只有 `=` 有測試，
// 把罩杯改成「只能等於」不會讓任何一支測試轉紅——而那會砍掉本功能的核心用途。
// 罩杯**沒有**區間，那條由下面既有的 `cup + range 恆不符合` 守著，兩者不重疊。

test('罩杯 pill ≤B：A 與 B 都命中（rank 比大小，不是字串相等）', () => {
    const names = namesMatching([{ dim: 'cup', op: '<=', value: 'B' }]);
    assert.deepEqual(names, ['full', 'noAge'], 'full=B、noAge=A；C/D 落榜、cup 缺值不入選');
});

test('罩杯 pill ≥C：C 與 D 都命中', () => {
    const names = namesMatching([{ dim: 'cup', op: '>=', value: 'C' }]);
    assert.deepEqual(names, ['tall', 'noHt'], 'tall=C、noHt=D；A/B 落榜');
});

test('罩杯 ≤／≥ 與身高 pill 可交集（spec-116 §1 的起點例子：矮 ＋ 罩杯以下）', () => {
    const names = namesMatching([
        { dim: 'cup', op: '<=', value: 'B' },
        { dim: 'height', op: '<=', value: '160' },
    ]);
    assert.deepEqual(names, ['full', 'noAge'], 'full=160cm/B、noAge=155cm/A 同時符合');
});

// TASK-120-C1 AC-7：≥K 必須命中 L+。自建局部陣列，不得動上面的 ALL。
test("罩杯 pill ≥K：cup:'L'／'Z' 回 true（AC-7，局部 list）", () => {
    const pred = buildActressPillPredicate([{ dim: 'cup', op: '>=', value: 'K' }]);
    const local = [
        { name: 'k', cup: 'K' },
        { name: 'l', cup: 'L' },
        { name: 'z', cup: 'Z' },
        { name: 'a', cup: 'A' },
        { name: 'none', cup: null },
    ];
    assert.equal(pred({ cup: 'L' }), true);
    assert.equal(pred({ cup: 'Z' }), true);
    assert.deepEqual(
        local.filter(pred).map((a) => a.name),
        ['k', 'l', 'z'],
    );
});

// ── 多 pill 交集 ───────────────────────────────────────────────────────────

test('多 pill 取交集：age=37 AND height=160cm 只剩 full', () => {
    const names = namesMatching([
        { dim: 'age', op: '=', value: '37' },
        { dim: 'height', op: '=', value: '160cm' },
    ]);
    assert.deepEqual(names, ['full']);
});

// ── fail-closed ────────────────────────────────────────────────────────────

test('fail-closed：未知 dim → 不符合', () => {
    const pred = buildActressPillPredicate([{ dim: 'foo', op: '=', value: 'x' }]);
    assert.equal(pred(A_FULL), false);
    assert.equal(pred(A_TALL), false);
});

test('fail-closed：Object.prototype 的 key 當 dim 一律不符合（不得 fail-open / 不得拋錯）', () => {
    // 裸 EXTRACTORS[dim] 會讓 toString 取到 Function.prototype.toString 而通過 !extractor
    // 檢查，predicate 於是對每一位女優回 true；__proto__ / hasOwnProperty 則直接拋錯。
    ['toString', 'constructor', '__proto__', 'hasOwnProperty', 'valueOf'].forEach((dim) => {
        const pred = buildActressPillPredicate([{ dim, op: '=', value: 'x' }]);
        assert.equal(pred(A_FULL), false, `dim=${dim} 必須不符合`);
        assert.equal(pred(A_TALL), false, `dim=${dim} 必須不符合`);
    });
});

test('fail-closed：未知 op（~=）→ 不符合', () => {
    // 116b 之後 <= / >= / range 皆為合法 op；此處改用真正未知的 op
    const pred = buildActressPillPredicate([{ dim: 'height', op: '~=', value: '160cm' }]);
    assert.equal(pred(A_FULL), false);
    assert.equal(pred(A_TALL), false);
});

test('fail-closed：女優該欄位缺值（height null）不出現在任何身高 pill 結果', () => {
    const pred = buildActressPillPredicate([{ dim: 'height', op: '=', value: '160cm' }]);
    assert.equal(pred(A_NO_HEIGHT), false);
    // 亦對「她自己本該有的值」不命中：缺 height 的女優對任何身高條件都不符合
    const predAny = buildActressPillPredicate([{ dim: 'height', op: '=', value: '999cm' }]);
    assert.equal(predAny(A_NO_HEIGHT), false);
});

test('fail-closed：女優 age null 對年齡 pill 不符合', () => {
    const pred = buildActressPillPredicate([{ dim: 'age', op: '=', value: '30' }]);
    assert.equal(pred(A_NO_AGE), false);
});

test('fail-closed：女優 cup null 對罩杯 pill 不符合', () => {
    const pred = buildActressPillPredicate([{ dim: 'cup', op: '=', value: 'A' }]);
    assert.equal(pred(A_NO_CUP), false);
});

// ── AC9 / CD-116a-1 交叉驗證 ───────────────────────────────────────────────

test('AC9：排序能取到身高的女優，必存在能命中她的身高 pill 值', () => {
    // 對每一位 actressHeightValue 非 null 的女優，用她的 height 字面當 pill 值應命中
    for (const a of ALL) {
        const hv = actressHeightValue(a);
        if (hv == null) continue;
        // 產品 pill value 是使用者點到的原始字串（如 '160cm'），不是 extractor 回的數字
        const pred = buildActressPillPredicate([{ dim: 'height', op: '=', value: a.height }]);
        assert.equal(
            pred(a),
            true,
            `${a.name} height=${a.height}（extractor=${hv}）必須被同值 pill 命中`,
        );
    }
});
