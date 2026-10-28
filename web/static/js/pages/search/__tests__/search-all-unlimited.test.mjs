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

// 搜尋中不拉走使用者正在看的片（R1）。stub 同步，不可掛起。
const hit = (f) => { f.searched = true; f.searchResults = [{}]; };
const miss = (f) => { f.searched = true; f.searchResults = []; };
const mkJump = (n, first, searchFn) => {
  const s = mkSpinState(n, (f) => searchFn(s, f));
  first(s.fileList[0]);
  s.calls = [];
  s.switchToFile = (idx) => { s.calls.push({ idx, processed: s.batchState.processed }); };
  return s;
};

test('searchAll: 搜尋中不把使用者正在看的片拉走（開始時有結果，或第一次跳之前被切走）', async () => {
  const a = mkJump(50, hit, (s, f) => hit(f));
  await a.searchAll();
  assert.equal(a.calls.length, 0, '(i) 按下時目前片有結果 → 整批不切片');

  let first = true;
  const b = mkJump(12, miss, (s, f) => { if (first) { first = false; s.currentFileIndex = 5; } hit(f); });
  await b.searchAll();
  assert.equal(b.calls.length, 0, '(ii) 第一次跳之前使用者切走 → 不拉回');
});

test('searchAll: 一開始詳細區空白時只在第一個有結果的那一輪跳一次', async () => {
  const s = mkJump(12, miss, (st, f) => { const i = st.fileList.indexOf(f); (i === 1 || i === 2 ? miss : hit)(f); });
  await s.searchAll();
  assert.equal(s.calls.length, 1, '只跳一次');
  assert.equal(s.calls[0].processed, 4, '第二輪搜完才跳');
  assert.equal(s.calls[0].idx, 3, '取該輪列表順序最前的有結果片');
});

test('searchAll: 搜到一半換了新清單，舊批次不再送搜尋、新批次搜完全部', async () => {
  const mk = (tag, n) => Array.from({ length: n }, (_, i) => ({
    path: `/x/${tag}${i}.mp4`, number: `${tag}-${i}`, searched: false, searchResults: [], has_nfo: false, skipReason: '',
  }));
  const sent = [];  // stub 以 setTimeout(0) settle，不會掛起，不需 flush()
  const s = mkSpinState(1, (f) => new Promise(r => setTimeout(() => { sent.push(f.path); hit(f); r(); }, 0)));
  s.fileList = mk('OLD', 10);
  const oldRun = s.searchAll();  // 第一組 2 片已送出、尚未 settle
  const b = s.batchState;        // 照 setFileList 的重置做法，再立刻重按批次搜尋
  Object.assign(b, { isProcessing: false, isPaused: false, total: 0, processed: 0, success: 0, failed: 0, activePaths: [] });
  b.runId++;
  s.fileList = mk('NEW', 20);
  s.currentFileIndex = 0;
  await Promise.all([oldRun, s.searchAll()]);
  assert.equal(sent.filter(p => p.includes('/NEW')).length, 20, '新的 20 片全被搜');
  assert.ok(sent.filter(p => p.includes('/OLD')).length <= 2, '舊清單只容許取代當下 in-flight 的 ≤ 2 片');
  assert.equal(b.isProcessing, false);
  assert.equal(b.activePaths.length, 0);
});
