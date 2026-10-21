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
import { canonicalizeMakers } from '../../insights/aggregate.js';

const row = (maker, recent, total = recent) => ({ maker, total, recent });

test('merges-spellings-before-threshold: MOODYZ 3 + Moodyz 3 合計過門檻、單看都不過', () => {
    const out = rankMakerCapsules([row('MOODYZ', 3), row('Moodyz', 3)], []);
    assert.equal(out.length, 1);
    assert.equal(out[0].count, 6);
    assert.equal(out[0].key, 'moodyz');
});

test('threshold-five-kept: recent 恰 5 留、恰 4 不留；recent=0 但 total 很大不達標', () => {
    const out = rankMakerCapsules([row('A', 5), row('B', 4), row('C', 0, 9999)], []);
    assert.deepEqual(out.map((c) => c.label), ['A']);
});

test('caps-at-five: >=6 家達標 ⇒ 恰 5 顆', () => {
    const rows = ['A', 'B', 'C', 'D', 'E', 'F', 'G'].map((m, i) => row(m, 20 - i));
    assert.equal(rankMakerCapsules(rows, []).length, 5);
});

test('sorted-by-count-desc: 依 count 降冪', () => {
    const rows = [row('A', 6), row('B', 9), row('C', 7), row('D', 12), row('E', 8)];
    assert.deepEqual(rankMakerCapsules(rows, []).map((c) => c.count), [12, 9, 8, 7, 6]);
});

test('tie-at-fifth: 第 5、6 名同片數 ⇒ 依代表寫法遞增決定誰上榜', () => {
    const rows = [row('A', 20), row('B', 19), row('C', 18), row('D', 17), row('Zeta', 6), row('Alpha', 6)];
    const out = rankMakerCapsules(rows, []);
    assert.equal(out.length, 5);
    assert.equal(out[4].label, 'Alpha');
});

test('hidden-excluded-next-backfills: hiddenKeys 之後排除，原第 6 名補上', () => {
    const rows = ['A', 'B', 'C', 'D', 'E', 'F'].map((m, i) => row(m, 20 - i));
    const out = rankMakerCapsules(rows, ['b']);
    assert.deepEqual(out.map((c) => c.label), ['A', 'C', 'D', 'E', 'F']);
});

test('all-hidden-or-empty-input: 全被 hidden／null／[] ⇒ []', () => {
    assert.deepEqual(rankMakerCapsules([row('A', 9)], ['a']), []);
    assert.deepEqual(rankMakerCapsules(null, []), []);
    assert.deepEqual(rankMakerCapsules([], null), []);
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

test('cross-path-same-label: 代表寫法與分析頁 canonicalizeMakers 相同（total 加權≠recent 加權，含平手）', () => {
    // Moodyz total 3 > MOODYZ total 2，但 recent 加權會選 MOODYZ；S1／s1 total 平手、recent 加權會選 s1
    const groups = [
        { rows: [row('Moodyz', 1, 3), row('MOODYZ', 4, 2)], expect: 'Moodyz' },
        { rows: [row('S1', 3, 2), row('s1', 9, 2)], expect: 'S1' },
    ];
    for (const g of groups) {
        const records = [];
        for (const r of g.rows) for (let i = 0; i < r.total; i++) records.push({ maker: r.maker });
        canonicalizeMakers(records);
        const analysisLabel = records[0].maker;
        const out = rankMakerCapsules(g.rows, []);
        assert.equal(out.length, 1);
        assert.equal(out[0].label, analysisLabel);
        assert.equal(out[0].label, g.expect);
    }
});
