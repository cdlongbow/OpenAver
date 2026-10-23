// TASK-173-T7: maker-merge.js 共用核心（片商寫法分組 + 代表寫法）契約
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const { makerKey, canonicalMakerLabels } = await import('../maker-merge.js');

test('fullwidth / 大小寫 / 前後空白 的寫法併成同一組，代表為次數最多者', () => {
    var labels = canonicalMakerLabels(new Map([
        ['MOODYZ', 5], ['Moodyz', 2], ['ＭＯＯＤＹＺ', 1], [' moodyz ', 1],
    ]));
    assert.strictEqual(labels.get('MOODYZ'), 'MOODYZ');
    assert.strictEqual(labels.get('Moodyz'), 'MOODYZ');
    assert.strictEqual(labels.get('ＭＯＯＤＹＺ'), 'MOODYZ');
    assert.strictEqual(labels.get(' moodyz '), 'MOODYZ');
    assert.strictEqual(makerKey('ＭＯＯＤＹＺ'), makerKey('moodyz'));
});


// 175a-T6: Python maker_key_of 與前端 makerKey 共用向量檔（BE-TEST-14；pytest 另讀一次同一檔）
const keyVectors = JSON.parse(readFileSync(
    new URL('../../../../../tests/data/maker_key_vectors.json', import.meta.url), 'utf8')).vectors;

test('makerKey 符合共用向量檔（與 Python maker_key_of 同表）', () => {
    assert.ok(keyVectors.length > 0);
    for (const v of keyVectors) {
        assert.strictEqual(makerKey(v.input), v.key, JSON.stringify(v.input));
    }
});
