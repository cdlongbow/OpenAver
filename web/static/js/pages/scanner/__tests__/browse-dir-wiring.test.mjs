// TASK-128-T3: scanner 頁 selectFolder 無-pywebview 分支接上 openBrowseDir。
// 守 callback 呼叫 addFolderPath；反向鎖 pywebview 存在時不呼叫 openBrowseDir。

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

function makeSpyOpenBrowseDir() {
  const calls = [];
  function openBrowseDir(targetKey, onSelect, options) {
    calls.push({ targetKey, onSelect, options });
  }
  return { openBrowseDir, calls };
}

test('scanner adds picked folder to source list', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const addFolderPathCalls = [];
  const toggleCalls = [];
  const fakeThis = Object.assign({}, stateScan(), {
    openBrowseDir,
    addFolderPath(path) { addFolderPathCalls.push(path); },
    toggleManualInput() { toggleCalls.push(true); },
    showToast() {},
  });
  delete window.pywebview;

  await stateScan().selectFolder.call(fakeThis);

  assert.equal(calls.length, 1, '無 pywebview 時應呼叫 openBrowseDir 一次');
  assert.equal(calls[0].targetKey, 'scanner');
  assert.equal(
    calls[0].options === undefined || Object.keys(calls[0].options || {}).length === 0
      || calls[0].options.expandVideos !== true,
    true,
    'scanner 不得帶 expandVideos: true',
  );
  assert.equal(toggleCalls.length, 0, '接上彈窗後不得再自動 toggleManualInput');

  calls[0].onSelect('/mnt/c/AVtest');
  assert.deepEqual(addFolderPathCalls, ['/mnt/c/AVtest']);
});

test('AC-4: scanner does not call openBrowseDir when window.pywebview exists', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const addFolderPathCalls = [];
  window.pywebview = {
    api: {
      select_folder: async () => ({ folder: '/desk/src' }),
    },
  };
  const fakeThis = Object.assign({}, stateScan(), {
    openBrowseDir,
    addFolderPath(path) { addFolderPathCalls.push(path); },
    toggleManualInput() {},
    showToast() {},
  });

  await stateScan().selectFolder.call(fakeThis);

  assert.equal(calls.length, 0, '有 pywebview 時不得呼叫 openBrowseDir');
  assert.deepEqual(addFolderPathCalls, ['/desk/src']);

  delete window.pywebview;
});
