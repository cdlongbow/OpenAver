// TASK-161a-T4: showcase-handoff.js 純函式契約（buildHandoffPills / applyHandoff）。
// 期望值一律手寫字面，不拿被測函式自己的輸出當期望。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildHandoffPills, applyHandoff } from '../showcase-handoff.js';
import { serializePills } from '../pill-filter.js';

const ACT = { dim: 'actress', value: '石川澪' };
const MKR = { dim: 'maker', value: 'Moodyz' };
const YEAR = { type: 'year', year: 2023 };

const OLD = {
    sort: 'date', order: 'asc', page: 3, search: 'abc', mode: 'grid',
    showFavoriteActresses: true, actressSort: 'video_count', actressOrder: 'desc',
    actressSearch: 'x', cardShape: 'poster', infoVisible: true, foo: 1,
    pills: [{ dim: 'series', value: 'zzz' }, { dim: 'release', op: '=', value: '2001' }],
};

test('handoff: buildHandoffPills 五種組合逐鍵等於 serializePills', () => {
    assert.deepStrictEqual(buildHandoffPills({ period: { type: 'all' }, actress: '', maker: '' }), []);
    assert.deepStrictEqual(
        buildHandoffPills({ period: { type: 'all' }, actress: '石川澪', maker: '' }),
        [{ dim: 'actress', value: '石川澪' }]);
    assert.deepStrictEqual(
        buildHandoffPills({ period: { type: 'all' }, actress: '', maker: 'Moodyz' }),
        [{ dim: 'maker', value: 'Moodyz' }]);
    assert.deepStrictEqual(
        buildHandoffPills({ period: YEAR, actress: '', maker: '' }),
        [{ dim: 'release', value: '2023', op: '=' }]);
    const all = buildHandoffPills({ period: YEAR, actress: '石川澪', maker: 'Moodyz' });
    assert.deepStrictEqual(all, [
        { dim: 'actress', value: '石川澪' },
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'release', value: '2023', op: '=' },
    ]);
    assert.deepStrictEqual(all, serializePills(all));
});

test('handoff: applyHandoff 覆寫 pills/search/page/showFavoriteActresses', () => {
    const r = JSON.parse(applyHandoff(JSON.stringify(OLD), { period: YEAR, actress: '石川澪', maker: 'Moodyz' }));
    assert.equal(r.search, '');
    assert.equal(r.page, 1);
    assert.equal(r.showFavoriteActresses, false);
    assert.deepStrictEqual(r.pills, [
        { dim: 'actress', value: '石川澪' },
        { dim: 'maker', value: 'Moodyz' },
        { dim: 'release', value: '2023', op: '=' },
    ]);
});

test('handoff: applyHandoff 保留 sort/order/mode/cardShape/infoVisible/actressSort/actressOrder/actressSearch 與未知鍵', () => {
    const r = JSON.parse(applyHandoff(JSON.stringify(OLD), { period: YEAR }));
    assert.equal(r.sort, 'date');
    assert.equal(r.order, 'asc');
    assert.equal(r.mode, 'grid');
    assert.equal(r.cardShape, 'poster');
    assert.equal(r.infoVisible, true);
    assert.equal(r.actressSort, 'video_count');
    assert.equal(r.actressOrder, 'desc');
    assert.equal(r.actressSearch, 'x');
    assert.equal(r.foo, 1);
});

