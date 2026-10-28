// TASK-182-T1: searchAll() 一次搜完全部待搜片（無 20 片上限）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBase } from '../state/base.js';
import { searchStateBatch } from '../state/batch.js';

globalThis.window = globalThis;
globalThis.window.t = (k) => k;

test('searchAll: 丟 50 片按一次批次搜尋，50 片全部被搜（無 20 片上限）', async () => {
  const fileList = Array.from({ length: 50 }, (_, i) => ({
    number: `ABC-${String(i + 1).padStart(3, '0')}`,
    searched: false, searchResults: [], has_nfo: false, skipReason: '',
  }));
  const searched = [];
  let totalDuringBatch = null;
  const state = {
    ...searchStateBatch(),
    batchState: searchStateBase().batchState,  // 真實初值（含產品碼設定的任何上限欄位）
    fileList,
    listMode: 'file',
    currentFileIndex: 0,
    showToast() {},
    switchToFile() {},
    _resetCoverState() {},
    _searchFileBackground: async (file) => {
      if (totalDuringBatch === null) totalDuringBatch = state.batchState.total;
      searched.push(file);
      file.searched = true;
      file.searchResults = [{}];
    },
  };

  await state.searchAll();

  assert.equal(searched.length, 50, '50 片全被搜');
  assert.equal(totalDuringBatch, 50, '批次進行中 total 為全部待搜片數');
});
