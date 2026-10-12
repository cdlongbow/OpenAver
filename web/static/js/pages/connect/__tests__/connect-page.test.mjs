// 168b-T6a: connectPage() driven by a fake bridge, plus template binding contract.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const captured = {};
globalThis.window = globalThis;
globalThis.document = { addEventListener(type, cb) { captured[type] = cb; } };
window.t = (key, params) => key + (params ? JSON.stringify(params) : '');

const timers = [];
globalThis.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
const winListeners = [];
window.addEventListener = (type, fn) => { winListeners.push({ type, fn }); };

const { connectPage } = await import('../main.js');

const URL_A = 'http://good.test:8765';
const okProbe = (over = {}) => ({
    ok: true, reason: null, version: '0.17.10', kind: 'linux',
    auth_required: true, authed: false, compat: { status: 'ok', hint: '' }, url: URL_A, ...over,
});

function fakeBridge(over = {}) {
    const calls = [];
    const api = {
        connect_get_state: async () => ({ mode: 'local', url: '', host: '', has_token: false, path_map: [], version: '0.17.7', last_ok: null }),
        connect_probe: async () => okProbe(),
        connect_login: async (url, pin) => (pin === '4827' ? { ok: true, reason: null } : { ok: false, reason: 'bad_pin' }),
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
function install(bridge) {
    window.pywebview = bridge ? { api: bridge.api } : undefined;
    window.__oaBridgeKind = bridge ? 'server' : undefined;
}
function fireReady(type = 'oabridgeready') {
    for (const l of winListeners.filter((x) => x.type === type)) l.fn();
}
function mkPage(mode = 'local', shellKind = 'windows') {
    const page = connectPage();
    page.$el = { dataset: { mode, shellKind } };
    return page;
}
const stateOf = (calls, name) => calls.filter((c) => c[0] === name);

test('local mode init reads bridge state', async () => {
    const b = fakeBridge(); install(b);
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
    assert.equal(page.mode, 'local');
    assert.equal(page.localVersion, '0.17.7');
    assert.equal(stateOf(b.calls, 'connect_probe').length, 0);
    assert.equal(page.actions().canApply, false);
});

test('client mode init auto-probes the saved url', async () => {
    const b = fakeBridge({
        connect_get_state: async () => ({ mode: 'client', url: URL_A, host: 'good.test:8765', has_token: true, path_map: [], version: '0.17.10', last_ok: '2026-10-13T08:00:00+00:00' }),
        connect_probe: async () => okProbe({ authed: true }),
    });
    install(b);
    const page = mkPage('client');
    page.init();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
    assert.equal(page.urlText, URL_A);
    assert.deepEqual(stateOf(b.calls, 'connect_probe'), [['connect_probe', URL_A]]);
    assert.equal(page.savedReach, 'ok');
    assert.match(page.statusLine(), /connect\.status_connected/);
    assert.match(page.lastOkText(), /connect\.last_ok/);
    assert.equal(page.actions().canApply, false);
    assert.equal(page.actions().canSwitchLocal, true);
});

test('client mode with an unreachable saved url still allows switching back', async () => {
    const b = fakeBridge({
        connect_get_state: async () => ({ mode: 'client', url: URL_A, host: 'good.test:8765', version: '0.17.10' }),
        connect_probe: async () => ({ ok: false, reason: 'unreachable', version: '', kind: '', compat: { status: 'unparseable', hint: '' }, url: '' }),
    });
    install(b);
    const page = mkPage('client');
    page.init();
    await new Promise((r) => setImmediate(r));
    assert.match(page.statusLine(), /connect\.status_down/);
    assert.equal(page.actions().canSwitchLocal, true);
    assert.equal(page.lastOkText(), '');
});

test('last_ok missing or broken renders no line', async () => {
    for (const bad of [undefined, null, '', 'not-a-date', 42]) {
        const b = fakeBridge({
            connect_get_state: async () => ({ mode: 'client', url: URL_A, host: 'h', version: '0.17.10', last_ok: bad }),
        });
        install(b);
        const page = mkPage('client');
        page.init();
        await new Promise((r) => setImmediate(r));
        assert.equal(page.lastOkText(), '', String(bad));
    }
});

test('bridge arrives via event before the deadline', async () => {
    timers.length = 0; winListeners.length = 0;
    install(undefined);
    const page = mkPage('local');
    page.init();
    assert.equal(page.bridge, 'pending');
    assert.equal(timers.length, 1);
    assert.equal(timers[0].ms, 8000);
    assert.ok(winListeners.some((l) => l.type === 'oabridgeready'));
    install(fakeBridge());
    fireReady();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
    timers[0].fn();
    assert.equal(page.bridge, 'ready');
});

test('bridge arrives via event after the deadline still recovers', async () => {
    timers.length = 0; winListeners.length = 0;
    install(undefined);
    const page = mkPage('local');
    page.init();
    timers[0].fn();
    assert.equal(page.bridge, 'unavailable');
    install(fakeBridge());
    fireReady();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
});

test('missing mode in the state reply means unavailable', async () => {
    for (const reply of [{}, null]) {
        install(fakeBridge({ connect_get_state: async () => reply }));
        const page = mkPage('local');
        page.init();
        await new Promise((r) => setImmediate(r));
        assert.equal(page.bridge, 'unavailable');
        const a = page.actions();
        assert.equal(a.canProbe || a.canApply || a.canLogin || a.canSwitchLocal, false);
    }
});

test('untrusted state reply waits for oabridgeready and retries once, then gives up', async () => {
    timers.length = 0; winListeners.length = 0;
    let n = 0;
    const b = fakeBridge({ connect_get_state: async () => (++n === 1 ? { ok: false, reason: 'untrusted' } : { mode: 'local', version: '0.17.7', path_map: [] }) });
    install(b);
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'pending');
    assert.equal(stateOf(b.calls, 'connect_get_state').length, 1);
    fireReady();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
    assert.equal(stateOf(b.calls, 'connect_get_state').length, 2);

    install(fakeBridge({ connect_get_state: async () => ({ ok: false, reason: 'untrusted' }) }));
    const page2 = mkPage('local');
    page2.init();
    await new Promise((r) => setImmediate(r));
    assert.equal(page2.bridge, 'pending');
    fireReady();
    await new Promise((r) => setImmediate(r));
    assert.equal(page2.bridge, 'unavailable');
});

test('shell present but not ready: no bridge call until oabridgeready, no unavailable on deadline', async () => {
    timers.length = 0; winListeners.length = 0;
    const b = fakeBridge();
    window.pywebview = { api: b.api };
    window.__oaBridgeKind = undefined;
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    assert.equal(b.calls.length, 0);
    assert.equal(page.bridge, 'pending');
    timers[0].fn();
    assert.equal(page.bridge, 'pending');
    fireReady();
    await new Promise((r) => setImmediate(r));
    assert.equal(page.bridge, 'ready');
    assert.equal(stateOf(b.calls, 'connect_get_state').length, 1);
});

test('untrusted reply on a later call flips the bridge to unavailable', async () => {
    const b = fakeBridge({ connect_probe: async () => ({ ok: false, reason: 'untrusted' }) });
    install(b);
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    page.urlText = ' ' + URL_A + ' ';
    await page.testConnection();
    assert.equal(page.bridge, 'unavailable');
    assert.equal(page.probe, null);
});

test('testConnection sends trimmed text; login and apply send canonical probe.url', async () => {
    const b = fakeBridge({ connect_probe: async () => okProbe({ url: 'http://good.test:8765' }) });
    install(b);
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    page.urlText = '  good.test:8765  ';
    await page.testConnection();
    assert.deepEqual(stateOf(b.calls, 'connect_probe'), [['connect_probe', 'good.test:8765']]);
    page.pin = '4827';
    await page.login();
    assert.deepEqual(stateOf(b.calls, 'connect_login'), [['connect_login', URL_A, '4827']]);
    await page.applyRestart();
    assert.deepEqual(stateOf(b.calls, 'connect_apply_restart'), [['connect_apply_restart', URL_A, null]]);
});

async function readyLocalWithProbe(over) {
    const b = fakeBridge(over); install(b);
    const page = mkPage('local');
    page.init();
    await new Promise((r) => setImmediate(r));
    page.urlText = URL_A;
    await page.testConnection();
    return { b, page };
}

test('test_login_failure_keeps_apply_locked', async () => {
    const { page } = await readyLocalWithProbe();
    page.pin = '0000';
    await page.login();
    assert.notEqual(page.phase, 'authed');
    assert.equal(page.actions().canApply, false);
    assert.match(page.pinErrorText(), /connect\.pin_bad/);
    page.pin = '4827';
    await page.login();
    assert.equal(page.phase, 'authed');
    assert.equal(page.actions().canApply, true);
    assert.equal(page.pinErrorText(), '');
});

test('test_pin_not_retained_after_login', async () => {
    const { page } = await readyLocalWithProbe();
    for (const pin of ['0000', '4827']) {
        page.pin = pin;
        await page.login();
        assert.equal(page.pin, '');
        assert.equal(JSON.stringify(page).includes(pin), false);
    }
});

test('apply success locks into restarting and calls the bridge exactly once', async () => {
    const { b, page } = await readyLocalWithProbe({ connect_probe: async () => okProbe({ auth_required: false }) });
    assert.equal(page.actions().canApply, true);
    await Promise.all([page.applyRestart(), page.applyRestart()]);
    await page.applyRestart();
    assert.equal(stateOf(b.calls, 'connect_apply_restart').length, 1);
    assert.equal(page.restarting, true);
    assert.equal(page.actions().canApply, false);
    assert.equal(page.actions().canProbe, false);
});

test('apply failure sets actionError and unlocks', async () => {
    const { page } = await readyLocalWithProbe({
        connect_probe: async () => okProbe({ auth_required: false }),
        connect_apply_restart: async () => ({ ok: false, reason: 'incompatible' }),
    });
    await page.applyRestart();
    assert.equal(page.restarting, false);
    assert.equal(page.busy, null);
    assert.notEqual(page.actionError, '');
    assert.match(page.actionErrorText(), /connect\.error_generic/);
    assert.equal(page.actions().canApply, true);
});

test('switchLocal calls connect_switch_local_restart and locks', async () => {
    const b = fakeBridge({
        connect_get_state: async () => ({ mode: 'client', url: URL_A, host: 'h', version: '0.17.10' }),
    });
    install(b);
    const page = mkPage('client');
    page.init();
    await new Promise((r) => setImmediate(r));
    await page.switchLocal();
    assert.equal(stateOf(b.calls, 'connect_switch_local_restart').length, 1);
    assert.equal(page.restarting, true);
});

test('pathMapForApply is null in T6a and applyRestart goes through it', async () => {
    const { b, page } = await readyLocalWithProbe({ connect_probe: async () => okProbe({ auth_required: false }) });
    assert.equal(page.pathMapForApply(), null);
    page.pathMapForApply = () => [{ server: '/a', local: 'D:/a' }];
    await page.applyRestart();
    assert.deepEqual(stateOf(b.calls, 'connect_apply_restart')[0][2], [{ server: '/a', local: 'D:/a' }]);
});

// ---------- template contract ----------
const html = readFileSync(new URL('../../../../../templates/connect.html', import.meta.url), 'utf8');

const ALLOWED = new Set(['window', 'true', 'false', 'null', 'undefined', '$el', '$refs', '$nextTick',
    '$event', 'event', 'Object', 'Math', 'JSON', 'Number', 'String', 'typeof', 'in', 'of']);

function templateIdentifiers(src) {
    const stripped = src.replace(/\{#[\s\S]*?#\}/g, '').replace(/\{%[\s\S]*?%\}/g, '').replace(/\{\{[\s\S]*?\}\}/g, '');
    const out = new Set();
    const locals = new Set();
    const attrRe = /\s(x-[\w:.-]+|:[\w.:-]+|@[\w.:-]+)="([^"]*)"/g;
    let m;
    while ((m = attrRe.exec(stripped))) {
        const [, name, rawVal] = m;
        if (name === 'x-data') continue;
        const val = rawVal.replace(/'[^']*'|`[^`]*`/g, '""');
        if (name === 'x-for') {
            const fm = /^\s*\(?\s*([\w$]+)\s*(?:,\s*([\w$]+))?\s*\)?\s+in\s+/.exec(val);
            if (fm) { locals.add(fm[1]); if (fm[2]) locals.add(fm[2]); }
        }
        for (const id of val.matchAll(/(?<![.\w$])[A-Za-z_$][\w$]*/g)) out.add(id[0]);
    }
    return [...out].filter((id) => !ALLOWED.has(id) && !locals.has(id));
}

test('test_template_bindings_declared', () => {
    const keys = new Set(Object.keys(connectPage()));
    const used = templateIdentifiers(html);
    assert.ok(used.length > 10, 'template should reference component members');
    const missing = used.filter((id) => !keys.has(id));
    assert.deepEqual(missing, []);
});

test('template has one root x-data and the factory is registered', () => {
    assert.equal(html.split('x-data="connectPage"').length - 1, 1);
    assert.equal(html.split('x-data').length - 1, 1);
    const reg = [];
    globalThis.Alpine = { data(name, fn) { reg.push([name, fn]); } };
    captured['alpine:init']();
    assert.deepEqual(reg.map((r) => r[0]), ['connectPage']);
    assert.equal(reg[0][1], connectPage);
});

test('template exposes the contract ids', () => {
    for (const id of ['connect-nobridge', 'connect-status-card', 'connect-url', 'connect-test-btn',
        'connect-probe-result', 'connect-pin', 'connect-login-btn', 'connect-pin-error', 'connect-forgot',
        'connect-nopassword', 'connect-cf', 'connect-apply-btn', 'connect-switch-local-btn',
        'connect-action-error', 'connect-restarting', 'connect-move-toggle']) {
        assert.ok(html.includes(`id="${id}"`), id);
    }
});
