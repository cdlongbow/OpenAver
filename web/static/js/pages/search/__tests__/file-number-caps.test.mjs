// TASK-caps: 番號字母 cap 對齊守衛（5/6 → 7），修復 7 字母前綴（PARATHD）
// 被 re.search-like 滑窗截斷掉首字的 bug。
//
// file.js 是 classic script（掛到 window.SearchFile），非 ES module——
// stub window 後動態 import 觸發頂層副作用（見 TASK-caps.md「前端 node:test 選擇理由」）。
// 對 production 原始碼零侵入：只改 regex cap 本身，不改匯出方式。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
await import('../file.js');
const { extractChineseTitle } = globalThis.window.SearchFile;

// === 必須新 PASS：extractChineseTitle 不殘留 7 字母番號碎片 ===

test('extractChineseTitle: 7 字母番號靠通用 cleanup 完整剝除（number 不匹配）', () => {
  // number=ABC-999 故意不匹配 PARATHD-02976 → 必須靠 file.js:115 的通用 {2,7} regex 剝除。
  // 若 number 傳 'PARATHD-02976'，exact-number 移除（file.js:112-114）會先吃掉它，
  // 就算 :115 回歸到 {2,6} 也照樣 green —— cap 未被鎖。故意用不匹配的 number。
  // cap={2,7} → '純中文標題'；cap={2,6}（回歸）→ 只吃 'ARATHD-02976'、殘留首字 'P' → 'P純中文標題'。
  const result = extractChineseTitle('PARATHD-02976 純中文標題.mp4', 'ABC-999');
  assert.equal(result, '純中文標題');
});

