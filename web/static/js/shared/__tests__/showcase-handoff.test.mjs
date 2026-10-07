// TASK-161a-T4: showcase-handoff.js 純函式契約（buildHandoffPills / applyHandoff）。
// 期望值一律手寫字面，不拿被測函式自己的輸出當期望。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildHandoffPills, applyHandoff } from '../showcase-handoff.js';
import { serializePills, deserializePills } from '../pill-filter.js';

const ACT = { dim: 'actress', value: '石川澪' };
const MKR = { dim: 'maker', value: 'Moodyz' };
const YEAR = { type: 'year', year: 2023 };
const RANGE = { type: 'range', from: 2019, to: 2023 };

const OLD = {
    sort: 'date', order: 'asc', page: 3, search: 'abc', mode: 'grid',
    showFavoriteActresses: true, actressSort: 'video_count', actressOrder: 'desc',
    actressSearch: 'x', cardShape: 'poster', infoVisible: true, foo: 1,
    pills: [{ dim: 'series', value: 'zzz' }, { dim: 'release', op: '=', value: '2001' }],
};
const OVERRIDE_KEYS = ['page', 'pills', 'search', 'showFavoriteActresses'];

function deepProxy(o) {
    if (o === null || typeof o !== 'object') return o;
    return new Proxy(o, {
        get(t, k) { return deepProxy(Reflect.get(t, k)); },
    });
}

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

test("handoff: 單年 release pill 為 op '=' 且 value 是字串", () => {
    const p = buildHandoffPills({ period: YEAR })[0];
    assert.deepStrictEqual(p, { dim: 'release', value: '2023', op: '=' });
    assert.equal(typeof p.value, 'string');
    assert.equal('value2' in p, false);
    assert.equal(deserializePills([p]).length, 1);
});

test('handoff: range release pill 帶 op range 與 value2', () => {
    const out = buildHandoffPills({ period: RANGE });
    assert.deepStrictEqual(out, [{ dim: 'release', value: '2019', op: 'range', value2: '2023' }]);
    assert.equal(deserializePills(out).length, 1);
});

test('handoff: pills 順序為女優、片商、發行日', () => {
    const out = buildHandoffPills({ period: RANGE, actress: '石川澪', maker: 'Moodyz' });
    assert.deepStrictEqual(out.map((p) => p.dim), ['actress', 'maker', 'release']);
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

test('handoff: 舊 pills 整組被取代', () => {
    const r = JSON.parse(applyHandoff(JSON.stringify(OLD), { period: { type: 'all' }, actress: '石川澪' }));
    assert.deepStrictEqual(r.pills, [{ dim: 'actress', value: '石川澪' }]);
    assert.equal(r.pills.some((p) => p.dim === 'series' || p.dim === 'pick'), false);
});

test('handoff: 無條件時 pills 為空陣列並仍清舊條件', () => {
    for (const sel of [null, undefined, {}, { period: { type: 'all' } }]) {
        const r = JSON.parse(applyHandoff(JSON.stringify(OLD), sel));
        assert.deepStrictEqual(r.pills, []);
        assert.equal(r.search, '');
        assert.equal(r.page, 1);
        assert.equal(r.showFavoriteActresses, false);
    }
});

test('handoff: 壞 JSON 與空字串以 {} 起算不拋', () => {
    const sel = { period: YEAR };
    for (const raw of [null, undefined, '', 'not json']) {
        const r = JSON.parse(applyHandoff(raw, sel));
        assert.deepStrictEqual(Object.keys(r).sort(), OVERRIDE_KEYS);
    }
    assert.equal(applyHandoff(null, sel), applyHandoff('', sel));
});

test('handoff: 非物件 JSON（陣列／字串／null／數字）以 {} 起算', () => {
    for (const raw of ['[1,2]', '"abc"', 'null', '3']) {
        const r = JSON.parse(applyHandoff(raw, { period: YEAR }));
        assert.deepStrictEqual(Object.keys(r).sort(), OVERRIDE_KEYS, raw);
    }
});

test('handoff: 產物經 deserializePills 往返無損', () => {
    const sels = [
        { period: YEAR, actress: '石川澪', maker: 'Moodyz' },
        { period: RANGE, actress: '石川澪', maker: 'Moodyz' },
        { period: { type: 'all' } },
    ];
    for (const sel of sels) {
        const built = buildHandoffPills(sel);
        const back = deserializePills(JSON.parse(applyHandoff('{}', sel)).pills);
        assert.equal(back.length, built.length);
        assert.deepStrictEqual(back, built);
    }
});

test('handoff: 不 mutate 輸入 sel 且 Proxy 包的 sel 結果相同', () => {
    const sel = { period: { type: 'range', from: 2019, to: 2023 }, actress: '石川澪', maker: 'Moodyz' };
    const frozen = Object.freeze({ ...sel, period: Object.freeze({ ...sel.period }) });
    const snapshot = JSON.stringify(frozen);
    const a = applyHandoff(JSON.stringify(OLD), frozen);
    assert.equal(JSON.stringify(frozen), snapshot);
    const b = applyHandoff(JSON.stringify(OLD), deepProxy(sel));
    assert.equal(a, b);
    assert.deepStrictEqual(buildHandoffPills(deepProxy(sel)), buildHandoffPills(sel));
});
