// TASK-144-T6: searchAll() 兩分支排除 skipReason 命中的檔案

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBatch } from '../state/batch.js';

globalThis.window = globalThis;
globalThis.window.t = (k) => k;

function makeState(fileList, searchedFilesCollector = []) {
  const toasts = [];
  return {
    ...searchStateBatch(),
    batchState: {
      isProcessing: false,
      isPaused: false,
      total: 0,
      processed: 0,
      success: 0,
      failed: 0,
    },
    fileList,
    listMode: 'file',
    currentFileIndex: 0,
    showToast(msg, type) { toasts.push({ msg, type }); },
    toasts,
    _searchFileBackground: async (file) => {
      searchedFilesCollector.push(file);
    },
    _resetCoverState() {},
  };
}


test('searchAll: skipReason 命中的檔案不被 failedFiles 分支撈回重跑', async () => {
  const searched = [];
  const file1 = { number: 'ABC-101', searched: true, searchResults: [], has_nfo: false, skipReason: 'not_found' };
  const file2 = { number: 'ABC-102', searched: true, searchResults: [], has_nfo: false, skipReason: '' };
  const state = makeState([file1, file2], searched);

  await state.searchAll();

  assert.equal(searched.length, 1, 'failedFiles 分支僅重試無 skipReason 者');
  assert.equal(searched.includes(file1), false, 'skipReason 命中的檔案不被 failedFiles 撈回');
  assert.equal(searched.includes(file2), true, '無 skipReason 且失敗的檔案被撈回重試');
  assert.equal(file1.searched, true, 'skipReason 命中的檔案 searched 不得被重置為 false');
});

