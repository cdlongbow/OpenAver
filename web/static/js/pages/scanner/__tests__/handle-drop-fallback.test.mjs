// TASK-128-T4: browser drop falls back to browse-dir modal + toast;
// desktop (pywebview) drop must not open the modal.
// TASK-138-T3: drag-overlay heartbeat state machine + CD-1 drop clears timer.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateScan, DRAG_OVERLAY_TIMEOUT_MS } = await import('../state-scan.js');

function makeFakeEvent() {
  return { preventDefault() {} };
}

function makeFakeDragEvent() {
  return { preventDefault() {}, dataTransfer: { types: ['Files'] } };
}
function makeFakeNonFileDragEvent() {
  return { preventDefault() {}, dataTransfer: { types: ['text/plain'] } };
}

let dragTimeoutCalls;

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
    showDragOverlay: true,
    handleDragTimeout(...args) {
      dragTimeoutCalls++;
      return stateScan().handleDragTimeout.call(this, ...args);
    },
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


