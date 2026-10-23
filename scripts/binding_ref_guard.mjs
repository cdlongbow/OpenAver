#!/usr/bin/env node
/**
 * binding_ref_guard.mjs — SPIKE（plan-179 T1）。非產品碼；GO 後由 T2/T3 整理。
 * 用法：node scripts/binding_ref_guard.mjs [root]
 * SPIKE_DUMP=<path> 另輸出完整 JSON（量測用；計時時不設）。
 */
import { readdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Expander, ToolError } from './lib/jinja-lite.mjs';
import { _parseCache } from './lib/binding-expr.mjs';
import { buildRegistry } from './lib/alpine-registry.mjs';
import {
  parseHtml, measureImbalance, deriveAppGlobals, walkEntry, BROWSER_CANDIDATES, MAGICS,
} from './lib/binding-scope.mjs';

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
// CD-179-8(3ii) 具名補充表：模板裸名使用「JS 模組／頁面 script 指定到 window」的東西。每項附理由與指定檔；過期偵測＝檔內仍有 `window.X =`
const EXTRA_WINDOW_GLOBALS = {
  GhostFly: { file: 'web/static/js/shared/ghost-fly.js', why: 'base.html:867 module 載入；search.html:1000／showcase.html:500 以 `window.GhostFly && GhostFly.floatingHearts($el)` 裸用' },
  toggleThemeWithTransition: { file: 'web/static/js/pages/settings/theme-transition.js', why: 'settings.html:1728 classic script 載入；settings.html:183 @click 裸用' },
};
const registry = buildRegistry(root);
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
    for (const [n, x] of Object.entries(EXTRA_WINDOW_GLOBALS)) {
      const src = readFileSync(join(root, x.file), 'utf8');
      if (!new RegExp(`window\\.${n}\\s*=`).test(src)) toolErrors.push(`stale EXTRA_WINDOW_GLOBALS entry ${n} (${x.file})`);
      appGlobals.set(n, `EXTRA ${x.file}`);
    }
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
const ms = performance.now() - t0;

const lines = [];
lines.push(`binding_ref_guard SPIKE: entries=${entries.length} (${entries.join(', ')})`);
lines.push(`unique bindings=${uniqBindings.size} refs=${uniqRefs.size} unresolved=${unresolved.length} findings(x-data)=${findings.size} K1 failures=${failures.size} unknown-directives=${unknownDirs.size} toolErrors=${toolErrors.length}`);
lines.push(`uncovered templates=${uncovered.length} orphan fragments=${orphanFragments.length} ${(ms / 1000).toFixed(2)}s`);
console.log(lines.join('\n'));

if (process.env.SPIKE_DUMP) {
  const catByName = new Map();
  for (const r of uniqRefs.values()) {
    if (!catByName.has(r.name)) catByName.set(r.name, { cats: {}, locs: [] });
    const e = catByName.get(r.name);
    const c = r.cat === null ? 'UNRESOLVED' : r.cat;
    e.cats[c] = (e.cats[c] || 0) + 1;
    if (e.locs.length < 200) {
      e.locs.push({
        cat: c, file: r.origin.file, line: r.origin.line, via: r.origin.via ? `${r.origin.via.kind}@${r.origin.via.file}:${r.origin.via.line}` : null,
        attr: r.attrName, value: r.attrValue.length > 160 ? `${r.attrValue.slice(0, 160)}…` : r.attrValue, entries: [...r.entries],
      });
    }
  }
  const regInfo = {};
  for (const [name, reg] of registry.regs) {
    let keys = null; let err = null;
    try { keys = [...registry.resolveReg(reg)]; } catch (e) { err = e.message; }
    regInfo[name] = { file: reg.file, line: reg.line, source: reg.source, keys: keys ? keys.length : null, err, notes: reg.notes || [], pageName: reg.pageName };
  }
  writeFileSync(process.env.SPIKE_DUMP, JSON.stringify({
    entries, fragments, allTpl, scanned: entries, excluded: allTpl.filter(isExcluded),
    expandedFragments: [...exp.expandedFragments], uncovered, orphanFragments,
    macroCalls: [...exp.macroCalls], expStats: exp.stats,
    dirCount, physDir, physTotal: physBindings.size, perEntryBindingCount, uniqueBindings: uniqBindings.size, expandedByEntry,
    failures: [...failures.values()].map((f) => ({ file: f.origin.file, line: f.origin.line, attr: f.attr.slice(0, 300), errs: f.errs })),
    unknownDirs: [...unknownDirs.values()].map((u) => ({ name: u.name, file: u.origin.file, line: u.origin.line })),
    findingsX: [...findings.values()].map((f) => ({ name: f.name, file: f.origin.file, line: f.origin.line, attr: f.attr, entry: f.entry })),
    unresolved: unresolved.map((r) => ({
      name: r.name, file: r.origin.file, line: r.origin.line, via: r.origin.via ? `${r.origin.via.kind}@${r.origin.via.file}:${r.origin.via.line}` : null,
      attr: r.attrName, value: r.attrValue.length > 300 ? `${r.attrValue.slice(0, 300)}…` : r.attrValue, write: r.write, entries: [...r.entries], tag: r.tag,
    })),
    byName: Object.fromEntries([...catByName.entries()].sort()),
    typeofUses, emptyAttrs, imbalance, parseErrCodes, toolErrors, appGlobals: [...appGlobals.entries()], appGlobalErrors,
    regInfo, regUse: [...regUse.entries()], pages: registry.pages.map((p) => ({ page: p.page, contributors: p.contributors.length, keys: p.contributors.reduce((n, c) => n + c.keys.size, 0) })),
    browserCandidates: [...BROWSER_CANDIDATES], magics: [...MAGICS],
    plainAttrNames: [...plainAttrNames.entries()].filter(([n]) => /expanded|^data-x|^x-/.test(n)),
    parseStages: { expr: [..._parseCache.values()].filter((v) => v.wrap === 'expr').length, stmts: [..._parseCache.values()].filter((v) => v.wrap === 'stmts').length, fail: [..._parseCache.values()].filter((v) => v.fail).length },
    ms,
  }, null, 1));
}

process.exit(toolErrors.length || uncovered.length ? 2 : unresolved.length || findings.size ? 1 : 0);
