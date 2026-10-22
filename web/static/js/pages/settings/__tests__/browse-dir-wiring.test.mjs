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


test('settings client mode opens browse dir and never calls select_folder', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  let nativeCalls = 0;
  window.pywebview = {
    api: { select_folder: async () => { nativeCalls++; return { folder: '/desk/out' }; } },
  };
  try {
    const fakeThis = Object.assign({}, stateUI(), {
      openBrowseDir,
      shellMode: 'client',
      form: { avlistOutputDir: '' },
      showToast() {},
    });

    await stateUI().selectOutputFolder.call(fakeThis);

    assert.equal(calls.length, 1, 'client 模式應呼叫 openBrowseDir 一次');
    assert.equal(calls[0].targetKey, 'settings');
    assert.equal(nativeCalls, 0, 'client 模式不得開這台電腦的原生對話框');
    calls[0].onSelect('/mnt/av/x');
    assert.equal(fakeThis.form.avlistOutputDir, '/mnt/av/x');
  } finally {
    delete window.pywebview;
  }
});

test('settings local shell mode still calls select_folder', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  let nativeCalls = 0;
  window.pywebview = {
    api: { select_folder: async () => { nativeCalls++; return { folder: '/desk/out' }; } },
  };
  try {
    const fakeThis = Object.assign({}, stateUI(), {
      openBrowseDir,
      shellMode: 'local',
      form: { avlistOutputDir: '' },
      showToast() {},
    });

    await stateUI().selectOutputFolder.call(fakeThis);

    assert.equal(calls.length, 0);
    assert.equal(nativeCalls, 1);
    assert.equal(fakeThis.form.avlistOutputDir, '/desk/out');
  } finally {
    delete window.pywebview;
  }
});
