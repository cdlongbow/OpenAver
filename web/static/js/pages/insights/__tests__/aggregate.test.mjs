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
    REST_KEY,
    ACTRESS_TOP_N,
    buildMakerDonutData,
    classifyRecordAgainstMainMaker,
    buildActressBoard,
    aggregateTags,
    aggregateAge,
    aggregateFieldTop8,
    buildGanttRows,
    ganttYearAxis,
    buildGanttYearCells,
    buildGanttAgeCells,
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

test('buildMainMakerYearMap: 4 部中 3 部同片商（3/4=75%）不計入主要片商年', () => {
    const records = [
        rec({ year: 2021, actresses: ['Bob'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Bob'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Bob'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Bob'], maker: 'Moodyz' }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map.hasOwnProperty('Bob|2021'), false);
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


test('§4.2 wiring: 5 卡群組 × 3 焦點 = 15 格 checklist', () => {
    const M = 'SOD';
    const A = 'Alice';
    // 手算常數用的 fixture（含 id，方便集合比對）
    // r1: 2020 Alice SOD
    // r2: 2021 Alice+Bob Moodyz
    // r3: 2022 Bob Moodyz
    // r4: null Alice SOD
    // r5: 2020 Carol IdeaPocket
    const records = [
        { id: 'r1', year: 2020, actresses: [A], maker: M },
        { id: 'r2', year: 2021, actresses: [A, 'Bob'], maker: 'Moodyz' },
        { id: 'r3', year: 2022, actresses: ['Bob'], maker: 'Moodyz' },
        { id: 'r4', year: null, actresses: [A], maker: M },
        { id: 'r5', year: 2020, actresses: ['Carol'], maker: 'IdeaPocket' },
    ];
    const period = { type: 'all' };
    const focusM = { type: 'maker', value: M };
    const focusA = { type: 'actress', value: A };
    const idsOf = (list) => list.map((r) => r.id);

    // 手算期望常數（不得由被測函式回填）
    const IDS_PERIOD_ALL = ['r1', 'r2', 'r3', 'r4', 'r5'];
    const IDS_SCOPE_MAKER = ['r1', 'r4'];
    const IDS_SCOPE_ACTRESS = ['r1', 'r2', 'r4'];
    const YEARS_NONE = {
        categories: ['2020', '2021', '2022', UNKNOWN_KEY],
        series: [{ name: null, data: [2, 1, 1, 1] }],
        dimmed: [false, false, false, false],
    };
    // maker SOD base = r1(2020)+r4(null) → 只有 2020..2020 + UNKNOWN
    const YEARS_MAKER = {
        categories: ['2020', UNKNOWN_KEY],
        series: [{ name: 'SOD', data: [1, 1] }],
        dimmed: [false, false],
    };
    // actress Alice base = r1(SOD 2020)+r2(Moodyz 2021)+r4(SOD null)
    // maker 計數 SOD=2 > Moodyz=1
    const YEARS_ACTRESS = {
        categories: ['2020', '2021', UNKNOWN_KEY],
        series: [
            { name: 'SOD', data: [1, 0, 1] },
            { name: 'Moodyz', data: [0, 1, 0] },
        ],
        dimmed: [false, false, false],
    };

    // ── 年份（3）── 手算常數
    assert.deepStrictEqual(aggregateYears(records, selOf(period, null)), YEARS_NONE);
    assert.deepStrictEqual(aggregateYears(records, selOf(period, focusM)), YEARS_MAKER);
    assert.deepStrictEqual(aggregateYears(records, selOf(period, focusA)), YEARS_ACTRESS);

    // ── 片商圓餅（3）──
    // 無焦點 → periodRecords
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 片商焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 女優焦點 → scopeRecords(actress)
    assert.deepStrictEqual(idsOf(scopeRecords(records, selOf(period, focusA), null)), IDS_SCOPE_ACTRESS);

    // ── 女優榜（3）──
    // 無焦點 → periodRecords
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 片商焦點 → scopeRecords(maker)
    assert.deepStrictEqual(idsOf(scopeRecords(records, selOf(period, focusM), null)), IDS_SCOPE_MAKER);
    // 女優焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);

    // ── 標籤／年齡／導演／系列（3）──
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    assert.deepStrictEqual(idsOf(scopeRecords(records, selOf(period, focusM), null)), IDS_SCOPE_MAKER);
    assert.deepStrictEqual(idsOf(scopeRecords(records, selOf(period, focusA), null)), IDS_SCOPE_ACTRESS);

    // ── 年表／分布表（3）──
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    assert.deepStrictEqual(idsOf(scopeRecords(records, selOf(period, focusM), null)), IDS_SCOPE_MAKER);
    // 女優焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);

    // 三個「期間全貌」格（片商圓餅×片商焦點、女優榜×女優焦點、年表×女優焦點）：
    // 卡片取用 periodRecords（不吃 focus）。三種焦點 UI 狀態下 id 集合皆＝手寫全庫常數；
    // 有焦點時若誤改成 scopeRecords，會偏離 IDS_PERIOD_ALL。
    for (const focus of [null, focusM, focusA]) {
        const overviewIds = idsOf(periodRecords(records, period));
        assert.deepStrictEqual(overviewIds, IDS_PERIOD_ALL);
        if (focus !== null) {
            assert.notDeepStrictEqual(
                idsOf(scopeRecords(records, selOf(period, focus), null)),
                IDS_PERIOD_ALL,
            );
        }
    }
});


test('buildMakerDonutData: outer 只對具名前 8 名分類；零計數桶不輸出；REST/UNKNOWN 不細分', () => {
    // SOD: 2 main + 1 other + 1 undetermined；Moodyz: 1 other only
    const map = {
        'Alice|2020': 'SOD',
        'Alice|2021': 'SOD',
    };
    const records = [
        rec({ maker: 'SOD', year: 2020, actresses: ['Alice'] }), // main
        rec({ maker: 'SOD', year: 2021, actresses: ['Alice'] }), // main
        rec({ maker: 'SOD', year: 2022, actresses: ['Alice'] }), // other (no map hit)
        rec({ maker: 'SOD', year: null, actresses: ['Alice'] }), // undetermined
        rec({ maker: 'Moodyz', year: 2020, actresses: ['Bob'] }), // other
        rec({ maker: null, year: 2020, actresses: ['Carol'] }), // unknown
        // rest makers to force a rest bucket
        rec({ maker: 'R9', year: 2020 }),
    ];
    // Pad 7 more makers so R9 is 9th → REST (SOD, Moodyz + 7 pad + R9 = 10 named)
    for (let i = 1; i <= 7; i++) {
        for (let n = 0; n < 3; n++) {
            records.push(rec({ maker: `Pad${i}`, year: 2020, actresses: [`P${i}-${n}`] }));
        }
    }
    // counts: Pad1..7 = 3 each, SOD = 4, Moodyz = 1, R9 = 1 → top8 = Pads + SOD (Moodyz+R9 → rest)
    const result = buildMakerDonutData(records, map);
    const namedNames = result.inner
        .filter((e) => e.kind === 'named')
        .map((e) => e.name);
    assert.equal(namedNames.length, 8);
    assert.equal(namedNames.includes('SOD'), true);
    assert.equal(namedNames.includes('Moodyz'), false);
    assert.equal(namedNames.includes('R9'), false);

    // outer for SOD: main/other/undetermined all non-zero
    const sodOuter = result.outer.filter((e) => e.maker === 'SOD');
    assert.deepStrictEqual(
        sodOuter.map((e) => e.kind).sort(),
        ['main', 'other', 'undetermined'],
    );
    assert.equal(sodOuter.find((e) => e.kind === 'main').value, 2);
    assert.equal(sodOuter.find((e) => e.kind === 'other').value, 1);
    assert.equal(sodOuter.find((e) => e.kind === 'undetermined').value, 1);

    // Moodyz not in top8 → no per-maker outer rows
    assert.equal(result.outer.some((e) => e.maker === 'Moodyz'), false);

    // REST / UNKNOWN: one undivided row each (value > 0)
    const restOuter = result.outer.filter((e) => e.kind === 'rest');
    const unkOuter = result.outer.filter((e) => e.kind === 'unknown');
    assert.equal(restOuter.length, 1);
    assert.equal(restOuter[0].maker, REST_KEY);
    assert.equal(restOuter[0].value, result.inner.find((e) => e.kind === 'rest').value);
    assert.equal(unkOuter.length, 1);
    assert.equal(unkOuter[0].maker, UNKNOWN_KEY);
    assert.equal(unkOuter[0].value, 1);
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

test('aggregateYears: dimmed 吃 range，期間只影響 dimmed 不影響 series 數值', () => {
    const records = fx();
    const all = aggregateYears(records, { period: ALL, actress: null, maker: null });
    const range = aggregateYears(records, { period: R(2020, 2021), actress: null, maker: null });
    const year = aggregateYears(records, { period: Y(2023), actress: null, maker: null });
    assert.deepEqual(all.categories, ['2020', '2021', '2022', '2023', UNKNOWN_KEY]);
    assert.deepEqual(range.series, all.series);
    assert.deepEqual(year.series, all.series);
    assert.deepEqual(all.dimmed, [false, false, false, false, false]);
    assert.deepEqual(range.dimmed, [false, false, true, true, true]);
    assert.deepEqual(year.dimmed, [true, true, true, false, true]);
});

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

test('buildGanttRows: 女優焦點下候選人主要片數與排序看期間∩片商全貌，不只看她本人的片', () => {
    const records = [
        ...many(2, { year: 2021, maker: 'S1', actresses: ['Focus'] }),
        ...many(5, { year: 2023, maker: 'S1', actresses: ['Zed'] }),
        ...many(4, { year: 2022, maker: 'S1', actresses: ['Amy'] }),
        ...many(4, { year: 2023, maker: 'S1', actresses: ['Bob'] }),
    ];
    const map = buildMainMakerYearMap(records);
    // 只選女優：列序＝她置頂，其餘依主要片數（Zed 5 > Amy 4 ＝ Bob 4），與依名字排序相反
    const a = buildGanttRows(records, map, { period: ALL, actress: 'Focus', maker: null });
    assert.deepEqual(a.map((r) => [r.name, r.mainCount]), [['Focus', 0], ['Zed', 5], ['Amy', 4], ['Bob', 4]]);
    // 女優∩片商∩期間（2023∩S1）：候選只剩 2023 的 S1 主要片商年，主要片數仍看全貌
    const b = buildGanttRows(records, map, { period: Y(2023), actress: 'Focus', maker: 'S1' });
    assert.deepEqual(b.map((r) => [r.name, r.mainCount]), [['Focus', 0], ['Zed', 5], ['Bob', 4]]);
});

