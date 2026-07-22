// TASK-106-T2' CD-106-5/CD-106-8: 「整理送實際候選」bug 修復
//
// buildOrganizeMetadata 是 batch.js 的 module-level 純函式（CD-106-8，不依賴 this），
// 直接 import 測試，不需 .call(fakeThis)。
//
// loadMore 的 file 模式硬關（CD-106-5 P1-#2）與 canGoNext() 的 file 分支去
// hasMoreResults（CD-106-5 round-3 P2）都是讀 this.* 的 mixin method，用
// .call(fakeThis) 呼叫（同 can-edit-file.test.mjs / set-file-list-fallback.test.mjs 慣例）。
//
// P2 fix（PR#115 Codex）: buildOrganizeMetadata 現透過 toDateInputValue 正規化 date 欄位，
// batch.js 因此新增 `import { toDateInputValue } from './result-card.js'`，而
// result-card.js 匯入瀏覽器 importmap 別名 `@/shared/open-local.js`。這條別名 import
// 現已進入 batch.js 的 static import graph——若像舊版一樣在頂層用靜態 `import` 拉
// buildOrganizeMetadata，node module linker 會在 register() 執行前就嘗試解析
// `@/shared/...`（ES module 靜態 import 於 body 執行前完成 link phase）而拋
// ERR_MODULE_NOT_FOUND。故 batch.js 改與 navigation.js 同做法：register() 之後才動態
// import。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { searchStateBase } from '../state/base.js';

globalThis.window = globalThis;

// navigation.js／batch.js 匯入瀏覽器 importmap 別名 `@/shared/...`（見 alias-loader.mjs
// 註解），掛一個 scope 僅本檔的 resolve hook 後才能動態 import。
register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { buildOrganizeMetadata } = await import('../state/batch.js');
const { searchStateNavigation } = await import('../state/navigation.js');

test('buildOrganizeMetadata: selectedCandidateIndex=2 → 送 searchResults[2]（非寫死 [0]）', () => {
  const file = {
    searchResults: [
      { number: 'ABC-001' },
      { number: 'ABC-002' },
      { number: 'ABC-003' },
    ],
    selectedCandidateIndex: 2,
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-003', date: '' });
});

test('buildOrganizeMetadata: selectedCandidateIndex 未設 → 送 searchResults[0]（?? 0 fallback，既有行為不回歸）', () => {
  const file = {
    searchResults: [
      { number: 'ABC-001' },
      { number: 'ABC-002' },
    ],
    // selectedCandidateIndex 缺省
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '' });
});

// P2 fix（PR#115 Codex）: date input 對非 YYYY-MM-DD 值顯示空白（toDateInputValue），但
// model 的 current().date 仍留原始非法值。若整理送出不經同一正規化，會把畫面上看不到的非法
// 值寫進 NFO <premiered> + 資料夾名。以下鎖「整理送出＝輸入框顯示值」，拿掉正規化即 RED。
test('buildOrganizeMetadata: date 為非 YYYY-MM-DD 格式（如 2020/01/01）→ 正規化為空字串', () => {
  const file = {
    searchResults: [{ number: 'ABC-001', date: '2020/01/01' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '' });
});

test('buildOrganizeMetadata: date 為 ISO 帶時間戳（如 2020-01-01T00:00:00Z）→ 正規化為空字串', () => {
  const file = {
    searchResults: [{ number: 'ABC-001', date: '2020-01-01T00:00:00Z' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '' });
});

test('buildOrganizeMetadata: date 為合法 YYYY-MM-DD → 原樣送出（no-op）', () => {
  const file = {
    searchResults: [{ number: 'ABC-001', date: '2020-01-01' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '2020-01-01' });
});

test('buildOrganizeMetadata: date 缺席 → 正規化為空字串', () => {
  const file = {
    searchResults: [{ number: 'ABC-001' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '' });
});

test('loadMore: listMode="file" → 立即回傳 null、不呼叫 fetch（CD-106-5 P1-#2 順修 pre-existing bug）', async () => {
  let fetchCalls = 0;
  globalThis.fetch = async () => { fetchCalls++; return { ok: true, json: async () => ({}) }; };

  // 刻意把 file-mode guard 之後、fetch 呼叫之前（含 finally 區塊）所有會被讀到的欄位都填好
  // （searchResults／currentOffset／PAGE_SIZE／_getAbortSignal／_clearAbort）——若把
  // `if (this.listMode==='file') return null;` 這行拿掉，loadMore 應能真的跑完整段（含
  // fetch() 與 finally）。這樣本測試才是靠 `fetchCalls === 0` 斷言殺掉 mutant，而不是靠拿掉
  // guard 後某個缺欄位造成的 TypeError 意外殺掉（test faithfulness；曾實測驗證：先只補
  // fetch 前段欄位，mutant 是被 finally 區塊的 `this._clearAbort is not a function` crash
  // 殺掉，不是被本斷言殺掉——因此補齊 _clearAbort stub）。
  const fakeThis = {
    ...searchStateNavigation(),
    listMode: 'file',
    isLoadingMore: false,
    hasMoreResults: true,
    currentQuery: 'ABC-123',
    searchResults: [{ number: 'ABC-001' }],
    currentOffset: 0,
    PAGE_SIZE: 20,
    _getAbortSignal: () => undefined,
    _clearAbort: () => {},
  };

  const result = await searchStateNavigation().loadMore.call(fakeThis, 'detail');

  assert.equal(result, null, 'file 模式下 loadMore 應立即回傳 null');
  assert.equal(fetchCalls, 0, 'file 模式下 loadMore 不應觸發 /api/search 請求');
});

test('canGoNext: file 模式末檔 + hasMoreResults=true + 無下個可見候選 → false（round-3 P2 回歸鎖，現況會誤回 true）', () => {
  const fakeThis = {
    ...searchStateBase(),
    listMode: 'file',
    searchResults: [{ number: 'ABC-001' }, { number: 'ABC-002' }],
    currentIndex: 1, // 已在最後一個候選，往後無非-_failed 項
    hasMoreResults: true, // loadMore 已被 CD-106-5 file 模式硬關，此 flag 不該再讓按鈕可點
    currentFileIndex: 0,
    fileList: [{ path: '/a/x1.mp4' }], // 只有一檔，currentFileIndex 已是最後一檔
  };

  assert.equal(searchStateBase().canGoNext.call(fakeThis), false);
});
