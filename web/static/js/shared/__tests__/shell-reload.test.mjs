// 168e-T6: 殼內 F5／Ctrl+R／Cmd+R 重新整理（一般頁／離線小頁／閘門頁）
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

globalThis.window = globalThis;
let reloads = 0;
globalThis.location = { reload: () => { reloads += 1; } };

const { onShellReloadKey } = await import('../shell-reload.js');

const OFFLINE = new URL('../../../../../windows/offline/offline.html', import.meta.url);
const GATE = new URL('../../../../templates/access_gate.html', import.meta.url);

function ev(key, mods = {}) {
  const e = { key, ctrlKey: false, metaKey: false, shiftKey: false, prevented: 0, ...mods };
  e.preventDefault = () => { e.prevented += 1; };
  return e;
}

function fakeEl() {
  const handlers = {};
  return {
    hidden: false, disabled: false, textContent: '', value: '', dataset: {}, clicks: 0, handlers,
    addEventListener(type, fn) { handlers[type] = fn; },
    click() { this.clicks += 1; },
  };
}

// 抽出 html 內唯一一段無屬性 <script>，丟進 node vm 執行；回 { ctx, els, keydown }（keydown＝掛在 document 的 handler）
function loadInline(url, { shell }) {
  const html = readFileSync(url, 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(m, 'inline <script> not found');
  const els = {};
  const docHandlers = {};
  const ctx = {
    document: {
      getElementById(id) { return (els[id] = els[id] || fakeEl()); },
      addEventListener(type, fn) { docHandlers[type] = fn; },
    },
    setTimeout: () => 0,
    location: { reload: () => { ctx.reloads += 1; } },
    fetch: () => Promise.resolve({}),
    Promise,
    reloads: 0,
    addEventListener() {},
  };
  ctx.window = ctx;
  if (shell) ctx.pywebview = {};
  vm.runInNewContext(m[1], ctx);
  return { ctx, els, keydown: docHandlers.keydown || (() => {}) };
}

beforeEach(() => {
  reloads = 0;
  delete globalThis.pywebview;
});

test('shell-reload 一般頁：F5／Ctrl+R／Cmd+R 在殼裡各 reload 恰一次且 preventDefault', () => {
  globalThis.pywebview = {};
  const cases = [ev('F5'), ev('r', { ctrlKey: true }), ev('r', { metaKey: true }), ev('R', { ctrlKey: true }), ev('R', { metaKey: true })];
  for (const e of cases) {
    reloads = 0;
    onShellReloadKey(e);
    assert.equal(e.prevented, 1, `preventDefault ${e.key}`);
    assert.equal(reloads, 1, `reload ${e.key}`);
  }
});


