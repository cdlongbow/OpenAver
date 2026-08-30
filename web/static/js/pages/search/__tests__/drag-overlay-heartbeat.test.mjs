// TASK-138-T3（CD-A6）：main.js 的 _armDragHeartbeat/_onDragTimeout/_onDrop 狀態機驗收。
// main.js 底部有頂層 document.addEventListener('alpine:init', ...) 副作用，import 前必須先
// stub globalThis.document，否則模組載入就丟錯；main.js 也要先 export searchPage 才能被
// 直接 import 呼叫。掃描頁對應測試見 handle-drop-fallback.test.mjs。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };  // 頂層 alpine:init 副作用的最小 stub

register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);

const { searchPage, DRAG_OVERLAY_TIMEOUT_MS } = await import('../main.js');

function makeFakeDragEvent() {
  return { preventDefault() {}, dataTransfer: { types: ['Files'] } };
}
function makeFakeNonFileDragEvent() {
  return { preventDefault() {}, dataTransfer: { types: ['text/plain'] } };
}

function makeHarness() {
  const handleFileDropCalls = [];
  const fakeThis = Object.assign({}, searchPage(), {
    dragActive: false,
    _dragTimeoutCalls: 0,
    _onDragTimeout(...args) {
      this._dragTimeoutCalls++;
      return searchPage()._onDragTimeout.call(this, ...args);
    },
    handleFileDrop(files) {
      handleFileDropCalls.push(files);
    },
  });
  return { fakeThis, handleFileDropCalls };
}

test('dragover 命中 Files → dragActive 開啟', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness();
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeDragEvent());
  assert.equal(fakeThis.dragActive, true);
  // FE-GUARD-13：_dragTimeoutHandle 是模組級變數，同檔多支 test() 共用同一份模組實例。
  // 本支測試武裝了一個 timer，若留著不排乾，下一支測試會拿到殘留 handle 而假紅。
  // tick 到逾時點讓它自己燒掉（_onDragTimeout 內會把 handle 設回 null）。
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
});

test('dragover 非 Files（例如純文字）→ 不開啟', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness();
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeNonFileDragEvent());
  assert.equal(fakeThis.dragActive, false);
});

test('連續 dragover 續期：逾時前再來一次，原本的逾時點不會關閉', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness();
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeDragEvent());
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS - 100);
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeDragEvent());
  t.mock.timers.tick(100);
  assert.equal(fakeThis.dragActive, true, '續期後不該在原本排定的逾時點被關閉');
  // 續期後的新逾時點（再 DRAG_OVERLAY_TIMEOUT_MS - 100）到了才該關——順帶把 timer 排乾（FE-GUARD-13）。
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS - 100);
  assert.equal(fakeThis.dragActive, false, '續期只是把逾時點往後推，新的逾時點到了仍要關');
});

test('逾時無新 dragover → dragActive 自動關閉（模擬 Esc / 拖出視窗）', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis } = makeHarness();
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeDragEvent());
  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
  assert.equal(fakeThis.dragActive, false);
  assert.equal(fakeThis._dragTimeoutCalls, 1);
});

test('drop 立即關閉、清掉逾時 timer，並呼叫 handleFileDrop', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis, handleFileDropCalls } = makeHarness();
  const files = [{ name: 'A.mp4' }];
  searchPage()._armDragHeartbeat.call(fakeThis, makeFakeDragEvent());
  searchPage()._onDrop.call(fakeThis, { preventDefault() {}, dataTransfer: { files } });
  assert.equal(fakeThis.dragActive, false, 'drop 後應立即關閉');
  assert.deepEqual(handleFileDropCalls, [files], 'drop 應呼叫 handleFileDrop 並帶入 dataTransfer.files');

  t.mock.timers.tick(DRAG_OVERLAY_TIMEOUT_MS);
  assert.equal(
    fakeThis._dragTimeoutCalls, 0,
    '[drag-overlay-heartbeat:CD-A6] drop 之後原本武裝的逾時 timer 必須被清掉，不得在逾時時間到了之後還觸發 _onDragTimeout',
  );
});

test('PyWebView 環境：drop 不呼叫 handleFileDrop（Python 端另行處理）', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { fakeThis, handleFileDropCalls } = makeHarness();
  window.pywebview = { api: {} };
  try {
    searchPage()._onDrop.call(fakeThis, { preventDefault() {}, dataTransfer: { files: [{ name: 'A.mp4' }] } });
    assert.equal(handleFileDropCalls.length, 0);
  } finally {
    delete window.pywebview;
  }
});
