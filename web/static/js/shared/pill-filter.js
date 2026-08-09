/**
 * pill-filter.js — metadata pill 正規化純函式（TASK-115-T1）
 *
 * 純函式模組，不是 Alpine state factory，不參與 main.js 的 mergeState() 合併鏈。
 * 因此不落入 plan T1「不得新增 state factory 模組」的禁令（該禁令針對會插進
 * mergeState 合併順序、可能撞 FE-ALPINE-05 覆蓋風險的模組）。
 *
 * T2 會把比對用的 predicate 加進同一個檔案。
 */

export function normalizePillValue(s) {
    if (s === null || s === undefined) return '';
    return String(s).trim().normalize('NFKC').toLowerCase();
}
