// TASK-149b-T2: enrich-gate.js 補資料條件收斂契約
// 零 import 依賴模組，不需要 importmap resolve hook / window stub。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const mod = await import('../enrich-gate.js');
const { shouldShowEnrichButton } = mod;

test('邊界條件 1：有封面有NFO，有番號與無番號皆不顯示', () => {
    assert.strictEqual(shouldShowEnrichButton({ number: 'ABC-123', has_cover: true, has_nfo: true }), false);
    assert.strictEqual(shouldShowEnrichButton({ number: null, has_cover: true, has_nfo: true }), false);
});

test('邊界條件 2：無封面無NFO，有番號顯示，無番號不顯示', () => {
    assert.strictEqual(shouldShowEnrichButton({ number: 'ABC-123', has_cover: false, has_nfo: false }), true);
    assert.strictEqual(shouldShowEnrichButton({ number: null, has_cover: false, has_nfo: false }), false);
});

test('邊界條件 3：有封面無NFO，有番號顯示，無番號不顯示', () => {
    assert.strictEqual(shouldShowEnrichButton({ number: 'ABC-123', has_cover: true, has_nfo: false }), true);
    assert.strictEqual(shouldShowEnrichButton({ number: null, has_cover: true, has_nfo: false }), false);
});

test('邊界條件 4：無封面有NFO，有番號顯示，無番號不顯示', () => {
    assert.strictEqual(shouldShowEnrichButton({ number: 'ABC-123', has_cover: false, has_nfo: true }), true);
    assert.strictEqual(shouldShowEnrichButton({ number: null, has_cover: false, has_nfo: true }), false);
});

test('邊界條件 5：video 為 null/undefined 時不顯示且不拋錯', () => {
    assert.strictEqual(shouldShowEnrichButton(null), false);
    assert.strictEqual(shouldShowEnrichButton(undefined), false);
});
