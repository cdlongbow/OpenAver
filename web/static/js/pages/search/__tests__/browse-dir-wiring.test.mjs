// TASK-128-T3: search 頁 addFiles/addFolder 無-pywebview 分支接上 openBrowseDir。
// 守 expandVideos: true + setFileList callback；反向鎖 pywebview 存在時不呼叫 openBrowseDir。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';

globalThis.window = globalThis;
window.t = (key) => key;

function makeSpyOpenBrowseDir() {
  const calls = [];
  function openBrowseDir(targetKey, onSelect, options) {
    calls.push({ targetKey, onSelect, options });
  }
  return { openBrowseDir, calls };
}

test('search trigger requests expanded video files', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const setFileListCalls = [];
  const fakeThis = Object.assign({}, searchStateFileList(), {
    openBrowseDir,
    async setFileList(paths) { setFileListCalls.push(paths); },
    showToast() {},
  });
  // 確保無 pywebview
  delete window.pywebview;

  await searchStateFileList().addFolder.call(fakeThis);

  assert.equal(calls.length, 1, '無 pywebview 時應呼叫 openBrowseDir 一次');
  assert.equal(calls[0].targetKey, 'search');
  assert.deepEqual(calls[0].options, { expandVideos: true });

  const files = ['/mnt/c/AVtest/a.mp4', '/mnt/c/AVtest/b.mp4'];
  await calls[0].onSelect(files);
  assert.deepEqual(setFileListCalls, [files], 'callback 應把展開後的檔案陣列交給 setFileList');
});

test('search addFiles also requests expanded video files (same wiring)', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const setFileListCalls = [];
  const fakeThis = Object.assign({}, searchStateFileList(), {
    openBrowseDir,
    async setFileList(paths) { setFileListCalls.push(paths); },
    showToast() {},
  });
  delete window.pywebview;

  await searchStateFileList().addFiles.call(fakeThis);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].targetKey, 'search');
  assert.deepEqual(calls[0].options, { expandVideos: true });

  await calls[0].onSelect(['/x/y.mp4']);
  assert.deepEqual(setFileListCalls, [['/x/y.mp4']]);
});

test('AC-4: search does not call openBrowseDir when window.pywebview exists', async () => {
  const { openBrowseDir, calls } = makeSpyOpenBrowseDir();
  const setFileListCalls = [];
  window.pywebview = {
    api: {
      select_folder: async () => ({ files: ['/desk/a.mp4'] }),
      select_files: async () => ['/desk/b.mp4'],
    },
  };
  const fakeThis = Object.assign({}, searchStateFileList(), {
    openBrowseDir,
    async setFileList(paths) { setFileListCalls.push(paths); },
    showToast() {},
  });

  await searchStateFileList().addFolder.call(fakeThis);
  await searchStateFileList().addFiles.call(fakeThis);

  assert.equal(calls.length, 0, '有 pywebview 時不得呼叫 openBrowseDir');
  assert.deepEqual(setFileListCalls, [['/desk/a.mp4'], ['/desk/b.mp4']]);

  delete window.pywebview;
});
