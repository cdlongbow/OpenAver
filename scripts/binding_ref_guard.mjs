#!/usr/bin/env node
/**
 * binding_ref_guard.mjs — 模板綁定守衛 CLI（plan-179）
 * 用法：node scripts/binding_ref_guard.mjs [root]
 * exit 0＝乾淨；1＝有 finding；2＝工具讀不懂（未登記指令／運算式解析失敗／標籤不平衡／過期表項／未覆蓋模板）
 */
import { readdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Expander, ToolError } from './lib/jinja-lite.mjs';
import { buildRegistry } from './lib/alpine-registry.mjs';
import { AlpineStateError } from './lib/alpine-state.mjs';
import { parseHtml, measureImbalance, deriveAppGlobals, walkEntry } from './lib/binding-scope.mjs';
import { EXTRA_WINDOW_GLOBALS, findStaleEntries } from './lib/binding-guard-config.mjs';

const t0 = performance.now();
const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(process.argv[2] || join(__dirname, '..'));
const tplRoot = join(root, 'web/templates');

const EXCLUDED_TOP = new Set(['design-system.html', 'motion_lab.html']);
const EXCLUDED_DIR = 'design_system/';

function listHtml(dir, prefix = '', out = []) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    if (ent.isDirectory()) listHtml(join(dir, ent.name), `${prefix}${ent.name}/`, out);
    else if (ent.name.endsWith('.html')) out.push(`${prefix}${ent.name}`);
  }
  return out.sort();
}

const allTpl = listHtml(tplRoot);
const isExcluded = (r) => EXCLUDED_TOP.has(r) || r.startsWith(EXCLUDED_DIR);
const entries = allTpl.filter((r) => !r.includes('/') && !r.startsWith('_') && !isExcluded(r));
// base.html 先跑（推導應用全域）
entries.sort((a, b) => (a === 'base.html' ? -1 : b === 'base.html' ? 1 : a.localeCompare(b)));

const toolErrors = [];
let registry;
try {
  registry = buildRegistry(root);
} catch (e) {
  if (!(e instanceof AlpineStateError)) throw e;
  console.log(`工具錯誤: registry: ${e.message}`);
  process.exit(2);
}
registry.toolErrors.forEach((e) => toolErrors.push(`registry: ${e}`));

const exp = new Expander(tplRoot);

const viaKey = (v) => (v ? `${v.kind}:${v.file}:${v.line}>${viaKey(v.parent)}` : '');
const siteKey = (o) => `${o.file}:${o.line}:${viaKey(o.via)}`;

const uniqBindings = new Map();   // 去重綁定（含 via）
const uniqRefs = new Map();       // 去重名字引用（含 via）
const failures = new Map();
const unknownDirs = new Map();
const findings = new Map();       // x-data 未註冊
const typeofUses = [];
let appGlobals = new Map();
let appGlobalErrors = [];

for (const entry of entries) {
  let ex;
  try {
    ex = exp.expandEntry(entry);
  } catch (e) {
    if (e instanceof ToolError) { toolErrors.push(`jinja ${entry}: ${e.message} (${e.file}:${e.line})`); continue; }
    throw e;
  }
  const { doc, errors } = parseHtml(ex.text);
  const im = measureImbalance(doc, errors, ex.text);
  for (const m of [...im.missing.map((x) => ({ ...x, what: `<${x.tag}> 缺結束標籤` })), ...im.stray.map((x) => ({ ...x, what: '多餘的結束標籤' }))]) {
    const o = ex.origins[m.line - 1] || { file: entry, line: m.line };
    toolErrors.push(`標籤不平衡 ${m.what}: web/templates/${o.file}:${o.line}（入口 ${entry}）`);
  }
  if (entry === 'base.html') {
    const g = deriveAppGlobals(doc);
    appGlobals = g.names;
    for (const [n, x] of Object.entries(EXTRA_WINDOW_GLOBALS)) appGlobals.set(n, `EXTRA ${x.file}`);
    appGlobalErrors = g.errors;
  }
  walkEntry(doc, {
    entry,
    origins: ex.origins,
    registry,
    appGlobals: new Set(appGlobals.keys()),
    record(r) {
      // 已解析與懸空分開去重：同一行同名的懸空不能被前一筆已解析的蓋掉
      const k = `${siteKey(r.origin)}:${r.name}:${r.attrName}:${r.cat === null ? 'U' : 'R'}`;
      if (!uniqRefs.has(k)) uniqRefs.set(k, { ...r, entries: new Set([entry]) });
      else uniqRefs.get(k).entries.add(entry);
    },
    onBinding(b) {
      const k = `${siteKey(b.origin)}:${b.name}`;
      if (!uniqBindings.has(k)) uniqBindings.set(k, b);
    },
    onFailure(f) { failures.set(`${siteKey(f.origin)}:${f.attr}`, f); },
    onUnknown(u) { unknownDirs.set(`${siteKey(u.origin)}:${u.name}`, u); },
    onFinding(f) {
      const k = `${siteKey(f.origin)}:${f.name}`;
      if (!findings.has(k)) findings.set(k, { ...f, entries: new Set([entry]) });
      else findings.get(k).entries.add(entry);
    },
    onTypeof(t) { typeofUses.push(t); },
    onToolError(m) { toolErrors.push(`scope ${entry}: ${m}`); },
  });
}

// 覆蓋不變式：已掃入口 ∪ 被展開片段 ∪ EXCLUDED ＝ web/templates/**/*.html
const covered = new Set([...entries, ...exp.expandedFragments, ...allTpl.filter(isExcluded)]);
const uncovered = allTpl.filter((r) => !covered.has(r));

// 讀不懂 ＝ 工具錯誤（exit 2），不是 finding
for (const f of failures.values()) toolErrors.push(`${f.origin.file}:${f.origin.line}: 運算式解析失敗 ${f.attr.slice(0, 80)}`);
for (const u of unknownDirs.values()) toolErrors.push(`${u.origin.file}:${u.origin.line}: 未登記指令 ${u.name}`);
for (const e of appGlobalErrors) toolErrors.push(`base.html 內嵌 script 解析失敗: ${e}`);
for (const r of uncovered) toolErrors.push(`web/templates/${r} 沒被任何入口涵蓋（不是入口、也沒被 include／macro 展開）`);
// typeof 豁免只影響「算不算懸空」；被豁免的名字仍算「有被引用」
const usedBrowser = new Set([...uniqRefs.values()].filter((r) => r.cat === 8).map((r) => r.name).concat(typeofUses.map((t) => t.name)));
for (const m of findStaleEntries(usedBrowser, root)) toolErrors.push(m);

// ---- 報告（spec §4）：以呼叫位置為主，同一 (位置,名字,屬性) 只報一次 ----
const tokens = (n) => n.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase().split(/[_\d]+/).filter(Boolean);
function lev(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[b.length];
}
function similar(name, candidates) {
  const tk = new Set(tokens(name));
  const limit = Math.max(2, Math.floor(name.length / 3));
  return [...new Set(candidates)].filter((c) => c !== name).map((c) => ({
    c, ov: tokens(c).filter((t) => tk.has(t)).length, d: lev(name.toLowerCase(), c.toLowerCase()),
  })).filter((x) => x.ov >= 1 || x.d <= limit)
    .sort((a, b) => b.ov - a.ov || a.d - b.d || (a.c < b.c ? -1 : a.c > b.c ? 1 : 0))
    .slice(0, 3).map((x) => x.c);
}
const clip = (v) => { const t = v.replace(/\s+/g, ' ').trim(); return t.length > 100 ? `${t.slice(0, 100)}…` : t; };

const reports = new Map();
function addReport(origin, name, attrText, attrKey, entrySet, candidates) {
  let call = null;                       // 最外層 macro 呼叫位置；include 只是物理檔案
  for (let v = origin.via; v; v = v.parent) if (v.kind === 'macro') call = v;
  const where = call ? { file: call.file, line: call.line } : origin;
  const k = `${where.file}:${where.line}|${name}|${attrKey}`;
  if (!reports.has(k)) {
    reports.set(k, {
      head: `✗ web/templates/${where.file}:${where.line}  ${clip(attrText)}${call ? ` (macro: ${origin.file}:${origin.line})` : ''}`,
      name, candidates, entrySet: new Set(),
    });
  }
  for (const e of entrySet) reports.get(k).entrySet.add(e);
}
for (const r of uniqRefs.values()) {
  if (r.cat !== null) continue;
  const attr = r.attrName.replace(/\(.*\)$/, '');
  addReport(r.origin, r.name, `${attr}="${r.attrValue}"`, attr, r.entries, similar(r.name, r.visible || []));
}
for (const f of findings.values()) {
  addReport(f.origin, f.name, f.attr, 'x-data', f.entries, similar(f.name, [...registry.regs.keys()]));
}
const order = (e) => entries.indexOf(e);
const reportLines = [];
for (const rp of reports.values()) {
  const es = [...rp.entrySet].sort((a, b) => order(a) - order(b));
  const page = (e) => e.replace(/\.html$/, '');
  const where = es.length === 1 ? `${page(es[0])} 頁任何狀態來源` : `${page(es[0])} 頁等 ${es.length} 頁共用的任何狀態來源`;
  reportLines.push(rp.head, `    ${rp.name} 不在 ${where}${rp.candidates.length ? `；相近：${rp.candidates.join(', ')}` : ''}`);
}

for (const t of toolErrors) console.log(`工具錯誤: ${t}`);
for (const l of reportLines) console.log(l);

if (!toolErrors.length && !reports.size) {
  const n = allTpl.filter((r) => covered.has(r) && !isExcluded(r)).length;
  console.log(`✓ binding_ref_guard: ${n} 模板 / ${uniqBindings.size} 綁定 / ${uniqRefs.size} 名字，${((performance.now() - t0) / 1000).toFixed(2)}s`);
}
process.exit(toolErrors.length || uncovered.length ? 2 : reports.size ? 1 : 0);
