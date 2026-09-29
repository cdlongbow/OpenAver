// F4: 非桌面版最愛資料夾未設定 → toast 講「尚未設定」（warning），其他失敗維持 load_failed（error）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateFileList } from '../state/file-list.js';
import { searchStateSearchFlow } from '../state/search-flow.js';
import { searchStateBase } from '../state/base.js';

globalThis.window = globalThis;
window.t = (key) => key;

function makeFakeThis(toasts) {
  return Object.assign(
    {},
    searchStateBase(),
    searchStateSearchFlow(),
    searchStateFileList(),
    { showToast(msg, type) { toasts.push({ msg, type }); } },
  );
}

test('favorite_folder_unset → 「尚未設定最愛資料夾」warning，不是 load_failed', async () => {
  globalThis.fetch = async () => ({ json: async () => ({ success: false, error: 'favorite_folder_unset' }) });
  const toasts = [];
  const fakeThis = makeFakeThis(toasts);
  await fakeThis.loadFavorite();
  assert.deepEqual(toasts, [{ msg: 'search.auto_organize.folder_not_configured', type: 'warning' }]);
  assert.equal(fakeThis.isLoadingFavorite, false);
});

test('其他失敗 → 維持 load_failed error', async () => {
  globalThis.fetch = async () => ({ json: async () => ({ success: false, error: 'boom' }) });
  const toasts = [];
  await makeFakeThis(toasts).loadFavorite();
  assert.deepEqual(toasts, [{ msg: 'search.toast.load_failed', type: 'error' }]);
});
