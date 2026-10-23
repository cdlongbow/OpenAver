/**
 * binding-guard-config.mjs — 模板綁定守衛的具名表（plan-179 CD-179-4／-8）
 * 只放資料與純函式。每張表的每一項都附「為什麼收它」；過期偵測見 findStaleEntries。
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/** CD-179-4：值是運算式的指令（x-data／x-for 由 binding-scope 特殊處理） */
export const EXPR_DIRECTIVES = new Set([
  'on', 'bind', 'text', 'html', 'show', 'if', 'model', 'modelable', 'init', 'effect', 'id',
  'trap', 'anchor', 'intersect', 'data', 'for',
]);
/** CD-179-4：值不是運算式的指令。其餘 x-* 一律未登記 ＝ 工具錯誤（exit 2） */
export const NOEXPR_DIRECTIVES = new Set([
  'ref', 'cloak', 'ignore', 'teleport', 'transition', 'collapse',
]);

/** CD-179-8(1)：Alpine 魔法名（執行期由 Alpine 注入，不在任何 x-data 內） */
export const MAGIC_NAMES = {
  $el: 'Alpine magic：目前元素',
  $refs: 'Alpine magic：x-ref 登記表',
  $store: 'Alpine magic：Alpine.store',
  $watch: 'Alpine magic：監看',
  $dispatch: 'Alpine magic：派發事件',
  $nextTick: 'Alpine magic：下一個 tick',
  $event: 'Alpine magic：事件物件（x-on 內）',
  $root: 'Alpine magic：最近的 x-data 根',
  $data: 'Alpine magic：目前 scope 資料',
  $id: 'Alpine magic：唯一 id',
  $persist: 'Alpine plugin：持久化',
  $focus: 'Alpine plugin：焦點管理',
  $anchor: 'Alpine plugin：錨定',
};

/**
 * CD-179-8(2)：模板實際裸用的瀏覽器全域，恰 13 個（T1 §(8) 實測）。值＝首次使用處 檔:行。
 * 明確不收 close open stop focus print name status find top parent length：
 * 這些是 window 的屬性但極易與狀態 key 打錯字重疊，收了會讓懸空名字靜默放行。
 */
export const BROWSER_GLOBALS = {
  window: 'base.html:491',
  encodeURIComponent: 'search.html:40',
  Boolean: 'search.html:187',
  undefined: 'scanner.html:477',
  Math: 'insights.html:317',
  clearInterval: 'base.html:529',
  setInterval: 'base.html:520',
  fetch: 'base.html:534',
  document: 'base.html:6',
  location: 'base.html:704',
  Array: 'base.html:548',
  Date: 'base.html:574',
  Number: 'insights.html:146',
};

/**
 * CD-179-8(3)：模板裸用、由 JS 模組／頁面 script 掛到 window 的名字（base.html 內嵌 script 推導不到）。
 * 過期偵測＝指定檔內仍有 `window.<名> =`。
 */
export const EXTRA_WINDOW_GLOBALS = {
  GhostFly: {
    file: 'web/static/js/shared/ghost-fly.js',
    line: 1364,
    why: 'ghost-fly.js:1364 指定 window.GhostFly；search.html:1000／showcase.html:500 以 `window.GhostFly && GhostFly.floatingHearts($el)` 裸用',
  },
  toggleThemeWithTransition: {
    file: 'web/static/js/pages/settings/theme-transition.js',
    line: 44,
    why: 'theme-transition.js:44 指定 window.toggleThemeWithTransition；settings.html:183 @click 裸用',
  },
};

/**
 * 過期偵測。回傳 [訊息]（空陣列＝沒過期）。
 * usedBrowser：本次掃描中解析為瀏覽器全域的名字集合；root：repo 根。
 */
export function findStaleEntries(usedBrowser, root) {
  const stale = [];
  for (const n of Object.keys(BROWSER_GLOBALS)) {
    if (!usedBrowser.has(n)) stale.push(`表內條目已過期：BROWSER_GLOBALS.${n}（掃描中從未被引用）`);
  }
  for (const [n, x] of Object.entries(EXTRA_WINDOW_GLOBALS)) {
    let src = null;
    try { src = readFileSync(join(root, x.file), 'utf8'); } catch { /* 缺檔＝過期 */ }
    if (src === null || !new RegExp(`window\\.${n}\\s*=`).test(src)) {
      stale.push(`表內條目已過期：EXTRA_WINDOW_GLOBALS.${n}（${x.file} 已不含 window.${n} =）`);
    }
  }
  return stale;
}
