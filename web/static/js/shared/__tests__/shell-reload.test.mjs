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

test('shell-reload 一般瀏覽器：無 window.pywebview 不攔不重載', () => {
  const cases = [ev('F5'), ev('r', { ctrlKey: true }), ev('r', { metaKey: true }), ev('R', { ctrlKey: true, shiftKey: true })];
  for (const e of cases) {
    onShellReloadKey(e);
    assert.equal(e.prevented, 0);
  }
  assert.equal(reloads, 0);
  // 離線頁與閘門頁同樣不攔
  for (const url of [OFFLINE, GATE]) {
    const { ctx, els, keydown } = loadInline(url, { shell: false });
    const e = ev('F5');
    keydown(e);
    assert.equal(e.prevented, 0);
    assert.equal(ctx.reloads, 0);
    assert.equal(els['retry-btn']?.clicks || 0, 0);
  }
});

test('shell-reload 離線小頁：快捷鍵只觸發重試、不 reload', () => {
  const { ctx, els, keydown } = loadInline(OFFLINE, { shell: true });
  assert.equal(typeof keydown, 'function');
  const btn = els['retry-btn'];
  btn.hidden = false;
  btn.disabled = false;
  for (const e of [ev('F5'), ev('r', { ctrlKey: true }), ev('r', { metaKey: true }), ev('R', { metaKey: true })]) {
    btn.clicks = 0;
    keydown(e);
    assert.equal(e.prevented, 1);
    assert.equal(btn.clicks, 1);
  }
  assert.equal(ctx.reloads, 0);
  // 正在重試（disabled）→ 不再點
  btn.disabled = true;
  btn.clicks = 0;
  const e2 = ev('F5');
  keydown(e2);
  assert.equal(btn.clicks, 0);
  assert.equal(ctx.reloads, 0);
});

test('shell-reload 離線小頁 relogin：重試鈕隱藏時不做事', () => {
  const { ctx, els, keydown } = loadInline(OFFLINE, { shell: true });
  const btn = els['retry-btn'];
  btn.hidden = true;
  btn.disabled = false;
  const e = ev('F5');
  keydown(e);
  assert.equal(btn.clicks, 0);
  assert.equal(ctx.reloads, 0);
});

test('shell-reload 其他按鍵不攔：單按 r、Ctrl+F、Ctrl+P、F12', () => {
  globalThis.pywebview = {};
  const keys = () => [ev('r'), ev('R'), ev('f', { ctrlKey: true }), ev('p', { ctrlKey: true }), ev('F12'), ev('p', { metaKey: true })];
  const batch = keys();
  for (const e of batch) onShellReloadKey(e);
  for (const e of batch) assert.equal(e.prevented, 0);
  assert.equal(reloads, 0);
  for (const url of [OFFLINE, GATE]) {
    const { ctx, els, keydown } = loadInline(url, { shell: true });
    els['retry-btn'] = els['retry-btn'] || fakeEl();
    for (const e of keys()) {
      keydown(e);
      assert.equal(e.prevented, 0);
    }
    assert.equal(ctx.reloads, 0);
    assert.equal(els['retry-btn'].clicks, 0);
  }
});

test('shell-reload 密碼閘門頁：在殼裡 F5 reload 一次、瀏覽器不攔', () => {
  const { ctx, keydown } = loadInline(GATE, { shell: true });
  assert.equal(typeof keydown, 'function');
  const e = ev('F5');
  keydown(e);
  assert.equal(e.prevented, 1);
  assert.equal(ctx.reloads, 1);
  const e2 = ev('r', { ctrlKey: true });
  keydown(e2);
  assert.equal(ctx.reloads, 2);
});
