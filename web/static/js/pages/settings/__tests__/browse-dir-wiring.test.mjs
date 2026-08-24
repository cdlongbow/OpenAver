// TASK-128-T3: settings 頁 selectOutputFolder 無-pywebview 分支接上 openBrowseDir。
// 守 callback 寫入 form.avlistOutputDir；反向鎖 pywebview 存在時不呼叫 openBrowseDir。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateUI } = await import('../state-ui.js');

function makeSpyOpenBrowseDir() {
  const calls = [];
  function openBrowseDir(targetKey, onSelect, options) {
    calls.push({ targetKey, onSelect, options });
  }
  return { openBrowseDir, calls };
}

test('settings writes picked folder into avlistOutputDir', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const fakeThis = Object.assign({}, stateUI(), {
    openBrowseDir,
    form: { avlistOutputDir: '' },
    showToast() {},
  });
  delete window.pywebview;

  await stateUI().selectOutputFolder.call(fakeThis);

  assert.equal(calls.length, 1, '無 pywebview 時應呼叫 openBrowseDir 一次');
  assert.equal(calls[0].targetKey, 'settings');
  assert.equal(
    calls[0].options === undefined || Object.keys(calls[0].options || {}).length === 0
      || calls[0].options.expandVideos !== true,
    true,
    'settings 不得帶 expandVideos: true',
  );

  calls[0].onSelect('/mnt/c/AVtest');
  assert.equal(fakeThis.form.avlistOutputDir, '/mnt/c/AVtest');
});

test('AC-4: settings does not call openBrowseDir when window.pywebview exists', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  window.pywebview = {
    api: {
      select_folder: async () => ({ folder: '/desk/out' }),
    },
  };
  const fakeThis = Object.assign({}, stateUI(), {
    openBrowseDir,
    form: { avlistOutputDir: '' },
    showToast() {},
  });

  await stateUI().selectOutputFolder.call(fakeThis);

  assert.equal(calls.length, 0, '有 pywebview 時不得呼叫 openBrowseDir');
  assert.equal(fakeThis.form.avlistOutputDir, '/desk/out');

  delete window.pywebview;
});
