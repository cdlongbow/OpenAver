/**
 * binding-expr.mjs — SPIKE（plan-179 T1，CD-179-4／-5）
 * 指令分類、兩段式 espree、eslint-scope 自由識別字。
 * 所有送進 eslint-scope 的 AST 一律 range:true（handoff §3）。
 */
import { parse } from 'espree';
import * as eslintScope from 'eslint-scope';

const analyze = eslintScope.analyze;

/** 值是運算式（含 x-data／x-for 兩個特殊） */
export const EXPR_DIRECTIVES = new Set([
  'on', 'bind', 'text', 'html', 'show', 'if', 'model', 'modelable', 'init', 'effect', 'id',
  'trap', 'anchor', 'intersect', 'data', 'for',
]);
/** 值不是運算式 */
export const NOEXPR_DIRECTIVES = new Set([
  'ref', 'cloak', 'ignore', 'teleport', 'transition', 'collapse',
]);

/**
 * 回 {kind:'plain'|'expr'|'noexpr'|'unknown', dir, arg}
 * 屬性名由 parse5 切好（小寫）。
 */
export function classifyAttr(rawName) {
  const name = rawName;
  let dir;
  let rest;
  if (name.startsWith('@')) { dir = 'on'; rest = name.slice(1); }
  else if (name.startsWith(':')) { dir = 'bind'; rest = name.slice(1); }
  else if (name.startsWith('x-')) {
    const body = name.slice(2);
    const m = body.match(/^[a-z]+/);
    dir = m ? m[0] : '';
    rest = body.slice(dir.length).replace(/^:/, '');
    if (!dir) return { kind: 'unknown', dir: body, name };
  } else return { kind: 'plain', name };
  const arg = rest.split('.')[0];
  if (EXPR_DIRECTIVES.has(dir)) return { kind: 'expr', dir, arg, name };
  if (NOEXPR_DIRECTIVES.has(dir)) return { kind: 'noexpr', dir, arg, name };
  return { kind: 'unknown', dir, arg, name };
}

const OPTS = { ecmaVersion: 2024, sourceType: 'script', loc: true, range: true };

/** 兩段式解析；皆失敗 → 回 {fail:[err1, err2]} */
const parseCache = new Map();
export const _parseCache = parseCache; // SPIKE 統計用
export function parseExpr(value) {
  if (parseCache.has(value)) return parseCache.get(value);
  let res;
  try {
    const ast = parse(`(${value}\n)`, OPTS);
    res = { ast, wrap: 'expr', colOffset: 1 };
  } catch (e1) {
    try {
      const ast = parse(`async function __b(){${value}\n}`, OPTS);
      res = { ast, wrap: 'stmts', colOffset: 'async function __b(){'.length };
    } catch (e2) {
      res = { fail: [e1.message, e2.message] };
    }
  }
  parseCache.set(value, res);
  return res;
}

/** 運算元位置 typeof X 的名字 */
function typeofNames(ast) {
  const names = new Set();
  (function w(n) {
    if (!n || typeof n !== 'object') return;
    if (Array.isArray(n)) { n.forEach(w); return; }
    if (n.type === 'UnaryExpression' && n.operator === 'typeof' && n.argument.type === 'Identifier') {
      names.add(n.argument.name);
    }
    for (const k of Object.keys(n)) {
      if (k === 'loc' || k === 'range') continue;
      const c = n[k];
      if (c && typeof c === 'object') w(c);
    }
  })(ast);
  return names;
}

const throughCache = new Map();
/**
 * 自由識別字 [{name, line(相對屬性值第 1 行=1), write}]
 * ＋ typeof 豁免集合
 */
export function freeIds(parsed, cacheKey) {
  if (cacheKey && throughCache.has(cacheKey)) return throughCache.get(cacheKey);
  const mgr = analyze(parsed.ast, { ecmaVersion: 2024, sourceType: 'script', ignoreEval: true });
  const out = mgr.globalScope.through.map((r) => ({
    name: r.identifier.name,
    line: r.identifier.loc.start.line,
    start: r.identifier.range[0],
    write: r.isWrite(),
  }));
  const tn = typeofNames(parsed.ast);
  const res = { ids: out, typeofNames: tn };
  if (cacheKey) throughCache.set(cacheKey, res);
  return res;
}

/** x-for：切成 {lhs, list}；失敗回 null */
export function splitFor(value) {
  const m = value.match(/([\s\S]*?)\s+(?:in|of)\s+([\s\S]*)/);
  if (!m) return null;
  const lhs = m[1].replace(/^\s*\(|\)\s*$/g, '').trim();
  return { lhs, list: m[2].trim() };
}

/** pattern 的綁定名 */
function patternNames(p, out) {
  if (!p) return;
  switch (p.type) {
    case 'Identifier': out.push(p.name); break;
    case 'ObjectPattern':
      p.properties.forEach((pr) => patternNames(pr.type === 'RestElement' ? pr.argument : pr.value, out));
      break;
    case 'ArrayPattern': p.elements.forEach((e) => patternNames(e, out)); break;
    case 'AssignmentPattern': patternNames(p.left, out); break;
    case 'RestElement': patternNames(p.argument, out); break;
    default: break;
  }
}

/** x-for 迴圈變數名；解析失敗回 {fail} */
export function forLoopVars(lhs) {
  try {
    const ast = parse(`((${lhs}) => 0)`, OPTS);
    const fn = ast.body[0].expression;
    const names = [];
    fn.params.forEach((p) => patternNames(p, names));
    // 預設值內的自由識別字（極罕見）也要查：以整個箭頭函式做 through
    const mgr = analyze(ast, { ecmaVersion: 2024, sourceType: 'script', ignoreEval: true });
    const through = mgr.globalScope.through.map((r) => r.identifier.name);
    return { names, through };
  } catch (e) {
    return { fail: e.message };
  }
}
