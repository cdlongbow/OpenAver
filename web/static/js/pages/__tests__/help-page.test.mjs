// TASK-107-P1-T3: helpPage init() gate 矩陣 + saveAutoCheckUpdate PUT wiring
//
// 核心不變式（spec-107 D-A1）：非桌面 → init() 一律不呼叫 checkUpdate()
// （對 /api/check-update 零請求 = 零 GitHub 連線）。此為 behavioral 不變式，
// 必須真的執行 init() 用 fetch spy 斷言「有沒有呼叫」，源碼字串比對證不了。
//
// help.js 是 exported page-module（Option A：export function helpPage + 保留
// alpine:init 註冊，比照 scanner/main.js:23）。模組頂層有
// `document.addEventListener('alpine:init', ...)`，node 無 document，故 import
// 前先 stub document（callback 只註冊、import 時不執行，不需真 Alpine）。
//
// 範本：search/__tests__/confirm-edit-actors-fetch-spy.test.mjs
// （globalThis.window = globalThis + fetch spy + fakeThis 展開 mixin）。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };
globalThis.t = (key) => key;

const { helpPage } = await import('../help.js');

// fetch spy：記錄每次呼叫的 url/method/body，回傳成功殼
function installFetchSpy() {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', body: opts.body });
    return { ok: true, json: async () => ({ success: true, has_update: false }) };
  };
  return calls;
}

function makeFakeThis(isDesktop, autoCheckUpdate) {
  return {
    ...helpPage(),
    $el: { dataset: { isDesktop, autoCheckUpdate } },
  };
}

// init() 內 loadVersion()/checkUpdate() 皆 async 但同步呼到第一個 await（fetch）
// 前，故 init.call() 返回後 fetch spy 已記錄；斷言 /api/check-update 有無即可。
function checkUpdateHit(calls) {
  return calls.some((c) => c.url === '/api/check-update');
}

test('init gate: (桌面, on) → checkUpdate 觸發（打 /api/check-update）', () => {
  const calls = installFetchSpy();
  const fakeThis = makeFakeThis('true', 'true');
  fakeThis.init();
  assert.equal(checkUpdateHit(calls), true, '桌面+開 應自動查更新');
  assert.equal(calls.some((c) => c.url === '/api/version'), true, 'init 仍呼 loadVersion');
});

test('init gate: (桌面, off) → 不打 /api/check-update（idle，與現況一致）', () => {
  const calls = installFetchSpy();
  const fakeThis = makeFakeThis('true', 'false');
  fakeThis.init();
  assert.equal(checkUpdateHit(calls), false, '桌面+關 不應自動查更新');
});

test('init gate: (非桌面, on) → 不打 /api/check-update（核心不變式：非桌面零 GitHub）', () => {
  const calls = installFetchSpy();
  const fakeThis = makeFakeThis('false', 'true');
  fakeThis.init();
  assert.equal(checkUpdateHit(calls), false, '非桌面 即使 on 也不得連 GitHub（spec D-A1）');
});

test('init gate: (非桌面, off) → 不打 /api/check-update', () => {
  const calls = installFetchSpy();
  const fakeThis = makeFakeThis('false', 'false');
  fakeThis.init();
  assert.equal(checkUpdateHit(calls), false, '非桌面+關 不查');
});

test('init 初值讀取：dataset → autoCheckUpdate / _isDesktop 正確反映', () => {
  installFetchSpy();
  const on = makeFakeThis('true', 'true');
  on.init();
  assert.equal(on._isDesktop, true);
  assert.equal(on.autoCheckUpdate, true);

  const off = makeFakeThis('false', 'false');
  off.init();
  assert.equal(off._isDesktop, false);
  assert.equal(off.autoCheckUpdate, false);
});

test('saveAutoCheckUpdate: on → PUT /api/config/general/auto_check_update body {"value":true}', async () => {
  const calls = installFetchSpy();
  const fakeThis = { ...helpPage(), autoCheckUpdate: true };
  await fakeThis.saveAutoCheckUpdate();
  const put = calls.find((c) => c.url === '/api/config/general/auto_check_update');
  assert.ok(put, '應打 auto_check_update 端點');
  assert.equal(put.method, 'PUT');
  assert.equal(put.body, JSON.stringify({ value: true }));
});

test('saveAutoCheckUpdate: off → body {"value":false}', async () => {
  const calls = installFetchSpy();
  const fakeThis = { ...helpPage(), autoCheckUpdate: false };
  await fakeThis.saveAutoCheckUpdate();
  const put = calls.find((c) => c.url === '/api/config/general/auto_check_update');
  assert.ok(put);
  assert.equal(put.method, 'PUT');
  assert.equal(put.body, JSON.stringify({ value: false }));
});
