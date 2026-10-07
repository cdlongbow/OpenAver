// 片庫分析聚合函式契約：setRecords／canonicalizeMakers／buildMainMakerYearMap／periodRecords／
// scopeRecords／aggregateYears／圓餅／女優榜／標籤／年齡／年表／分布表／與她同片。
// 純函式、零 window / Alpine。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const agg = await import('../aggregate.js');
const { scopeRecords } = await import('../selection.js');
const {
    setRecords,
    getRecords,
    canonicalizeMakers,
    buildMainMakerYearMap,
} = agg;
const {
    periodRecords,
    aggregateYears,
    UNKNOWN_KEY,
    ACTRESS_TOP_N,
    buildMakerDonutData,
    classifyRecordAgainstMainMaker,
    buildActressBoard,
    aggregateTags,
    aggregateAge,
    aggregateFieldTop8,
    buildGanttRows,
    buildGanttYearCells,
    buildSoloRows,
    buildCostarRows,
} = agg;

function rec(opts) {
    return {
        year: opts.year === undefined ? 2020 : opts.year,
        month: opts.month === undefined ? null : opts.month,
        actresses: opts.actresses === undefined ? ['Alice'] : opts.actresses,
        maker: opts.maker === undefined ? 'SOD' : opts.maker,
        tags: opts.tags === undefined ? [] : opts.tags,
        date: opts.date === undefined ? null : opts.date,
        duration: opts.duration === undefined ? null : opts.duration,
    };
}

// 測試用手組 sel。
function selOf(period, focus) {
    return {
        period: period || { type: 'all' },
        actress: focus && focus.type === 'actress' ? focus.value : null,
        maker: focus && focus.type === 'maker' ? focus.value : null,
    };
}

function favs(map) {
    return map;
}

test('canonicalizeMakers: MOODYZ／Moodyz／ＭＯＯＤＹＺ／前後空白合成一家', () => {
    const records = [
        rec({ maker: 'Moodyz' }),
        rec({ maker: 'Moodyz' }),
        rec({ maker: 'MOODYZ' }),
        rec({ maker: 'ＭＯＯＤＹＺ' }),
        rec({ maker: ' moodyz ' }),
    ];
    canonicalizeMakers(records);
    assert.equal(records[0].maker, 'Moodyz');
    assert.equal(records[1].maker, 'Moodyz');
    assert.equal(records[2].maker, 'Moodyz');
    assert.equal(records[3].maker, 'Moodyz');
    assert.equal(records[4].maker, 'Moodyz');
});

test('canonicalizeMakers: null、空字串與全空白不分組、不被改寫', () => {
    const records = [
        rec({ maker: null }),
        rec({ maker: '' }),
        rec({ maker: '   ' }),
        rec({ maker: '\t' }),
    ];
    canonicalizeMakers(records);
    assert.equal(records[0].maker, null);
    assert.equal(records[1].maker, '');
    assert.equal(records[2].maker, '   ');
    assert.equal(records[3].maker, '\t');
});

test('setRecords: 進場一次合併片商，getRecords 讀到合併後的值', () => {
    try {
        setRecords([
            rec({ maker: 'MOODYZ' }),
            rec({ maker: 'Moodyz' }),
            rec({ maker: 'Moodyz' }),
        ]);
        const got = getRecords();
        assert.equal(got.length, 3);
        assert.equal(got[0].maker, 'Moodyz');
        assert.equal(got[1].maker, 'Moodyz');
        assert.equal(got[2].maker, 'Moodyz');
    } finally {
        setRecords([]);
    }
});

test('setRecords: 連續兩次設定不殘留上一批的合併結果（module singleton）', () => {
    try {
        setRecords([
            rec({ maker: 'Moodyz' }),
            rec({ maker: 'MOODYZ' }),
        ]);
        setRecords([
            rec({ maker: 'S1' }),
            rec({ maker: 's1' }),
            rec({ maker: 'S1' }),
        ]);
        const got = getRecords();
        assert.equal(got.length, 3);
        assert.equal(got[0].maker, 'S1');
        assert.equal(got[1].maker, 'S1');
        assert.equal(got[2].maker, 'S1');
    } finally {
        setRecords([]);
    }
});

// ── buildMainMakerYearMap ────────────────────────────────────────────

test('buildMainMakerYearMap: 5 部中 4 部同片商（4/5=80%）應計入主要片商年', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map['Alice|2020'], 'SOD');
});

test('buildMainMakerYearMap: 跨多家片商時回傳計數最高者（最高者非陣列首現）', () => {
    // Alpha 先出現 1 部；Gamma 後出現但累積到 5 部。total=6、5/6≈83% 命中，
    // 且比值刻意避開剛好 80% 邊界（留給上一條 mutation 鎖專用）。
    const records = [
        rec({ year: 2022, actresses: ['Carol'], maker: 'Alpha' }),
        rec({ year: 2022, actresses: ['Carol'], maker: 'Gamma' }),
        rec({ year: 2022, actresses: ['Carol'], maker: 'Gamma' }),
        rec({ year: 2022, actresses: ['Carol'], maker: 'Gamma' }),
        rec({ year: 2022, actresses: ['Carol'], maker: 'Gamma' }),
        rec({ year: 2022, actresses: ['Carol'], maker: 'Gamma' }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map['Carol|2022'], 'Gamma');
});

test('buildMainMakerYearMap: maker null 計入分母但不能當主要片商（6 部 3A+3未知不命中）', () => {
    // 兩位女優同 fixture：Dana 6 部（3 A＋3 未知）、DanaNull 5 部全未知（達門檻）
    const records = [
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
    ];
    const map = buildMainMakerYearMap(records);
    // 若誤把 null 從分母排除 → Dana total=3、100% 會誤判命中
    assert.equal(map.hasOwnProperty('Dana|2023'), false);
    // 若拿掉 null 候選排除，DanaNull 的 null 桶 5/5=100% 會誤寫入 key
    assert.equal(map.hasOwnProperty('DanaNull|2023'), false);
});

test('periodRecords: type=all 保留 year===null；type=year 排除 null 與非該年', () => {
    const nullRec = rec({ year: null, actresses: ['Alice'], maker: 'SOD' });
    const y2020 = rec({ year: 2020, actresses: ['Bob'], maker: 'Moodyz' });
    const y2021 = rec({ year: 2021, actresses: ['Carol'], maker: 'SOD' });
    const records = [nullRec, y2020, y2021];

    const all = periodRecords(records, { type: 'all' });
    assert.equal(all.length, 3);
    assert.ok(all.includes(nullRec));

    const only2020 = periodRecords(records, { type: 'year', year: 2020 });
    assert.deepStrictEqual(only2020, [y2020]);
    assert.equal(only2020.includes(nullRec), false);
    assert.equal(only2020.includes(y2021), false);
});

test('scopeRecords: actress 焦點含多人片任一人命中；maker 焦點嚴格比對', () => {
    const multi = rec({ year: 2020, actresses: ['Alice', 'Bob'], maker: 'SOD' });
    const onlyBob = rec({ year: 2021, actresses: ['Bob'], maker: 'Moodyz' });
    const onlyAlice = rec({ year: 2022, actresses: ['Alice'], maker: 'IdeaPocket' });
    const records = [multi, onlyBob, onlyAlice];

    const byActress = scopeRecords(records, selOf({ type: 'all' }, { type: 'actress', value: 'Alice' }), null);
    assert.deepStrictEqual(byActress, [multi, onlyAlice]);

    const byMaker = scopeRecords(records, selOf({ type: 'all' }, { type: 'maker', value: 'SOD' }), null);
    assert.deepStrictEqual(byMaker, [multi]);
});

test('aggregateYears: 片商焦點 categories/series 正值斷言（含空年與 UNKNOWN）', () => {
    // M：2020×2、2022×1、year=null×1；2021 無片（空位）；混入其他片商不得影響
    const M = 'M';
    const records = [
        rec({ year: 2020, actresses: ['A1'], maker: M }),
        rec({ year: 2020, actresses: ['A2'], maker: M }),
        rec({ year: 2022, actresses: ['A3'], maker: M }),
        rec({ year: null, actresses: ['A4'], maker: M }),
        rec({ year: 2021, actresses: ['B1'], maker: 'Other' }),
        rec({ year: 2020, actresses: ['B2'], maker: 'Other' }),
        rec({ year: null, actresses: ['B3'], maker: 'Other' }),
    ];
    const result = aggregateYears(
        records, selOf({ type: 'all' }, { type: 'maker', value: M }),
    );
    assert.deepStrictEqual(result.categories, ['2020', '2021', '2022', UNKNOWN_KEY]);
    assert.equal(result.series.length, 1);
    assert.equal(result.series[0].name, 'M');
    assert.deepStrictEqual(result.series[0].data, [2, 0, 1, 1]);
    assert.deepStrictEqual(result.dimmed, [false, false, false, false]);
});

test('aggregateYears: 女優焦點 series 依 maker 分桶排序；year===null 進對應 maker 的 UNKNOWN 年', () => {
    // Moodyz×2、SOD×2（同分名稱遞增 SOD < Moodyz？ 'Moodyz' < 'SOD' 字串序）
    // 計數：SOD 3（含 1 筆 year null）、Moodyz 2 → SOD 先
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: null, actresses: ['Alice'], maker: 'SOD' }),
        // 另一女優不進 base
        rec({ year: 2020, actresses: ['Bob'], maker: 'IdeaPocket' }),
    ];
    const result = aggregateYears(
        records, selOf({ type: 'all' }, { type: 'actress', value: 'Alice' }),
    );
    assert.deepStrictEqual(result.categories, ['2020', '2021', UNKNOWN_KEY]);
    assert.equal(result.series.length, 2);
    assert.equal(result.series[0].name, 'SOD');
    assert.deepStrictEqual(result.series[0].data, [0, 2, 1]);
    assert.equal(result.series[1].name, 'Moodyz');
    assert.deepStrictEqual(result.series[1].data, [2, 0, 0]);
    // 不得另開獨立 UNKNOWN series
    assert.equal(result.series.some((s) => s.name === UNKNOWN_KEY), false);
});

test('buildMakerDonutData: inner 三部分 value 總和恆等於 total（REST/UNKNOWN 為 0 仍各佔一筆）', () => {
    const records = [
        rec({ maker: 'SOD', year: 2020 }),
        rec({ maker: 'Moodyz', year: 2021 }),
    ];
    const result = buildMakerDonutData(records, {});
    assert.equal(result.total, 2);
    assert.equal(result.inner.length, 4); // 2 named + rest + unknown
    const rest = result.inner.find((e) => e.kind === 'rest');
    const unknown = result.inner.find((e) => e.kind === 'unknown');
    assert.ok(rest);
    assert.ok(unknown);
    assert.equal(rest.value, 0);
    assert.equal(unknown.value, 0);
    const sum = result.inner.reduce((s, e) => s + e.value, 0);
    assert.equal(sum, result.total);
});

test('classifyRecordAgainstMainMaker: 多人片任一人命中即為 main', () => {
    const map = { 'Alice|2020': 'SOD' };
    const got = classifyRecordAgainstMainMaker(
        rec({ maker: 'SOD', year: 2020, actresses: ['Bob', 'Alice', 'Carol'] }),
        map,
    );
    assert.equal(got, 'main');
});

test('classifyRecordAgainstMainMaker: 主要片商年命中時分類為 main（主要片商作品），不誤判為 other', () => {
    const map = { 'Alice|2020': 'SOD' };
    assert.equal(
        classifyRecordAgainstMainMaker(
            rec({ maker: 'SOD', year: 2020, actresses: ['Alice'] }),
            map,
        ),
        'main',
    );
    assert.equal(
        classifyRecordAgainstMainMaker(
            rec({ maker: 'SOD', year: 2021, actresses: ['Alice'] }),
            map,
        ),
        'other',
    );
});

// ── buildActressBoard (TASK-156b-T5) ─────────────────────────────────

test('buildActressBoard: 排序＝count 遞減 → monthCount 遞減 → name 遞增', () => {
    const records = [
        rec({ actresses: ['Carol'], month: '2020-01' }),
        rec({ actresses: ['Alice'], month: '2020-01' }),
        rec({ actresses: ['Alice'], month: '2020-02' }),
        rec({ actresses: ['Bob'], month: '2020-01' }),
        rec({ actresses: ['Bob'], month: '2020-02' }),
        rec({ actresses: ['Bob'], month: '2020-03' }),
    ];
    // Alice:2/2, Bob:3/3, Carol:1/1 → Bob, Alice, Carol
    const { rows } = buildActressBoard(records, selOf(undefined, null));
    assert.deepEqual(rows.map((r) => r.name), ['Bob', 'Alice', 'Carol']);
    assert.deepEqual(rows.map((r) => r.rank), [1, 2, 3]);
});

test('buildActressBoard: 女優排名剛好第 25 名時不附加額外列', () => {
    const records = [];
    // 26 人：A01..A26 各 26..1 片，全部同月 → A25 剛好 rank 25
    for (let i = 1; i <= 26; i++) {
        const name = 'A' + String(i).padStart(2, '0');
        const count = 27 - i; // A01=26 ... A25=2, A26=1
        for (let n = 0; n < count; n++) {
            records.push(rec({ actresses: [name], month: '2020-01' }));
        }
    }
    const focus = { type: 'actress', value: 'A25' };
    const { rows } = buildActressBoard(records, selOf(undefined, focus));
    assert.equal(rows.length, 25);
    assert.equal(rows[24].name, 'A25');
    assert.equal(rows[24].rank, 25);
    assert.equal(rows.filter((r) => r.name === 'A25').length, 1);
});

test('buildActressBoard: focus 女優 rank>25 時附加真實排名列', () => {
    const records = [];
    for (let i = 1; i <= 26; i++) {
        const name = 'A' + String(i).padStart(2, '0');
        const count = 27 - i;
        for (let n = 0; n < count; n++) {
            records.push(rec({ actresses: [name], month: '2020-01' }));
        }
    }
    // A26 片數最少 → rank 26
    const focus = { type: 'actress', value: 'A26' };
    const { rows } = buildActressBoard(records, selOf(undefined, focus));
    assert.equal(rows.length, 26);
    assert.equal(rows[25].name, 'A26');
    assert.equal(rows[25].rank, 26);
    assert.ok(rows.length <= ACTRESS_TOP_N + 1);
});

test('buildActressBoard: 多人片每位女優各計一次；maker 焦點不附加列', () => {
    const records = [
        rec({ actresses: ['Alice', 'Bob'], month: '2020-01' }),
    ];
    const { rows } = buildActressBoard(records, selOf(undefined, { type: 'maker', value: 'SOD' }));
    assert.equal(rows.length, 2);
    assert.equal(rows[0].count, 1);
    assert.equal(rows[1].count, 1);
});

test('aggregateTags: 同片重複標籤字面只算一次', () => {
    const records = [
        rec({ tags: ['A', 'A', 'A'] }),
        rec({ tags: ['B'] }),
    ];
    const result = aggregateTags(records);
    // A 只算 1 次（1/2 = 50%，不進 pulled）；B 也是 1/2
    const aEntry = result.rest.find((e) => e[0] === 'A');
    assert.ok(aEntry);
    assert.equal(aEntry[1], 1);
});

test('aggregateTags: withTagCount 與 coverage 正確；標籤字面原樣保留', () => {
    const records = [
        rec({ tags: ['字幕'] }),
        rec({ tags: ['中字'] }),
        rec({ tags: [] }),
        rec({ tags: ['字幕', '中字'] }),
    ];
    const result = aggregateTags(records);
    assert.equal(result.total, 4);
    assert.equal(result.withTagCount, 3);
    assert.equal(result.coverage, 0.75);
    // 前端不做合併：兩個字面各自一筆
    const names = result.rest.map((e) => e[0]).sort();
    assert.deepEqual(names, ['中字', '字幕']);
});

// ── aggregateAge（TASK-156c-T1）─────────────────────────────────────

test('aggregateAge: duration=239 的片不計年齡，仍計入分母', () => {
    const records = [
        rec({
            actresses: ['Alice'],
            date: '2020-06-01',
            duration: 239,
        }),
    ];
    const favorites = favs({ Alice: { birth: '1998-01-01' } });
    const result = aggregateAge(records, favorites, selOf(undefined, null));
    assert.equal(result.total, 1);
    assert.equal(result.recordsWithAge, 0);
    assert.equal(result.pairCount, 0);
    assert.equal(result.coverage, 0);
    assert.equal(result.median, null);
});

test('aggregateAge: 以 records[].actresses 的 primary 名直接查 favorites', () => {
    // favorites 以 primary 名為 key；actresses 陣列已是 primary（後端覆蓋別名）
    const records = [
        rec({
            actresses: ['Alice'],
            date: '2020-01-01',
            duration: 120,
        }),
    ];
    const favorites = favs({ Alice: { birth: '1998-01-01' } });
    const result = aggregateAge(records, favorites, selOf(undefined, null));
    assert.equal(result.pairCount, 1);
    assert.equal(result.recordsWithAge, 1);
    assert.equal(result.median, 22);
    assert.equal(result.histogram[22], 1);
});

test('aggregateAge: 同片兩位收藏女優都算出年齡時涵蓋率分子只計一次', () => {
    // 片 1：兩位收藏女優都算出年齡 → pairCount+=2、recordsWithAge 只 +1
    // 片 2：無生日 → 不得進分子（鎖 if (recordHasAge) 守衛；拿掉 if 會讓本測試轉紅）
    const records = [
        rec({
            actresses: ['Alice', 'Bob'],
            date: '2020-06-01',
            duration: 120,
        }),
        rec({
            actresses: ['Carol'],
            date: '2020-06-01',
            duration: 120,
        }),
    ];
    const favorites = favs({
        Alice: { birth: '1998-01-01' },
        Bob: { birth: '1995-01-01' },
        // Carol 刻意不在 favorites → 無有效年齡
    });
    const result = aggregateAge(records, favorites, selOf(undefined, null));
    assert.equal(result.total, 2);
    assert.equal(result.pairCount, 2);
    assert.equal(result.recordsWithAge, 1);
    assert.equal(result.coverage, 0.5);
});

test('aggregateAge: date="2021-02-31"（日曆不合法）回 null，不計年齡但計入分母', () => {
    // 表驅動：日曆不合法、只有年／年月（無完整 date）——都不計年齡但仍計入分母
    const cases = [
        { name: '2021-02-31', rec: { actresses: ['Alice'], date: '2021-02-31', duration: 120 } },
        { name: '只有年月', rec: { actresses: ['Alice'], year: 2020, month: '2020-06', date: null, duration: 120 } },
    ];
    for (const c of cases) {
        const favorites = favs({ Alice: { birth: '1998-01-01' } });
        const result = aggregateAge([rec(c.rec)], favorites, selOf(undefined, null));
        assert.equal(result.total, 1, c.name);
        assert.equal(result.recordsWithAge, 0, c.name);
        assert.equal(result.pairCount, 0, c.name);
        assert.equal(result.coverage, 0, c.name);
        assert.equal(result.median, null, c.name);
    }
});

test('aggregateAge: 女優焦點時只算她本人；同片其他收藏女優（共演者）不進 histogram／pairCount', () => {
    const records = [
        rec({
            actresses: ['Alice', 'Bob'],
            date: '2020-06-01',
            duration: 120,
        }),
    ];
    const favorites = favs({
        Alice: { birth: '1998-01-01' }, // age 22 on 2020-06-01
        Bob: { birth: '1995-01-01' },   // age 25 — 共演者，焦點 Alice 時不得計入
    });
    const result = aggregateAge(
        records,
        favorites, selOf(undefined, { type: 'actress', value: 'Alice' }),
    );
    assert.equal(result.pairCount, 1);
    assert.equal(result.recordsWithAge, 1);
    assert.equal(result.median, 22);
    assert.equal(result.histogram[22], 1);
    assert.equal(result.histogram[25], undefined);
});

// ── aggregateFieldTop8 ───────────────────────────────────────────────

test('aggregateFieldTop8: 空字串不進排名但仍計入 total', () => {
    const records = [
        { director: '' },
        { director: null },
        { director: '庵野秀明' },
    ];
    const res = aggregateFieldTop8(records, 'director');
    assert.equal(res.total, 3);
    assert.equal(res.withValueCount, 1);
    assert.equal(res.coverage, 1 / 3);
    assert.deepEqual(res.top, [['庵野秀明', 1]]);
});

// ── buildGanttRows / ganttYearAxis / buildGanttYearCells ─────────────
// ── ganttAgeEligibility / ganttAgeAxis / buildGanttAgeCells ──────────

test('buildGanttRows: 選了年份＋片商焦點時只列同一組(y,mk)交集，不得OR判斷', () => {
    // A|2023→S1、A|2020→Moodyz；選 2023＋Moodyz 時同一組 entry 不符 → 不出現
    const map = {
        'Alice|2023': 'S1',
        'Alice|2020': 'Moodyz',
    };
    const records = [
        rec({ year: 2023, actresses: ['Alice'], maker: 'S1' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'Moodyz' }),
    ];
    const none = buildGanttRows(
        records,
        map, selOf({ type: 'year', year: 2023 }, { type: 'maker', value: 'Moodyz' }),
    );
    assert.equal(none.some((r) => r.name === 'Alice'), false);

    // period=all／period=2023 無 focus／focus=Moodyz 無 period／period=2023+focus=S1 → 都出現
    assert.equal(
        buildGanttRows(records, map, selOf({ type: 'all' }, null)).some((r) => r.name === 'Alice'),
        true,
    );
    assert.equal(
        buildGanttRows(records, map, selOf({ type: 'year', year: 2023 }, null)).some(
            (r) => r.name === 'Alice',
        ),
        true,
    );
    assert.equal(
        buildGanttRows(records, map, selOf({ type: 'all' }, { type: 'maker', value: 'Moodyz' })).some(
            (r) => r.name === 'Alice',
        ),
        true,
    );
    assert.equal(
        buildGanttRows(
            records,
            map, selOf({ type: 'year', year: 2023 }, { type: 'maker', value: 'S1' }),
        ).some((r) => r.name === 'Alice'),
        true,
    );
});

test('buildGanttRows: 女優焦點且她不在前25名時附加她那一列', () => {
    const map = {};
    const records = [];
    // 25 位候選人各有一個主要片商年；Zoe 不在其中但有片
    for (let i = 1; i <= 25; i++) {
        const name = `Act${String(i).padStart(2, '0')}`;
        map[`${name}|2020`] = 'SOD';
        records.push(rec({ year: 2020, actresses: [name], maker: 'SOD' }));
    }
    records.push(rec({ year: 2021, actresses: ['Zoe'], maker: 'Moodyz' }));

    const withAppend = buildGanttRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Zoe' }),
    );
    assert.equal(withAppend.length, 26);
    const first = withAppend[0];
    assert.equal(first.name, 'Zoe');
    assert.equal(first.appended, true);
    assert.equal(first.pinned, true);

    // 已在前 25 → 不重複附加
    const already = buildGanttRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Act01' }),
    );
    assert.equal(already.filter((r) => r.name === 'Act01').length, 1);
    assert.equal(already.some((r) => r.appended), false);

    // records 裡完全沒有她的片 → 不附加
    const missing = buildGanttRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Ghost' }),
    );
    assert.equal(missing.some((r) => r.name === 'Ghost'), false);
});

test('buildGanttRows: 女優焦點且她 rank 外附加時，附加列直接置頂在 index 0（不是末列）', () => {
    const map = {};
    const records = [];
    for (let i = 1; i <= 25; i++) {
        const name = `Act${String(i).padStart(2, '0')}`;
        map[`${name}|2020`] = 'SOD';
        records.push(rec({ year: 2020, actresses: [name], maker: 'SOD' }));
    }
    records.push(rec({ year: 2021, actresses: ['Zoe'], maker: 'Moodyz' }));

    const pinned = buildGanttRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Zoe' }),
    );
    assert.equal(pinned.length, 26);
    assert.equal(pinned[0].name, 'Zoe');
    assert.equal(pinned[0].pinned, true);
    assert.equal(pinned[0].appended, true);
    assert.deepEqual(
        pinned.slice(1).map((r) => r.name),
        Array.from({ length: 25 }, (_, i) => `Act${String(i + 1).padStart(2, '0')}`),
    );
});

test('buildGanttYearCells: 主要片商年→main、有片非主要→dot、無片→empty', () => {
    const map = { 'Alice|2020': 'SOD' };
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' }),
    ];
    const cells = buildGanttYearCells('Alice', records, map, [2020, 2021, 2022]);
    assert.equal(cells.length, 3);
    assert.equal(cells[0].state, 'main');
    assert.equal(cells[0].maker, 'SOD');
    assert.equal(cells[0].filmCount, 2);
    assert.equal(cells[0].makerCount, 2);
    assert.equal(cells[1].state, 'dot');
    assert.equal(cells[1].filmCount, 1);
    assert.equal(cells[2].state, 'empty');
    assert.equal(cells[2].filmCount, 0);
});

// ── buildSoloRows（TASK-156c-T4） ─────────────────────────────────────

test('buildSoloRows: 先篩再取 25——原始片數前3名因主要片商佔比過半被篩掉，結果從第4名起仍取滿25位', () => {
    const map = {};
    const records = [];
    // 片數前 3 名：每人 6 部，其中 4 部是主要片商作品（ratio 0.667）→ 被篩掉
    ['Top1', 'Top2', 'Top3'].forEach((name) => {
        map[`${name}|2020`] = 'M';
        for (let i = 0; i < 4; i++) {
            records.push(rec({ year: 2020, actresses: [name], maker: 'M' }));
        }
        for (let i = 0; i < 2; i++) {
            records.push(rec({ year: 2020, actresses: [name], maker: 'Other' }));
        }
    });
    // 剩下 25 位候選人：各 1 部、無主要片商作品（ratio 0）
    const restNames = [];
    for (let i = 1; i <= 25; i++) {
        const name = `Rest${String(i).padStart(2, '0')}`;
        restNames.push(name);
        records.push(rec({ year: 2020, actresses: [name], maker: 'Other' }));
    }
    const rows = buildSoloRows(records, map, selOf({ type: 'all' }, null), [], []);
    assert.equal(rows.length, 25);
    assert.equal(rows.some((r) => r.name.startsWith('Top')), false);
    assert.deepEqual(
        rows.map((r) => r.name).sort(),
        restNames.sort(),
    );
});

test('buildSoloRows: 片商焦點時候選池限定在該片商有片的人，但 total/segments 用期間全貌', () => {
    const map = {};
    const records = [];
    // 她在片商 Y 只有 1 部，其餘 9 部散在其他具名片商（共 10 部，ratio 0）
    records.push(rec({ year: 2020, actresses: ['Solo'], maker: 'Y' }));
    ['B', 'C', 'D', 'E', 'F', 'G', 'H'].forEach((mk) => {
        records.push(rec({ year: 2020, actresses: ['Solo'], maker: mk }));
    });
    records.push(rec({ year: 2020, actresses: ['Solo'], maker: 'A' }));
    records.push(rec({ year: 2020, actresses: ['Solo'], maker: 'A' }));
    // 干擾：另一位女優只在片商 Z 有片，片商焦點是 Y 時不該出現
    records.push(rec({ year: 2020, actresses: ['Other'], maker: 'Z' }));

    const rows = buildSoloRows(
        records,
        map, selOf({ type: 'all' }, { type: 'maker', value: 'Y' }),
        [],
        ['Y', 'A'],
    );
    assert.equal(rows.some((r) => r.name === 'Other'), false);
    const solo = rows.find((r) => r.name === 'Solo');
    assert.ok(solo, 'Solo 應該上榜');
    assert.equal(solo.total, 10);
    assert.ok(solo.segments.length >= 2);
});

test('buildSoloRows: 主要片商佔比恰好 50% 不列，49%（如 24/49）列入', () => {
    const map = {};
    const records = [];
    // Half：10 部，5 部主要（ratio 0.5）→ 排除
    map['Half|2020'] = 'M';
    for (let i = 0; i < 5; i++) {
        records.push(rec({ year: 2020, actresses: ['Half'], maker: 'M' }));
    }
    for (let i = 0; i < 5; i++) {
        records.push(rec({ year: 2020, actresses: ['Half'], maker: 'Other' }));
    }
    // Under：49 部，24 部主要（ratio≈0.4898）→ 列入
    map['Under|2020'] = 'N';
    for (let i = 0; i < 24; i++) {
        records.push(rec({ year: 2020, actresses: ['Under'], maker: 'N' }));
    }
    for (let i = 0; i < 25; i++) {
        records.push(rec({ year: 2020, actresses: ['Under'], maker: 'Other' }));
    }
    const rows = buildSoloRows(records, map, selOf({ type: 'all' }, null), [], []);
    assert.equal(rows.some((r) => r.name === 'Half'), false);
    const under = rows.find((r) => r.name === 'Under');
    assert.ok(under, 'Under 應該上榜');
    assert.equal(under.total, 49);
    assert.equal(under.mainCount, 24);
});

test('buildSoloRows: 女優焦點且她不符合篩選條件但有紀錄 → 附加末列；已在前25不重複；無紀錄不附加', () => {
    const map = {};
    const records = [];
    // 25 位候選人各 1 部，皆符合條件
    const names = [];
    for (let i = 1; i <= 25; i++) {
        const name = `Cand${String(i).padStart(2, '0')}`;
        names.push(name);
        records.push(rec({ year: 2020, actresses: [name], maker: 'Other' }));
    }
    // ExcludedByRatio：主要片商佔比過半，本來不會上榜
    map['ExcludedByRatio|2020'] = 'M';
    for (let i = 0; i < 4; i++) {
        records.push(rec({ year: 2020, actresses: ['ExcludedByRatio'], maker: 'M' }));
    }
    records.push(rec({ year: 2020, actresses: ['ExcludedByRatio'], maker: 'Other' }));

    const withAppend = buildSoloRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'ExcludedByRatio' }),
        [],
        [],
    );
    assert.equal(withAppend.length, 26);
    const first = withAppend[0];
    assert.equal(first.name, 'ExcludedByRatio');
    assert.equal(first.appended, true);
    assert.equal(first.pinned, true);
    assert.equal(first.total, 5);

    // 已在前 25 → 不重複附加
    const already = buildSoloRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Cand01' }),
        [],
        [],
    );
    assert.equal(already.filter((r) => r.name === 'Cand01').length, 1);
    assert.equal(already.some((r) => r.appended), false);

    // periodRecords 裡完全沒有她的紀錄 → 不附加
    const missing = buildSoloRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'Ghost' }),
        [],
        [],
    );
    assert.equal(missing.some((r) => r.name === 'Ghost'), false);
});

test('buildSoloRows: 女優焦點且她 rank 外附加時，附加列直接置頂在 index 0（不是末列）', () => {
    const map = {};
    const records = [];
    const names = [];
    for (let i = 1; i <= 25; i++) {
        const name = `Cand${String(i).padStart(2, '0')}`;
        names.push(name);
        records.push(rec({ year: 2020, actresses: [name], maker: 'Other' }));
    }
    map['ExcludedByRatio|2020'] = 'M';
    for (let i = 0; i < 4; i++) {
        records.push(rec({ year: 2020, actresses: ['ExcludedByRatio'], maker: 'M' }));
    }
    records.push(rec({ year: 2020, actresses: ['ExcludedByRatio'], maker: 'Other' }));

    const pinned = buildSoloRows(
        records,
        map, selOf({ type: 'all' }, { type: 'actress', value: 'ExcludedByRatio' }),
        [],
        [],
    );
    assert.equal(pinned.length, 26);
    assert.equal(pinned[0].name, 'ExcludedByRatio');
    assert.equal(pinned[0].pinned, true);
    assert.equal(pinned[0].appended, true);
    assert.deepEqual(pinned.slice(1).map((r) => r.name), names);
});

test('buildCostarRows: 2～4人的片正常計入所有非焦點搭檔', () => {
    const sel = selOf({ type: 'all' }, { type: 'actress', value: 'Alice' });
    const records = [
        rec({ actresses: ['Alice', 'Bob'] }), // 2 人片
        rec({ actresses: ['Alice', 'Bob', 'Carol'] }), // 3 人片
        rec({ actresses: ['Alice', 'Carol', 'Dave', 'Eve'] }), // 4 人片
        rec({ actresses: ['Alice', 'Bob', 'Carol', 'Dave', 'Eve'] }), // 5 人片：不計入
        rec({ actresses: ['Alice', 'Bob', 'Carol', 'Dave', 'Eve', 'Frank'] }), // 6 人片：不計入
        rec({ actresses: ['Alice'] }), // 1 人片：不計入
    ];
    assert.deepEqual(buildCostarRows(records, sel), [
        { name: 'Bob', count: 2 },
        { name: 'Carol', count: 2 },
        { name: 'Dave', count: 1 },
        { name: 'Eve', count: 1 },
    ]);
    // 只有 5 人以上、只有 1 人的片 → 空
    assert.deepEqual(buildCostarRows(records.slice(3, 5), sel), []);
    assert.deepEqual(buildCostarRows(records.slice(5), sel), []);
});

test('buildCostarRows: 同片重複名字去重後只算一次人數與合作', () => {
    const records = [
        rec({ actresses: ['Alice', 'Alice', 'Bob'] }),
        rec({ actresses: ['Alice', 'Bob', 'Carol', 'Dave', 'Alice', 'Bob'] }),
    ];
    const got = buildCostarRows(records, selOf({ type: 'all' }, { type: 'actress', value: 'Alice' }));
    assert.deepEqual(got, [
        { name: 'Bob', count: 2 },
        { name: 'Carol', count: 1 },
        { name: 'Dave', count: 1 },
    ]);
});

// ── TASK-161a-T2b／T5a：sel／skipDim 簽名 ───────────────────

function many(n, opts) {
    const out = [];
    for (let i = 0; i < n; i++) out.push(rec(opts));
    return out;
}

// Alice：2023 是 S1 主要片商年（4 部全 S1）、2020 是 Moodyz 主要片商年（4 部全 Moodyz），
// 2021 另有 2 部 S1（不構成主要片商年）。Carol：2023 是 Moodyz 主要片商年。
// 另有 Bob／Cat／Dan 與 Alice 同片，一部無年份。
function fx() {
    return [
        ...many(2, { year: 2023, maker: 'S1', actresses: ['Alice', 'Bob'] }),
        ...many(2, { year: 2023, maker: 'S1', actresses: ['Alice'] }),
        ...many(4, { year: 2020, maker: 'Moodyz', actresses: ['Alice'] }),
        ...many(2, { year: 2021, maker: 'S1', actresses: ['Alice'] }),
        ...many(4, { year: 2023, maker: 'Moodyz', actresses: ['Carol'] }),
        rec({ year: 2023, maker: 'Moodyz', actresses: ['Alice', 'Cat'] }),
        rec({ year: 2022, maker: 'S1', actresses: ['Alice', 'Dan'] }),
        rec({ year: null, maker: 'S1', actresses: ['Carol'] }),
    ];
}

const ALL = { type: 'all' };
const Y = (year) => ({ type: 'year', year });
const R = (from, to) => ({ type: 'range', from, to });

test('buildGanttRows: 期間∩片商必須同一個 (y,mk) 同時成立，不是各自成立', () => {
    const records = fx();
    const map = buildMainMakerYearMap(records);
    assert.equal(map['Alice|2023'], 'S1');
    assert.equal(map['Alice|2020'], 'Moodyz');
    const names = (sel) => buildGanttRows(records, map, sel).map((r) => r.name).sort();
    assert.deepEqual(names({ period: Y(2023), actress: null, maker: 'Moodyz' }), ['Carol']);
    assert.deepEqual(names({ period: Y(2023), actress: null, maker: 'S1' }), ['Alice']);
    assert.deepEqual(names({ period: R(2019, 2023), actress: null, maker: 'Moodyz' }), ['Alice', 'Carol']);
});

test('buildSoloRows: 誰上榜＝期間∩片商，長條比例＝期間全貌', () => {
    const records = [
        ...many(2, { year: 2023, maker: 'S1', actresses: ['Eve'] }),
        ...many(3, { year: 2023, maker: 'Moodyz', actresses: ['Eve'] }),
        ...many(3, { year: 2023, maker: 'Moodyz', actresses: ['Fay'] }),
        ...many(1, { year: 2019, maker: 'S1', actresses: ['Gus'] }),
    ];
    const map = buildMainMakerYearMap(records);
    const sel = { period: Y(2023), actress: null, maker: 'S1' };
    const rows = buildSoloRows(records, map, sel, [], []);
    const names = rows.map((r) => r.name);
    assert.deepEqual(names, ['Eve']);
    // Eve 的列畫的是她 2023 全貌 5 部，不是只有 S1 的 2 部
    assert.equal(rows[0].total, 5);
    const range = buildSoloRows(records, map, { period: R(2019, 2023), actress: null, maker: 'S1' }, [], []);
    assert.deepEqual(range.map((r) => r.name).sort(), ['Eve', 'Gus']);
});

test('buildCostarRows: 範圍＝期間∩女優∩片商，沒選女優回空', () => {
    const records = fx();
    assert.deepEqual(buildCostarRows(records, { period: ALL, actress: null, maker: 'S1' }), []);
    assert.deepEqual(buildCostarRows(records, { period: ALL, actress: null, maker: null }), []);
    const got = buildCostarRows(records, { period: Y(2023), actress: 'Alice', maker: 'S1' });
    assert.deepEqual(got, [{ name: 'Bob', count: 2 }]);
    const wide = buildCostarRows(records, { period: Y(2023), actress: 'Alice', maker: null });
    assert.deepEqual(wide, [{ name: 'Bob', count: 2 }, { name: 'Cat', count: 1 }]);
});

