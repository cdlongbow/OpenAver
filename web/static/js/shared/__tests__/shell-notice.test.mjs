// 168c-T5: handleShellNotice 五格（合法／缺容器／缺 store／壞版本／非物件）
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.t = (key, params) => (params ? `${key}|${JSON.stringify(params)}` : key);

const { handleShellNotice } = await import('../shell-notice.js');

let shows;
function setup({ container = true, store = true } = {}) {
  shows = [];
  globalThis.document = { querySelector: () => (container ? {} : null) };
  globalThis.Alpine = store
    ? { store: () => ({ show: (...a) => shows.push(a) }) }
    : { store: () => undefined };
}

beforeEach(() => setup());

test('handleShellNotice shows an info toast once and returns true for a valid payload', () => {
  const ok = handleShellNotice({ kind: 'update_available', version: '9.9.9' });
  assert.equal(ok, true);
  assert.equal(shows.length, 1);
  assert.equal(shows[0][0], 'common.shell.update_available|{"version":"9.9.9"}');
  assert.equal(shows[0][1], 'info');
  assert.equal(shows[0][2], 10000);
});

test('handleShellNotice returns false and never calls show when the page has no toast container', () => {
  setup({ container: false });
  assert.equal(handleShellNotice({ kind: 'update_available', version: '9.9.9' }), false);
  assert.equal(shows.length, 0);
  // Alpine.store("toast") 缺失或 Alpine 不存在 ⇒ 同樣 false
  setup({ store: false });
  assert.equal(handleShellNotice({ kind: 'update_available', version: '9.9.9' }), false);
  delete globalThis.Alpine;
  assert.equal(handleShellNotice({ kind: 'update_available', version: '9.9.9' }), false);
});


// 168e-T12: update_marker 純 DOM，不依賴 toast 容器與 Alpine
function setupDots(n) {
  const dots = Array.from({ length: n }, () => ({ hidden: true, title: '' }));
  globalThis.document = { querySelector: () => null, querySelectorAll: () => dots };
  delete globalThis.Alpine;
  return dots;
}


