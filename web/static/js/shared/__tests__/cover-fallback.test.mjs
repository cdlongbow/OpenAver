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


// ===== shouldFallbackToCover =====

test('shouldFallbackToCover: preview 與 cover 皆存在、不同、尚未 fallback → true', () => {
  const result = {
    preview_cover_url: 'http://mt:8080/v1/images/primary/FANZA/ABC-001?url=x',
    cover: 'http://example.com/cover.jpg',
  };
  assert.equal(shouldFallbackToCover(result), true);
});


// ===== clearPreviewFailedFlags（restoreState() reset 點，裁決 3）=====


// ---------------------------------------------------------------------------
// isStaleCoverError —— Sonnet review P2：持久旗標必須配 stale guard
// ---------------------------------------------------------------------------
// 燈箱 <img> 是單一元素跨候選重用。舊碼的 @error 寫的是頁面層 boolean（切走即被重置，
// 寫錯了也無害），本 task 改寫的是**跟著資料走的持久旗標** _previewFailed——寫到錯的
// 候選上，那一筆會整個 session 停在 cover，明明它的 preview 是好的。

const PROXY = (raw) => `/api/proxy-image?url=${encodeURIComponent(raw)}`;


test('isStaleCoverError: src 是上一張候選的（使用者已切走）→ 判 stale，必須忽略', () => {
  const oldRaw = 'http://mt:8080/v1/images/primary/FANZA/OLD-1?url=x';
  const nowRaw = 'http://mt:8080/v1/images/primary/FANZA/NEW-2?url=y';
  assert.equal(isStaleCoverError(PROXY(oldRaw), nowRaw), true);
});


