/**
 * jinja-lite.mjs — SPIKE（plan-179 T1，CD-179-2）
 *
 * 封閉子集 Jinja 展開器：把 web/templates 的模板展開成「瀏覽器收到的 HTML 文字」，
 * 並建「輸出行 → 來源 {file,line,via}」行來源表。
 *
 * 支援：extends/block/endblock、from…import、include、macro/endmacro、
 *       if/elif/else/endif（一律取聯集，不求值）、{{ }}、{# #}。
 * 其他構造（raw/for/set/call/with/filter/import…）→ ToolError（點名檔案行與構造）。
 */
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { parse as espreeParse } from 'espree';

export class ToolError extends Error {
  constructor(code, message, file = null, line = null) {
    super(message);
    this.name = 'ToolError';
    this.code = code;
    this.file = file;
    this.line = line;
  }
}

const countNl = (s) => (s.match(/\n/g) || []).length;

/* ───────────── tokenizer ───────────── */

function scanTagEnd(src, from, endTok, file, line0) {
  // 在 {{ … }} / {% … %} 內追蹤引號，避免字串內的 }} / %} 提早結束
  let i = from;
  let q = null;
  while (i < src.length) {
    const c = src[i];
    if (q) {
      if (c === '\\') { i += 2; continue; }
      if (c === q) q = null;
      i++;
      continue;
    }
    if (c === '"' || c === "'") { q = c; i++; continue; }
    if (src.startsWith(endTok, i)) return i;
    i++;
  }
  throw new ToolError('unterminated', `unterminated ${endTok} tag`, file, line0);
}

export function tokenize(src, file) {
  const toks = [];
  let i = 0;
  let line = 1;
  let textStart = 0;
  const flushText = (end) => {
    if (end > textStart) {
      const raw = src.slice(textStart, end);
      toks.push({ t: 'text', raw, line: line });
      line += countNl(raw);
    }
  };
  while (i < src.length) {
    const c2 = src.slice(i, i + 2);
    if (c2 === '{#') {
      flushText(i);
      const e = src.indexOf('#}', i + 2);
      if (e < 0) throw new ToolError('unterminated', 'unterminated {# comment', file, line);
      const raw = src.slice(i, e + 2);
      toks.push({ t: 'drop', raw, line, kind: 'comment' });
      line += countNl(raw);
      i = e + 2;
      textStart = i;
    } else if (c2 === '{{') {
      flushText(i);
      const e = scanTagEnd(src, i + 2, '}}', file, line);
      const raw = src.slice(i, e + 2);
      toks.push({ t: 'expr', raw, body: src.slice(i + 2, e).replace(/^-|-$/g, '').trim(), line });
      line += countNl(raw);
      i = e + 2;
      textStart = i;
    } else if (c2 === '{%') {
      flushText(i);
      const e = scanTagEnd(src, i + 2, '%}', file, line);
      const raw = src.slice(i, e + 2);
      toks.push({ t: 'tag', raw, body: src.slice(i + 2, e).replace(/^-|-$/g, '').trim(), line });
      line += countNl(raw);
      i = e + 2;
      textStart = i;
    } else {
      i++;
    }
  }
  flushText(src.length);
  return toks;
}

/* ───────────── parser ───────────── */

function parseTree(toks, file) {
  const root = { t: 'root', children: [] };
  const stack = [root];
  const top = () => stack[stack.length - 1];
  for (const tok of toks) {
    if (tok.t === 'text' || tok.t === 'expr' || tok.t === 'drop') {
      top().children.push({ ...tok });
      continue;
    }
    const body = tok.body;
    const kw = (body.match(/^[A-Za-z_]+/) || [''])[0];
    const nl = countNl(tok.raw);
    switch (kw) {
      case 'if': case 'elif': case 'else': case 'endif':
        top().children.push({ t: 'drop', raw: tok.raw, line: tok.line, kind: kw });
        break;
      case 'block': {
        const m = body.match(/^block\s+([A-Za-z_]\w*)\s*$/);
        if (!m) throw new ToolError('unsupported', `unsupported block syntax: {% ${body} %}`, file, tok.line);
        const node = { t: 'block', name: m[1], children: [], line: tok.line, nl };
        top().children.push(node);
        stack.push(node);
        break;
      }
      case 'endblock': {
        if (top().t !== 'block') throw new ToolError('unbalanced', 'endblock without block', file, tok.line);
        stack.pop();
        break;
      }
      case 'macro': {
        const m = body.match(/^macro\s+([A-Za-z_]\w*)\s*\(([\s\S]*)\)\s*$/);
        if (!m) throw new ToolError('unsupported', `unsupported macro syntax: {% ${body.slice(0, 60)} %}`, file, tok.line);
        const node = { t: 'macro', name: m[1], sig: m[2], children: [], line: tok.line, file };
        top().children.push(node);
        stack.push(node);
        break;
      }
      case 'endmacro': {
        if (top().t !== 'macro') throw new ToolError('unbalanced', 'endmacro without macro', file, tok.line);
        stack.pop();
        break;
      }
      case 'extends': {
        const m = body.match(/^extends\s+(['"])([^'"]+)\1\s*$/);
        if (!m) throw new ToolError('unsupported', `unsupported extends: {% ${body} %}`, file, tok.line);
        top().children.push({ t: 'extends', path: m[2], line: tok.line });
        break;
      }
      case 'include': {
        const m = body.match(/^include\s+(['"])([^'"]+)\1\s*$/);
        if (!m) throw new ToolError('unsupported', `unsupported include: {% ${body} %}`, file, tok.line);
        top().children.push({ t: 'include', path: m[2], line: tok.line, nl });
        break;
      }
      case 'from': {
        const m = body.match(/^from\s+(['"])([^'"]+)\1\s+import\s+([\w\s,]+)$/);
        if (!m) throw new ToolError('unsupported', `unsupported from-import: {% ${body} %}`, file, tok.line);
        top().children.push({
          t: 'from', path: m[2], names: m[3].split(',').map((s) => s.trim()).filter(Boolean), line: tok.line, nl,
        });
        break;
      }
      default:
        throw new ToolError('unsupported', `unsupported Jinja construct: {% ${kw} %}`, file, tok.line);
    }
  }
  if (stack.length !== 1) {
    throw new ToolError('unbalanced', `unclosed ${top().t} ${top().name || ''}`, file, top().line);
  }
  return root;
}

/* ───────────── expander ───────────── */

function* eachNode(nodes, intoMacro = false) {
  for (const n of nodes) {
    yield n;
    if (n.children && (n.t === 'block' || (intoMacro && n.t === 'macro'))) yield* eachNode(n.children, intoMacro);
  }
}

const htmlEscape = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&#34;').replace(/'/g, '&#39;');

class Output {
  constructor() {
    this.parts = [];
    this.origins = [];           // 輸出行(0-based) → {file,line,via}
    this.curEmpty = true;
    this.curOrigin = null;
  }

  push(str, file, line, via) {
    if (str === '') return;
    const pieces = str.split('\n');
    pieces.forEach((piece, idx) => {
      if (idx > 0) {
        this.parts.push('\n');
        this.origins.push(this.curOrigin);
        this.curEmpty = true;
        this.curOrigin = null;
      }
      if (piece !== '') {
        if (this.curEmpty) {
          this.curOrigin = { file, line: line + idx, via };
          this.curEmpty = false;
        }
        this.parts.push(piece);
      } else if (this.curEmpty && this.curOrigin === null) {
        this.curOrigin = { file, line: line + idx, via };
      }
    });
  }

  finish() {
    this.origins.push(this.curOrigin);
    return { text: this.parts.join(''), origins: this.origins };
  }
}

export class Expander {
  constructor(templatesRoot) {
    this.root = templatesRoot;
    this.cache = new Map();
    this.expandedFragments = new Set(); // 被 include / macro 展開到的檔（rel）
    this.macroCalls = new Map();        // 'file#name' → 次數
    this.stats = { macroExpansions: 0, includeExpansions: 0, exprReplaced: 0, dropped: 0 };
  }

  load(rel, fromFile = null, fromLine = null) {
    if (this.cache.has(rel)) return this.cache.get(rel);
    const abs = join(this.root, rel);
    if (!existsSync(abs)) throw new ToolError('missing', `template not found: ${rel}`, fromFile, fromLine);
    const src = readFileSync(abs, 'utf8');
    const tree = parseTree(tokenize(src, rel), rel);
    const tpl = { rel, tree, macros: new Map(), env: new Map(), extends: null, blocks: new Map() };
    this.cache.set(rel, tpl);
    for (const n of eachNode(tree.children, true)) {
      if (n.t === 'macro') tpl.macros.set(n.name, n);
      if (n.t === 'extends') tpl.extends = n.path;
    }
    for (const [k, m] of tpl.macros) tpl.env.set(k, { macro: m, tpl });
    for (const n of eachNode(tree.children, false)) {
      if (n.t === 'from') {
        const other = this.load(n.path, rel, n.line);
        for (const name of n.names) {
          const mm = other.macros.get(name);
          if (!mm) throw new ToolError('missing', `macro ${name} not found in ${n.path}`, rel, n.line);
          tpl.env.set(name, { macro: mm, tpl: other });
        }
      }
    }
    return tpl;
  }

  expandEntry(rel) {
    const out = new Output();
    const tpl = this.load(rel);
    const used = new Set([rel]);
    if (tpl.extends) {
      const parent = this.load(tpl.extends, rel, 1);
      if (parent.extends) throw new ToolError('unsupported', 'multi-level extends', parent.rel, 1);
      used.add(parent.rel);
      const overrides = new Map();
      for (const n of eachNode(tpl.tree.children, false)) {
        if (n.t === 'block') {
          if (overrides.has(n.name)) throw new ToolError('dup', `duplicate block ${n.name}`, rel, n.line);
          overrides.set(n.name, { node: n, tpl });
        }
      }
      this.render(parent.tree.children, { tpl: parent, overrides, params: null, via: null, depth: 0, out });
    } else {
      this.render(tpl.tree.children, { tpl, overrides: null, params: null, via: null, depth: 0, out });
    }
    const res = out.finish();
    res.used = used;
    return res;
  }

  render(nodes, ctx) {
    if (ctx.depth > 24) throw new ToolError('recursion', 'expansion depth > 24', ctx.tpl.rel, null);
    const file = ctx.tpl.rel;
    const { out } = ctx;
    for (const n of nodes) {
      switch (n.t) {
        case 'text':
          out.push(n.raw, file, n.line, ctx.via);
          break;
        case 'drop':
          this.stats.dropped++;
          out.push('\n'.repeat(countNl(n.raw)), file, n.line, ctx.via);
          break;
        case 'expr':
          this.renderExpr(n, ctx);
          break;
        case 'block': {
          const ov = ctx.overrides && ctx.overrides.get(n.name);
          if (ov) {
            this.render(ov.node.children, { ...ctx, tpl: ov.tpl, depth: ctx.depth + 1 });
          } else {
            this.render(n.children, ctx);
          }
          break;
        }
        case 'macro': case 'extends':
          break; // 定義處不輸出
        case 'from':
          break;
        case 'include': {
          const inc = this.load(n.path, file, n.line);
          this.expandedFragments.add(inc.rel);
          this.stats.includeExpansions++;
          const via = { kind: 'include', file, line: n.line, parent: ctx.via };
          this.render(inc.tree.children, {
            tpl: inc, overrides: null, params: null, via, depth: ctx.depth + 1, out,
          });
          out.push('\n', file, n.line, ctx.via);
          break;
        }
        default:
          throw new ToolError('internal', `unknown node ${n.t}`, file, n.line);
      }
    }
  }

  renderExpr(n, ctx) {
    const file = ctx.tpl.rel;
    const body = n.body;
    const nl = countNl(n.raw);
    const { out } = ctx;
    // macro 呼叫
    const mc = body.match(/^([A-Za-z_]\w*)\s*\(/);
    if (mc && ctx.tpl.env.has(mc[1])) {
      this.expandMacro(n, mc[1], ctx);
      return;
    }
    // macro 參數代入（唯一的求值）
    if (ctx.params) {
      const simple = body.match(/^([A-Za-z_]\w*)\s*(\|\s*safe)?\s*$/);
      if (simple && ctx.params.has(simple[1])) {
        const v = ctx.params.get(simple[1]);
        const s = v === undefined || v === null ? '' : (v === true ? 'True' : v === false ? 'False' : String(v));
        out.push((simple[2] ? s : htmlEscape(s)) + '\n'.repeat(nl), file, n.line, ctx.via);
        return;
      }
      const ids = body.match(/[A-Za-z_]\w*/g) || [];
      const hit = ids.find((id) => ctx.params.has(id));
      if (hit) {
        throw new ToolError('unsupported', `macro param "${hit}" used in complex expression: {{ ${body.slice(0, 60)} }}`, file, n.line);
      }
    }
    this.stats.exprReplaced++;
    out.push('0' + '\n'.repeat(nl), file, n.line, ctx.via);
  }

  expandMacro(n, name, ctx) {
    const file = ctx.tpl.rel;
    const { macro, tpl: mtpl } = ctx.tpl.env.get(name);
    // 解析實參：f(<args>)（Jinja 的 name=value 恰是合法 JS AssignmentExpression）
    let ast;
    try {
      ast = espreeParse(`(${n.body}\n)`, { ecmaVersion: 2024, sourceType: 'script' });
    } catch (e) {
      throw new ToolError('macro-args', `cannot parse macro call {{ ${n.body.slice(0, 60)} }}: ${e.message}`, file, n.line);
    }
    const call = ast.body[0].expression;
    if (call.type !== 'CallExpression' || call.callee.type !== 'Identifier' || call.callee.name !== name) {
      throw new ToolError('macro-args', `macro call has trailing filter/expr: {{ ${n.body.slice(0, 60)} }}`, file, n.line);
    }
    const lit = (node, what) => {
      if (node.type === 'Literal') return node.value;
      if (node.type === 'Identifier') {
        if (node.name === 'true' || node.name === 'True') return true;
        if (node.name === 'false' || node.name === 'False') return false;
        if (node.name === 'none' || node.name === 'None') return null;
      }
      if (node.type === 'UnaryExpression' && node.operator === '-' && node.argument.type === 'Literal') return -node.argument.value;
      throw new ToolError('macro-args', `non-literal macro ${what} (${node.type}) in call ${name}(…)`, file, n.line);
    };
    // 簽章
    let sigAst;
    try {
      sigAst = espreeParse(`(function __m(${macro.sig}\n){})`, { ecmaVersion: 2024, sourceType: 'script' });
    } catch (e) {
      throw new ToolError('macro-sig', `cannot parse macro signature ${name}(…): ${e.message}`, mtpl.rel, macro.line);
    }
    const fn = sigAst.body[0].expression;
    const params = new Map();
    const order = [];
    for (const p of fn.params) {
      if (p.type === 'Identifier') { params.set(p.name, undefined); order.push(p.name); }
      else if (p.type === 'AssignmentPattern' && p.left.type === 'Identifier') {
        params.set(p.left.name, lit(p.right, 'default')); order.push(p.left.name);
      } else throw new ToolError('macro-sig', `unsupported macro param shape in ${name}`, mtpl.rel, macro.line);
    }
    let pos = 0;
    for (const a of call.arguments) {
      if (a.type === 'AssignmentExpression' && a.operator === '=' && a.left.type === 'Identifier') {
        if (!params.has(a.left.name)) throw new ToolError('macro-args', `unknown kwarg ${a.left.name} for ${name}`, file, n.line);
        params.set(a.left.name, lit(a.right, `arg ${a.left.name}`));
      } else {
        if (pos >= order.length) throw new ToolError('macro-args', `too many positional args for ${name}`, file, n.line);
        params.set(order[pos++], lit(a, `positional arg ${pos}`));
      }
    }
    this.stats.macroExpansions++;
    this.expandedFragments.add(mtpl.rel);
    const key = `${mtpl.rel}#${name}`;
    this.macroCalls.set(key, (this.macroCalls.get(key) || 0) + 1);
    const via = { kind: 'macro', name, file, line: n.line, macroFile: mtpl.rel, macroLine: macro.line, parent: ctx.via };
    this.render(macro.children, {
      tpl: mtpl, overrides: null, params, via, depth: ctx.depth + 1, out: ctx.out,
    });
    ctx.out.push('\n', file, n.line, ctx.via);
  }
}
