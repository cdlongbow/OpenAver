// TASK-141b-T9: wishlist-aging.js 純函式契約（spec-141 F9，CD-5/CD-6/CD-7）。
// 全部零 import 的純函式（不 import 任何模組之外的東西），不需要 globalThis.window
// stub、不需要 resolve hook（無跨目錄 `@/` import）。比照 shared/__tests__/release-window.test.mjs
// 的零 stub 範本。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    classifyWishlistAging,
    ageDaysOf,
    WISHLIST_AGING_THRESHOLD_DAYS,
} from '../wishlist-aging.js';

// [branch review P3-7] CD-5：門檻只在定義處出現一次，測試由常數推導邊界。
const { STAGE1, STAGE2 } = WISHLIST_AGING_THRESHOLD_DAYS;

// 固定基準時刻（不依賴真實 wall-clock，CD-6 可注入的意義所在）
const NOW_MS = Date.UTC(2026, 8, 3, 12, 0, 0); // 2026-09-03T12:00:00Z

function pad(n) { return String(n).padStart(2, '0'); }

function daysAgoStr(days) {
    const d = new Date(NOW_MS - days * 86400000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

function daysAheadDateStr(days) {
    const d = new Date(NOW_MS + days * 86400000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

// ===== DoD 1：六種邊界 =====

test('T9-DoD1-recent-created-not-aged: 3 天前、發售日過去 → 0', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(3), '2020-01-01', NOW_MS), 0);
});

test('T9-DoD1-lower-boundary-13-days-not-aged: 第 1 階門檻前一天 → 0', () => {
    // [branch review P3-7] CD-5 的目的是「改一個常數就能調門檻」——邊界一律由常數推出，
    // 不抄字面 14/30，否則改門檻會讓 5 支測試同時假性轉紅、得逐支手改。
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE1 - 1), '', NOW_MS), 0);
});

test('T9-DoD1-stage1-upper-boundary-14-days: 第 1 階門檻當天 → 1', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE1), '', NOW_MS), 1);
});

test('T9-DoD1-stage1-29-days: 第 2 階門檻前一天 → 1', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE2 - 1), '', NOW_MS), 1);
});

test('T9-DoD1-stage2-30-days-no-release-date: 第 2 階門檻當天、release_date 空字串 → 2（沒有發售日照常計齡）', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE2), '', NOW_MS), 2);
});

test('T9-DoD1-future-release-overrides-aging: 60 天前、發售日未來 → 0（未發售例外壓過計齡）', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(60), daysAheadDateStr(10), NOW_MS), 0);
});

test('T9-DoD1-now-accepts-Date-instance: now 可傳 Date 物件而非純數字', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE1), '', new Date(NOW_MS)), 1);
});

test('T9-DoD1-thresholds-are-named-constants: 具名常數值可被 import 斷言', () => {
    assert.equal(WISHLIST_AGING_THRESHOLD_DAYS.STAGE1, 14);
    assert.equal(WISHLIST_AGING_THRESHOLD_DAYS.STAGE2, 30);
    assert.ok(Object.isFrozen(WISHLIST_AGING_THRESHOLD_DAYS));
});

// ===== DoD 2：畸形輸入 fail-closed =====

test('T9-DoD3-empty-string-created-at-no-throw', () => {
    assert.doesNotThrow(() => classifyWishlistAging('', '', NOW_MS));
    assert.equal(classifyWishlistAging('', '', NOW_MS), 0);
});

test('T9-DoD3-non-date-format-created-at-fail-closed', () => {
    assert.doesNotThrow(() => classifyWishlistAging('not-a-date', '', NOW_MS));
    assert.equal(classifyWishlistAging('not-a-date', '', NOW_MS), 0);
});

test('T9-DoD3-null-created-at-no-throw', () => {
    assert.doesNotThrow(() => classifyWishlistAging(null, '', NOW_MS));
    assert.equal(classifyWishlistAging(null, '', NOW_MS), 0);
});

test('T9-DoD3-undefined-created-at-no-throw', () => {
    assert.doesNotThrow(() => classifyWishlistAging(undefined, undefined, NOW_MS));
    assert.equal(classifyWishlistAging(undefined, undefined, NOW_MS), 0);
});

test('T9-DoD3-malformed-release-date-does-not-throw-and-falls-back-to-age', () => {
    // release_date 畸形 → 視同無有效未來發售日，落回計齡路徑，不拋錯
    assert.doesNotThrow(() => classifyWishlistAging(daysAgoStr(60), 'not-a-date', NOW_MS));
    assert.equal(classifyWishlistAging(daysAgoStr(60), 'not-a-date', NOW_MS), 2);
});

test('T9-DoD3-ageDaysOf-malformed-returns-null', () => {
    assert.equal(ageDaysOf('', NOW_MS), null);
    assert.equal(ageDaysOf('garbage', NOW_MS), null);
    assert.equal(ageDaysOf(null, NOW_MS), null);
});

test('T9-DoD3-ageDaysOf-valid-returns-number', () => {
    assert.equal(ageDaysOf(daysAgoStr(STAGE1), NOW_MS), STAGE1);
});
