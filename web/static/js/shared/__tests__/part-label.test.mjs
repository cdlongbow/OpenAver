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

test('formatPartLabel: 2 段 → token 以 / 連接', () => {
    assert.equal(formatPartLabel(['cd1', 'cd2']), 'cd1/cd2');
    assert.equal(formatPartLabel(['pt1', 'pt2']), 'pt1/pt2');
});

test('formatPartLabel: 3+ 段且前綴一致 → 首尾 + EN DASH (U+2013)', () => {
    const label = formatPartLabel(['cd1', 'cd2', 'cd3', 'cd4']);
    assert.equal(label, 'cd1–cd4');
    assert.equal(label, 'cd1\u2013cd4');
    assert.notEqual(label, 'cd1-cd4');
    assert.equal(formatPartLabel(['dvd1', 'dvd2', 'dvd3']), 'dvd1–dvd3');
});

test('formatPartLabel: 前綴不一致 → i18n fallback', () => {
    const calls = [];
    const prev = window.t;
    window.t = (key, params) => {
        calls.push([key, params]);
        return `${params.n} 段`;
    };
    try {
        assert.equal(formatPartLabel(['cd1', 'pt2']), '2 段');
        assert.deepEqual(calls, [['showcase.video.part_count_fallback', { n: 2 }]]);
        assert.equal(formatPartLabel(['cd1', 'cd2', 'pt3']), '3 段');
    } finally {
        window.t = prev;
    }
});
