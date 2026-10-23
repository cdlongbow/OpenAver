// 168e-T6: 殼內 F5／Ctrl+R／Cmd+R 重新整理（一般頁／離線小頁／閘門頁）
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
let reloads = 0;
globalThis.location = { reload: () => { reloads += 1; } };

const { onShellReloadKey } = await import('../shell-reload.js');


function ev(key, mods = {}) {
  const e = { key, ctrlKey: false, metaKey: false, shiftKey: false, prevented: 0, ...mods };
  e.preventDefault = () => { e.prevented += 1; };
  return e;
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


