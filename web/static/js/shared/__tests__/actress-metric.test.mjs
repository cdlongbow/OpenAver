// TASK-116a-T1: actress-metric.js 純函式取值契約
// 零 import 依賴的模組，不需要 importmap resolve hook / window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const metricMod = await import('../actress-metric.js');
const { actressAgeValue, actressHeightValue, actressCupValue, actressMetricRange } = metricMod;

// ── CUP_RANK 已刪除（120-C1：改字元碼推導，不留第二張真實來源）────────────────


// ── actressAgeValue ────────────────────────────────────────────────────────


// Codex PR review P3：isNaN(Infinity) 是 false，用 isNaN 會讓 '1e999' 漏成 Infinity 通過。
// 這一條鎖住「fail-closed」名實相符——Infinity 無法與任何女優的數值比大小。

// ── actressHeightValue ─────────────────────────────────────────────────────

test('actressHeightValue 有值（"160cm"）→ 160', () => {
    assert.equal(actressHeightValue({ height: '160cm' }), 160);
});


// ── actressCupValue ────────────────────────────────────────────────────────


// ── actressMetricRange（116c-T2，CD-116c-6）─────────────────────────────────


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


