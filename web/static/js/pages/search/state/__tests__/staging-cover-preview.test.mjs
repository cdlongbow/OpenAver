// TASK-113c-T3b DoD-5：search-flow.js:233 的 stagingCover 賦值——顯示點對帳表 #9，
// 全表唯一真正決定「staging 卡片預覽能不能生效」的賦值點。search.html:674 讀的
// `stagingCover` 是純字串 state（宣告 base.js:34），漏改這裡＝樣板改對了也沒用。
//
// resolveStagingCoverUrl() 是從該賦值點抽出的 module-level 純函式（見
// search-flow.js 頂部），不需要模擬真 SSE/DOM。
//
// `state/` 這層目前無 __tests__/，本檔是 TASK-113c-T3b 唯一該在此新建測試的地方
// （Opus 審核裁決 3：buildOrganizeMetadata 的測試併入既有
// search/__tests__/build-organize-metadata.test.mjs，不在此重開）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveStagingCoverUrl } from '../search-flow.js';

test('resolveStagingCoverUrl: preview_cover_url 存在 → 優先於 cover', () => {
  const item = {
    cover: 'http://example.com/cover.jpg',
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  };
  assert.equal(
    resolveStagingCoverUrl(item),
    'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  );
});

test('resolveStagingCoverUrl: preview_cover_url 為空字串 → fallback 回 cover（FE-JS-01：|| 對空字串 fallback 是要的行為）', () => {
  const item = { cover: 'http://example.com/cover.jpg', preview_cover_url: '' };
  assert.equal(resolveStagingCoverUrl(item), 'http://example.com/cover.jpg');
});

test('resolveStagingCoverUrl: 兩者皆缺 → 空字串（不炸）', () => {
  assert.equal(resolveStagingCoverUrl({}), '');
  assert.equal(resolveStagingCoverUrl(undefined), '');
});

test('resolveStagingCoverUrl: 沒有 preview_cover_url 欄位（既有候選/舊資料）→ 沿用 cover（不回歸）', () => {
  const item = { cover: 'http://example.com/cover.jpg' };
  assert.equal(resolveStagingCoverUrl(item), 'http://example.com/cover.jpg');
});
