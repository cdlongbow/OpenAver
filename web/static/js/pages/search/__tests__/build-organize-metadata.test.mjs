// TASK-106-T2' CD-106-5/CD-106-8: 「整理送實際候選」bug 修復
//
// buildOrganizeMetadata 是 batch.js 的 module-level 純函式（CD-106-8，不依賴 this），
// 直接 import 測試，不需 .call(fakeThis)。
//
// loadMore 的 file 模式硬關（CD-106-5 P1-#2）與 canGoNext() 的 file 分支去
// hasMoreResults（CD-106-5 round-3 P2）都是讀 this.* 的 mixin method，用
// .call(fakeThis) 呼叫（同 can-edit-file.test.mjs / set-file-list-fallback.test.mjs 慣例）。
//
// 本檔同時測 navigation.js 的 loadMore／canGoNext，而 navigation.js 匯入瀏覽器 importmap
// 別名 `@/shared/...`——plain `node --test` 不認得，需先掛 alias-loader resolve hook 才能 import。
// register() 於 body 執行、靜態 import link phase 之後才生效，故 navigation.js 與 batch.js 皆
// 在 register() 之後動態 import（batch.js 一併沿用同做法，保持一致）。

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

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-003' });
});

test('buildOrganizeMetadata: selectedCandidateIndex 未設 → 送 searchResults[0]（?? 0 fallback，既有行為不回歸）', () => {
  const file = {
    searchResults: [
      { number: 'ABC-001' },
      { number: 'ABC-002' },
    ],
    // selectedCandidateIndex 缺省
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001' });
});

// T7: date 正規化雙寫已回退（buildOrganizeMetadata = {...cand}）。候選 date 隨 raw 直通、
// 不再經 toDateInputValue——新設計中有日期走唯讀 raw span、無日期才出（只能吐合法值的）picker，
// 唯讀 span 顯示即整理送出值（顯示＝整理一致）。以下鎖「合法日期原值直通、缺席即無 date key」。
test('buildOrganizeMetadata: date 為合法 YYYY-MM-DD → 原值直通（raw，不正規化）', () => {
  const file = {
    searchResults: [{ number: 'ABC-001', date: '2020-01-01' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001', date: '2020-01-01' });
});

test('buildOrganizeMetadata: date 缺席 → 無 date key（不再正規化為空字串）', () => {
  const file = {
    searchResults: [{ number: 'ABC-001' }],
  };

  assert.deepEqual(buildOrganizeMetadata(file), { number: 'ABC-001' });
});

// TASK-126（Codex PR review P2）：這兩支從「驗**不傳遞**」翻成「驗**傳遞**」。
//
// 113c-T3b 立的規矩逐字是「preview_* **不能落磁碟**」，剝除只是當時達成它的手段。
// 兩件事分開之後：不變式（不落磁碟）由 `tests/unit/test_organizer.py::TestT6PreviewNotPersisted`
// 直接驗證產出的 NFO 與 DB；而傳遞是**必要的**——搜尋後按「產生」是最常走的入庫路徑，
// 後端不會重新搜尋，不傳等於被牆的使用者永遠拿不到代理退路（spec §3.2 的承諾）。
//
// ⚠️ 這兩支測試的**方向被刻意翻面了**。若日後有人想改回剝除，請先讀
// `feature/126-metatube-image-proxy/CODEX-ROUND1-FIXES.md`。

test('buildOrganizeMetadata: preview_cover_url 必須傳給 /api/scrape-single（下載端的代理退路）', () => {
  const file = {
    searchResults: [{
      number: 'ABC-001',
      cover: 'http://example/cover.jpg',
      preview_cover_url: 'http://mt:8080/v1/images/primary/MGS/ABC-001?url=c',
    }],
  };

  const result = buildOrganizeMetadata(file);
  assert.equal(
    result.preview_cover_url,
    'http://mt:8080/v1/images/primary/MGS/ABC-001?url=c',
    '剝掉它 → 被牆的使用者按「產生」永遠拿不到封面，而且沒有錯誤訊息',
  );
  assert.equal(result.cover, 'http://example/cover.jpg', '原址必須一併保留（原址優先）');
});

test('buildOrganizeMetadata: preview_sample_images 必須傳給 /api/scrape-single', () => {
  const file = {
    searchResults: [{
      number: 'ABC-001',
      sample_images: ['http://example/s1.jpg', 'http://example/s2.jpg'],
      preview_sample_images: ['http://mt:8080/v1/images/primary/MGS/ABC-001?url=s1', ''],
      preview_cover_url: 'http://mt:8080/v1/images/primary/MGS/ABC-001?url=c',
    }],
  };

  const result = buildOrganizeMetadata(file);
  assert.deepEqual(
    result.preview_sample_images,
    ['http://mt:8080/v1/images/primary/MGS/ABC-001?url=s1', ''],
    '逐張傳遞，含空字串那一格（空＝這格沒有代理，落回原址）',
  );
  assert.deepEqual(result.sample_images, ['http://example/s1.jpg', 'http://example/s2.jpg']);
});

test('buildOrganizeMetadata: 仍然只送選中的那個候選，不混到別的候選', () => {
  const file = {
    selectedCandidateIndex: 1,
    searchResults: [
      { number: 'WRONG-000', cover: 'http://example/wrong.jpg' },
      { number: 'ABC-001', cover: 'http://example/right.jpg', preview_cover_url: 'http://mt:8080/p' },
    ],
  };
  const result = buildOrganizeMetadata(file);
  assert.equal(result.number, 'ABC-001');
  assert.equal(result.preview_cover_url, 'http://mt:8080/p');
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
