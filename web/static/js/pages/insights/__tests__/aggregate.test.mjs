// TASK-156b-T1: setRecords / getRecords / buildMakerColorSlots / buildMainMakerYearMap 契約。
// TASK-156b-T2: periodRecords / scopeRecords / aggregateYears 契約 + §4.2 wiring。
// 純函式、零 window / Alpine；邊界條件各至少一條真斷言。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const agg = await import('../aggregate.js');
const {
    setRecords,
    getRecords,
    buildMakerColorSlots,
    buildMainMakerYearMap,
} = agg;
const {
    periodRecords,
    scopeRecords,
    aggregateYears,
    UNKNOWN_KEY,
    REST_KEY,
    buildMakerDonutData,
    classifyRecordAgainstMainMaker,
} = agg;

function rec(opts) {
    return {
        year: opts.year === undefined ? 2020 : opts.year,
        actresses: opts.actresses === undefined ? ['Alice'] : opts.actresses,
        maker: opts.maker === undefined ? 'SOD' : opts.maker,
    };
}

// ── setRecords / getRecords ──────────────────────────────────────────

test('getRecords: 呼叫 setRecords 前回傳空陣列', () => {
    assert.deepEqual(getRecords(), []);
});

test('setRecords/getRecords: 內容逐項相同但不是同一個陣列 reference', () => {
    const records = [
        rec({ maker: 'SOD', year: 2021 }),
        rec({ maker: 'Moodyz', year: 2022, actresses: ['Bob'] }),
    ];
    setRecords(records);
    const got = getRecords();
    assert.equal(got.length, 2);
    assert.equal(got[0].maker, 'SOD');
    assert.equal(got[1].maker, 'Moodyz');
    assert.notStrictEqual(got, records);
    // 再設一次確認 length=0 + push 覆寫（不是 append）
    setRecords([rec({ maker: 'IdeaPocket' })]);
    assert.equal(getRecords().length, 1);
    assert.equal(getRecords()[0].maker, 'IdeaPocket');
});

// ── buildMakerColorSlots ─────────────────────────────────────────────

test('buildMakerColorSlots: 第 9 名（含）以後不進 slot map', () => {
    // 10 家具名片商，計數 10..1；只有前 8 名進 map
    const makers = [
        'M10', 'M09', 'M08', 'M07', 'M06', 'M05', 'M04', 'M03', 'M02', 'M01',
    ];
    const records = [];
    makers.forEach((name, i) => {
        const count = 10 - i;
        for (let n = 0; n < count; n++) {
            records.push(rec({ maker: name, actresses: [`A${i}-${n}`] }));
        }
    });
    const slots = buildMakerColorSlots(records);
    assert.equal(Object.keys(slots).length, 8);
    assert.equal(slots['M10'], 0);
    assert.equal(slots['M09'], 1);
    assert.equal(slots['M08'], 2);
    assert.equal(slots['M07'], 3);
    assert.equal(slots['M06'], 4);
    assert.equal(slots['M05'], 5);
    assert.equal(slots['M04'], 6);
    assert.equal(slots['M03'], 7);
    assert.equal(slots.hasOwnProperty('M02'), false);
    assert.equal(slots.hasOwnProperty('M01'), false);
});

test('buildMakerColorSlots: 同分時依名稱字串遞增，超出 Top8 排除字串序較大者', () => {
    // 7 家具名高計數（8..2，皆 > 1）佔 slot 0..6；其餘三家同分 count=1
    // → 字串序 Apple < Mango < Zebra；Top8 只收 Apple；Mango、Zebra 被排除
    const records = [];
    const high = ['H8', 'H7', 'H6', 'H5', 'H4', 'H3', 'H2'];
    high.forEach((name, i) => {
        const count = 8 - i;
        for (let n = 0; n < count; n++) {
            records.push(rec({ maker: name }));
        }
    });
    // 刻意用非字串序的加入順序，抓「未排序直接 slice」假綠
    records.push(rec({ maker: 'Zebra' }));
    records.push(rec({ maker: 'Apple' }));
    records.push(rec({ maker: 'Mango' }));

    const slots = buildMakerColorSlots(records);
    assert.equal(Object.keys(slots).length, 8);
    assert.equal(slots['Apple'], 7);
    assert.equal(slots.hasOwnProperty('Mango'), false);
    assert.equal(slots.hasOwnProperty('Zebra'), false);
});

test('buildMakerColorSlots: maker 為 null 的紀錄不佔名額、不出現在 key 中', () => {
    const records = [];
    for (let i = 0; i < 20; i++) {
        records.push(rec({ maker: null }));
    }
    // 剛好 8 家具名片商各 1 部
    for (let i = 1; i <= 8; i++) {
        records.push(rec({ maker: `Named${i}` }));
    }
    const slots = buildMakerColorSlots(records);
    assert.equal(Object.keys(slots).length, 8);
    assert.equal(slots.hasOwnProperty('null'), false);
    assert.equal(Object.prototype.hasOwnProperty.call(slots, null), false);
    for (let i = 1; i <= 8; i++) {
        assert.equal(typeof slots[`Named${i}`], 'number');
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
    const records = [
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: 'StudioA' }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
        rec({ year: 2023, actresses: ['Dana'], maker: null }),
    ];
    const map = buildMainMakerYearMap(records);
    // 若誤把 null 從分母排除 → total=3、best/total=100% 會誤判命中
    assert.equal(map.hasOwnProperty('Dana|2023'), false);
});

test('buildMainMakerYearMap: 5 部全為 maker null（未知達門檻）仍不得選為主要片商', () => {
    // 鎖 null 候選排除：若拿掉 `if (mk === null) return;`，null 桶 5/5=100% 會誤寫入 key
    const records = [
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
        rec({ year: 2023, actresses: ['DanaNull'], maker: null }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map.hasOwnProperty('DanaNull|2023'), false);
});

test('buildMainMakerYearMap: 3 部全同片商（100%）未達至少 4 部門檻不計入', () => {
    const records = [
        rec({ year: 2025, actresses: ['Fran'], maker: 'SOD' }),
        rec({ year: 2025, actresses: ['Fran'], maker: 'SOD' }),
        rec({ year: 2025, actresses: ['Fran'], maker: 'SOD' }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map.hasOwnProperty('Fran|2025'), false);
});

test('buildMainMakerYearMap: year 為 null 的片完全不影響任何女優|年計算', () => {
    // 有 year 的 4 部同片商本應命中；夾雜 year=null 的同女優片不得改變結果
    const records = [
        rec({ year: 2024, actresses: ['Eve'], maker: 'SOD' }),
        rec({ year: 2024, actresses: ['Eve'], maker: 'SOD' }),
        rec({ year: 2024, actresses: ['Eve'], maker: 'SOD' }),
        rec({ year: 2024, actresses: ['Eve'], maker: 'SOD' }),
        rec({ year: null, actresses: ['Eve'], maker: 'Moodyz' }),
        rec({ year: null, actresses: ['Eve'], maker: 'Moodyz' }),
        rec({ year: null, actresses: ['Eve'], maker: 'Moodyz' }),
        rec({ year: null, actresses: ['Eve'], maker: 'Moodyz' }),
    ];
    const map = buildMainMakerYearMap(records);
    assert.equal(map['Eve|2024'], 'SOD');
    // 不得出現 null year 的 key
    assert.equal(Object.keys(map).some((k) => k.includes('|null') || k.endsWith('|')), false);
});

// ── periodRecords / scopeRecords（TASK-156b-T2）──────────────────────

test('scopeRecords: focus=null 時與 periodRecords 回傳內容逐項相同', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: null, actresses: ['Bob'], maker: 'Moodyz' }),
        rec({ year: 2021, actresses: ['Carol'], maker: 'SOD' }),
    ];
    const period = { type: 'all' };
    assert.deepStrictEqual(
        scopeRecords(records, period, null),
        periodRecords(records, period),
    );
    const yearPeriod = { type: 'year', year: 2020 };
    assert.deepStrictEqual(
        scopeRecords(records, yearPeriod, null),
        periodRecords(records, yearPeriod),
    );
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

    const byActress = scopeRecords(records, { type: 'all' }, { type: 'actress', value: 'Alice' });
    assert.deepStrictEqual(byActress, [multi, onlyAlice]);

    const byMaker = scopeRecords(records, { type: 'all' }, { type: 'maker', value: 'SOD' });
    assert.deepStrictEqual(byMaker, [multi]);
});

// ── aggregateYears（TASK-156b-T2）────────────────────────────────────

test('aggregateYears: 無焦點時 categories 尾端固定有 UNKNOWN_KEY（即使沒有 year===null）', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2022, actresses: ['Bob'], maker: 'Moodyz' }),
    ];
    const result = aggregateYears(records, { type: 'all' }, null);
    assert.deepStrictEqual(result.categories, ['2020', '2021', '2022', UNKNOWN_KEY]);
    assert.equal(result.series.length, 1);
    assert.equal(result.series[0].name, null);
    assert.deepStrictEqual(result.series[0].data, [1, 0, 1, 0]);
    assert.deepStrictEqual(result.dimmed, [false, false, false, false]);
});

test('aggregateYears: 有焦點時只有 base 真有 year===null 才出現 UNKNOWN_KEY', () => {
    const withNull = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: null, actresses: ['Alice'], maker: 'SOD' }),
    ];
    const withNullResult = aggregateYears(
        withNull, { type: 'all' }, { type: 'maker', value: 'SOD' },
    );
    assert.ok(withNullResult.categories.includes(UNKNOWN_KEY));
    assert.equal(withNullResult.categories[withNullResult.categories.length - 1], UNKNOWN_KEY);

    const noNull = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' }),
    ];
    const noNullResult = aggregateYears(
        noNull, { type: 'all' }, { type: 'maker', value: 'SOD' },
    );
    assert.equal(noNullResult.categories.includes(UNKNOWN_KEY), false);
    assert.deepStrictEqual(noNullResult.categories, ['2020', '2021']);
});

test('aggregateYears: 有焦點時橫軸涵蓋到最後一年即使該年沒有片（空年保留空位）', () => {
    // Alice：2019 與 2021 有片、2020 空年；mutation 把 <= 改 < 會丟掉最後一年 2021
    const records = [
        rec({ year: 2019, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' }),
        rec({ year: 2020, actresses: ['Bob'], maker: 'SOD' }), // 非焦點，不影響範圍
    ];
    const result = aggregateYears(
        records, { type: 'all' }, { type: 'actress', value: 'Alice' },
    );
    assert.deepStrictEqual(result.categories, ['2019', '2020', '2021']);
    // 2020 空位：各 series 該格皆 0
    const idx2020 = result.categories.indexOf('2020');
    for (const s of result.series) {
        assert.equal(s.data[idx2020], 0);
    }
    assert.equal(result.categories.includes('2021'), true);
});

test('aggregateYears: 選年份時其他年數值不變只淡化', () => {
    const records = [
        rec({ year: 2019, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'Moodyz' }),
        rec({ year: null, actresses: ['Alice'], maker: 'SOD' }),
    ];
    const focus = { type: 'actress', value: 'Alice' };
    const allPeriod = aggregateYears(records, { type: 'all' }, focus);
    const yearPeriod = aggregateYears(records, { type: 'year', year: 2020 }, focus);

    assert.equal(allPeriod.series.length, yearPeriod.series.length);
    for (let i = 0; i < allPeriod.series.length; i++) {
        assert.equal(allPeriod.series[i].name, yearPeriod.series[i].name);
        assert.deepStrictEqual(allPeriod.series[i].data, yearPeriod.series[i].data);
    }
    assert.deepStrictEqual(allPeriod.dimmed, [false, false, false, false]);
    assert.deepStrictEqual(yearPeriod.dimmed, [true, false, true, true]);
});

test('aggregateYears: 無焦點 series 長度 1、name null；categories=min..max+UNKNOWN_KEY', () => {
    const records = [
        rec({ year: 2021, actresses: ['A'], maker: 'SOD' }),
        rec({ year: 2023, actresses: ['B'], maker: 'Moodyz' }),
        rec({ year: null, actresses: ['C'], maker: 'SOD' }),
    ];
    const result = aggregateYears(records, { type: 'all' }, null);
    assert.deepStrictEqual(result.categories, ['2021', '2022', '2023', UNKNOWN_KEY]);
    assert.equal(result.series.length, 1);
    assert.equal(result.series[0].name, null);
    assert.deepStrictEqual(result.series[0].data, [1, 0, 1, 1]);
});

test('aggregateYears: 片商焦點 base 空時回傳空 categories/series/dimmed', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
    ];
    const result = aggregateYears(
        records, { type: 'all' }, { type: 'maker', value: 'MissingStudio' },
    );
    assert.deepStrictEqual(result, { categories: [], series: [], dimmed: [] });
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
        records, { type: 'all' }, { type: 'maker', value: M },
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
        records, { type: 'all' }, { type: 'actress', value: 'Alice' },
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

test('aggregateYears: 女優焦點同分時依片商名稱字串遞增', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'Zebra' }),
        rec({ year: 2020, actresses: ['Alice'], maker: 'Apple' }),
    ];
    const result = aggregateYears(
        records, { type: 'all' }, { type: 'actress', value: 'Alice' },
    );
    assert.deepStrictEqual(result.series.map((s) => s.name), ['Apple', 'Zebra']);
});

test('aggregateYears: dimmed 對 year 期間只有 String(Y) 為 false，其餘含 UNKNOWN 皆 true', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: 'SOD' }),
        rec({ year: 2021, actresses: ['Bob'], maker: 'SOD' }),
        rec({ year: null, actresses: ['Carol'], maker: 'SOD' }),
    ];
    const allDimmed = aggregateYears(records, { type: 'all' }, null);
    assert.deepStrictEqual(allDimmed.dimmed, [false, false, false]);

    const yearDimmed = aggregateYears(records, { type: 'year', year: 2020 }, null);
    assert.deepStrictEqual(yearDimmed.dimmed, [false, true, true]);
    assert.equal(yearDimmed.categories[yearDimmed.categories.length - 1], UNKNOWN_KEY);
});

test('aggregateYears: maker 未知桶用 UNKNOWN_KEY，不產生顯示字串', () => {
    const records = [
        rec({ year: 2020, actresses: ['Alice'], maker: null }),
        rec({ year: 2021, actresses: ['Alice'], maker: 'SOD' }),
    ];
    const result = aggregateYears(
        records, { type: 'all' }, { type: 'actress', value: 'Alice' },
    );
    assert.equal(result.series.some((s) => s.name === UNKNOWN_KEY), true);
    assert.equal(result.series.some((s) => s.name === 'SOD'), true);
});

// ── §4.2 wiring 15 格 checklist ──────────────────────────────────────

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
    assert.deepStrictEqual(aggregateYears(records, period, null), YEARS_NONE);
    assert.deepStrictEqual(aggregateYears(records, period, focusM), YEARS_MAKER);
    assert.deepStrictEqual(aggregateYears(records, period, focusA), YEARS_ACTRESS);

    // ── 片商圓餅（3）──
    // 無焦點 → periodRecords
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 片商焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 女優焦點 → scopeRecords(actress)
    assert.deepStrictEqual(idsOf(scopeRecords(records, period, focusA)), IDS_SCOPE_ACTRESS);

    // ── 女優 Top20（3）──
    // 無焦點 → periodRecords
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    // 片商焦點 → scopeRecords(maker)
    assert.deepStrictEqual(idsOf(scopeRecords(records, period, focusM)), IDS_SCOPE_MAKER);
    // 女優焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);

    // ── 標籤／年齡／導演／系列（3）──
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    assert.deepStrictEqual(idsOf(scopeRecords(records, period, focusM)), IDS_SCOPE_MAKER);
    assert.deepStrictEqual(idsOf(scopeRecords(records, period, focusA)), IDS_SCOPE_ACTRESS);

    // ── 年表／分布表（3）──
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);
    assert.deepStrictEqual(idsOf(scopeRecords(records, period, focusM)), IDS_SCOPE_MAKER);
    // 女優焦點 → periodRecords（期間全貌，忽略 focus）
    assert.deepStrictEqual(idsOf(periodRecords(records, period)), IDS_PERIOD_ALL);

    // 三個「期間全貌」格（片商圓餅×片商焦點、女優Top20×女優焦點、年表×女優焦點）：
    // 卡片取用 periodRecords（不吃 focus）。三種焦點 UI 狀態下 id 集合皆＝手寫全庫常數；
    // 有焦點時若誤改成 scopeRecords，會偏離 IDS_PERIOD_ALL。
    for (const focus of [null, focusM, focusA]) {
        const overviewIds = idsOf(periodRecords(records, period));
        assert.deepStrictEqual(overviewIds, IDS_PERIOD_ALL);
        if (focus !== null) {
            assert.notDeepStrictEqual(
                idsOf(scopeRecords(records, period, focus)),
                IDS_PERIOD_ALL,
            );
        }
    }
});

// ── TASK-156b-T4: buildMakerDonutData / classifyRecordAgainstMainMaker ──

test('buildMakerDonutData: 局部第 9 名（含）以後併入 REST_KEY，不個別列名', () => {
    // 10 家具名片商計數 10..1；局部前 8 具名，第 9／10 名併入 REST
    const makers = [
        'M10', 'M09', 'M08', 'M07', 'M06', 'M05', 'M04', 'M03', 'M02', 'M01',
    ];
    const records = [];
    makers.forEach((name, i) => {
        const count = 10 - i;
        for (let n = 0; n < count; n++) {
            records.push(rec({ maker: name, actresses: [`A${i}-${n}`], year: 2020 }));
        }
    });
    const result = buildMakerDonutData(records, {});
    const named = result.inner.filter((e) => e.kind === 'named');
    assert.equal(named.length, 8);
    assert.deepStrictEqual(
        named.map((e) => e.name),
        ['M10', 'M09', 'M08', 'M07', 'M06', 'M05', 'M04', 'M03'],
    );
    const rest = result.inner.find((e) => e.kind === 'rest');
    assert.ok(rest);
    assert.equal(rest.name, REST_KEY);
    // M02 count=2 + M01 count=1
    assert.equal(rest.value, 3);
    assert.equal(
        result.inner.some((e) => e.name === 'M02' || e.name === 'M01'),
        false,
    );
});

test('buildMakerDonutData: maker 為 null/空字串的紀錄全部併入 UNKNOWN_KEY', () => {
    const records = [
        rec({ maker: 'SOD', year: 2020 }),
        rec({ maker: null, year: 2020 }),
        rec({ maker: '', year: 2021 }),
        rec({ maker: null, year: 2022 }),
    ];
    const result = buildMakerDonutData(records, {});
    const unknown = result.inner.find((e) => e.kind === 'unknown');
    assert.ok(unknown);
    assert.equal(unknown.name, UNKNOWN_KEY);
    assert.equal(unknown.value, 3);
    const named = result.inner.filter((e) => e.kind === 'named');
    assert.equal(named.length, 1);
    assert.equal(named[0].name, 'SOD');
    assert.equal(named[0].value, 1);
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

test('classifyRecordAgainstMainMaker: year==null 時即使其他年命中仍為 undetermined', () => {
    const map = { 'Alice|2020': 'SOD' };
    const got = classifyRecordAgainstMainMaker(
        rec({ maker: 'SOD', year: null, actresses: ['Alice'] }),
        map,
    );
    assert.equal(got, 'undetermined');
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

test('classifyRecordAgainstMainMaker: actresses 為空 → undetermined', () => {
    assert.equal(
        classifyRecordAgainstMainMaker(
            rec({ maker: 'SOD', year: 2020, actresses: [] }),
            { 'Alice|2020': 'SOD' },
        ),
        'undetermined',
    );
});
