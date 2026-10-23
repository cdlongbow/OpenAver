// 168b-T6b: connectPage() path-map table driven by a fake bridge.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.window = globalThis;
globalThis.document = { addEventListener() {} };
window.t = (key, params) => key + (params ? JSON.stringify(params) : '');
globalThis.setTimeout = () => 1;
window.addEventListener = () => {};
const toasts = [];
globalThis.Alpine = { store: () => ({ show(m, t) { toasts.push([m, t]); } }) };

const { connectPage } = await import('../main.js');
const { rulesForSave } = await import('../connect-logic.js');

const URL_A = 'http://good.test:8765';
const URL_B = 'http://nopin.test:8765';
const okProbe = (over = {}) => ({
    ok: true, reason: null, version: '0.17.10', kind: 'linux',
    auth_required: true, authed: false, compat: { status: 'ok', hint: '' }, url: URL_A, ...over,
});
const SOURCES = [
    { path: '/volume1/av', kind: 'directory', readonly: false, sample: '/volume1/av/a.mp4' },
    { path: '/volume1/fav', kind: 'favorite', readonly: false, sample: null },
];
const SAVED = [{ server: '/volume1/av', local: '\\\\nas\\av' }, { server: '/volume1/gone', local: 'Z:\\gone' }];

function fakeBridge(over = {}, mode = 'local') {
    const calls = [];
    const api = {
        connect_get_state: async () => ({
            mode, url: mode === 'client' ? URL_A : '', host: 'good.test:8765', path_map: SAVED, version: '0.17.7',
        }),
        connect_probe: async (url) => okProbe({ url, authed: mode === 'client' }),
        connect_login: async (url, pin) => (pin === '4827' ? { ok: true, reason: null } : { ok: false, reason: 'bad_pin' }),
        connect_sources: async () => ({ ok: true, reason: null, sources: SOURCES }),
        connect_test_row: async () => ({ state: 'ok' }),
        connect_save_path_map: async () => ({ ok: true, reason: null }),
        connect_apply_restart: async () => ({ ok: true, reason: null }),
        connect_switch_local_restart: async () => ({ ok: true, reason: null }),
        ...over,
    };
    const wrapped = {};
    for (const [name, fn] of Object.entries(api)) {
        wrapped[name] = (...args) => { calls.push([name, ...args]); return fn(...args); };
    }
    return { api: wrapped, calls };
}
const flush = () => new Promise((r) => setImmediate(r));
const of = (calls, name) => calls.filter((c) => c[0] === name);

async function boot(over = {}, mode = 'local') {
    const b = fakeBridge(over, mode);
    window.pywebview = { api: b.api };
    window.__oaBridgeKind = 'server';
    toasts.length = 0;
    const page = connectPage();
    page.$el = { dataset: { mode, shellKind: 'windows' } };
    page.init();
    await flush();
    return { b, page };
}
async function authed(over = {}, mode = 'local') {
    const ctx = await boot(over, mode);
    const { page } = ctx;
    if (mode === 'local') {
        page.urlText = URL_A;
        await page.testConnection();
        page.pin = '4827';
        await page.login();
        await flush();
    }
    return ctx;
}

test('login success loads sources once for the probed url', async () => {
    const { b, page } = await authed();
    assert.deepEqual(of(b.calls, 'connect_sources'), [['connect_sources', URL_A]]);
    assert.equal(page.sourcesState, 'ok');
    assert.equal(page.sourcesFor, URL_A);
    assert.deepEqual(page.rows.map((r) => r.server), ['/volume1/av', '/volume1/fav', '/volume1/gone']);
    assert.equal(page.rows[0].local, '\\\\nas\\av');
    assert.equal(page.rows[2].stale, true);
    await page.testConnection();
    await flush();
    assert.equal(of(b.calls, 'connect_sources').length, 1);
});

test('no sources are requested before the password is confirmed', async () => {
    const { b, page } = await boot();
    page.urlText = URL_A;
    await page.testConnection();
    await flush();
    assert.equal(of(b.calls, 'connect_sources').length, 0);
    assert.equal(page.actions().tableVisible, false);
});


test('sources reply is dropped when the probe moved on', async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const { b, page } = await boot({
        connect_probe: async (url) => okProbe({ url, auth_required: false }),
        connect_sources: async (url) => {
            if (url === URL_A) await gate;
            return { ok: true, reason: null, sources: url === URL_A ? SOURCES : [SOURCES[0]] };
        },
    });
    page.urlText = URL_A;
    const first = page.testConnection();
    await flush();
    page.urlText = URL_B;
    const second = page.testConnection();
    await flush();
    release();
    await Promise.all([first, second]);
    await flush();
    assert.equal(page.sourcesFor, URL_B);
    assert.deepEqual(page.rows.filter((r) => !r.stale).map((r) => r.server), ['/volume1/av']);
    assert.deepEqual(of(b.calls, 'connect_sources').map((c) => c[1]), [URL_A, URL_B]);
});


test('failed sources load errors out and apply sends null', async () => {
    const { b, page } = await authed({ connect_sources: async () => ({ ok: false, reason: 'bad_response', sources: [] }) });
    assert.equal(page.sourcesState, 'error');
    assert.equal(page.actions().canReloadSources, true);
    assert.strictEqual(page.pathMapForApply(), null);
    await page.applyRestart();
    assert.strictEqual(of(b.calls, 'connect_apply_restart')[0][2], null);
});


test('apply sends the loaded rules as the second argument', async () => {
    const { b, page } = await authed();
    await page.applyRestart();
    assert.deepEqual(of(b.calls, 'connect_apply_restart')[0], ['connect_apply_restart', URL_A, rulesForSave(page.rows)]);
    assert.deepEqual(of(b.calls, 'connect_apply_restart')[0][2].map((r) => r.server), ['/volume1/av', '/volume1/gone']);
});

test('removing the stale row drops it from apply', async () => {
    const { b, page } = await authed();
    page.removeStale(page.rows[2]);
    await page.applyRestart();
    assert.deepEqual(of(b.calls, 'connect_apply_restart')[0][2], [{ server: '/volume1/av', local: '\\\\nas\\av' }]);
});

test('testRow passes server, trimmed local and sample', async () => {
    const { b, page } = await authed();
    const row = page.rows[0];
    row.local = '  \\\\nas\\av  ';
    await page.testRow(row);
    assert.deepEqual(of(b.calls, 'connect_test_row'), [['connect_test_row', '/volume1/av', '\\\\nas\\av', '/volume1/av/a.mp4']]);
    assert.equal(row.state, 'ok');
    assert.equal(row.testing, false);
});


test('test_editing_local_path_clears_previous_row_result', async () => {
    const { page } = await authed();
    const row = page.rows[0];
    await page.testRow(row);
    assert.equal(row.state, 'ok');
    row.local = '\\\\nas\\av2';
    page.onLocalInput(row);
    assert.equal(row.state, null);
    assert.equal(page.rowResult(row), 'none');
});


test('save sends rules, toasts once and clears dirty', async () => {
    const { b, page } = await authed({}, 'client');
    assert.equal(page.sourcesState, 'ok');
    assert.equal(page.actions().canSaveRows, false);
    page.rows[1].local = '/Volumes/fav';
    assert.equal(page.actions().canSaveRows, true);
    await page.saveRows();
    assert.deepEqual(of(b.calls, 'connect_save_path_map'), [['connect_save_path_map', [
        { server: '/volume1/av', local: '\\\\nas\\av' },
        { server: '/volume1/fav', local: '/Volumes/fav' },
        { server: '/volume1/gone', local: 'Z:\\gone' },
    ]]]);
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0][1], 'success');
    assert.equal(page.actions().canSaveRows, false);
    assert.equal(page.busy, null);
});


test('save failure toasts an error and stays dirty', async () => {
    const { page } = await authed({ connect_save_path_map: async () => ({ ok: false, reason: 'not_client' }) }, 'client');
    page.rows[1].local = '/Volumes/fav';
    await page.saveRows();
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0][1], 'error');
    assert.equal(page.actions().canSaveRows, true);
});


test('client mode other server: table follows the probe and save stays locked', async () => {
    const { b, page } = await authed({ connect_probe: async (url) => okProbe({ url, authed: true }) }, 'client');
    page.urlText = URL_B;
    await page.testConnection();
    await flush();
    assert.equal(page.sourcesFor, URL_B);
    page.rows[0].local = 'changed';
    assert.equal(page.actions().canSaveRows, false);
    await page.applyRestart();
    assert.deepEqual(of(b.calls, 'connect_apply_restart')[0][1], URL_B);
    assert.equal(of(b.calls, 'connect_apply_restart')[0][2][0].local, 'changed');
});


// window.t 的假函式會 JSON 轉義反斜線，渲染文字測試改用讀 zh_TW.json 的真格式化器
const ZH_ROWS = JSON.parse(readFileSync(new URL('../../../../../../locales/zh_TW.json', import.meta.url), 'utf8')).connect.rows;
async function withRealT(fn) {
    const orig = window.t;
    window.t = (key, params = {}) => {
        const msg = ZH_ROWS[key.replace('connect.rows.', '')];
        return Object.entries(params).reduce((m, [k, v]) => m.replace(`{${k}}`, () => String(v)), msg);
    };
    try { await fn(); } finally { window.t = orig; }
}
const FAIL_PATH = '\\\\nas\\av\\日本\\a.mp4';

test('testRow 失敗時渲染出的文字含實際路徑', async () => {
    const { page } = await authed({ connect_test_row: async () => ({ state: 'not_found', local_path: FAIL_PATH }) });
    const row = page.rows[0];
    await page.testRow(row);
    assert.equal(page.rowResult(row), 'fail');
    await withRealT(() => {
        const text = page.rowFailText(row);
        assert.ok(text.includes(FAIL_PATH));
        assert.equal(text, '這台電腦看不到這個位置：' + FAIL_PATH);
    });
});


