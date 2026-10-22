// TASK-165-T9: 設定頁自訂來源獨立元件（customSources）行為。
// 不經 Alpine：直接呼叫 factory，fetch 用可手動 resolve 的 stub。

import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { customSources } = await import('../state-custom-sources.js');

const realFetch = globalThis.fetch;
const live = [];
afterEach(() => {
  globalThis.fetch = realFetch;
  while (live.length) live.pop().destroy();
});

const tick = () => new Promise((r) => setTimeout(r, 0));

function make() {
  const c = customSources();
  live.push(c);
  return c;
}

function entry(id, status, extra = {}) {
  return {
    id, source_id: `custom:${id}`, name: id.toUpperCase(), status,
    enabled: false, verified_at: null, last_result: null, load_error: null, ...extra,
  };
}

function resp(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

// 手動 resolve 的 fetch stub
function deferredFetch() {
  const calls = [];
  globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
    calls.push({ url, init, resolve, reject });
  });
  return calls;
}

// 依 URL 回覆固定內容的 fetch stub
function routedFetch(routes) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    const key = `${(init && init.method) || 'GET'} ${url}`;
    const r = routes[key];
    return typeof r === 'function' ? r() : r;
  };
  return calls;
}


test('polling starts only while a source is verifying and stops when none is', async () => {
  const bodies = [
    { success: true, sources: [entry('a', 'verifying')] },
    { success: true, sources: [entry('a', 'passed')] },
  ];
  const c = make();
  routedFetch({ 'GET /api/custom-sources': () => resp(bodies.shift()) });
  await c.customSrcRefresh();
  assert.notEqual(c.customSrcPollTimer, null, 'verifying → timer');
  await c.customSrcRefresh();
  assert.equal(c.customSrcPollTimer, null, 'no verifying → timer cleared');

  const c2 = make();
  routedFetch({ 'GET /api/custom-sources': () => resp({ success: true, sources: [entry('a', 'passed'), entry('b', 'unverified')] }) });
  await c2.customSrcRefresh();
  assert.equal(c2.customSrcPollTimer, null, 'never verifying → never a timer');
});


test('toggle on a passed source POSTs the flipped enabled with the bare id, then swaps the list', async () => {
  const c = make();
  c.customSrcList = [entry('p', 'passed', { enabled: false })];
  const calls = routedFetch({
    'POST /api/custom-sources/p/enabled': resp({ success: true }),
    'GET /api/custom-sources': resp({ success: true, sources: [entry('p', 'passed', { enabled: true })] }),
  });
  await c.customSrcToggle('p');
  assert.equal(calls[0].url, '/api/custom-sources/p/enabled');
  assert.deepEqual(JSON.parse(calls[0].init.body), { enabled: true });
  assert.equal(c.customSrcList[0].enabled, true);
  assert.equal(c.customSrcOpenId, null);
});


test('remove: open → confirm sends DELETE with bare id, closes, swaps list', async () => {
  const c = make();
  c.customSrcList = [entry('x', 'failed')];
  c.customSrcOpenId = 'x';
  c.customSrcOpenRemove('x');
  assert.equal(c.customSrcRemoveId, 'x');
  const calls = routedFetch({
    'DELETE /api/custom-sources/x': resp({ success: true }),
    'GET /api/custom-sources': resp({ success: true, sources: [] }),
  });
  await c.customSrcConfirmRemove();
  assert.equal(calls[0].url, '/api/custom-sources/x');
  assert.equal(c.customSrcRemoveId, null);
  assert.equal(c.customSrcOpenId, null);
  assert.deepEqual(c.customSrcList, []);
  c.customSrcOpenRemove('x');
  c.customSrcCloseRemove();
  assert.equal(c.customSrcRemoveId, null);
});


