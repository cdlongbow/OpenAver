#!/usr/bin/env node
/**
 * state_map.mjs — Alpine mergeState 狀態地圖產生器（plan-131a T6）
 *
 * 複用 T1 的 alpine-state.mjs 解析核心，收集每個 merge 貢獻者內的 `this.<name>`，
 * 計算各貢獻者之間的伸手依賴矩陣（誰擁有什麼 key、誰在讀誰的 key），
 * 印成 Markdown 到 stdout。隨叫隨用，不落檔、不設 drift 閘（CD-9）。
 *
 * 用法：
 *   node scripts/state_map.mjs                # 掃真 repo
 *   node scripts/state_map.mjs <scratch-root>  # 掃指定 root
 */

import { readFileSync } from 'node:fs';
import { dirname, join, resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'espree';
import {
  collectPages, loadImportMap, findMergeStateLocalNames, findMergeStateCalls,
  walk, findNamedFactory,
} from './lib/alpine-state.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const argv2 = process.argv[2];
const ROOT = argv2 && !argv2.startsWith('--') ? resolve(argv2) : join(__dirname, '..');

const PARSE_OPTS = { ecmaVersion: 2024, sourceType: 'module', loc: true };


// findMergeStateCalls 已改由 ./lib/alpine-state.mjs 提供（吃 local 綁定名集合）。
// 這裡原本有一份逐字相同、硬編字面 'mergeState' 的副本——頁面一旦用 alias
// （`import { mergeState as composeState }`）它就找不到呼叫、`return new Set()`，
// 於是該 inline 貢獻者那一列的伸手矩陣**靜默全印成 `·`**：不報錯、不提示，
// 是一筆看起來正常但錯誤的資料。刪掉副本，與守衛共用同一份實作。
//
// walk / findNamedFactory 同理，於 Codex PR#161 review 第 2 輪一併收斂（**同一個病第二次發作**）：
// 第 1 輪把 alpine-state.mjs 的 findNamedFactory 補上 export list 支援後，這裡的逐字副本沒跟著改，
// 於是 `function f(){}; export { f };` 形的貢獻者變成「守衛過得了、地圖印成全 `·`」——
// exit 0、stderr 全空、數字看起來完全正常。**這正是「重複實作」的失效形狀：不是兩邊都錯，是兩邊分岔。**
// 依 CLAUDE.md 停損規則（下一輪 finding 由上一輪的修正造成 → 停止 fix-forward、改窮舉盤點），
// 窮舉結果：兩支腳本只重複這 2 個函式、無第三份，且當初沒共用不是設計判斷而是 alpine-state.mjs 沒 export。

/**
 * 收集 node 整棵子樹內的 `this.<name>`
 * @param {any} node
 * @returns {Set<string>}
 */
function collectThisReads(node) {
  const reads = new Set();
  walk(node, (n) => {
    if (
      n.type === 'MemberExpression'
      && !n.computed
      && n.object
      && n.object.type === 'ThisExpression'
      && n.property
      && n.property.type === 'Identifier'
    ) {
      reads.add(n.property.name);
    }
  });
  return reads;
}

/**
 * 貢獻者短名
 * @param {import('./lib/alpine-state.mjs').Contributor} c
 * @returns {string}
 */
function contributorShortName(c) {
  if (c.kind === 'inline') {
    const match = c.source.match(/([^/]+:\d+)$/);
    return match ? match[1] : c.source;
  }
  const base = basename(c.source, '.js');
  if (base.startsWith('state-')) return base.slice('state-'.length);
  if (base.startsWith('search-')) return base.slice('search-'.length);
  return base;
}

/**
 * @param {string} root
 * @param {import('./lib/alpine-state.mjs').PageInfo} page
 * @param {import('./lib/alpine-state.mjs').Contributor} contributor
 * @param {Map<string, import('estree').Program>} astCache
 * @returns {Set<string>}
 */
function getContributorReads(root, page, contributor, astCache, importMap) {
  if (contributor.kind === 'factory') {
    const absPath = resolve(root, contributor.source);
    let ast = astCache.get(absPath);
    if (!ast) {
      const code = readFileSync(absPath, 'utf8');
      ast = parse(code, PARSE_OPTS);
      astCache.set(absPath, ast);
    }
    const factory = findNamedFactory(ast, contributor.factoryName);
    if (!factory) return new Set();
    return collectThisReads(factory);
  }

  if (contributor.kind === 'inline') {
    const entryAbs = resolve(root, page.entry);
    let ast = astCache.get(entryAbs);
    if (!ast) {
      const code = readFileSync(entryAbs, 'utf8');
      ast = parse(code, PARSE_OPTS);
      astCache.set(entryAbs, ast);
    }
    // 吃 local 綁定名，才認得 `import { mergeState as composeState }` 的 alias 頁；
    // 硬編字面 'mergeState' 會在那種頁面靜默回空集合、把整列印成 `·`。
    const mergeCalls = findMergeStateCalls(ast, findMergeStateLocalNames(ast, importMap));
    if (mergeCalls.length === 0) return new Set();
    const arg = mergeCalls[0].arguments[contributor.order];
    if (!arg) return new Set();
    return collectThisReads(arg);
  }

  return new Set();
}

function main() {
  let pages;
  try {
    pages = collectPages(ROOT);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`✗ state_map: ${msg}`);
    process.exit(1);
  }

  // 與 collectPages 讀同一份 importmap（CD-3：現場解析，不抄第二份）
  const importMap = loadImportMap(ROOT);

  /** @type {Map<string, import('estree').Program>} */
  const astCache = new Map();
  const outputs = [];

  for (const page of pages) {
    const contributors = page.contributors;
    const n = contributors.length;
    const shortNames = contributors.map(contributorShortName);

    // key -> 生效擁有者（order 最大的 contributor，last-wins）
    /** @type {Map<string, import('./lib/alpine-state.mjs').Contributor>} */
    const effectiveOwnerMap = new Map();
    for (const c of contributors) {
      for (const key of c.keys.keys()) {
        const prev = effectiveOwnerMap.get(key);
        if (!prev || c.order > prev.order) {
          effectiveOwnerMap.set(key, c);
        }
      }
    }

    // 收集各 contributor 的 this.<name> 讀取
    const contributorReads = contributors.map((c) =>
      getContributorReads(ROOT, page, c, astCache, importMap)
    );

    // 建構 dependency matrix: cell[reader][owner]
    const matrix = Array.from({ length: n }, () => Array(n).fill(0));
    const ownCounts = Array(n).fill(0);
    const extCounts = Array(n).fill(0);

    for (let rIdx = 0; rIdx < n; rIdx++) {
      const reads = contributorReads[rIdx];
      for (const readKey of reads) {
        const owner = effectiveOwnerMap.get(readKey);
        if (!owner) {
          // 不屬於任何貢獻者的 key（Alpine magic 等）不計入矩陣，亦不算進外求
          continue;
        }
        const oIdx = owner.order;
        matrix[rIdx][oIdx]++;
      }
      ownCounts[rIdx] = matrix[rIdx][rIdx];
      let ext = 0;
      for (let oIdx = 0; oIdx < n; oIdx++) {
        if (oIdx !== rIdx) {
          ext += matrix[rIdx][oIdx];
        }
      }
      extCounts[rIdx] = ext;
    }

    const sectionLines = [];
    sectionLines.push(`## ${page.page} (${n} 貢獻者 / ${effectiveOwnerMap.size} keys)`);
    sectionLines.push('');
    sectionLines.push('### 伸手矩陣');
    sectionLines.push('');

    // 表格 Header
    const headerCols = ['reader', ...shortNames, '自有', '外求'];
    sectionLines.push(`| ${headerCols.join(' | ')} |`);
    sectionLines.push(`| ${headerCols.map(() => '---').join(' | ')} |`);

    // 表格 Rows
    for (let rIdx = 0; rIdx < n; rIdx++) {
      const rowCols = [
        shortNames[rIdx],
        ...matrix[rIdx].map((v) => (v === 0 ? '·' : String(v))),
        String(ownCounts[rIdx]),
        String(extCounts[rIdx]),
      ];
      sectionLines.push(`| ${rowCols.join(' | ')} |`);
    }

    sectionLines.push('');
    sectionLines.push('### key → 擁有者 → 被誰讀');
    sectionLines.push('');

    const sortedKeys = Array.from(effectiveOwnerMap.keys()).sort();
    for (const key of sortedKeys) {
      const owner = effectiveOwnerMap.get(key);
      const ownerName = contributorShortName(owner);
      const readers = [];
      for (let rIdx = 0; rIdx < n; rIdx++) {
        if (contributorReads[rIdx].has(key)) {
          readers.push(shortNames[rIdx]);
        }
      }
      const readerText = readers.length > 0 ? readers.join(', ') : '·';
      sectionLines.push(`- \`${key}\`: \`${ownerName}\` → ${readerText}`);
    }

    outputs.push(sectionLines.join('\n'));
  }

  console.log(outputs.join('\n\n'));
}

main();
