// TASK-141b-T9: wishlist-aging.js 純函式契約（spec-141 F9，CD-5/CD-6/CD-7）。
// 全部零 import 的純函式（不 import 任何模組之外的東西），不需要 globalThis.window
// stub、不需要 resolve hook（無跨目錄 `@/` import）。比照 shared/__tests__/release-window.test.mjs
// 的零 stub 範本。

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    classifyWishlistAging,
    WISHLIST_AGING_THRESHOLD_DAYS,
} from '../wishlist-aging.js';

// [branch review P3-7] CD-5：門檻只在定義處出現一次，測試由常數推導邊界。
const { STAGE1 } = WISHLIST_AGING_THRESHOLD_DAYS;

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


test('T9-DoD1-lower-boundary-13-days-not-aged: 第 1 階門檻前一天 → 0', () => {
    // [branch review P3-7] CD-5 的目的是「改一個常數就能調門檻」——邊界一律由常數推出，
    // 不抄字面 14/30，否則改門檻會讓 5 支測試同時假性轉紅、得逐支手改。
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE1 - 1), '', NOW_MS), 0);
});

test('T9-DoD1-stage1-upper-boundary-14-days: 第 1 階門檻當天 → 1', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(STAGE1), '', NOW_MS), 1);
});


test('T9-DoD1-future-release-overrides-aging: 60 天前、發售日未來 → 0（未發售例外壓過計齡）', () => {
    assert.equal(classifyWishlistAging(daysAgoStr(60), daysAheadDateStr(10), NOW_MS), 0);
});


// ===== DoD 2：畸形輸入 fail-closed =====


