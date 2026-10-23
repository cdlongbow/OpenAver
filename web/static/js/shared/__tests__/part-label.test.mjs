// TASK-122-T3: formatPartLabel 三分支契約。
// 純函式；window.t 在前綴不一致時才碰，測試自行 stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.window.t = (key, params) => {
    if (key === 'showcase.video.part_count_fallback') return `${params.n} 段`;
    return '[' + key + ']';
};

const { formatPartLabel } = await import('../part-label.js');

test('formatPartLabel: length < 2 → 空字串', () => {
    assert.equal(formatPartLabel(undefined), '');
    assert.equal(formatPartLabel(null), '');
    assert.equal(formatPartLabel([]), '');
    assert.equal(formatPartLabel(['cd1']), '');
});


test('formatPartLabel: 3+ 段且前綴一致 → 首尾 + EN DASH (U+2013)', () => {
    const label = formatPartLabel(['cd1', 'cd2', 'cd3', 'cd4']);
    assert.equal(label, 'cd1–cd4');
    assert.equal(label, 'cd1\u2013cd4');
    assert.notEqual(label, 'cd1-cd4');
    assert.equal(formatPartLabel(['dvd1', 'dvd2', 'dvd3']), 'dvd1–dvd3');
});

