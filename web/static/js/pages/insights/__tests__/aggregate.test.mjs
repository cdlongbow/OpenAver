// TASK-156b-T1: setRecords / getRecords / buildMakerColorSlots / buildMainMakerYearMap 契約。
// 純函式、零 window / Alpine；邊界條件各至少一條真斷言。

import { test } from 'node:test';
import assert from 'node:assert/strict';

const {
    setRecords,
    getRecords,
    buildMakerColorSlots,
    buildMainMakerYearMap,
} = await import('../aggregate.js');

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
