/**
 * batch-search-rules.js — 批次搜尋的純函式規則（TASK-182）。
 * 純函式、零 window／DOM 依賴、無 module 級可變狀態。
 */

/**
 * isFileSearching(activePaths, path) → boolean
 * 該片是否正在批次搜尋中（路徑在 activePaths 內）。比對字串，不比物件身分（FE-ALPINE-14）。
 */
export function isFileSearching(activePaths, path) {
    return Array.isArray(activePaths) && activePaths.includes(path);
}
