// TASK-128-T4: browser drop falls back to browse-dir modal + toast;
// desktop (pywebview) drop must not open the modal.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateScan } = await import('../state-scan.js');

function makeFakeEvent() {
  return { preventDefault() {} };
}

function makeHarness({ withPywebview } = { withPywebview: false }) {
  const openBrowseDirCalls = [];
  const toastCalls = [];
  const addFolderPathCalls = [];

  if (withPywebview) {
    window.pywebview = { api: {} };
  } else {
    delete window.pywebview;
  }

  const fakeThis = Object.assign({}, stateScan(), {
    dragCounter: 3,
    showDragOverlay: true,
    openBrowseDir(targetKey, onSelect, options) {
      openBrowseDirCalls.push({ targetKey, onSelect, options });
    },
    showToast(message, type) {
      toastCalls.push({ message, type });
    },
    addFolderPath(path) {
      addFolderPathCalls.push(path);
    },
  });

  return { fakeThis, openBrowseDirCalls, toastCalls, addFolderPathCalls };
}

test('browser drop opens the browse-dir modal', () => {
  const { fakeThis, openBrowseDirCalls, toastCalls, addFolderPathCalls } = makeHarness({
    withPywebview: false,
  });

  stateScan().handleDrop.call(fakeThis, makeFakeEvent());

  assert.equal(openBrowseDirCalls.length, 1, 'browser drop must open browse-dir once');
  assert.equal(openBrowseDirCalls[0].targetKey, 'scanner');
  assert.equal(
    toastCalls.length,
    1,
    'browser drop must show the browse-dir fallback toast',
  );
  assert.equal(toastCalls[0].message, 'scanner.toast.browse_dir_fallback');
  assert.equal(toastCalls[0].type, 'info');
  assert.equal(addFolderPathCalls.length, 0, 'path is only added via onSelect');

  openBrowseDirCalls[0].onSelect('/mnt/c/Dropped');
  assert.deepEqual(addFolderPathCalls, ['/mnt/c/Dropped']);
});

test('desktop drop does not open the modal', () => {
  const { fakeThis, openBrowseDirCalls, toastCalls } = makeHarness({
    withPywebview: true,
  });

  stateScan().handleDrop.call(fakeThis, makeFakeEvent());

  assert.equal(openBrowseDirCalls.length, 0, 'desktop drop must not open browse-dir');
  assert.equal(toastCalls.length, 0, 'desktop drop must not show toast');

  delete window.pywebview;
});

test('both drop paths clear dragCounter and hide the overlay', () => {
  const browser = makeHarness({ withPywebview: false });
  stateScan().handleDrop.call(browser.fakeThis, makeFakeEvent());
  assert.equal(browser.fakeThis.dragCounter, 0);
  assert.equal(browser.fakeThis.showDragOverlay, false);

  const desktop = makeHarness({ withPywebview: true });
  stateScan().handleDrop.call(desktop.fakeThis, makeFakeEvent());
  assert.equal(desktop.fakeThis.dragCounter, 0);
  assert.equal(desktop.fakeThis.showDragOverlay, false);

  delete window.pywebview;
});
