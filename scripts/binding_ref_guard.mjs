#!/usr/bin/env node
/**
 * binding_ref_guard.mjs — 模板綁定守衛 CLI（plan-179；輸出格式定稿屬 T3）
 * 用法：node scripts/binding_ref_guard.mjs [root]
 * exit 0＝乾淨；1＝有 finding；2＝工具讀不懂（未登記指令／運算式解析失敗／過期表項／未覆蓋模板）
 */
import { readdirSync, writeFileSync, readFileSync } from 'node:fs';
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
const fragments = allTpl.filter((r) => (r.includes('/') || r.startsWith('_')) && !isExcluded(r));

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

const uniqBindings = new Map();   // key → {dir,name,origin}
const physBindings = new Map();   // 物理位置 file:line:name（忽略 via）
const perEntryBindingCount = {};
const uniqRefs = new Map();       // file:line:name:attr:via → rec
const failures = new Map();
const unknownDirs = new Map();
const findings = new Map();
const typeofUses = [];
const emptyAttrs = [];
const imbalance = {};
const parseErrCodes = {};
const regUse = new Map();
const plainAttrNames = new Map();
const expandedByEntry = {};
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
  expandedByEntry[entry] = { lines: ex.origins.length, used: [...ex.used] };
  const { doc, errors } = parseHtml(ex.text);
  const im = measureImbalance(doc, errors, ex.text);
  imbalance[entry] = {
    missingEnd: im.missing.map((m) => ({ ...m, origin: ex.origins[m.line - 1] })),
    stray: im.stray.map((m) => ({ ...m, origin: ex.origins[m.line - 1] })),
  };
  for (const e of errors) parseErrCodes[e.code] = (parseErrCodes[e.code] || 0) + 1;
  if (entry === 'base.html') {
    const g = deriveAppGlobals(doc);
    appGlobals = g.names;
    for (const [n, x] of Object.entries(EXTRA_WINDOW_GLOBALS)) appGlobals.set(n, `EXTRA ${x.file}`);
    appGlobalErrors = g.errors;
  }
  perEntryBindingCount[entry] = 0;
  walkEntry(doc, {
    entry,
    origins: ex.origins,
    registry,
    appGlobals: new Set(appGlobals.keys()),
    record(r) {
      const k = `${siteKey(r.origin)}:${r.name}:${r.attrName}`;
      if (!uniqRefs.has(k)) uniqRefs.set(k, { ...r, entries: new Set([entry]) });
      else uniqRefs.get(k).entries.add(entry);
    },
    onBinding(b) {
      perEntryBindingCount[entry]++;
      const k = `${siteKey(b.origin)}:${b.name}`;
      if (!uniqBindings.has(k)) uniqBindings.set(k, b);
      const pk = `${b.origin.file}:${b.origin.line}:${b.name}`;
      if (!physBindings.has(pk)) physBindings.set(pk, b);
    },
    onFailure(f) { failures.set(`${siteKey(f.origin)}:${f.attr}`, f); },
    onUnknown(u) { unknownDirs.set(`${siteKey(u.origin)}:${u.name}`, u); },
    onFinding(f) { findings.set(`${siteKey(f.origin)}:${f.name}`, f); },
    onTypeof(t) { typeofUses.push(t); },
    onEmpty(x) { emptyAttrs.push({ ...x, entry }); },
    onToolError(m) { toolErrors.push(`scope ${entry}: ${m}`); },
    onRegUse(reg, cat) { regUse.set(reg.name, { cat, source: reg.source }); },
    onPlainAttr(p) { plainAttrNames.set(p.name, (plainAttrNames.get(p.name) || 0) + 1); },
  });
}

// 覆蓋不變式
const covered = new Set([...entries, ...exp.expandedFragments, ...allTpl.filter(isExcluded)]);
const uncovered = allTpl.filter((r) => !covered.has(r));
const orphanFragments = fragments.filter((r) => !exp.expandedFragments.has(r));

// 殘餘
const unresolved = [...uniqRefs.values()].filter((r) => r.cat === null);
const dirCount = {};
for (const b of uniqBindings.values()) {
  const key = b.dir === 'bind' ? ':attr' : b.dir === 'on' ? '@event' : `x-${b.dir}`;
  dirCount[key] = (dirCount[key] || 0) + 1;
}
const physDir = {};
for (const b of physBindings.values()) {
  const key = b.dir === 'bind' ? ':attr' : b.dir === 'on' ? '@event' : `x-${b.dir}`;
  physDir[key] = (physDir[key] || 0) + 1;
}
// 讀不懂 ＝ 工具錯誤（exit 2），不是 finding
for (const f of failures.values()) toolErrors.push(`${f.origin.file}:${f.origin.line}: 運算式解析失敗 ${f.attr.slice(0, 80)}`);
for (const u of unknownDirs.values()) toolErrors.push(`${u.origin.file}:${u.origin.line}: 未登記指令 ${u.name}`);
for (const e of appGlobalErrors) toolErrors.push(`base.html 內嵌 script 解析失敗: ${e}`);
// typeof 豁免只影響「算不算懸空」；被豁免的名字仍算「有被引用」
const usedBrowser = new Set([...uniqRefs.values()].filter((r) => r.cat === 8).map((r) => r.name).concat(typeofUses.map((t) => t.name)));
for (const m of findStaleEntries(usedBrowser, root)) toolErrors.push(m);
const ms = performance.now() - t0;

const lines = [];
lines.push(`binding_ref_guard: entries=${entries.length} (${entries.join(', ')})`);
lines.push(`unique bindings=${uniqBindings.size} refs=${uniqRefs.size} unresolved=${unresolved.length} findings(x-data)=${findings.size} K1 failures=${failures.size} unknown-directives=${unknownDirs.size} toolErrors=${toolErrors.length}`);
lines.push(`uncovered templates=${uncovered.length} orphan fragments=${orphanFragments.length} ${(ms / 1000).toFixed(2)}s`);
console.log(lines.join('\n'));

for (const t of toolErrors) console.log(`工具錯誤: ${t}`);
for (const u of unresolved) console.log(`✗ ${u.origin.file}:${u.origin.line}  ${u.name}`);
for (const f of findings.values()) console.log(`✗ ${f.origin.file}:${f.origin.line}  ${f.name}`);

process.exit(toolErrors.length || uncovered.length ? 2 : unresolved.length || findings.size ? 1 : 0);
