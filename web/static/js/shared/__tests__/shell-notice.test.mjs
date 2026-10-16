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

test('handleShellNotice rejects malformed version or kind without showing', () => {
  const bad = [
    { kind: 'update_available', version: '<script>1</script>' },
    { kind: 'update_available', version: 'v9.9.9' },
    { kind: 'update_available', version: '' },
    { kind: 'update_available', version: 9 },
    { kind: 'update_available' },
    { kind: 'other', version: '9.9.9' },
    null, undefined, 'update_available', 42, true, // 非物件
  ];
  for (const p of bad) assert.equal(handleShellNotice(p), false, JSON.stringify(p));
  assert.equal(shows.length, 0);
});

// 168e-T12: update_marker 純 DOM，不依賴 toast 容器與 Alpine
function setupDots(n) {
  const dots = Array.from({ length: n }, () => ({ hidden: true, title: '' }));
  globalThis.document = { querySelector: () => null, querySelectorAll: () => dots };
  delete globalThis.Alpine;
  return dots;
}

test('update_marker reveals every data-shell-update dot and sets its title on a page with no toast container or Alpine', () => {
  const dots = setupDots(2);
  assert.equal(handleShellNotice({ kind: 'update_marker', version: '9.9.9' }), true);
  for (const d of dots) {
    assert.equal(d.hidden, false);
    assert.equal(d.title, 'common.shell.update_marker_title|{"version":"9.9.9"}');
  }
});

test('update_marker returns false when the page has no dot', () => {
  setupDots(0);
  assert.equal(handleShellNotice({ kind: 'update_marker', version: '9.9.9' }), false);
});

test('update_marker rejects malformed version and leaves dots hidden', () => {
  const dots = setupDots(2);
  for (const v of ['<script>1</script>', 'v9.9.9', '', 9, undefined]) {
    assert.equal(handleShellNotice({ kind: 'update_marker', version: v }), false, String(v));
  }
  for (const d of dots) assert.equal(d.hidden, true);
});
