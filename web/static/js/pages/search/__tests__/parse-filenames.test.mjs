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

test('parseFilenames: fetch reject（AbortError）原樣往外傳，err.name 不被重新包裝掉', async () => {
  const abortErr = new DOMException('The operation was aborted', 'AbortError');
  globalThis.fetch = async () => { throw abortErr; };
  await assert.rejects(
    () => parseFilenames(['a.mp4']),
    (err) => err.name === 'AbortError' && err === abortErr,
  );
});

test('parseFilenames: 不傳第二引數呼叫 parseFilenames(filenames) 不得拋出 TypeError（`{ signal } = {}` 預設值不可省，CD-4 陷阱點）', async () => {
  stubFetch(async () => ({ ok: true, json: async () => ({ results: [] }) }));
  // setFileList:316 只傳一個引數呼叫 parseFilenames(filenames)。若簽章寫成
  // `{ signal }`（無預設值），對 undefined 解構會立即同步 throw TypeError——
  // 這個 TypeError 會被 setFileList 新加的 catch 誤判成「API 不可用」，
  // 症狀是「批次選檔永遠顯示連線失敗」但根因其實是簽章寫法。
  await assert.doesNotReject(() => parseFilenames(['a.mp4']));
});

test('parseFilenames: 帶 signal 呼叫時，fetch 的 options 內含相同 signal（供 AbortController 取消 in-flight request）', async () => {
  const controller = new AbortController();
  const calls = stubFetch(async () => ({ ok: true, json: async () => ({ results: [] }) }));
  await parseFilenames(['a.mp4'], { signal: controller.signal });
  const [, options] = calls[0];
  assert.equal(options.signal, controller.signal);
});
