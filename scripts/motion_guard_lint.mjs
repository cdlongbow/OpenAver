#!/usr/bin/env node
/**
 * motion_guard_lint.mjs — 「永不停止的動畫」白名單守衛（TASK-133a-T4 / CD-133a-6）
 *
 * 檢查所有 CSS 與 JS 中的永續無限動畫：
 *  - CSS：掃描 web/static/css/ 所有 .css 檔（排除 generated 的 tailwind.css），
 *         尋找 animation 縮寫或 animation-iteration-count 中的 infinite
 *  - JS： 掃描 web/static/js/ 所有 .js 檔（排除 vendor/），
 *         透過 espree AST 尋找 repeat: -1 物件屬性宣告
 *
 * 雙向對帳：
 *  - 磁碟多出未登記項目 → RED（MG-CSS-01 / MG-JS-01）
 *  - 筆數不符 → RED
 *  - 白名單有殘留條目但檔案內已無相符宣告 → RED
 *
 * 用法：
 *   node scripts/motion_guard_lint.mjs                # 掃真 repo
 *   node scripts/motion_guard_lint.mjs <scratch-root>  # 掃指定 root（供測試 / mutation 自驗）
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'espree';

const __dirname = dirname(fileURLToPath(import.meta.url));
const argv2 = process.argv[2];
const ROOT = argv2 && !argv2.startsWith('--') ? resolve(argv2) : join(__dirname, '..');

// ============================================================================
// 白名單定義（2026-08-28 盤點：CSS 10 條 14 處，JS 5 條 6 處）
// ============================================================================

const CSS_ALLOW = [
  {
    file: 'web/static/css/components/rotating-border.css',
    name: 'rotate-spotlight',
    count: 1,
    why: '搜尋頁結果卡的常駐「本地已有」狀態指示（spec §4 不碰搜尋頁）；側欄那顆已於 T3 改成一圈就停，但這條規則本身仍是 infinite，因為它是跨頁共用的',
  },
  {
    file: 'web/static/css/components/source-pill.css',
    name: 'source-pill-spin',
    count: 3,
    why: '來源查詢中的載入指示器（短命載入態）',
  },
  {
    file: 'web/static/css/pages/design-system.css',
    name: 'ds-float',
    count: 2,
    why: '元件展示頁的裝飾動畫（不是產品畫面）',
  },
  {
    file: 'web/static/css/pages/design-system.css',
    name: 'spin',
    count: 1,
    why: '展示頁載入指示器',
  },
  {
    file: 'web/static/css/pages/search.css',
    name: 'spin',
    count: 1,
    why: '載入指示器',
  },
  {
    file: 'web/static/css/pages/search.css',
    name: 'shimmer',
    count: 1,
    why: '骨架微光（載入態，由 x-show 收掉）',
  },
  {
    file: 'web/static/css/pages/showcase.css',
    name: 'spin',
    count: 2,
    why: '載入指示器',
  },
  {
    file: 'web/static/css/pages/showcase.css',
    name: 'dust-twinkle',
    count: 1,
    why: '相似探索的星塵（spec §5.1 owner 拍板結案不追）',
  },
  {
    file: 'web/static/css/pages/showcase.css',
    name: 'shimmer',
    count: 1,
    why: '骨架微光',
  },
  {
    file: 'web/static/css/theme.css',
    name: 'spin',
    count: 1,
    why: '全站載入指示器',
  },
];

const JS_ALLOW = [
  {
    file: 'web/static/js/pages/motion-lab/constellation-host.js',
    count: 1,
    why: 'motion-lab 展示頁',
  },
  {
    file: 'web/static/js/pages/showcase/state-similar.js',
    count: 1,
    why: '相似探索星塵（同 spec §5.1）',
  },
  {
    file: 'web/static/js/shared/burst-picker.js',
    count: 1,
    why: '精選灌滿的火花',
  },
  {
    file: 'web/static/js/shared/constellation/breathing.js',
    count: 2,
    why: '星座呼吸效果',
  },
  {
    file: 'web/static/js/shared/ghost-fly.js',
    count: 1,
    why: 'focalDetectWait 等待指示（有 caller 明確 start/stop）',
  },
];

// ============================================================================
// CSS 解析與掃描
// ============================================================================

// CSS 註解剝除（移植自 scripts/css-guard.mjs:38-40，保留換行使行號與原檔一致）
function stripCssComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\r\n]/g, ' '));
}

const CSS_ANIMATION_KEYWORDS = new Set([
  'infinite',
  'linear', 'ease', 'ease-in', 'ease-out', 'ease-in-out', 'step-start', 'step-end',
  'normal', 'reverse', 'alternate', 'alternate-reverse',
  'none', 'forwards', 'backwards', 'both',
  'running', 'paused',
  'inherit', 'initial', 'unset', 'revert', 'revert-layer',
  '!important', 'important',
]);

function isAnimationNameToken(token) {
  const lower = token.toLowerCase();
  if (CSS_ANIMATION_KEYWORDS.has(lower)) return false;
  // numbers, durations e.g. 1s, 2.5s, 600ms, 0s, 0, .5s
  if (/^[+-]?(\d+(\.\d*)?|\.\d+)(s|ms)?$/i.test(lower)) return false;
  // function calls e.g. var(...), calc(...), steps(...), cubic-bezier(...)
  if (/^[a-zA-Z_-][a-zA-Z0-9_-]*\(.*\)$/.test(token)) return false;
  return true;
}

function splitCommaList(str) {
  const parts = [];
  let depth = 0;
  let current = '';
  for (let i = 0; i < str.length; i += 1) {
    const ch = str[i];
    if (ch === '(') {
      depth += 1;
      current += ch;
    } else if (ch === ')') {
      depth = Math.max(0, depth - 1);
      current += ch;
    } else if (ch === ',' && depth === 0) {
      if (current.trim()) parts.push(current.trim());
      current = '';
    } else {
      current += ch;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

function tokenizeAnimationValue(val) {
  const tokens = [];
  let depth = 0;
  let current = '';
  for (let i = 0; i < val.length; i += 1) {
    const ch = val[i];
    if (ch === '(') {
      depth += 1;
      current += ch;
    } else if (ch === ')') {
      depth = Math.max(0, depth - 1);
      current += ch;
    } else if (/\s/.test(ch) && depth === 0) {
      if (current.trim()) tokens.push(current.trim());
      current = '';
    } else {
      current += ch;
    }
  }
  if (current.trim()) tokens.push(current.trim());
  return tokens;
}

function scanCssFile(filePath, relPath) {
  const raw = readFileSync(filePath, 'utf8');
  const text = stripCssComments(raw);
  const regex = /(?:^|[;{}])\s*(animation(?:-iteration-count)?)\s*:\s*([^;{}]+)/g;
  const results = [];
  let m;
  while ((m = regex.exec(text)) !== null) {
    const prop = m[1];
    const fullVal = m[2].trim();
    const propOffset = m.index + m[0].indexOf(prop);
    const line = text.slice(0, propOffset).split('\n').length;
    const parts = splitCommaList(fullVal);
    for (const part of parts) {
      const tokens = tokenizeAnimationValue(part);
      const isInf = tokens.some((t) => t.toLowerCase() === 'infinite');
      if (isInf) {
        const animName = prop === 'animation-iteration-count'
          ? ''
          : (tokens.find(isAnimationNameToken) || '');
        results.push({ file: relPath, name: animName, line });
      }
    }
  }
  return results;
}

function walkCssFiles(dir, base, list = []) {
  if (!existsSync(dir)) return list;
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name);
    const rel = `${base}/${ent.name}`;
    if (ent.isDirectory()) {
      walkCssFiles(full, rel, list);
    } else if (ent.isFile() && ent.name.endsWith('.css')) {
      if (rel !== 'web/static/css/tailwind.css') {
        list.push({ full, rel });
      }
    }
  }
  return list;
}

// ============================================================================
// JS 解析與掃描（espree AST）
// ============================================================================

const PARSE_OPTS = { ecmaVersion: 2024, sourceType: 'module', loc: true };

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  visit(node);
  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'range') continue;
    const child = node[key];
    if (Array.isArray(child)) {
      for (const c of child) walk(c, visit);
    } else if (child && typeof child === 'object' && child.type) {
      walk(child, visit);
    }
  }
}

function isMinusOne(node) {
  if (!node) return false;
  if (node.type === 'Literal' && node.value === -1) return true;
  if (
    node.type === 'UnaryExpression'
    && node.operator === '-'
    && node.prefix
    && node.argument
    && node.argument.type === 'Literal'
    && node.argument.value === 1
  ) {
    return true;
  }
  return false;
}

function isRepeatKey(keyNode, computed) {
  if (computed) return false;
  if (!keyNode) return false;
  if (keyNode.type === 'Identifier' && keyNode.name === 'repeat') return true;
  if (keyNode.type === 'Literal' && keyNode.value === 'repeat') return true;
  return false;
}

function scanJsFile(filePath, relPath) {
  const code = readFileSync(filePath, 'utf8');
  let ast;
  try {
    ast = parse(code, PARSE_OPTS);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`espree failed to parse ${relPath}: ${msg}`);
  }
  const results = [];
  walk(ast, (node) => {
    if (node.type === 'Property' && isRepeatKey(node.key, node.computed) && isMinusOne(node.value)) {
      results.push({ file: relPath, line: node.loc ? node.loc.start.line : 0 });
    }
  });
  return results;
}

function walkJsFiles(dir, base, list = []) {
  if (!existsSync(dir)) return list;
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name);
    const rel = `${base}/${ent.name}`;
    if (ent.isDirectory()) {
      if (rel !== 'web/static/js/vendor') {
        walkJsFiles(full, rel, list);
      }
    } else if (ent.isFile() && ent.name.endsWith('.js')) {
      list.push({ full, rel });
    }
  }
  return list;
}

// ============================================================================
// 主流程與對帳
// ============================================================================

function main() {
  let hadError = false;
  function reportError(prefix, msg) {
    console.error(`✗ ${prefix}: ${msg}`);
    hadError = true;
  }

  // 1. 掃描 CSS
  const cssDir = join(ROOT, 'web', 'static', 'css');
  const cssFiles = walkCssFiles(cssDir, 'web/static/css');
  const scannedCss = [];
  for (const { full, rel } of cssFiles) {
    try {
      const items = scanCssFile(full, rel);
      scannedCss.push(...items);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      reportError('MG-CSS-01', `讀取/解析 ${rel} 失敗：${msg}`);
    }
  }

  // CSS 依 `${file}:::${name}` 分組
  const cssGroups = new Map();
  for (const item of scannedCss) {
    const key = `${item.file}:::${item.name}`;
    let group = cssGroups.get(key);
    if (!group) {
      group = { file: item.file, name: item.name, lines: [] };
      cssGroups.set(key, group);
    }
    group.lines.push(item.line);
  }

  // CSS 掃描結果與白名單比對
  for (const group of cssGroups.values()) {
    const allow = CSS_ALLOW.find((e) => e.file === group.file && (e.name ?? '') === group.name);
    if (!allow) {
      reportError(
        'MG-CSS-01',
        `未登記的無限 CSS 動畫：${group.file}:${group.lines.join(',')} (${group.name || '<anonymous>'})`,
      );
    } else if (group.lines.length !== allow.count) {
      reportError(
        'MG-CSS-01',
        `${group.file} 的動畫「${group.name}」筆數不符（掃到 ${group.lines.length} 筆，白名單登記 ${allow.count} 筆）。若這是合法的合併或拆分，把 count 改成 ${group.lines.length}`,
      );
    }
  }

  // CSS 白名單殘留檢查
  for (const entry of CSS_ALLOW) {
    const fileAbs = join(ROOT, ...entry.file.split('/'));
    if (existsSync(fileAbs)) {
      const key = `${entry.file}:::${entry.name ?? ''}`;
      const group = cssGroups.get(key);
      if (!group || group.lines.length === 0) {
        reportError('MG-CSS-01', `白名單有殘留條目，請刪掉：${entry.file} (${entry.name || '<anonymous>'})`);
      }
    }
  }

  // 2. 掃描 JS
  const jsDir = join(ROOT, 'web', 'static', 'js');
  const jsFiles = walkJsFiles(jsDir, 'web/static/js');
  const scannedJs = [];
  for (const { full, rel } of jsFiles) {
    try {
      const items = scanJsFile(full, rel);
      scannedJs.push(...items);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      reportError('MG-JS-01', msg);
    }
  }

  // JS 依 file 分組
  const jsGroups = new Map();
  for (const item of scannedJs) {
    let group = jsGroups.get(item.file);
    if (!group) {
      group = { file: item.file, lines: [] };
      jsGroups.set(item.file, group);
    }
    group.lines.push(item.line);
  }

  // JS 掃描結果與白名單比對
  for (const group of jsGroups.values()) {
    const allow = JS_ALLOW.find((e) => e.file === group.file);
    if (!allow) {
      reportError('MG-JS-01', `未登記的 repeat: -1 動畫：${group.file}:${group.lines.join(',')}`);
    } else if (group.lines.length !== allow.count) {
      reportError(
        'MG-JS-01',
        `${group.file} 的 repeat: -1 筆數不符（掃到 ${group.lines.length} 筆，白名單登記 ${allow.count} 筆）。若這是合法的合併或拆分，把 count 改成 ${group.lines.length}`,
      );
    }
  }

  // JS 白名單殘留檢查
  for (const entry of JS_ALLOW) {
    const fileAbs = join(ROOT, ...entry.file.split('/'));
    if (existsSync(fileAbs)) {
      const group = jsGroups.get(entry.file);
      if (!group || group.lines.length === 0) {
        reportError('MG-JS-01', `白名單有殘留條目，請刪掉：${entry.file}`);
      }
    }
  }

  if (hadError) {
    process.exit(1);
  }

  console.log(
    `✓ motion_guard_lint: 無限動畫與 repeat: -1 白名單對帳一致（CSS ${CSS_ALLOW.length} 條 / ${scannedCss.length} 處，JS ${JS_ALLOW.length} 條 / ${scannedJs.length} 處）`,
  );
}

main();
