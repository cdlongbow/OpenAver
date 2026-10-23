// TASK-163b-T4a: 測試連線分片行為（fake this 用 mergeState 建，getter 才會活）。

import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

globalThis.window = globalThis;
window.t = (key) => key;

register(
  new URL('../../search/__tests__/alias-loader.mjs', import.meta.url),
  import.meta.url,
);

const { stateSourceProbe } = await import('../state-source-probe.js');
const { mergeState } = await import('@/shared/merge-state.js');

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function makeSources() {
  return [
    { id: 'dmm', type: 'builtin', enabled: true, manual_only: false },
    { id: 'javbus', type: 'builtin', enabled: false, manual_only: false },
    { id: 'javlibrary', type: 'builtin', enabled: false, manual_only: true },
    { id: 'mt-a', type: 'metatube', enabled: true, manual_only: false },
    { id: 'mt-b', type: 'metatube', enabled: false, manual_only: false },
  ];
}

function makeFake(extra = {}) {
  const toasts = [];
  const fake = mergeState({
    form: { proxyUrl: ' http://p:1 ', proxyScope: 'dmm' },
    sources: makeSources(),
    showToast(msg, type) { toasts.push([msg, type]); },
  }, stateSourceProbe());
  Object.assign(fake, extra);
  return { fake, toasts };
}

// 手動控制 resolve 時機的 fetch stub
function deferredFetch() {
  const calls = [];
  globalThis.fetch = (url, init) => {
    return new Promise((resolve, reject) => {
      calls.push({ url, init, resolve, reject });
    });
  };
  const ok = (call, results) => call.resolve({ ok: true, status: 200, json: async () => ({ results }) });
  return { calls, ok };
}
const RES = { dmm: { state: 'ok' }, 'mt-a': { state: 'blocked' } };

test('srcProbeKey changes with proxyUrl, proxyScope, and any pill', () => {
  const { fake } = makeFake();
  const base = fake.srcProbeKey;
  fake.form.proxyUrl = 'http://q:2';
  assert.notEqual(fake.srcProbeKey, base, 'proxyUrl');
  fake.form.proxyUrl = ' http://p:1 ';
  assert.equal(fake.srcProbeKey, base, 'restored');
  fake.form.proxyScope = 'all';
  assert.notEqual(fake.srcProbeKey, base, 'proxyScope');
  fake.form.proxyScope = 'dmm';
  for (const s of fake.sources) {
    s.enabled = !s.enabled;
    assert.notEqual(fake.srcProbeKey, base, `toggle ${s.id}`);
    s.enabled = !s.enabled;
  }
  assert.equal(fake.srcProbeKey, base);
});


test('runSrcProbe sends only lit pills and manual_only pills', async () => {
  const { fake } = makeFake();
  const { calls, ok } = deferredFetch();
  const p = fake.runSrcProbe();
  assert.equal(fake.srcProbeStatus, 'running');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, 'POST');
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual(body.source_ids, ['dmm', 'javlibrary', 'mt-a']);
  assert.equal(body.proxy_url, 'http://p:1');
  assert.equal(body.proxy_scope, 'dmm');
  ok(calls[0], RES);
  await p;
  assert.deepEqual(fake.srcProbeResults, RES);
  assert.equal(fake.srcProbeStatus, 'idle');
  assert.deepEqual(fake.srcProbeSummary, { ok: 1, total: 2 });
});


test('late response after clearSrcProbe is discarded', async () => {
  const { fake, toasts } = makeFake();
  const { calls, ok } = deferredFetch();
  const p = fake.runSrcProbe();
  fake.clearSrcProbe();
  ok(calls[0], RES);
  await p;
  assert.deepEqual(fake.srcProbeResults, {});
  assert.equal(fake.srcProbeStatus, 'idle');
  assert.equal(toasts.length, 0);
});


test('failed request clears results, returns to idle and toasts once', async () => {
  for (const mode of ['reject', 'non2xx', 'noResults']) {
    const { fake, toasts } = makeFake();
    fake.srcProbeResults = { stale: { state: 'ok' } };
    const { calls } = deferredFetch();
    const p = fake.runSrcProbe();
    if (mode === 'reject') calls[0].reject(new Error('net'));
    else if (mode === 'non2xx') calls[0].resolve({ ok: false, status: 500, json: async () => ({}) });
    else calls[0].resolve({ ok: true, status: 200, json: async () => ({}) });
    await p;
    assert.deepEqual(fake.srcProbeResults, {}, mode);
    assert.equal(fake.srcProbeStatus, 'idle', mode);
    assert.deepEqual(toasts, [['settings.sources.probe_failed', 'error']], mode);
  }
});

