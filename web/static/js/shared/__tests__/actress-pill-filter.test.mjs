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


// ── 三維度正向命中 ─────────────────────────────────────────────────────────


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


test('fail-closed：女優該欄位缺值（height null）不出現在任何身高 pill 結果', () => {
    const pred = buildActressPillPredicate([{ dim: 'height', op: '=', value: '160cm' }]);
    assert.equal(pred(A_NO_HEIGHT), false);
    // 亦對「她自己本該有的值」不命中：缺 height 的女優對任何身高條件都不符合
    const predAny = buildActressPillPredicate([{ dim: 'height', op: '=', value: '999cm' }]);
    assert.equal(predAny(A_NO_HEIGHT), false);
});


// ── AC9 / CD-116a-1 交叉驗證 ───────────────────────────────────────────────

