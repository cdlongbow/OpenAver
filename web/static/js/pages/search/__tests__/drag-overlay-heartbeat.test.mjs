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

