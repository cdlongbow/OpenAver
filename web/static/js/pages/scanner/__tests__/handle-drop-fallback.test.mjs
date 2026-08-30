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

test('desktop drop does not open the modal', () => {
  const { fakeThis, openBrowseDirCalls, toastCalls } = makeHarness({
    withPywebview: true,
  });

  stateScan().handleDrop.call(fakeThis, makeFakeEvent());

  assert.equal(openBrowseDirCalls.length, 0, 'desktop drop must not open browse-dir');
  assert.equal(toastCalls.length, 0, 'desktop drop must not show toast');

  delete window.pywebview;
});

test('both drop paths clear the drag-overlay timeout and hide the overlay immediately', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });  // 只列 setTimeout，見上方 Node v24.13.0 警告
  dragTimeoutCalls = 0;

  const browser = makeHarness({ withPywebview: false });
  stateScan().handleDragOver.call(browser.fakeThis, makeFakeDragEvent());  // 先武裝逾時
  stateScan().handleDrop.call(browser.fakeThis, makeFakeEvent());
  assert.equal(browser.fakeThis.showDragOverlay, false, 'drop 後應立即關閉覆蓋層');
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
  assert.equal(
    dragTimeoutCalls, 0,
    '[handle-drop-fallback:CD-1] drop 之後原本武裝的逾時 timer 必須被清掉，不得在逾時時間到了之後還觸發 handleDragTimeout',
  );

  dragTimeoutCalls = 0;
  const desktop = makeHarness({ withPywebview: true });
  stateScan().handleDragOver.call(desktop.fakeThis, makeFakeDragEvent());
  stateScan().handleDrop.call(desktop.fakeThis, makeFakeEvent());
  assert.equal(desktop.fakeThis.showDragOverlay, false);
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
  assert.equal(dragTimeoutCalls, 0, '[handle-drop-fallback:CD-1] 桌面版同理');

  delete window.pywebview;
});

test('dragover 命中 Files → showDragOverlay 開啟', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness({ withPywebview: false });
  fakeThis.showDragOverlay = false;  // makeHarness 預設灌 true 是給既有 handleDrop 測試用的，這裡要從關的狀態開始
  stateScan().handleDragOver.call(fakeThis, makeFakeDragEvent());
  assert.equal(fakeThis.showDragOverlay, true);
  // FE-GUARD-13：_dragTimeoutHandle 是模組級變數，同檔多支 test() 共用同一份模組實例。
  // 本支測試武裝了一個 timer，若留著不排乾，下一支測試會拿到殘留 handle 而假紅。
  // tick 到逾時點讓它自己燒掉（handleDragTimeout 內會把 handle 設回 null）。
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
});

test('dragover 非 Files → 不開啟', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness({ withPywebview: false });
  fakeThis.showDragOverlay = false;
  stateScan().handleDragOver.call(fakeThis, makeFakeNonFileDragEvent());
  assert.equal(fakeThis.showDragOverlay, false);
});

test('連續 dragover 續期：逾時前再來一次，原本的逾時點不會關閉', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness({ withPywebview: false });
  fakeThis.showDragOverlay = false;
  stateScan().handleDragOver.call(fakeThis, makeFakeDragEvent());
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS - 100);
  stateScan().handleDragOver.call(fakeThis, makeFakeDragEvent());  // 續期
  t.mock.timers.tick(100);  // 走到「原本」的逾時點
  assert.equal(fakeThis.showDragOverlay, true, '續期後不該在原本排定的逾時點被關閉');
  // 續期後的新逾時點（再 DRAG_OVERLAY_TIMEOUT_MS - 100）到了才該關——順帶把 timer 排乾（FE-GUARD-13）。
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS - 100);
  assert.equal(fakeThis.showDragOverlay, false, '續期只是把逾時點往後推，新的逾時點到了仍要關');
});

test('逾時無新 dragover → showDragOverlay 自動關閉（模擬 Esc / 拖出視窗）', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness({ withPywebview: false });
  fakeThis.showDragOverlay = false;
  stateScan().handleDragOver.call(fakeThis, makeFakeDragEvent());
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
  assert.equal(fakeThis.showDragOverlay, false);
});
