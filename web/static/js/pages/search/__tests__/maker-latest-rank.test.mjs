// TASK-173-T11：片商膠囊排名純函式 rankMakerCapsules（CD-173-2／-3）
//
// 守住的行為：
//   - 大小寫／全半形不同寫法先合併再過門檻（recent >= 5），合計數才是 count
//   - 取前 5、count 降冪、平手依代表寫法遞增；hiddenKeys 在門檻之後排除，空位由下一名補上
//   - 代表寫法與分析頁 canonicalizeMakers 一致（以全庫 total 加權，不是 recent）
//   - spellings 帶組內全部寫法（含 recent=0 的舊寫法）

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rankMakerCapsules } from '../maker-capsules.js';

const row = (maker, recent, total = recent) => ({ maker, total, recent });

test('merges-spellings-before-threshold: MOODYZ 3 + Moodyz 3 合計過門檻、單看都不過', () => {
    const out = rankMakerCapsules([row('MOODYZ', 3), row('Moodyz', 3)], []);
    assert.equal(out.length, 1);
    assert.equal(out[0].count, 6);
    assert.equal(out[0].key, 'moodyz');
});


test('ranks-by-recent-not-total: 舊片很多但近況少的片商排在近況多者之後', () => {
    const out = rankMakerCapsules([row('Old', 5, 9000), row('New', 30, 30)], []);
    assert.deepEqual(out.map((c) => c.label), ['New', 'Old']);
    assert.deepEqual(out.map((c) => c.count), [30, 5]);
});

test('spellings-carry-all-writings: spellings 含組內全部寫法（含 recent=0），依輸入順序不重複', () => {
    const out = rankMakerCapsules([row('MOODYZ', 6, 10), row('Moodyz', 0, 50), row('MOODYZ', 1, 1)], []);
    assert.deepEqual(out[0].spellings, ['MOODYZ', 'Moodyz']);
});

