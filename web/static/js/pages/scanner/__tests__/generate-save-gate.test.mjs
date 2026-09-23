// TASK-153b-T6：generate() 在 saveConfig() 回 false 時必須中止，不得進入 generating。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

const localStorageStore = new Map();
globalThis.localStorage = {
  getItem: (k) => (localStorageStore.has(k) ? localStorageStore.get(k) : null),
  setItem: (k, v) => { localStorageStore.set(k, String(v)); },
  removeItem: (k) => { localStorageStore.delete(k); },
};

// 避免未加 gate 時 new EventSource 直接拋錯把 state 改成 'error'，掩蓋 generating 回歸。
class FakeEventSource {
  constructor() {
    this.onmessage = null;
    this.onerror = null;
  }
  close() {}
}
globalThis.EventSource = FakeEventSource;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateScan } = await import('../state-scan.js');

test('generate does not start when saveConfig fails', async () => {
  const base = stateScan();
  const fakeThis = Object.assign({}, base, {
    state: 'idle',
    configDirty: true,
    directories: [{ path: '/tmp/sample-folder', readonly: false }],
    folderSnapshot: JSON.stringify([{ path: '/tmp/sample-folder', readonly: false }]),
    eventSource: null,
    showToast() {},
    async saveConfig() {
      return false;
    },
    $refs: { logOutput: { innerHTML: '' } },
    addLog() {},
    flushLogs() {},
  });

  await fakeThis.generate.call(fakeThis);

  assert.equal(
    fakeThis.state,
    'idle',
    'saveConfig 失敗時 generate() 應保持 idle，不得進入 generating',
  );
  assert.equal(fakeThis.eventSource, null, 'saveConfig 失敗時不得建立 EventSource');
});
