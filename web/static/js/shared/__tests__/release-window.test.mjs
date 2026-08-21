// TASK-124a-T1: release-window.js 六支純函式契約。
//
// 全部零 import 的純函式（不 import 任何模組），不需要 globalThis.window stub、
// 不需要 resolve hook（無跨目錄 `@/` import）。比照 shared/__tests__/part-label.test.mjs
// 的最簡範本。
//
// parseEndpoint 走「嚴格形狀」（Opus 對 card 的裁決，覆蓋 card 原文「月份允許 1 或 2 位」
// 那一列）：正則 `^(\d{4})(?:-(\d{2}))?$`，月份必須恰兩位。composeEndpoint 永遠 zero-pad，
// 系統本身不會產生 '2023-9' 這種形狀；容忍一位月份等於製造一種只有手改 localStorage
// 才生得出、而 pill 上會顯示成 '=2023-9' 的形狀，故本檔明確斷言 '2023-9' → null。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    parseReleaseKey,
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

test('parseReleaseKey：恰 7 字 YYYY-MM（無 DD）同一條解析路徑', () => {
    assert.equal(parseReleaseKey('2024-09'), 202409);
});

test('parseReleaseKey：只有年份（無月份）→ null（spec §4.4／§9 已知限制 1）', () => {
    assert.equal(parseReleaseKey('2015'), null);
});

test('parseReleaseKey：空字串 → null', () => {
    assert.equal(parseReleaseKey(''), null);
});

test('parseReleaseKey：null/undefined → null（型別防禦）', () => {
    assert.equal(parseReleaseKey(null), null);
    assert.equal(parseReleaseKey(undefined), null);
});

test('parseReleaseKey：number 型別 → null（型別防禦）', () => {
    assert.equal(parseReleaseKey(123), null);
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

test('parseEndpoint：月份只有一位（"2023-9"）→ null（嚴格形狀，刻意的裁決）', () => {
    // 覆蓋 card 原文「月份允許 1 或 2 位」——composeEndpoint 永遠 zero-pad，
    // 系統本身不會產生這種形狀，容忍它只會讓手改 localStorage 的畸形資料活下來。
    assert.equal(parseEndpoint('2023-9'), null);
});

test('parseEndpoint：空字串 → null', () => {
    assert.equal(parseEndpoint(''), null);
});

test('parseEndpoint：年份非恰四位 → null', () => {
    assert.equal(parseEndpoint('2'), null);
    assert.equal(parseEndpoint('250'), null);
    assert.equal(parseEndpoint('20244'), null);
});

test('parseEndpoint：開頭非數字 → null', () => {
    assert.equal(parseEndpoint('-1'), null);
});

test('parseEndpoint：月份不在 1–12 → null（13 月／0 月）', () => {
    assert.equal(parseEndpoint('2023-13'), null);
    assert.equal(parseEndpoint('2023-00'), null);
});

test('parseEndpoint：形狀多一段（YYYY-M-D）→ null', () => {
    assert.equal(parseEndpoint('2023-9-1'), null);
    assert.equal(parseEndpoint('2023-09-09'), null);
});

test('parseEndpoint：月份段空（"2023-"）→ null', () => {
    assert.equal(parseEndpoint('2023-'), null);
});

test('parseEndpoint：非字串（number/null/undefined/object）→ null（型別防禦）', () => {
    assert.equal(parseEndpoint(2023), null);
    assert.equal(parseEndpoint(null), null);
    assert.equal(parseEndpoint(undefined), null);
    assert.equal(parseEndpoint({}), null);
});

test('parseEndpoint：只給月份形狀的畸形 token（與 T2 的「有月無年」邊界分工，見 card 文末落差記錄）', () => {
    // parseEndpoint 永遠收到已經拼好的單一 token；「有月無年」的使用者輸入分工在 T2
    // 的 _releaseEndpoint()（讀取年格空、月格有字的情境），本函式只驗形狀。
    assert.equal(parseEndpoint('-09'), null);
    assert.equal(parseEndpoint('09'), null);
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

test('expandPill：parseEndpoint 任一端失敗 → null（= / <= / >= 各一）', () => {
    assert.equal(expandPill({ dim: 'release', op: '=', value: 'garbage' }), null);
    assert.equal(expandPill({ dim: 'release', op: '<=', value: 'garbage' }), null);
    assert.equal(expandPill({ dim: 'release', op: '>=', value: 'garbage' }), null);
});

test('expandPill：range 的 value 或 value2 任一失敗 → null', () => {
    assert.equal(expandPill({ dim: 'release', op: 'range', value: 'garbage', value2: '2023' }), null);
    assert.equal(expandPill({ dim: 'release', op: 'range', value: '2023', value2: 'garbage' }), null);
});

test('expandPill：未知 op（不在四個白名單內）→ null（fail-closed）', () => {
    assert.equal(expandPill({ dim: 'release', op: '!=', value: '2024' }), null);
    assert.equal(expandPill({ dim: 'release', value: '2024' }), null);
});

test('expandPill：lo > hi 的 range 誠實回傳（不對調，對調是 T2 的事）', () => {
    assert.deepEqual(
        expandPill({ dim: 'release', op: 'range', value: '2024-06', value2: '2023-01' }),
        { lo: 202406, hi: 202301 },
    );
});

// ===== matchesReleasePill =====

test('matchesReleasePill：w 為 null → false（fail-closed，不是 fail-open，唯一直接測這條的樁測試）', () => {
    assert.equal(matchesReleasePill({ release_date: '2024-09-09' }, null), false);
});

test('matchesReleasePill：video.release_date 解析不出年月 → false（fail-closed）', () => {
    const w = { lo: 202401, hi: 202412 };
    assert.equal(matchesReleasePill({ release_date: '2015' }, w), false);
    assert.equal(matchesReleasePill({ release_date: null }, w), false);
    assert.equal(matchesReleasePill({}, w), false);
});

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

test('matchesReleasePill：lo > hi 的誠實空集 → 任何 video 皆 false', () => {
    const w = { lo: 202406, hi: 202301 };
    assert.equal(matchesReleasePill({ release_date: '2024-06-01' }, w), false);
    assert.equal(matchesReleasePill({ release_date: '2023-01-01' }, w), false);
});

test('matchesReleasePill：-Infinity 端點對極端小整數仍成立比較', () => {
    const w = { lo: -Infinity, hi: 202412 };
    assert.equal(matchesReleasePill({ release_date: '0001-01-01' }, w), true);
});

test('matchesReleasePill：+Infinity 端點對任何合法 key 皆成立右側比較', () => {
    const w = { lo: 202401, hi: Infinity };
    assert.equal(matchesReleasePill({ release_date: '9999-12-01' }, w), true);
});

// ===== composeEndpoint =====

test('composeEndpoint：(2023, null) → "2023"（年份不 pad，CD-124a-10）', () => {
    assert.equal(composeEndpoint(2023, null), '2023');
});

test('composeEndpoint：(2023, 9) → "2023-09"（月份 zero-pad 到兩位）', () => {
    assert.equal(composeEndpoint(2023, 9), '2023-09');
});

test('composeEndpoint：(2023, 12) → "2023-12"（已兩位，不變）', () => {
    assert.equal(composeEndpoint(2023, 12), '2023-12');
});

test('composeEndpoint：月份不在 1–12 → null（防禦）', () => {
    assert.equal(composeEndpoint(2023, 0), null);
    assert.equal(composeEndpoint(2023, 13), null);
});

test('composeEndpoint：年份非四位整數 → null（防禦）', () => {
    assert.equal(composeEndpoint(250, null), null);
    assert.equal(composeEndpoint(2, null), null);
});

test('composeEndpoint：年份缺失（null/undefined）→ null（年份是必填端點）', () => {
    assert.equal(composeEndpoint(null, null), null);
    assert.equal(composeEndpoint(undefined, undefined), null);
});

// ===== videoYearRange =====

test('videoYearRange：空陣列 → null', () => {
    assert.equal(videoYearRange([]), null);
});

test('videoYearRange：非陣列 → null', () => {
    assert.equal(videoYearRange(undefined), null);
    assert.equal(videoYearRange(null), null);
});

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
