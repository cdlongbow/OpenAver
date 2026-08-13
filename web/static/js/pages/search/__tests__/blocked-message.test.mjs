// TASK-118-T4c: blocked 與 not_found 的使用者可見字串必須不同（AC-4.1）
//
// 四個「結果為空」渲染點依 data.blocked 分流。window.t 走真字典查表
// （locales/zh_TW.json），「逐字不變」比的是使用者字串，不是 key 名。

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { searchStateFileList } from '../state/file-list.js';
import { searchStateSearchFlow } from '../state/search-flow.js';
import { searchStateBase } from '../state/base.js';

const zhTW = JSON.parse(
  readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..', '..', 'locales', 'zh_TW.json'),
    'utf8',
  ),
);

function lookup(dict, key) {
  return key.split('.').reduce((o, k) => (o == null ? o : o[k]), dict);
}

function installT() {
  window.t = (key, params = {}) => {
    const val = lookup(zhTW, key);
    if (typeof val !== 'string') return '[' + key + ']';
    return val.replace(/\{(\w+)\}/g, (_, k) => (
      Object.prototype.hasOwnProperty.call(params, k) ? params[k] : '{' + k + '}'
    ));
  };
}

// 卡片規定的使用者可見 blocked 字面（寫死，不得從 dict 回推，否則 locale 未寫時會假綠）
const BLOCKED_TEXT = 'FC2 官方站目前連不上（可能被擋或暫時無回應），這不代表沒有這部片，稍後再試一次';
const FILELIST_BLOCKED = (number) => `${number}：來源目前連不上（可能被擋或暫時無回應），這不代表沒有這部片，稍後再試一次`;
const NO_DATA = '找不到資料';
const FILELIST_NOT_FOUND = (number) => `找不到 ${number} 的資料`;

assert.equal(lookup(zhTW, 'search.error.no_data'), NO_DATA);
assert.equal(lookup(zhTW, 'search.filelist.not_found'), '找不到 {number} 的資料');

globalThis.window = globalThis;
globalThis.document = { querySelector: () => null };
globalThis.requestAnimationFrame = (fn) => fn();

class FakeEventSource {
  static instances = [];
  static CLOSED = 2;
  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
    this.readyState = 0;
    FakeEventSource.instances.push(this);
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

function lastES() {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1];
}

function emit(es, payload) {
  es.onmessage({ data: JSON.stringify(payload) });
}

function makeFakeThis(overrides = {}) {
  return Object.assign(
    {},
    searchStateBase(),
    searchStateSearchFlow(),
    searchStateFileList(),
    {
      _resetCoverState() {},
      $nextTick(fn) { fn(); },
      checkLocalStatus() {},
      preloadImages() {},
    },
    overrides,
  );
}

function setup() {
  FakeEventSource.instances = [];
  globalThis.EventSource = FakeEventSource;
  installT();
}

async function driveBranch1(thisArg, resultExtra) {
  await thisArg.doSearch('FC2-123456');
  const es = lastES();
  emit(es, { type: 'seed', slots: ['FC2-123456'] });
  emit(es, { type: 'result-complete' });
  emit(es, { type: 'result', success: false, data: [], ...resultExtra });
}

async function driveBranch2(thisArg, resultExtra) {
  await thisArg.doSearch('FC2-123456');
  emit(lastES(), { type: 'result', success: false, data: [], ...resultExtra });
}

async function driveBranch3(thisArg, json) {
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => json,
  });
  thisArg.requestId = 1;
  await thisArg.fallbackSearch('FC2-123456', 1);
}

async function driveBranch4(thisArg, resultExtra) {
  const file = { number: 'FC2-123456', searched: false, filename: 'FC2-123456.mp4' };
  const p = thisArg.searchForFile(file, 'first', false);
  emit(lastES(), { type: 'result', success: false, data: [], ...resultExtra });
  await p;
  return file;
}

// 1. 分支 1（SSE 漸進 allFailed）：blocked:true → errorText 是 blocked 文案
test('1 分支1 SSE 漸進 allFailed：blocked:true → errorText 是 blocked 文案', async () => {
  setup();
  const fakeThis = makeFakeThis();
  await driveBranch1(fakeThis, { blocked: true, blocked_sources: ['official'] });
  assert.equal(fakeThis.errorText, BLOCKED_TEXT);
  assert.equal(fakeThis.pageState, 'error');
  assert.notEqual(fakeThis.errorText, NO_DATA);
});

// 2. 分支 1：blocked:false → errorText 逐字等於既有 search.error.no_data 文案
test('2 分支1：blocked:false → errorText 逐字等於「找不到資料」', async () => {
  setup();
  const fakeThis = makeFakeThis();
  await driveBranch1(fakeThis, { blocked: false });
  assert.equal(fakeThis.errorText, NO_DATA);

  setup();
  const omitted = makeFakeThis();
  await driveBranch1(omitted, {});
  assert.equal(omitted.errorText, NO_DATA);
});

// 3. 分支 2（SSE 非漸進空）：同上兩態
test('3 分支2 SSE 非漸進空：blocked true/false 兩態', async () => {
  setup();
  const blockedThis = makeFakeThis();
  await driveBranch2(blockedThis, { blocked: true, blocked_sources: ['official'] });
  assert.equal(blockedThis.errorText, BLOCKED_TEXT);
  assert.notEqual(blockedThis.errorText, NO_DATA);

  setup();
  const notBlocked = makeFakeThis();
  await driveBranch2(notBlocked, { blocked: false });
  assert.equal(notBlocked.errorText, NO_DATA);
});

// 4. 分支 3（REST fallback）：blocked:true 且 data.error 為空 → blocked；data.error 有值 → 仍優先
test('4 分支3 REST fallback：blocked 與 data.error 優先序', async () => {
  setup();
  const blockedThis = makeFakeThis();
  await driveBranch3(blockedThis, { success: false, data: [], blocked: true, error: '' });
  assert.equal(blockedThis.errorText, BLOCKED_TEXT);

  setup();
  const errorFirst = makeFakeThis();
  await driveBranch3(errorFirst, {
    success: false,
    data: [],
    blocked: true,
    error: 'explicit backend error',
  });
  assert.equal(errorFirst.errorText, 'explicit backend error');

  setup();
  const notBlocked = makeFakeThis();
  await driveBranch3(notBlocked, { success: false, data: [], blocked: false, error: '' });
  assert.equal(notBlocked.errorText, NO_DATA);
});

// 5. 分支 4（逐檔搜尋）：blocked:true → coverError 是 blocked 文案；false → 既有 {number} 文案逐字
test('5 分支4 逐檔搜尋：blocked true/false 兩態', async () => {
  setup();
  const blockedThis = makeFakeThis();
  await driveBranch4(blockedThis, { blocked: true, blocked_sources: ['official'] });
  assert.equal(blockedThis.coverError, FILELIST_BLOCKED('FC2-123456'));
  assert.notEqual(blockedThis.coverError, FILELIST_NOT_FOUND('FC2-123456'));

  setup();
  const notBlocked = makeFakeThis();
  await driveBranch4(notBlocked, { blocked: false });
  assert.equal(notBlocked.coverError, FILELIST_NOT_FOUND('FC2-123456'));
});

// 6. blocked:true 且 blocked_sources 缺席 → 不拋錯、仍渲染 blocked 文案
test('6 blocked:true 且 blocked_sources 缺席 → 不拋錯、仍渲染 blocked 文案', async () => {
  setup();
  const b1 = makeFakeThis();
  await assert.doesNotReject(() => driveBranch1(b1, { blocked: true }));
  assert.equal(b1.errorText, BLOCKED_TEXT);
  assert.equal(b1.errorText.includes('undefined'), false);

  setup();
  const b2 = makeFakeThis();
  await assert.doesNotReject(() => driveBranch2(b2, { blocked: true }));
  assert.equal(b2.errorText, BLOCKED_TEXT);
  assert.equal(b2.errorText.includes('undefined'), false);

  setup();
  const b3 = makeFakeThis();
  await assert.doesNotReject(() => driveBranch3(b3, { success: false, data: [], blocked: true }));
  assert.equal(b3.errorText, BLOCKED_TEXT);
  assert.equal(b3.errorText.includes('undefined'), false);

  setup();
  const b4 = makeFakeThis();
  await assert.doesNotReject(() => driveBranch4(b4, { blocked: true }));
  assert.equal(b4.coverError, FILELIST_BLOCKED('FC2-123456'));
  assert.equal(b4.coverError.includes('undefined'), false);
});
