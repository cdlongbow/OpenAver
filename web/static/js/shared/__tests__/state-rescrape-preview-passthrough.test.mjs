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

// ---------------------------------------------------------------------------
// TASK-113c-T8 P1（Codex PR#128 round-4）：`_previewFailed` 不得隨採用流入 result
// ---------------------------------------------------------------------------
// 上面兩支守的是「新欄位要自動同進同出」；這兩支守的是**反面**——
// `_previewFailed` 是彈窗這一次顯示的暫態旗標（rescrapePreview 依 CD-62-2 是
// transient），不是資料。漏剝的話：彈窗裡預覽失敗過一次 → 採用後那一筆帶著旗標
// 進 searchResults → saveState() 持久化 → 即使 metatube 已恢復也永遠停在 cover。
//
// 判準分界：**沒有底線前綴的欄位 = 來自 API 的資料 → 同進同出；
// `_previewFailed` = 客戶端暫態 → 剝除。** 兩者不是同一類東西。

function makeFailedPreview() {
  return { ...makePreview(), _previewFailed: true };
}

test('rescrapeConfirm (search 入口): 彈窗曾 fallback 過 → 採用後的 result 不得帶 _previewFailed', async () => {
  let committed = null;
  const fakeThis = {
    ...rescrapeState(),
    _rescraping: false,
    rescrapeCfWaiting: false,
    rescrapeEntryPoint: 'search',
    rescrapePreview: makeFailedPreview(),
    rescrapeNumber: 'ABC-001',
    searchQuery: '',
    currentQuery: '',
    _commitSearchResults: (payload) => { committed = payload; },
    closeRescrape: () => {},
  };

  await rescrapeState().rescrapeConfirm.call(fakeThis);

  const adopted = committed.data[0];
  assert.ok(!('_previewFailed' in adopted),
    '_previewFailed 是彈窗暫態，不得流入 searchResults（會被 saveState 持久化）');
  // 同時確認資料欄位沒有被連坐剝掉
  assert.equal(adopted.preview_cover_url, 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x');
  assert.equal(adopted.cover, 'http://example.com/cover.jpg');
});

test('rescrapeConfirm (switch-source 入口): 彈窗曾 fallback 過 → 原地替換的 result 不得帶 _previewFailed', async () => {
  const searchResults = [{ number: 'ABC-001', cover: 'http://old/cover.jpg' }];
  const target = { arr: searchResults, idx: 0, number: 'ABC-001', listMode: 'search' };
  let saved = 0;

  const fakeThis = {
    ...rescrapeState(),
    _rescraping: false,
    rescrapeCfWaiting: false,
    rescrapeEntryPoint: 'switch-source',
    rescrapePreview: makeFailedPreview(),
    rescrapeNumber: 'ABC-001',
    _switchTarget: target,
    searchResults,
    fileList: [],
    _rescrapeCommitSource: 'metatube:FANZA',
    _candidateReplaceSeq: 0,
    _resetCoverState: () => {},
    saveState: () => { saved += 1; },
    closeRescrape: () => {},
  };

  await rescrapeState().rescrapeConfirm.call(fakeThis);

  const replaced = searchResults[0];
  assert.equal(saved, 1, '本分支會顯式 saveState() —— 正是漏剝時旗標被持久化的那一步');
  assert.ok(!('_previewFailed' in replaced),
    '_previewFailed 不得隨原地替換寫進 searchResults 並被 saveState 持久化');
  assert.equal(replaced.preview_cover_url, 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x');
});
