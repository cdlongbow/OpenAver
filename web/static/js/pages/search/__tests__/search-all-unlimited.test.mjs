// TASK-182-T1: searchAll() 一次搜完全部待搜片（無 20 片上限）

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchStateBase } from '../state/base.js';
import { searchStateBatch } from '../state/batch.js';
import { isFileSearching } from '../batch-search-rules.js';

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

// 搜尋中轉圈名單（R1：搜完後不殘留、搜尋中看得出搜到哪幾片）。三個出口＋純函式同一失敗原因。
const mkSpinState = (n, searchFn) => ({
  ...searchStateBatch(), batchState: searchStateBase().batchState,
  fileList: Array.from({ length: n }, (_, i) => ({
    path: `/x/ABC-00${i + 1}.mp4`, number: `ABC-00${i + 1}`, searched: false, searchResults: [], has_nfo: false, skipReason: '',
  })),
  listMode: 'file', currentFileIndex: 0, showToast() {}, switchToFile() {}, _resetCoverState() {},
  _searchFileBackground: searchFn,
});

test('searchAll: 搜尋中轉圈名單只含正在搜的片，搜完或中斷後清空', async () => {
  assert.equal(isFileSearching(['p1'], 'p1'), true);
  assert.equal(isFileSearching(['p1'], 'p2'), false);
  assert.equal(isFileSearching([], 'p1'), false);

  const snaps = [];
  const a = mkSpinState(6, async (file) => {
    snaps.push({ path: file.path, active: [...a.batchState.activePaths] });
    await new Promise(r => setTimeout(r, 0));
    file.searched = true; file.searchResults = [{}];
  });
  await a.searchAll();
  assert.equal(snaps.length, 6);
  for (const s of snaps) {
    assert.ok(s.active.includes(s.path), `開始搜 ${s.path} 時名單含自己`);
    assert.ok(s.active.length <= 2, '同時最多 2 片');
  }
  assert.equal(a.batchState.activePaths.length, 0, '搜完清空');

  const b = mkSpinState(4, async () => { b.batchState.isProcessing = false; });
  await b.searchAll();
  assert.equal(b.batchState.activePaths.length, 0, '中斷後清空');

  const c = mkSpinState(1, async () => { throw new Error('x'); });
  await assert.rejects(() => c.searchAll());
  assert.equal(c.batchState.activePaths.length, 0, '例外後清空');
});
