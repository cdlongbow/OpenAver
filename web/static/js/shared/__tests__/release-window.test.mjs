// TASK-124a-T1: release-window.js 六支純函式契約。
//
// 全部零 import 的純函式（不 import 任何模組），不需要 globalThis.window stub、
// 不需要 resolve hook（無跨目錄 `@/` import）。比照 shared/__tests__/part-label.test.mjs
// 的最簡範本。
//
// parseEndpoint 走「嚴格形狀」：正則 `^(\d{4})(?:-(\d{2}))?$`，月份必須恰兩位
// （composeEndpoint 永遠 zero-pad，系統本身不會產生 '2023-9'）。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    parseReleaseKey,
    parseReleaseYearOnly,
    parseEndpoint,
    expandPill,
    matchesReleasePill,
    composeEndpoint,
    videoYearRange,
} from '../release-window.js';

// ===== parseReleaseKey =====

test('parseReleaseKey：YYYY-MM-DD 取前 7 字，DD 丟棄', () => {
    assert.equal(parseReleaseKey('2024-09-09'), 202409);
});

test('parseReleaseKey：只有年份（無月份）→ null（spec §4.4／§9 已知限制 1）', () => {
    assert.equal(parseReleaseKey('2015'), null);
});

test('parseReleaseKey：畸形字串（非 \\d{4}-\\d{2} 開頭）→ null', () => {
    assert.equal(parseReleaseKey('unknown'), null);
    assert.equal(parseReleaseKey('N/A'), null);
    assert.equal(parseReleaseKey('not-a-date'), null);
    assert.equal(parseReleaseKey('2024/09/09'), null);
});

test('parseReleaseKey：月份不在 1–12 → null（資料層防禦）', () => {
    assert.equal(parseReleaseKey('2024-13-01'), null);
    assert.equal(parseReleaseKey('2024-00-01'), null);
});

// ===== parseEndpoint（嚴格形狀，見檔頭說明） =====

test('parseEndpoint：四位年、無月 → {y, m:null}', () => {
    assert.deepEqual(parseEndpoint('2023'), { y: 2023, m: null });
});

test('parseEndpoint：YYYY-MM（月份恰兩位）→ {y, m}', () => {
    assert.deepEqual(parseEndpoint('2023-09'), { y: 2023, m: 9 });
    assert.deepEqual(parseEndpoint('2023-12'), { y: 2023, m: 12 });
});

// ===== expandPill（spec §4.3 展開規則表，逐列） =====

test('expandPill 1：{op:"=", value:"2024-09"} → {lo:202409, hi:202409}', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '=', value: '2024-09' }), { lo: 202409, hi: 202409 });
});

test('expandPill 2：{op:"=", value:"2024"} → {lo:202401, hi:202412}（缺月＝整年）', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '=', value: '2024' }), { lo: 202401, hi: 202412 });
});

test('expandPill 3：{op:">=", value:"2024-09"} → {lo:202409, hi:Infinity}', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '>=', value: '2024-09' }), { lo: 202409, hi: Infinity });
});

test('expandPill 4：{op:">=", value:"2024"} → {lo:202401, hi:Infinity}', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '>=', value: '2024' }), { lo: 202401, hi: Infinity });
});

test('expandPill 5：{op:"<=", value:"2024-09"} → {lo:-Infinity, hi:202409}', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '<=', value: '2024-09' }), { lo: -Infinity, hi: 202409 });
});

test('expandPill 6：{op:"<=", value:"2024"} → {lo:-Infinity, hi:202412}', () => {
    assert.deepEqual(expandPill({ dim: 'release', op: '<=', value: '2024' }), { lo: -Infinity, hi: 202412 });
});

test('expandPill 7：{op:"range", value:"2023", value2:"2024-06"} → {lo:202301, hi:202406}', () => {
    assert.deepEqual(
        expandPill({ dim: 'release', op: 'range', value: '2023', value2: '2024-06' }),
        { lo: 202301, hi: 202406 },
    );
});

test('expandPill 8：{op:"range", value:"2023-05", value2:"2023"} → {lo:202305, hi:202312}', () => {
    assert.deepEqual(
        expandPill({ dim: 'release', op: 'range', value: '2023-05', value2: '2023' }),
        { lo: 202305, hi: 202312 },
    );
});

// ===== matchesReleasePill =====

test('matchesReleasePill：key 落在 [lo, hi] 含端點 → true', () => {
    const w = { lo: 202401, hi: 202412 };
    assert.equal(matchesReleasePill({ release_date: '2024-01-01' }, w), true);
    assert.equal(matchesReleasePill({ release_date: '2024-12-31' }, w), true);
    assert.equal(matchesReleasePill({ release_date: '2024-06-15' }, w), true);
});

test('matchesReleasePill：key 落在區間外 → false', () => {
    const w = { lo: 202401, hi: 202412 };
    assert.equal(matchesReleasePill({ release_date: '2023-12-31' }, w), false);
    assert.equal(matchesReleasePill({ release_date: '2025-01-01' }, w), false);
});

// ===== parseReleaseYearOnly & matchesReleasePill (year-only) =====

test('parseReleaseYearOnly：輸入表', () => {
    const table = [
        ['2015', 2015],
        ['2015-03', 2015],
        ['2015-03-09', 2015],
        ['2015-13-01', 2015],
        ['20150301', 2015],
        ['1900', 1900],
        ['2100', 2100],
        ['1899', null],
        ['2200', null],
        ['abcd', null],
        ['', null],
        [null, null],
    ];
    for (const [raw, expected] of table) {
        assert.equal(parseReleaseYearOnly(raw), expected, `failed for raw: ${raw}`);
    }
});

test('年份-only：窗口涵蓋整年才算', () => {
    const wEq = expandPill({ op: '=', value: '2015' });
    const wRange = expandPill({ op: 'range', value: '2014', value2: '2016' });
    const wGte = expandPill({ op: '>=', value: '2015' });
    const wLte = expandPill({ op: '<=', value: '2015' });

    assert.equal(matchesReleasePill({ release_date: '2015' }, wEq), true);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wRange), true);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wGte), true);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wLte), true);

    assert.equal(matchesReleasePill({ release_date: '2015-13-01' }, wEq), true);
    assert.equal(matchesReleasePill({ release_date: '20150301' }, wEq), true);
});

test('年份-only：窗口只涵蓋部分月份不算', () => {
    const wPartRange = expandPill({ op: 'range', value: '2015-03', value2: '2015-06' });
    const wGtePart = expandPill({ op: '>=', value: '2015-03' });
    const wLtePart = expandPill({ op: '<=', value: '2015-06' });
    const wOtherYear = expandPill({ op: '=', value: '2014' });
    const wNextYear = expandPill({ op: '>=', value: '2016' });

    assert.equal(matchesReleasePill({ release_date: '2015' }, wPartRange), false);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wGtePart), false);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wLtePart), false);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wOtherYear), false);
    assert.equal(matchesReleasePill({ release_date: '2015' }, wNextYear), false);

    assert.equal(matchesReleasePill({ release_date: '2015-13-01' }, wPartRange), false);
    assert.equal(matchesReleasePill({ release_date: '20150301' }, wPartRange), false);
});

test('年份-only：解析不出年份／空值不算', () => {
    const w = expandPill({ op: '<=', value: '2099' });
    assert.equal(matchesReleasePill({ release_date: '1899' }, w), false);
    assert.equal(matchesReleasePill({ release_date: '2200' }, w), false);
    assert.equal(matchesReleasePill({ release_date: '' }, w), false);
    assert.equal(matchesReleasePill({ release_date: null }, w), false);
    assert.equal(matchesReleasePill({}, w), false);
});

// ===== composeEndpoint =====

test('composeEndpoint：(2023, null) → "2023"（年份不 pad，CD-124a-10）', () => {
    assert.equal(composeEndpoint(2023, null), '2023');
});

test('composeEndpoint：(2023, 9) → "2023-09"（月份 zero-pad 到兩位）', () => {
    assert.equal(composeEndpoint(2023, 9), '2023-09');
});

test('composeEndpoint：月份不在 1–12 → null（防禦）', () => {
    assert.equal(composeEndpoint(2023, 0), null);
    assert.equal(composeEndpoint(2023, 13), null);
});

test('composeEndpoint：年份非四位整數 → null（防禦）', () => {
    assert.equal(composeEndpoint(250, null), null);
    assert.equal(composeEndpoint(2, null), null);
});

// ===== videoYearRange =====

test('videoYearRange：全部影片皆解析不出年月 → null', () => {
    assert.equal(videoYearRange([{ release_date: '2015' }, { release_date: '' }, { release_date: null }]), null);
});

test('videoYearRange：混合（部分可解析部分不可）→ 只取可解析的算 min/max', () => {
    const videos = [
        { release_date: '2020-05-01' },
        { release_date: 'unknown' },
        { release_date: '2018-01-01' },
        { release_date: '2022-12-31' },
    ];
    assert.deepEqual(videoYearRange(videos), { min: 2018, max: 2022 });
});
