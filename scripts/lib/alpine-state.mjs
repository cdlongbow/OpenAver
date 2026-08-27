/**
 * alpine-state.mjs — Alpine mergeState 貢獻者解析核心（plan-131a T1）
 *
 * 從四頁 main.js 的 mergeState(...) 呼叫現場解析每個貢獻者的頂層 key。
 * 只回結構，不做撞名判定、不印報告（判定是 T2；地圖是 T6）。
 *
 * fail-closed：任一環節失敗一律 throw AlpineStateError（帶 rule 1–8），
 * 不得靜默略過。由呼叫端（T2／T6）決定怎麼收尾。
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'espree';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = join(__dirname, '../..');

const PARSE_OPTS = { ecmaVersion: 2024, sourceType: 'module', loc: true };

/** 共用 merge 契約的正典位置。來源限定比對這個路徑，不比對 specifier 字面字串。 */
const MERGE_STATE_REL = 'web/static/js/shared/merge-state.js';

const IMPORTMAP_START = '<script type="importmap">';
const IMPORTMAP_END = '</script>';

/** @typedef {'init'|'get'|'set'} KeyKind */
/** @typedef {{ kinds: Set<KeyKind>, line: number }} KeyInfo */
/** @typedef {{
 *   kind: 'factory'|'inline',
 *   source: string,
 *   factoryName: string|null,
 *   order: number,
 *   keys: Map<string, KeyInfo>,
 * }} Contributor */
/** @typedef {{
 *   page: string,
 *   entry: string,
 *   contributors: Contributor[],
 * }} PageInfo */

export class AlpineStateError extends Error {
  /**
   * @param {number} rule fail-closed 條號 1–8
   * @param {string} message
   */
  constructor(rule, message) {
    super(`FAIL_CLOSED_${rule}: ${message}`);
    this.name = 'AlpineStateError';
    this.rule = rule;
  }
}

function relPosix(root, absPath) {
  return relative(root, absPath).split(sep).join('/');
}

function parseModule(code, label) {
  try {
    return parse(code, PARSE_OPTS);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new AlpineStateError(7, `espree failed to parse ${label}: ${detail}`);
  }
}

/**
 * ① base.html 抽 importmap → JSON.parse → 別名表
 * @param {string} root
 * @returns {Record<string, string>}
 */
function loadImportMap(root) {
  const basePath = join(root, 'web/templates/base.html');
  if (!existsSync(basePath)) {
    throw new AlpineStateError(1, `base.html not found at ${relPosix(root, basePath)}`);
  }
  const html = readFileSync(basePath, 'utf8');
  const start = html.indexOf(IMPORTMAP_START);
  if (start < 0) {
    throw new AlpineStateError(1, 'base.html: <script type="importmap"> block not found');
  }
  const contentStart = start + IMPORTMAP_START.length;
  const end = html.indexOf(IMPORTMAP_END, contentStart);
  if (end < 0) {
    throw new AlpineStateError(1, 'base.html: importmap closing </script> not found');
  }
  const raw = html.slice(contentStart, end).trim();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new AlpineStateError(1, `base.html importmap is not valid JSON: ${detail}`);
  }
  if (!parsed || typeof parsed !== 'object' || !parsed.imports || typeof parsed.imports !== 'object') {
    throw new AlpineStateError(1, 'base.html importmap missing "imports" object');
  }
  return /** @type {Record<string, string>} */ (parsed.imports);
}

/**
 * specifier → 磁碟相對路徑（posix），**純字串代換，不碰檔案系統**。
 *
 * 刻意與 `resolveSpecifier()` 分家：那一支會 `existsSync` 並在找不到檔案時
 * throw rule 6，語意是「這個 factory 分片必須真的存在」。本支只回答
 * 「這個 specifier **指向哪裡**」——用在判斷某個 import 是不是來自共用的
 * merge 契約，那件事不需要、也不該要求該檔在掃描目標裡實體存在
 * （合成 fixture 只寫 main.js ＋ 分片檔，從不寫出 shared/merge-state.js）。
 * 把兩者混用會讓全部合成案例集體變成 FAIL_CLOSED_6。
 *
 * @param {Record<string, string>} imports
 * @param {string} specifier
 * @returns {string|null} 相對 root 的 posix 路徑；不吃任何別名時回 null
 */
function specifierToRelPath(imports, specifier) {
  // 最長前綴優先（避免 `@/` 誤吃 `@/shared/`）
  const aliases = Object.keys(imports).sort((a, b) => b.length - a.length);
  for (const alias of aliases) {
    if (!specifier.startsWith(alias)) continue;
    const urlPath = imports[alias];
    if (!urlPath.startsWith('/')) return null;
    return join('web', urlPath.slice(1), specifier.slice(alias.length))
      .split(sep).join('/');
  }
  return null;
}

/**
 * specifier（如 `@/showcase/state-base.js`）→ 磁碟絕對路徑。
 * 別名 value 是網址路徑 `/static/js/...`，磁碟前綴 `web`。
 * @param {string} root
 * @param {Record<string, string>} imports
 * @param {string} specifier
 * @param {string} fromEntry
 */
function resolveSpecifier(root, imports, specifier, fromEntry) {
  // 最長前綴優先（避免 `@/` 誤吃 `@/shared/`）
  const aliases = Object.keys(imports).sort((a, b) => b.length - a.length);
  for (const alias of aliases) {
    if (!specifier.startsWith(alias)) continue;
    const rest = specifier.slice(alias.length);
    const urlPath = imports[alias]; // e.g. /static/js/shared/
    if (!urlPath.startsWith('/')) {
      throw new AlpineStateError(
        6,
        `${fromEntry}: alias ${alias} value is not an absolute URL path: ${urlPath}`,
      );
    }
    const diskRel = join('web', urlPath.slice(1), rest);
    const abs = resolve(root, diskRel);
    if (!existsSync(abs)) {
      throw new AlpineStateError(
        6,
        `${fromEntry}: specifier ${specifier} resolved to missing file ${relPosix(root, abs)}`,
      );
    }
    return abs;
  }
  throw new AlpineStateError(
    6,
    `${fromEntry}: specifier ${specifier} not matched by any importmap alias`,
  );
}

/**
 * @param {import('estree').CallExpression} call
 * @returns {string|null}
 */
function factoryIdentFromCall(call) {
  const callee = call.callee;
  if (callee.type === 'Identifier') return callee.name;
  // stateBase.call(this) → MemberExpression(.call) → object Identifier
  if (
    callee.type === 'MemberExpression'
    && !callee.computed
    && callee.property.type === 'Identifier'
    && callee.property.name === 'call'
    && callee.object.type === 'Identifier'
  ) {
    return callee.object.name;
  }
  return null;
}

/**
 * 建 local 綁定名 → { importedName, specifier } 對照表（只收具名 import）。
 * @param {import('estree').Program} ast
 */
function buildImportBindings(ast) {
  /** @type {Map<string, { importedName: string, specifier: string }>} */
  const map = new Map();
  for (const node of ast.body) {
    if (node.type !== 'ImportDeclaration') continue;
    if (typeof node.source.value !== 'string') continue;
    const specifier = node.source.value;
    for (const spec of node.specifiers) {
      if (spec.type !== 'ImportSpecifier') continue;
      const local = spec.local.name;
      const imported = spec.imported.type === 'Identifier'
        ? spec.imported.name
        : String(spec.imported.value);
      map.set(local, { importedName: imported, specifier });
    }
  }
  return map;
}

/**
 * 收集該檔中「綁到共用 merge 契約」的**本地名稱**。
 *
 * 為什麼回的是 local name 而不是布林：ESM 的 `import { mergeState as composeState }`
 * 是完全合法的，呼叫端寫的是 `composeState(...)`。舊版以 **imported name** 判定該頁要納入、
 * 卻以字面 `mergeState` 找 CallExpression，兩者只是碰巧一致——只要有人取別名，
 * 該頁就會被納入卻找不到呼叫，噴一個**內容說謊**的 FAIL_CLOSED_3（訊息說「沒有呼叫」，
 * 但呼叫就在那裡）。這違反 CD-2「日後新頁自動涵蓋、不維護清單」的承諾。
 * 沒有別名時 `local === imported`，走同一條路徑，不需要特判。
 *
 * 同時**限定來源**必須是 `web/static/js/shared/merge-state.js`：本守衛檢查的是
 * 那支 `Object.defineProperties` descriptor-preserving 合併的 last-wins 語意，
 * 別處一個剛好也叫 `mergeState` 的函式（例如 `Object.assign` 版）語意不同，
 * 不該被當成同一套契約。來源比對走**解析後的路徑**而不是 specifier 字面字串——
 * 別名表是從 base.html 現場讀的（CD-3），比對字面會在別名 value 改動時誤判。
 *
 * ⚠️ **已知限制（刻意留白，不隱藏）**：
 * - `import * as ns from '...'; ns.mergeState(...)` 的 namespace import **不吃**。
 *   全檔對 import 的處理向來只認 `ImportSpecifier`（具名），這是既有慣例不是本次新開的洞；
 *   要支援得新增一條 fail-closed 規則（CD-6 會變 9 條），超出本次範圍。
 * - barrel 檔的 re-export（`export { mergeState } from '...'`）不追鏈，會被判為「別家來源」而排除。
 *   現況專案沒有 barrel 檔。
 * - **非 importmap 別名的 specifier（相對路徑 `'../../shared/merge-state.js'`）不吃** ⇒ 該頁**整頁靜默排除**，
 *   報告裡直接少一頁、數字照樣全綠（131b branch review 沙盒實證）。這與上面兩條同源：
 *   `specifierToRelPath()` 只認 importmap 別名。**沒有升級成 fail-closed 是刻意的**——
 *   「這頁提到 mergeState 卻解析不出來源就 throw」會把 `〔source-3〕`（namespace import 刻意排除）
 *   那支既有測試一起弄紅，屬於自生洞。現況全庫 main.js 一律用 `@/`；
 *   哪天要正式支援，跟上面兩條一起做成 CD-6 的第 9 條規則。
 *
 * @param {import('estree').Program} ast
 * @param {Record<string, string>} imports importmap 別名表
 * @returns {Set<string>} 本地綁定名集合；空集合 ＝ 這頁沒有用共用 merge 契約
 */
function findMergeStateLocalNames(ast, imports) {
  /** @type {Set<string>} */
  const locals = new Set();
  for (const node of ast.body) {
    if (node.type !== 'ImportDeclaration') continue;
    if (typeof node.source.value !== 'string') continue;
    if (specifierToRelPath(imports, node.source.value) !== MERGE_STATE_REL) continue;
    for (const spec of node.specifiers) {
      if (spec.type !== 'ImportSpecifier') continue;
      const imported = spec.imported.type === 'Identifier'
        ? spec.imported.name
        : String(spec.imported.value);
      if (imported === 'mergeState') locals.add(spec.local.name);
    }
  }
  return locals;
}

/**
 * 收集該頁**全部** mergeState(...) CallExpression。
 *
 * 刻意回陣列而不是「第一個」：只取第一個的話，某頁哪天多出第二處呼叫
 * （新的子元件、死碼殘留）時，那一處的貢獻者會**完全不被檢查**——
 * 而「沒被抓到」與「沒有撞名」永遠分不出來。CD-6 要求失效方向是吵不是靜默，
 * 所以由呼叫端在「不是恰好一處」時走 fail-closed 第 3 條。
 *
 * @param {import('estree').Program} ast
 * @param {Set<string>} localNames `findMergeStateLocalNames()` 回的本地綁定名集合
 * @returns {import('estree').CallExpression[]}
 */
export function findMergeStateCalls(ast, localNames) {
  /** @type {import('estree').CallExpression[]} */
  const found = [];
  walk(ast, (node) => {
    if (
      node.type === 'CallExpression'
      && node.callee.type === 'Identifier'
      && localNames.has(node.callee.name)
    ) {
      found.push(node);
    }
  });
  return found;
}

/** 簡易 AST walk（只走物件／陣列子節點） */
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

/**
 * 依具名 export 找 factory 函式節點。
 * @param {import('estree').Program} ast
 * @param {string} name
 * @returns {import('estree').Function|null}
 */
function findNamedFactory(ast, name) {
  for (const node of ast.body) {
    if (node.type !== 'ExportNamedDeclaration') continue;
    const decl = node.declaration;
    if (!decl) continue;
    if (decl.type === 'FunctionDeclaration' && decl.id && decl.id.name === name) {
      return decl;
    }
    if (decl.type === 'VariableDeclaration') {
      for (const d of decl.declarations) {
        if (d.id.type !== 'Identifier' || d.id.name !== name) continue;
        if (
          d.init
          && (d.init.type === 'FunctionExpression' || d.init.type === 'ArrowFunctionExpression')
        ) {
          return d.init;
        }
      }
    }
  }
  return null;
}

/**
 * 只取函式 body 的直接子 ReturnStatement（不得遞迴進 method）。
 * @param {import('estree').Function} fn
 * @param {string} label
 * @returns {import('estree').ObjectExpression}
 */
function topLevelReturnObject(fn, label) {
  // () => ({ ... }) 表達式箭頭函式
  if (fn.type === 'ArrowFunctionExpression' && fn.body.type === 'ObjectExpression') {
    return fn.body;
  }
  if (fn.body.type !== 'BlockStatement') {
    throw new AlpineStateError(
      7,
      `${label}: factory body is not a BlockStatement or ObjectExpression`,
    );
  }
  for (const stmt of fn.body.body) {
    if (stmt.type !== 'ReturnStatement') continue;
    if (!stmt.argument || stmt.argument.type !== 'ObjectExpression') {
      throw new AlpineStateError(
        7,
        `${label}: top-level return is not an ObjectExpression`,
      );
    }
    return stmt.argument;
  }
  throw new AlpineStateError(7, `${label}: no top-level return ObjectExpression`);
}

/**
 * 從 ObjectExpression 收頂層 key；同貢獻者內 get/set collapse。
 * @param {import('estree').ObjectExpression} obj
 * @param {string} label
 * @returns {Map<string, KeyInfo>}
 */
function collectKeys(obj, label) {
  /** @type {Map<string, KeyInfo>} */
  const keys = new Map();
  for (const prop of obj.properties) {
    if (prop.type === 'SpreadElement') {
      throw new AlpineStateError(8, `${label}: top-level SpreadElement is not allowed`);
    }
    if (prop.type !== 'Property') {
      throw new AlpineStateError(8, `${label}: unexpected object property type ${prop.type}`);
    }
    if (prop.computed) {
      throw new AlpineStateError(8, `${label}: computed key is not allowed`);
    }
    let name;
    if (prop.key.type === 'Identifier') {
      name = prop.key.name;
    } else if (prop.key.type === 'Literal' && typeof prop.key.value === 'string') {
      name = prop.key.value;
    } else {
      throw new AlpineStateError(8, `${label}: unsupported key node type ${prop.key.type}`);
    }
    /** @type {KeyKind} */
    const kind = prop.kind === 'get' || prop.kind === 'set' ? prop.kind : 'init';
    const line = prop.loc ? prop.loc.start.line : 0;
    const existing = keys.get(name);
    if (existing) {
      existing.kinds.add(kind);
    } else {
      keys.set(name, { kinds: new Set([kind]), line });
    }
  }
  return keys;
}

/**
 * @param {string} root
 * @param {Record<string, string>} importMap
 * @param {string} entryAbs
 * @param {string} entryRel
 * @param {import('estree').Program} entryAst
 * @param {import('estree').CallExpression} mergeCall
 * @returns {Contributor[]}
 */
function collectContributors(root, importMap, entryAbs, entryRel, entryAst, mergeCall) {
  const bindings = buildImportBindings(entryAst);
  /** @type {Contributor[]} */
  const contributors = [];

  mergeCall.arguments.forEach((arg, order) => {
    if (arg.type === 'ObjectExpression') {
      const line = arg.loc ? arg.loc.start.line : 0;
      const source = `${entryRel}:${line}`;
      contributors.push({
        kind: 'inline',
        source,
        factoryName: null,
        order,
        keys: collectKeys(arg, source),
      });
      return;
    }

    if (arg.type !== 'CallExpression') {
      throw new AlpineStateError(
        4,
        `${entryRel}: mergeState argument #${order} is neither CallExpression nor ObjectExpression (got ${arg.type})`,
      );
    }

    const localName = factoryIdentFromCall(arg);
    if (!localName) {
      throw new AlpineStateError(
        4,
        `${entryRel}: mergeState argument #${order} CallExpression has no resolvable factory identifier`,
      );
    }

    const binding = bindings.get(localName);
    if (!binding) {
      throw new AlpineStateError(
        5,
        `${entryRel}: factory identifier '${localName}' has no matching import`,
      );
    }

    const shardAbs = resolveSpecifier(root, importMap, binding.specifier, entryRel);
    const shardRel = relPosix(root, shardAbs);
    const shardCode = readFileSync(shardAbs, 'utf8');
    const shardAst = parseModule(shardCode, shardRel);
    const factory = findNamedFactory(shardAst, binding.importedName);
    if (!factory) {
      throw new AlpineStateError(
        7,
        `${shardRel}: named factory '${binding.importedName}' not found`,
      );
    }
    const obj = topLevelReturnObject(factory, `${shardRel}#${binding.importedName}`);
    contributors.push({
      kind: 'factory',
      source: shardRel,
      factoryName: binding.importedName,
      order,
      keys: collectKeys(obj, `${shardRel}#${binding.importedName}`),
    });
  });

  return contributors;
}

/**
 * 解析所有 mergeState 頁面的貢獻者與頂層 key。
 * @param {string} [root] repo 根（預設本檔 ../../）
 * @returns {PageInfo[]}
 */
export function collectPages(root = DEFAULT_ROOT) {
  const absRoot = resolve(root);
  const importMap = loadImportMap(absRoot);

  const pagesDir = join(absRoot, 'web/static/js/pages');
  if (!existsSync(pagesDir)) {
    throw new AlpineStateError(2, `pages directory missing: web/static/js/pages`);
  }

  const dirents = readdirSync(pagesDir, { withFileTypes: true });
  /** @type {PageInfo[]} */
  const pages = [];

  for (const ent of dirents) {
    if (!ent.isDirectory()) continue;
    const entryAbs = join(pagesDir, ent.name, 'main.js');
    if (!existsSync(entryAbs)) continue;

    const entryRel = relPosix(absRoot, entryAbs);
    const code = readFileSync(entryAbs, 'utf8');
    const ast = parseModule(code, entryRel);

    // 空集合 ＝ 這頁沒有用共用 merge 契約（沒 import，或 import 的是別處同名函式）
    // ⇒ 靜默排除，與「這頁根本沒 import」同一邊。CD-2 的頁面篩選本來就是排除性質，
    //    把它升級成 fail-closed 只會無謂擴大觸發面；不用本契約的頁面原本就不在檢查範圍內。
    const mergeLocals = findMergeStateLocalNames(ast, importMap);
    if (mergeLocals.size === 0) continue;

    const mergeCalls = findMergeStateCalls(ast, mergeLocals);
    if (mergeCalls.length === 0) {
      throw new AlpineStateError(
        3,
        `${entryRel}: imports mergeState (as ${[...mergeLocals].join('/')}) but no ${[...mergeLocals].join('/')}(...) call found`,
      );
    }
    if (mergeCalls.length > 1) {
      const lines = mergeCalls.map((c) => (c.loc ? c.loc.start.line : '?')).join(', ');
      throw new AlpineStateError(
        3,
        `${entryRel}: expected exactly one mergeState(...) call, found ${mergeCalls.length} (lines ${lines})`
        + ' — 多於一處時本核心只會分析其中一處，其餘貢獻者將完全不被檢查（假陰性）。'
        + '要支援多處請先擴充本核心，不要靜默略過。',
      );
    }
    const mergeCall = mergeCalls[0];

    pages.push({
      page: ent.name,
      entry: entryRel,
      contributors: collectContributors(
        absRoot, importMap, entryAbs, entryRel, ast, mergeCall,
      ),
    });
  }

  if (pages.length === 0) {
    throw new AlpineStateError(2, 'no pages/*/main.js imports mergeState');
  }

  // 穩定順序：頁名排序（非硬編碼頁清單；只是輸出可重現）
  pages.sort((a, b) => a.page.localeCompare(b.page));
  return pages;
}

export { DEFAULT_ROOT, MERGE_STATE_REL, loadImportMap, findMergeStateLocalNames };
