// TASK-103-T5: parseFilenames throw 語意 + `{ signal } = {}` 預設值守衛（CD-4）
//
// 舊版 parseFilenames 內建 try/catch，API 失敗時靜默 fallback 到本地番號解析——
// 本 task 拔掉 fallback，改為 fail-loud（!response.ok 時 throw；fetch reject 原樣往外傳，
// 含 AbortError，不得被重新包裝弄丟 err.name）。呼叫端（setFileList/handleFileDrop）
// 各自決定失敗語意，不再由 parseFilenames 自己吞錯誤。
//
// file.js 是 classic script（掛到 window.SearchFile），沿用 file-number-caps.test.mjs
// 的 `globalThis.window = globalThis; await import('../file.js')` 手法。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
await import('../file.js');
const { parseFilenames } = globalThis.window.SearchFile;

function stubFetch(impl) {
  const calls = [];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return impl(...args);
  };
  return calls;
}

test('parseFilenames: response.ok → 回傳 data.results', async () => {
  stubFetch(async () => ({
    ok: true,
    json: async () => ({ results: [{ filename: 'a.mp4', number: 'ABC-123', has_subtitle: false }] }),
  }));
  const results = await parseFilenames(['a.mp4']);
  assert.deepEqual(results, [{ filename: 'a.mp4', number: 'ABC-123', has_subtitle: false }]);
});

test('parseFilenames: !response.ok → throw Error(`HTTP ${status}`)（fail-loud，不再靜默 fallback 到本地番號解析）', async () => {
  stubFetch(async () => ({ ok: false, status: 500 }));
  await assert.rejects(() => parseFilenames(['a.mp4']), /HTTP 500/);
});


