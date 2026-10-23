/**
 * binding-ref-guard.test.mjs — `scripts/binding_ref_guard.mjs` 黑箱測試（plan-179 T2）
 * 手法比照 state-key-guard.test.mjs；每支測試先在乾淨 scratch 斷言 exit 0（綠對照），再做紅格。
 * 紅格一律斷言「exit code ＋ 輸出含名字／原因關鍵字 ＋ 無 stack trace」——崩潰也是 exit 1。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BROWSER_GLOBALS, EXTRA_WINDOW_GLOBALS } from '../lib/binding-guard-config.mjs';

const GUARD = join(dirname(fileURLToPath(import.meta.url)), '..', 'binding_ref_guard.mjs');
const IMPORTS = { '@/shared/': '/static/js/shared/', '@/demo/': '/static/js/pages/demo/' };

function writeAt(root, rel, content) {
  const abs = join(root, ...rel.split('/'));
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content);
}

/** 乾淨 scratch：base.html（用到全部瀏覽器全域）＋ mergeState 頁 ＋ 展開工廠 widget ＋ 兩個 EXTRA 指定檔 */
function makeScratch(root, pageHtml = '', extraJs = {}, gOverride = {}) {
  writeAt(root, 'web/templates/base.html',
    `<script type="importmap">${JSON.stringify({ imports: IMPORTS })}</script>\n<body x-data="demoPage"><p x-text="[${Object.keys(BROWSER_GLOBALS).map((n) => gOverride[n] || n).join(', ')}].length"></p></body>\n`);
  if (pageHtml) writeAt(root, 'web/templates/p.html', pageHtml);
  writeAt(root, 'web/static/js/pages/demo/main.js',
    "import { shardA } from '@/demo/shardA.js';\nimport { mergeState } from '@/shared/merge-state.js';\nAlpine.data('demoPage', () => mergeState(shardA()));\n");
  writeAt(root, 'web/static/js/pages/demo/shardA.js', 'export function shardA() {\n  return { a: 1, list: [], go() {} };\n}\n');
  writeAt(root, 'web/static/js/pages/demo/widget.js',
    "import { toast } from '../../shared/toast.js';\nAlpine.data('widget', () => ({ w1: 1, ...toast() }));\n");
  writeAt(root, 'web/static/js/shared/toast.js', 'export function toast() {\n  return { t1: 1 };\n}\n');
  for (const [n, x] of Object.entries(EXTRA_WINDOW_GLOBALS)) writeAt(root, x.file, `window.${n} = 1;\n`);
  for (const [rel, c] of Object.entries(extraJs)) writeAt(root, rel, c);
}

function run(pageHtml, extraJs, gOverride) {
  const root = mkdtempSync(join(tmpdir(), 'binding-ref-guard-'));
  try {
    makeScratch(root, pageHtml, extraJs, gOverride);
    const r = spawnSync(process.execPath, [GUARD, root], { encoding: 'utf8' });
    const output = `${r.stdout}\n${r.stderr}`;
    assert.ok(!output.includes('\n    at '), `stack trace:\n${output}`);
    return { status: r.status, output };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('legal bindings pass', () => {
  const ok = run('');
  assert.equal(ok.status, 0, ok.output);
  const r = run(`<div x-data="demoPage"><div x-data="widget">
  <span x-text="a + w1 + t1"></span>
  <template x-for="(item, i) in list"><b x-text="item.n + i" @click="go(item)"></b></template>
  <template x-for="{id, name} in list"><b x-text="id + name"></b></template>
  <i x-text="list.filter(s => s.trim()).map(({q}) => q).length"></i>
  <i x-show="typeof maybeGlobal !== 'undefined'"></i>
  <i x-ref="foo" x-text="$refs.foo"></i></div>
  <div x-data="{ open: false }" @click="open = !open" x-show="open && a"></div></div>`);
  assert.equal(r.status, 0, r.output);
  const onlyTypeof = run('', {}, { Number: "typeof Number === 'function' && Number(1)" });
  assert.equal(onlyTypeof.status, 0, onlyTypeof.output);
});

test('dangling names fail', () => {
  assert.equal(run('').status, 0);
  const cases = [
    ['gooo', '<div x-data="demoPage"><b @click="gooo()"></b></div>'],
    ['item', '<div x-data="demoPage"><template x-for="b in list"><i x-text="item.n"></i></template></div>'],
    ['foo', '<div x-data="demoPage"><i x-ref="foo"></i><i x-text="foo"></i></div>'],
    ['__b', '<div x-data="demoPage"><b @click="__b()"></b></div>'],
    ['nowhere', '<div x-data="nowhere"></div>'],
  ];
  for (const [name, html] of cases) {
    const r = run(html);
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, new RegExp(`p\\.html:\\d+[^\\n]*\\n\\s+${name} 不在`));
  }
});

test('unreadable input exits 2', () => {
  assert.equal(run('<div x-data="widget"></div>').status, 0);
  const bad = [
    ['spread', '<div x-data="bad"></div>', { 'web/static/js/pages/demo/bad.js': "Alpine.data('bad', () => ({ b: 1, ...someObj }));\n" }],
    ['shardA.js', '', { 'web/static/js/pages/demo/shardA.js': 'export function shardA() {\n  return { a: 1, ...someObj };\n}\n' }],
    ['未登記指令', '<div x-foo="1"></div>', {}],
    ['過期', '', { 'web/static/js/shared/ghost-fly.js': 'export const x = 1;\n' }],
  ];
  for (const [kw, html, js] of bad) {
    const r = run(html, js);
    assert.equal(r.status, 2, r.output);
    assert.ok(r.output.includes(kw), r.output);
  }
});

test('jinja and macros expand at the call site', () => {
  const pill = "{% macro pill(loading_expr='false', attrs='') %}\n<button x-show=\"{{ loading_expr }}\" {{ attrs|safe }}></button>\n{% endmacro %}\n";
  const panel = (fn) => `{% macro panel() %}\n<div x-show="open" @keydown.escape.window="open && ${fn}()"></div>\n{% endmacro %}\n`;
  const page = (close) => `{% from '_macros/pill.html' import pill %}\n{% from '_macros/panel.html' import panel %}\n{# <b @click="gooo()"></b> #}\n<!-- <b @click="gooo()"></b> -->\n<div x-data="demoPage" class="{{ x|default('light') }}">\n  {% if a %}<b></b>{% else %}<i></i>{% endif %}\n  <i data-x-show="gooo"></i>\n  {{ pill(loading_expr='a', attrs='@click="go()"') }}\n  <div x-data="{ open: false, ${close}() {} }">\n    {{ panel() }}\n  </div>\n</div>\n`;
  const macros = (fn) => ({ 'web/templates/_macros/pill.html': pill, 'web/templates/_macros/panel.html': panel(fn) });
  const ok = run(page('close'), macros('close'));
  assert.equal(ok.status, 0, ok.output);
  const red = run(page('shut'), macros('close'));
  assert.equal(red.status, 1, red.output);
  const callLine = page('shut').split('\n').findIndex((l) => l.includes('{{ panel() }}')) + 1;
  const first = red.output.split('\n').find((l) => l.startsWith('✗ '));
  assert.ok(first.startsWith(`✗ web/templates/p.html:${callLine}`) && first.includes('(macro: '), red.output);
  assert.ok(!red.output.split('\n').some((l) => l.startsWith('✗ web/templates/_macros/')), red.output);
});

test('uncovered templates exit 2', () => {
  const orphan = '<b @click="zzz()"></b>\n';
  const n = (o) => Number((/(\d+) 模板/.exec(o) || [])[1]);
  const base = run('');
  assert.equal(base.status, 0, base.output);
  const failures = [];
  const cells = [['cell A', '_orphan.html'], ['cell B', 'foo/x.html']];
  for (const [label, rel] of cells) {
    const r = run('', { [`web/templates/${rel}`]: orphan });
    if (r.status !== 2 || !r.output.includes(rel)) failures.push(`${label}: ${r.status}\n${r.output}`);
  }
  const g = run('', { 'web/templates/newpage.html': '<div x-data="demoPage"></div>\n' });
  if (g.status !== 0 || n(g.output) !== n(base.output) + 1) failures.push(`cell green: ${g.status}\n${g.output}`);
  assert.deepEqual(failures, []);
});

test('exit code follows findings', () => {
  assert.equal(run('<div x-data="demoPage"><i x-text="list"></i></div>').status, 0);
  const r = run('<div x-data="demoPage"><i x-text="lisst"></i></div>');
  assert.equal(r.status, 1, r.output);
  assert.match(r.output, /lisst 不在 p 頁任何狀態來源/);
  assert.match(r.output, /相近：[^\n]*\blist\b/);
});
