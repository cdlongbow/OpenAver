/**
 * alpine-registry.mjs — SPIKE（plan-179 T1，CD-179-7）
 *
 * `Alpine.data('<字面名>', …)` 註冊表：名稱 → { file, kind, keys:Set }。
 * 重用 alpine-state.mjs 既有匯出（collectPages / findMergeStateCalls /
 * findMergeStateLocalNames / loadImportMap / findNamedFactory / walk / AlpineStateError）。
 * 未匯出者以 SPIKE-COPY 暫代（T2 需匯出的清單見 findings）：
 *   parseModule、relPosix、resolveSpecifier、buildImportBindings、topLevelReturnObject、collectKeys
 * spread 只在本模組處理；alpine-state.mjs 一個字都沒動。
 */
import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join, relative, resolve, sep, dirname } from 'node:path';
import { parse } from 'espree';
import {
  collectPages, findMergeStateCalls, findMergeStateLocalNames, loadImportMap,
  findNamedFactory, walk, AlpineStateError,
} from './alpine-state.mjs';

/* ── SPIKE-COPY ─────────────────────────────────────────────── */
const PARSE_OPTS = { ecmaVersion: 2024, sourceType: 'module', loc: true };
function relPosix(root, abs) { return relative(root, abs).split(sep).join('/'); } // SPIKE-COPY
function parseModule(code, label) { // SPIKE-COPY
  try { return parse(code, PARSE_OPTS); } catch (err) {
    throw new AlpineStateError(7, `espree failed to parse ${label}: ${err.message}`);
  }
}
function resolveSpecifier(root, imports, specifier, fromEntry, fromAbs = null) { // SPIKE-COPY（＋相對路徑：alpine-state.mjs 沒有，新模組自己補）
  if (specifier.startsWith('.') && fromAbs) {
    const abs = resolve(dirname(fromAbs), specifier);
    if (!existsSync(abs)) throw new AlpineStateError(6, `${fromEntry}: ${specifier} → missing ${relPosix(root, abs)}`);
    return abs;
  }
  const aliases = Object.keys(imports).sort((a, b) => b.length - a.length);
  for (const alias of aliases) {
    if (!specifier.startsWith(alias)) continue;
    const abs = resolve(root, join('web', imports[alias].slice(1), specifier.slice(alias.length)));
    if (!existsSync(abs)) throw new AlpineStateError(6, `${fromEntry}: ${specifier} → missing ${relPosix(root, abs)}`);
    return abs;
  }
  throw new AlpineStateError(6, `${fromEntry}: specifier ${specifier} not matched by importmap alias`);
}
function buildImportBindings(ast) { // SPIKE-COPY
  const map = new Map();
  for (const node of ast.body) {
    if (node.type !== 'ImportDeclaration' || typeof node.source.value !== 'string') continue;
    for (const spec of node.specifiers) {
      if (spec.type !== 'ImportSpecifier') continue;
      const imported = spec.imported.type === 'Identifier' ? spec.imported.name : String(spec.imported.value);
      map.set(spec.local.name, { importedName: imported, specifier: node.source.value });
    }
  }
  return map;
}
function topLevelReturnObject(fn, label) { // SPIKE-COPY
  if (fn.type === 'ArrowFunctionExpression' && fn.body.type === 'ObjectExpression') return fn.body;
  if (fn.body.type !== 'BlockStatement') throw new AlpineStateError(7, `${label}: factory body is not Block/Object`);
  for (const stmt of fn.body.body) {
    if (stmt.type !== 'ReturnStatement') continue;
    if (!stmt.argument || stmt.argument.type !== 'ObjectExpression') {
      throw new AlpineStateError(7, `${label}: top-level return is not an ObjectExpression`);
    }
    return stmt.argument;
  }
  throw new AlpineStateError(7, `${label}: no top-level return ObjectExpression`);
}
function collectKeys(obj, label) { // SPIKE-COPY（spread 已由呼叫端拆掉；computed 仍 throw）
  const keys = new Set();
  for (const prop of obj.properties) {
    if (prop.type === 'SpreadElement') throw new AlpineStateError(8, `${label}: SpreadElement reached collectKeys`);
    if (prop.type !== 'Property') throw new AlpineStateError(8, `${label}: unexpected property type ${prop.type}`);
    if (prop.computed) throw new AlpineStateError(8, `${label}: computed key`);
    if (prop.key.type === 'Identifier') keys.add(prop.key.name);
    else if (prop.key.type === 'Literal' && typeof prop.key.value === 'string') keys.add(prop.key.value);
    else throw new AlpineStateError(8, `${label}: unsupported key node ${prop.key.type}`);
  }
  return keys;
}
/* ──────────────────────────────────────────────────────────── */

function listJs(dir, out = []) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === '__tests__') continue;
      listJs(p, out);
    } else if (ent.name.endsWith('.js')) out.push(p);
  }
  return out;
}

/** 解函式（Identifier 於本檔宣告 / 具名 import / FunctionExpression） */
function localFunction(ast, name) {
  for (const node of ast.body) {
    const decl = node.type === 'ExportNamedDeclaration' && node.declaration ? node.declaration : node;
    if (decl.type === 'FunctionDeclaration' && decl.id && decl.id.name === name) return decl;
    if (decl.type === 'VariableDeclaration') {
      for (const d of decl.declarations) {
        if (d.id.type === 'Identifier' && d.id.name === name && d.init
          && (d.init.type === 'FunctionExpression' || d.init.type === 'ArrowFunctionExpression')) return d.init;
      }
    }
  }
  return null;
}

export function buildRegistry(root) {
  const absRoot = resolve(root);
  const importMap = loadImportMap(absRoot);
  const pages = collectPages(absRoot); // 既有 API，不改
  const pageByEntry = new Map(pages.map((p) => [p.entry, p]));
  const jsRoot = join(absRoot, 'web/static/js');
  const regs = new Map();           // name → { file, line, resolve:()=>keys }
  const toolErrors = [];
  const astCache = new Map();
  const astOf = (abs) => {
    if (!astCache.has(abs)) astCache.set(abs, parseModule(readFileSync(abs, 'utf8'), relPosix(absRoot, abs)));
    return astCache.get(abs);
  };

  for (const abs of listJs(jsRoot)) {
    const rel = relPosix(absRoot, abs);
    const code = readFileSync(abs, 'utf8');
    if (!code.includes('Alpine.data(')) continue;
    const ast = astOf(abs);
    walk(ast, (node) => {
      if (node.type !== 'CallExpression') return;
      const c = node.callee;
      if (!(c.type === 'MemberExpression' && !c.computed && c.object.type === 'Identifier'
        && c.object.name === 'Alpine' && c.property.type === 'Identifier' && c.property.name === 'data')) return;
      const nameArg = node.arguments[0];
      if (!nameArg || nameArg.type !== 'Literal' || typeof nameArg.value !== 'string') {
        toolErrors.push(`${rel}:${node.loc.start.line}: Alpine.data first arg is not a string literal`);
        return;
      }
      const name = nameArg.value;
      if (regs.has(name)) {
        toolErrors.push(`duplicate Alpine.data('${name}') at ${rel}:${node.loc.start.line} and ${regs.get(name).file}:${regs.get(name).line}`);
        return;
      }
      regs.set(name, { name, file: rel, line: node.loc.start.line, abs, arg: node.arguments[1], ast, keys: null });
    });
  }

  /** 解一個「會回傳狀態物件的 factory」→ Set(keys)；seen 防迴圈 */
  function keysOfFactoryFn(fn, ast, abs, label, notes) {
    const obj = topLevelReturnObject(fn, label);
    const plain = { ...obj, properties: obj.properties.filter((p) => p.type !== 'SpreadElement') };
    const keys = collectKeys(plain, label);
    const bindings = buildImportBindings(ast);
    for (const p of obj.properties) {
      if (p.type !== 'SpreadElement') continue;
      const a = p.argument;
      if (a.type !== 'CallExpression' || a.callee.type !== 'Identifier') {
        throw new AlpineStateError(8, `${label}: spread of non-call (${a.type})`);
      }
      const nm = a.callee.name;
      let subFn; let subAst; let subAbs; let subLabel;
      const b = bindings.get(nm);
      if (b) {
        subAbs = resolveSpecifier(absRoot, importMap, b.specifier, label, abs);
        subAst = astOf(subAbs);
        subFn = findNamedFactory(subAst, b.importedName);
        subLabel = `${relPosix(absRoot, subAbs)}#${b.importedName}`;
      } else {
        subFn = localFunction(ast, nm); subAst = ast; subAbs = abs; subLabel = `${label}->${nm}`;
      }
      if (!subFn) throw new AlpineStateError(7, `${label}: cannot resolve spread factory ${nm}()`);
      const sub = keysOfFactoryFn(subFn, subAst, subAbs, subLabel, notes);
      notes.push(`${label}: ...${nm}() expanded → ${sub.size} keys`);
      for (const k of sub) keys.add(k);
    }
    return keys;
  }

  function resolveReg(reg) {
    if (reg.keys) return reg.keys;
    const { ast, abs, arg, file, name } = reg;
    const notes = [];
    reg.notes = notes;
    const label = `${file}#Alpine.data('${name}')`;
    let fn = null;
    let fnAst = ast; let fnAbs = abs; let fnLabel = label;
    if (arg.type === 'ArrowFunctionExpression' || arg.type === 'FunctionExpression') fn = arg;
    else if (arg.type === 'Identifier') {
      const b = buildImportBindings(ast).get(arg.name);
      if (b) {
        fnAbs = resolveSpecifier(absRoot, importMap, b.specifier, file, abs);
        fnAst = astOf(fnAbs);
        fn = findNamedFactory(fnAst, b.importedName);
        fnLabel = `${relPosix(absRoot, fnAbs)}#${b.importedName}`;
      } else {
        fn = localFunction(ast, arg.name);
        fnLabel = `${file}#${arg.name}`;
      }
    } else if (arg.type === 'MemberExpression' && !arg.computed && arg.object.type === 'Identifier'
      && arg.object.name === 'window' && arg.property.type === 'Identifier') {
      // window.X = <Identifier | function> 同檔賦值
      const wname = arg.property.name;
      let rhs = null;
      walk(ast, (n) => {
        if (n.type === 'AssignmentExpression' && n.operator === '=' && n.left.type === 'MemberExpression'
          && !n.left.computed && n.left.object.type === 'Identifier' && n.left.object.name === 'window'
          && n.left.property.type === 'Identifier' && n.left.property.name === wname) rhs = n.right;
      });
      if (!rhs) throw new AlpineStateError(7, `${label}: window.${wname} assignment not found in same file`);
      notes.push(`window.${wname} resolved via same-file assignment (${rhs.type})`);
      if (rhs.type === 'FunctionExpression' || rhs.type === 'ArrowFunctionExpression') fn = rhs;
      else if (rhs.type === 'Identifier') {
        const b = buildImportBindings(ast).get(rhs.name);
        if (b) {
          fnAbs = resolveSpecifier(absRoot, importMap, b.specifier, file, abs);
          fnAst = astOf(fnAbs);
          fn = findNamedFactory(fnAst, b.importedName);
          fnLabel = `${relPosix(absRoot, fnAbs)}#${b.importedName}`;
        } else fn = localFunction(ast, rhs.name);
      }
    }
    if (!fn) throw new AlpineStateError(7, `${label}: cannot resolve factory (${arg.type})`);

    // mergeState 頁？
    const page = pageByEntry.get(file);
    if (page) {
      const locals = findMergeStateLocalNames(ast, importMap);
      let hasMerge = false;
      walk(fn, (n) => {
        if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && locals.has(n.callee.name)) hasMerge = true;
      });
      if (hasMerge) {
        const keys = new Set();
        for (const c of page.contributors) for (const k of c.keys.keys()) keys.add(k);
        reg.source = 'mergeState';
        reg.pageName = page.page;
        reg.contribCount = page.contributors.length;
        reg.keys = keys;
        return keys;
      }
    }
    reg.source = 'factory';
    reg.keys = keysOfFactoryFn(fn, fnAst, fnAbs, fnLabel, notes);
    return reg.keys;
  }

  return { regs, resolveReg, toolErrors, pages };
}
