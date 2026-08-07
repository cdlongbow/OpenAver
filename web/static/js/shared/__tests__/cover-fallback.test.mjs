// TASK-113c-T7/T8: preview_cover_url 破圖 fallback 補上 error-time 重試（Codex PR#128
// round-3 P2）。三個顯示點（detail / hero lightbox / grid card）共用的兩顆純函式：
// resolveResultCoverUrl（決定這次要顯示 preview 還是 cover，回傳原始 URL，裁決 2：
// proxy 包裹留在呼叫點，不在這裡）與 shouldFallbackToCover（決定這次失敗要不要觸發
// fallback）。以及 persistence.js::clearPreviewFailedFlags（restoreState() 的 reset
// 點，裁決 3：測「清除函式本身」，不測 restoreState 跑完後的某個時間點）。
//
// 比照既有 staging-cover-preview.test.mjs 的抽出-純函式模式，同一種先例。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

// result-card.js 頂部 import { openLocal } from '@/shared/open-local.js'（瀏覽器
// importmap 別名，見 web/templates/base.html `"@/shared/": "/static/js/shared/"`）。
// plain `node --test` 不認得這個別名——比照既有
// pages/search/__tests__/confirm-edit-identity-guard.test.mjs 的先例，用同一顆
// alias-loader.mjs（scope 僅本測試檔的 module graph，不動 package.json）。
register(new URL('../../pages/search/__tests__/alias-loader.mjs', import.meta.url), import.meta.url);
const { resolveResultCoverUrl, shouldFallbackToCover, isStaleCoverError } = await import('../cover-fallback.js');
const { clearPreviewFailedFlags } = await import('../../pages/search/state/persistence.js');

// ===== resolveResultCoverUrl =====

test('resolveResultCoverUrl: preview 存在且未失敗 → 優先於 cover', () => {
  const result = {
    cover: 'http://example.com/cover.jpg',
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  };
  assert.equal(
    resolveResultCoverUrl(result),
    'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  );
});

test('resolveResultCoverUrl: _previewFailed 為 true → 改用 cover（即使 preview_cover_url 仍在）', () => {
  const result = {
    cover: 'http://example.com/cover.jpg',
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
    _previewFailed: true,
  };
  assert.equal(resolveResultCoverUrl(result), 'http://example.com/cover.jpg');
});

test('resolveResultCoverUrl: preview_cover_url 為空字串 → fallback 回 cover（FE-JS-01：|| 對空字串 fallback 行為保留）', () => {
  const result = { cover: 'http://example.com/cover.jpg', preview_cover_url: '' };
  assert.equal(resolveResultCoverUrl(result), 'http://example.com/cover.jpg');
});

test('resolveResultCoverUrl: 沒有 preview_cover_url 欄位（pre-T3b 舊資料）→ 沿用 cover（不回歸）', () => {
  const result = { cover: 'http://example.com/cover.jpg' };
  assert.equal(resolveResultCoverUrl(result), 'http://example.com/cover.jpg');
});

test('resolveResultCoverUrl: preview 與 cover 皆缺 → 空字串', () => {
  assert.equal(resolveResultCoverUrl({}), '');
});

test('resolveResultCoverUrl: falsy input → 空字串（不炸）', () => {
  assert.equal(resolveResultCoverUrl(undefined), '');
  assert.equal(resolveResultCoverUrl(null), '');
});

// ===== shouldFallbackToCover =====

test('shouldFallbackToCover: preview 與 cover 皆存在、不同、尚未 fallback → true', () => {
  const result = {
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
    cover: 'http://example.com/cover.jpg',
  };
  assert.equal(shouldFallbackToCover(result), true);
});

test('shouldFallbackToCover: 已經 _previewFailed（已經在用 cover）→ false', () => {
  const result = {
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
    cover: 'http://example.com/cover.jpg',
    _previewFailed: true,
  };
  assert.equal(shouldFallbackToCover(result), false);
});

test('shouldFallbackToCover: 沒有 cover 可退 → false', () => {
  const result = {
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
  };
  assert.equal(shouldFallbackToCover(result), false);
});

test('shouldFallbackToCover: cover 是空字串 → false', () => {
  const result = {
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
    cover: '',
  };
  assert.equal(shouldFallbackToCover(result), false);
});

test('shouldFallbackToCover: preview === cover（退了也沒差）→ false', () => {
  const result = {
    preview_cover_url: 'http://example.com/cover.jpg',
    cover: 'http://example.com/cover.jpg',
  };
  assert.equal(shouldFallbackToCover(result), false);
});

test('shouldFallbackToCover: 沒有 preview（舊資料，從未組出過 preview_cover_url）→ false', () => {
  const result = { cover: 'http://example.com/cover.jpg' };
  assert.equal(shouldFallbackToCover(result), false);
});

test('shouldFallbackToCover: falsy input → false（不炸）', () => {
  assert.equal(shouldFallbackToCover(undefined), false);
  assert.equal(shouldFallbackToCover(null), false);
});

// ===== clearPreviewFailedFlags（restoreState() reset 點，裁決 3）=====

test('clearPreviewFailedFlags: 陣列內部分結果帶 _previewFailed:true → 清除後全部不帶', () => {
  const results = [
    { number: 'ABC-001', _previewFailed: true },
    { number: 'ABC-002' },
    { number: 'ABC-003', _previewFailed: true },
  ];
  clearPreviewFailedFlags(results);
  assert.equal('_previewFailed' in results[0], false);
  assert.equal('_previewFailed' in results[1], false);
  assert.equal('_previewFailed' in results[2], false);
});

test('clearPreviewFailedFlags: 沒有該欄位的物件不受影響（其餘欄位不動）', () => {
  const untouched = { number: 'ABC-002', cover: 'http://example.com/cover.jpg' };
  const results = [untouched];
  clearPreviewFailedFlags(results);
  assert.equal(results[0], untouched);
  assert.deepEqual(results[0], { number: 'ABC-002', cover: 'http://example.com/cover.jpg' });
});

test('clearPreviewFailedFlags: 非陣列輸入（undefined/null）原樣回傳，不炸', () => {
  assert.equal(clearPreviewFailedFlags(undefined), undefined);
  assert.equal(clearPreviewFailedFlags(null), null);
});

test('clearPreviewFailedFlags: 回傳同一個陣列參照（就地清除）', () => {
  const results = [{ _previewFailed: true }];
  const out = clearPreviewFailedFlags(results);
  assert.equal(out, results);
});


// ---------------------------------------------------------------------------
// isStaleCoverError —— Sonnet review P2：持久旗標必須配 stale guard
// ---------------------------------------------------------------------------
// 燈箱 <img> 是單一元素跨候選重用。舊碼的 @error 寫的是頁面層 boolean（切走即被重置，
// 寫錯了也無害），本 task 改寫的是**跟著資料走的持久旗標** _previewFailed——寫到錯的
// 候選上，那一筆會整個 session 停在 cover，明明它的 preview 是好的。

const PROXY = (raw) => `/api/proxy-image?url=${encodeURIComponent(raw)}`;

test('isStaleCoverError: src 與當前候選相符 → 不是 stale（要正常處理這發 error）', () => {
  const raw = 'http://mt:8080/v1/images/primary/FANZA/A-1?url=x';
  assert.equal(isStaleCoverError(PROXY(raw), raw), false);
});

test('isStaleCoverError: src 是上一張候選的（使用者已切走）→ 判 stale，必須忽略', () => {
  const oldRaw = 'http://mt:8080/v1/images/primary/FANZA/OLD-1?url=x';
  const nowRaw = 'http://mt:8080/v1/images/primary/FANZA/NEW-2?url=y';
  assert.equal(isStaleCoverError(PROXY(oldRaw), nowRaw), true);
});

test('isStaleCoverError: 沒有期望值（女優燈箱／無影片）→ 不判 stale，交給既有分支', () => {
  assert.equal(isStaleCoverError(PROXY('http://mt/x'), ''), false);
  assert.equal(isStaleCoverError(PROXY('http://mt/x'), undefined), false);
});

test('isStaleCoverError: src 讀不到（空字串）→ 不判 stale，不要吞掉真的失敗', () => {
  assert.equal(isStaleCoverError('', 'http://mt/x'), false);
});

test('isStaleCoverError: 已 fallback 到 cover 後，cover 自己失敗那一發不得被誤判成 stale', () => {
  const cover = 'https://cdn.example.com/a.jpg';
  assert.equal(isStaleCoverError(PROXY(cover), cover), false);
});
