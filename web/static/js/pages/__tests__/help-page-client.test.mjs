// 168c-T5: helpPage 在桌面殼 client 模式的選路與 bridge 版四個方法
// 一律假 bridge／假 fetch；絕不碰真的 update_run 或 /api/trigger-update。

import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };
globalThis.t = (key) => key;
globalThis.document.querySelector = () => null;
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};

const { helpPage } = await import('../help.js');

function installFetchSpy() {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', headers: opts.headers });
    return { ok: true, json: async () => ({ success: true, has_update: false, version: '0.0.1' }) };
  };
  return calls;
}

// replies: { name: reply | fn }；缺的 name 不放進 api（模擬舊殼）
function installBridge(replies, { ready = true } = {}) {
  const log = [];
  const api = {};
  for (const [name, reply] of Object.entries(replies)) {
    api[name] = async (...args) => {
      log.push({ name, args });
      return typeof reply === 'function' ? reply(...args) : reply;
    };
  }
  globalThis.pywebview = { api };
  globalThis.__oaBridgeKind = ready ? 'server' : undefined;
  return log;
}

const OK_REPLIES = () => ({
  update_check: { ok: true, reason: null, has_update: true, current_version: '0.17.7', latest_version: '9.9.9', download_url: 'https://x/dl' },
  update_context: { ok: true, is_default_path: true, current_version: '0.17.7' },
  update_run: { ok: true, reason: null },
  local_settings_get: { ok: true, auto_check_update: false },
  local_settings_save: { ok: true },
});

function makeFakeThis(dataset) {
  const toasts = [];
  const self = {
    ...helpPage(),
    $el: { dataset },
    showToast(msg, type) { toasts.push([msg, type]); },
  };
  self.toasts = toasts;
  return self;
}

async function boot(dataset) {
  const self = makeFakeThis(dataset);
  self.init();
  await self._routingReady;
  await self._clientInitDone;
  return self;
}

const CLIENT = { isDesktop: 'true', autoCheckUpdate: 'false', shellMode: 'client' };
const hit = (calls, url) => calls.filter((c) => c.url === url).length;

test('client mode with an old shell missing update_check routes to server endpoints', async () => {
  const calls = installFetchSpy();
  const replies = OK_REPLIES();
  delete replies.update_check;
  const log = installBridge(replies);
  const self = await boot(CLIENT);
  assert.equal(self._bridgeMode, false);
  await self.checkUpdate();
  assert.equal(hit(calls, '/api/check-update'), 1);
  assert.equal(log.length, 0, 'bridge 零呼叫');
  assert.equal(self.errorMsg, '');
  assert.equal(hit(calls, '/api/version'), 1, '舊殼退回 loadVersion');
});

test('client mode whose bridge never becomes ready falls back to server endpoints', async () => {
  const calls = installFetchSpy();
  const log = installBridge(OK_REPLIES(), { ready: false });
  // whenBridgeReady 預設 3 秒逾時：加速它
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms, ...a) => realSetTimeout(fn, ms === 3000 ? 5 : ms, ...a);
  try {
    const self = await boot({ ...CLIENT, autoCheckUpdate: 'true' });
    assert.equal(self._bridgeMode, false);
    assert.equal(log.length, 0);
    assert.equal(hit(calls, '/api/version'), 1);
    assert.equal(hit(calls, '/api/check-update'), 1, 'SSR 值判斷的自動檢查');
  } finally {
    globalThis.setTimeout = realSetTimeout;
  }
});

test('client mode with a full bridge uses bridge for version, setting, check, context and run', async () => {
  const calls = installFetchSpy();
  const log = installBridge(OK_REPLIES());
  const self = await boot({ ...CLIENT, autoCheckUpdate: 'true' });
  assert.equal(self._bridgeMode, true);
  assert.equal(self.appVersion, 'v0.17.7');
  assert.equal(self.autoCheckUpdate, false, '用 local_settings_get，不用 SSR 值');
  assert.equal(log.some((l) => l.name === 'update_check'), false, '本機設定關 → 不自動檢查');

  await self.checkUpdate();
  assert.deepEqual([self.hasUpdate, self.latestVersion, self.downloadUrl], [true, '9.9.9', 'https://x/dl']);
  assert.equal(self.checkDone, true);
  assert.equal(self.checkUpdateLoading, false);

  await self.triggerUpdate();
  assert.equal(self.showUpdateModal, true);
  assert.equal(self.isDefaultPath, true);

  await self.confirmUpdate();
  assert.equal(log.filter((l) => l.name === 'update_run').length, 1);
  assert.equal(self.showUpdateModal, false);
  assert.equal(self.updateLoading, false);
  assert.deepEqual(self.toasts, [['help.update_modal.toast_success', 'info']]);

  assert.deepEqual(calls.map((c) => c.url), [], '零伺服器端點（含 /api/trigger-update）');
});

test('client mode with bridge auto-checks via update_check when local setting is on', async () => {
  const calls = installFetchSpy();
  const replies = OK_REPLIES();
  replies.local_settings_get = { ok: true, auto_check_update: true };
  const log = installBridge(replies);
  await boot({ ...CLIENT, autoCheckUpdate: 'false' });
  await new Promise((r) => setImmediate(r));
  assert.equal(log.filter((l) => l.name === 'update_check').length, 1);
  assert.equal(calls.length, 0);
});

// update_check 任一失敗形狀 → errorMsg 恆為 check_update_failed
for (const [label, reply] of [
  ['timeout', { ok: false, reason: 'timeout' }],
  ['network', { ok: false, reason: 'network' }],
  ['not_client', { ok: false, reason: 'not_client' }],
  ['ok with reason', { ok: true, reason: 'bad_response' }],
  ['throws', () => { throw new Error('boom'); }],
]) {
  test(`client bridge update_check failure (${label}) shows the single failure message`, async () => {
    installFetchSpy();
    const replies = OK_REPLIES();
    replies.update_check = reply;
    installBridge(replies);
    const self = await boot(CLIENT);
    await self.checkUpdate();
    assert.equal(self.errorMsg, 'help.js.check_update_failed');
    assert.equal(self.checkDone, true);
    assert.equal(self.checkUpdateLoading, false);
    assert.equal(self.hasUpdate, false);
  });
}

test('client bridge update_run ok:false toasts error and still closes the modal', async () => {
  installFetchSpy();
  const replies = OK_REPLIES();
  replies.update_run = { ok: false, reason: 'launch_failed' };
  installBridge(replies);
  const self = await boot(CLIENT);
  self.showUpdateModal = true;
  await self.confirmUpdate();
  assert.deepEqual(self.toasts, [['help.update_modal.toast_error', 'info']]);
  assert.equal(self.showUpdateModal, false);
  assert.equal(self.updateLoading, false);
});

test('client bridge update_context failure defaults to the default-path modal', async () => {
  installFetchSpy();
  const replies = OK_REPLIES();
  replies.update_context = { ok: false, reason: 'not_client' };
  installBridge(replies);
  const self = await boot(CLIENT);
  self.isDefaultPath = false;
  await self.triggerUpdate();
  assert.equal(self.isDefaultPath, true);
  assert.equal(self.showUpdateModal, true);
});

test('client bridge local_settings_save failure reverts autoCheckUpdate and toasts', async () => {
  const calls = installFetchSpy();
  const replies = OK_REPLIES();
  replies.local_settings_save = { ok: false, reason: 'write_failed' };
  const log = installBridge(replies);
  const self = await boot(CLIENT);
  self.autoCheckUpdate = true; // x-model 已翻
  await self.saveAutoCheckUpdate();
  assert.equal(self.autoCheckUpdate, false);
  assert.equal(self._autoCheckSaving, false);
  assert.deepEqual(self.toasts, [['help.hero.auto_check_save_failed', 'error']]);
  assert.deepEqual(log.find((l) => l.name === 'local_settings_save').args, [{ auto_check_update: true }]);
  assert.equal(calls.length, 0, '零 PUT /api/config');
});

test('client bridge local_settings_save success keeps the toggle', async () => {
  installFetchSpy();
  installBridge(OK_REPLIES());
  const self = await boot(CLIENT);
  self.autoCheckUpdate = true;
  await self.saveAutoCheckUpdate();
  assert.equal(self.autoCheckUpdate, true);
  assert.deepEqual(self.toasts, []);
});

test('client mode click before routing is decided waits instead of hitting the server', async () => {
  const calls = installFetchSpy();
  const log = installBridge(OK_REPLIES());
  const self = makeFakeThis(CLIENT);
  self.init();
  const p = self.checkUpdate(); // 選路尚未決定
  assert.equal(calls.length, 0, '決定前不得打 /api/check-update');
  await p;
  assert.equal(calls.length, 0);
  assert.equal(log.filter((l) => l.name === 'update_check').length, 1);
  assert.equal(self.hasUpdate, true);
});

// 非 client：bridge 零呼叫、原端點
for (const shellMode of [undefined, '', 'local', 'evil']) {
  test(`non-client shellMode ${JSON.stringify(shellMode)} keeps server endpoints and never touches the bridge`, async () => {
    const calls = installFetchSpy();
    const log = installBridge(OK_REPLIES());
    const ds = { isDesktop: 'true', autoCheckUpdate: 'false' };
    if (shellMode !== undefined) ds.shellMode = shellMode;
    const self = makeFakeThis(ds);
    self.init();
    assert.equal(hit(calls, '/api/version'), 1, 'init 同步返回時 /api/version 已記錄');
    await self.checkUpdate();
    await self.triggerUpdate();
    await self.confirmUpdate();
    self.autoCheckUpdate = true;
    await self.saveAutoCheckUpdate();
    assert.equal(log.length, 0);
    assert.equal(hit(calls, '/api/check-update'), 1);
    assert.equal(hit(calls, '/api/install-context'), 1);
    const trig = calls.find((c) => c.url === '/api/trigger-update');
    assert.equal(trig.headers['X-OpenAver-Desktop-Action'], 'trigger-update');
    const put = calls.find((c) => c.url === '/api/config/general/auto_check_update');
    assert.equal(put.method, 'PUT');
  });
}

// ── 第二輪：init 的 local_settings_get 還沒回來時使用者切換開關 ──
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

for (const [label, ssr, userValue, expectAutoCheck] of [
  ['user turns it off', 'true', false, 0],
  ['user turns it on', 'false', true, 0],
]) {
  test(`client bridge: toggling auto-check while local_settings_get is pending keeps the user's value (${label})`, async () => {
    const calls = installFetchSpy();
    const gate = deferred();
    const replies = OK_REPLIES();
    replies.local_settings_get = () => gate.promise; // 回的值＝SSR 值（舊值）
    const log = installBridge(replies);
    const self = makeFakeThis({ ...CLIENT, autoCheckUpdate: ssr });
    self.init();
    await self._routingReady;
    await new Promise((r) => setImmediate(r)); // 讓 init 走到 local_settings_get 等待處
    self.autoCheckUpdate = userValue; // x-model 已翻
    const saving = self.saveAutoCheckUpdate();
    assert.equal(self._autoCheckSaving, true, '第一個 await 之前就上鎖');
    gate.resolve({ ok: true, auto_check_update: ssr === 'true' });
    await saving;
    await self._clientInitDone;
    await new Promise((r) => setImmediate(r));
    assert.equal(self.autoCheckUpdate, userValue, '初始化舊回覆不得蓋掉使用者的值');
    const saves = log.filter((l) => l.name === 'local_settings_save');
    assert.equal(saves.length, 1);
    assert.deepEqual(saves[0].args, [{ auto_check_update: userValue }]);
    assert.equal(log.filter((l) => l.name === 'update_check').length, expectAutoCheck);
    assert.equal(self._autoCheckSaving, false);
    assert.equal(calls.length, 0);
  });
}

test('client bridge: update_context failure shows the unknown state, never the server version', async () => {
  const calls = installFetchSpy();
  const replies = OK_REPLIES();
  replies.update_context = { ok: false, reason: 'not_client' };
  installBridge(replies);
  const self = await boot(CLIENT);
  assert.equal(self._bridgeMode, true);
  assert.equal(self.appVersion, 'help.js.version_load_failed');
  assert.equal(hit(calls, '/api/version'), 0);
});

test('client bridge: update_context reply without current_version also shows the unknown state', async () => {
  const calls = installFetchSpy();
  const replies = OK_REPLIES();
  replies.update_context = { ok: true, is_default_path: true };
  installBridge(replies);
  const self = await boot(CLIENT);
  assert.equal(self.appVersion, 'help.js.version_load_failed');
  assert.equal(hit(calls, '/api/version'), 0);
});
