/**
 * binding-scope.mjs — SPIKE（plan-179 T1，CD-179-3／-6／-8）
 * parse5 樹走訪＋scope 棧；對每個綁定算自由識別字並分類到 spec §3 類別。
 */
import * as parse5 from 'parse5';
import { parse as espreeParse } from 'espree';
import {
  classifyAttr, parseExpr, freeIds, splitFor, forLoopVars,
} from './binding-expr.mjs';

export const MAGICS = new Set([
  '$el', '$refs', '$store', '$watch', '$dispatch', '$nextTick', '$event', '$root', '$data', '$id',
  '$persist', '$focus', '$anchor',
]);

/** 策展瀏覽器全域（候選集合；T1 從全樹反推實際用到者）。刻意不收 close open stop focus print name status find top parent length */
export const BROWSER_CANDIDATES = new Set([
  'window', 'document', 'console', 'event', 'location', 'navigator', 'history', 'localStorage', 'sessionStorage',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame',
  'fetch', 'Math', 'JSON', 'Date', 'Number', 'String', 'Boolean', 'Array', 'Object', 'Promise', 'parseInt',
  'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI',
  'Intl', 'RegExp', 'Set', 'Map', 'Symbol', 'Error', 'URL', 'URLSearchParams', 'undefined', 'NaN', 'Infinity',
  'alert', 'confirm', 'prompt', 'CSS', 'getComputedStyle', 'matchMedia', 'screen', 'performance', 'structuredClone',
  'Event', 'CustomEvent', 'AbortController', 'FormData', 'Blob', 'File', 'FileReader', 'Image', 'Audio', 'crypto',
  'queueMicrotask', 'atob', 'btoa', 'Reflect', 'Proxy', 'BigInt', 'WeakMap', 'WeakSet', 'globalThis',
]);

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
const OPTIONAL_END = new Set([
  'p', 'li', 'option', 'optgroup', 'tr', 'td', 'th', 'dt', 'dd', 'thead', 'tbody', 'tfoot', 'colgroup',
  'html', 'head', 'body', 'caption', 'rt', 'rp',
]);

const HTML_NS = 'http://www.w3.org/1999/xhtml';

export function parseHtml(text) {
  const errors = [];
  const doc = parse5.parse(text, {
    sourceCodeLocationInfo: true,
    onParseError: (e) => errors.push(e),
  });
  return { doc, errors };
}

function childrenOf(node) {
  if (node.nodeName === 'template' && node.content) return node.content.childNodes;
  return node.childNodes || [];
}

function isElement(n) { return n.tagName !== undefined; }

/** CD-179-3：標籤不平衡量測 */
export function measureImbalance(doc, errors, text) {
  const missing = [];
  (function w(n) {
    if (isElement(n)) {
      const tag = n.tagName;
      const loc = n.sourceCodeLocation;
      if (loc && !VOID.has(tag) && !OPTIONAL_END.has(tag) && !loc.endTag) {
        const foreign = n.namespaceURI !== HTML_NS;
        const st = loc.startTag;
        const selfClosed = st && text.slice(st.startOffset, st.endOffset).endsWith('/>');
        if (!(foreign && selfClosed)) missing.push({ tag, line: loc.startLine });
      }
    }
    for (const c of childrenOf(n)) w(c);
  })(doc);
  const stray = errors.filter((e) => e.code === 'end-tag-without-matching-open-element')
    .map((e) => ({ code: e.code, line: e.startLine }));
  return { missing, stray };
}

/** base.html 內嵌經典 script → 應用全域名單 */
export function deriveAppGlobals(doc) {
  const names = new Map(); // name → how
  const errors = [];
  (function w(n) {
    if (isElement(n) && n.tagName === 'script') {
      const hasSrc = n.attrs.some((a) => a.name === 'src');
      const type = (n.attrs.find((a) => a.name === 'type') || {}).value;
      if (!hasSrc && (!type || type === 'text/javascript')) {
        const code = (n.childNodes[0] && n.childNodes[0].value) || '';
        let ast;
        try {
          ast = espreeParse(code, { ecmaVersion: 2024, sourceType: 'script', loc: true });
        } catch (e) {
          errors.push(`inline script at line ${n.sourceCodeLocation && n.sourceCodeLocation.startLine}: ${e.message}`);
          ast = null;
        }
        if (ast) {
          for (const st of ast.body) {
            if (st.type === 'FunctionDeclaration') names.set(st.id.name, 'function decl');
            if (st.type === 'VariableDeclaration') {
              for (const d of st.declarations) if (d.id.type === 'Identifier') names.set(d.id.name, `${st.kind} decl`);
            }
          }
          (function walkAst(x) {
            if (!x || typeof x !== 'object') return;
            if (Array.isArray(x)) { x.forEach(walkAst); return; }
            if (x.type === 'AssignmentExpression' && x.left.type === 'MemberExpression' && !x.left.computed
              && x.left.object.type === 'Identifier' && x.left.object.name === 'window'
              && x.left.property.type === 'Identifier') names.set(x.left.property.name, 'window.X =');
            for (const k of Object.keys(x)) {
              if (k === 'loc' || k === 'range') continue;
              if (x[k] && typeof x[k] === 'object') walkAst(x[k]);
            }
          })(ast);
        }
      }
    }
    for (const c of childrenOf(n)) w(c);
  })(doc);
  return { names, errors };
}

/**
 * 分析一個入口（已 parse5 化）。
 * opts: { entry, origins, registry, appGlobals:Set, record(ref), onBinding(b), onFailure(f), onUnknown(u), onFinding(f), onToolError(msg) }
 */
export function walkEntry(doc, opts) {
  const { origins, registry } = opts;
  const originOf = (line) => origins[line - 1] || { file: '?', line };

  function lookup(name, stack) {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].keys.has(name)) return { cat: stack[i].cat, scope: stack[i] };
    }
    if (MAGICS.has(name)) return { cat: 7, scope: { label: 'magic' } };
    if (opts.appGlobals.has(name)) return { cat: 6, scope: { label: 'app-global' } };
    if (BROWSER_CANDIDATES.has(name)) return { cat: 8, scope: { label: 'browser-global' } };
    return null;
  }

  function checkAttrExpr(value, ctxEl, attr, stack, extra = {}) {
    const parsed = parseExpr(value);
    const o = originOf(attr.line);
    if (parsed.fail) {
      opts.onFailure({ origin: o, attr: `${attr.name}="${value}"`, errs: parsed.fail });
      return null;
    }
    const { ids, typeofNames } = freeIds(parsed, value);
    const results = [];
    for (const id of ids) {
      if (extra.skipStart !== undefined && id.start === extra.skipStart && id.name === extra.skipName) continue;
      if (typeofNames.has(id.name)) { opts.onTypeof && opts.onTypeof({ origin: o, name: id.name, attr: attr.name }); continue; }
      const res = lookup(id.name, stack);
      const refOrigin = originOf(attr.line + id.line - 1);
      const rec = {
        name: id.name,
        cat: res ? res.cat : null,
        write: id.write,
        origin: attr.line + id.line - 1 === attr.line ? o : refOrigin,
        attrName: attr.name,
        attrValue: value,
        entry: opts.entry,
        scopeLabel: res ? res.scope.label : null,
        tag: ctxEl.tagName,
      };
      opts.record(rec);
      results.push(rec);
    }
    return { parsed, ids, results };
  }

  function dataScope(el, attr, stack, isAncestorEl) {
    const value = attr.value.trim();
    const o = originOf(attr.line);
    const mk = (keys, cat, label, extra = {}) => ({ keys, cat, label, ...extra });
    if (value === '') return mk(new Set(), 3, 'empty x-data');
    const parsed = parseExpr(value);
    if (parsed.fail) { opts.onFailure({ origin: o, attr: `x-data="${value}"`, errs: parsed.fail }); return null; }
    if (parsed.wrap !== 'expr') { opts.onToolError(`x-data is not an expression at ${o.file}:${o.line}`); return null; }
    const expr = parsed.ast.body[0].expression;
    const hasComponentAncestor = stack.some((s) => s.component);
    if (expr.type === 'ObjectExpression') {
      const keys = new Set();
      for (const p of expr.properties) {
        if (p.type !== 'Property' || p.computed) { opts.onToolError(`x-data object has ${p.type}/computed key at ${o.file}:${o.line}`); return null; }
        if (p.key.type === 'Identifier') keys.add(p.key.name);
        else if (p.key.type === 'Literal') keys.add(String(p.key.value));
        else { opts.onToolError(`x-data key type ${p.key.type} at ${o.file}:${o.line}`); return null; }
      }
      checkAttrExpr(value, el, attr, stack);
      const cat = isAncestorEl ? 5 : 3;
      return mk(keys, cat, `literal x-data @${o.file}:${o.line}`, { component: !isAncestorEl });
    }
    let calleeName;
    if (expr.type === 'Identifier') { calleeName = expr.name; }
    else if (expr.type === 'CallExpression' && expr.callee.type === 'Identifier') {
      calleeName = expr.callee.name;
    } else { opts.onToolError(`x-data shape ${expr.type} at ${o.file}:${o.line}`); return null; }
    if (expr.type === 'CallExpression') checkAttrExpr(value, el, attr, stack, { skipStart: expr.callee.range[0], skipName: calleeName });
    const reg = registry.regs.get(calleeName);
    if (!reg) {
      opts.onFinding({
        kind: 'x-data-unregistered', name: calleeName, origin: o, attr: `x-data="${value}"`, entry: opts.entry,
      });
      return mk(new Set(), 4, `unregistered ${calleeName}`, { component: true });
    }
    let keys;
    try { keys = registry.resolveReg(reg); } catch (e) {
      opts.onToolError(`registry ${calleeName}: ${e.message}`);
      return null;
    }
    let cat;
    if (reg.source === 'mergeState') cat = hasComponentAncestor ? 4 : 1;
    else cat = hasComponentAncestor ? 4 : 2;
    opts.onRegUse && opts.onRegUse(reg, cat);
    return mk(keys, cat, `Alpine.data('${calleeName}')`, { component: true });
  }

  function walk(node, stack) {
    if (!isElement(node)) {
      for (const c of childrenOf(node)) walk(c, stack);
      return;
    }
    const loc = node.sourceCodeLocation;
    const attrLine = (name) => (loc && loc.attrs && loc.attrs[name] ? loc.attrs[name].startLine : loc.startLine);
    let st = stack;
    const attrs = node.attrs.map((a) => ({ name: a.name, value: a.value, line: attrLine(a.name) }));
    const tag = node.tagName;
    // 1. x-data 先
    const xd = attrs.find((a) => a.name === 'x-data');
    if (xd) {
      opts.onBinding({ dir: 'data', name: 'x-data', origin: originOf(xd.line), entry: opts.entry });
      const sc = dataScope(node, xd, stack, tag === 'html' || tag === 'body');
      if (sc) st = [...stack, sc];
    }
    // 2. x-for
    let childStack = st;
    const xf = attrs.find((a) => a.name === 'x-for');
    if (xf) {
      opts.onBinding({ dir: 'for', name: 'x-for', origin: originOf(xf.line), entry: opts.entry });
      const sp = splitFor(xf.value);
      const o = originOf(xf.line);
      if (!sp) opts.onFailure({ origin: o, attr: `x-for="${xf.value}"`, errs: ['x-for regex did not match'] });
      else {
        checkAttrExpr(sp.list, node, { name: 'x-for(list)', line: xf.line, value: sp.list }, st);
        const lv = forLoopVars(sp.lhs);
        if (lv.fail) opts.onFailure({ origin: o, attr: `x-for="${xf.value}"`, errs: [lv.fail] });
        else {
          for (const nm of lv.through) {
            const res = lookup(nm, st);
            opts.record({
              name: nm, cat: res ? res.cat : null, origin: o, attrName: 'x-for(default)', attrValue: xf.value, entry: opts.entry,
            });
          }
          childStack = [...st, { keys: new Set(lv.names), cat: 7, label: `x-for ${lv.names.join(',')}`, loop: true }];
        }
      }
    }
    // 3. 其他屬性
    for (const a of attrs) {
      if (a.name === 'x-data' || a.name === 'x-for') continue;
      const cls = classifyAttr(a.name);
      if (cls.kind === 'plain') {
        opts.onPlainAttr && opts.onPlainAttr({ name: a.name, origin: originOf(a.line), entry: opts.entry });
        continue;
      }
      if (cls.kind === 'unknown') {
        opts.onUnknown({ name: a.name, dir: cls.dir, origin: originOf(a.line), entry: opts.entry });
        continue;
      }
      if (cls.kind === 'noexpr') continue;
      opts.onBinding({ dir: cls.dir, name: a.name, origin: originOf(a.line), entry: opts.entry });
      if (a.value.trim() === '') { opts.onEmpty && opts.onEmpty({ name: a.name, origin: originOf(a.line) }); continue; }
      const useStack = (xf && a.name === ':key') || (xf && a.name === 'x-bind:key') ? childStack : st;
      checkAttrExpr(a.value, node, a, useStack);
    }
    for (const c of childrenOf(node)) walk(c, childStack);
  }

  walk(doc, []);
}
