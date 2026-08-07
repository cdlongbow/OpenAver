// TASK-113c-T3b DoD-6：re-inject 一致性回歸鎖。
//
// state-rescrape.js 的 rescrapeConfirm() 在 'search' 與 'switch-source' 兩個入口都用
// 排除法解構（`const { success: _s, sourceName: _sn, sourceCensored: _sc, ...adopted }`）
// 把 rescrapePreview 攤回結果物件——這個寫法讓任何新 key（含 preview_cover_url）
// 自動跟著 cover 一起「同進同出」，不需要手動列欄位名。
//
// 這支測試在正確實作下必定通過（見 TASK-113c-T3b.md 設計問題 5）：它守的是「以後不要
// 退化」——例如某天有人把 spread 改成手動列欄位、或把 preview_cover_url 加進排除清單，
// 這支測試會轉紅。不是「現在有 bug」。
//
// state-rescrape.js 匯入瀏覽器 importmap 別名 `@/components/...`，plain `node --test`
// 不認得，沿用 pages/search/__tests__/alias-loader.mjs 的既有 resolve hook（純字首轉譯，
// 與呼叫端所在目錄無關，見該檔說明）。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;

register(
  new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);
const { rescrapeState } = await import('../state-rescrape.js');

function makePreview() {
  return {
    success: true,
    sourceName: 'FANZA',
    sourceCensored: true,
    number: 'ABC-001',
    cover: 'http://example.com/cover.jpg',
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  };
}

test('rescrapeConfirm (search 入口): rescrapePreview 解構重注入 → cover 與 preview_cover_url 同進同出', async () => {
  let committed = null;
  const fakeThis = {
    ...rescrapeState(),
    _rescraping: false,
    rescrapeCfWaiting: false,
    rescrapeEntryPoint: 'search',
    rescrapePreview: makePreview(),
    rescrapeNumber: 'ABC-001',
    searchQuery: '',
    currentQuery: '',
    _commitSearchResults: (payload) => { committed = payload; },
    closeRescrape: () => {},
  };

  await rescrapeState().rescrapeConfirm.call(fakeThis);

  assert.ok(committed, '_commitSearchResults 應被呼叫');
  const adopted = committed.data[0];
  assert.equal(adopted.cover, 'http://example.com/cover.jpg');
  assert.equal(adopted.preview_cover_url, 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x');
  // transient-only 欄位仍應被剝除（既有行為不回歸）
  assert.ok(!('success' in adopted));
  assert.ok(!('sourceName' in adopted));
  assert.ok(!('sourceCensored' in adopted));
});

test('rescrapeConfirm (switch-source 入口): rescrapePreview 解構重注入 → cover 與 preview_cover_url 同進同出', async () => {
  const searchResults = [{ number: 'ABC-001', cover: 'http://old/cover.jpg' }];
  const target = { arr: searchResults, idx: 0, number: 'ABC-001', listMode: 'search' };

  const fakeThis = {
    ...rescrapeState(),
    _rescraping: false,
    rescrapeCfWaiting: false,
    rescrapeEntryPoint: 'switch-source',
    rescrapePreview: makePreview(),
    rescrapeNumber: 'ABC-001',
    _switchTarget: target,
    searchResults,
    fileList: [],
    _rescrapeCommitSource: 'metatube:FANZA',
    _candidateReplaceSeq: 0,
    _resetCoverState: () => {},
    saveState: () => {},
    closeRescrape: () => {},
  };

  await rescrapeState().rescrapeConfirm.call(fakeThis);

  const replaced = searchResults[0];
  assert.equal(replaced.cover, 'http://example.com/cover.jpg');
  assert.equal(replaced.preview_cover_url, 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x');
  assert.ok(!('success' in replaced));
  assert.ok(!('sourceName' in replaced));
  assert.ok(!('sourceCensored' in replaced));
});
