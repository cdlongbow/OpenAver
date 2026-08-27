#!/usr/bin/env node
/**
 * state_key_guard.mjs — Alpine mergeState 跨貢獻者撞名守衛（plan-131a T2）
 *
 * 依 T1 的 alpine-state.mjs 解析核心所得之頁面狀態貢獻者資訊，判定：
 * 同一頁裡，來自不同 merge 貢獻者的宣告使用了同名頂層 key ⇒ RED。
 *
 * 訊息點名：
 * - 哪些來源（分片檔路徑:行號 或 inline 來源 main.js:行號）
 * - 哪個 key
 * - 哪一份生效（由 order 決定，order 最大者生效）
 * - 處置建議
 *
 * exit code：
 * - 0: 乾淨（零撞名）
 * - 1: 有撞名或解析失敗（AlpineStateError / fail-closed）
 *
 * 用法：
 *   node scripts/state_key_guard.mjs                # 掃真 repo
 *   node scripts/state_key_guard.mjs <scratch-root>  # 掃指定 root（供測試 / mutation 自驗）
 */

import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { collectPages } from './lib/alpine-state.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const argv2 = process.argv[2];
const ROOT = argv2 && !argv2.startsWith('--') ? resolve(argv2) : join(__dirname, '..');

function main() {
  let pages;
  try {
    pages = collectPages(ROOT);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`✗ state_key_guard: ${msg}`);
    process.exit(1);
  }

  let hadError = false;
  const pageSummaries = [];

  for (const page of pages) {
    /** @type {Map<string, Array<{ contributor: import('./lib/alpine-state.mjs').Contributor, line: number }>>} */
    const keyMap = new Map();
    const uniqueKeys = new Set();

    for (const c of page.contributors) {
      for (const [keyName, info] of c.keys.entries()) {
        uniqueKeys.add(keyName);
        let list = keyMap.get(keyName);
        if (!list) {
          list = [];
          keyMap.set(keyName, list);
        }
        list.push({ contributor: c, line: info.line });
      }
    }

    pageSummaries.push(`${page.page} ${page.contributors.length}/${uniqueKeys.size}`);

    /** @type {Array<{ key: string, occurrences: Array<{ contributor: import('./lib/alpine-state.mjs').Contributor, line: number, loc: string }>, maxOrder: number }>} */
    const collisions = [];

    for (const [keyName, list] of keyMap.entries()) {
      if (list.length > 1) {
        let maxOrder = -Infinity;
        const occurrences = list.map((item) => {
          if (item.contributor.order > maxOrder) {
            maxOrder = item.contributor.order;
          }
          // 兩種貢獻者都印「**那個 key 自己的宣告行**」，不是貢獻者的起始行。
          // inline 的 source 形如 `…/search/main.js:27`（27 ＝ 現場物件的 `{` 那行），
          // 直接印它會讓每個 key 都指向同一行——而 search 頁最可能發生的撞名正是
          // `init`（宣告在 :64，Alpine 頁面幾乎都有這個 method），指到 :27 只會讓
          // 讀訊息的人開錯地方。剝掉尾端的 `:<line>` 取回檔案路徑再接上 key 的行號。
          const file = item.contributor.kind === 'inline'
            ? item.contributor.source.replace(/:\d+$/, '')
            : item.contributor.source;
          const loc = `${file}:${item.line}`;
          return {
            contributor: item.contributor,
            line: item.line,
            loc,
          };
        });

        // 依 order 排序（從小到大）
        occurrences.sort((a, b) => a.contributor.order - b.contributor.order);

        collisions.push({
          key: keyName,
          occurrences,
          maxOrder,
        });
      }
    }

    if (collisions.length > 0) {
      hadError = true;
      console.error(`✗ state_key_guard: ${page.page} 頁跨貢獻者撞名 ${collisions.length} 個\n`);
      for (const col of collisions) {
        console.error(`  ${col.key}`);
        for (const occ of col.occurrences) {
          const isWinner = occ.contributor.order === col.maxOrder;
          const suffix = isWinner ? '      ← 合併順序在後，這份生效' : '';
          console.error(`    ${occ.loc}${suffix}`);
        }
      }
      console.error('  → mergeState 後者無聲覆蓋前者。刪掉不生效的那份，或改名。');
    }
  }

  if (hadError) {
    process.exit(1);
  }

  console.log(`✓ state_key_guard: 頂層狀態零跨貢獻者撞名（${pageSummaries.join('、')}）`);
}

main();
