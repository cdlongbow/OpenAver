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

globalThis.window = globalThis;

// navigation.js／batch.js 匯入瀏覽器 importmap 別名 `@/shared/...`（見 alias-loader.mjs
// 註解），掛一個 scope 僅本檔的 resolve hook 後才能動態 import。
register(new URL('./alias-loader.mjs', import.meta.url), import.meta.url);
const { buildOrganizeMetadata } = await import('../state/batch.js');

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


// T7: date 正規化雙寫已回退（buildOrganizeMetadata = {...cand}）。候選 date 隨 raw 直通、
// 不再經 toDateInputValue——新設計中有日期走唯讀 raw span、無日期才出（只能吐合法值的）picker，
// 唯讀 span 顯示即整理送出值（顯示＝整理一致）。以下鎖「合法日期原值直通、缺席即無 date key」。


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


