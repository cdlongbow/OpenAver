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

/** 該檔是否具名 import 了 mergeState */
function importsMergeState(ast) {
  for (const node of ast.body) {
    if (node.type !== 'ImportDeclaration') continue;
    for (const spec of node.specifiers) {
      if (spec.type !== 'ImportSpecifier') continue;
      const imported = spec.imported.type === 'Identifier'
        ? spec.imported.name
        : String(spec.imported.value);
      if (imported === 'mergeState') return true;
    }
  }
  return false;
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
 * @returns {import('estree').CallExpression[]}
 */
function findMergeStateCalls(ast) {
  /** @type {import('estree').CallExpression[]} */
  const found = [];
  walk(ast, (node) => {
    if (
      node.type === 'CallExpression'
      && node.callee.type === 'Identifier'
      && node.callee.name === 'mergeState'
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

    if (!importsMergeState(ast)) continue;

    const mergeCalls = findMergeStateCalls(ast);
    if (mergeCalls.length === 0) {
      throw new AlpineStateError(
        3,
        `${entryRel}: imports mergeState but no mergeState(...) call found`,
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

export { DEFAULT_ROOT };
